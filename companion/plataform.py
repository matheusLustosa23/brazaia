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
    """Notificação → SYNC nos 3 SOs (o comando entrega e sai)."""
    if _IS_TERMUX:
        return await _run_sync(
            ["termux-notification", "--title", title, "--content", message,"--image-path", image or _asset("braza_logo_full.png")]
        )
    if image:
        await open_file(image)
    if sys.platform == "win32":
        try:
            from win11toast import toast
            # win11toast pode BLOQUEAR esperando o toast ser dispensado →
            # to_thread pra nunca segurar o event loop do companion.
            await asyncio.to_thread(toast, title, message, icon=_asset("braza_logo.ico"))
            return "ok"
        except Exception as e:
            print(f"🔔 {title}: {message}  ({e})")
            return "ok (print)"
    if shutil.which("notify-send"):
        return await _run_sync(
            ["notify-send", "-i", _asset("braza_logo.png"), title, message]
        )
    print(f"🔔 {title}: {message}")
    return "ok (print)"
    
  