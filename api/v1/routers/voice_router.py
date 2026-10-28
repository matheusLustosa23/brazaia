"""WS de voz — streaming full-duplex.

client → PCM16 contínuo (bytes) + controle json ({"type":"barge"} / {"type":"bye"})
server → eventos json (state/partial/final/reply_delta/reply_end/error) + PCM24k (bytes)

Turno AAC (celular Termux, sem ffmpeg): client manda {"type":"audio_turn","fmt":"aac"}
e o PRÓXIMO binário é o AAC cru; o server decodifica (ffmpeg) → PCM16 + silêncio → VAD fecha o turno.

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


async def _decode_aac(aac: bytes) -> bytes:
    """Decodifica AAC (gravado no celular Termux) → PCM16 16k mono, via ffmpeg no server.
    Usa arquivo temporário (não pipe:0) porque o container AAC/m4a pode precisar de seek."""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".aac", delete=False) as f:
        f.write(aac)
        path = f.name
    try:
        p = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "quiet", "-i", path,
            "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        pcm, _ = await p.communicate()
        return pcm
    finally:
        os.unlink(path)


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
    pending_aac = False                              # próximo binário é um turno AAC (celular)?
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                if pending_aac:                      # turno do celular: decodifica AAC → feed + silêncio
                    pcm = await _decode_aac(msg["bytes"])
                    sess.feed(pcm)
                    sess.feed(b"\x00" * 48000)       # ~1,5s de silêncio → VAD do server fecha o turno
                    pending_aac = False
                else:
                    sess.feed(msg["bytes"])          # streaming normal (note): PCM16 contínuo
            elif msg.get("text"):
                t = orjson.loads(msg["text"]).get("type")
                if t == "bye":
                    break
                elif t == "barge":
                    await sess.external_barge()
                elif t == "audio_turn":              # celular avisou: o próximo binário é AAC
                    pending_aac = True
    except WebSocketDisconnect:
        pass
    finally:
        await sess.shutdown()
        task.cancel()
