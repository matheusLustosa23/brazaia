from infrastructure.acervo.acervo import Acervo
from domain.tools.guard import ToolCtx
from infrastructure.tools.read_doc import ReadDocInput, ReadDocTool
from infrastructure.tools.search_docs import SearchDocsInput, SearchDocsTool

TEMA = """# Práticas gerenciais com Scrum

## Introdução

Capacitar pessoas a desenvolver projetos com Scrum.

## Módulo 1 — conceitosbasicospraticos

### Pilares

A implementação do controle de processo empírico é apoiada em três pilares.

> **imagens**
>
> > **creditos**
> >
> > Creative Stall/Shutterstock.com

> **accordions**
>
> > **titulo accordion**
> >
> > Transparência
>
> > **conteudo accordion**
> >
> > Todos devem saber o que é um incremento pronto.

## Eventos do Scrum

A sprint dura no máximo um mês.

### Verificando o aprendizado

> **enunciado questao**
>
> ### Qual destes é um pilar do Scrum?

> **titulo questao**
>
> Questão 1

> **conteudo feedback positivo**
>
> Transparência é um dos três pilares.

> **alternativas**
>
> > **alternativa resposta**
> >
> > Velocidade.
>
> > **alternativa resposta**
> >
> > Transparência.
"""


def _ac(tmp_path):
    ac = Acervo(str(tmp_path / "acervo"), str(tmp_path / "acervo.db"))
    ac.salvar("estacio", "metodos-ageis/02-scrum", TEMA, {"titulo": "Práticas gerenciais com Scrum", "disciplina": "Métodos Ágeis"})
    return ac


def test_componentes_desembrulhados(tmp_path):
    ac = _ac(tmp_path)
    s = ac.sumario("estacio/metodos-ageis/02-scrum")
    pil = next(x for x in s["secoes"] if x["titulo"] == "Pilares")
    txt = ac.ler(s["doc"], pil["n"])["texto"]
    assert "**Transparência**" in txt and "Shutterstock" not in txt and "accordion" not in txt
    assert pil["caminho"] == "Módulo 1 > Pilares"                       # nome grudado do módulo some


def test_secao_dentro_do_modulo_e_questao_em_ordem(tmp_path):
    ac = _ac(tmp_path)
    s = ac.sumario("estacio/metodos-ageis/02-scrum")
    ev = next(x for x in s["secoes"] if x["titulo"] == "Eventos do Scrum")
    assert ev["caminho"] == "Módulo 1 > Eventos do Scrum"               # "##" solto dentro do módulo
    vq = next(x for x in s["secoes"] if x["titulo"] == "Verificando o aprendizado")
    q = ac.ler(s["doc"], vq["n"])["texto"]
    assert q.index("**Questão 1.** Qual destes é um pilar do Scrum?") < q.index("- (a) Velocidade.") < q.index("Resposta comentada:")
    assert not any("Qual destes" in x["titulo"] for x in s["secoes"])   # enunciado em "###" não vira seção


def test_busca_sem_acento_e_por_qualquer_palavra(tmp_path):
    ac = _ac(tmp_path)
    r = ac.buscar("quais sao os pilares do scrum")
    assert r and r[0]["caminho"].endswith("Pilares") and r[0]["disciplina"] == "Métodos Ágeis"
    assert ac.buscar("transparencia")                                   # sem acento acha "Transparência"


def test_parte_grande_e_achar_doc(tmp_path):
    ac = Acervo(str(tmp_path / "a"), str(tmp_path / "a.db"))
    grande = "# Doc\n\n## Seção\n\n" + "\n\n".join(f"Parágrafo {i} " + "x" * 400 for i in range(20))
    ac.salvar("docs", "grande", grande)
    s = ac.sumario("docs/grande")
    sec = next(x for x in s["secoes"] if x["titulo"] == "Seção")
    assert sec["partes"] >= 3 and ac.ler("docs/grande", sec["n"], 1)["parte"] == 1
    assert ac.achar_doc("grande") == "docs/grande"


async def test_ferramentas(tmp_path):
    ac = _ac(tmp_path)
    ctx = ToolCtx(fala_do_usuario="")
    out = await SearchDocsTool(ac).run(SearchDocsInput(consulta="pilares scrum"), ctx)
    assert "Métodos Ágeis · Práticas gerenciais com Scrum › Módulo 1 > Pilares" in out and "read_doc" in out
    cat = await ReadDocTool(ac).run(ReadDocInput(), ctx)
    assert "• Métodos Ágeis" in cat and "doc=estacio/metodos-ageis/02-scrum" in cat
    sm = await ReadDocTool(ac).run(ReadDocInput(doc="scrum"), ctx)
    assert "§" in sm and "Pilares" in sm
    nada = await SearchDocsTool(ac).run(SearchDocsInput(consulta="cocomo"), ctx)
    assert "nada encontrado" in nada and "Métodos Ágeis" in nada


def test_rota_enviar_listar_buscar_remover(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from api.v1.routers import acervo_router
    from api.v1.setup import register_exception_handlers
    app = FastAPI(); register_exception_handlers(app)
    app.include_router(acervo_router.router, prefix="/api/v1")
    app.state.settings = SimpleNamespace(agent_api_key=SecretStr("k"))
    app.state.acervo = Acervo(str(tmp_path / "a"), str(tmp_path / "a.db"))
    c, h = TestClient(app), {"x-api-key": "k"}
    html = b"<h1>Regulamento</h1><h2>Pagamento</h2><p>Multa por atraso de 2% ao mes.</p>"
    r = c.post("/api/v1/acervo", files={"arquivo": ("regulamento.html", html)}, data={"colecao": "anexos"}, headers=h)
    assert r.status_code == 200 and r.json()["doc"] == "anexos/regulamento"
    assert [d["id"] for d in c.get("/api/v1/acervo", headers=h).json()["docs"]] == ["anexos/regulamento"]
    assert "Multa" in c.get("/api/v1/acervo/busca", params={"q": "multa atraso"}, headers=h).json()["trechos"][0]["trecho"]
    assert c.get("/api/v1/acervo/sumario/anexos/regulamento", headers=h).status_code == 200
    assert c.post("/api/v1/acervo", files={"arquivo": ("x.exe", b"MZ")}, headers=h).status_code == 415
    assert c.delete("/api/v1/acervo/anexos/regulamento", headers=h).json() == {"ok": True}
    assert c.get("/api/v1/acervo", headers=h).json()["docs"] == []
    assert c.get("/api/v1/acervo").status_code == 401
