"""Acervo: biblioteca de documentos (Markdown) que o agente CONSULTA em vez de responder de memória.

Como agentes que leem bem (o Claude, por exemplo) fazem: BUSCAR → ver o SUMÁRIO → LER só a seção que importa.
Nunca joga o documento inteiro no contexto (um tema da Estácio tem ~80 KB).

Arquivos:  data/acervo/<colecao>/.../<doc>.md   (frontmatter opcional: titulo, disciplina, ordem, fonte, url)
Índice:    data/acervo.db   (reconstruível: apagou → `python ops/acervo.py reindexar`)
  docs     id (caminho sem .md, ex.: "estacio/metodos-ageis/2-praticas-gerenciais-com-scrum"), titulo, meta
  secoes   cada título (#, ##, ###…) vira uma seção: caminho "Módulo 1 > O Scrum", texto, tamanho
  partes   seção grande quebrada em partes de ≤ ~3000 chars (no limite de parágrafo) — é o que a busca acha
  partes_fts  FTS5 sem acento sobre título do doc + caminho da seção + texto da parte
"""
import json
import os
import re
import sqlite3
import time
import unicodedata

PARTE_MAX = 3000

_SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS docs (
    id TEXT PRIMARY KEY, colecao TEXT NOT NULL, titulo TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}',
    arquivo TEXT NOT NULL, bytes INTEGER NOT NULL, indexado_em REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS secoes (
    doc_id TEXT NOT NULL, n INTEGER NOT NULL, nivel INTEGER NOT NULL, titulo TEXT NOT NULL, caminho TEXT NOT NULL,
    texto TEXT NOT NULL, PRIMARY KEY (doc_id, n)
);
CREATE TABLE IF NOT EXISTS partes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, secao INTEGER NOT NULL, parte INTEGER NOT NULL,
    texto TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS partes_fts USING fts5(titulo_doc, caminho, texto, tokenize = 'unicode61 remove_diacritics 2');
