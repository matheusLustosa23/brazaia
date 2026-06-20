from fastapi import Request, Header

from domain.contracts import LLMClient
from domain.exceptions.base import AgentError
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator

def get_llm(request: Request) -> LLMClient:
    """Injeta o LLMClient guardado no app.state pelo lifespan."""
    return request.app.state.llm

def get_memory(request: Request) -> MemoryService:
    return request.app.state.memory

def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator

def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None)
) -> None:
    """PLACEHOLDER de auth — comparação simples com AGENT_API_KEY (SecretStr).
    Rate-limit / ACL / política de ações ficam para feat-access-control.
    Lança AgentError → handler converte no envelope ApiResponse."""
    expected = request.app.state.settings.agent_api_key.get_secret_value()
    if x_api_key != expected:
        raise AgentError("api key inválida", status=401)