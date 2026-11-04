from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from api.v1.dependencies import COOKIE_PAINEL, token_painel
from api.v1.routers import painel_router
from api.v1.setup import register_exception_handlers

CHAVE = "segredo-teste"


class _GW:
    def __init__(self):
        self.enviados = []

    async def listar_status(self):
        return [{"id": "S24", "nome": "Celular", "status": "active", "conectado": True, "conectado_desde": 1.0,
                 "ultima_vez": 2.0, "registrado_em": 0.5, "tools": ["notify"]}]

    async def request(self, device_id, name, args):
        self.enviados.append((device_id, name, args))
        return "ok"


def _app():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(painel_router.api, prefix="/api/v1")
    app.include_router(painel_router.pagina)
    app.state.settings = SimpleNamespace(agent_api_key=SecretStr(CHAVE))
    gw = _GW()
    app.state.container = SimpleNamespace(device=SimpleNamespace(gateway=gw))
    return app, gw


def test_sem_cookie_nega():
    app, _ = _app()
    c = TestClient(app)
    assert c.get("/painel/").status_code == 401
    assert c.get("/api/v1/painel/devices").status_code == 401


def test_chave_na_url_vira_cookie_e_sai_da_url():
    app, _ = _app()
    c = TestClient(app, follow_redirects=False)
    r = c.get(f"/painel/?k={CHAVE}")
    assert r.status_code == 303 and r.headers["location"] == "/painel/"
    assert CHAVE not in r.headers["set-cookie"]                 # o cookie guarda o HMAC, não a chave
    assert c.cookies.get(COOKIE_PAINEL) == token_painel(CHAVE)
    assert c.get("/painel/").status_code == 200
    assert c.get("/api/v1/painel/devices").json()["devices"][0]["id"] == "S24"


def test_chave_errada_nega():
    app, _ = _app()
    assert TestClient(app).get("/painel/?k=errada").status_code == 401


def test_api_aceita_x_api_key():
    app, _ = _app()
    assert TestClient(app).get("/api/v1/painel/devices", headers={"x-api-key": CHAVE}).status_code == 200


def test_notificar_usa_a_tool_do_device():
    app, gw = _app()
    r = TestClient(app).post("/api/v1/painel/devices/S24/notificar", json={"message": "oi"},
                             headers={"x-api-key": CHAVE})
    assert r.json()["ok"] is True and gw.enviados == [("S24", "notify", {"title": "Painel", "message": "oi"})]
