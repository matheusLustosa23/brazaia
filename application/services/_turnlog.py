"""Log de mensagens BRUTAS por turno: a fala do user + a saída CRUA do LLM (com <think> intacto).

Pra AUDITAR o comportamento real do modelo (ex.: como o Qwen envolve o thinking, multi-bloco, tags)
sem chutar — a gente abre este arquivo e olha o que realmente veio. Irmão do _trace.py.

Arquivo: <raiz-do-projeto>/turnos_brutos.log  (append; *.log está no .gitignore; apague antes de uma rodada limpa).
"""
import json, logging, os, time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_ROOT, "turnos_brutos.log")

_log = logging.getLogger("turnos_brutos")
if not _log.handlers:
    _h = logging.FileHandler(_PATH, mode="a", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def log_turno(session_id: str, user_message: str, raw_output: str, *, think: bool) -> None:
    """Uma linha JSON por turno: ts · session · think · user · raw (saída do LLM SEM strip, com <think>).
    Nunca quebra o fluxo: em erro, só ignora (é auditoria, não pode derrubar a resposta)."""
    try:
        _log.info(json.dumps({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": session_id,
            "think": think,
            "user": user_message,
            "raw": raw_output,
        }, ensure_ascii=False))
    except Exception:
        pass
