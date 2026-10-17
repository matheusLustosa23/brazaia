"""Lógica do adapter STT (infrastructure/voice/asr.py) — sem modelo/GPU."""
import sys
from types import SimpleNamespace

from domain.voice_contract import Word
from infrastructure.voice.asr import (
    is_hallucination, collapse_repeats, _remove_coladas, Stabilizer, _resolve_stt,
)


def W(texto, inicio=0.0, fim=0.0):
    return Word(texto, inicio, fim)


# ── is_hallucination ──────────────────────────────────────────────────────────
def test_frase_fantasma_sozinha_e_alucinacao():
    assert is_hallucination("obrigado") is True
    assert is_hallucination("") is True
    assert is_hallucination("tchau valeu") is True


def test_fala_real_nao_e_alucinacao():
    assert is_hallucination("qual a chance") is False
    assert is_hallucination("muito obrigado agora me explica isso") is False


# ── collapse_repeats ──────────────────────────────────────────────────────────
def test_colapsa_bloco_repetido():
    assert collapse_repeats("qual é E aí E aí E aí a chance") == "qual é E aí a chance"
    assert collapse_repeats("você você você entende") == "você entende"
    assert collapse_repeats("mais ou menos mais ou menos mais ou menos isso") == "mais ou menos isso"


def test_nao_colapsa_duas_vezes_nem_texto_normal():
    assert collapse_repeats("E aí E aí") == "E aí E aí"
    assert collapse_repeats("isso é totalmente normal") == "isso é totalmente normal"


def test_remove_coladas():
    assert _remove_coladas(["sim", "sim", "não"]) == ["sim", "não"]
    assert _remove_coladas(["Sim", "sim"]) == ["Sim"]


# ── Stabilizer (LocalAgreement-2) ─────────────────────────────────────────────
def test_firma_so_prefixo_concordante_em_dois_passos():
    s = Stabilizer()
    f, _, _ = s.step([W("qual"), W("a")])
    assert f == ""                              # 1º passo não firma nada
    f, p, _ = s.step([W("qual"), W("a"), W("chance")])
    assert f == "qual a" and p == "chance"


def test_autocorrige_sem_firmar_o_erro():
    s = Stabilizer()
    s.step([W("chance"), W("di")])              # "di" provisório (erro do STT)
    s.step([W("de"), W("dar")])                 # corrige p/ "de" — "di" nunca firma
    assert "di" not in s.committed


def test_desalinhamento_no_comeco_nao_firma_nem_perde():
    s = Stabilizer()
    s.step([W("isso"), W("e"), W("provisorio")])
    f, _, _ = s.step([W("oh"), W("isso"), W("e"), W("provisorio")])
    assert f == ""
    assert [w.texto for w in s.provisorias] == ["oh", "isso", "e", "provisorio"]


def test_divergencia_no_meio_firma_prefixo_mantem_resto():
    s = Stabilizer()
    s.step([W("a"), W("b"), W("c"), W("d")])
    f, _, _ = s.step([W("a"), W("X"), W("c"), W("d")])
    assert f == "a"
    assert [w.texto for w in s.provisorias] == ["X", "c", "d"]


def test_flush_fecha_e_zera():
    s = Stabilizer()
    s.step([W("oi")]); s.step([W("oi")])
    assert s.flush() == "oi"
    assert s.has_text() is False


def test_tail_word():
    s = Stabilizer()
    s.step([W("chance"), W("de")]); s.step([W("chance"), W("de")])
    assert s.tail_word() == "de"


# ── _resolve_stt (modelo/device automáticos pelo hardware) ────────────────────
def _stt(device="auto", model="auto", compute=""):
    return SimpleNamespace(voice_stt_device=device, voice_stt_model=model, voice_stt_compute=compute)


def test_resolve_cpu_auto_vira_small_int8():
    assert _resolve_stt(_stt("cpu", "auto")) == ("small", "cpu", "int8")


def test_resolve_cpu_modelo_fixo_mantem():
    assert _resolve_stt(_stt("cpu", "medium")) == ("medium", "cpu", "int8")


def test_resolve_cpu_large_rebaixa_base():
    assert _resolve_stt(_stt("cpu", "large-v3-turbo")) == ("base", "cpu", "int8")


def test_resolve_gpu_auto_vira_large_turbo(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctranslate2",
                        SimpleNamespace(get_cuda_device_count=lambda: 1))
    assert _resolve_stt(_stt("auto", "auto")) == ("large-v3-turbo", "cuda", "float16")


def test_resolve_gpu_modelo_fixo_mantem(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctranslate2",
                        SimpleNamespace(get_cuda_device_count=lambda: 1))
    assert _resolve_stt(_stt("auto", "small")) == ("small", "cuda", "float16")


def test_resolve_auto_sem_gpu_cai_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctranslate2",
                        SimpleNamespace(get_cuda_device_count=lambda: 0))
    assert _resolve_stt(_stt("auto", "auto")) == ("small", "cpu", "int8")
