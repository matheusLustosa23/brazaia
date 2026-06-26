import asyncio
import logging
import numpy as np
import orjson
import websockets
from companion.audio import capture_chunks
from companion.config import CompanionConfig

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
RECORD_SECONDS = 5
BAR_WIDTH = 20
RMS_FACTOR = 300  # calibrado para RMS ~2000-3000 = 50% da barra

def volume_bar(chunk: bytes, width: int = BAR_WIDTH) -> str: 
    audio = np.frombuffer(chunk, dtype=np.int16)
    rms = np.sqrt(np.mean(audio.astype(float) ** 2))
    level = min(int(rms / RMS_FACTOR), width)
    pct = min(int(rms / RMS_FACTOR * 100 / width), 100)
    bar = "█" * level + "░" * (width - level)
    return f"[{bar}] {pct}%"
    


class VoiceSession:
    def __init__(self, cfg: CompanionConfig):
        self.cfg = cfg
        self.url = f"{cfg.server_ws_url}/ws/voice"
    
    async def loop(self):
        """Modo simplificado: conecta, grava 5 segundos, envia."""
        while True:
            print("Pressione Enter para falar (ou aguarde 5s de gravação)...") 
            await asyncio.get_event_loop().run_in_executor(None, input)
            print("Gravando... fale agora!")
            await self._run_turn()
        
    async def _run_turn(self):
        async with websockets.connect(self.url, max_size=None) as ws:
            await ws.send(
                orjson.dumps(
                    {
                        "type": "turn_start",
                        "device_id": self.cfg.device_id,
                        "sample_rate": SAMPLE_RATE,
                    }
                ).decode()
            )
            stop = asyncio.Event()
            audio_chunks = []
            async def capture():
                async for chunk in capture_chunks(stop):
                    audio_chunks.append(chunk)
                    elapsed = len(audio_chunks) * 0.03
                    bar = volume_bar(chunk)
                    print(f"\r {bar} | {elapsed:.1f}s", end="", flush=True)
            
            async def timer():
                await asyncio.sleep(RECORD_SECONDS)
                stop.set()
            
            await asyncio.gather(capture(), timer())
            print()
            for chunk in audio_chunks:
                await ws.send(chunk)
            print(f"Enviados {len(audio_chunks)} chunks ao servidor")

            await ws.send(orjson.dumps({"type": "turn_end"}).decode())
            
            async for msg in ws:
                if isinstance(msg, bytes):...
                else:
                    ctrl = orjson.loads(msg)
                    print(f"resposta: {ctrl}")
                    if ctrl.get("type") == "turn_done":
                        return
    
async def main():
    from companion.config import load_config
    session = VoiceSession(load_config())
    await session.loop()
