"""Síntese de fala (TTS) local por frase + segmentação de texto.

MÚLTIPLOS ENGINES atrás da mesma interface `Synthesizer.synth(text) -> PCM int16 @ target_sr`,
escolhidos por `TTS_ENGINE` (cada um com import preguiçoso — só instale o que for usar):

  kokoro     — leve, 82M (padrão). PT fraco (English-first).           [já instalado]
  piper      — rápido/leve, vozes PT-BR decentes.                      pip install piper-tts  + baixar voz .onnx
  xtts       — Coqui XTTS-v2, naturalidade ALTA em PT.                 pip install coqui-tts
  chatterbox — Chatterbox Multilingual, qualidade de ponta.           pip install chatterbox-tts

Cada engine sintetiza na sua taxa nativa; aqui resamplamos pra `target_sr` (24k) que o companion toca.
Sem clonagem: usamos as vozes/speakers PRONTOS de cada modelo.
"""
from __future__ import annotations
import os
import re
from typing import Protocol
import numpy as np


# ───────── texto ─────────
_SUP = {"²": " ao quadrado ", "³": " ao cubo ", "⁰": " elevado a zero ",
        "⁴": " elevado a quatro ", "⁵": " elevado a cinco ", "ⁿ": " elevado a n ", "¹": ""}


def mathspeak(t: str) -> str:
    """Converte notação matemática → fala em português (pro TTS não soletrar 'p a b').
    Ex.: 'P(A|B) = P(A ∩ B) / P(B)' → 'P de A dado B igual a P de A interseção B dividido por P de B'."""
    # potências
    t = re.sub(r"\^\s*2\b", " ao quadrado ", t)
    t = re.sub(r"\^\s*3\b", " ao cubo ", t)
    t = re.sub(r"\^\s*([0-9A-Za-z]+)", r" elevado a \1 ", t)
    for k, v in _SUP.items():
        t = t.replace(k, v)
    # fatorial: letra/número isolado + !  ou  )!   (NÃO mexe em exclamação tipo 'Vamos!')
    t = t.replace(")!", ") fatorial ")
    t = re.sub(r"\b([A-Za-z0-9])!", r"\1 fatorial ", t)
    # notação de função/probabilidade: 'P(' → 'P de '  (letra colada no parêntese)
    t = re.sub(r"\b([A-Za-z])\s*\(", r"\1 de ", t)
    # símbolos matemáticos
    t = t.replace("e/ou", "e ou")
    for k, v in {
        "|": " dado ", "∩": " interseção ", "∪": " união ", "∈": " pertence a ",
        "≥": " maior ou igual a ", "≤": " menor ou igual a ", "≠": " diferente de ",
        "≈": " aproximadamente ", "∑": " somatório de ", "Σ": " somatório de ",
        "∞": " infinito ", "√": " raiz quadrada de ", "±": " mais ou menos ",
        "×": " vezes ", "⋅": " vezes ", "·": " vezes ", "÷": " dividido por ", "/": " dividido por ",
    }.items():
        t = t.replace(k, v)
    t = re.sub(r"\s\*\s", " vezes ", t); t = t.replace("*", " vezes ")
    t = re.sub(r"\s=\s", " igual a ", t); t = t.replace("=", " igual a ")
    t = re.sub(r"\s\+\s", " mais ", t)
    t = re.sub(r"\s-\s", " menos ", t)                 # só hífen cercado de espaço (não quebra palavra)
    t = re.sub(r"[()\[\]{}]", " ", t)                   # tira parênteses restantes (grupos) → fala corrida
    return re.sub(r"\s+", " ", t).strip()


