import asyncio, websockets, time
from companion._json import dumps, loads
from companion.audio import capture_chunks, GaplessPlayer

async def conversar(cfg, *, idle_s: float | None = None, once=False):
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        stop = asyncio.Event()
        bot_falando = asyncio.Event()        
        player = GaplessPlayer() 
        ultima = time.monotonic()
        async def enviar_mic():
            async for chunk in capture_chunks(stop, chunks_ms=100):   # PCM16 16k
                if stop.is_set(): break
                if not bot_falando.is_set():
                    await ws.send(chunk)

        async def receber():
            nonlocal ultima
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    await player.write(msg) 
                    continue
                ev = loads(msg); t = ev.get("type")
                if   t == "partial":   ultima = time.monotonic(); print(f"\r\033[K {ev['firme']} \033[90m{ev.get('prov','')}\033[0m", end="", flush=True)
                elif t == "final":       ultima = time.monotonic(); print(f"\r\033[K🫵 {ev['text']}")
                elif t == "reply_start": bot_falando.set(); print("🤖 ", end="", flush=True)
                elif t == "reply_delta": print(ev["text"], end="", flush=True)
                elif t == "reply_end":   
                    bot_falando.clear(); ultima = time.monotonic()
                    if once: stop.set()
                elif t == "timing":      print(ev)
                elif t == "state":       pass
                elif t == "error":       print("⚠", ev["text"])
                
        async def watchdog():
            while idle_s and not stop.is_set():
                await asyncio.sleep(0.5)
                if not bot_falando.is_set() and time.monotonic() - ultima > idle_s:
                    print("\n💤 silêncio — voltando pro wake") 
                    stop.set()
        tarefas = [asyncio.create_task(c()) for c in (enviar_mic, receber, watchdog)]
        try:
            await stop.wait() 
        finally:
            for t in tarefas: t.cancel()
            stop.set()
            player.close()
            try: await ws.send(dumps({"type": "bye"}))
            except Exception: pass


async def _aac_pra_pcm16(aac_path: str) -> bytes:
    """ffmpeg: AAC → PCM16 16k mono (raw). Requer `pkg install ffmpeg` no Termux."""
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "quiet", "-i", aac_path, "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1",
        stdout=asyncio.subprocess.PIPE)
    pcm, _ = await p.communicate()
    return pcm


async def conversar_termux(cfg, *, once=False):
    """Voz por TURNO no Termux (celular): grava (AAC) → PCM16 → feed no /ws/voice → toca a resposta.
    Suporta once (1 turno) e multi-turno (loop até end-phrase). O wake no celular é separado (botão)."""
    import os
    from companion.audio import capturar_turno, tocar, TTS_SAMPLE_RATE
    url = f"{cfg.server_ws_url}/ws/voice"
    aac = os.path.expanduser("~/brazaia/turno.aac")
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        while True:
            await capturar_turno()                       # grava o turno (deixa o .aac no disco)
            pcm = await _aac_pra_pcm16(aac)              # AAC → PCM16 16k
            for i in range(0, len(pcm), 3200):          # feed em pedaços
                await ws.send(pcm[i:i + 3200])
            await ws.send(b"\x00" * 48000)              # ~1,5s de silêncio → VAD do server fecha o turno

            audio = bytearray(); texto = ""
            async for msg in ws:                        # recebe a resposta deste turno
                if isinstance(msg, (bytes, bytearray)):
                    audio += msg
                    continue
                ev = loads(msg); t = ev.get("type")
                if   t == "final":       texto = ev["text"]; print("🫵", texto)
                elif t == "reply_delta": print(ev["text"], end="", flush=True)
                elif t == "reply_end":   print(); break
                elif t == "error":       print("⚠", ev["text"]); break

            if audio:
                await tocar(bytes(audio), TTS_SAMPLE_RATE)   # toca por arquivo (termux-media-player)
            if once or any(p in texto.lower() for p in cfg.end_phrases):
                break
        try:
            await ws.send(dumps({"type": "bye"}))
        except Exception:
            pass
