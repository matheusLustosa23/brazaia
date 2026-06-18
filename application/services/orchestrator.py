from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Awaitable, Callable

from domain.contracts import DeviceRouter, LLMClient
from domain.tools.base import ToolRegistry
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
        self._last_call: tuple | None = None
        
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
                session_id, history, user_turn, msg, active, device_id
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
        session_id,
        history,
        user_turn,
        msg,
        active,
        device_id
    ):
        raise NotImplementedError()
    
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