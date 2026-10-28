"""Loop da VoiceSession (application/services/voice_service.py) com mocks — sem modelo.

asyncio_mode = "auto" (pyproject): funções async viram testes direto.
"""
import asyncio
from types import SimpleNamespace

import numpy as np

from domain.voice_contract import Word
from application.services.voice_service import VoiceSession


class FakeVAD:
    def __init__(self):
        self.speaking = True
    def speech_prob(self, audio):
        return 1.0 if self.speaking else 0.0


class FakeASR:
    def __init__(self):
        self.calls = 0
    def transcribe_words(self, audio, prompt=""):
        self.calls += 1
        return [Word("qual", 0.0, 0.5), Word("foi", 0.5, 1.0)]


class FakeTTS:
    def __init__(self):
        self.spoken = []
    def synth(self, texto):
        self.spoken.append(texto)
        return b"\x00\x01" * 20                 # PCM fake não-vazio


class FakeOrch:
    def __init__(self):
        self.ran_with = None
    async def create_session(self):
        return "sess1"
    async def run(self, session_id, user_message, *, extra_system=None, **kw):
        self.ran_with = user_message
        for delta in ["Foi bem. ", "Quer continuar?"]:
            yield delta


def _settings():
    return SimpleNamespace(voice_hop_s=0.01, voice_min_speech_s=0.0, voice_vad_prob=0.5,
                           voice_rms_threshold=0.015, voice_preroll_s=0.1, voice_end_silence_s=0.03)


def _frame(valor, n=400):
    return (np.full(n, valor, np.float32) * 32767).astype(np.int16).tobytes()


async def test_turno_completo_listen_para_respond():
    vad, asr, tts, orch = FakeVAD(), FakeASR(), FakeTTS(), FakeOrch()
    events, audio_out = [], []
    async def emit(o): events.append(o)
    async def send_audio(p): audio_out.append(p)

    sess = VoiceSession(_settings(), asr, vad, tts, orch, "sess1", emit, send_audio)
    task = asyncio.create_task(sess.run())

    vad.speaking = True                         # fala
    for _ in range(3):
        sess.feed(_frame(0.8)); await asyncio.sleep(0.02)
    vad.speaking = False                        # silêncio → dispara endpoint
    for _ in range(3):
        sess.feed(_frame(0.0)); await asyncio.sleep(0.02)
    for _ in range(50):                         # espera fechar o turno e responder
        await asyncio.sleep(0.02)
        if any(e.get("type") == "reply_end" for e in events):
            break
    await sess.shutdown(); task.cancel()
    try:
        await task
    except BaseException:
        pass

    tipos = {e.get("type") for e in events}
    assert asr.calls > 0
    assert "partial" in tipos and "final" in tipos
    assert orch.ran_with and orch.ran_with.strip()
    assert {"reply_start", "reply_delta", "reply_end"} <= tipos
    assert len(tts.spoken) > 0 and len(audio_out) > 0


async def test_barge_cancela_geracao():
    async def noop(*a):
        pass
    sess = VoiceSession(_settings(), FakeASR(), FakeVAD(), FakeTTS(), FakeOrch(), "s", noop, noop)
    sess._task = asyncio.create_task(asyncio.sleep(10))     # "geração" em curso
    await sess.external_barge()
    assert sess._barged
    assert sess._cancel.is_set()
    assert sess._task.cancelled() or sess._task.done()
