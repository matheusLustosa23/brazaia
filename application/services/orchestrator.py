from __future__ import annotations

import orjson

from collections.abc import AsyncIterator
from typing import Awaitable, Callable

from domain.contracts import DeviceRouter, LLMClient
from domain.tools.base import ToolRegistry
from domain.entities.message import ToolCall, Completion
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService

MAX_STEPS = 8

ConfirmFn = Callable[[str, dict], Awaitable[bool]]

async def _always_true(name: str, payload: dict) -> bool:
    return True


class Orchestrator:
    """Application service: cérebro do agente. Depende só de contratos (domain/),
    nunca de infrastructure/. Injeção por lifespan/dependencies."""
    
    def __init__(
        self,
        llm: LLMClient,
        context: ContextManager,
        tools: ToolRegistry,
        memory: MemoryService,
        device_router: DeviceRouter,
        *,
        confirm: ConfirmFn | None = None,
        audit_log=None
    ) -> None:
        self._llm = llm
        self._context = context
        self._tools = tools
        self._memory = memory
        self._device_router = device_router
        self._confirm = confirm or _always_true
        self._audit_log = audit_log
        self._sessions: dict[str, list[dict]] = {}
        self._traces: dict[str, list[dict]] = {}

        
    async def run(
        self,
        session_id: str,
        user_message: str,
        *,
        image: str | None = None,
        device_id: str | None = None
    ) -> AsyncIterator[str]:
        history = self._sessions.get(session_id,[])
        memory_block = await self._memory.render_compact(user_message)
        system = self._system_prompt()
        capabilities = self._device_router.capabilities(device_id)
        active = self._tools.for_device(capabilities)
        user_turn: dict | None = _user_turn(user_message, image)
        seen: set[tuple[str, bytes]] = set()
        
        for _step in range(MAX_STEPS):
            messages = self._context.build(system, memory_block, history, user_turn or {})
            msg = await self._llm.complete(messages, tools=active.as_openai_tools())
            
            if not getattr(msg, "tool_calls", None):
                text = msg.content or ""
                if user_turn:
                    history = history + [user_turn]
                history = history + [{"role": "assistant", "content": text}]
                self._sessions[session_id] = history
                yield text
                return
            history = await self._handle_tool_calls(
                session_id, history, user_turn, msg, active, device_id, seen
            )
            user_turn = None
            
        yield "[aviso] limite de passos atingido; respondo com o que apurei até aqui."
       
    
    def _system_prompt(self) -> str:
        return(
             "Você é o assistente pessoal local do dono. Aja por ferramentas quando útil; "
            "responda em português, direto.\nFerramentas:\n" + self._tools.describe_all()
        )
    
    async def _handle_tool_calls(
        self,
        session_id: str,
        history: list[dict],
        user_turn: dict | None,
        msg: Completion,
        active: ToolRegistry,
        device_id: str | None,
        seen: set[tuple[str, bytes]],
    ) -> list[dict]:
        if user_turn is not None:
            history = history + [user_turn]
        
        history = history + [
            {
                "role":"assistant",
                "content":msg.content,
                "tool_calls":[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
            }
        ]
        
        for tc in msg.tool_calls:
            name = tc.name
            payload = tc.arguments
            
            if self._is_repeat(name, payload, seen):
                obs = "[loop cortado] repetição da mesma ação detectada."
            else:
                self._remember_call(name, payload, seen)
                obs = await self._execute(name, payload, active, device_id)
            
            compact = await self._context.summarize(obs, foco=f"resultado de {name}")
            history = history + [
                {
                    "role": "tool", 
                    "tool_call_id": tc.id, 
                    "content": compact
                }
            ]
            self._trace(session_id, name, payload, obs, compact)
            
        return history

    def _is_repeat(self, name: str, payload: dict, seen: set[tuple[str, bytes]]) -> bool:
        return (name, orjson.dumps(payload, option=orjson.OPT_SORT_KEYS),) in seen
    
    def _remember_call(self, name: str, payload: dict, seen: set[tuple[str, bytes]]) -> None:
        seen.add((name, orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)))
    
    async def _execute(
        self,
        name: str,
        payload: dict,
        active: ToolRegistry,
        device_id: str | None
    ) -> str:
        tool = active.get(name)
        if tool is None:
            return f"[erro] ferramenta '{name}' não existe"
        
        if tool.action_class == "destructive" and not await self._confirm(name, payload):
            return f"[cancelado] ação destrutiva '{name}' não confirmada pelo usuário."
        
        if tool.side == "server":
            return await active.run(name, payload)
        return await self._device_router.dispatch(device_id, {"name": name, "arguments": payload})
    
    def _trace(
        self,
        session_id: str,
        name: str,
        payload: dict,
        raw_obs: str,
        compact: str
    ) -> None:
        self._traces.setdefault(session_id, []).append({
            "tool": name, "input": payload,
            "obs_raw_len": len(raw_obs), "obs_compact": compact,
        })
    
        
    
def _user_turn(text: str, image: str  | None) -> dict:
    if not image:
        return {"role":"user","content": text}
    return {
        "role":"user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image}}
        ]
    }