from companion.config import CompanionConfig
from companion.wake import WakeWord
from companion.vad import SilenceEndpointer
from companion.greeting import play_greeting
from companion.audio import capture_chunks, play, TTS_SAMPLE_RATE
import websockets, numpy as np
from websockets.asyncio.client import ClientConnection
import asyncio, time
from companion._json import dumps, loads  


SAMPLE_RATE =  16_000
BAR_WIDTH = 20
RMS_FACTOR = 300

FOLLOW_UP_FRAME_MS = 30

def volume_bar(chunk: bytes, width: int = BAR_WIDTH) -> str:
    audio = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(audio.astype(float) ** 2)) if audio.size else 0.0
    level = min(int(rms / RMS_FACTOR), width)
    pct = min(int(rms / RMS_FACTOR * 100 / width), 100)
    return f"[{'█' * level}{'░' * (width - level)}] {pct}%"


class ConversationSession:
    
    def __init__(self, cfg: CompanionConfig):
        self.cfg = cfg
        self.url = f"{cfg.server_ws_url}/ws/voice"
        self.wake = WakeWord(cfg.wake_models, cfg.wake_threshold)
        self._endpointer = SilenceEndpointer(silence_ms=cfg.silence_ms)
        
    async def loop(self):
        from companion.voice_stream import conversar
        while True:
            stop = asyncio.Event()
            await self.wake.wait_for_trigger(capture_chunks(stop, chunks_ms=80))
            stop.set()
            if self.cfg.greeting_enabled:
                await play_greeting(self.cfg.greeting_voice)
            await conversar(self.cfg, idle_s=30) 

    
                
        