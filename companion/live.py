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
        self.clear()                                      # sair (q) corta na hora: abort descarta o que o
        try: self.stream.abort(); self.stream.close()     # dispositivo ainda segura (stop esperaria tocar tudo)
        except Exception: pass


IDLE_WAKE_S = 30.0                      # wake: 30 s sem ninguém falar → volta pro STANDBY


def _modelos_wake() -> None:
    """O openwakeword precisa de 2 modelos-BASE (melspectrogram + embedding). A 0.4 já traz os dois no pacote;
    as mais novas NÃO (o pip vem sem eles → NO_SUCHFILE). Confere a pasta do pacote e, se faltar, baixa só esses
    (+ VAD) pela função da própria lib — os wake words prontos de outras palavras ficam de fora."""
    import openwakeword
    pasta = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    if os.path.exists(os.path.join(pasta, "melspectrogram.onnx")):
        return
    import openwakeword.utils
    baixar = getattr(openwakeword.utils, "download_models", None)
    if baixar is None:
        raise RuntimeError(f"faltam os modelos-base do openwakeword em {pasta} e esta versão não sabe baixar")
    baixar(model_names=["__so_os_modelos_base__"])


def _saudacao(voz: str) -> bytes:
    """PCM 24k de uma saudação gravada (companion/assets/greeting_<voz>_N.wav) — b"" se não houver."""
    import glob, random, wave
    arqs = glob.glob(f"companion/assets/greeting_{voz}_*.wav")
    if not arqs:
        return b""
    with wave.open(random.choice(arqs), "rb") as w:
        return w.readframes(w.getnframes())


