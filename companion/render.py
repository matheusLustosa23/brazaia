# companion/render.py — renderizador do chat (promovido do protótipo scripts/_proto_respostas.py)
import re, random, string
from io import StringIO
from rich.console import Console
from rich.markdown import Markdown
from pylatexenc.latex2text import LatexNodes2Text

# --- animação do checklist/loader (promovido de scripts/_proto_respostas.py) ---
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"                                           # spinner do loader/etapas
VERDE = "#39ff14"                                                  # verde vivo (loader)
_POOL = string.ascii_uppercase + string.digits + "@#$%*+=?/\\|"   # sem < > & " ' (não quebra ANSI/HTML)

def decode(nome: str, passos: int, fpl: int = 1) -> str:
    """Efeito 'hacker decode': revela o nome da esquerda p/ direita conforme passos; o resto é ruído."""
    alvo = nome.upper()
    trav = min(len(alvo), max(0, passos) // fpl)
    return alvo[:trav] + "".join(random.choice(_POOL) for _ in range(len(alvo) - trav))

_L2T = LatexNodes2Text()
_SUP = str.maketrans('0123456789+-=()ni', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ')
_SUB = str.maketrans('0123456789+-=()i', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ᵢ')

def latex_para_unicode(t: str) -> str:
    def conv(m):
        s = _L2T.latex_to_text(m.group(1))
        s = re.sub(r'\^\{([^}]*)\}', lambda g: g.group(1).translate(_SUP), s)
        s = re.sub(r'\^([0-9A-Za-z+\-=()])', lambda g: g.group(1).translate(_SUP), s)
        s = re.sub(r'_\{([^}]*)\}', lambda g: g.group(1).translate(_SUB), s)
        s = re.sub(r'_([0-9A-Za-z+\-=()])', lambda g: g.group(1).translate(_SUB), s)
        return re.sub(r'\s+', ' ', s).strip()
    t = re.sub(r'\$\$(.+?)\$\$', conv, t, flags=re.S)
    return re.sub(r'\$(.+?)\$', conv, t, flags=re.S)

def md_ansi(text: str, width: int = 100, bg: str | None = None, code_theme: str = "monokai") -> str:
    text = latex_para_unicode(text)          # ← conversor embutido, 1ª linha, antes de renderizar
    buf = StringIO()
    con = Console(file=buf, force_terminal=True, color_system="truecolor", width=width)
    con.print(Markdown(text, code_theme=code_theme), style=(f"on {bg}" if bg else None))
    return buf.getvalue()
