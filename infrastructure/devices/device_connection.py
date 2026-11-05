import time

from fastapi import WebSocket

class DeviceConnectionManager:
    """Responsabilidade Única: Manter o estado bruto das conexões WebSockets ativas."""
    
    def __init__(self) -> None:
        self._conns: dict[str, WebSocket] = {}
        self._desde: dict[str, float] = {}                  # device_id -> quando ESTA conexão abriu
        
    def register(self, device_id: str,ws: WebSocket) -> None:
        self._conns[device_id] = ws
        self._desde[device_id] = time.time()
    
    def unregister(self, device_id: str) -> None:
        self._conns.pop(device_id, None)
        self._desde.pop(device_id, None)

    def desde(self, device_id: str) -> float | None:
        """Quando a conexão atual do device abriu (None = não está conectado)."""
        return self._desde.get(device_id)
    
    def get(self, device_id: str) -> WebSocket | None:
        return self._conns.get(device_id)
    
    def names(self) -> list[str]:
        return list(self._conns.keys())