async def rodar_live(cfg, session_id: str | None, *, fone: bool = False, modo: str = "continuo",
                     info: dict | None = None) -> str | None:
    """Abre o painel e conversa por voz na sessão. Devolve o session_id usado (o server cria se None).

    modo: continuo — sempre ouvindo, até q/Esc.
          wake     — STANDBY até ouvir "braza" (detecção LOCAL, openwakeword) → saudação → conversa;
                     30 s de silêncio → volta pro STANDBY. q/Esc sai.
          once     — um turno (você fala, ele responde) e volta sozinho pro chat."""
    import sounddevice as sd
    import websockets

    ev = hud.EstadoVoz()
    ev.info = {"sessao": (session_id or "nova")[:8],
               "audio": ("fone" if fone else "alto-falante") + ("" if modo == "continuo" else f" · {modo}"), **(info or {})}
    ev.set("aguardando", "conectando no server…")
    sid = session_id
    loop = asyncio.get_running_loop()
    mic_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
    player = Player()
    respondendo = False                   # entre o final e o fim do áudio da resposta
    mudo = False                          # depois de um barge-in: ignora o resto do áudio da resposta cortada
    turnos = 0                            # respostas completas nesta conversa (o once sai depois da 1ª)
    atividade = time.monotonic()          # última vez que alguém falou (wake: base do "30 s de silêncio")

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
        nonlocal sid, mudo, respondendo, turnos, atividade
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                if mudo:
                    continue
                player.feed(bytes(msg)); ev.nivel = hud.rms(bytes(msg)); atividade = time.monotonic()
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
                atividade = time.monotonic()
                if not respondendo:                                   # você começou a falar de novo: a caixa mostra
                    ev.texto = m.get("text", ""); ev.reply = ""       # só a fala nova (a resposta anterior sai)
                    ev.set("captando", "ouvindo… (o silêncio encerra)")
            elif ty == "final":
                ev.texto = m.get("text", ""); ev.reply = ""; respondendo = True; mudo = False
                atividade = time.monotonic(); ev.set("pensando", "pensando…")
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
                respondendo = False; turnos += 1; atividade = time.monotonic()
            elif ty == "error":
                ev.log = f"⚠ {m.get('text', '')}"

    async def volta_a_ouvir() -> None:
        """Quando a resposta terminou E o áudio acabou de tocar → volta pro 'pode falar'."""
        while not ev.quit:
            await asyncio.sleep(0.1)
            if not respondendo and not player.busy() and ev.estado in ("falando", "pensando"):
                ev.nivel = 0.0; ev.set("detectando", "pode falar")

    async def vigia() -> None:
        """Encerra ESTA conversa: once → depois da 1ª resposta tocada · wake → 30 s sem ninguém falar."""
        while not ev.quit:
            await asyncio.sleep(0.2)
            ocioso = not respondendo and not player.busy()
            if modo == "once" and turnos >= 1 and ocioso:
                return
            if modo == "wake" and ocioso and time.monotonic() - atividade >= IDLE_WAKE_S:
                return
        return

    async def conversa() -> None:
        """Uma conexão com o /ws/voice na sessão atual, até q/Esc ou a vigia encerrar."""
        nonlocal respondendo, mudo, turnos, atividade
        respondendo = mudo = False; turnos = 0; atividade = time.monotonic()
        while not mic_q.empty():                                      # descarta o áudio velho (o "braza", a saudação)
            mic_q.get_nowait()
        url = f"{cfg.server_ws_url}/ws/voice" + (f"?session_id={sid}" if sid else "")
        async with websockets.connect(url, max_size=None, ping_interval=None,
                                      proxy=os.getenv("SOCKS_PROXY") or None) as ws:
            ev.set("detectando", "conectado ✓ — pode falar")
            tarefas = [asyncio.create_task(f(ws)) for f in (enviar, receber)] + \
                      [asyncio.create_task(volta_a_ouvir()), asyncio.create_task(vigia())]
            try:
                await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tarefas: t.cancel()
                try: await ws.send(dumps({"type": "bye"}))
                except Exception: pass

    async def standby(wake) -> bool:
        """wake: espera o "braza" no mic (local) e toca a saudação. False = saiu (q/Esc) no STANDBY."""
        ev.texto = ev.reply = ""; ev.nivel = 0.0
        while not mic_q.empty():                                      # descarta o que acumulou (carregando/conversa)
            mic_q.get_nowait()
        ev.set("aguardando", "diga \"braza\" pra acordar")
        async def blocos_80ms():                                      # o openwakeword quer blocos de 80 ms
            junto = b""
            while not ev.quit:
                junto += await mic_q.get()
                if len(junto) >= SR * 80 // 1000 * 2:
                    ev.nivel = hud.rms(junto) * 0.6
                    yield junto; junto = b""
        espera = asyncio.create_task(wake.wait_for_trigger(blocos_80ms()))
        while not espera.done():
            if ev.quit:
                espera.cancel(); return False
            await asyncio.sleep(0.1)
        if getattr(cfg, "greeting_enabled", True):
            pcm = _saudacao(getattr(cfg, "greeting_voice", "pm_santa"))
            if pcm:
                ev.set("falando", "acordei!"); player.feed(pcm)
                while player.busy() and not ev.quit:
                    ev.nivel = 0.5; await asyncio.sleep(0.05)
        return not ev.quit

    async def fluxo() -> None:
        if modo != "wake":
            await conversa(); return
        ev.set("aguardando", "carregando o wake word…")
        await asyncio.to_thread(_modelos_wake)                   # 1ª vez nesta máquina: baixa os modelos-base
        from companion.wake import WakeWord
        wake = await asyncio.to_thread(WakeWord, cfg.wake_models, cfg.wake_threshold)
        while not ev.quit:
            if not await standby(wake):
                return
            await conversa()

    render = asyncio.create_task(hud.render_loop(ev))
    principal = asyncio.create_task(fluxo())
    try:
        mic.start()
        await asyncio.wait({render, principal}, return_when=asyncio.FIRST_COMPLETED)   # q/Esc, once acabou ou erro
        if principal.done() and principal.exception():               # não derruba o CLI: mostra no painel e sai
            e = principal.exception()
            ev.set("aguardando", f"⚠ {type(e).__name__}: {e}"); await asyncio.sleep(2.5)
            raise e  # type: ignore[misc]
    finally:
        ev.quit = True
        principal.cancel()
        await asyncio.gather(render, principal, return_exceptions=True)   # restaura o terminal antes de voltar
        try: mic.stop(); mic.close()
        except Exception: pass
        player.close()
    return sid


_n_wav = 0

