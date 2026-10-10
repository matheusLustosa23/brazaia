"""Transcrição ao vivo no terminal — fala do usuário E do agente.

A fala do usuário aparece como linha parcial que se atualiza no lugar (autocorreção à vista) e se
fixa ao fechar o turno. A fala do agente é o próprio texto do LLM, transmitido token a token (o que
está sendo falado). Sem TUI full-screen: só ANSI simples e robusto.
"""
from __future__ import annotations
import sys

DIM = "\033[2m"
RST = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CLEAR_LINE = "\r\033[K"


class Transcript:
    def __init__(self, stream=sys.stdout):
        self.out = stream
        self._open = None   # None | "user" | "agent"

    def _w(self, s: str):
        self.out.write(s)
        self.out.flush()

    # --- usuário ---
    def user_partial(self, text: str):
        import shutil
        cols = shutil.get_terminal_size((100, 24)).columns
        avail = max(10, cols - 12)                       # cabe em 1 linha (prefixo "🫵 você: ")
        shown = text if len(text) <= avail else "…" + text[-(avail - 1):]   # mostra o FIM (ao vivo)
        self._w(f"{CLEAR_LINE}{CYAN}🫵 você:{RST} {shown or '…'}")
        self._open = "user"

    def user_final(self, text: str):
        self._w(f"{CLEAR_LINE}{CYAN}🫵 você:{RST} {text}\n")
        self._open = None

    # --- agente ---
    def thinking(self):
        self._w(f"{DIM}· pensando…{RST}\n")

    def agent_start(self):
        self._w(f"{GREEN}🤖 braza:{RST} ")
        self._open = "agent"

    def agent_delta(self, delta: str):
        self._w(delta)

    def agent_final(self):
        if self._open == "agent":
            self._w("\n")
        self._open = None

    def interrupted(self):
        self._w(f" {YELLOW}⟲ (interrompido){RST}\n")
        self._open = None

    # --- status / erros ---
    def info(self, msg: str):
        self._w(f"{DIM}· {msg}{RST}\n")

    def error(self, msg: str):
        if self._open:
            self._w("\n")
        self._w(f"{YELLOW}⚠ {msg}{RST}\n")
        self._open = None
