from dataclasses import dataclass, field

@dataclass(frozen=True)
class ToolCtx:
    fala_do_usuario: str
    ids_reais: set[str] = field(default_factory=set)
    session_id: str  = "voice"
    device_id: str | None = None        # device do turno (p/ a tool persistir artefato em {device}/{session}/…)


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""                     
    fallback: str | None = None