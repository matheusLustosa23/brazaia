from fastapi import Request

from domain.contracts import LLMClient

def get_llm(request: Request) -> LLMClient:
    """Injeta o LLMClient guardado no app.state pelo lifespan."""
    return request.app.state.llm