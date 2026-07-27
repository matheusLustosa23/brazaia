from dataclasses import dataclass, field

@dataclass(frozen=True)
class ToolCtx:
    fala_do_usuario: str
    ids_reais: set[str] = field(default_factory=set)
    session_id: str  = "voice"


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""                     
    fallback: str | None = None