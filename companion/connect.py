"""connect — presenca do device no server (/ws/device/{id}), RPC de tools.

O server empurra tool-calls ({request_id, name, arguments}); o runtime executa
LOCALMENTE e devolve {request_id, result}. Enquanto roda, o server pode agir neste
aparelho (notificar, tirar foto, etc.).

Roda SILENCIOSO em background, logando em ~/ts/connect.log:
  python -m companion.connect            # inicia em BG (silencioso) e volta o prompt
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

LOG = os.path.expanduser("~/ts/connect.log")


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


async def _sessao(cfg) -> None:
    """Uma conexao: handshake -> escuta tool-calls -> responde. Retorna quando a conexao cai."""
    uri = f"{cfg.server_ws_url}/ws/device/{cfg.device_id}"
    async with websockets.connect(uri) as ws:
        hs = {"name": cfg.device_name, "handlers": runtime.list_tools()}
        if CAMERAS:
            hs["cameras"] = CAMERAS
        await ws.send(dumps(hs))
        log(f"🔌 conectado: {cfg.device_id} @ {uri}")
        bem = loads(await ws.recv())
        if bem.get("type") == "welcome":
            log(f"❇️  handshake ok — tools no server: {bem.get('tools')}")
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
    """Inicia o connect DESTACADO em background e confirma: 'conectado' ou 'falhou a conectar'."""
    import subprocess
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    pos = os.path.getsize(LOG) if os.path.exists(LOG) else 0      # le so o que ESTE start produzir
    logf = open(LOG, "a")
    subprocess.Popen([sys.executable, "-m", "companion.connect", "--fg"],
                     stdout=logf, stderr=logf, start_new_session=True)
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


if __name__ == "__main__":
    if "--watch" in sys.argv:
        _watch()
    elif "--fg" in sys.argv:
        try:
            asyncio.run(conectar())
        except KeyboardInterrupt:
            pass
    else:
        _start_bg()
