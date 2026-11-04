"""Painel do agente no navegador: páginas estáticas em /painel/ + API JSON em /api/v1/painel/….

Servido pelo próprio agente (só a tailnet alcança o server). Acesso: /painel/?k=<chave> uma vez → cookie.
As páginas leem/escrevem pelos MESMOS serviços que as tools usam (gateway de devices, cérebro): uma regra só.
"""
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from api.v1.dependencies import COOKIE_PAINEL, chave_ok, cookie_ok, require_painel, token_painel

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
