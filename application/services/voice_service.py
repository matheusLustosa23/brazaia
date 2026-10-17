"""Serviço de voz streaming (full-duplex).

VoiceSession = UMA conexão de voz: máquina de estados LISTEN⇄RESPOND + barge-in,
usando os ports (ASR/VAD/TTS) e o orchestrator (o agente). O router injeta os
callbacks de saída (emit = json, send_audio = PCM).

VOICE_STYLE é o estilo de fala (extra_system do orchestrator); mantido aqui porque
os scripts de medição (scripts/medir_*.py) importam dele.
"""
import asyncio
import logging

import numpy as np

from application.services.orchestrator import Orchestrator
from infrastructure.voice.asr import Stabilizer, is_hallucination, collapse_repeats
from infrastructure.voice.vad import Endpointer, rms
from infrastructure.voice.tts import SentenceChunker, para_fala

logger = logging.getLogger(__name__)


VOICE_STYLE = """\
Você está numa conversa por VOZ. O usuário OUVE, não lê. Responda como uma pessoa \
responderia falando — direto e curto.

Regra principal — BREVIDADE:
- Responda em 1 ou 2 frases. Vá direto ao ponto que foi perguntado.
- Dê a resposta primeiro. Não recapitule o histórico, não liste etapas, não explique seu \
raciocínio a menos que peçam.
- Assunto longo → dê só o essencial e ofereça continuar ("quer que eu detalhe?").
- Pergunta curta = resposta curta. Só se estenda com "explica/detalha/passo a passo" explícito.

Tom:
- Coloquial e natural, como falando com um colega. Frases corridas, sem marcações visuais \
(listas, títulos, asteriscos, emojis, markdown).
- Nunca faça meta-comentário sobre formato, voz ou que você está sendo breve.

Exemplos:
P: "Onde a gente parou?"
✓ "Paramos no script do wake word."
✗ "Na última interação fizemos uma análise dos arquivos X e Y, depois editamos o wake.py nas \
linhas tais, commitamos e discutimos o threshold..."

P: "Deu certo o treino?"
✓ "Deu, o modelo ficou pronto. O recall ainda tá baixo, mas dá pra usar."
✗ "O treino concluiu com accuracy 0.80, recall 0.51 e 3.7 falsos positivos por hora..."

Matemática — SEMPRE em linguagem natural falada, NUNCA LaTeX nem símbolos ($, \\frac, \\sqrt, \\lim, ^, _):
- \\frac{a}{b} → "a sobre b"  ·  \\sqrt{x} → "raiz de x"  ·  x^2 → "x ao quadrado"  ·  x^n → "x elevado a n"
- \\lim_{x\\to4} → "o limite de x tendendo a 4"  ·  \\frac{0}{0} → "zero sobre zero"

A fala TERMINA nas palavras. Depois de falar a fórmula por extenso, NÃO a repita em símbolos NEM em LaTeX —
nada de "ou seja, V = I × R", "M = P(1+r)^t", "∫", "x³/3", "²". Quem quer o símbolo, você MOSTRA na tela.
  ✗ "...tensão igual a corrente vezes resistência, ou seja, V = I × R."
  ✓ "...tensão igual a corrente vezes resistência."

Usar ferramenta é AÇÃO, não markup: pra RENDERIZAR/MOSTRAR/ENVIAR/ABRIR/GUARDAR, CHAME a ferramenta certa
(render_math, display_math, display_page, notify, open_image, capture_image, lembrar) — NUNCA escreva o nome
dela nem o LaTeX na fala ("display_math(...)" dito em voz alta é erro).
Pedir pra "renderizar/gerar/mostrar uma fórmula, equação ou exercício" é AÇÃO VISUAL → CHAME render_math
(gera a imagem) ou display_math (abre na tela); não é pra você só falar a conta.
"""


