from typing import Protocol, runtime_checkable
import numpy as np

Word = tuple[str, float, float]   # (palavra, início_s, fim_s)

@runtime_checkable
class VoiceASR(Protocol):
    """STT. `transcribe_words` é o streaming (re-transcreve a janela, devolve palavras c/ tempo)."""
    def transcribe_words(self, audio: np.ndarray, prompt: str = "") -> list[Word]: ...

@runtime_checkable
class VoiceVAD(Protocol):
    """Probabilidade de fala (0..1) nos últimos ~0.5s. Separa fala de ruído."""
    def speech_prob(self, audio: np.ndarray) -> float: ...

@runtime_checkable
class VoiceTTS(Protocol):
    """TTS por frase: texto → PCM int16 @ 24k."""
    def synth(self, texto: str) -> bytes: ...
