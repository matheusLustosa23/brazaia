import websockets
from companion._json import dumps, loads
from companion.audio import capturar_turno, tocar, TTS_SAMPLE_RATE
from  companion.plataform import _IS_TERMUX
from websockets.asyncio.client import ClientConnection
from companion.config import CompanionConfig

CAPTURE_FMT = "aac" if _IS_TERMUX else "pcm" 

async def _receber_e_tocar(ws: ClientConnection) -> str: 
    """Lê a resposta (PCM até o turn_done), IMPRIME a transcrição (debug de captação) e toca."""
    pcm, texto = bytearray(), ""
    async for msg in ws:
        if isinstance(msg, (bytes, bytearray)):
            pcm.extend(msg)
        else:
            ev = loads(msg)
            if ev.get("type") == "turn_done":
                texto = ev.get("text", "")
                print(f"[você disse] {ev.get('text','')}")   # DEBUG: o que o ASR captou
                print(f"[resposta]   {ev.get('reply','')}")
                break
    if pcm:
        await tocar(bytes(pcm), TTS_SAMPLE_RATE)
    return texto

async def turno_unico(cfg: CompanionConfig) -> None:
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_timeout=120) as ws:
        await ws.send(dumps({"type": "turn_start", "device_id": cfg.device_id, "fmt": CAPTURE_FMT}))
        await ws.send(await capturar_turno())
        await ws.send(dumps({"type": "turn_end"}))
        await _receber_e_tocar(ws)

async def enviar_arquivo(cfg: CompanionConfig, caminho: str) -> str:
    with open(caminho, "rb") as f:
        audio = f.read()
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_timeout=120) as ws:
        await ws.send(dumps({"type": "turn_start", "device_id": cfg.device_id, "fmt": "aac"}))
        await ws.send(audio)
        await ws.send(dumps({"type": "turn_end"}))
        return await _receber_e_tocar(ws)