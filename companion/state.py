# companion/state.py — estado compartilhado da sessão do CLI (lido pelo rodapé/_toolbar).
from dataclasses import dataclass

@dataclass
class SessionState:
    session_id: str | None = None
    device_online: bool = False
    device_status: str = "offline"        # "online" | "reconectando" | "offline" (pro footer)
    modo: str = "texto"

estado = SessionState()
