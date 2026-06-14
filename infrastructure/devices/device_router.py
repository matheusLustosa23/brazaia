class DeviceRouter:
    """PLACEHOLDER do roteador de ações device-side (adapter de infraestrutura).
    Interface mínima — sem despacho real (feat-companion-actuator implementa o WS por device-id).
    Implementa um contrato do domínio; NÃO importa FastAPI."""

    def __init__(self) -> None:
        self._devices: dict[str, object] = {}

    def register(self, device_id: str, conn: object) -> None:
        """Registra a conexão de um companion (no-op estrutural por enquanto)."""
        self._devices[device_id] = conn

    async def dispatch(self, device_id: str, action: dict) -> dict:
        """Despacha uma tool-call device-side ao companion certo (placeholder)."""
        raise NotImplementedError("Device dispatch — feat-companion-actuator")
