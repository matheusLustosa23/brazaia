import websockets
from companion._json import dumps, loads
from companion.audio import capturar_turno, tocar, TTS_SAMPLE_RATE

async def turno_unico(cfg) -> None:
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_timeout=120) as ws:
        await ws.send(
            dumps(
                {
                "type": "turn_start", 
                "device_id": cfg.device_id
                }
            )
            
        )
        await ws.send(await capturar_turno())
        await ws.send(dumps({"type": "turn_end"}))
        audio = bytearray()
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                audio.extend(msg)
            elif loads(msg).get("type") == "turn_done":
                break
        if audio:
            await tocar(bytes(audio), TTS_SAMPLE_RATE)

