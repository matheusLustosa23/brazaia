import asyncio, base64
import cv2
from companion.runtime import runtime

def _grab(index: int = 0) -> str:
    cap = cv2.VideoCapture(index)
    try:
        ok, frame = cap.read()
        if not ok: return "[erro] câmera do device sem frame"
        _, buf = cv2.imencode(".jpg", frame)
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    finally:
        cap.release()  

@runtime.register_tool("capture_image")
async def capture_image_handler(args: dict) -> str:
    return await asyncio.to_thread(_grab)