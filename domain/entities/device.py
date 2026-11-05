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
    plataforma: str = ""                                  # termux | windows | linux | macos (o companion diz)
    permissoes: dict = field(default_factory=dict)        # {"camera": "ok", "localizacao": "negada", ...}
    estado: dict = field(default_factory=dict)            # {"bateria": 81, "carregando": False}
    estado_em: float | None = None                        # quando o estado foi lido
    
    def is_online(self, timeout: float = 60.0) -> bool:
        if self.last_seen is None:
            return False
        return (time.time() - self.last_seen) < timeout
    
    def activate(self) -> None:
        self.status = "active"
    
    def revoke(self) -> None:
        self.status = "revoked"

@dataclass
class Localizacao:
    """Uma leitura de posição de um device. `quando` = quando o DEVICE leu (pode chegar depois, pela fila)."""
    device_id: str
    lat: float
    lon: float
    quando: float
    precisao_m: float | None = None
    fonte: str = ""          # gps | network | last | windows | geoclue
    origem: str = ""         # pedido (alguém pediu agora) | periodica (coleta de 15 em 15 min)
