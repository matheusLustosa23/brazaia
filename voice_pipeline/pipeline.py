"""Orquestração da pipeline de voz — máquina de estados LISTEN ⇄ RESPOND com barge-in.

LISTEN:  a cada `hop`, transcreve o buffer que cresce, estabiliza (LocalAgreement-2), mostra o
         parcial; quando o silêncio fecha o turno (endpoint semântico), manda o texto pro Responder.
RESPOND: consome os deltas do Responder → mostra no terminal E sintetiza por frase → toca (gapless).
         Enquanto fala, vigia o microfone; se o usuário voltar a falar, CORTA o áudio na hora,
         cancela a geração e volta a ouvir (barge-in).

Depende apenas de abstrações injetadas (transcriber, responder, tts, player, transcript), então a
troca de qualquer peça — inclusive o Responder pelo agente (entrega 2) — não mexe aqui.
"""
from __future__ import annotations
import asyncio
import numpy as np

from .vad import SilenceEndpointer, rms
from .stt import Stabilizer
from .tts import clean_for_speech, SentenceChunker


class VoicePipeline:
    def __init__(self, cfg, *, buffer, transcriber, responder, tts, player, transcript):
        self.cfg = cfg
        self.buf = buffer
        self.transcriber = transcriber
        self.responder = responder
        self.tts = tts
        self.player = player
        self.tx = transcript

        self.sr = cfg.audio.sample_rate
        self.stab = Stabilizer()
        self.endpointer = SilenceEndpointer(cfg.vad)
        self.history: list[dict] = []

        self._cancel = asyncio.Event()
        self._resp_task: asyncio.Task | None = None
        self._barged = False          # setado por external_barge() (client cortou o áudio)
        self.quit = False

    # ---------- RESPOND ----------
    async def _respond(self):
        self.tx.agent_start()
        chunker = SentenceChunker(self.cfg.tts.first_chunk_chars)
        reply = ""
        spoke = False
        try:
            async for delta in self.responder.stream(self.history):
                if self._cancel.is_set():
                    break
                reply += delta
                self.tx.agent_delta(delta)
                for sent in chunker.push(delta):
                    if self._cancel.is_set():
                        break
                    spoke = await self._speak(sent) or spoke
            if not self._cancel.is_set():
                spoke = await self._speak(chunker.flush()) or spoke
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.tx.error(f"vLLM: {type(e).__name__}: {e}")
        content = reply.strip()
        if self._cancel.is_set() and content:
            content += " …(interrompido)"
        if content:
            self.history.append({"role": "assistant", "content": content})
        if self._cancel.is_set():
            self.tx.interrupted()
        else:
            self.tx.agent_final()

    async def _speak(self, text: str) -> bool:
        fala = clean_for_speech(text)
        if not fala:
            return False
        pcm = await asyncio.to_thread(self.tts.synth, fala)
        if pcm and not self._cancel.is_set():
            self.player.feed(pcm)
            return True
        return False

    async def _stop_response(self):
        self._cancel.set()
        if self._resp_task:
            self._resp_task.cancel()
            try:
                await self._resp_task
            except Exception:
                pass
            self._resp_task = None

    # ---------- LISTEN ----------
    def _transcribe(self, audio: np.ndarray) -> list:
        prompt = " ".join(self.stab.committed[-40:])
        return self.transcriber.transcribe(audio, prompt)

    async def _listen_step(self) -> bool:
        """Um passo de escuta. Retorna True se um turno foi fechado (→ ir pra RESPOND)."""
        await asyncio.sleep(self.cfg.stt.hop_s)
        audio = self.buf.snapshot()
        if len(audio) < self.sr * self.cfg.vad.min_speech_s:
            return False

        onset_win = int(self.sr * self.cfg.vad.onset_window_s)
        if rms(audio, onset_win) < self.cfg.vad.rms_threshold:
            # silêncio: talvez feche o turno
            self.endpointer.update_silence(self.cfg.stt.hop_s)
            if self.stab.has_text():
                if self.endpointer.ended(self.stab.tail_word()):
                    return True
            else:
                # ninguém falou ainda: mantém só o pré-roll pra não comer o início
                self.buf.keep_last(int(self.sr * self.cfg.vad.preroll_s))
            return False

        # tem voz: transcreve e atualiza o parcial
        self.endpointer.reset()
        hyp = await asyncio.to_thread(self._transcribe, audio)
        committed, partial, agreed_end = self.stab.step(hyp)
        if agreed_end > 0.4:                 # já firmamos até aqui: descarta áudio antigo (deriva menos)
            self.buf.drop_front(int((agreed_end - 0.3) * self.sr))
        self.tx.user_partial((committed + " " + partial).strip())
        return False

    # ---------- barge-in (disparado pelo CLIENT) ----------
    async def external_barge(self):
        """O client detecta a fala durante o playback (mic+player lá) e CORTA o áudio local na hora.
        Aqui o server só precisa PARAR a geração/TTS do turno atual."""
        if self._resp_task and not self._resp_task.done():
            self._barged = True
            self._cancel.set()
            await self._stop_response()

    # ---------- loop principal ----------
    async def run(self):
        self.tx.info(f"pronto — STT={self.cfg.stt.engine} · barge_in={self.cfg.barge.enabled} · fale à vontade (Ctrl+C sai)")
        state = "LISTEN"
        self.endpointer.reset()
        while not self.quit:
            if state == "LISTEN":
                try:
                    closed = await self._listen_step()
                except Exception as e:
                    self.tx.error(f"STT: {type(e).__name__}: {e}")
                    await asyncio.sleep(0.5)
                    continue
                if closed:
                    final = self.stab.flush()
                    self.buf.clear()
                    self.endpointer.reset()
                    if final:
                        self.tx.user_final(final)
                        self.history.append({"role": "user", "content": final})
                        self.tx.thinking()
                        self._cancel.clear()
                        self._resp_task = asyncio.create_task(self._respond())
                        state = "RESPOND"
            else:  # RESPOND — barge-in é do CLIENT; aqui só aguardamos o fim (ou o barge externo)
                await asyncio.sleep(self.cfg.barge.poll_s)
                if self._resp_task and self._resp_task.done():
                    if self._barged:                         # client cortou: preserva a fala nova
                        self.buf.keep_last(int(self.sr * 3.0)); self._barged = False
                    else:                                    # terminou normal (o client cuida do áudio tocando)
                        self.buf.clear()
                    self.stab.reset()
                    self.endpointer.reset()
                    state = "LISTEN"

    async def shutdown(self):
        self.quit = True
        await self._stop_response()
