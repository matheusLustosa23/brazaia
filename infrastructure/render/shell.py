"""wrap_page: injeta o design system do brazaia no HTML que o LLM autora.

Baseado no visual do escolha-do-modelo-2026 (dark; cyan/violet/amber/green/coral).
Mesmo princípio do KaTeX (E1): o servidor dá o VOCABULÁRIO de componentes; o LLM
escreve só o CONTEÚDO usando as classes. Ganho medido: ~30 linhas de conteúdo
(500 tok) em vez de ~300 de tudo (4K) → saída menor, melhor, sem truncar.

Decisões de adaptação (o original é uma landing desktop):
- Fontes de SISTEMA (não Syne/JetBrains via CDN): o device pode estar offline e a
  página vem do localhost. A identidade vem da COR + LAYOUT. Embutir as fontes
  depois é o mesmo padrão do KaTeX, se quiser o look exato.
- Grids RESPONSIVOS (auto-fit): colapsam pra 1 coluna no celular.
- Sem hero/orbs: é página de conteúdo, não landing.
- Dark por ESCOLHA (o design é dark; não é omissão de tema claro).

O CSS mora num ARQUIVO editável (assets/page.css) e é INLINADO no build — não
linkado com <link>. Por quê inline e não <link>: o HTML tem que ser
self-contained (foi o que fez funcionar nos 3 SOs). Um <link> reabriria o
problema do transporte — no Termux o browser buscaria o css via localhost (mais
uma rota + cache), no desktop via file:// (frágil), e offline seria ponto de
falha. Mesmo padrão do KaTeX no page.py (_css_com_fontes lê e embute).
O ganho do arquivo é DEV: edita CSS de verdade (syntax highlight, sem escapar
aspas em string Python) sem perder o self-contained.

O vocabulário está documentado em STYLE_GUIDE (abaixo), que vai pra instrução do LLM.
"""
import html as _html
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"


@lru_cache(maxsize=1)
def _css() -> str:
    return (_ASSETS / "page.css").read_text(encoding="utf-8")


# vai pra instrução do LLM (description da display_page ou skill "gerador de página")
STYLE_GUIDE = (
    "Escreva só o HTML do corpo, usando estas classes (o CSS já existe no servidor):\n"
    "- <div class='card'>...       bloco com borda\n"
    "- <div class='grid'>cards...  colunas responsivas (colapsam no celular)\n"
    "- <div class='stat'><span class='v'>42</span><span class='k'>rótulo</span></div>  número em destaque\n"
    "- <span class='tag tag-cyan'>NOVO</span>   etiqueta (cyan/violet/amber/green/coral)\n"
    "- <span class='label'>SEÇÃO</span>         eyebrow monospace\n"
    "- <div class='callout callout-amber'>aviso</div>\n"
    "- <div class='bar'><span style='width:70%'></span></div>   barra de progresso\n"
    "- <table>, <ul>, <h2>, <p>, <code> já vêm estilizados — use-os direto, sem classe.\n"
    "Exemplo: <span class='label'>Planos</span><div class='grid'>"
    "<div class='card'><h3>Grátis</h3><p>R$0</p></div>"
    "<div class='card'><h3>Pro <span class='tag tag-cyan'>popular</span></h3><p>R$29</p></div></div>\n"
    "NÃO use CDN/lib externa nem <style>/<link> (o device pode estar offline)."
)


def wrap_page(body_html: str, title: str = "brazaia") -> str:
    """Embrulha o corpo autorado pelo LLM num HTML self-contained com o design system."""
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_html.escape(title)}</title><style>{_css()}</style></head>'
            f'<body><main><h1>{_html.escape(title)}</h1>{body_html}</main></body></html>')