import re
from domain.tools.guard import GuardResult

_PROTO = re.compile(r"\[\s*chamando ferramenta|\[\s*resultado da ferramenta|\[\s*imagem capturada", re.I)
_ID    = re.compile(r"image_id[\s=:]+([0-9a-f]{6,})", re.I)

def check_output(content: str, ids_reais: set[str]) -> GuardResult:
    """Resultado real = msg role='tool'; id real = arg de tool_call. No content do assistant = invenção."""
    if not content:
        return GuardResult(ok=True)
    if _PROTO.search(content):
        return GuardResult(
            ok=False,
            reason="Você narrou uma ferramenta no texto sem chamá-la. "
                    "Ou CHAME de verdade, ou diga que não fez / não tem."
        )
    for m in _ID.finditer(content):
        if m.group(1) not in ids_reais:
            return GuardResult(
                ok=False,
                reason="Você citou um id que nenhuma ferramenta produziu neste turno."
            )
    return GuardResult(ok=True)
        