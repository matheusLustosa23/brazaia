import asyncio
from uuid import uuid4


class DeviceRPCManager:
    """Responsabilidade Única: Gerenciar ciclo de vida RPC assíncrono (Futures e Correlation IDs)."""
    
    def __init__(self, timeout: float = 30.0) -> None:
        self._pending: dict[str, asyncio.Future] = {}
        self._timeout = timeout
        
    def create_request(self) -> tuple[str, asyncio.Future]:
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        return request_id, future
    
    def resolve_response(self, request_id: str, data: dict) -> None:
        future = self._pending.pop(request_id, None)
        if future and not future.done():
            if "error" in data:
               future.set_result(f"[erro device] {data['error']}") 
            else:
                future.set_result(data.get("result", "ok"))
                
    def cancel_request(self, request_id: str) -> None:
        self._pending.pop(request_id, None)
    
    @property
    def timeout(self) -> float:
        return self._timeout