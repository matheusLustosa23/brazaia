from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from domain.entities.message import Completion
from domain.entities.memory_fact import MemoryFact


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
        **opts: Any
    ) -> Completion: ...
    
    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **opts: Any
        ) -> AsyncIterator[tuple[str, Any]]: ...
    
    async def health(self) -> dict: ...
    
@runtime_checkable
class MemoryStore(Protocol):
    """Persistência da memória pessoal. Implementado por infrastructure.memory.sqlite_store."""
    
    async def init(self) -> None: ...
    async def upsert_fact(self, fact: MemoryFact) -> tuple[int, str]: ...
    async def forget(self, fact_id: int) -> None: ...
    async def by_category(self, category: str) -> list[MemoryFact]: ...
    async def search(self, query: str, limit: int = 10) -> list[MemoryFact]: ...
    async def link(
        self,
        from_id: int,
        to_id: int,
        relation: str,
        strength: float = 1.0,
        origin: str = "inferred"
    ) -> None: ...

class DeviceRouter(Protocol):
    """Roteador de ações device-side. Implementado por infrastructure.devices.device_router."""
    
    async def dispatch(self, device_id: str | None, tool_call: dict) -> str: ...
    def capabilities(self, device_id: str | None) -> set[str] | None: ...

class SessionStore(Protocol):
    """Contrato de sessões. Injetado no Orchestrator (application service)."""
    async def create(self) -> str: ...
    async def get(self, session_id: str) -> list[dict]: ...
    async def append(self, session_id: str, message: dict) -> None: ...
    async def set(self, session_id: str, history: list[dict]) -> None: ...