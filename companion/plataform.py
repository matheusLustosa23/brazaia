import os, sys, shutil, subprocess
from typing import Callable, cast
_IS_THERMUX = shutil.which("termux-open") is not None


def _run(command) -> None:
    subprocess.run(command, capture_output=True)

def open_file(path: str) -> None:
    if _IS_THERMUX:
        _run(["termux-open", path])
    elif sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        _run(["open", path])
    else:
        _run(["xdg-open", path])

def open_url(url: str):
    if _IS_THERMUX:
        _run(["termix-open-url", url])
    elif sys.platform == "win32":  
        os.startfile(url)
    elif sys.platform == "darwin": 
        _run(["open", url])
    else:
        _run(["xdg-open", url])

def notify(title: str, message: str, image: str | None = None) -> str:
    if _IS_THERMUX:
        cmd = ["termux-notification", "--title", title, "--content", message]
        if image:
            cmd += ["--image-path", image]
        _run(cmd)
        return "android"
    if image:
        open_file(image)
    try:
        from plyer import notification
        from plyer.facades import Notification 
        notification = cast(Notification, notification)
        notification.notify(
            title=title,
            message=message,
            timeout=8
        )
        return "desktop"
    except Exception as e:
        print(f"Notificação não disponível: {e}")    
    print(f"🔔 {title}: {message}")
    return "print"