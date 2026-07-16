"""content (LaTeX cru do LLM) -> HTML self-contained com KaTeX.

Um motor só: este HTML é a fonte da verdade de como a matemática aparece.
Quem quer foto (E4) tira um print DELE; quem quer página (E3) recebe ELE.
Por isso foto e página nunca divergem — e há um lugar só pra caçar bug.

Não parseamos nada: o auto-render do KaTeX acha os $...$ sozinho.
"""
import base64
import html as _html
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"

# A instrução de sintaxe mora AQUI, junto do motor que a interpreta — não na
# description de cada tool. Quem define o que é sintaxe válida é este módulo; as
# tools (display_page, render_math) só repassam. Duplicar em cada uma seria dar
# duas verdades pra mesma coisa: alguém ajusta uma, esquece a outra, e a
# description passa a mentir sobre o render.
#
# Validada em 5 assuntos (16/07/2026) — vetores, matrizes 3x3 + determinantes,
# sistemas, integrais + somatórios, limites/derivadas: 0 falhas, 0 comandos
# fora de $...$.
SINTAXE = (
    "Escreva LaTeX normal: texto corrido em português e matemática entre $...$ "
    "(ou $$...$$ pra bloco).\n"
    "Ex.: 1) Dado o vetor $\\vec{v} = (3, -4)$, calcule a sua norma."
)

_TEMPLATE = """<!doctype html>
    <html lang="pt-BR">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>__TITULO_TXT__</title>
    <style>
    __KATEX_CSS__
    body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            max-width: 760px; margin: 0 auto; padding: 22px 18px 60px;
            font-size: 17px; line-height: 1.9; color: #15181e; background: #fff; }
    h1 { font-size: 1.35rem; text-align: center; margin: 0 0 20px; }
    /* pre-wrap: preserva os \\n do LLM SEM quebrar o content em elementos.
        Essencial (bug medido): o $...$ do \\begin{cases} ATRAVESSA linhas, e o
        auto-render do KaTeX não casa delimitador entre elementos diferentes. */
    #c { white-space: pre-wrap; }
    .katex { font-size: 1.05em; }
    </style></head>
    <body>__TITULO_H1__<div id="c">__CORPO__</div>
    <script>__KATEX_JS__</script>
    <script>__AUTO_JS__</script>
    <script>
    renderMathInElement(document.getElementById("c"), {
        delimiters: [
        {left: "$$", right: "$$", display: true},
        {left: "$",  right: "$",  display: false}
        ],
        throwOnError: false
    });
    </script></body></html>
"""

@lru_cache(maxsize=1)
def _css_com_fontes() -> str:
    """CSS do KaTeX com as fontes embutidas em data URI.

    Tem que ser self-contained: o HTML vai INTEIRO pro celular, que pode estar
    sem internet. Sem as fontes o KaTeX cai em fallback e a tipografia
    matemática vai por água abaixo — que é justamente o que se está comprando.
    Só .woff2: é o que todo browser moderno usa; as outras urls do CSS ficam
    apontando pra caminho relativo e nunca são buscadas.
    """
    css = (_ASSETS / "katex.min.css").read_text(encoding="utf-8")
    for fonte in sorted((_ASSETS / "fonts").glob("*.woff2")):
        b64 = base64.b64encode(fonte.read_bytes()).decode()
        css = css.replace(f"fonts/{fonte.name}", f"data:font/woff2;base64,{b64}")
    return css

@lru_cache(maxsize=1)
def _js() -> tuple[str, str]:
    return ((_ASSETS / "katex.min.js").read_text(encoding="utf-8"),
            (_ASSETS / "auto-render.min.js").read_text(encoding="utf-8"))

def render_page(content: str, title: str | None = None) -> str:
    """content = o LaTeX CRU que o LLM mandou. Devolve HTML self-contained.

    O _html.escape é obrigatório e correto: '2 & 3' vira '2 &amp; 3' no fonte,
    e o browser devolve '&' no textContent -> o KaTeX lê o LaTeX certinho.
    Sem escape, um 'x < 5' quebraria o HTML.
    """
    titulo_txt = title or "brazaia"
    h1 = f"<h1>{_html.escape(titulo_txt)}</h1>" if title else ""
    katex_js, auto_js = _js()
    return (_TEMPLATE
            .replace("__KATEX_CSS__", _css_com_fontes())
            .replace("__KATEX_JS__", katex_js)
            .replace("__AUTO_JS__", auto_js)
            .replace("__TITULO_TXT__", _html.escape(titulo_txt))
            .replace("__TITULO_H1__", h1)
            .replace("__CORPO__", _html.escape(content)))
    