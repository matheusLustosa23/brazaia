import asyncio
import numpy as np
from faster_whisper import WhisperModel


class ASR:
    """faster-whisper na CPU int8 (default `small`). Stateless: o modelo é carregado
    uma vez (no lifespan) e cada chamada transcreve o PCM recebido."""

    def __init__(self, model_size: str = "small", device: str = "cpu", beam_size: int = 1):
        self._model = WhisperModel(model_size, device=device, compute_type="int8")
        self._beam = beam_size

    def _transcribe_sync(self, pcm: bytes, language: str | None) -> str | None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        audio = samples.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(audio, language=language, beam_size=self._beam, vad_filter=True)
        text = " ".join(s.text for s in segments).strip()
        return text or None

    async def transcribe(self, pcm: bytes, language: str | None = "pt") -> str | None:
        if not pcm:
            return None
        return await asyncio.to_thread(self._transcribe_sync, pcm, language)