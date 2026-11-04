"""Painel do agente no navegador: páginas estáticas em /painel/ + API JSON em /api/v1/painel/….

Servido pelo próprio agente (só a tailnet alcança o server). Acesso: /painel/?k=<chave> uma vez → cookie.
As páginas leem/escrevem pelos MESMOS serviços que as tools usam (gateway de devices, cérebro): uma regra só.
"""
import base64
import dataclasses
import os
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from api.v1.dependencies import COOKIE_PAINEL, chave_ok, cookie_ok, require_painel, token_painel
from infrastructure.devices import google_timeline

WEB = os.path.join(os.path.dirname(__file__), "..", "..", "..", "web", "painel")

pagina = APIRouter(tags=["painel"])                       # montado na raiz: /painel/
api = APIRouter(prefix="/painel", tags=["painel"])        # montado em /api/v1: /api/v1/painel/…

_NEGADO = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Painel</title><body style="font:16px system-ui;padding:2rem;max-width:36rem">
<h1>Painel do agente</h1><p>Acesso não autorizado neste navegador.</p>
<p>Abra uma vez <code>/painel/?k=&lt;AGENT_API_KEY&gt;</code> — o navegador guarda um cookie e a chave sai da URL.</p>"""


@pagina.get("/painel", include_in_schema=False)
async def sem_barra():
    return RedirectResponse("/painel/")


@pagina.get("/painel/", include_in_schema=False)
async def index(request: Request, k: str | None = None):
    if k is not None:
        if not chave_ok(request, k):
            return HTMLResponse(_NEGADO, status_code=401)
        r = RedirectResponse("/painel/", status_code=303)          # tira a chave da URL (histórico/tela)
        r.set_cookie(COOKIE_PAINEL, token_painel(k), max_age=60 * 60 * 24 * 90, httponly=True, samesite="lax")
        return r
    if not cookie_ok(request):
        return HTMLResponse(_NEGADO, status_code=401)
    return FileResponse(os.path.join(WEB, "index.html"), media_type="text/html; charset=utf-8")


# ── devices ────────────────────────────────────────────────────────────────────────────────────────────
@api.get("/devices", dependencies=[Depends(require_painel)])
async def devices(request: Request):
    return {"devices": await request.app.state.container.device.gateway.listar_status()}


class NotificarIn(BaseModel):
    title: str = Field(default="Painel", max_length=80)
    message: str = Field(default="teste do painel", max_length=500)


@api.post("/devices/{device_id}/notificar", dependencies=[Depends(require_painel)])
async def notificar(device_id: str, corpo: NotificarIn, request: Request):
    """Mesma tool que o agente usa (notify) — o painel não tem caminho próprio pro device."""
    gw = request.app.state.container.device.gateway
    r = await gw.request(device_id, "notify", {"title": corpo.title, "message": corpo.message})
    ok = isinstance(r, str) and not r.startswith(("[erro]", "[timeout]"))
    return {"ok": ok, "resultado": r}


@api.get("/devices/{device_id}/localizacoes", dependencies=[Depends(require_painel)])
async def localizacoes(device_id: str, request: Request, horas: float = 24, desde: float | None = None,
                       ate: float | None = None):
    """Trilha do device: últimas `horas`, ou o intervalo desde/ate (epoch). Mais recente primeiro."""
    svc = request.app.state.container.device.service
    ini = desde if desde is not None else time.time() - horas * 3600
    pts = await svc.localizacoes(device_id, desde=ini, limite=20000)
    if ate is not None:
        pts = [p for p in pts if p.quando <= ate]
    return {"device": device_id, "pontos": [dataclasses.asdict(p) for p in pts]}


@api.post("/devices/{device_id}/localizar", dependencies=[Depends(require_painel)])
async def localizar(device_id: str, request: Request):
    """Lê a posição AGORA (mesmo caminho da tool get_location) e grava no histórico."""
    ponto, motivo = await request.app.state.container.device.gateway.localizar(device_id)
    return {"ok": ponto is not None, "ponto": ponto, "motivo": motivo}


# ── ferramentas do device pelo painel (os MESMOS handlers que o agente chama) ──────────────────────────
def _gw(request: Request):
    return request.app.state.container.device.gateway


def _falhou(r) -> bool:
    return not isinstance(r, str) or r.startswith(("[erro", "[timeout]"))


class CapturarIn(BaseModel):
    camera: str | None = Field(default=None, description="back | front (celular); vazio = a padrão")


@api.post("/devices/{device_id}/capturar", dependencies=[Depends(require_painel)])
async def capturar(device_id: str, corpo: CapturarIn, request: Request):
    r = await _gw(request).request(device_id, "capture_image", {"camera": corpo.camera}, timeout=45)
    if _falhou(r) or not str(r).startswith("data:image"):
        return {"ok": False, "motivo": str(r)[:300]}
    return {"ok": True, "imagem": r}


_MAX_ABRIR = 15 * 1024 * 1024


@api.post("/devices/{device_id}/abrir", dependencies=[Depends(require_painel)])
async def abrir(device_id: str, request: Request, arquivo: UploadFile = File(...)):
    """Arquivo arrastado pro painel → abre NO DEVICE (HTML no navegador dele, imagem no visualizador)."""
    dados = await arquivo.read()
    if len(dados) > _MAX_ABRIR:
        raise HTTPException(status_code=413, detail="arquivo maior que 15 MB")
    nome = (arquivo.filename or "").lower()
    tipo = arquivo.content_type or ""
    if nome.endswith((".html", ".htm")) or tipo == "text/html":
        r = await _gw(request).request(device_id, "display_page", {"html": dados.decode("utf-8", "replace")})
    elif tipo.startswith("image/") or nome.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        mime = tipo if tipo.startswith("image/") else "image/" + ("jpeg" if nome.endswith(("jpg", "jpeg")) else nome.rsplit(".", 1)[-1])
        uri = f"data:{mime};base64," + base64.b64encode(dados).decode()
        r = await _gw(request).request(device_id, "open_image", {"image": uri}, timeout=45)
    else:
        raise HTTPException(status_code=415, detail="só HTML ou imagem (png, jpg, webp, gif)")
    return {"ok": not _falhou(r), "resultado": str(r)[:300]}


@api.post("/devices/{device_id}/estado", dependencies=[Depends(require_painel)])
async def atualizar_estado(device_id: str, request: Request):
    """Lê a bateria agora (get_estado) e grava."""
    import orjson
    r = await _gw(request).request(device_id, "get_estado", {})
    try:
        est = orjson.loads(r) if isinstance(r, str) and r.startswith("{") else None
    except orjson.JSONDecodeError:
        est = None
    if not isinstance(est, dict):
        return {"ok": False, "motivo": str(r)[:200]}
    await request.app.state.container.device.service.atualizar_estado(device_id, est)
    return {"ok": True, "estado": est}


@api.post("/devices/{device_id}/localizacoes/importar", dependencies=[Depends(require_painel)])
async def importar_google(device_id: str, request: Request, arquivo: UploadFile = File(...)):
    """Timeline.json exportado do Google Maps → histórico deste device (origem 'google')."""
    try:
        pontos = google_timeline.ler(await arquivo.read())
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"não reconheci o arquivo da Linha do tempo: {e}")
    novos = await request.app.state.container.device.service.salvar_localizacoes(device_id, pontos, origem="google")
    return {"ok": True, "lidos": len(pontos), "novos": novos,
            "de": pontos[0]["quando"] if pontos else None, "ate": pontos[-1]["quando"] if pontos else None}



# ── cérebro (P3): grafo, ficha, gestão, linha do tempo, revisar ─────────────────────────────────────────
def _cer(request: Request):
    return request.app.state.container.ai.memory


async def _ou_422(coro):
    try:
        return await coro
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@api.get("/cerebro", dependencies=[Depends(require_painel)])
async def cerebro_panorama(request: Request):
    return await _cer(request).panorama()


@api.get("/cerebro/entidades/{ent_id}", dependencies=[Depends(require_painel)])
async def cerebro_ficha(ent_id: int, request: Request):
    f = await _cer(request).ficha(ent_id)
    if f is None:
        raise HTTPException(status_code=404, detail="entidade não existe")
    return f


class EntidadeIn(BaseModel):
    nome: str | None = Field(default=None, max_length=120)
    tipo: str | None = Field(default=None, max_length=60)
    area: str | None = Field(default=None, max_length=40)


@api.post("/cerebro/entidades", dependencies=[Depends(require_painel)])
async def cerebro_criar(corpo: EntidadeIn, request: Request):
    return await _ou_422(_cer(request).criar_entidade(corpo.nome or "", corpo.tipo))


@api.patch("/cerebro/entidades/{ent_id}", dependencies=[Depends(require_painel)])
async def cerebro_editar(ent_id: int, corpo: EntidadeIn, request: Request):
    return await _ou_422(_cer(request).editar_entidade(ent_id, corpo.nome, corpo.tipo, corpo.area))


@api.delete("/cerebro/entidades/{ent_id}", dependencies=[Depends(require_painel)])
async def cerebro_apagar(ent_id: int, request: Request):
    return await _ou_422(_cer(request).apagar_entidade(ent_id))


class ObservacaoIn(BaseModel):
    entidade_id: int
    categoria: str = Field(default="observacao", max_length=60)
    texto: str = Field(max_length=1000)
    substitui: int | None = None          # editar = corrigir: a antiga fica no histórico


@api.post("/cerebro/observacoes", dependencies=[Depends(require_painel)])
async def cerebro_observar(corpo: ObservacaoIn, request: Request):
    return await _ou_422(_cer(request).nova_observacao(corpo.entidade_id, corpo.categoria, corpo.texto, corpo.substitui))


@api.post("/cerebro/observacoes/{obs_id}/invalidar", dependencies=[Depends(require_painel)])
async def cerebro_invalidar(obs_id: int, request: Request):
    return {"ok": await _cer(request).invalidar_observacao(obs_id)}


@api.delete("/cerebro/observacoes/{obs_id}", dependencies=[Depends(require_painel)])
async def cerebro_apagar_obs(obs_id: int, request: Request):
    return {"ok": await _cer(request).apagar_observacao(obs_id)}


class RelacaoIn(BaseModel):
    de_id: int
    tipo: str = Field(max_length=60)
    para: str = Field(max_length=120)     # nome da outra entidade (criada se não existir)


@api.post("/cerebro/relacoes", dependencies=[Depends(require_painel)])
async def cerebro_relacionar(corpo: RelacaoIn, request: Request):
    return await _ou_422(_cer(request).nova_relacao(corpo.de_id, corpo.tipo, corpo.para))


@api.delete("/cerebro/relacoes/{rel_id}", dependencies=[Depends(require_painel)])
async def cerebro_apagar_rel(rel_id: int, request: Request):
    return {"ok": await _cer(request).apagar_relacao(rel_id)}


@api.get("/cerebro/registros", dependencies=[Depends(require_painel)])
async def cerebro_registros(request: Request, tipo: str | None = None, entidade_id: int | None = None,
                            desde: float | None = None, ate: float | None = None):
    return {"registros": await _cer(request).lista_registros(tipo, entidade_id, desde, ate)}


@api.post("/cerebro/registros/{reg_id}/invalidar", dependencies=[Depends(require_painel)])
async def cerebro_invalidar_reg(reg_id: int, request: Request):
    return {"ok": await _cer(request).invalidar_registro(reg_id)}


@api.get("/cerebro/revisar", dependencies=[Depends(require_painel)])
async def cerebro_revisar(request: Request, dias: float = 7):
    return await _cer(request).revisar(dias)


@api.get("/cerebro/busca", dependencies=[Depends(require_painel)])
async def cerebro_busca(request: Request, q: str = ""):
    return await _cer(request).busca_painel(q)
