"""Força o interpretador a carregar os arquivos de ferramentas
ativando os decorators @runtime.register_tool no bootstrap."""
from companion.tools import notify_handler   # noqa: F401
from companion.tools import capture_handler  # noqa: F401