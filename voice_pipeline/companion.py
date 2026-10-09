"""Companion da pipeline de voz (roda no SEU device — note, celular, etc.). LEVE: sem GPU.

Só faz I/O: captura o microfone e streama pro server; recebe os eventos e o áudio do TTS, toca
(gapless) e mostra a transcrição ao vivo (você + agente). Toda a inteligência está no server.

Barge-in é feito AQUI (mic + alto-falante convivem no mesmo processo → corte LOCAL instantâneo, igual
ao protótipo monolítico). O server só recebe o sinal {"type":"barge"} pra parar a geração.

Dependências aqui: sounddevice, numpy, websockets  (NÃO precisa de torch/kokoro/whisper).

Rodar (no seu device):
  python -m voice_pipeline.companion --host 100.78.164.45            # com fone (barge-in por voz)
  python -m voice_pipeline.companion --host 100.78.164.45 --no-barge-in   # sem fone (half-duplex)
  BARGE_MS=400 python -m voice_pipeline.companion --host ...        # barge menos sensível
"""
from __future__ import annotations
import os
import json
import asyncio
import argparse

import numpy as np
import websockets

from .config import Config
from .capture import Microphone
from .playback import Player
from .transcript import Transcript


def _frame_rms(pcm: bytes) -> float:
    """RMS 0..~1 de um frame PCM int16."""
    a = np.frombuffer(pcm, np.int16)
    return float(np.sqrt(np.mean((a.astype(np.float32) / 32768.0) ** 2))) if a.size else 0.0


async def run(host: str, port: int, barge_in: bool):
    cfg = Config.load()
    tx = Transcript()
    tx.info(f"conectando em ws://{host}:{port} …")
    player = Player(cfg.audio, cfg.audio.tts_sample_rate)
    player.start()

    loop = asyncio.get_running_loop()
    sendq: asyncio.Queue = asyncio.Queue()

    # barge-in: exige ~BARGE_MS de fala sustentada durante o playback (callback é a cada frame_ms)
    barge_ms = int(os.getenv("BARGE_MS", "250"))
    barge_need = max(2, barge_ms // max(1, cfg.audio.frame_ms))
    st = {"muted": False, "barge_hits": 0, "barged": False}   # estado compartilhado (audio thread + loop)

    def on_frame(pcm: bytes):
        # barge-in LOCAL: fala durante o playback → corta o áudio na hora + avisa o server
        if barge_in and player.busy() and not st["muted"]:
            if _frame_rms(pcm) >= cfg.vad.rms_threshold:
                st["barge_hits"] += 1
                if st["barge_hits"] >= barge_need and not st["barged"]:
                    st["barged"] = True
                    st["muted"] = True
                    player.clear()                                   # CORTE LOCAL INSTANTÂNEO
                    loop.call_soon_threadsafe(sendq.put_nowait, {"type": "barge"})
                    tx.interrupted()
            else:
                st["barge_hits"] = 0
        # stream do mic pro server (half-duplex: não envia enquanto a IA fala)
        if barge_in or not player.busy():
            loop.call_soon_threadsafe(sendq.put_nowait, pcm)

    mic = Microphone(cfg.audio, on_frame)
    uri = f"ws://{host}:{port}"

    try:
        async with websockets.connect(uri, max_size=None, ping_interval=20) as ws:
            mic.start()
            await ws.send(json.dumps({"type": "hello"}))
            tx.info("conectado ✓ — pode falar  (Ctrl+C sai)")

            async def sender():
                while True:
                    item = await sendq.get()
                    try:
                        await ws.send(item if isinstance(item, (bytes, bytearray)) else json.dumps(item))
                    except Exception:
                        break

            async def receiver():
                async for msg in ws:
                    if isinstance(msg, (bytes, bytearray)):
                        if not st["muted"]:
                            player.feed(msg)
                        continue
                    m = json.loads(msg); ty = m.get("type")
                    if ty == "partial":       tx.user_partial(m.get("text", ""))
                    elif ty == "final":       tx.user_final(m.get("text", ""))
                    elif ty == "thinking":    tx.thinking()
                    elif ty == "reply_start":
                        player.clear()                               # corta sobra do turno anterior
                        tx.agent_start()
                        st["muted"] = False; st["barged"] = False; st["barge_hits"] = 0
                    elif ty == "reply_delta": tx.agent_delta(m.get("text", ""))
                    elif ty == "reply_end":   tx.agent_final()
                    elif ty == "interrupt":   player.clear(); st["muted"] = True; tx.interrupted()
                    elif ty == "info":        tx.info(m.get("text", ""))
                    elif ty == "error":       tx.error(m.get("text", ""))

            sndr = asyncio.create_task(sender())
            rcvr = asyncio.create_task(receiver())
            try:
                await rcvr                                   # até a conexão cair / Ctrl+C
            finally:
                sndr.cancel()
                try:
                    await ws.send(json.dumps({"type": "bye"}))
                except Exception:
                    pass
    finally:
        mic.stop()
        player.stop()


def main():
    ap = argparse.ArgumentParser(description="Companion da pipeline de voz (I/O remoto, sem GPU).")
    ap.add_argument("--host", required=True, help="IP/host do server (ex.: 100.78.164.45)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-barge-in", action="store_true", help="half-duplex (use se NÃO tiver fone)")
    a = ap.parse_args()
    try:
        asyncio.run(run(a.host, a.port, not a.no_barge_in))
    except KeyboardInterrupt:
        pass
    print("\n[companion] encerrado.")


if __name__ == "__main__":
    main()
