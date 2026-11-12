import hashlib
import hmac

from fastapi import Request, Header, WebSocket
from core.container import Container
from domain.contracts import LLMClient
from domain.exceptions.base import AgentError
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService

def _get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container



def get_llm(request: Request) -> LLMClient:
    return _get_container(request).ai.llm

def get_orchestrator(request: Request) -> Orchestrator:
    return _get_container(request).orchestrator



def get_asr(websocket: WebSocket):
    return websocket.app.state.asr

def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.agent_api_key.get_secret_value()
    if x_api_key != expected:
        raise AgentError("api key inválida", status=401)


# ── painel (navegador) ──────────────────────────────────────────────────────────────────────────────────
# O navegador não manda x-api-key. Abre-se UMA vez /painel/?k=<chave>; o servidor devolve um cookie com um
# HMAC da chave (a chave em si nunca fica no cookie) e tira a chave da URL. Trocar a chave invalida os cookies.
COOKIE_PAINEL = "braza_painel"


def token_painel(chave: str) -> str:
    return hmac.new(chave.encode(), b"painel-v1", hashlib.sha256).hexdigest()


def chave_ok(request: Request, chave: str | None) -> bool:
    esperado = request.app.state.settings.agent_api_key.get_secret_value()
    return chave is not None and hmac.compare_digest(chave, esperado)


def cookie_ok(request: Request) -> bool:
    esperado = token_painel(request.app.state.settings.agent_api_key.get_secret_value())
    return hmac.compare_digest(request.cookies.get(COOKIE_PAINEL, ""), esperado)


def require_painel(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """API do painel: aceita o cookie do navegador OU a x-api-key (CLI/scripts)."""
    if not (cookie_ok(request) or chave_ok(request, x_api_key)):
        raise AgentError("acesso ao painel negado — abra /painel/?k=<chave> uma vez", status=401)
