import asyncio, base64, os, subprocess, shutil, time
from companion.runtime import runtime
_IS_TERMUX = shutil.which("termux-camera-photo") is not None
CAMERAS = ["back", "front"] if _IS_TERMUX else None

def _grab_termux(camera: str | None):
    cam = "1" if camera == "front" else "0"
    raw, small = os.path.expanduser("~/frame_raw.jpg"), os.path.expanduser("~/frame.jpg")
    ok, err = False, ""
    for _ in range(3):
        p = subprocess.run(["termux-camera-photo", "-c", cam,raw], capture_output=True, text=True)
        ok = not p.returncode and os.path.exists(raw)
        err = (p.stderr or "")
        if ok and os.path.getsize(raw) >= 40_000: break
        time.sleep(0.6)
    
    if not ok: return f"[erro] cam {cam}:  {err or 'sem captura'}"
    src, magick = raw, (shutil.which("magick") or shutil.which("convert"))
    if magick and subprocess.run([magick,raw,"-resize","1280x1280>","-quality","80",small]).returncode == 0:
        src = small
    d = open(src,"rb").read()
    return "data:image/jpeg;base64,"+base64.b64encode(d).decode() if d else "[erro] foto vazia"

def _grab_cv2(camera: str | None) -> str:
    import cv2
    cap = cv2.VideoCapture(0)
    try:
        ok, frame = cap.read()
        if not ok: return "[erro] câmera do device sem frame"
        _, buf = cv2.imencode(".jpg", frame)
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    finally:
        cap.release()  

@runtime.register_tool("capture_image")
async def capture_image_handler(args: dict) -> str:
    return await asyncio.to_thread(_grab_termux if _IS_TERMUX else _grab_cv2, args.get("camera"))