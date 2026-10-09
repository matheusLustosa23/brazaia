"""Detecção de atividade de voz (VAD) + endpoint (quando a fala começou/terminou).

Abordagem leve e robusta, sem modelo extra de VAD:
  • energia (RMS) sobre uma janela curta → distingue fala de silêncio;
  • endpoint por silêncio acumulado, com um ajuste SEMÂNTICO: se a última palavra reconhecida é de
    continuação ("em", "que", "para"...), espera mais antes de encerrar — evita cortar no meio.

Isso casa com o STT em streaming: o `SilenceEndpointer` recebe o nível e a cauda do texto a cada hop.
"""
from __future__ import annotations
import numpy as np


def rms(audio: np.ndarray, window_samples: int) -> float:
    """RMS dos últimos `window_samples` (0.0 se vazio)."""
    recent = audio[-window_samples:] if window_samples > 0 else audio
    return float(np.sqrt(np.mean(recent ** 2)) + 1e-9) if recent.size else 0.0


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
