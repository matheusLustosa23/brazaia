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
