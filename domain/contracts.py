from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from domain.entities.message import Completion


@runtime_checkable
class LLMClient(Protocol):
    """Contrato do engine. `application/` depende disto, nunca do `openai`.

    Implementado por `infrastructure.llm.client.OpenAILLMClient` e por fakes nos testes.
    """
    
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **opst: Any
    ) -> Completion: ...
    
    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tools_choice: str = "auto",
        **opts: Any
        ) -> AsyncIterator[tuple[str, Any]]: ...
    
    async def health(self) -> dict: ...