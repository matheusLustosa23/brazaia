import numpy as np
from openwakeword.model import Model
from collections.abc import AsyncIterator


class WakeWord:
    """Detecção on-device. Carrega 1+ modelos custom; dispara no threshold."""

    def __init__(self, model_paths: list[str], threshold: float = 0.3):
        self._model = Model(wakeword_model_paths=model_paths)
        self._threshold = threshold

    async def wait_for_trigger(self, chunks: AsyncIterator[bytes]) -> str:
        """Consome chunks PCM int16 16kHz até detectar um wake. Retorna o nome do modelo."""
        async for chunk in chunks:
            audio = np.frombuffer(chunk, dtype=np.int16)
            scores = self._model.predict(audio)
            if isinstance(scores, tuple):
                scores = scores[0]
            for name, score in scores.items():
                if score >= self._threshold:
                    self._model.reset()
                    return name
        return ""
