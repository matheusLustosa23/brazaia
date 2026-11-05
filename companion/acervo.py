"""python -m companion acervo — manda documentos pro ACERVO do agente (ele passa a consultar com search_docs).

Funciona de qualquer device (desktop ou Termux): o arquivo vai pela mesma rota que o painel usa; o server
converte (PDF, Word, PowerPoint, HTML, planilha…) pra Markdown, corta em seções e indexa.

Uso:
  python -m companion acervo add ~/Downloads/contrato.pdf            # coleção "anexos"
  python -m companion acervo add aula1.pdf aula2.pdf --colecao facul  # vários de uma vez, noutra coleção
  python -m companion acervo lista
  python -m companion acervo buscar "multa por atraso"
  python -m companion acervo tirar anexos/contrato
Depois é só perguntar no chat: "o que o contrato diz sobre multa?".
"""
import argparse
import asyncio
import os
import sys

import httpx

from companion._json import loads
from companion.chat_client import _headers, _http_base
from companion.config import load_config


def _cliente(timeout: float = 120) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, proxy=os.getenv("SOCKS_PROXY") or None)


async def enviar_documento(cfg, caminho: str, colecao: str = "anexos") -> dict:
    """Usado pelo comando e pelo CLI (/documento). Devolve {doc, titulo, secoes, partes, chars} ou levanta erro legível."""
    caminho = os.path.expanduser(caminho)
    if not os.path.isfile(caminho):
        raise FileNotFoundError(f"arquivo não encontrado: {caminho}")
    with open(caminho, "rb") as f:
        dados = f.read()
    async with _cliente() as http:
        r = await http.post(f"{_http_base(cfg.server_ws_url)}/acervo", headers=_headers(),
                            files={"arquivo": (os.path.basename(caminho), dados)}, data={"colecao": colecao})
    if r.status_code >= 400:
        try:
            msg = loads(r.content).get("message") or r.text
        except Exception:
            msg = r.text
        raise RuntimeError(f"o server recusou ({r.status_code}): {msg}")
    return loads(r.content)


async def _lista(cfg) -> None:
    async with _cliente(30) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/acervo", headers=_headers())
        r.raise_for_status()
    docs = loads(r.content)["docs"]
    por: dict[str, list] = {}
    for d in docs:
        por.setdefault(d["colecao"], []).append(d)
    for col, ds in por.items():
        print(f"📚 {col} ({len(ds)})")
        for d in ds:
            extra = d["meta"].get("disciplina") or d["meta"].get("enviado_em") or ""
            print(f"   {d['id']}  ·  {d['titulo']}  {('· ' + extra) if extra else ''}")


async def _buscar(cfg, q: str) -> None:
    async with _cliente(30) as http:
        r = await http.get(f"{_http_base(cfg.server_ws_url)}/acervo/busca", headers=_headers(), params={"q": q})
        r.raise_for_status()
    for t in loads(r.content)["trechos"]:
        print(f"- {t['titulo']} › {t['caminho']}  [{t['doc']} §{t['secao']}]\n    {t['trecho'][:220]}")


async def _tirar(cfg, doc: str) -> None:
    async with _cliente(30) as http:
        r = await http.delete(f"{_http_base(cfg.server_ws_url)}/acervo/{doc}", headers=_headers())
    print("🗑 removido" if r.status_code == 200 else f"não removi ({r.status_code}): {r.text[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m companion acervo", description="documentos que o agente consulta")
    ap.add_argument("acao", choices=["add", "lista", "buscar", "tirar"])
    ap.add_argument("alvos", nargs="*")
    ap.add_argument("--colecao", default="anexos")
    a = ap.parse_args()
    cfg = load_config()
    if a.acao == "add":
        if not a.alvos:
            sys.exit("diga o(s) arquivo(s): python -m companion acervo add arquivo.pdf")
        for arq in a.alvos:
            try:
                r = asyncio.run(enviar_documento(cfg, arq, a.colecao))
                tam = f"{r['chars'] // 1000} mil" if r["chars"] >= 1000 else str(r["chars"])
                print(f"✅ {os.path.basename(arq)} → {r['doc']} · {r['secoes']} seção(ões), {tam} caracteres")
            except Exception as e:
                print(f"❌ {os.path.basename(arq)}: {e}")
    elif a.acao == "lista":
        asyncio.run(_lista(cfg))
    elif a.acao == "buscar":
        asyncio.run(_buscar(cfg, " ".join(a.alvos)))
    else:
        for d in a.alvos:
            asyncio.run(_tirar(cfg, d))


if __name__ == "__main__":
    main()
