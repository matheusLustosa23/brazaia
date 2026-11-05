"""Busca na web (SearXNG próprio) e leitura de páginas — o agente pesquisa o que não está no acervo.

web_search → lista de resultados (título, link, resumo). web_fetch → baixa UMA página, tira menu/propaganda/
rodapé (trafilatura), vira Markdown e é guardada no ACERVO (coleção "web"): página curta volta inteira; longa
volta o sumário, e o agente lê por seção com read_doc — o mesmo jeito de ler o material (nunca a página toda).
"""
import asyncio
import re
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.acervo.acervo import Acervo

_CURTA = 7000          # página até isso (chars) volta inteira; maior → sumário + read_doc
_MAX_BYTES = 8 * 1024 * 1024


class WebSearchInput(BaseModel):
    consulta: str = Field(description="O que pesquisar, do jeito que se busca no Google: 'scrum guide 2020 mudanças', 'preço dólar hoje'.")
    noticias: bool = Field(default=False, description="true = só notícias recentes (fatos do dia, lançamentos, eventos).")
    quantidade: int = Field(default=6, ge=1, le=10, description="Quantos resultados (padrão 6).")


class WebSearchTool(Tool[WebSearchInput]):
    name = "web_search"
    description = (
        "Pesquisa na INTERNET (buscador próprio) e devolve título, link e resumo de cada resultado. Use pra "
        "assunto atual, notícia, preço, versão de software, ou o que NÃO está no acervo. Depois abra 2–3 links "
        "com web_fetch pra ler de verdade — o resumo do resultado é curto e pode enganar."
    )
    input_schema = WebSearchInput
    side = "server"
    action_class = "read"
    timeout_s = 25.0
    router_hint = "pesquisar na internet (sites, notícias, blogs)"

    def __init__(self, searxng_url: str) -> None:
        self._url = searxng_url.rstrip("/")

    async def run(self, payload: WebSearchInput, ctx: ToolCtx) -> str:
        params = {"q": payload.consulta, "format": "json", "language": "pt-BR"}
        if payload.noticias:
            params["categories"] = "news"
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(f"{self._url}/search", params=params)
                r.raise_for_status()
                dados = r.json()
        except Exception as e:
            return f"[erro] a busca na web não respondeu ({type(e).__name__}). O SearXNG está no ar? (braza status)"
        vistos, linhas = set(), []
        for res in dados.get("results", []):
            url = res.get("url") or ""
            dominio = urlparse(url).netloc.removeprefix("www.")
            if not url or url in vistos:
                continue
            vistos.add(url)
            data = f" · {res['publishedDate'][:10]}" if res.get("publishedDate") else ""
            resumo = re.sub(r"\s+", " ", res.get("content") or "").strip()[:260]
            linhas.append(f"{len(linhas) + 1}. {res.get('title', '').strip()} — {dominio}{data}\n   {url}\n   {resumo}")
            if len(linhas) >= payload.quantidade:
                break
        if not linhas:
            return f"[web] nada encontrado para “{payload.consulta}”. Tente outras palavras (ou em inglês)."
        return (f"[web] {len(linhas)} resultado(s) para “{payload.consulta}”{' (notícias)' if payload.noticias else ''}:\n"
                + "\n".join(linhas) + "\nAbra os mais relevantes com web_fetch(url) antes de responder; cite os links.")


class WebFetchInput(BaseModel):
    url: str = Field(description="O link da página (veio do web_search ou o dono mandou).")
    pergunta: str | None = Field(default=None, description=(
        "O que você quer saber DESSA página (palavras-chave). Com isso, página longa volta direto com os TRECHOS "
        "que respondem — sem precisar ler parte por parte. Ex.: 'mudanças product owner 2020'."))


