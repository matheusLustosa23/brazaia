"""Acervo do agente (documentos que ele CONSULTA): importar, reindexar, ver.

Uso (na raiz do repo):
  python ops/acervo.py importar-estacio <pasta do cache>   # cada tema: meta.json + tema.md → acervo/estacio/<disciplina>/<ordem>-<tema>.md
  python ops/acervo.py importar <arquivo.md|pasta> --colecao NOME   # qualquer Markdown
  python ops/acervo.py reindexar                            # refaz o índice a partir dos .md (apagou o acervo.db? isto recria)
  python ops/acervo.py status
  python ops/acervo.py buscar "pilares do scrum"            # testa a busca como o agente vê
Depois: `braza restart --agent` não é necessário (o índice é lido a cada busca).
"""
import argparse
import json
import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from infrastructure.acervo.acervo import Acervo, slug   # noqa: E402


def _acervo() -> Acervo:
    return Acervo(os.path.join(RAIZ, "data", "acervo"), os.path.join(RAIZ, "data", "acervo.db"))


_MINUSC = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "para", "com", "no", "na"}


def titulo_pt(s: str) -> str:
    """'MEDIDAS DE ESFORÇO DE DESENVOLVIMENTO' → 'Medidas de Esforço de Desenvolvimento'."""
    ps = s.strip().lower().split()
    return " ".join(p if (i and p in _MINUSC) else p[:1].upper() + p[1:] for i, p in enumerate(ps))


def importar_estacio(ac: Acervo, pasta: str) -> None:
    n = 0
    for nome in sorted(os.listdir(pasta)):
        d = os.path.join(pasta, nome)
        mj, md = os.path.join(d, "meta.json"), os.path.join(d, "tema.md")
        if not (os.path.isfile(mj) and os.path.isfile(md)):
            continue
        m = json.load(open(mj, encoding="utf-8"))
        disc = titulo_pt(m.get("disciplina") or "sem disciplina")
        titulo = (m.get("titulo") or nome).strip()
        rel = f"{slug(disc)}/{int(m.get('ordem') or 0):02d}-{slug(titulo)}"
        meta = {"titulo": titulo[:1] + titulo[1:].lower() if titulo.isupper() else titulo, "disciplina": disc,
                "ordem": m.get("ordem"), "fonte": "Estácio", "codigo": m.get("num_code"), "url": m.get("url_original", "")}
        doc = ac.salvar("estacio", rel, open(md, encoding="utf-8").read(), meta)
        print("  ✓", doc)
        n += 1
    print(f"{n} tema(s) importado(s)")


def importar(ac: Acervo, alvo: str, colecao: str) -> None:
    arqs = [alvo] if os.path.isfile(alvo) else [os.path.join(b, a) for b, _, fs in os.walk(alvo) for a in fs if a.endswith(".md")]
    base = os.path.dirname(alvo) if os.path.isfile(alvo) else alvo
    for a in sorted(arqs):
        rel = os.path.relpath(a, base)
        print("  ✓", ac.salvar(colecao, rel, open(a, encoding="utf-8").read()))


def main() -> None:
    ap = argparse.ArgumentParser(description="acervo de documentos do agente")
    ap.add_argument("acao", choices=["importar-estacio", "importar", "reindexar", "status", "buscar"])
    ap.add_argument("alvo", nargs="?")
    ap.add_argument("--colecao", default="docs")
    a = ap.parse_args()
    ac = _acervo()
    if a.acao == "importar-estacio":
        importar_estacio(ac, a.alvo)
    elif a.acao == "importar":
        importar(ac, a.alvo, a.colecao)
    elif a.acao == "reindexar":
        print(ac.reindexar(), "documento(s) reindexado(s)")
    elif a.acao == "buscar":
        for r in ac.buscar(a.alvo or ""):
            print(f"- {r['disciplina']} · {r['titulo']} › {r['caminho']}  [{r['doc']} §{r['secao']}]\n    {r['trecho'][:200]}")
    docs = ac.docs()
    if a.acao == "status":
        cols = {}
        for d in docs:
            cols.setdefault(d["colecao"], []).append(d)
        for col, ds in cols.items():
            print(f"{col}: {len(ds)} documento(s), {sum(d['bytes'] for d in ds) // 1024} KB")
            for d in ds:
                print(f"   {d['id']}  ·  {d['titulo']}")


if __name__ == "__main__":
    main()
