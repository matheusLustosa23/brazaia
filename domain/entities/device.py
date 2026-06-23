from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import time

Status = Literal["pending", "active", "revoked"]

@dataclass
class Device:
    """Entidade de domínio — representa um device registrado no sistema."""
    id: str
    name: str
    status: Status = "pending"
    allowed_tools: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_seen: float | None = None
    
    def is_online(self, timeout: float = 60.0) -> bool:
        if self.last_seen is None:
            return False
        return (time.time() - self.last_seen) < timeout
    
    def activate(self) -> None:
        self.status = "active"
    
    def revoke(self) -> None:
        self.status = "revoked"