async def _tocar_termux(pcm: bytes, rate: int, parar=None) -> None:
    """Toca no termux-media-player e só volta quando ELE parar de tocar. O `tocar` do audio.py espera só a
    duração calculada; o player do Android demora a começar → o painel voltava pro radar (e o mic regravava)
    com a fala ainda tocando. Aqui pergunta ao player (`info`) até sair do 'Playing'."""
    import time, wave
    from companion.audio import _DIR
    from companion.plataform import _run_sync
    os.makedirs(_DIR, exist_ok=True)
    global _n_wav
    _n_wav = (_n_wav + 1) % 4                                     # alterna arquivos: o próximo trecho não sobrescreve o que toca
    wav = f"{_DIR}/resposta_live_{_n_wav}.wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    await _run_sync(["termux-media-player", "play", wav])
    dur = len(pcm) / 2 / rate
    t0 = time.monotonic(); tocou = False
    while time.monotonic() - t0 < dur + 20:                       # teto: a duração + folga p/ a demora do player
        if parar is not None and parar():                         # q → para o player na hora
            await _run_sync(["termux-media-player", "stop"]); return
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


async def rodar_live_termux(cfg, session_id: str | None, *, modo: str = "continuo",
                            info: dict | None = None) -> str | None:
    """LIVE no celular (Termux): mesmo painel e mesma sessão, mas por TURNOS — o Termux não dá áudio contínuo
    (termux-microphone-record grava em arquivo). Ciclo: grava → Enter envia (AAC cru; o server decodifica,
    caminho já validado na voz do celular) → resposta falada → volta a gravar sozinho. q sai.
    modo once: um ciclo só e volta pro chat. (wake não existe aqui: sem áudio contínuo não dá pra escutar o "braza".)"""
    import websockets
    from companion.audio import GravacaoLivre

    ev = hud.EstadoVoz()
    ev.info = {"sessao": (session_id or "nova")[:8], "audio": "por turno" + (" · once" if modo == "once" else ""),
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
        ev.texto = ev.reply = ""; ev.set("captando", "🎙 gravando — fale e aperte Enter")
        fim = asyncio.Event(); asyncio.create_task(anima(fim, 0.25))
        enviar = await esperar_enter()
        fim.set()
        aac = await grav.parar()                                  # sempre para (libera o mic do Termux)
        if not enviar:
            return False
        ev.set("pensando", f"enviando {len(aac) // 1024} KB…")
        await ws.send(dumps({"type": "audio_turn", "fmt": "aac"}))
        await ws.send(aac)
        fila: asyncio.Queue = asyncio.Queue()                     # trechos de áudio (1 por frase) na ordem
        async def tocador() -> None:
            """Toca cada frase assim que chega (não espera a resposta inteira). Junta o que acumulou enquanto a
            anterior tocava → menos pausas (o player do Android demora a começar cada arquivo)."""
            anim = asyncio.Event()
            while True:
                pcm = await fila.get()
                acabou = pcm is None
                pcm = pcm or b""
                while not fila.empty():
                    nxt = fila.get_nowait()
                    if nxt is None:
                        acabou = True; break
                    pcm += nxt
                if pcm and not ev.quit:
                    if ev.estado != "falando":
                        ev.set("falando", "falando…"); asyncio.create_task(anima(anim, 0.35))
                    await _tocar_termux(pcm, TTS_SR, parar=lambda: ev.quit)
                if acabou or ev.quit:
                    anim.set(); return
        tocando: asyncio.Task | None = None
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=90)
            if isinstance(msg, (bytes, bytearray)):
                fila.put_nowait(bytes(msg))
                if tocando is None:
                    tocando = asyncio.create_task(tocador())
                continue
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
        if tocando is not None:                                   # resposta completa: espera a fila terminar de tocar
            fila.put_nowait(None)
            await tocando
        return not ev.quit

    async def conversa() -> None:
        nonlocal sid
        async with websockets.connect(url, max_size=None, ping_interval=None,
                                      proxy=os.getenv("SOCKS_PROXY") or None) as ws:
            m = loads(await asyncio.wait_for(ws.recv(), timeout=15))   # 1º evento = a sessão em uso
            if m.get("type") == "session":
                sid = m.get("session_id") or sid; ev.info["sessao"] = (sid or "nova")[:8]
            while await turno(ws) and modo != "once":
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
        from companion.plataform import _run_sync              # q no meio da fala: o termux-media-player seguia tocando
        await _run_sync(["termux-media-player", "stop"])
    return sid
