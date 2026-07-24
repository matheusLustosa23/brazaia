import asyncio
from collections.abc import AsyncGenerator
import os, wave
from companion.plataform import _IS_TERMUX, _run_sync

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000   # Kokoro (saída do TTS)
CHANNELS = 1
DTYPE = "int16"
_DIR = os.path.expanduser("~/brazaia")

async def capture_chunks(stop_event: asyncio.Event, chunks_ms: int = 30) -> AsyncGenerator[bytes , None]:
    import sounddevice as sd
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
    
    if _IS_TERMUX:
        os.makedirs(_DIR, exist_ok=True)
        aac, pcm, dur = f"{_DIR}/turno.aac", f"{_DIR}/turno.pcm", 8
        await _run_sync(["termux-microphone-record", "-f", aac, "-l", str(dur), "-e", "aac"])
        await asyncio.sleep(dur + 0.4)
        await _run_sync(["ffmpeg", "-y", "-i", aac, "-ar", "16000", "-ac", "1", "-f", "s16le", pcm])
        with open(pcm, "rb") as f:
            return f.read()
        
    
    from companion.vad import SilenceEndpointer, FRAME_MS
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
    import numpy as np
    import sounddevice as sd
    audio = np.frombuffer(audio_bytes, dtype=np.int16)
    
    def _play():
        sd.play(audio, samplerate=sample_rate)
        sd.wait()
    
    await asyncio.get_event_loop().run_in_executor(None, _play)
    
async def tocar(pcm: bytes, rate: int) -> None:
    """Toca a resposta — Termux: WAV + termux-media-player. Desktop: sounddevice."""
    if _IS_TERMUX:
        wav = f"{_DIR}/resposta.wav"
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        await _run_sync(["termux-media-player", "play", wav])
        return
    await play(pcm, rate)
    
    