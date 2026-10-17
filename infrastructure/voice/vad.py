"""Adapter de VAD (detecção de fala) + Endpointer (fim de turno).

Implementa o port VoiceVAD. Dois papéis distintos:
- VAD (SileroVAD/RmsVAD): "tem FALA neste pedaço de áudio?" — separa voz de ruído/silêncio.
- Endpointer: "o turno ACABOU?" — decide pelo tempo de silêncio, com reforço semântico
  (segura mais tempo se a última palavra foi de continuação: 'de', 'para', 'e'...).

Por que VAD neural (Silero) e não só energia (RMS): o RMS cru deixa ruído passar por fala,
e aí o Whisper inventa 'obrigado'/espanhol no silêncio. O Silero corta isso na origem.
"""
from typing import Any
import numpy as np
from domain.voice_contract import VoiceVAD


def rms(audio: np.ndarray, janela: int) -> float:
    """Energia (RMS) dos últimos `janela` samples. Base do fallback por energia."""
    trecho = audio[-janela:] if janela > 0 else audio
    return float(np.sqrt(np.mean(trecho ** 2)) + 1e-9) if trecho.size else 0.0


class SileroVAD:
    """VAD neural (Silero). Implementa VoiceVAD. pip install silero-vad.

    speech_prob = maior probabilidade de fala nos últimos ~0.5s (janelas de 512 @ 16k).
    O import é lazy: o torch/silero só carregam quando o adapter é instanciado.
    """
    WIN = 512   # o silero exige janelas de exatamente 512 amostras @ 16k

    def __init__(self, sr: int = 16000):
        import torch
        from silero_vad import load_silero_vad
        self._torch = torch
        # SileroVADSequence é um modelo torch JIT: o stub não expõe reset_states/__call__
        # (existem em runtime). Any evita falso-positivo do Pylance sem mascarar outros erros.
        self.model: Any = load_silero_vad()
        self.sr = sr

    def speech_prob(self, audio: np.ndarray) -> float:
        trecho = audio[-self.sr // 2:]                 # últimos 0.5s
        if len(trecho) < self.WIN:
            return 0.0
        self.model.reset_states()
        probs = []
        for i in range(0, len(trecho) - self.WIN + 1, self.WIN):
            janela = np.ascontiguousarray(trecho[i:i + self.WIN], np.float32)
            probs.append(float(self.model(self._torch.from_numpy(janela), self.sr)))
        return max(probs) if probs else 0.0


class RmsVAD:
    """Fallback por energia, quando o silero-vad não está instalado. Implementa VoiceVAD."""
    def __init__(self, settings):
        self.threshold = settings.voice_rms_threshold
        self.janela = int(16000 * 0.3)                 # 0.3s

    def speech_prob(self, audio: np.ndarray) -> float:
        return 1.0 if rms(audio, self.janela) >= self.threshold else 0.0


def make_vad(settings) -> VoiceVAD | None:
    """Fábrica: escolhe o VAD por settings.voice_vad. 'off' desliga (None → cai no RMS do service)."""
    modo = settings.voice_vad.lower()
    if modo in ("off", "none"):
        return None
    if modo in ("auto", "silero"):
        try:
            v = SileroVAD()
            print("[vad] silero ativo", flush=True)
            return v
        except Exception as e:
            print(f"[vad] silero indisponível ({e}); usando RMS", flush=True)
    return RmsVAD(settings)


# palavras de continuação: se o turno termina numa delas, provavelmente ainda não acabou
CONT_WORDS = {"em", "de", "do", "da", "no", "na", "com", "e", "ou", "a", "o", "que", "para",
              "pra", "por", "um", "uma", "se", "como", "quando", "onde", "é"}


class Endpointer:
    """Decide o FIM do turno por silêncio acumulado, com reforço semântico.

    Regra: espera `voice_end_silence_s` de silêncio; mas se a última palavra foi de
    continuação (CONT_WORDS), exige 2.5x mais — quem disse 'a chance de' ainda vai falar.
    """
    def __init__(self, settings):
        self.end_silence = settings.voice_end_silence_s
        self.mult = 2.5
        self.silencio = 0.0

    def reset(self):
        self.silencio = 0.0

    def add_silence(self, hop: float):
        self.silencio += hop

    def ended(self, tail_word: str) -> bool:
        necessario = self.end_silence * (self.mult if tail_word in CONT_WORDS else 1.0)
        return self.silencio >= necessario
