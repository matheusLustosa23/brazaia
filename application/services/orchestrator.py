from __future__ import annotations

import orjson, re

from collections.abc import AsyncIterator
from typing import Awaitable, Callable,BinaryIO

from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry
from domain.tools.guard import ToolCtx, GuardResult
from domain.contracts import SessionStore
from domain.entities.message import Completion
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.helpers import _strip, persist_image
from application.guards.output import check_output
from application.services.tool_router import ToolRouter
from application.services.juiz import Juiz
from application.services._trace import trace
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.vision.image_index import ImageIndex

MAX_STEPS = 15

ConfirmFn = Callable[[str, dict], Awaitable[bool]]

VISION_STYLE = """\
Você está olhando uma IMAGEM real capturada agora.
Grounding (regra absoluta): descreva/leia SÓ o que está de fato na imagem; NÃO invente elementos/textos.
NÃO projete a resposta ESPERADA: leia o que ESTÁ escrito na foto, mesmo que seja diferente do problema que você gerou ou esteja errado. Nunca assuma que o usuário acertou.
Se a foto está borrada/escura/cortada e você NÃO consegue ler os símbolos, diga "não consegui ler, manda uma foto mais nítida" — NÃO invente uma resolução plausível.
Se algo estiver ilegível, DIGA que não conseguiu ler — nunca preencha com suposição.
Ao avaliar (quadro/exercício): CONFIRA cada passo e o resultado circulado; diga o que está CERTO e ERRADO e ONDE.
Se o resultado escrito estiver errado, APONTE — nunca "corrija em silêncio". É por voz: curto, veredito primeiro.
"""

