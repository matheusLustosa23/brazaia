import asyncio
from collections.abc import AsyncGenerator

import numpy as np
import sounddevice as sd
from companion.vad import SilenceEndpointer, FRAME_MS

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000   # Kokoro (saída do TTS)
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
            
async def capturar_turno() -> bytes:
    """Grava UM turno do mic até o silêncio. Devolve PCM 16k mono. (desktop)"""
    stop = asyncio.Event()
    ep = SilenceEndpointer(silence_ms=1500)
    buf = bytearray()
    falou = False
    async for chunk in capture_chunks(stop, chunks_ms=FRAME_MS):
        if ep.is_speech(chunk):
            falou = True
        buf.extend(chunk)
        if falou and ep.ended(chunk):
            stop.set()
            break
    return bytes(buf)
        
async def play(audio_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    """Reproduz PCM int16 no speaker."""
    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    
    def _play():
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
    
    await asyncio.get_event_loop().run_in_executor(None, _play)
    
    