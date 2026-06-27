import orjson, logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from application.services.voice_service import VoiceService
from api.v1.dependencies import get_asr  # injeta o ASR compartilhado (lifespan)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.websocket("/ws/ping")
async def ping_ws(ws: WebSocket) -> None:
    """Endpoint de health check para o ConnectivityMonitor.
    Aceita conexão e fecha imediatamente — confirma que o servidor está vivo."""
    await ws.accept()
    await ws.close()

@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket, asr=Depends(get_asr)) -> None:
   
    await ws.accept()
    voice = VoiceService(asr)
    
    try:
        first = await ws.receive()
        start = orjson.loads(first["text"])
        assert start.get("type") == "turn_start"
        logger.info("turn_start device=%s", start.get("device_id"))
        
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                voice.feed(msg["bytes"])
            elif msg.get("text") is not None:
                ctrl = orjson.loads(msg["text"])
                if ctrl.get("type") == "turn_end":
                    texto = await voice.transcribe()
                    logger.info("turn_end texto=%s", texto)
                    # Slice 3: resposta = await voice.reply_text(texto)
                    await ws.send_text(
                        orjson.dumps({"type": "turn_done", "text": texto or ""}).decode()
                    )
                    return
    except WebSocketDisconnect:
        return                   
    
  
    