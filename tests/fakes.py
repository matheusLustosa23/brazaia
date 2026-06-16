from collections.abc import AsyncIterator
from typing import Any

from domain.entities.message import Completion


class FakeLLM:
    """Satisfaz domain.contracts.LLMClient; registra as chamadas a complete()."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **opts: Any,
    ) -> Completion:
        self.calls.append(messages)
        return Completion(content="RESUMO")

    def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **opts: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        async def _gen() -> AsyncIterator[tuple[str, Any]]:
            yield ("text", "resumo")

        return _gen()

    async def health(self) -> dict:
        return {"vllm": "up", "model": "fake"}
    
def fake_count(msgs: list[dict]) -> int:
    """Contador determinístico (nº de caracteres do content) — exato e aditivo p/ os testes."""
    return sum(
        len(str(m.get("content","")))
        for m in msgs 
    )