import asyncio, base64, cv2, os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Protocol

class VisionSource(Protocol):
    name: str
    async def capture(self) -> str: ...

class VisionRegistry:
    
    def __init__(self) -> None:
        self._sources: dict[str, VisionSource] = {}
        
    def register(self, src: VisionSource) -> None:
        self._sources[src.name] = src
    
    def names(self) -> list[str]:
        return list(self._sources.keys())

    async def capture(self, source: str) -> str:
        src = self._sources.get(source)
        if src is None:
            raise ValueError(f"fonte de visão '{source}' não existe (tem: {self.names()})")
        return await src.capture()

class WebCam:
    name = "webcam"
    
    def __init__(self, index: int = 0, save_dir: str | None = "~/capturas"):
        self._i = index
        self._save_dir = os.path.expanduser(save_dir) if save_dir else None
    
    async def capture(self) -> str:
        return await asyncio.to_thread(self._grab)
    
    def _grab(self) -> str:
        cap = cv2.VideoCapture(self._i)
        try:
            ok, frame = cap.read()
            if not ok: raise RuntimeError("Web cam sem frame")
            _, buf = cv2.imencode(".jpg", frame)
            
            if self._save_dir:
                SP = ZoneInfo("America/Sao_Paulo")
                os.makedirs(self._save_dir, exist_ok=True)
                fname = datetime.now(SP).strftime("%Y%m%d_%H%M%S_%f") + ".jpg"
                buf.tofile(os.path.join(self._save_dir, fname))
            
            return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
        finally:
            cap.release()
    