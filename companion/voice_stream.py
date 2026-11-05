import asyncio, os, websockets, time
from companion._json import dumps, loads
from companion.audio import capture_chunks, GaplessPlayer

# proxy lido na hora da conexao (depois do load_config carregar o ~/.brazaia.env):
# Termux = socks5://localhost:1055 (tailscaled userspace); desktop = None (direto).

async def conversar(cfg, *, idle_s: float | None = None, once=False):
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_interval=None, proxy=os.getenv("SOCKS_PROXY") or None) as ws:
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


async def conversar_termux(cfg, *, once=False):
    """Voz por TURNO no Termux (celular): grava AAC → manda o AAC CRU pro server (que decodifica) → toca a resposta.
    SEM ffmpeg no celular. Suporta once (1 turno) e multi-turno (loop até end-phrase). Wake no celular é separado (botão)."""
    from companion.audio import capturar_turno, tocar, TTS_SAMPLE_RATE
    url = f"{cfg.server_ws_url}/ws/voice"
    async with websockets.connect(url, max_size=None, ping_interval=None, proxy=os.getenv("SOCKS_PROXY") or None) as ws:
        print(f"🔌 conectado em {url}", flush=True)
        while True:
            print("🎙  preparando mic…", flush=True)      # o "fale agora" vem do capturar_turno (mic já quente)
            aac = await capturar_turno()                 # bytes AAC (Termux) — SEM converter
            print(f"\n📤 enviando áudio ({len(aac)} bytes)…", flush=True)
            await ws.send(dumps({"type": "audio_turn", "fmt": "aac"}))   # avisa: o próximo binário é AAC
            await ws.send(aac)                           # manda o AAC cru → o server decodifica
            print("⏳ processando no server…", flush=True)

            audio = bytearray(); texto = ""
            try:
                while True:                             # recebe a resposta deste turno (c/ timeout p/ não travar)
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    if isinstance(msg, (bytes, bytearray)):
                        audio += msg
                        continue
                    ev = loads(msg); t = ev.get("type")
                    if   t == "final":       texto = ev["text"]; print(f"\n🫵 {texto}\n")
                    elif t == "reply_start": print("🤖 ", end="", flush=True)
                    elif t == "reply_delta": print(ev["text"], end="", flush=True)
                    elif t == "reply_end":   print("\n"); break
                    elif t == "error":       print(f"\n⚠ {ev['text']}\n"); break
            except asyncio.TimeoutError:
                print("\n⌛ sem resposta do server em 30s (áudio não detectado?)")

            if audio:
                await tocar(bytes(audio), TTS_SAMPLE_RATE)   # toca por arquivo (termux-media-player)
            if once or any(p in texto.lower() for p in cfg.end_phrases):
                break
        try:
            await ws.send(dumps({"type": "bye"}))
        except Exception:
            pass
