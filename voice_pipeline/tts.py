"""Síntese de fala (TTS) local por frase + segmentação de texto.

Kokoro (PT-BR, voz pm_santa) sintetiza frase a frase, de modo que a reprodução começa assim que a
PRIMEIRA sentença fica pronta — sem esperar a resposta inteira (TTFA baixo). O `SentenceChunker`
quebra o fluxo de tokens do LLM em sentenças/cláusulas; `clean_for_speech` tira o que não se fala
(markdown, código, emoji).
"""
from __future__ import annotations
import re
import numpy as np


def clean_for_speech(t: str) -> str:
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[*_#>|]+", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+", "", t)
    return re.sub(r"\s+", " ", t).strip()


class SentenceChunker:
    """Acumula deltas do LLM e devolve sentenças completas assim que fecham.

    O primeiro trecho pode sair numa vírgula/ponto-e-vírgula (first_chunk_chars) pra começar a falar
    mais cedo; os seguintes esperam fim de sentença (. ! ? … quebra de linha)."""

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
                if s and re.search(r"\w", s):      # ignora fragmentos só de pontuação (ex.: "..." → ".")
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


def _resolve_torch_device(requested: str) -> str:
    """'auto'/'cuda' → 'cuda' só se o torch enxergar GPU; senão 'cpu' (não quebra)."""
    if requested not in ("auto", "cuda"):
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


class KokoroTTS:
    """Síntese PT-BR. `synth(texto) -> PCM int16 bytes @ tts_sample_rate`."""

    def __init__(self, cfg, tts_sample_rate: int = 24000):
        from kokoro import KPipeline
        device = _resolve_torch_device(cfg.device)
        print(f"[tts] kokoro ({cfg.voice}) @ {device} ...", flush=True)
        self.cfg = cfg
        self.sr = tts_sample_rate
        try:
            self.pipe = KPipeline(lang_code=cfg.lang_code, device=device); self.device = device
        except Exception as e:                       # cuda pediu mas falhou → CPU (kokoro roda bem na CPU)
            print(f"[tts] {device} falhou ({e}); caindo pra CPU", flush=True)
            self.pipe = KPipeline(lang_code=cfg.lang_code, device="cpu"); self.device = "cpu"
        for _ in self.pipe("ok", cfg.voice):   # aquece (primeira síntese é mais lenta)
            pass

    def synth(self, texto: str) -> bytes:
        chunks = []
        for r in self.pipe(texto, self.cfg.voice):
            a = r.audio
            if a is None:
                continue
            chunks.append(a.detach().cpu().numpy() if hasattr(a, "detach") else a.numpy())
        if not chunks:
            return b""
        return (np.concatenate(chunks) * 32767).astype(np.int16).tobytes()
