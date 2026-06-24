import asyncio
from collections.abc import AsyncGenerator

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "int16"


async def capture_chunks(stop_event: asyncio.Event, chunks_ms: int = 30) -> AsyncGenerator[bytes , None]:
    """Gera chunks de áudio do microfone como PCM int16."""
    frames_per_chunks = int(SAMPLE_RATE * chunks_ms / 1000)
    q: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    def callback(indata, frames, time, status):
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))
    
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        callback=callback,
        blocksize=frames_per_chunks
    ):
        while not stop_event.is_set():
            chunk = await q.get()
            yield chunk

async def play(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    """Reproduz PCM int16 no speaker."""
    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: sd.play(audio, samplerate=sample_rate)
    )