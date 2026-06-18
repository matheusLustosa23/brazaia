class DeviceRouter:
    """PLACEHOLDER do roteador de ações device-side (adapter de infraestrutura).
    Interface mínima — sem despacho real (feat-companion-actuator implementa o WS por device-id).
    Implementa DeviceRouter de domain/contracts.py; NÃO importa FastAPI."""

    def __init__(self) -> None:
        self._devices: dict[str, object] = {}

    def register(self, device_id: str, conn: object) -> None:
        self._devices[device_id] = conn

    def capabilities(self, device_id: str | None) -> set[str] | None:
        return None

    async def dispatch(self, device_id: str | None, tool_call: dict) -> str:
        raise NotImplementedError("Device dispatch — feat-companion-actuator")
