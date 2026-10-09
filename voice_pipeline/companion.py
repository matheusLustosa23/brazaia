"""Companion da pipeline de voz (roda no SEU device — note, celular, etc.). LEVE: sem GPU.

Só faz I/O: captura o microfone e streama pro server; recebe os eventos e o áudio do TTS, toca
(gapless) e mostra a transcrição ao vivo (você + agente). Toda a inteligência está no server.

Dependências aqui: sounddevice, numpy, websockets  (NÃO precisa de torch/kokoro/whisper).

Rodar (no seu device):
  python -m voice_pipeline.companion --host 100.78.164.45            # com fone (barge-in por voz)
  python -m voice_pipeline.companion --host 100.78.164.45 --no-barge-in   # sem fone (half-duplex)
"""
from __future__ import annotations
import json
import asyncio
import argparse

import websockets

from .config import Config
from .capture import Microphone
from .playback import Player
from .transcript import Transcript


async def run(host: str, port: int, barge_in: bool):
    cfg = Config.load()
    tx = Transcript()
    tx.info(f"conectando em ws://{host}:{port} …")
    player = Player(cfg.audio, cfg.audio.tts_sample_rate)
    player.start()

    loop = asyncio.get_running_loop()
    sendq: asyncio.Queue = asyncio.Queue()

    def on_frame(pcm: bytes):
        # half-duplex: em modo sem fone, não manda mic enquanto a IA fala (evita eco/auto-barge)
        if (not barge_in) and player.busy():
            return
        loop.call_soon_threadsafe(sendq.put_nowait, pcm)

    mic = Microphone(cfg.audio, on_frame)
    uri = f"ws://{host}:{port}"

    try:
        async with websockets.connect(uri, max_size=None, ping_interval=20) as ws:
            mic.start()
            await ws.send(json.dumps({"type": "hello"}))
            tx.info("conectado ✓ — pode falar  (Ctrl+C sai)")
            muted = False   # após barge-in, ignora o PCM da resposta cortada até a NOVA começar

            async def sender():
                while True:
                    pcm = await sendq.get()
                    try:
                        await ws.send(pcm)
                    except Exception:
                        break

            async def receiver():
                nonlocal muted
                async for msg in ws:
                    if isinstance(msg, (bytes, bytearray)):
                        if not muted:
                            player.feed(msg)
                        continue
                    m = json.loads(msg); ty = m.get("type")
                    if ty == "partial":      tx.user_partial(m.get("text", ""))
                    elif ty == "final":      tx.user_final(m.get("text", ""))
                    elif ty == "thinking":   tx.thinking()
                    elif ty == "reply_start":tx.agent_start(); muted = False
                    elif ty == "reply_delta":tx.agent_delta(m.get("text", ""))
                    elif ty == "reply_end":  tx.agent_final()
                    elif ty == "interrupt":  player.clear(); muted = True; tx.interrupted()
                    elif ty == "info":       tx.info(m.get("text", ""))
                    elif ty == "error":      tx.error(m.get("text", ""))

            st = asyncio.create_task(sender())
            rc = asyncio.create_task(receiver())
            try:
                await rc                                   # até a conexão cair / Ctrl+C
            finally:
                st.cancel()
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
