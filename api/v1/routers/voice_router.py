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


@router.websocket("/ws/transcribe")
async def transcribe_ws(ws: WebSocket) -> None:
    """STT-only: recebe UM turno de áudio (PCM ou AAC) e devolve só a transcrição.
    É o modo 'mensagem de voz' do CLI — NÃO roda LLM nem TTS (isso é o /ws/voice).

    Protocolo: {"type":"turn_start","fmt":"pcm|aac"} → bytes do áudio → {"type":"turn_end"}
    Resposta:  {"type":"final","text":...}  (ou {"type":"error","text":...})"""
    await ws.accept()
    asr = ws.app.state.asr
    if asr is None:
        await ws.send_text(orjson.dumps({"type": "error", "text": "voz desabilitada no server"}).decode())
        await ws.close()
        return
    import numpy as np
    from infrastructure.voice.asr import is_hallucination, collapse_repeats
    fmt = "pcm"
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                raw = msg["bytes"]
                try:
                    pcm = await _decode_aac(raw) if fmt == "aac" else raw
                except FileNotFoundError:
                    await ws.send_text(orjson.dumps({"type": "error", "text": "ffmpeg não está no PATH do server"}).decode())
                    continue
                if not pcm:
                    await ws.send_text(orjson.dumps({"type": "error", "text": "áudio vazio / ffmpeg falhou"}).decode())
                    continue
                audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
                words = await asyncio.to_thread(asr.transcribe_words, audio, "")
                texto = collapse_repeats(" ".join(w.texto for w in words).strip())
                if is_hallucination(texto):
                    texto = ""
                logger.info("[transcribe] %d bytes → %r", len(raw), texto)
                await ws.send_text(orjson.dumps({"type": "final", "text": texto}).decode())
            elif msg.get("text"):
                d = orjson.loads(msg["text"])
                if d.get("type") == "turn_start":
                    fmt = d.get("fmt", "pcm")
                elif d.get("type") == "bye":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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
                    pending_aac = False
                    try:
                        pcm = await _decode_aac(msg["bytes"])
                    except FileNotFoundError:
                        await emit({"type": "error", "text": "ffmpeg não está no PATH do server"})
                        continue
                    logger.info("[voz] turno AAC: %d bytes → %d bytes PCM", len(msg["bytes"]), len(pcm))
                    if not pcm:
                        await emit({"type": "error", "text": "ffmpeg não decodificou o AAC (0 bytes)"})
                        continue
                    await sess.handle_turn(pcm)      # áudio fechado → transcreve inteiro e responde (sem VAD streaming)
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