HONESTIDADE = """
# Honestidade (regras inegociáveis — valem para TODAS as ferramentas, inclusive as futuras)
- Só afirme que uma ação foi realizada se o RESULTADO da ferramenta confirmar. Nunca invente um
  resultado nem declare um sucesso que você não verificou.
- Você NUNCA escreve o RESULTADO de uma ferramenta — um "ok", um id, um placeholder como
  "[imagem capturada · image_id=…]", uma descrição de imagem — sem ter CHAMADO a ferramenta
  NESTE turno e recebido a resposta. Se você não chamou, NÃO HÁ resultado: não o simule nem
  o narre. "Vou capturar/abrir/enviar…" só vira verdade DEPOIS que a ferramenta rodou e
  confirmou — antes disso, ou você chama, ou diz que vai fazer e espera.
- Se uma ferramenta falhar, não existir, ou não for a adequada: RELATE a falha ao dono e PARE.
  Não a substitua por outra ferramenta (ex.: echo) para simular que funcionou, e não execute uma
  ação diferente da que foi pedida sem ele pedir.
- Sem a ferramenta certa para o pedido, diga com clareza que não consegue — não improvise um "faz de conta".
- IDs, códigos e identificadores (image_id, session, device...) você NUNCA inventa.
  Um id só vale se você o RECEBEU: (a) retornado por uma ferramenta agora (ex.:
  render_math, capture_image) OU (b) já presente antes no histórico desta conversa.
  Se você precisa de um e não o recebeu de nenhuma dessas fontes: diga que não
  encontrou e PERGUNTE — nunca gere um "parecido".

# Grounding (não alucinar)
- Fale apenas do que você realmente sabe ou observou: resultado de ferramenta, imagem capturada, memória.
  Não invente fatos, caminhos, nomes, números ou infraestrutura que você não viu.
- Se algo estiver ausente, ilegível ou incerto, diga que não sabe — nunca preencha com suposição como certeza.
- Você só descreve/lê uma imagem VISÍVEL neste turno. Sem imagem agora (só o placeholder [imagem capturada · id]), NÃO afirme o que ela mostra — reabra com load_image e ESPERE.
  ✗ "qual a resposta que você viu?" (sem imagem aberta) → "Vi $(x+5)^2$." (INVENTADO)
  ✓ "Não tenho a imagem aberta pra reler — deixa eu reabrir." → chama load_image, ESPERA, só então responde.

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
        image_index: ImageIndex, 
        *,
        confirm: ConfirmFn | None = None,
        audit_log: BinaryIO | None = None,
        router: ToolRouter | None = None,
        juiz: Juiz
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
        self._image_index = image_index
        self._router = router
        self._juiz = juiz
    
    @staticmethod
    def _chamou_certo(msg: Completion, esperada: str) -> bool:
            return bool(msg.tool_calls) and msg.tool_calls[0].name == esperada

    async def _ensure_tool_call(
        self, msg: Completion, 
        tool_esperada: str, 
        messages: list[dict], 
        active: ToolRegistry
    ) -> Completion | None:
        
        
        nudge = {
            "role": "system",
            "content": f"Você ainda precisa chamar '{tool_esperada}' para atender o pedido. Chame-a agora com os argumentos corretos"
        }
        trace(f"[nudge] pedindo {tool_esperada}")
        msg = await self._llm.complete(messages + [nudge], tools=active.as_openai_tools(), tool_choice="auto")
        trace(f"[nudge->] tools={[t.name for t in msg.tool_calls]} content={(msg.content or '')}")
        
        if not self._chamou_certo(msg, tool_esperada):
            trace(f"[force] {tool_esperada}")
            msg = await self._llm.complete(
                messages,
                tools=active.as_openai_tools(),
                tool_choice={"type": "function", "function": {"name": tool_esperada}}
            )
            trace(f"[force->] tools={[t.name for t in msg.tool_calls]} args={[t.arguments for t in msg.tool_calls]}")

        if not self._chamou_certo(msg, tool_esperada):
            trace(f"[ABORT] nem forçado chamou {tool_esperada}")
            return None

        return msg

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
        ids_reais: set[str] = set() 

        trace(f"===== REQUEST: {user_message}")
        plano = await self._router.plan(user_message, active) if self._router else []
        tools_restantes = list(plano)
      
        for _step in range(MAX_STEPS):
            messages = self._context.build(system, memory_block, history, user_turn or {})
            msg = None
            #sem tools pra chamar , retorna a mensagem para o user
            if not tools_restantes:
                trace(f"===== SEM TOOLS PARA CHAMR")
                texto = await self._finalizar_turno(
                    messages=messages,
                    user_turn=user_turn,
                    history=history,
                    ids_reais=ids_reais,
                    session_id=session_id,
                    mensagem_llm=None
                )
                yield texto
                return
            
            resposta_llm = await self._llm.complete(
                messages, tools=active.as_openai_tools(), tool_choice="auto",
            )
            
            tool_requisitada = resposta_llm.tool_calls[0].name if resposta_llm.tool_calls else None
            mensagem_llm = resposta_llm.content or ""
            
            trace(f"[auto]  tools={[{t.name: t.arguments} for t in resposta_llm.tool_calls]} finish={resposta_llm.finish_reason} content={mensagem_llm}")
            
            #chamou uma tool esperada
            if tool_requisitada in tools_restantes:
                msg = resposta_llm
            # OMITIU
            elif tool_requisitada is None:
                #Motivo plausivio , retornamos ao usuario
                trace(f"===== LLM NÃO CHAMOU TOOL")
                if await self._juiz.classifica_omissao(user_message, mensagem_llm, active.describe_for_router()) == "RESPONDER":
                    trace(f"===== MOTIVO DE OMISSAO PLAUSIVEL")
                    texto = await self._finalizar_turno(
                        messages=messages,
                        user_turn=user_turn,
                        history=history,
                        ids_reais=ids_reais,
                        session_id=session_id,
                        mensagem_llm=mensagem_llm
                    )
                    yield texto
                    return
                
                #Aluncinou , forçamos a chamada
                trace(f"===== LLM ALUNCINOU")
                msg = await self._ensure_tool_call(
                    messages=messages,
                    active=active,
                    msg=resposta_llm,
                    tool_esperada=tools_restantes[0],
                )
                if msg is None: yield "Não foi possível executar a chamada"; return
                tool_requisitada = msg.tool_calls[0].name
            # Chamou uma tool fora do plano
            else:
                #se faz sentido , aceitamos , abordamos o plano
                trace(f"===== LLM CHAMOU UMA TOOL FORA DO PLAO")
                autorizado, tools_substituidas = await self._juiz.aceita_divergencia(
                    pedido=user_message, 
                    tool_chamada=tool_requisitada, 
                    args=resposta_llm.tool_calls[0].arguments, 
                    tools=active.describe_for_router(),
                    restante=tools_restantes
                )
                if autorizado:
                    trace(f"===== CHAMADA AUTORIZADA - TOOLS {tools_substituidas} FORAM SUBSTITUIDAS POR {tool_requisitada}")
                    msg = resposta_llm
                    for t in tools_substituidas:
                        tools_restantes.remove(t)
                # caso seja divergencia sem sentido tentamos forças
                else:
                    trace(f"===== LLM ALUNCINOU")
                    msg = await self._ensure_tool_call(
                        messages=messages,
                        active=active,
                        msg=resposta_llm,
                        tool_esperada=tools_restantes[0],
                    )
                    if msg is None: yield "Não foi possível executar a chamada"; return
                    tool_requisitada = msg.tool_calls[0].name
            
            if tool_requisitada in tools_restantes: tools_restantes.remove(tool_requisitada)
                
            history, saw_image = await self._handle_tool_calls(
                session_id, history, user_turn, msg, active, device_id, seen, user_message, ids_reais
            )
            
            if saw_image and VISION_STYLE not in system:
                system = f"{system}\n\n{VISION_STYLE}"
                
            user_turn = None
          
             
            
        yield "[aviso] limite de passos atingido; respondo com o que apurei até aqui."
    
    def _system_prompt(self) -> str:
        return(
            "Você é o assistente pessoal local do dono. Aja por ferramentas quando útil; "
             + HONESTIDADE +
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
        user_msg: str,
        ids_reais: set[str],
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
        ctx = ToolCtx(fala_do_usuario=user_msg, ids_reais=ids_reais, session_id=session_id)
        for tc in msg.tool_calls:
            name = tc.name
            payload = tc.arguments
            
            if self._is_repeat(name, payload, seen):
                obs = "[loop cortado] repetição da mesma ação detectada."
            else:
                self._remember_call(name, payload, seen)
                obs = await self._execute(name, payload, active, device_id, ctx)
                
            if isinstance(obs, str) and obs.startswith("data:image/"):
                img_id = persist_image(obs, session_id, device_id, self._image_index)
                ids_reais.add(img_id)
                origem = (
                    f"foto · camera={payload.get("source", "?")}"
                    if name == "capture_image" else "imagem recarregada"
                )
                tool_content = [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": obs
                        },
                        
                    },
                    {
                        "type": "text", 
                        "text": f"[{origem} · image_id={img_id}]" 
                    },
                ]
                saw_image = True
                trace_txt = f"[{origem} · image_id={img_id}]"
            else:
                ids_reais.update(re.findall(r"image_id=([0-9a-f]{12})", obs)) 
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
        device_id: str | None,
        ctx: ToolCtx
    ) -> str:
        tool = active.get(name)
        if tool is None:
            return f"[erro] ferramenta '{name}' não existe"
        
        if tool.action_class == "destructive" and not await self._confirm(name, payload):
            trace(f"[cancelado] ação destrutiva '{name}' não confirmada pelo usuário.")
            return f"[cancelado] ação destrutiva '{name}' não confirmada pelo usuário."
        
        verify = tool.before(payload, ctx)
        if not verify.ok:
            trace(f"[bloqueado] {verify.reason}" )
            return f"[bloqueado] {verify.reason}" 
        
        if tool.side == "server":
            result =  await active.run(name, payload)
        else:
            parsed = tool.input_schema.model_validate(payload)
            result = await self._device_gateway.dispatch(device_id, tool, parsed)
        
        confirm = tool.after(result, ctx)
        if not confirm.ok:
            trace(f"[falha] {confirm.reason}")
            return f"[falha] {confirm.reason}"
        
        trace(f"[execute tool] {name} ({payload}) device:{device_id}")
        return  result
    
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
    
    async def _finalizar_turno(
        self, 
        messages: list[dict], 
        ids_reais: set[str],
        user_turn: dict | None,
        history: list[dict],
        session_id: str,
        mensagem_llm: str | None
    ) -> str:
        """Resposta final: streama (1 geração), roda o output guard (G2) e auto-corrige 1×."""
        if mensagem_llm is None:
            buf: list[str] = []
            async for kind, tok in self._llm.stream(messages):
                if kind == "text":
                    buf.append(tok)
            mensagem_llm = "".join(buf)
            guard = check_output(mensagem_llm, ids_reais)
            if not guard.ok:
                aviso = {"role": "system", "content": guard.reason}
                buf2: list[str] = []
                async for kind, tok in self._llm.stream(messages + [aviso]):
                    if kind == "text":
                        buf2.append(tok)
                mensagem_llm = "".join(buf2)
                if not check_output(mensagem_llm, ids_reais).ok:
                    mensagem_llm  = "Não consegui fazer isso agora."
        
        if user_turn:
            history = history + [user_turn]
        history = history + [{"role": "assistant", "content": mensagem_llm}]
        await self._session_store.set(session_id, _strip(history))
        self._flush_trace(session_id)
                
        return mensagem_llm
    
    
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

