import re

_FILE_ID_SO = re.compile(r"^\s*\[?\s*file_id\s*=\s*([0-9a-f]{12})\b")   # começa com o marcador (pega [file_id=X · html · …] também)
ELISION = "⟨conteúdo omitido"     # prefixo que o histórico usa no lugar do body gigante (ver orchestrator._stash_args)


def falha_device(res: str | None) -> bool:
    """True se a resposta do device indica erro/ausência.
    Convenção do gateway/handlers: falhas começam com [erro]/[timeout]/[bloqueado]."""
    if not res or not isinstance(res, str):
        return True
    return res.lstrip().startswith(("[erro", "[timeout", "[bloqueado"))


def so_file_id(texto: str | None) -> str | None:
    """Rede de segurança: se o texto é SÓ um marcador 'file_id=XXXX' (o modelo às vezes cola isso como
    body_html, imitando o histórico), devolve o id pra resolver. Senão, None (é conteúdo de verdade)."""
    if not texto:
        return None
    m = _FILE_ID_SO.match(texto)
    return m.group(1) if m else None


def eh_placeholder(texto: str | None) -> bool:
    """True se o body_html não é conteúdo de verdade, mas uma MARCA do histórico que o modelo copiou:
    um marcador [file_id=…] ou a elisão ⟨html omitido…⟩. Os tools de render recusam isso e mandam o
    modelo re-escrever o HTML (ou usar open_file/see_file pra um artefato existente)."""
    if not texto:
        return False
    return bool(so_file_id(texto)) or texto.lstrip().startswith(ELISION)
