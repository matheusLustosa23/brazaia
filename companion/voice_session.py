import asyncio
import logging
import numpy as np
import orjson
import websockets
import time
from companion.audio import capture_chunks, play, TTS_SAMPLE_RATE
from companion.wake import WakeWord
from companion.config import CompanionConfig
from companion.vad import SilenceEndpointer


logger = logging.getLogger(__name__)

SAMPLE_RATE =  16_000
BAR_WIDTH = 20
RMS_FACTOR = 300
SILENCE_MS = 1500             # silêncio contínuo para encerrar o turno


def volume_bar(chunk: bytes, width: int = BAR_WIDTH) -> str:
    audio = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(audio.astype(float) ** 2)) if audio.size else 0.0
    level = min(int(rms / RMS_FACTOR), width)
    pct = min(int(rms / RMS_FACTOR * 100 / width), 100)
    return f"[{'█' * level}{'░' * (width - level)}] {pct}%"


class VoiceSession:
    def __init__(self, cfg: CompanionConfig, max_seconds: float | None = None):
        self.cfg = cfg
        self.url = f"{cfg.server_ws_url}/ws/voice"
        self.max_seconds = max_seconds
        self._endpointer = SilenceEndpointer(silence_ms=SILENCE_MS)
        self.wake = WakeWord(cfg.wake_models, cfg.wake_threshold)
    
    async def loop(self):
        """Modo completo: wake → grava → envia → resposta."""
        while True:
            stop = asyncio.Event()
            print("Aguardando wake ('Fala Braza')...")
            trigger = await self.wake.wait_for_trigger(capture_chunks(stop, chunks_ms=80))
            stop.set()
            print(f"[wake: {trigger}] fale agora...")
            await self._run_turn()
    
    async def _run_turn(self):
        async with websockets.connect(self.url, max_size=None) as ws:
            await ws.send(
                orjson.dumps(
                    {"type": "turn_start", "device_id": self.cfg.device_id,
                     "sample_rate": SAMPLE_RATE}
                ).decode()
            )
            
            stop = asyncio.Event()
            t0 = time.monotonic()
            self._endpointer.reset()
            
            async for chunk in capture_chunks(stop):
                await ws.send(chunk)
                
                bar = volume_bar(chunk)
                print(f"\r {bar} | {time.monotonic() - t0:.1f}s ", end="", flush=True)
                
                if self._endpointer.ended(chunk):
                    print("\n[silêncio detectado]")
                    stop.set()
                    break
                
                if self.max_seconds and time.monotonic() - t0 >= self.max_seconds:
                    stop.set()
                    break
            
            await ws.send(orjson.dumps({"type": "turn_end"}).decode())

            async for msg in ws:
                if isinstance(msg, bytes):
                    await play(msg, sample_rate=TTS_SAMPLE_RATE)
                else:
                    ctrl = orjson.loads(msg)
                    if ctrl.get("type") == "turn_done":
                        print(f"Transcrição: {ctrl.get('text')}")
                        if ctrl.get("reply"):
                            print(f"IA: {ctrl.get('reply')}")
                        return


async def main():
    from companion.config import load_config
    session = VoiceSession(load_config())
    await session.loop()            