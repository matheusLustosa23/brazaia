"""Motor ÚNICO de render — Pico (classless) + KaTeX. Substitui page.py + shell.py.

O LLM escreve HTML SEMÂNTICO (o Pico estiliza sozinho, sem classe) e matemática
NATURAL: bloco `$$...$$`, inline `\\(...\\)`. NUNCA cifrão único `$` pra math
(fica reservado a dinheiro — R$ 29). Validado (22/08/2026): o 27B obedece a regra
e o R$ nunca colide (v3 do teste comparativo).

Imagem (screenshot) e página (create_file/open_file) usam o MESMO render() -> nunca divergem.
Self-contained (assets embutidos) -> funciona offline, no celular, via file://.

style:
  "free"  (PADRÃO) -> NÃO injeta Pico; o body_html É a página inteira (o LLM autora
                       seu próprio <style>). Pra design bespoke. Continua self-contained.
  "pico"           -> injeta o Pico (classless); corpo vai em <main>. Barato, consistente.
KaTeX só entra se houver math no corpo (economia de peso).
"""
import base64, html as _html, re
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"

# Instrução que vai pras descriptions das tools (uma verdade só, aqui no motor).
STYLE_GUIDE = (
    "Você AUTORA o visual com o SEU próprio CSS (num <style>), com criatividade. O modo 'free' (PADRÃO) "
    "dá conta de tudo sozinho — use ele SEMPRE.\n"
    "  Só use style='pico' se o DONO pedir EXPLICITAMENTE 'usando pico'. Fora isso, é sempre free (sua criatividade).\n"
    "MATEMÁTICA (funciona no free, NÃO precisa de pico): bloco $$…$$ · inline \\(…\\). NUNCA cifrão único $ "
    "(é dinheiro: R$ 29). Ex.: \\(\\vec{v}=(3,-4)\\) e $$x=\\frac{-b}{2a}$$.\n"
    "NÃO use CDN/<link> externo (o device pode estar offline) — CSS inline no <style>."
)

_TEM_MATH = re.compile(r'\$\$|\\\(|\\\[')

_KATEX_SIZE = ".katex{font-size:1.05em}table .katex{white-space:nowrap}div.math{margin:14px 0}"
_PICO_EXTRA = ("main{padding:22px 18px 60px}"
               ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}")

# auto-render (renderMathInElement): $$ e \[ \] = bloco; \( \) = inline. SEM $ solto (cifrão seguro).
_AUTORENDER = ('<script>{kjs}</script><script>{ajs}</script><script>'
               'renderMathInElement(document.body,{{delimiters:['
               '{{left:"$$",right:"$$",display:true}},'
               '{{left:"\\\\[",right:"\\\\]",display:true}},'
               '{{left:"\\\\(",right:"\\\\)",display:false}}'
               '],throwOnError:false}});</script>')


@lru_cache(1)
def _pico() -> str:
    return (_ASSETS / "pico.classless.min.css").read_text("utf-8")

@lru_cache(1)
def _katex_css() -> str:                       # fontes embutidas (offline)
    css = (_ASSETS / "katex.min.css").read_text("utf-8")
    for f in sorted((_ASSETS / "fonts").glob("*.woff2")):
        css = css.replace(f"fonts/{f.name}", "data:font/woff2;base64," + base64.b64encode(f.read_bytes()).decode())
    return css

@lru_cache(1)
def _katex_js() -> tuple[str, str]:
    return ((_ASSETS / "katex.min.js").read_text("utf-8"),
            (_ASSETS / "auto-render.min.js").read_text("utf-8"))


def render(body_html: str, title: str | None = None, style: str = "free") -> str:
    """body_html (HTML semântico + math natural) -> HTML self-contained. Ver docstring do módulo."""
    tem_math = bool(_TEM_MATH.search(body_html))
    css_parts: list[str] = []
    if style == "pico":
        css_parts.append(_pico())
        css_parts.append(_PICO_EXTRA)
    if tem_math:
        css_parts.append(_katex_css())
        css_parts.append(_KATEX_SIZE)
    css = "\n".join(css_parts)

    head = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(title or "brazaia")}</title><style>{css}</style></head>')

    if style == "pico":
        h1 = f"<h1>{_html.escape(title)}</h1>" if title else ""
        corpo = f"<main>{h1}{body_html}</main>"
    else:                                                  # free: o LLM manda a página toda
        corpo = body_html

    scripts = ""
    if tem_math:
        kjs, ajs = _katex_js()
        scripts = _AUTORENDER.format(kjs=kjs, ajs=ajs)
    return f"{head}<body>{corpo}{scripts}</body></html>"
