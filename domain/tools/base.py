from __future__ import annotations

import asyncio
from typing import ClassVar, Literal, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from domain.tools.guard import ToolCtx, GuardResult

InputType = TypeVar("InputType", bound=BaseModel)

Side = Literal["server", "device"]
ActionClass = Literal["read", "reversible", "destructive"]


class Tool(Generic[InputType]):
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema:type[InputType]
    side: ClassVar[Side] = "server"
    action_class: ClassVar[ActionClass] = "read"
    timeout_s: ClassVar[float] = 15.0
    
    def before(self, args: dict, ctx: ToolCtx) ->  GuardResult:
        return GuardResult(ok=True)
    
    def after(self, result: str, ctx: ToolCtx) -> GuardResult:
        return GuardResult(ok=True)
    
    async def run(self, payload: InputType) -> str:
        raise NotImplementedError()
    
    def openai_schema(self) -> dict:      
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> Tool | None:
        return self._tools.get(tool_name)

    def __contains__(self, name):
        return name in self._tools
    
    def get_all_tool_names(self) -> list[str]:
        """Retorna nomes de todas as tools registradas."""
        return list(self._tools.keys())
    
    
    async def run(self, name: str, payload: dict) -> str:
        tool = self.get(name)
        if tool is  None:
            return f"[erro] ferramenta '{name}' não existe"
        if tool.side == "device":
            return f"[erro] '{name}' é device-side; despache via Device Router"
        try:
            parsed = tool.input_schema.model_validate(payload)
        except ValidationError as e:
             return f"[erro de input em {name}] {e.errors()}"
        return await self._invoke(tool, parsed)

    
    
    async def _invoke(self, tool: Tool, parsed: BaseModel) -> str:
        try:
            return await asyncio.wait_for(tool.run(parsed), timeout=tool.timeout_s)
        except asyncio.TimeoutError:
            return f"[timeout] '{tool.name}' excedeu {tool.timeout_s}s"
        except Exception as e:
            return f"[erro ao executar {tool.name}] {type(e).__name__}: {e}"
    
    def as_openai_tools(
        self,
        *,
        only: list[str] | None = None
    ) -> list[dict]:
        """Schema nativo de function calling consumido pelo vLLM (parser hermes)."""
        items = (
            [self._tools[n] for n in only if n in self._tools]
            if only is not None
            else list(self._tools.values())
        )
        return [
            t.openai_schema()
            for t in items
        ]
    
    def describe_all(self) -> str:
        """Texto compacto p/ o system estático (preserva prefix cache do vLLM)."""
        return "\n".join(
            f"- {t.name} [{t.side}/{t.action_class}]: {t.description}"
            for t in self._tools.values()
        )
    
    def for_device(self, capabilities: set[str] | None = None) -> ToolRegistry:
        """Subconjunto: server-side sempre + device-side só se a capability existir."""
        sub = ToolRegistry()
        for t in self._tools.values():
            if t.side == "server":
                sub.register(t)
            elif capabilities and t.name in capabilities:
                sub.register(t)
        return sub