"""connect — presenca do device no server (/ws/device/{id}), RPC de tools.

O server empurra tool-calls ({request_id, name, arguments}); o runtime executa
LOCALMENTE e devolve {request_id, result}. Enquanto roda, o server pode agir neste
aparelho (notificar, tirar foto, etc.).

Roda SILENCIOSO em background, logando em ~/ts/connect.log:
  python -m companion.connect            # inicia em BG (silencioso) e volta o prompt
  python -m companion.connect status     # estado: conectado / reconectando / parado
  python -m companion.connect stop       # desconecta (mata o connect; p/ testar)
  python -m companion.connect --watch    # acompanha os logs (tail -f)
  python -m companion.connect --fg       # primeiro plano (debug; o supervisor usa este)

CS2b (TODO): no Termux (tailscaled userspace), sair pelo SOCKS5 (localhost:1055) p/
             alcancar o server SEM o app do Tailscale.
"""
import asyncio, os, subprocess, sys, time
import websockets
from companion._json import dumps, loads
from companion.config import load_config
from companion.tools.capture_handler import CAMERAS
from companion import localizacao, permissoes
from companion.runtime import runtime
from companion.state import estado                 # device_status p/ o rodapé do CLI (embed); inofensivo standalone

LOG = os.path.expanduser("~/ts/connect.log")
PIDFILE = os.path.expanduser("~/.braza_companion.pid")   # cross-platform: braza e o CLI leem o mesmo


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ── gestão de processo CROSS-PLATFORM (Windows: tasklist/taskkill; POSIX: os.kill) ──
def _pid_vivo(pid: int) -> bool:
    if os.name == "nt":
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def _matar(pid: int) -> None:
    import subprocess, signal
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)   # /T mata a árvore
    else:
        try: os.kill(pid, signal.SIGTERM)
        except OSError: pass


def _pid_salvo() -> int | None:
    try:
        return int(open(PIDFILE).read().strip())
    except Exception:
        return None


async def _sessao(cfg) -> None:
    """Uma conexao: handshake -> escuta tool-calls -> responde. Retorna quando a conexao cai."""
    uri = f"{cfg.server_ws_url}/ws/device/{cfg.device_id}"
    async with websockets.connect(uri, max_size=None, ping_timeout=120,
                                  proxy=os.getenv("SOCKS_PROXY") or None) as ws:   # max_size=None: imagem (base64) passa de 1MB e o default derrubava a conexão
        hs = {"name": cfg.device_name, "handlers": runtime.list_tools(),
              "plataforma": localizacao.plataforma(), "permissoes": permissoes.carregar(),
              "estado": localizacao.estado_salvo() or await asyncio.to_thread(localizacao.ler_estado)}
        if CAMERAS:
            hs["cameras"] = CAMERAS
        await ws.send(dumps(hs))
        log(f"🔌 conectado: {cfg.device_id} @ {uri}")
        bem = loads(await ws.recv())
        if bem.get("type") == "welcome":
            log(f"❇️  handshake ok — tools no server: {bem.get('tools')}")
            await _talvez_atualizar(cfg, bem.get("companion") or {})
        estado.device_online = True; estado.device_status = "online"   # rodapé: 🛰 on
        fila = asyncio.create_task(_esvaziar_fila(ws))
        try:
            await _escutar(ws)
        finally:
            fila.cancel()


SUPERVISIONADO = False        # True só no `connect --fg` (supervisor/serviço): aí pode sair pra atualizar


