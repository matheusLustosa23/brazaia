"""Adapter de TTS (texto -> fala).

Dois mundos convivem aqui:
- `class TTS` (ANTIGO): Kokoro por streaming de tokens (.stream). Mantido p/ compat
  (scripts/gen_greetings.py). Import do kokoro agora é LAZY (voz vira opcional).
- `make_tts` + PiperTTS/KokoroTTS (NOVO): síntese por FRASE (.synth -> PCM int16 @ 24k),
  usada pela VoiceSession streaming. Engines plugáveis por settings.voice_tts_engine.

mathspeak: fala a matemática ("P de A dado B"), rede de segurança além do prompt de voz.
"""
import asyncio
import os
import re
from collections.abc import AsyncIterator

import numpy as np

try:
    from emoji import replace_emoji
except ImportError:
    replace_emoji = None


# ──────────────────────────────────────────────────────────────────────────────
# Limpeza de texto p/ fala
# ──────────────────────────────────────────────────────────────────────────────
def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)      # blocos de código
    text = re.sub(r"`([^`]*)`", r"\1", text)                # `inline`
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)    # [txt](url) -> txt
    text = re.sub(r"[*_#~>]+", " ", text)                   # markdown: * _ # ~ > (| fica p/ P(A|B))
    text = re.sub(r"^\s*[-•·]\s+", "", text, flags=re.M)    # marcadores de lista
    text = replace_emoji(text, "") if replace_emoji else re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+", "", text)  # emojis
    return re.sub(r"\s+", " ", text).strip()


_SUP = {"²": " ao quadrado ", "³": " ao cubo ", "ⁿ": " elevado a n "}

