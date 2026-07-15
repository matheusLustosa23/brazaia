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
        default_img = os.path.abspath(f"companion/assets/images/braza_logo_full.png")
        cmd = ["termux-notification", "--title", title, "--content", message, "--image-path", image or default_img]
    
        _run(cmd)
        return "android"
    if image:
        open_file(image)
    try:
        icon_ext = ".ico" if sys.platform == "win32" else ".png"
        icon_path = os.path.abspath(f"companion/assets/images/braza_logo{icon_ext}")
        if sys.platform  == "win32":
            from win11toast import toast
            toast(title, message, icon=icon_path)
            return "windows"
        else:
            _run(["notify-send", "-i", icon_path, title, message])
            return "linux"
    except Exception as e:
        print(f"Notificação não disponível: {e}")    
    print(f"🔔 {title}: {message}")
    return "print"