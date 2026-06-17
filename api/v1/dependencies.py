from fastapi import Request

from domain.contracts import LLMClient
from application.services.memory_service import MemoryService

def get_llm(request: Request) -> LLMClient:
    """Injeta o LLMClient guardado no app.state pelo lifespan."""
    return request.app.state.llm

def get_memory(request: Request) -> MemoryService:
    return request.state.memory