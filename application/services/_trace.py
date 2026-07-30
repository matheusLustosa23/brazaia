"""Trace de DEBUG do router×auto → grava num arquivo (pra análise offline).
Temporário — remover quando fechar a investigação do router.

Arquivo: <raiz-do-projeto>/router_trace.log  (append; apague antes de uma rodada limpa).
"""
import logging
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PATH = os.path.join(_ROOT, "router_trace.log")

_log = logging.getLogger("router_trace")
if not _log.handlers:
    _h = logging.FileHandler(_PATH, mode="a", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def trace(msg: str) -> None:
    """Escreve uma linha no router_trace.log (não vai pro stdout — evita floodar o terminal)."""
    _log.info(msg)
