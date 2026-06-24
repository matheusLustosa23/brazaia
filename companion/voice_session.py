import asyncio
import orjson
import websockets
from companion.audio import capture_chunks, play
from companion.wake import WakeWord
from companion.config import CompanionConfig


class VoiceSession:
    def __init__(self, cfg: CompanionConfig):
        self.cfg = cfg
        self.url = f"{cfg.server_ws_url}/ws/voice"
        self.wake = WakeWord()

    async def loop(self):
        while True:
            stop = asyncio.Event()
            await self.wake.wait_for_trigger(capture_chunks(stop))
            await self._run_turn()
            

    async def _run_turn(self, pcm: bytes | None = None, offline_context: str = ""):
        """Executa um turno de voz.

        Se pcm é fornecido (do ModeRouter), envia direto ao servidor.
        Se pcm é None, captura do microfone em tempo real."""
        stop = asyncio.Event()
        async with websockets.connect(self.url, max_size=None) as ws:
            payload = {
                "type": "turn_start",
                "device_id": self.cfg.device_id,
                "sample_rate": 16_000,
            }
            if offline_context:
                payload["offline_context"] = offline_context
            await ws.send(orjson.dumps(payload))

            async def push_audio():
                if pcm is not None:
                    await ws.send(pcm)
                else:
                    async for chunk in capture_chunks(stop):
                        await ws.send(chunk)
                
                await ws.send(orjson.dumps({"type": "turn_end"}).decode())

            async def pull_audio():
                async for msg in ws:
                    if isinstance(msg, bytes):
                        await play(msg)
                    else:
                        ctrl = orjson.loads(msg)
                        if ctrl.get("type") == "turn_done":
                            stop.set()
                            return

            await asyncio.gather(push_audio(), pull_audio())