async def _talvez_atualizar(cfg, novo: dict) -> None:
    """O servidor anunciou outra versão do pacote → baixa, instala e sai (o supervisor sobe a nova em ~30 s).
    Só quando instalado como pacote E supervisionado: rodando do repo ("dev") ou dentro do CLI, nunca."""
    import companion
    v = novo.get("versao")
    if not v or companion.__version__ in ("dev", v) or not SUPERVISIONADO:
        return
    import httpx
    from companion import DADOS
    base = cfg.server_ws_url.replace("wss://", "https://").replace("ws://", "http://").split("/api/")[0]
    destino = os.path.join(DADOS, "pacote", novo["arquivo"])
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    log(f"⬆️  atualizando companion {companion.__version__} → {v}…")
    try:
        async with httpx.AsyncClient(timeout=120, proxy=os.getenv("SOCKS_PROXY") or None) as http:
            r = await http.get(base + novo["url"])
            r.raise_for_status()
        with open(destino, "wb") as f:
            f.write(r.content)
        # --no-deps: o download já veio pelo SOCKS (o pip não fala SOCKS sem PySocks); deps novas = instalar à mão
        p = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "pip", "install", "--no-deps",
                                    "--force-reinstall", "-q", destino], capture_output=True, text=True, timeout=300)
    except Exception as e:
        log(f"⚠️  atualização falhou ({type(e).__name__}: {e}) — sigo na versão {companion.__version__}")
        return
    if p.returncode != 0:
        log(f"⚠️  pip falhou: {(p.stderr or p.stdout)[-300:]} — sigo na versão {companion.__version__}")
        return
    log(f"✅ companion {v} instalado — reiniciando (o supervisor sobe a nova versão)")
    subprocess.run(["pkill", "-f", "companion.localizacao rastrear"], check=False)   # rastreador volta com a nova
    os._exit(0)


async def _esvaziar_fila(ws) -> None:
    """Manda ao server o que o rastreador deixou na fila (e a bateria), a cada 30 s enquanto conectado.
    Só apaga da fila no 'ack' (em _escutar): conexão caiu no meio = reenvia na próxima, sem duplicar no server.
    BLINDADA (04/11): era uma tarefa solta — uma exceção a matava calada e a conexão seguia 'online' sem mandar
    nada (pontos de 13:31 a 15:57 só chegaram quando o connect foi reiniciado). Agora erro = log + tenta de novo;
    3 seguidos = fecha a conexão (o laço do conectar() reconecta e cria a tarefa de novo)."""
    ultimo_estado = 0.0
    ultima_leitura = 0.0                            # device sem bateria (PC) devolve vazio: não ler a cada 30 s
    falhas = 0
    while True:
        try:
            pontos = localizacao.pendentes()
            if pontos:
                await ws.send(dumps({"type": "localizacao", "pontos": pontos}))
                log(f"📍 {len(pontos)} ponto(s) da fila enviados")
                if len(pontos) >= 200:              # voltou a conexão com muita coisa acumulada: esvazia em sequência
                    falhas = 0
                    await asyncio.sleep(5)
                    continue
            est = localizacao.estado_salvo()
            if time.time() - (est or {}).get("quando", 0) > 300 and time.time() - ultima_leitura > 300:
                ultima_leitura = time.time()        # leitura velha (rastreador parado/atrasado): lê aqui
                novo = await asyncio.to_thread(localizacao.ler_estado)
                if novo:
                    localizacao.salvar_estado(novo)
                    est = localizacao.estado_salvo()
            if est and est.get("quando", 0) > ultimo_estado:
                ultimo_estado = est["quando"]
                await ws.send(dumps({"type": "estado", "estado": {k: v for k, v in est.items() if k != "quando"},
                                     "quando": est["quando"]}))
            falhas = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            falhas += 1
            log(f"⚠️  envio da fila falhou ({falhas}/3): {type(e).__name__}: {e}")
            if falhas >= 3:
                log("🔁 fila travada — fechando a conexão pra reconectar")
                await ws.close()
                return
        await asyncio.sleep(30)                     # o rastreador gera até 1 ponto/30 s em movimento


async def _escutar(ws) -> None:
    async for msg in ws:
        action = loads(msg)
        if action.get("type") == "ack":                         # server gravou → tira da fila
            localizacao.remover(action.get("ids") or [])
            continue
        if "request_id" in action and "name" in action:        # tool-call do server
            rid, nome = action["request_id"], action["name"]
            log(f"⚡ tool {nome} (id={rid})")
            resultado = await runtime.execute(action)
            await ws.send(dumps({"request_id": rid, "result": resultado}))
            log(f"📤 respondido id={rid}")


