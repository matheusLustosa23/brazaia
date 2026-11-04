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

