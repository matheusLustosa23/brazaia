"""Serviço de voz streaming (full-duplex).

VoiceSession = UMA conexão de voz: máquina de estados LISTEN⇄RESPOND + barge-in,
usando os ports (ASR/VAD/TTS) e o orchestrator (o agente). O router injeta os
callbacks de saída (emit = json, send_audio = PCM).

VOICE_STYLE é o estilo de fala (extra_system do orchestrator); mantido aqui porque
os scripts de medição (scripts/medir_*.py) importam dele.
"""
import asyncio
import logging
import time

import numpy as np

from application.services.orchestrator import Orchestrator
from application.prompts import build_system
from infrastructure.llm.client import no_think_var
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
        self._stt_ms = 0.0          # acumula o tempo de STT do turno em andamento
        self._last_stt_ms = 0.0     # STT do turno que está sendo respondido

    # ── entrada do mic (router → a cada PCM16) ──
    def feed(self, pcm: bytes) -> None:
        a = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, a])

    # ── turno COMPLETO (celular: áudio já fechado, pré-gravado) ──
    async def handle_turn(self, pcm: bytes) -> None:
        """Transcreve o áudio inteiro de uma vez e responde. NÃO usa o loop de streaming/VAD
        (o turno já vem fechado pelo celular; o endpointer incremental é só pro note)."""
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
        _t = time.perf_counter()
        words = await asyncio.to_thread(self.asr.transcribe_words, audio, "")
        self._last_stt_ms = (time.perf_counter() - _t) * 1000
        texto = collapse_repeats(" ".join(w.texto for w in words).strip())
        logger.info("[voz] turno transcrito %r (haluc=%s)", texto, is_hallucination(texto))
        await self.emit({"type": "final", "text": texto})
        if not texto or is_hallucination(texto):
            await self.emit({"type": "reply_end"})          # fecha o turno mesmo sem fala válida
            return
        self._cancel.clear()
        self._barged = False
        await self._respond(texto)

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

    async def _speak(self, text: str) -> float:
        """Sintetiza e envia uma frase. Retorna o tempo de síntese em ms (0 se nada falado)."""
        fala = para_fala(text)
        if not fala:
            return 0.0
        _t = time.perf_counter()
        pcm = await asyncio.to_thread(self.tts.synth, fala)
        dt = (time.perf_counter() - _t) * 1000
        if pcm and not self._cancel.is_set():
            await self.send_audio(pcm)
        return dt

    async def _respond(self, text: str) -> None:
        await self.emit({"type": "reply_start"})
        chunk = SentenceChunker()
        reply = ""
        t0 = time.perf_counter()
        ttft_ms = ttfa_ms = None        # time-to-first-token / time-to-first-audio
        tts_ms = 0.0
        token = no_think_var.set(True)  # desliga o thinking do Qwen3 só neste turno de voz
        try:
            async for ev in self.orch.run_react(session_id=self.sid, user_message=text,
                                                extra_system=build_system("voz")):
                if self._cancel.is_set():
                    break
                if not isinstance(ev, str):      # orchestrator pode emitir eventos (dict)
                    continue
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                reply += ev
                await self.emit({"type": "reply_delta", "text": ev})
                for frase in chunk.push(ev):
                    if self._cancel.is_set():
                        break
                    tts_ms += await self._speak(frase)
                    if ttfa_ms is None:
                        ttfa_ms = (time.perf_counter() - t0) * 1000
            if not self._cancel.is_set():
                dt = await self._speak(chunk.flush())
                tts_ms += dt
                if ttfa_ms is None and dt:
                    ttfa_ms = (time.perf_counter() - t0) * 1000
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("erro gerando resposta de voz")   # traceback no server
            await self.emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            no_think_var.reset(token)
        tempos = {
            "stt_ms": round(self._last_stt_ms),
            "ttft_ms": round(ttft_ms or 0),      # STT→1º token do LLM ("pensar")
            "ttfa_ms": round(ttfa_ms or 0),      # STT→1º áudio (o que o usuário SENTE)
            "tts_ms": round(tts_ms),             # tempo total de síntese
            "resp_ms": round((time.perf_counter() - t0) * 1000),
            "chars": len(reply),
        }
        logger.info("[voz] tempos %s", tempos)
        await self.emit({"type": "timing", **tempos})
        await self.emit({"type": "reply_end"})

    async def run(self) -> None:
        state = "LISTEN"
        self.ep.reset()
        await self.emit({"type": "state", "estado": "detectando"})
        try:
            while not self.quit:
                if state == "LISTEN":
                    await asyncio.sleep(self.s.voice_hop_s)
                    audio = self.buf.copy()
                    if len(audio) < self.sr * self.s.voice_min_speech_s:
                        continue
                    speech = self._is_speech(audio)
                    logger.debug("[voz] LISTEN buf=%.1fs speech=%s sil=%.1f committed=%d",
                                 len(audio) / self.sr, speech, self.ep.silencio, len(self.stab.committed))
                    if not speech:                                 # silêncio → endpoint
                        self.ep.add_silence(self.s.voice_hop_s)
                        if self.stab.has_text() and self.ep.ended(self.stab.tail_word()):
                            final = self.stab.flush()
                            self.buf = np.zeros(0, np.float32)
                            self.ep.reset()
                            logger.info("[voz] FINAL %r (haluc=%s)", final, is_hallucination(final))
                            if final and not is_hallucination(final):
                                await self.emit({"type": "final", "text": final})
                                self._last_stt_ms = self._stt_ms  # STT deste turno
                                self._stt_ms = 0.0
                                self._cancel.clear()
                                self._barged = False
                                self._task = asyncio.create_task(self._respond(final))
                                state = "RESPOND"
                        elif not self.stab.has_text():
                            self.buf = self.buf[-int(self.sr * self.s.voice_preroll_s):]   # só pré-roll
                        continue
                    self.ep.reset()                                # tem fala → transcreve
                    prompt = " ".join(self.stab.committed[-40:])
                    _t = time.perf_counter()
                    hyp = await asyncio.to_thread(self.asr.transcribe_words, audio, prompt)
                    self._stt_ms += (time.perf_counter() - _t) * 1000
                    firme, provisorio, fim = self.stab.step(hyp)
                    if fim > 0.4:
                        self.buf = self.buf[int((fim - 0.3) * self.sr):]   # drop_front do já-firmado
                    firme_c = collapse_repeats(firme.strip())
                    prov_c = collapse_repeats(provisorio.strip())
                    logger.debug("[voz] partial %r ⟨%r⟩", firme_c, prov_c)
                    await self.emit({"type": "partial", "text": (firme_c + " " + prov_c).strip(),
                                     "firme": firme_c, "prov": prov_c})
                else:  # RESPOND
                    await asyncio.sleep(0.15)
                    if self._task and self._task.done():
                        self.buf = self.buf[-int(self.sr * 3.0):] if self._barged else np.zeros(0, np.float32)
                        self.stab.reset()
                        self.ep.reset()
                        self._barged = False
                        state = "LISTEN"
                        await self.emit({"type": "state", "estado": "detectando"})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[voz] run() crashou: %s: %s", type(e).__name__, e)
            try:
                await self.emit({"type": "error", "text": f"[run crashou] {type(e).__name__}: {e}"})
            except Exception:
                pass

    async def shutdown(self) -> None:
        self.quit = True
        await self.external_barge()