async def conectar(cfg=None) -> None:
    """Mantem o device conectado com reconexao automatica (backoff)."""
    cfg = cfg or load_config()
    backoff = 1
    while True:
        try:
            await _sessao(cfg)
            backoff = 1                                             # saiu limpo -> reseta
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            log(f"🔁 caiu ({type(e).__name__}) — reconectando em {backoff}s")
        except Exception as e:
            log(f"💥 {type(e).__name__}: {e}")
        estado.device_online = False; estado.device_status = "reconectando"   # caiu/server fechou -> rodapé
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)                             # 1->2->4...->30s


def _watch() -> None:
    """Acompanha os logs do connect (tail -f)."""
    import subprocess
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "a").close()                                         # garante que o arquivo existe
    print(f"📡 seguindo {LOG} (Ctrl+C pra sair)\n", flush=True)
    try:
        subprocess.run(["tail", "-n", "60", "-F", LOG])
    except KeyboardInterrupt:
        pass


def _start_bg() -> None:
    """Inicia o connect DESTACADO em background e confirma: 'conectado' ou 'falhou a conectar'.
    (No Windows o braza é o lançador preferido — Minimized, p/ window-station do open_image/browser.)"""
    import subprocess
    pid = _pid_salvo()
    if pid and _pid_vivo(pid):
        print("🟢 connect ja esta rodando (use: status / --watch / stop)")
        return
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    pos = os.path.getsize(LOG) if os.path.exists(LOG) else 0      # le so o que ESTE start produzir
    logf = open(LOG, "a")
    kw = {"creationflags": subprocess.CREATE_NEW_CONSOLE} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen([sys.executable, "-m", "companion.connect", "--fg"],
                         stdout=logf, stderr=logf, **kw)
    try: open(PIDFILE, "w").write(str(p.pid))
    except Exception: pass
    for _ in range(16):                                          # espera o 1o resultado (~8s)
        time.sleep(0.5)
        with open(LOG) as f:
            f.seek(pos); novo = f.read()
        if "conectado:" in novo:
            print("✅ conectado"); return
        if "💥" in novo or "caiu" in novo:
            motivo = next((l for l in novo.splitlines() if "💥" in l or "caiu" in l), "").strip()
            print(f"❌ falhou a conectar — {motivo}"); return
    print("⚠ sem resposta em 8s — acompanhe: python -m companion.connect --watch")


def _status() -> None:
    """Mostra o estado da conexao: conectado / reconectando / parado."""
    pid = _pid_salvo()
    rodando = bool(pid and _pid_vivo(pid))
    ultima = ""
    if os.path.exists(LOG):
        linhas = [l for l in open(LOG, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        ultima = linhas[-1] if linhas else ""
    if not rodando:
        print("⚫ parado (connect nao esta rodando)")
    elif "conectado:" in ultima:
        print(f"🟢 conectado — {ultima}")
    elif "caiu" in ultima or "💥" in ultima:
        print(f"🟡 reconectando — {ultima}")
    else:
        print(f"⚪ rodando — {ultima or '(sem log ainda)'}")


def _stop() -> None:
    """Desconecta: mata o connect (--fg) pelo PID salvo. Se o supervisor estiver rodando, reergue em ~30s."""
    pid = _pid_salvo()
    if pid and _pid_vivo(pid):
        _matar(pid)
        try: os.remove(PIDFILE)
        except OSError: pass
        print("⏹ connect desconectado")
    else:
        print("⚫ connect ja estava parado")


if __name__ == "__main__":
    if "status" in sys.argv:
        _status()
    elif "stop" in sys.argv:
        _stop()
    elif "--watch" in sys.argv:
        _watch()
    elif "--fg" in sys.argv:
        SUPERVISIONADO = True
        try:
            open(PIDFILE, "w").write(str(os.getpid()))   # authoritative: quem subir o --fg registra o PID
        except Exception:
            pass
        try:
            asyncio.run(conectar())
        except KeyboardInterrupt:
            pass
    else:
        _start_bg()
