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
async def voice_ws(ws: WebSocket) -> None:
   
    await ws.accept()
    asr = ws.app.state.asr
    orchestrator = ws.app.state.container.orchestrator
    tts = ws.app.state.tts
    voice = VoiceService(asr, orchestrator, tts)
    
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
                    if texto:
                        try:
                            async for pcm in voice.reply_audio(texto):
                                await ws.send_bytes(pcm)
                            resposta = voice.last_reply
                        except Exception as e:
                            logger.warning("tts_error: %s", e)
                            resposta = await voice.reply_text(texto)
                    else: 
                        resposta = ""
                    
                    logger.info("llm_reply: %s", resposta[:100])
                    await ws.send_text(orjson.dumps(
                        {"type": "turn_done", "text": texto or "", "reply": resposta}
                    ).decode())
                    return
    except WebSocketDisconnect:
        return                   
    
  
    