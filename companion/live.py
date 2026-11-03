"""companion/live.py — MODO LIVE: conversa por voz contínua com o painel (companion/ui/hud.py).

Fluxo: mic (PCM16 16k contínuo) → /ws/voice?session_id=… → o server transcreve, detecta o fim da fala,
responde pelo agente e devolve áudio (PCM 24k) + eventos → o painel mostra e o player toca.
A sessão é a MESMA do CLI: ao sair (q/Esc) o CLI continua nela e mostra os turnos falados.

O server só manda state=detectando; os outros estados o cliente deduz:
  partial → captando (você falando) · final → pensando · 1º áudio → falando · fim do áudio → detectando

Eco/barge-in:
  sem fone (padrão) — HALF-DUPLEX: o mic fica mudo enquanto o agente fala (o alto-falante não vira "fala").
  fone (/live fone) — BARGE-IN: falar por cima corta o áudio na hora e manda {"type":"barge"} pro server.
"""
import asyncio, os, sys, threading, time
from companion._json import dumps, loads
from companion.ui import hud

SR, TTS_SR = 16_000, 24_000
FRAME = SR * 20 // 1000                 # 20 ms por bloco do mic
BARGE_RMS = 0.18                        # nível (0..1 do hud.rms) que conta como "falando por cima"
BARGE_FRAMES = 8                        # ~160 ms seguidos acima do nível → barge-in


def _mic_device():
    """MIC_DEVICE do env; 'pulse' (default do Linux) não existe no Windows → cai no mic padrão."""
    dev = os.getenv("MIC_DEVICE", "pulse" if sys.platform.startswith("linux") else "")
    if not dev:
        return None
    return int(dev) if dev.isdigit() else dev


class Player:
    """Saída gapless por callback: feed() enfileira, o callback consome. clear() corta na hora (barge-in).

    busy() NÃO pode olhar só o nosso buffer: o do sistema (PulseAudio no note) puxa o áudio bem antes de ele
    SOAR — o nosso esvaziava com segundos de fala pela frente, o painel voltava pro radar e o mic reabria
    em cima da voz. Então o callback, ao ENTREGAR cada trecho pro dispositivo, empurra um "relógio de fim":
    o trecho começa a soar quando o anterior acabar (ou daqui a `latency`, se estava parado) e dura o que dura."""

    def __init__(self) -> None:
        import sounddevice as sd
        self.buf = bytearray(); self.lock = threading.Lock()
        self._fim = 0.0                                   # monotonic() em que o último trecho termina de SOAR
        self.stream = sd.RawOutputStream(samplerate=TTS_SR, channels=1, dtype="int16", blocksize=0, callback=self._cb)
        self._lat = float(getattr(self.stream, "latency", 0.0) or 0.0)   # o que o dispositivo segura antes de soar
        self.stream.start()

    def _cb(self, outdata, frames, t, status) -> None:
        need = frames * 2
        with self.lock:
            n = min(need, len(self.buf)); outdata[:n] = bytes(self.buf[:n]); del self.buf[:n]
            if n:                                         # este trecho soa DEPOIS do que já está na fila do dispositivo
                self._fim = max(self._fim, time.monotonic() + self._lat) + n / 2 / TTS_SR
        if n < need:
            outdata[n:] = b"\x00" * (need - n)

    def feed(self, pcm: bytes) -> None:
        with self.lock: self.buf.extend(pcm)

    def clear(self) -> None:
        with self.lock: self.buf.clear(); self._fim = time.monotonic()

    def busy(self) -> bool:
        with self.lock:
            return len(self.buf) > 0 or time.monotonic() < self._fim

    def close(self) -> None:
        try: self.stream.stop(); self.stream.close()
        except Exception: pass


