def falha_device(res: str | None) -> bool:
    """True se a resposta do device indica erro/ausência.
    Convenção do gateway/handlers: falhas começam com [erro]/[timeout]/[bloqueado]."""
    if not res or not isinstance(res, str):
        return True
    return res.lstrip().startswith(("[erro", "[timeout", "[bloqueado"))
