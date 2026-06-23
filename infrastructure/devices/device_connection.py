from fastapi import WebSocket

class DeviceConnectionManager:
    """Responsabilidade Única: Manter o estado bruto das conexões WebSockets ativas."""
    
    def __init__(self) -> None:
        self._conns: dict[str, WebSocket] = {}
        
    def register(self, device_id: str,ws: WebSocket) -> None:
        self._conns[device_id] = ws
    
    def unregister(self, device_id: str) -> None:
        self._conns.pop(device_id, None)
    
    def get(self, device_id: str) -> WebSocket | None:
        return self._conns.get(device_id)