def mathspeak(t: str) -> str:
    """Converte símbolos matemáticos em fala PT ('P(A|B)' -> 'P de A dado B')."""
    t = re.sub(r"\^\s*2\b", " ao quadrado ", t)
    t = re.sub(r"\^\s*3\b", " ao cubo ", t)
    t = re.sub(r"\^\s*([0-9A-Za-z]+)", r" elevado a \1 ", t)
    for k, v in _SUP.items():
        t = t.replace(k, v)
    t = t.replace(")!", ") fatorial ")
    t = re.sub(r"\b([A-Za-z0-9])!", r"\1 fatorial ", t)
    t = re.sub(r"\b([A-Za-z])\s*\(", r"\1 de ", t)          # P( -> "P de "
    t = t.replace("e/ou", "e ou")
    for k, v in {"|": " dado ", "∩": " interseção ", "∪": " união ", "∈": " pertence a ",
                 "≥": " maior ou igual a ", "≤": " menor ou igual a ", "≠": " diferente de ",
                 "√": " raiz quadrada de ", "×": " vezes ", "·": " vezes ", "÷": " dividido por ",
                 "/": " dividido por ", "∞": " infinito ", "Σ": " somatório de "}.items():
        t = t.replace(k, v)
    t = re.sub(r"\s\*\s", " vezes ", t); t = t.replace("*", " vezes ")
    t = re.sub(r"\s=\s", " igual a ", t); t = t.replace("=", " igual a ")
    t = re.sub(r"\s\+\s", " mais ", t); t = re.sub(r"\s-\s", " menos ", t)
    t = re.sub(r"[()\[\]{}]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def para_fala(text: str) -> str:
    """Pipeline de limpeza da VoiceSession: tira markdown e fala a matemática."""
    return mathspeak(clean_for_speech(text))


# ──────────────────────────────────────────────────────────────────────────────
# Chunker por frase (TTFA baixo: sintetiza assim que fecha uma frase)
# ──────────────────────────────────────────────────────────────────────────────
class SentenceChunker:
    def __init__(self, first: int = 20):
        self.first = first
        self.buf = ""
        self._primeira = True

    def push(self, delta: str) -> list[str]:
        self.buf += delta
        out: list[str] = []
        while True:
            hits = [self.buf.find(c) for c in ".!?…\n" if self.buf.find(c) != -1]
            if not hits:
                break
            i = min(hits)
            frase = self.buf[:i + 1].strip()
            self.buf = self.buf[i + 1:]
            if frase and re.search(r"\w", frase):
                out.append(frase)
        if self._primeira and not out and len(self.buf) >= self.first:
            j = max(self.buf.rfind(","), self.buf.rfind(";"), self.buf.rfind(":"))
            if j >= 10:
                frase = self.buf[:j + 1].strip()
                self.buf = self.buf[j + 1:]
                if frase and re.search(r"\w", frase):
                    out.append(frase)
        if out:
            self._primeira = False
        return out

    def flush(self) -> str:
        frase = self.buf.strip()
        self.buf = ""
        return frase


# ──────────────────────────────────────────────────────────────────────────────
# ANTIGO — Kokoro por streaming de tokens (compat: scripts/gen_greetings.py)
# ──────────────────────────────────────────────────────────────────────────────
class TTS:
    """Kokoro 82M na CPU, pt-BR (lang_code='p'). Saída: PCM int16 a 24kHz."""
    SAMPLE_RATE = 24_000

    def __init__(self, voice="pf_dora"):
        from kokoro import KPipeline        # lazy: voz é opcional
        self._pipe = KPipeline(lang_code="p")
        self._voice = voice

    async def stream(self, tokens: AsyncIterator[str]) -> AsyncIterator[bytes]:
        buf = ""
        async for tok in tokens:
            buf += tok
            if buf and buf[-1] in ".!?…\n":
                fala = clean_for_speech(buf)
                if fala and (pcm := await asyncio.to_thread(self._synth, fala)):
                    yield pcm
                buf = ""
        fala = clean_for_speech(buf)
        if fala and buf.split() and (pcm := await asyncio.to_thread(self._synth, fala)):
            yield pcm

    def _synth(self, texto: str) -> bytes | None:
        chunks = [r.audio.numpy() for r in self._pipe(texto, self._voice) if r.audio is not None]
        if not chunks:
            return None
        return (np.concatenate(chunks) * 32767).astype(np.int16).tobytes()


# ──────────────────────────────────────────────────────────────────────────────
# NOVO — síntese por frase (.synth), engines plugáveis
# ──────────────────────────────────────────────────────────────────────────────
def _dev(req: str) -> str:
    if req not in ("auto", "cuda"):
        return req
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def _rs(a: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Resample linear src->dst."""
    if src == dst or a.size == 0:
        return a
    n = int(round(len(a) * dst / src))
    return np.interp(np.linspace(0, 1, n, endpoint=False),
                     np.linspace(0, 1, len(a), endpoint=False), a).astype(np.float32)

def _pcm(a: np.ndarray) -> bytes:
    return (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()


class PiperTTS:
    """Piper (ONNX). Engine campeão. Implementa VoiceTTS (.synth -> PCM int16 @ target)."""
    def __init__(self, settings, target: int = 24_000):
        from piper import PiperVoice   # type: ignore
        self.model = PiperVoice.load(settings.voice_piper_model,
                                     use_cuda=(_dev(settings.voice_tts_device) == "cuda"))
        self.native = int(getattr(self.model.config, "sample_rate", 22050))
        self.target = target

    def synth(self, texto: str) -> bytes:
        pcm = bytearray()
        if hasattr(self.model, "synthesize_stream_raw"):
            for c in self.model.synthesize_stream_raw(texto):
                pcm.extend(c)
        else:
            for c in self.model.synthesize(texto):
                pcm.extend(getattr(c, "audio_int16_bytes", b"") or bytes(c))
        if not pcm:
            return b""
        a = np.frombuffer(bytes(pcm), np.int16).astype(np.float32) / 32768.0
        return _pcm(_rs(a, self.native, self.target))


class KokoroTTS:
    """Kokoro (fallback). Implementa VoiceTTS (.synth -> PCM int16 @ target)."""
    def __init__(self, settings, target: int = 24_000):
        from kokoro import KPipeline
        d = _dev(settings.voice_tts_device)
        try:
            self.p = KPipeline(lang_code="p", device=d)
        except Exception:
            self.p = KPipeline(lang_code="p", device="cpu")
        self.voice = settings.voice_tts_voice
        self.speed = settings.voice_tts_speed
        self.native = 24_000
        self.target = target
        for _ in self.p("ok", self.voice, speed=self.speed):   # warmup
            pass

    def synth(self, texto: str) -> bytes:
        chunks = [(a.detach().cpu().numpy() if hasattr(a, "detach") else np.asarray(a))
                  for r in self.p(texto, self.voice, speed=self.speed)
                  if (a := r.audio) is not None]
        if not chunks:
            return b""
        return _pcm(_rs(np.concatenate(chunks).astype(np.float32), self.native, self.target))


def make_tts(settings, target: int = 24_000):
    """Fábrica: escolhe o engine por settings.voice_tts_engine (default piper -> fallback kokoro)."""
    eng = (settings.voice_tts_engine or "kokoro").lower()
    if eng == "piper":
        if settings.voice_piper_model and os.path.exists(settings.voice_piper_model):
            return PiperTTS(settings, target)
        print("[tts] piper sem modelo -> kokoro", flush=True)
        return KokoroTTS(settings, target)
    return KokoroTTS(settings, target)