async def rodar_live(cfg, session_id: str | None, *, fone: bool = False, info: dict | None = None) -> str | None:
    """Abre o painel e conversa por voz na sessão até q/Esc. Devolve o session_id usado (o server cria se None)."""
    import sounddevice as sd
    import websockets

    ev = hud.EstadoVoz()
    ev.info = {"sessao": (session_id or "nova")[:8], "audio": "fone" if fone else "alto-falante", **(info or {})}
    ev.set("aguardando", "conectando no server…")
    sid = session_id
    loop = asyncio.get_running_loop()
    mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
    player = Player()
    respondendo = False                   # entre o final e o fim do áudio da resposta
    mudo = False                          # depois de um barge-in: ignora o resto do áudio da resposta cortada

    def on_mic(indata, frames, t, status) -> None:
        b = bytes(indata)
        try: loop.call_soon_threadsafe(mic_q.put_nowait, b)
        except Exception: pass            # fila cheia (loop atrasado) → descarta o bloco

    try:
        mic = sd.RawInputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME,
                                device=_mic_device(), callback=on_mic)
    except Exception:
        player.close()                    # sem mic → não deixa o alto-falante aberto
        raise
    url = f"{cfg.server_ws_url}/ws/voice" + (f"?session_id={session_id}" if session_id else "")

    async def enviar(ws) -> None:
        nonlocal mudo, respondendo
        acima = 0
        while not ev.quit:
            b = await mic_q.get()
            nivel = hud.rms(b)
            falando_ia = player.busy() or ev.estado == "falando"
            if not falando_ia:
                if ev.estado in ("aguardando", "detectando", "captando"):
                    ev.nivel = nivel                                  # anel/sinal acompanham a SUA voz
                acima = 0
                await ws.send(b)
                continue
            if not fone:                                              # half-duplex: não manda o eco da própria fala
                continue
            acima = acima + 1 if nivel >= BARGE_RMS else 0
            if acima >= BARGE_FRAMES:                                 # falou por cima → corta e avisa o server
                acima = 0; player.clear(); mudo = True; respondendo = False
                ev.reply = ""; ev.set("captando", "te ouvindo… (interrompeu)")
                await ws.send(dumps({"type": "barge"}))
            await ws.send(b)

    async def receber(ws) -> None:
        nonlocal sid, mudo, respondendo
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                if mudo:
                    continue
                player.feed(bytes(msg)); ev.nivel = hud.rms(bytes(msg))
                if ev.estado != "falando":
                    ev.set("falando", "falando…")
                continue
            m = loads(msg); ty = m.get("type")
            if ty == "session":
                sid = m.get("session_id") or sid; ev.info["sessao"] = (sid or "nova")[:8]
            elif ty == "state":
                if not respondendo:
                    ev.set("detectando", "pode falar")
            elif ty == "partial":
                if not respondendo:
                    ev.texto = m.get("text", ""); ev.set("captando", "ouvindo… (o silêncio encerra)")
            elif ty == "final":
                ev.texto = m.get("text", ""); ev.reply = ""; respondendo = True; mudo = False
                ev.set("pensando", "pensando…")
            elif ty == "reply_start":
                mudo = False
            elif ty == "reply_delta":
                ev.reply = (ev.reply + m.get("text", "")).replace("\n\n", " · ").replace("\n", " ")
            elif ty == "passo":                                       # tool do agente: ▸ rodando · ✔/✗ resultado
                desc = m.get("porque") or m.get("tool") or "ferramenta"
                if m.get("estado") == "executando":
                    ev.set("pensando", f"▸ {desc}")
                else:
                    marca = "✔" if m.get("estado") == "ok" else "✗"
                    ev.log = f"{marca} {desc} → {m.get('detalhe', '')}"
            elif ty == "reply_end":
                respondendo = False
            elif ty == "error":
                ev.log = f"⚠ {m.get('text', '')}"

    async def volta_a_ouvir() -> None:
        """Quando a resposta terminou E o áudio acabou de tocar → volta pro 'pode falar'."""
        while not ev.quit:
            await asyncio.sleep(0.1)
            if not respondendo and not player.busy() and ev.estado in ("falando", "pensando"):
                ev.nivel = 0.0; ev.set("detectando", "pode falar")

    tarefas: list[asyncio.Task] = []
    render = asyncio.create_task(hud.render_loop(ev))
    try:
        async with websockets.connect(url, max_size=None, ping_interval=None,
                                      proxy=os.getenv("SOCKS_PROXY") or None) as ws:
            mic.start()
            ev.set("detectando", "conectado ✓ — pode falar")
            tarefas = [asyncio.create_task(enviar(ws)), asyncio.create_task(receber(ws)),
                       asyncio.create_task(volta_a_ouvir())]
            await asyncio.wait({render, *tarefas}, return_when=asyncio.FIRST_COMPLETED)   # q/Esc ou a conexão caiu
            ev.quit = True
            try: await ws.send(dumps({"type": "bye"}))
            except Exception: pass
    except Exception as e:                                            # não derruba o CLI: mostra no painel e sai
        ev.set("aguardando", f"⚠ {type(e).__name__}: {e}")
        await asyncio.sleep(2.5)
        raise
    finally:
        ev.quit = True
        for t in tarefas: t.cancel()
        await asyncio.gather(render, return_exceptions=True)        # restaura o terminal antes de voltar pro CLI
        try: mic.stop(); mic.close()
        except Exception: pass
        player.close()
    return sid


