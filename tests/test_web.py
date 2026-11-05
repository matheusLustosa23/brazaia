import httpx
import pytest

from domain.tools.guard import ToolCtx
from infrastructure.acervo.acervo import Acervo
from infrastructure.tools import web as W

HTML = ("<html><head><title>Pilares do Scrum</title></head><body><nav>menu menu menu</nav><article>"
        "<h1>Pilares do Scrum</h1>" + "".join(f"<p>Parágrafo {i}: transparência, inspeção e adaptação sustentam o Scrum empírico no ciclo {i}.</p>" for i in range(12)) +
        "</article><footer>rodapé © 2026</footer></body></html>")


class _Resp:
    def __init__(self, status=200, content=b"", tipo="text/html; charset=utf-8", url="https://ex.com/p"):
        self.status_code, self.content, self.headers, self.url = status, content, {"content-type": tipo}, url

    def json(self):
        import json
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)  # type: ignore[arg-type]


def _cliente(resp):
    class C:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return resp
    return C


async def test_fetch_extrai_e_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(W.httpx, "AsyncClient", _cliente(_Resp(content=HTML.encode())))
    ac = Acervo(str(tmp_path / "a"), str(tmp_path / "a.db"))
    out = await W.WebFetchTool(ac, "teste/1.0").run(W.WebFetchInput(url="https://ex.com/p"), ToolCtx(fala_do_usuario=""))
    assert out.startswith("[web] Pilares do Scrum") and "transparência" in out and "rodapé" not in out and "menu menu" not in out
    assert ac.docs()[0]["colecao"] == "web" and ac.docs()[0]["meta"]["url"] == "https://ex.com/p"


async def test_fetch_recusado_por_robo(tmp_path, monkeypatch):
    monkeypatch.setattr(W.httpx, "AsyncClient", _cliente(_Resp(status=403)))
    out = await W.WebFetchTool(Acervo(str(tmp_path / "a"), str(tmp_path / "a.db")), "t").run(
        W.WebFetchInput(url="https://ex.com/p"), ToolCtx(fala_do_usuario=""))
    assert "recusou robôs" in out


async def test_search_formata(monkeypatch):
    import json
    dados = {"results": [{"title": "Pilares", "url": "https://www.ex.com/a", "content": "três pilares", "publishedDate": "2026-10-01T00:00"},
                         {"title": "Dup", "url": "https://www.ex.com/a", "content": "x"}]}
    monkeypatch.setattr(W.httpx, "AsyncClient", _cliente(_Resp(content=json.dumps(dados).encode())))
    out = await W.WebSearchTool("http://x").run(W.WebSearchInput(consulta="pilares"), ToolCtx(fala_do_usuario=""))
    assert "1. Pilares — ex.com · 2026-10-01" in out and "Dup" not in out and "web_fetch" in out


async def test_fetch_com_pergunta_devolve_trechos(tmp_path, monkeypatch):
    blocos = "".join(f"<h2>Seção {i}</h2>" + "".join(f"<p>Texto genérico {i}.{k} sobre assuntos diversos do projeto, da equipe, das reuniões e dos artefatos de acompanhamento número {i*100+k}.</p>" for k in range(20))
                     for i in range(6))
    blocos += "<h2>Product Goal</h2>" + "".join(f"<p>O Product Goal é o objetivo de longo prazo do produto, item {k}.</p>" for k in range(8))
    html = f"<html><head><title>Guia</title></head><body><article><h1>Guia</h1>{blocos}</article></body></html>"
    monkeypatch.setattr(W.httpx, "AsyncClient", _cliente(_Resp(content=html.encode())))
    ac = Acervo(str(tmp_path / "a"), str(tmp_path / "a.db"))
    out = await W.WebFetchTool(ac, "t").run(W.WebFetchInput(url="https://ex.com/g", pergunta="product goal"), ToolCtx(fala_do_usuario=""))
    assert "trecho(s) mais relevantes" in out and "Product Goal é o objetivo" in out
    assert out.index("Product Goal") < (out.find("Texto genérico") if "Texto genérico" in out else len(out))
