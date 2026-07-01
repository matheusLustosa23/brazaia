import orjson, logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from application.services.voice_service import VoiceService


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
    session_id = await orchestrator.create_session() 
    voice = VoiceService(asr, orchestrator, tts, session_id)
    
    try:
        while True:
            first = await ws.receive()
            if first.get("type") == "websocket.disconnect":
                break
            text = first.get("text")
            if text is None:            # veio bytes fora de hora — ignora
                continue
            ctrl = orjson.loads(text)
            if ctrl.get("type") == "conversation_end":
                    break
            assert ctrl.get("type") == "turn_start"
            logger.info("turn_start device=%s", ctrl.get("device_id"))
            
            voice.reset()
            
            while True:
                
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                if msg.get("bytes") is not None:
                    voice.feed(msg["bytes"])
                elif msg.get("text") and orjson.loads(msg["text"]).get("type") == "turn_end":
                    break
                
            texto = await voice.transcribe()
            resposta = ""
            if texto:
                try:
                    async for pcm in voice.reply_audio(texto):
                        await ws.send_bytes(pcm)
                    resposta = voice.last_reply
                except Exception as e:
                    logger.warning("tts_error: %s", e)
                    resposta = await voice.reply_text(texto)
            await ws.send_text(
                orjson.dumps(
                    {
                      "type": "turn_done", 
                      "text": texto or "", 
                      "reply": resposta  
                    }
                ).decode()
            )
    except WebSocketDisconnect:
        return                   
    
  
    