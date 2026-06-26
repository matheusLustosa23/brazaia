import orjson, logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
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
    msg = await ws.receive()
    text = msg.get("text") or msg.get("bytes",b"").decode()
    start = orjson.loads(text)
    assert start["type"] == "turn_start"
    logger.info(f"turn_start: device={start.get('device_id')}")
    
    audio = bytearray()
    chunk_count = 0 
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                audio.extend(msg["bytes"])
                chunk_count += 1
                if chunk_count % 50 == 0:
                    logger.info(f"audio_chunks_received: {chunk_count} bytes={len(audio)}")
            elif msg.get("text") is not None:
                ctrl = orjson.loads(msg["text"])
                if ctrl.get("type") == "turn_end":
                    break
                
        await ws.send_text(orjson.dumps({
            "type": "turn_done",
            "asr": "",
            "debug": {"chunks": chunk_count, "bytes": len(audio)}
        }).decode())
        
    except WebSocketDisconnect:
        return
    await  ws.send_text(orjson.dumps({"type": "turn_done", "asr": None}).decode())
    
                
    