class VoiceSession:
    """UMA conexão de voz (streaming). O router injeta emit (json) e send_audio (PCM)."""

    def __init__(self, settings, asr, vad, tts, orchestrator: Orchestrator,
                 session_id: str, emit, send_audio):
        self.s = settings
        self.asr = asr
        self.vad = vad
        self.tts = tts
        self.orch = orchestrator
        self.sid = session_id
        self.emit = emit
        self.send_audio = send_audio

        self.sr = 16000
        self.buf = np.zeros(0, np.float32)
        self.stab = Stabilizer()
        self.ep = Endpointer(settings)
        self._cancel = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._barged = False
        self.quit = False

    # ── entrada do mic (router → a cada PCM16) ──
    def feed(self, pcm: bytes) -> None:
        a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, a])

    def _is_speech(self, audio: np.ndarray) -> bool:
        if self.vad is not None:
            return self.vad.speech_prob(audio) >= self.s.voice_vad_prob
        return rms(audio, int(self.sr * 0.3)) >= self.s.voice_rms_threshold

    # ── barge-in: o client cortou local e mandou {"barge"}; aqui só cancela a geração ──
    async def external_barge(self) -> None:
        if self._task and not self._task.done():
            self._barged = True
            self._cancel.set()
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):   # CancelledError é BaseException no 3.8+
                pass

    async def _speak(self, text: str) -> None:
        fala = para_fala(text)
        if not fala:
            return
        pcm = await asyncio.to_thread(self.tts.synth, fala)
        if pcm and not self._cancel.is_set():
            await self.send_audio(pcm)

    async def _respond(self, text: str) -> None:
        await self.emit({"type": "reply_start"})
        chunk = SentenceChunker()
        reply = ""
        try:
            async for ev in self.orch.run(session_id=self.sid, user_message=text,
                                          extra_system=VOICE_STYLE):
                if self._cancel.is_set():
                    break
                if not isinstance(ev, str):      # orchestrator pode emitir eventos (dict)
                    continue
                reply += ev
                await self.emit({"type": "reply_delta", "text": ev})
                for frase in chunk.push(ev):
                    if self._cancel.is_set():
                        break
                    await self._speak(frase)
            if not self._cancel.is_set():
                await self._speak(chunk.flush())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self.emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
        await self.emit({"type": "reply_end"})

    async def run(self) -> None:
        state = "LISTEN"
        self.ep.reset()
        await self.emit({"type": "state", "estado": "detectando"})
        while not self.quit:
            if state == "LISTEN":
                await asyncio.sleep(self.s.voice_hop_s)
                audio = self.buf.copy()
                if len(audio) < self.sr * self.s.voice_min_speech_s:
                    continue
                if not self._is_speech(audio):                     # silêncio → endpoint
                    self.ep.add_silence(self.s.voice_hop_s)
                    if self.stab.has_text() and self.ep.ended(self.stab.tail_word()):
                        final = self.stab.flush()
                        self.buf = np.zeros(0, np.float32)
                        self.ep.reset()
                        if final and not is_hallucination(final):
                            await self.emit({"type": "final", "text": final})
                            self._cancel.clear()
                            self._barged = False
                            self._task = asyncio.create_task(self._respond(final))
                            state = "RESPOND"
                    elif not self.stab.has_text():
                        self.buf = self.buf[-int(self.sr * self.s.voice_preroll_s):]   # só pré-roll
                    continue
                self.ep.reset()                                    # tem fala → transcreve
                prompt = " ".join(self.stab.committed[-40:])
                hyp = await asyncio.to_thread(self.asr.transcribe_words, audio, prompt)
                firme, provisorio, fim = self.stab.step(hyp)
                if fim > 0.4:
                    self.buf = self.buf[int((fim - 0.3) * self.sr):]   # drop_front do já-firmado
                await self.emit({"type": "partial",
                                 "text": collapse_repeats((firme + " " + provisorio).strip())})
            else:  # RESPOND
                await asyncio.sleep(0.15)
                if self._task and self._task.done():
                    self.buf = self.buf[-int(self.sr * 3.0):] if self._barged else np.zeros(0, np.float32)
                    self.stab.reset()
                    self.ep.reset()
                    self._barged = False
                    state = "LISTEN"
                    await self.emit({"type": "state", "estado": "detectando"})

    async def shutdown(self) -> None:
        self.quit = True
        await self.external_barge()
