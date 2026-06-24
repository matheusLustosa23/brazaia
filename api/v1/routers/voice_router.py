import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

@router.websocket("/ws/ping")
async def ping_ws(ws: WebSocket) -> None:
    """Endpoint de health check para o ConnectivityMonitor.
    Aceita conexão e fecha imediatamente — confirma que o servidor está vivo."""
    await ws.accept()
    await ws.close()

@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket) -> None:
    await ws.accept()
    start = orjson.loads(await ws.receive_text())
    assert start["type"] == "turn_start"
    
    audio = bytearray()
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                audio.extend(msg["bytes"])
            elif msg.get("text") is not None:
                ctrl = orjson.loads(msg["text"])
                if ctrl.get("type") == "turn_end":
                    break
    except WebSocketDisconnect:
        return
    await  ws.send_text(orjson.dumps({"type": "turn_done", "asr": None}).decode())
    
                
    