def clean_for_speech(t: str) -> str:
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)      # links
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)            # **negrito** (preserva o * solto p/ multiplicação)
    t = re.sub(r"[#>_]+", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+", "", t)
    t = mathspeak(t)                                    # math → fala PT (antes do TTS)
    return re.sub(r"\s+", " ", t).strip()


class SentenceChunker:
    """Acumula deltas do LLM e devolve sentenças completas assim que fecham (TTFA baixo)."""

    def __init__(self, first_chunk_chars: int = 20):
        self.first_chunk_chars = first_chunk_chars
        self._buf = ""
        self._first = True

    def push(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        while True:
            hits = [self._buf.find(c) for c in ".!?…\n" if self._buf.find(c) != -1]
            if hits:
                i = min(hits)
                s = self._buf[:i + 1].strip()
                self._buf = self._buf[i + 1:]
                if s and re.search(r"\w", s):
                    out.append(s)
                continue
            break
        if self._first and not out and len(self._buf) >= self.first_chunk_chars:
            j = max(self._buf.rfind(","), self._buf.rfind(";"), self._buf.rfind(":"))
            if j >= 10:
                s = self._buf[:j + 1].strip()
                self._buf = self._buf[j + 1:]
                if s and re.search(r"\w", s):
                    out.append(s)
        if out:
            self._first = False
        return out

    def flush(self) -> str:
        s = self._buf.strip()
        self._buf = ""
        return s


# ───────── áudio ─────────
def _resolve_torch_device(requested: str) -> str:
    """'auto'/'cuda' → 'cuda' só se o torch enxergar GPU; senão 'cpu'."""
    if requested not in ("auto", "cuda"):
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _resample(a: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Resample linear (upsample de voz é ok). Evita dep extra; p/ produção, trocar por polyphase."""
    if src == dst or a.size == 0:
        return a
    n = int(round(len(a) * dst / src))
    xp = np.linspace(0.0, 1.0, num=len(a), endpoint=False)
    xq = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(xq, xp, a).astype(np.float32)


def _to_pcm16(a: np.ndarray) -> bytes:
    return (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


class Synthesizer(Protocol):
    def synth(self, texto: str) -> bytes: ...


# ───────── engines ─────────
class KokoroTTS:
    """Kokoro PT-BR (pf_dora/pm_alex/pm_santa). Nativo 24k."""

    def __init__(self, cfg, target_sr: int = 24000):
        from kokoro import KPipeline
        device = _resolve_torch_device(cfg.device)
        print(f"[tts] kokoro ({cfg.voice}) @ {device} ...", flush=True)
        self.cfg = cfg; self.target_sr = target_sr; self.native = 24000
        try:
            self.pipe = KPipeline(lang_code=cfg.lang_code, device=device); self.device = device
        except Exception as e:
            print(f"[tts] {device} falhou ({e}); CPU", flush=True)
            self.pipe = KPipeline(lang_code=cfg.lang_code, device="cpu"); self.device = "cpu"
        for _ in self.pipe("ok", cfg.voice, speed=cfg.speed):
            pass

    def synth(self, texto: str) -> bytes:
        chunks = []
        for r in self.pipe(texto, self.cfg.voice, speed=self.cfg.speed):
            a = r.audio
            if a is None:
                continue
            chunks.append(a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a))
        if not chunks:
            return b""
        audio = np.concatenate(chunks).astype(np.float32)
        return _to_pcm16(_resample(audio, self.native, self.target_sr))


class PiperTTS:
    """Piper (onnx). Rápido; vozes PT-BR (ex.: pt_BR-faber-medium, pt_BR-edresson-low)."""

    def __init__(self, cfg, target_sr: int = 24000):
        from piper import PiperVoice
        model = cfg.piper_model or os.getenv("PIPER_MODEL", "")
        if not model:
            raise RuntimeError("PIPER_MODEL não definido — baixe uma voz pt_BR do Piper (.onnx + .onnx.json) "
                               "e aponte PIPER_MODEL=/caminho/pt_BR-faber-medium.onnx")
        print(f"[tts] piper ({os.path.basename(model)}) ...", flush=True)
        use_cuda = _resolve_torch_device(cfg.device) == "cuda"
        try:
            self.voice = PiperVoice.load(model, use_cuda=use_cuda)
        except TypeError:
            self.voice = PiperVoice.load(model)
        self.native = int(getattr(self.voice.config, "sample_rate", 22050))
        self.target_sr = target_sr

    def synth(self, texto: str) -> bytes:
        pcm = bytearray()
        if hasattr(self.voice, "synthesize_stream_raw"):            # piper 0.x
            for chunk in self.voice.synthesize_stream_raw(texto):
                pcm.extend(chunk)
        else:                                                        # piper 1.x (AudioChunk)
            for chunk in self.voice.synthesize(texto):
                pcm.extend(getattr(chunk, "audio_int16_bytes", b"") or bytes(chunk))
        if not pcm:
            return b""
        a = np.frombuffer(bytes(pcm), np.int16).astype(np.float32) / 32768.0
        return _to_pcm16(_resample(a, self.native, self.target_sr))


class XttsTTS:
    """Coqui XTTS-v2 multilíngue. Usa SPEAKER pronto (TTS_SPEAKER). Nativo 24k."""

    def __init__(self, cfg, target_sr: int = 24000):
        os.environ.setdefault("COQUI_TOS_AGREED", "1")              # aceita a licença (modelo baixa 1x)
        from TTS.api import TTS
        device = _resolve_torch_device(cfg.device)
        self.speaker = cfg.speaker or "Ana Florence"
        print(f"[tts] xtts-v2 (speaker={self.speaker}) @ {device} ...", flush=True)
        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self.native = 24000; self.target_sr = target_sr

    def synth(self, texto: str) -> bytes:
        wav = self.tts.tts(text=texto, language="pt", speaker=self.speaker)
        a = np.asarray(wav, dtype=np.float32)
        return _to_pcm16(_resample(a, self.native, self.target_sr))


class ChatterboxTTS:
    """Chatterbox Multilingual. Voz default do modelo (sem clonagem)."""

    def __init__(self, cfg, target_sr: int = 24000):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        device = _resolve_torch_device(cfg.device)
        print(f"[tts] chatterbox-ml @ {device} ...", flush=True)
        self.model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self.native = int(getattr(self.model, "sr", 24000))
        self.target_sr = target_sr

    def synth(self, texto: str) -> bytes:
        wav = self.model.generate(texto, language_id="pt")
        a = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
        a = a.squeeze().astype(np.float32)
        return _to_pcm16(_resample(a, self.native, self.target_sr))


def make_synth(cfg, target_sr: int = 24000) -> Synthesizer:
    eng = (cfg.engine or "kokoro").lower()
    if eng == "piper":      return PiperTTS(cfg, target_sr)
    if eng == "xtts":       return XttsTTS(cfg, target_sr)
    if eng == "chatterbox": return ChatterboxTTS(cfg, target_sr)
    return KokoroTTS(cfg, target_sr)
