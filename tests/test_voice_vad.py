"""Lógica do adapter VAD (infrastructure/voice/vad.py) — sem modelo."""
from types import SimpleNamespace

import numpy as np

from infrastructure.voice.vad import rms, RmsVAD, Endpointer, CONT_WORDS


def test_rms():
    assert round(rms(np.zeros(5000, np.float32), 4800), 4) == 0.0
    assert round(rms(np.full(5000, 0.5, np.float32), 4800), 3) == 0.5
    assert rms(np.zeros(0, np.float32), 100) == 0.0


def test_rmsvad_threshold():
    vad = RmsVAD(SimpleNamespace(voice_rms_threshold=0.015))
    assert vad.speech_prob(np.full(5000, 0.5, np.float32)) == 1.0
    assert vad.speech_prob(np.full(5000, 0.001, np.float32)) == 0.0


def test_endpointer_palavra_normal():
    ep = Endpointer(SimpleNamespace(voice_end_silence_s=1.2))
    ep.add_silence(1.0)
    assert ep.ended("chance") is False
    ep.add_silence(0.3)                     # total 1.3s >= 1.2
    assert ep.ended("chance") is True


def test_endpointer_reset():
    ep = Endpointer(SimpleNamespace(voice_end_silence_s=1.2))
    ep.add_silence(2.0)
    ep.reset()
    assert ep.ended("chance") is False


def test_endpointer_palavra_continuacao_segura_mais():
    ep = Endpointer(SimpleNamespace(voice_end_silence_s=1.2))
    ep.add_silence(1.2)                     # ainda não: 'de' exige 1.2 * 2.5 = 3.0s
    assert ep.ended("de") is False
    ep.add_silence(1.8)                     # total 3.0s
    assert ep.ended("de") is True


def test_cont_words():
    assert "de" in CONT_WORDS and "para" in CONT_WORDS
    assert "chance" not in CONT_WORDS
