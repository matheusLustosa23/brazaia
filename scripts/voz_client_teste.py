"""Client de teste da rota /ws/voice (streaming) — pra ouvir a pipe no Ubuntu, sem o companion.

Mic → server (PCM16 16k contínuo) · server → fala de volta (PCM 24k) + eventos json.
Anti-vazamento: não manda o mic enquanto o bot fala (evita o TTS virar STT).
Barge-in NÃO implementado aqui (é só teste) — espera o bot terminar antes de falar.

Pré-req: server rodando com voz, e no Ubuntu:  uv add sounddevice  (+ sudo apt install libportaudio2)

Rodar:
    SERVER_WS_URL=ws://localhost:8080/api/v1 uv run python scripts/voz_client_teste.py
    # server remoto (tailscale):
    SERVER_WS_URL=ws://iobraza:8080/api/v1   uv run python scripts/voz_client_teste.py
"""
import asyncio
import json
import os

import numpy as np
import sounddevice as sd
import websockets

_BASE = os.getenv("SERVER_WS_URL", "ws://localhost:8080/api/v1").rstrip("/")
URL = _BASE if _BASE.endswith("/ws/voice") else _BASE + "/ws/voice"   # aceita base OU url completa
SR_IN = 16000      # mic → server
SR_OUT = 24000     # server → alto-falante
BLOCK = 1600       # 0.1s @ 16k


async def main():
    print(f"conectando em {URL} ...")
    async with websockets.connect(URL, max_size=None, ping_interval=None) as ws:   # ping off: evita colisão pong×áudio
        print("conectado ✓  — pode falar! (Ctrl+C pra sair)\n")
        loop = asyncio.get_running_loop()
        mic_q: asyncio.Queue[bytes] = asyncio.Queue()
        bot_falando = asyncio.Event()        # enquanto setado, não manda o mic

        def on_mic(indata, frames, time_info, status):
            pcm = (np.clip(indata[:, 0], -1, 1) * 32767).astype(np.int16).tobytes()
            loop.call_soon_threadsafe(mic_q.put_nowait, pcm)

        mic = sd.InputStream(samplerate=SR_IN, channels=1, dtype="float32",
                             blocksize=BLOCK, callback=on_mic)
        player = sd.OutputStream(samplerate=SR_OUT, channels=1, dtype="int16")
        mic.start()
        player.start()

        async def enviar_mic():
            while True:
                pcm = await mic_q.get()
                if not bot_falando.is_set():
                    await ws.send(pcm)

        async def receber():
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    await asyncio.to_thread(player.write, np.frombuffer(msg, np.int16))
                    continue
                ev = json.loads(msg)
                t = ev.get("type")
                if t == "partial":
                    firme = ev.get("firme", ev.get("text", ""))
                    prov = ev.get("prov", "")
                    # \r\033[K limpa a linha (não empilha); firme normal, provisório em cinza
                    print(f"\r\033[K  {firme} \033[90m{prov}\033[0m", end="", flush=True)
                elif t == "final":
                    print(f"\r\033[K🫵  {ev.get('text', '')}")
                elif t == "reply_start":
                    bot_falando.set()
                    print("🤖 ", end="", flush=True)
                elif t == "reply_delta":
                    print(ev.get("text", ""), end="", flush=True)
                elif t == "timing":
                    print(f"\n⏱  STT {ev['stt_ms']}ms · pensar(TTFT) {ev['ttft_ms']}ms · "
                          f"1º áudio(TTFA) {ev['ttfa_ms']}ms · TTS {ev['tts_ms']}ms · "
                          f"total {ev['resp_ms']}ms · {ev['chars']} chars")
                elif t == "reply_end":
                    print()
                    bot_falando.clear()
                elif t == "error":
                    print(f"\n⚠  {ev.get('text')}")

        try:
            await asyncio.gather(enviar_mic(), receber())
        finally:
            mic.stop()
            player.stop()
            try:
                await ws.send(json.dumps({"type": "bye"}))
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nsaindo.")
