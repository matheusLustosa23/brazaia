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
import asyncio, os, sys, time
import websockets
from companion._json import dumps, loads
from companion.config import load_config
from companion.tools.capture_handler import CAMERAS
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
        hs = {"name": cfg.device_name, "handlers": runtime.list_tools()}
        if CAMERAS:
            hs["cameras"] = CAMERAS
        await ws.send(dumps(hs))
        log(f"🔌 conectado: {cfg.device_id} @ {uri}")
        bem = loads(await ws.recv())
        if bem.get("type") == "welcome":
            log(f"❇️  handshake ok — tools no server: {bem.get('tools')}")
        estado.device_online = True; estado.device_status = "online"   # rodapé: 🛰 on
        async for msg in ws:
            action = loads(msg)
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
