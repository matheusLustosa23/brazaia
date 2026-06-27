from fastapi import Request, Header, WebSocket
from core.container import Container
from domain.contracts import LLMClient
from domain.exceptions.base import AgentError
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService

def _get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container



def get_llm(request: Request) -> LLMClient:
    return _get_container(request).ai.llm

def get_memory(request: Request) -> MemoryService:
    return _get_container(request).ai.memory

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