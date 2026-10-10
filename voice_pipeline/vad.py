"""Detecção de atividade de voz (VAD) + endpoint (quando a fala começou/terminou).

Abordagem leve e robusta, sem modelo extra de VAD:
  • energia (RMS) sobre uma janela curta → distingue fala de silêncio;
  • endpoint por silêncio acumulado, com um ajuste SEMÂNTICO: se a última palavra reconhecida é de
    continuação ("em", "que", "para"...), espera mais antes de encerrar — evita cortar no meio.

Isso casa com o STT em streaming: o `SilenceEndpointer` recebe o nível e a cauda do texto a cada hop.
"""
from __future__ import annotations
import os
import numpy as np


def rms(audio: np.ndarray, window_samples: int) -> float:
    """RMS dos últimos `window_samples` (0.0 se vazio)."""
    recent = audio[-window_samples:] if window_samples > 0 else audio
    return float(np.sqrt(np.mean(recent ** 2)) + 1e-9) if recent.size else 0.0


class SileroGate:
    """VAD NEURAL (Silero) — separa fala de ruído/silêncio com precisão (bem melhor que RMS).
    Lazy; se não instalar (`pip install silero-vad`) a pipeline cai pro RMS. Roda rápido até na CPU."""

    WIN = 512   # silero exige janelas de 512 amostras @ 16k (32ms)

    def __init__(self, sr: int = 16000):
        import torch
        from silero_vad import load_silero_vad
        self._torch = torch
        self.model = load_silero_vad()
        self.sr = sr

    def speech_prob(self, audio: np.ndarray) -> float:
        """Maior probabilidade de fala nos últimos ~0.5s (0..1)."""
        a = audio[-self.sr // 2:]
        if len(a) < self.WIN:
            return 0.0
        self.model.reset_states()
        probs = []
        for i in range(0, len(a) - self.WIN + 1, self.WIN):
            chunk = self._torch.from_numpy(np.ascontiguousarray(a[i:i + self.WIN], dtype=np.float32))
            probs.append(float(self.model(chunk, self.sr)))
        return max(probs) if probs else 0.0


def make_speech_gate(sr: int = 16000):
    """Retorna um SileroGate se disponível e habilitado (USE_VAD), senão None (→ pipeline usa RMS)."""
    mode = os.getenv("USE_VAD", "auto").lower()
    if mode in ("0", "off", "none", "rms"):
        return None
    try:
        g = SileroGate(sr)
        print("[vad] Silero VAD ativo (fala × ruído neural)", flush=True)
        return g
    except Exception as e:
        print(f"[vad] Silero indisponível ({type(e).__name__}); usando gate RMS. "
              f"Instale com: uv pip install silero-vad", flush=True)
        return None


class SilenceEndpointer:
    """Decide o fim do turno por silêncio, com reforço semântico."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.silence_s = 0.0

    def reset(self):
        self.silence_s = 0.0

    def is_speech(self, audio: np.ndarray, sr: int) -> bool:
        win = int(sr * self.cfg.onset_window_s)
        return rms(audio, win) >= self.cfg.rms_threshold

    def update_silence(self, hop_s: float):
        """Acumula tempo de silêncio (chamado quando o hop foi silencioso)."""
        self.silence_s += hop_s

    def ended(self, tail_word: str) -> bool:
        """True se o silêncio acumulado já basta pra fechar o turno.

        `tail_word` é a última palavra reconhecida (sem pontuação, minúscula); se for palavra de
        continuação, exige mais silêncio (cont_mult)."""
        need = self.cfg.end_silence_s
        if tail_word in self.cfg.cont_words:
            need *= self.cfg.cont_mult
        return self.silence_s >= need
