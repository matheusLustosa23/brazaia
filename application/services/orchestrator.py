from __future__ import annotations

import orjson

from collections.abc import AsyncIterator
from typing import Awaitable, Callable,BinaryIO

from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry
from domain.contracts import SessionStore
from domain.entities.message import Completion
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from infrastructure.devices.device_gateway import DeviceGateway

MAX_STEPS = 8

ConfirmFn = Callable[[str, dict], Awaitable[bool]]

VISION_STYLE = """\
Você está olhando uma IMAGEM real capturada agora.
Grounding (regra absoluta): descreva/leia SÓ o que está de fato na imagem; NÃO invente elementos/textos.
Se algo estiver ilegível, DIGA que não conseguiu ler — nunca preencha com suposição.
Ao avaliar (quadro/exercício): CONFIRA cada passo e o resultado circulado; diga o que está CERTO e ERRADO e ONDE.
Se o resultado escrito estiver errado, APONTE — nunca "corrija em silêncio". É por voz: curto, veredito primeiro.
"""

async def _always_true(name: str, payload: dict) -> bool:
    return True

async def deny_by_default(name: str, payload: dict) -> bool:
    """Default seguro: nega destrutiva sem aceite explícito do transporte."""
    return False


class Orchestrator:
    """Application service: cérebro do agente. Depende só de contratos (domain/),
    nunca de infrastructure/. Injeção por lifespan/dependencies."""
    
    def __init__(
        self,
        llm: LLMClient,
        context: ContextManager,
        tools: ToolRegistry,
        memory: MemoryService,
        device_gateway: DeviceGateway,
        session_store: SessionStore,
        *,
        confirm: ConfirmFn | None = None,
        audit_log: BinaryIO | None = None
    ) -> None:
        self._llm = llm
        self._context = context
        self._tools = tools
        self._memory = memory
        self._device_gateway = device_gateway
        self._confirm = confirm or deny_by_default
        self._audit_log = audit_log
        self._session_store = session_store
        self._traces: dict[str, list[dict]] = {}

    async def run(
        self,
        session_id: str,
        user_message: str,
        *,
        image: str | None = None,
        device_id: str | None = None,
        extra_system: str | None = None
    ) -> AsyncIterator[str]:
        history = await self._session_store.get(session_id)
        memory_block = await self._memory.render_compact(user_message)
        system = self._system_prompt()
        if extra_system:
            system = f"{system}\n\n{extra_system}"
        capabilities = await self._device_gateway.capabilities(device_id)
        active = self._tools.for_device(capabilities)
        user_turn: dict | None = _user_turn(user_message, image)
        seen: set[tuple[str, bytes]] = set()
        
        for _step in range(MAX_STEPS):
            messages = self._context.build(system, memory_block, history, user_turn or {})
            msg = await self._llm.complete(messages, tools=active.as_openai_tools())
            
            if not getattr(msg, "tool_calls", None):
                if user_turn:
                    history = history + [user_turn]
                buf: list[str] = []
                async for _, tok in self._llm.stream(messages):
                    buf.append(tok)
                    yield tok
                history = history + [{"role": "assistant", "content": "".join(buf)}]
                await self._session_store.set(session_id, history) 
                self._flush_trace(session_id)
                return
            history, saw_image = await self._handle_tool_calls(
                session_id, history, user_turn, msg, active, device_id, seen
            )
            if saw_image and VISION_STYLE not in system:
                system = f"{system}\n\n{VISION_STYLE}"
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
    ) ->  tuple[list[dict], bool]:
        if user_turn is not None:
            history = history + [user_turn]
        history = history + [
            {
                "role":"assistant",
                "content":msg.content if msg.content is not None else "",
                "tool_calls":[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": orjson.dumps(tc.arguments).decode()
                        }
                    }
                    for tc in msg.tool_calls
                ]
            }
        ]
        saw_image = False
        for tc in msg.tool_calls:
            name = tc.name
            payload = tc.arguments
            
            if self._is_repeat(name, payload, seen):
                obs = "[loop cortado] repetição da mesma ação detectada."
            else:
                self._remember_call(name, payload, seen)
                obs = await self._execute(name, payload, active, device_id)
                
            if isinstance(obs, str) and obs.startswith("data:image/"):
                tool_content = [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": obs
                        }
                    }
                ]
                saw_image = True
                trace_txt = "[imagem capturada]"
            else:
                tool_content =  await self._context.summarize(obs, foco=f"resultado de {name}")
                trace_txt = tool_content
        
        
            history = history + [
                {
                    "role": "tool", 
                    "tool_call_id": tc.id, 
                    "content": tool_content
                }
            ]
            self._trace(session_id, name, payload, obs,  trace_txt)
            
        return (history, saw_image)

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
        
        parsed = tool.input_schema.model_validate(payload)
        return await self._device_gateway.dispatch(device_id, tool, parsed)
    
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
    
    def _flush_trace(self, session_id: str) -> None:
        entries = self._traces.pop(session_id,[])
        if entries and self._audit_log is not None:
            self._audit_log.write(
                orjson.dumps({"session": session_id, "steps": entries}) + b"\n"
            )
    
    async def create_session(self) -> str:
        return await self._session_store.create()
    
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