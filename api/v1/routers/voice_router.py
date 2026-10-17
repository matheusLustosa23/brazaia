"""WS de voz — streaming full-duplex.

client → PCM16 contínuo (bytes) + controle json ({"type":"barge"} / {"type":"bye"})
server → eventos json (state/partial/final/reply_delta/reply_end/error) + PCM24k (bytes)

O router é só transporte: liga a VoiceSession ao WS (emite json/áudio com lock;
recebe PCM/controle). A lógica toda vive na VoiceSession.
"""
import asyncio
import logging

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from application.services.voice_service import VoiceSession

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/ping")
async def ping_ws(ws: WebSocket) -> None:
    """Health check do ConnectivityMonitor: aceita e fecha na hora."""
    await ws.accept()
    await ws.close()


@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket) -> None:
    await ws.accept()
    s = ws.app.state.settings
    asr = ws.app.state.asr
    vad = ws.app.state.vad
    tts = ws.app.state.tts
    if asr is None or tts is None:
        await ws.send_text(orjson.dumps({"type": "error", "text": "voz desabilitada no server"}).decode())
        await ws.close()
        return

    orchestrator = ws.app.state.container.orchestrator
    sid = await orchestrator.create_session()

    lock = asyncio.Lock()
    async def emit(obj: dict) -> None:          # json com lock (ordena com o áudio)
        async with lock:
            await ws.send_text(orjson.dumps(obj).decode())
    async def send_audio(pcm: bytes) -> None:
        async with lock:
            await ws.send_bytes(pcm)

    sess = VoiceSession(s, asr, vad, tts, orchestrator, sid, emit, send_audio)
    task = asyncio.create_task(sess.run())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                sess.feed(msg["bytes"])
            elif msg.get("text"):
                t = orjson.loads(msg["text"]).get("type")
                if t == "bye":
                    break
                elif t == "barge":
                    await sess.external_barge()
    except WebSocketDisconnect:
        pass
    finally:
        await sess.shutdown()
        task.cancel()
