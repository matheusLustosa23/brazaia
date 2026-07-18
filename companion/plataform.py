"""Backends por SO (Termux · Linux · Windows · macOS).

Duas classes de ação — é isto que evita travar o fluxo:
  sync     — o processo faz o trabalho e MORRE sozinho. Esperar o exit code é
             o certo: é assim que sabemos que executou.
  detached — o processo ABRE UMA JANELA e fica vivo enquanto o usuário quiser.
             Esperar terminar = esperar o usuário fechar (foi o que travou com
             subprocess.run no xdg-open). Aqui "continua vivo depois da janela
             de graça" É o sinal de sucesso.
"""

import os, sys, shutil,  asyncio

_IS_TERMUX = shutil.which("termux-open") is not None
_GRACE = 1.0 

_SERVE_PORT = 8765
_conteudo: dict[str, tuple[str, bytes]] = {}     # rota -> (content-type, bytes)
_servidor_no_ar = False


def _asset(nome: str) -> str:
    return os.path.abspath(os.path.join("companion", "assets", "images", nome))

async def _reap(proc: asyncio.subprocess.Process):
    """Só espera o filho pra ele não virar <defunct> na tabela de processos.
    Sem isto, cada imagem aberta deixa um zumbi até o companion morrer."""
    try:
        await proc.wait()
    except Exception:
        pass

async def _startfile(alvo: str) -> str:
    """Windows: não é subprocesso, é ShellExecute — volta na hora, sem rc."""
    try:
        await asyncio.to_thread(os.startfile, alvo)  # type: ignore[attr-defined]
        return "ok"
    except OSError as e:
        return f"[erro] {e}"

async def _toast_bg(title: str, message: str) -> None:
    """win11toast BLOQUEIA até o usuário dispensar o toast — isso é DETACHED
    (a notificação fica viva enquanto ele quiser), não sync. Medido no Windows:
    com await, o notify só voltava depois de fechar o toast. Então dispara e
    segue — apareceu = sucesso. Esperar o dismiss é o mesmo erro do run/xdg-open."""
    try:
        from win11toast import toast # type: ignore[attr-defined]
        await asyncio.to_thread(toast, title, message, icon=_asset("braza_logo.ico"))
    except Exception as e:
        print(f"🔔 {title}: {message}  ({e})")

def _servir(rota: str, tipo: str, dados: bytes) -> str:
    """Guarda o conteúdo em memória e devolve a URL localhost que o abre.

    Existe porque o Chrome no Android recusa content:// (HTML e imagem) — testado
    e descartadas as alternativas (grant, /sdcard). localhost não passa por
    sandbox: o browser faz um GET num servidor que roda no próprio Termux.

    Em memória (sem arquivo em disco): zero content://, zero limpeza. Bind em
    127.0.0.1 → nada sai do aparelho. Sobe uma vez, na 1ª chamada (lazy).
    """
    global _servidor_no_ar
    _conteudo[rota] = (tipo, dados)
    if not _servidor_no_ar:
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                item = _conteudo.get(self.path.lstrip("/"))
                if not item:
                    self.send_error(404)
                    return
                tipo, dados = item
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(dados)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(dados)
            def log_message(self, format, *args):
                pass
            
        srv = HTTPServer(("127.0.0.1", _SERVE_PORT), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _servidor_no_ar = True
        
    return f"http://localhost:{_SERVE_PORT}/{rota}"

async def show_html(html: str) -> str:
    """Abre uma página no navegador do device. Termux → localhost; desktop → arquivo tmp."""
    if _IS_TERMUX:
        url = _servir("page.html", "text/html; charset=utf-8", html.encode("utf-8"))
        return await _run_detached(["termux-open-url", url])
    import tempfile
    caminho = os.path.join(tempfile.gettempdir(), "brazaia_page.html")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return await open_file(caminho)

async def show_image(png: bytes) -> str:
    """Abre uma imagem em tela cheia. Termux → localhost (Chrome dá zoom); desktop → viewer."""
    if _IS_TERMUX:
        url = _servir("img.png", "image/png", png)
        return await _run_detached(["termux-open-url", url])
    import tempfile
    caminho = os.path.join(tempfile.gettempdir(), "brazaia_img.png")
    with open(caminho, "wb") as f:
        f.write(png)
    return await open_file(caminho)

async def _run_sync(cmd: list[str], timeout: float = 10.0) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, 
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError:
        return f"[erro] comando não encontrado: {cmd[0]}"
    
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"[erro] {cmd[0]} travou (> {timeout}s)"
    if proc.returncode != 0:
        return f"[erro] {cmd[0]} rc={proc.returncode}: {(err or b'').decode(errors='replace')[:200]}"
    return "ok"

async def _run_detached(cmd: list[str]):
    """stderr=DEVNULL de propósito: ninguém lê o pipe depois da janela de graça,
    e pipe cheio (GTK adora cuspir warning) TRAVA o filho.
    start_new_session solta o filho do grupo do companion: restart/Ctrl+C aqui
    não mata a janela que o usuário está olhando.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True
        )
    except FileNotFoundError:
        return f"[erro] comando não encontrado: {cmd[0]}"
    try:
        await asyncio.wait_for(proc.wait(), timeout=_GRACE)
    except asyncio.TimeoutError:
        asyncio.create_task(_reap(proc))
        return "ok (aberto)"
    if proc.returncode != 0:
        return f"[erro] {cmd[0]} rc={proc.returncode}"
    return "ok"

async def open_file(path: str) -> str:
    """Visualizador/navegador padrão do SO → DETACHED (a janela fica viva)."""
    if _IS_TERMUX:
        return await _run_detached(["termux-open", path])
    if sys.platform == "win32":
        return await _startfile(path)
    if sys.platform == "darwin":
        return await _run_detached(["open", path])
    
    return await _run_detached(["xdg-open", path])

async def open_url(url: str) -> str:
    
    if _IS_TERMUX:
        return await _run_detached(["termux-open-url", url])
    if sys.platform == "win32":
        return await _startfile(url)
    if sys.platform == "darwin":
        return await _run_detached(["open", url])
    return await _run_detached(["xdg-open", url])

async def notify(title: str, message: str, image: str | None = None) -> str:
    """Notificação. Termux/Linux = SYNC (entrega e sai); Windows toast = DETACHED."""
    if _IS_TERMUX:
        return await _run_sync(
            ["termux-notification", "--title", title, "--content", message,"--image-path", image or _asset("braza_logo_full.png")]
        )
    if image:
        await open_file(image)
    if sys.platform == "win32":
            asyncio.create_task(_toast_bg(title, message))
            return "ok"        
    if shutil.which("notify-send"):
        return await _run_sync(
            ["notify-send", "-i", _asset("braza_logo.png"), title, message]
        )
    print(f"🔔 {title}: {message}")
    return "ok (print)"
    
  