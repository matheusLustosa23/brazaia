import asyncio, numpy as np
from openwakeword.model import Model
from collections.abc import AsyncIterator

WAKE_MODEL_PATH = ".venv/lib/python3.12/site-packages/openwakeword/resources/models/hey_jarvis_v0.1.onnx"
THRESHOLD = 0.3


class WakeWord:
    def __init__(self, path: str = WAKE_MODEL_PATH):
        self._model = Model(wakeword_model_paths=[path])
        
    async def wait_for_trigger(self, mic_chunks: AsyncIterator[bytes]) -> None:
        """Bloqueia até detectar 'Hey Jarvis'. Mic permanece local até aqui."""
        async for chunk in mic_chunks:
            audio = np.frombuffer(chunk, dtype=np.int16)
            scores = self._model.predict(audio)
            if isinstance(scores, tuple):
                scores = scores[0]
            if max(scores.values()) >= THRESHOLD:
                self._model.reset()
                return
            await asyncio.sleep(0)
            
            
                