class WebFetchTool(Tool[WebFetchInput]):
    name = "web_fetch"
    description = (
        "Abre UMA página da web e lê o CONTEÚDO (sem menu/propaganda). Página curta volta inteira. Longa: passe "
        "`pergunta` e volta com os TRECHOS que respondem (texto original); sem pergunta volta o SUMÁRIO pra ler com "
        "read_doc(doc, secao). Fica guardada no acervo. Funciona com HTML e PDF."
    )
    input_schema = WebFetchInput
    side = "server"
    action_class = "read"
    timeout_s = 40.0
    router_hint = "abrir e ler uma página da web pelo link"

    def __init__(self, acervo: Acervo, user_agent: str) -> None:
        self._acervo = acervo
        self._ua = user_agent              # robô que se identifica (sem se passar por navegador)

    async def run(self, payload: WebFetchInput, ctx: ToolCtx) -> str:
        url = payload.url.strip()
        if not re.match(r"https?://", url):
            return "[erro] passe um link completo (https://…)."
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": self._ua}) as http:
                r = await http.get(url)
        except Exception as e:
            return f"[erro] não consegui abrir {url} ({type(e).__name__})."
        if r.status_code in (401, 403, 429):
            return f"[erro] {urlparse(url).netloc} recusou robôs ({r.status_code}) — use outro resultado da busca."
        if r.status_code >= 400:
            return f"[erro] {url} respondeu {r.status_code} — tente outro resultado."
        if len(r.content) > _MAX_BYTES:
            return f"[erro] página grande demais ({len(r.content) // 1_000_000} MB)."
        tipo = r.headers.get("content-type", "")
        try:
            titulo, texto = await asyncio.to_thread(_extrair, str(r.url), r.content, tipo)
        except ValueError as e:
            return f"[erro] {e}"
        dominio = urlparse(str(r.url)).netloc.removeprefix("www.")
        info = await asyncio.to_thread(self._acervo.adicionar, f"{dominio} — {titulo}"[:110] + ".md",
                                       f"# {titulo}\n\nFonte: {r.url}\n\n{texto}".encode(), "web",
                                       {"url": str(r.url), "fonte": "web", "titulo": titulo})
        doc = info["doc"]
        if len(texto) <= _CURTA:
            return f"[web] {titulo} ({r.url}) — guardado como doc={doc}:\n\n{texto}"
        if payload.pergunta:
            trechos = self._acervo.partes_relevantes(payload.pergunta, doc)
            if trechos:
                corpo = "\n\n".join(f"── {t['caminho']} (secao={t['secao']}, parte={t['parte']}) ──\n{t['texto']}" for t in trechos)
                return (f"[web] {titulo} ({r.url}) — página longa ({len(texto) // 1000} mil chars), guardada como doc={doc}. "
                        f"Os {len(trechos)} trecho(s) mais relevantes para “{payload.pergunta}”:\n\n{corpo}\n\n"
                        f"Faltou algo? read_doc(doc=\"{doc}\") mostra o sumário; search_docs(consulta, documento=\"{doc}\") acha outros trechos.")
        s = self._acervo.sumario(doc) or {"secoes": []}
        secoes = "\n".join(f"§{x['n']} {x['caminho']} ({x['chars'] // 100 / 10} mil chars)" for x in s["secoes"] if x["chars"] >= 80)
        return (f"[web] {titulo} ({r.url}) — página longa ({len(texto) // 1000} mil chars), guardada como doc={doc}.\n"
                f"Sumário:\n{secoes}\nLeia as seções que importam com read_doc(doc=\"{doc}\", secao=N) "
                f"(ou search_docs(consulta, documento=\"{doc}\")).")


def _extrair(url: str, conteudo: bytes, tipo: str) -> tuple[str, str]:
    """(título, Markdown do conteúdo principal). HTML → trafilatura (tira menu/rodapé/propaganda); PDF → markitdown."""
    if "pdf" in tipo or url.lower().endswith(".pdf"):
        from infrastructure.acervo.acervo import para_markdown
        nome = url.rstrip("/").rsplit("/", 1)[-1] or "documento.pdf"
        return nome.removesuffix(".pdf"), para_markdown(nome if nome.endswith(".pdf") else nome + ".pdf", conteudo)
    import trafilatura
    html = conteudo.decode(_charset(tipo), "replace")
    texto = trafilatura.extract(html, url=url, output_format="markdown", include_tables=True, include_links=False,
                                include_comments=False, favor_recall=True)
    if not texto or len(texto) < 200:
        raise ValueError("não achei conteúdo de texto nessa página (só script/menu, ou exige login)")
    meta = trafilatura.extract_metadata(html, default_url=url)
    titulo = (meta.title if meta and meta.title else urlparse(url).path.strip("/").rsplit("/", 1)[-1] or url).strip()
    return titulo[:120], texto


def _charset(tipo: str) -> str:
    m = re.search(r"charset=([\w-]+)", tipo or "")
    return m[1] if m else "utf-8"