"""

_STOP = set("""a o as os um uma de do da dos das no na nos nas em por para pra com sem e ou que se nao sim como qual quais
quando onde porque sobre ao aos me te eu voce isso isto esse essa este esta ser ter foi era sao tem mais menos muito
explica explique fala fale diga mostra mostre o que sao quais""".split())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")
    return s[:80] or "doc"


def termos(consulta: str) -> list[str]:
    vistos: list[str] = []
    for p in re.findall(r"\w+", norm(consulta)):
        if len(p) >= 3 and p not in _STOP and p not in vistos:
            vistos.append(p)
    return vistos[:14]


def _frontmatter(texto: str) -> tuple[dict, str]:
    if texto.startswith("---\n"):
        fim = texto.find("\n---", 4)
        if fim > 0:
            meta = {}
            for linha in texto[4:fim].splitlines():
                if ":" in linha:
                    k, v = linha.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            return meta, texto[fim + 4:].lstrip("\n")
    return {}, texto


def _secoes(texto: str) -> list[tuple[int, str, str, str]]:
    """[(nivel, titulo, caminho, texto)] — cada título abre uma seção; o caminho é a pilha de títulos acima.
    Ignora '#' dentro de bloco de código."""
    out, pilha, viu_h1 = [], [], False
    atual = (0, "(início)", "(início)", [])
    em_codigo = False
    for linha in texto.splitlines():
        if linha.strip().startswith("```"):
            em_codigo = not em_codigo
        m = None if em_codigo else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", linha)
        if m:
            if "".join(atual[3]).strip():
                out.append((atual[0], atual[1], atual[2], "\n".join(atual[3]).strip()))
            nivel, titulo = len(m[1]), m[2].strip()
            if nivel == 1 and viu_h1:
                nivel = 4                                   # H1 no meio do tema = subtópico, não outro documento
            viu_h1 = viu_h1 or nivel == 1
            em_modulo = any(t.startswith("Módulo") for _, t in pilha)
            if nivel == 2 and em_modulo and not re.match(r"(Módulo|Introdução|Conclusão|Referências|Explore)", titulo):
                nivel = 3                                   # "## Pequenas entregas" dentro do Módulo 2 = seção dele
            titulo = re.sub(r"^(Módulo \d+)\s*[—-]\s*[a-z0-9]{12,}$", r"\1", titulo)   # "Módulo 1 — valoresep…" → "Módulo 1"
            pilha = [p for p in pilha if p[0] < nivel] + [(nivel, titulo)]
            caminho = " > ".join(t for n, t in pilha if n > 1) or titulo
            atual = (nivel, titulo, caminho, [])
        else:
            atual[3].append(linha)
    if "".join(atual[3]).strip():
        out.append((atual[0], atual[1], atual[2], "\n".join(atual[3]).strip()))
    return out


def _partes(texto: str) -> list[str]:
    """Quebra no limite de parágrafo (linha em branco), em pedaços de até PARTE_MAX."""
    blocos, atual = [], ""
    for par in re.split(r"\n\s*\n", texto):
        if atual and len(atual) + len(par) > PARTE_MAX:
            blocos.append(atual.strip())
            atual = ""
        while len(par) > PARTE_MAX:                         # parágrafo gigante (tabela): corta seco
            blocos.append(par[:PARTE_MAX])
            par = par[PARTE_MAX:]
        atual += par + "\n\n"
    if atual.strip():
        blocos.append(atual.strip())
    return blocos or [""]


# marcações de componentes da página original (acordeão, card, questão…) que vieram na conversão pra Markdown
_SAI = {"imagens", "cards", "accordions", "tabs", "modais", "itens carrossel", "conteudo accordion",
        "conteudo card tematico", "conteudo texto", "texto card", "descricao card", "conteudo tab", "conteudo modal",
        "right item", "left item", "legenda", "conteudo feedback"}
_CREDITO = {"creditos", "creditos accordion", "creditos tab"}               # some o rótulo E a linha seguinte
_TITULO = {"titulo accordion", "titulo card", "titulo modal", "titulo tab"}  # a linha seguinte vira **título**
_QUESTAO = {"enunciado questao": "enun", "conteudo enunciado questao": "enun", "titulo questao": "titulo",
            "conteudo feedback positivo": "certo", "conteudo feedback negativo": "errado",
            "alternativas": None, "alternativa resposta": "alt"}


def _questao(q: dict) -> list[str]:
    titulo = " ".join(q["titulo"]).strip() or "Questão"
    linhas = ["", f"**{titulo}.** {' '.join(q['enun']).strip()}"]
    for i, alt in enumerate(q["alts"]):
        linhas.append(f"- ({'abcdefgh'[i] if i < 8 else i + 1}) {' '.join(alt).strip()}")
    if q["certo"]:
        linhas.append(f"Resposta comentada: {' '.join(q['certo']).strip()}")
    if q["errado"]:
        linhas.append(f"Por que não: {' '.join(q['errado']).strip()}")
    return linhas + [""]


def _componentes(texto: str) -> str:
    """Desembrulha os componentes da página: tira o '>' de citação que os envolve, some rótulos e créditos de
    imagem, título de acordeão/card vira **negrito**, e cada questão do "Verificando o aprendizado" (que vem fora
    de ordem: enunciado, título, resposta, alternativas) é remontada como enunciado → (a)…(e) → resposta comentada."""
    out: list[str] = []
    pendente = None
    q = None
    campo = None

    def fecha():
        nonlocal q, campo
        if q is not None:
            out.extend(_questao(q))
        q, campo = None, None

    for linha in texto.splitlines():
        crua = re.sub(r"^(\s*>\s?)+", "", linha).rstrip()
        rot = re.fullmatch(r"\*\*([a-z_ ]+)\*\*", crua.strip())
        r = rot[1].strip() if rot else None
        if r in _QUESTAO:
            if _QUESTAO[r] == "enun" and (q is None or q["enun"]):
                fecha()
                q = {"enun": [], "titulo": [], "certo": [], "errado": [], "alts": []}
            if q is None:
                q = {"enun": [], "titulo": [], "certo": [], "errado": [], "alts": []}
            campo = _QUESTAO[r]
            if campo == "alt":
                q["alts"].append([])
            continue
        if q is not None and campo == "enun" and crua.startswith("#"):
            crua = crua.lstrip("#").strip()                     # alguns temas escrevem o enunciado como título
        if q is not None and (r is not None or crua.startswith("#")):
            fecha()                                             # outro componente/título: a questão acabou
        if q is not None:
            if crua.strip() and campo:
                (q["alts"][-1] if campo == "alt" else q[campo]).append(crua.strip())
            continue
        if r in _SAI:
            continue
        if r in _CREDITO:
            pendente = "some"
            continue
        if r in _TITULO:
            pendente = "titulo"
            continue
        if pendente and crua.strip():
            tipo, pendente = pendente, None
            if tipo == "some":
                continue
            out.extend(["", f"**{crua.strip()}**"])
            continue
        out.append(crua)
    fecha()
    return "\n".join(out)


def _limpo(texto: str) -> str:
    """Tira ruído de conversão (componentes, &nbsp;, quebras demais) sem mexer no conteúdo."""
    texto = _componentes(texto)
    texto = texto.replace(" ", " ")
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


class Acervo:
    def __init__(self, raiz: str, db: str) -> None:
        self.raiz, self.db = raiz, db
        os.makedirs(raiz, exist_ok=True)
        with self._c() as c:
            c.executescript(_SCHEMA)

    def _c(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db)

    # ── escrita / índice ───────────────────────────────────────────────────────────────────────────────
    def salvar(self, colecao: str, rel: str, texto: str, meta: dict | None = None) -> str:
        """Grava um .md no acervo (com frontmatter) e indexa. Devolve o id do documento."""
        caminho = os.path.join(self.raiz, colecao, rel if rel.endswith(".md") else rel + ".md")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        fm = "".join(f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}\n"
                     for k, v in (meta or {}).items())
        with open(caminho, "w", encoding="utf-8") as f:
            f.write((f"---\n{fm}---\n\n" if fm else "") + texto)
        return self.indexar(caminho)

    def indexar(self, caminho: str) -> str:
        texto = open(caminho, encoding="utf-8").read()
        meta, corpo = _frontmatter(texto)
        corpo = _limpo(corpo)
        rel = os.path.relpath(caminho, self.raiz).replace(os.sep, "/")
        doc_id = rel[:-3] if rel.endswith(".md") else rel
        colecao = doc_id.split("/", 1)[0]
        h1 = re.search(r"^#\s+(.+)$", corpo, re.M)
        titulo = meta.get("titulo") or (h1[1].strip() if h1 else os.path.basename(doc_id))
        secs = _secoes(corpo)
        with self._c() as c:
            for t in ("partes_fts",):
                c.execute(f"DELETE FROM {t} WHERE rowid IN (SELECT id FROM partes WHERE doc_id = ?)", (doc_id,))
            c.execute("DELETE FROM partes WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM secoes WHERE doc_id = ?", (doc_id,))
            c.execute("INSERT OR REPLACE INTO docs VALUES (?,?,?,?,?,?,?)",
                      (doc_id, colecao, titulo, json.dumps(meta, ensure_ascii=False), rel, len(corpo.encode()), time.time()))
            rotulo = " · ".join(x for x in (meta.get("disciplina"), titulo) if x)
            for n, (nivel, tit, cam, txt) in enumerate(secs):
                c.execute("INSERT INTO secoes VALUES (?,?,?,?,?,?)", (doc_id, n, nivel, tit, cam, txt))
                for k, pedaco in enumerate(_partes(txt)):
                    cur = c.execute("INSERT INTO partes(doc_id, secao, parte, texto) VALUES (?,?,?,?)", (doc_id, n, k, pedaco))
                    c.execute("INSERT INTO partes_fts(rowid, titulo_doc, caminho, texto) VALUES (?,?,?,?)",
                              (cur.lastrowid, rotulo, cam, pedaco))
        return doc_id

    def reindexar(self) -> int:
        n = 0
        with self._c() as c:
            c.execute("DELETE FROM partes_fts"); c.execute("DELETE FROM partes"); c.execute("DELETE FROM secoes"); c.execute("DELETE FROM docs")
        for base, _, arqs in os.walk(self.raiz):
            for a in sorted(arqs):
                if a.endswith(".md"):
                    self.indexar(os.path.join(base, a)); n += 1
        return n

    # ── leitura ────────────────────────────────────────────────────────────────────────────────────────
    def docs(self, colecao: str | None = None) -> list[dict]:
        with self._c() as c:
            rows = c.execute("SELECT id, colecao, titulo, meta, bytes FROM docs" + (" WHERE colecao = ?" if colecao else "")
                             + " ORDER BY id", (colecao,) if colecao else ()).fetchall()
        return [{"id": r[0], "colecao": r[1], "titulo": r[2], "meta": json.loads(r[3]), "bytes": r[4]} for r in rows]

    def achar_doc(self, ref: str) -> str | None:
        """Aceita o id exato ou um pedaço do título/id ('scrum', 'praticas gerenciais')."""
        with self._c() as c:
            if c.execute("SELECT 1 FROM docs WHERE id = ?", (ref,)).fetchone():
                return ref
            alvo = norm(ref)
            for i, t, m in c.execute("SELECT id, titulo, meta FROM docs ORDER BY id"):
                if alvo in norm(i) or alvo in norm(t) or alvo in norm(json.loads(m).get("disciplina", "")):
                    return i
        return None

    def buscar(self, consulta: str, colecao: str | None = None, doc: str | None = None, limite: int = 8) -> list[dict]:
        ts = termos(consulta)
        if not ts:
            return []
        q = " OR ".join(f'"{t}"*' for t in ts)
        sql = """SELECT p.doc_id, p.secao, p.parte, s.caminho, d.titulo, d.meta, p.texto,
                        bm25(partes_fts, 1.0, 4.0, 1.0) AS rank
                 FROM partes_fts JOIN partes p ON p.id = partes_fts.rowid
                 JOIN secoes s ON s.doc_id = p.doc_id AND s.n = p.secao JOIN docs d ON d.id = p.doc_id
                 WHERE partes_fts MATCH ?"""
        args: list = [q]
        if colecao:
            sql += " AND d.colecao = ?"; args.append(colecao)
        if doc:
            sql += " AND d.id = ?"; args.append(doc)
        sql += " ORDER BY rank LIMIT ?"; args.append(limite * 3)
        with self._c() as c:
            rows = c.execute(sql, args).fetchall()
        out, vistos = [], set()
        for d, s, p, cam, tit, meta, txt, _ in rows:
            if (d, s) in vistos:                                   # uma entrada por seção (a melhor parte)
                continue
            vistos.add((d, s))
            out.append({"doc": d, "secao": s, "parte": p, "caminho": cam, "titulo": tit,
                        "disciplina": json.loads(meta).get("disciplina", ""), "trecho": _trecho(txt, ts)})
            if len(out) >= limite:
                break
        return out

    def partes_relevantes(self, consulta: str, doc_id: str, limite: int = 3, max_chars: int = 7500) -> list[dict]:
        """As PARTES (texto original inteiro, não um resumo) do documento que mais respondem à consulta, em ordem
        de relevância — o jeito Perplexity: em vez de ler a página toda, entrega os pedaços que importam."""
        ts = termos(consulta)
        if not ts:
            return []
        q = " OR ".join(f'"{t}"*' for t in ts)
        with self._c() as c:
            rows = c.execute(
                """SELECT p.secao, p.parte, s.caminho, p.texto FROM partes_fts JOIN partes p ON p.id = partes_fts.rowid
                   JOIN secoes s ON s.doc_id = p.doc_id AND s.n = p.secao
                   WHERE partes_fts MATCH ? AND p.doc_id = ? ORDER BY bm25(partes_fts, 1.0, 4.0, 1.0) LIMIT ?""",
                (q, doc_id, limite * 2)).fetchall()
        out, total = [], 0
        for secao, parte, cam, txt in rows:
            if len(out) >= limite or (out and total + len(txt) > max_chars):
                break
            out.append({"secao": secao, "parte": parte, "caminho": cam, "texto": txt})
            total += len(txt)
        return out

    def sumario(self, doc_id: str) -> dict | None:
        with self._c() as c:
            d = c.execute("SELECT titulo, meta, bytes FROM docs WHERE id = ?", (doc_id,)).fetchone()
            if not d:
                return None
            secs = c.execute("SELECT s.n, s.nivel, s.titulo, s.caminho, length(s.texto), "
                             "(SELECT COUNT(*) FROM partes p WHERE p.doc_id = s.doc_id AND p.secao = s.n) "
                             "FROM secoes s WHERE s.doc_id = ? ORDER BY s.n", (doc_id,)).fetchall()
        return {"doc": doc_id, "titulo": d[0], "meta": json.loads(d[1]), "bytes": d[2],
                "secoes": [{"n": r[0], "nivel": r[1], "titulo": r[2], "caminho": r[3], "chars": r[4], "partes": r[5]} for r in secs]}

    def ler(self, doc_id: str, secao: int, parte: int = 0) -> dict | None:
        with self._c() as c:
            s = c.execute("SELECT caminho FROM secoes WHERE doc_id = ? AND n = ?", (doc_id, secao)).fetchone()
            if not s:
                return None
            total = c.execute("SELECT COUNT(*) FROM partes WHERE doc_id = ? AND secao = ?", (doc_id, secao)).fetchone()[0]
            p = c.execute("SELECT texto FROM partes WHERE doc_id = ? AND secao = ? AND parte = ?", (doc_id, secao, parte)).fetchone()
            prox = c.execute("SELECT n, caminho FROM secoes WHERE doc_id = ? AND n > ? ORDER BY n LIMIT 1", (doc_id, secao)).fetchone()
        if not p:
            return None
        return {"doc": doc_id, "secao": secao, "caminho": s[0], "parte": parte, "partes": total, "texto": p[0],
                "proxima_secao": {"n": prox[0], "caminho": prox[1]} if prox else None}


    def adicionar(self, nome: str, dados: bytes, colecao: str = "anexos", meta: dict | None = None) -> dict:
        """Arquivo enviado pelo dono (CLI, celular, painel) → Markdown → acervo/<colecao>/<nome>.md, indexado.
        Mesmo nome de arquivo = substitui (reenviar atualiza)."""
        texto = para_markdown(nome, dados)
        base = os.path.splitext(os.path.basename(nome))[0]
        if not re.search(r"^#\s+", texto, re.M):                          # sem título: o nome do arquivo vira o título
            texto = f"# {base}\n\n{texto}"
        doc = self.salvar(slug(colecao), slug(base), texto,
                          {"titulo": base, "fonte": "anexo", "arquivo": os.path.basename(nome),
                           "enviado_em": time.strftime("%Y-%m-%d %H:%M"), **(meta or {})})
        s = self.sumario(doc) or {"secoes": []}
        return {"doc": doc, "titulo": base, "secoes": len(s["secoes"]),
                "partes": sum(x["partes"] for x in s["secoes"]), "chars": sum(x["chars"] for x in s["secoes"])}

    def remover(self, doc_id: str) -> bool:
        with self._c() as c:
            r = c.execute("SELECT arquivo FROM docs WHERE id = ?", (doc_id,)).fetchone()
            if not r:
                return False
            c.execute("DELETE FROM partes_fts WHERE rowid IN (SELECT id FROM partes WHERE doc_id = ?)", (doc_id,))
            c.execute("DELETE FROM partes WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM secoes WHERE doc_id = ?", (doc_id,))
            c.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        try:
            os.remove(os.path.join(self.raiz, r[0]))
        except OSError:
            pass
        return True


def _trecho(texto: str, ts: list[str], tam: int = 320) -> str:
    """O pedaço em volta do 1º termo achado (sem acento na comparação)."""
    plano = re.sub(r"\s+", " ", texto)
    n = norm(plano)
    pos = min((n.find(t) for t in ts if n.find(t) >= 0), default=0)
    ini = max(0, pos - tam // 3)
    return ("…" if ini else "") + plano[ini:ini + tam].strip() + ("…" if ini + tam < len(plano) else "")


# ── documentos enviados pelo dono (CLI / celular / painel) ─────────────────────────────────────────────────
FORMATOS = {".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx", ".html", ".htm", ".csv", ".json", ".xlsx"}


def para_markdown(nome: str, dados: bytes) -> str:
    """Qualquer formato aceito → Markdown. md/txt passam direto; o resto vai pelo markitdown (Microsoft).
    PDF quase não tem títulos: cada página vira '## Página N' — assim o sumário e a leitura por seção funcionam."""
    import io
    ext = os.path.splitext(nome.lower())[1]
    if ext not in FORMATOS:
        raise ValueError(f"formato {ext or '(sem extensão)'} não suportado — aceito: {', '.join(sorted(FORMATOS))}")
    if ext in (".md", ".markdown", ".txt"):
        return dados.decode("utf-8", "replace")
    from markitdown import MarkItDown, StreamInfo                       # import tardio: pesa e só serve aqui
    texto = MarkItDown().convert_stream(io.BytesIO(dados), stream_info=StreamInfo(extension=ext, filename=nome)).text_content or ""
    if ext == ".pdf" and "\f" in texto:
        paginas = [p.strip() for p in texto.split("\f")]
        texto = "\n\n".join(f"## Página {i}\n\n{p}" for i, p in enumerate(paginas, 1) if p)
    if not texto.strip():
        raise ValueError("não consegui extrair texto (PDF escaneado/imagem? precisa de OCR)")
    return texto
