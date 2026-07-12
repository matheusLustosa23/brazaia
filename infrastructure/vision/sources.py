import asyncio, base64, cv2, os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Protocol
from infrastructure.devices.device_gateway import DeviceGateway

class VisionSource(Protocol):
    name: str
    async def capture(self) -> str: ...

class VisionRegistry:
    
    def __init__(self) -> None:
        self._sources: dict[str, VisionSource] = {}
        
    def register(self, src: VisionSource) -> None:
        self._sources[src.name] = src
    
    def unregister(self, name: str) -> None:
        self._sources.pop(name, None)
    
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

class DeviceCamera:
    """Fonte remota: pede a foto ao companion do device via RPC."""
    def __init__(self, gateway: DeviceGateway, device_id: str, name: str, camera: str | None = None):
        self._gateway = gateway
        self._device_id = device_id
        self.name = name
        self._camera = camera
    
    async def capture(self) -> str:
        args = {"camera": self._camera} if self._camera else {}
        return await self._gateway.request(self._device_id, "capture_image", args)
    