async def _tocar_termux(pcm: bytes, rate: int) -> None:
    """Toca no termux-media-player e só volta quando ELE parar de tocar. O `tocar` do audio.py espera só a
    duração calculada; o player do Android demora a começar → o painel voltava pro radar (e o mic regravava)
    com a fala ainda tocando. Aqui pergunta ao player (`info`) até sair do 'Playing'."""
    import time, wave
    from companion.audio import _DIR
    from companion.plataform import _run_sync
    os.makedirs(_DIR, exist_ok=True)
    wav = f"{_DIR}/resposta_live.wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    await _run_sync(["termux-media-player", "play", wav])
    dur = len(pcm) / 2 / rate
    t0 = time.monotonic(); tocou = False
    while time.monotonic() - t0 < dur + 20:                       # teto: a duração + folga p/ a demora do player
        try:
            p = await asyncio.create_subprocess_exec("termux-media-player", "info",
                                                     stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out = (await asyncio.wait_for(p.communicate(), 5))[0].decode(errors="ignore")
        except Exception:                                         # sem 'info' → volta ao jeito antigo (duração)
            await asyncio.sleep(max(0.0, dur + 0.3 - (time.monotonic() - t0))); return
        if "Playing" in out:
            tocou = True
        elif tocou or time.monotonic() - t0 > dur + 3:           # parou depois de tocar (ou nunca começou)
            return
        await asyncio.sleep(0.4)


async def rodar_live_termux(cfg, session_id: str | None, *, info: dict | None = None) -> str | None:
    """LIVE no celular (Termux): mesmo painel e mesma sessão, mas por TURNOS — o Termux não dá áudio contínuo
    (termux-microphone-record grava em arquivo). Ciclo: grava → Enter envia (AAC cru; o server decodifica,
    caminho já validado na voz do celular) → resposta falada → volta a gravar sozinho. q sai."""
    import websockets
    from companion.audio import GravacaoLivre

    ev = hud.EstadoVoz()
    ev.info = {"sessao": (session_id or "nova")[:8], "audio": "por turno",
               "dica": "Enter envia · q volta pro chat", **(info or {})}
    ev.set("aguardando", "conectando no server…")
    sid = session_id
    url = f"{cfg.server_ws_url}/ws/voice" + (f"?session_id={session_id}" if session_id else "")

    async def anima(ate: asyncio.Event, base: float) -> None:
        """Sem PCM ao vivo no Termux → o anel/sinal pulsam sozinhos enquanto grava ou fala."""
        import math, time
        t0 = time.monotonic()
        while not ate.is_set() and not ev.quit:
            ev.nivel = base + 0.25 * abs(math.sin((time.monotonic() - t0) * 5)); await asyncio.sleep(0.05)
        ev.nivel = 0.0

    async def esperar_enter() -> bool:
        """True = Enter (envia) · False = q (sai). As teclas chegam pela fila do render_loop."""
        ev.teclas.clear()
        while not ev.quit:
            if any(k in ("\r", "\n") for k in ev.teclas):
                ev.teclas.clear(); return True
            await asyncio.sleep(0.05)
        return False

    async def turno(ws) -> bool:
        """Um ciclo completo. False = o usuário saiu (q)."""
        nonlocal sid
        grav = GravacaoLivre()
        await grav.iniciar()
        ev.texto = ""; ev.set("captando", "🎙 gravando — fale e aperte Enter")
        fim = asyncio.Event(); asyncio.create_task(anima(fim, 0.25))
        enviar = await esperar_enter()
        fim.set()
        aac = await grav.parar()                                  # sempre para (libera o mic do Termux)
        if not enviar:
            return False
        ev.set("pensando", f"enviando {len(aac) // 1024} KB…")
        await ws.send(dumps({"type": "audio_turn", "fmt": "aac"}))
        await ws.send(aac)
        audio = bytearray()
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=90)
            if isinstance(msg, (bytes, bytearray)):
                audio += msg; continue
            m = loads(msg); ty = m.get("type")
            if ty == "session":
                sid = m.get("session_id") or sid; ev.info["sessao"] = (sid or "nova")[:8]
            elif ty == "final":
                ev.texto = m.get("text", ""); ev.reply = ""; ev.set("pensando", "pensando…")
            elif ty == "reply_delta":
                ev.reply = (ev.reply + m.get("text", "")).replace("\n\n", " · ").replace("\n", " ")
            elif ty == "passo":
                desc = m.get("porque") or m.get("tool") or "ferramenta"
                if m.get("estado") == "executando":
                    ev.set("pensando", f"▸ {desc}")
                else:
                    ev.log = f"{'✔' if m.get('estado') == 'ok' else '✗'} {desc} → {m.get('detalhe', '')}"
            elif ty == "error":
                ev.log = f"⚠ {m.get('text', '')}"
            elif ty == "reply_end":
                break
        if audio and not ev.quit:
            ev.set("falando", "falando…")
            fim = asyncio.Event(); asyncio.create_task(anima(fim, 0.35))
            await _tocar_termux(bytes(audio), TTS_SR)             # espera o PLAYER terminar (não só a duração)
            fim.set()
        return not ev.quit

    async def conversa() -> None:
        nonlocal sid
        async with websockets.connect(url, max_size=None, ping_interval=None,
                                      proxy=os.getenv("SOCKS_PROXY") or None) as ws:
            m = loads(await asyncio.wait_for(ws.recv(), timeout=15))   # 1º evento = a sessão em uso
            if m.get("type") == "session":
                sid = m.get("session_id") or sid; ev.info["sessao"] = (sid or "nova")[:8]
            while await turno(ws):
                pass
            try: await ws.send(dumps({"type": "bye"}))
            except Exception: pass

    render = asyncio.create_task(hud.render_loop(ev))
    tarefa = asyncio.create_task(conversa())
    try:
        await asyncio.wait({render, tarefa}, return_when=asyncio.FIRST_COMPLETED)
        if tarefa.done() and tarefa.exception():                  # mostra o erro no painel antes de sair
            e = tarefa.exception()
            ev.set("aguardando", f"⚠ {type(e).__name__}: {e}"); await asyncio.sleep(2.5)
            raise e  # type: ignore[misc]
    finally:
        ev.quit = True
        try:                                                      # deixa o turno PARAR a gravação (senão o mic do
            await asyncio.wait_for(asyncio.shield(tarefa), 5)     # Termux fica preso gravando) antes de cancelar
        except BaseException:
            pass
        tarefa.cancel()
        await asyncio.gather(render, tarefa, return_exceptions=True)
    return sid
