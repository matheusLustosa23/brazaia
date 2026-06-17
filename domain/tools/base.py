from __future__ import annotations

import asyncio
from typing import ClassVar, Literal

from pydantic import BaseModel, ValidationError

Side = Literal["server", "device"]
ActionClass = Literal["read", "reversible", "destructive"]


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]
    side: ClassVar[Side] = "server"
    action_class: ClassVar[ActionClass] = "read"
    timeout_s: ClassVar[float] = 15.0
    
    async def run(self, payload: BaseModel) -> str:
        raise NotImplementedError()

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
    
    def get(self, tool_name: str) -> Tool | None:
        return self._tools.get(tool_name)
    
    def __contains__(self, name):
        return name in self._tools
    
    async def run(self, name: str, payload: dict) -> str:
        tool = self.get(name)
        if tool is  None:
            return f"[erro] ferramenta '{name}' não existe"
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
        