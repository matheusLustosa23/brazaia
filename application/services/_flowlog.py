"""Log de FLUXO do turno: cada etapa numa linha legível, em ordem, pra ACOMPANHAR ao vivo (tail).

Irmão do _turnlog.py (saída crua do LLM) e do _trace.py. Aqui entra o "o que aconteceu e quando":
msg do user → contexto → cada chamada ao LLM (tempo, tokens, saída) → cada tool (args, resultado,
tempo) → guard → eventos enviados ao cliente → fim/erro. Uma linha por etapa, prefixada pela sessão.

Arquivo: <raiz-do-projeto>/fluxo.log  (append; *.log está no .gitignore).
Acompanhar no server:  Get-Content C:\\workspace\\brazaia\\fluxo.log -Wait -Tail 50
"""
import logging
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_ROOT, "fluxo.log")

_log = logging.getLogger("fluxo")
if not _log.handlers:
    _h = logging.FileHandler(_PATH, mode="a", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%H:%M:%S"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def flow(session_id: str | None, etapa: str, msg: str) -> None:
    """Uma linha: `hh:mm:ss.mmm [sessão6] etapa  msg`. Nunca quebra o fluxo (é observação)."""
    try:
        _log.info("[%s] %-9s %s", (session_id or "-")[:6], etapa, msg)
    except Exception:
        pass


def curto(s, n: int = 200) -> str:
    """Texto numa linha só (⏎ no lugar das quebras), cortado em n — pra caber na linha do log."""
    t = str(s if s is not None else "").replace("\r", "").replace("\n", "⏎")
    return t[:n] + (f"…(+{len(t) - n})" if len(t) > n else "")
