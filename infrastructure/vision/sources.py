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
    
    def __init__(self, index: int = 0):
        self._i = index
    
    async def capture(self) -> str:
        return await asyncio.to_thread(self._grab)
    
    def _grab(self) -> str:
        cap = cv2.VideoCapture(self._i)
        try:
            ok, frame = cap.read()
            if not ok: raise RuntimeError("Web cam sem frame")
            _, buf = cv2.imencode(".jpg", frame)
            b64 = base64.b64encode(buf).decode()
            return "data:image/jpeg;base64," + b64
        finally:
            cap.release()
    