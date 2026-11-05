"""brazaia companion — o lado do DEVICE (celular, note, PC): conexão com o agente, tools locais, CLI e voz.

Roda de dois jeitos:
  • instalado como pacote (`pip install <servidor>/api/v1/companion/pacote/...whl`) — o normal nos devices;
    tem VERSAO (gerada no build) e se atualiza sozinho quando o servidor anuncia outra;
  • direto do repositório (desenvolvimento) — versão "dev", nunca se auto-atualiza.

Arquivos do pacote (modelo do wake word, imagens, scripts de boot) são achados por `caminho(...)`, relativo a
ESTA pasta — nunca relativo à pasta atual (antes era "companion/assets/..." e só funcionava de dentro do repo).
"""
import os

PACOTE = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.expanduser("~/.brazaia")          # scripts instalados + arquivos de trabalho (fora do pacote/repo)

try:
    from companion._versao import VERSAO as __version__   # escrito pelo build do pacote (infrastructure/companion_pacote.py)
except ImportError:
    __version__ = "dev"


def caminho(*partes: str) -> str:
    """Arquivo que vem DENTRO do pacote: caminho("models", "braza.onnx")."""
    return os.path.join(PACOTE, *partes)
