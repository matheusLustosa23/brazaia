from __future__ import annotations

import orjson, re

from typing import Awaitable, Callable,BinaryIO
from collections.abc import AsyncIterator

from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry
from domain.tools.guard import ToolCtx
from domain.contracts import SessionStore
from domain.entities.message import Completion, ToolCall
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.helpers import _strip, persist_image, normalize_image_uri
from application.guards.output import check_output
from application.services._trace import trace
from application.services._turnlog import log_turno
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

STUDY_MODE = (
    "MODO ESTUDO — você é um tutor ANCORADO, não um oráculo.\n"
    "Numa tutoria, resposta errada dita com confiança é PIOR que 'não sei' — ensina algo falso "
    "e prejudica o aprendizado do Dono. Sua precisão vem de ANCORAR, não de lembrar.\n"

    "\nANCORE antes de responder:\n"
    "- Dúvida sobre um conteúdo específico (página, slide, enunciado, exercício, caderno)? "
    "Peça pra ver — 'tira uma foto do que te confundiu' → capture_image. Responda sobre o que está "
    "VISÍVEL, apoiado no próprio texto, não de memória.\n"
    "- Sem o material à vista, explique só o que você tem CERTEZA; o resto, mande conferir.\n"

    "\nDERIVÁVEL vs LEMBRADO — trate diferente:\n"
    "- DERIVÁVEL (uma conta, uma demonstração, um passo lógico): MOSTRE o passo a passo — o Dono "
    "confere cada passo e aprende o caminho. Renderize com render_math/display_math; nunca escreva "
    "LaTeX cru no chat.\n"
    "- LEMBRADO (data, valor exato, enunciado de teorema, citação, referência): risco de alucinar. "
    "NÃO crave — marque 'acho que é X, confere no material'.\n"

    "\nNUNCA:\n"
    "- ✗ inventar referência, título, autor, página, nome de teorema ou valor pra 'parecer completo'.\n"
    "- ✗ afirmar seco um fato de memória sobre o qual você não tem certeza.\n"
    "✓ 'não tenho a referência exata — isso está no seu material, confere lá.'\n"
    "✓ 'não tenho certeza desse valor; o jeito de checar é [método].'\n"

    "\nCOMO ensinar (adapte ao pedido):\n"
    "- Dúvida pontual → esclareça CURTO e preciso.\n"
    "- Conceito novo → não entregue mastigado: veja o que ele já sabe, guie até a resposta, "
    "cheque o entendimento no fim.\n"
    "- 'Onde errei?' → aponte o passo EXATO do erro dele; não reescreva tudo do zero.\n"

    "\nESTRUTURA da explicação (padrão didático):\n"
    "- Se o conceito depende de um PRÉ-REQUISITO (freq. relativa usa freq. absoluta), ensine o "
    "pré-requisito ANTES. Decomponha em partes numeradas, cada uma sobre a anterior.\n"
    "- Toda fórmula: renderize e logo abaixo defina cada símbolo ('onde: ...').\n"
    "- Conta: mostre PASSO A PASSO granular (a divisão, depois a multiplicação, depois o resultado) — "
    "nunca pule pro final; o Dono confere cada passo.\n"
    "- Dê um EXEMPLO concreto e, havendo casos, uma TABELA comparativa (display_page).\n"
    "- Ofereça uma VERIFICAÇÃO que o Dono faça sozinho (ex.: a soma das freq. relativas dá 100%).\n"
    "- Feche com um resumo curto.\n"
    "- Se o material tiver falha/lacuna, aponte COM NUANCE: o que está certo, o que está incompleto, "
    "e como ficaria melhor. Não confunda 'pressupõe pré-requisito' com 'errado'.\n"

    "\nFERRAMENTAS no estudo:\n"
    "- capture_image → ler a página/enunciado/caderno do Dono.\n"
    "- render_math / display_math → mostrar a fórmula ou a derivação na tela.\n"
    "- display_page → montar uma tabela/resumo comparativo quando ajudar.\n"
    "- lembrar → registrar o ponto fraco e o que já foi explicado, pra revisar depois "
    "('semana passada você travou em integração por partes').\n"

    "\nRegra-mãe: na dúvida entre PARECER sábio e SER fiel, seja fiel. O aprendizado do Dono depende disso."
)


async def deny_by_default(name: str, payload: dict) -> bool:
    """Default seguro: nega destrutiva sem aceite explícito do transporte."""
    return False


_FIM_COT = "</think>"

def _tail_parcial(s: str, tag: str) -> int:
    """Maior sufixo de s que é prefixo de tag (a tag pode chegar partida entre chunks do stream)."""
    for k in range(min(len(tag) - 1, len(s)), 0, -1):
        if s.endswith(tag[:k]):
            return k
    return 0


class _CoTSplit:
    """Separa raciocínio/resposta de UMA chamada ao LLM. Com enable_thinking a abertura <think> fica
    NO PROMPT, então o stream chega 'raciocínio </think> resposta' (sem abertura). Começa em 'think'
    (se esperado) e vira 'reply' no 1º </think>. Separar POR CHAMADA é o único jeito confiável: no
    texto concatenado do turno os limites somem (medido: resposta pode aparecer no meio)."""
    def __init__(self, think_esperado: bool) -> None:
        self.modo = "think" if think_esperado else "reply"
        self.pend = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        s = self.pend + chunk
        self.pend = ""
        if self.modo == "reply":
            if s:
                out.append(("reply", s))
            return out
        j = s.find(_FIM_COT)
        if j == -1:                                   # ainda em raciocínio; segura tag partida no fim
            k = _tail_parcial(s, _FIM_COT)
            if k:
                self.pend = s[-k:]
                s = s[:-k]
            if s:
                out.append(("think", s))
            return out
        if j:
            out.append(("think", s[:j]))
        resto = s[j + len(_FIM_COT):]
        self.modo = "reply"
        if resto:
            out.append(("reply", resto))
        return out

    def flush(self) -> list[tuple[str, str]]:
        """Fim da chamada: devolve o que sobrou pendente (tag partida que nunca fechou)."""
        if not self.pend:
            return []
        p, self.pend = self.pend, ""
        return [(self.modo, p)]


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
        self._image_index = image_index

    
    async def run_react(self, session_id, user_message, *, image=None, device_id=None, extra_system=None, think=True) -> AsyncIterator[tuple[str, str]]:
        history = await self._session_store.get(session_id)
        memory_block = await self._memory.render_compact(user_message)
        # extra_system (ex.: build_system("voz")) é o system COMPLETO quando vem; senão usa o genérico.
        system = extra_system if extra_system else self._system_prompt()
        # thinking OFF: desligado pelo TEMPLATE (chat_template_kwargs.enable_thinking=False), via no_think=not think
        # na chamada ao llm.stream lá embaixo. O soft-switch "/no_think" no prompt é IGNORADO pelo abliterado
        # (medido: pensou 3/3) — por isso foi removido. thinking ON: não induz formato; o modelo emite o CoT
        # nativo entre <think>…</think> e o CLI separa por essas tags (_SepThink).
        active = self._tools.for_device(await self._device_gateway.capabilities(device_id))
        user_turn = _user_turn(user_message, image)
        seen: set[tuple[str, bytes]] = set()
        ids_reais: set[str] = set()
        for _m in history:                                  # semeia ids de turnos ANTERIORES (regra b): um id já
            _c = _m.get("content")                          # presente no histórico é válido. Sem isso o check_output
            if isinstance(_c, str):                         # acusava falso ("id que nenhuma tool produziu neste turno")
                ids_reais.update(re.findall(r"image_id=([0-9a-f]{12})", _c))
            elif isinstance(_c, list):
                for _b in _c:
                    if isinstance(_b, dict) and isinstance(_b.get("text"), str):
                        ids_reais.update(re.findall(r"image_id=([0-9a-f]{12})", _b["text"]))
        saw_image = False
        bruto_turno: list[str] = []   # TUDO que foi streamado no turno (todos os passos) → log bruto p/ auditar o thinking
        for _step in range(MAX_STEPS):
            if saw_image and VISION_STYLE not in system:
                system = f"{system}\n\n{VISION_STYLE}"
            messages = self._context.build(system, memory_block, history, user_turn or {})
            texto = ""
            frag: dict[int, dict] = {}                          # index -> {"id","name","args"}
            bruto_turno.append(f"\n⟦── chamada {_step + 1} ──⟧\n")   # marca o limite de CADA llm.stream no log bruto
            sep = _CoTSplit(think)                               # separa raciocínio/resposta DESTA chamada (por-chamada = confiável)
            async for kind, val in self._llm.stream(
                messages, tools=active.as_openai_tools(), tool_choice="auto", no_think=not think
            ):
                if kind == "text":
                    bruto_turno.append(val)
                    for tg, piece in sep.feed(val):
                        if tg == "reply":
                            texto += piece                      # texto = só a RESPOSTA (raciocínio fica fora do guard/save)
                        yield (tg, piece)                       # etiquetado: ('think'|'reply', pedaço)
                else:                                           # ("tool_call_delta", tcd cru)
                    f = frag.setdefault(val.index, {"id": "", "name": "", "args": ""})
                    if val.id:
                        f["id"] = val.id
                    if val.function and val.function.name:
                        f["name"] += val.function.name
                    if val.function and val.function.arguments:
                        f["args"] += val.function.arguments
            for tg, piece in sep.flush():                        # fecha a chamada (raciocínio que não fechou </think>)
                if tg == "reply":
                    texto += piece
                yield (tg, piece)
            if frag:                                            # tool(s) → executa, resultado REAL volta
                tool_calls = [
                    ToolCall(id=f["id"] or f"call_{i}", name=f["name"], arguments=orjson.loads(f["args"] or "{}"))
                    for i, f in sorted(frag.items())
                ]
                resp = Completion(content=texto or None, tool_calls=tool_calls, finish_reason="tool_calls")
                history, saw_image, _ok, _passos = await self._handle_tool_calls(
                    session_id, history, 
                    user_turn, 
                    resp, 
                    active, 
                    device_id, 
                    seen, 
                    user_message, 
                    ids_reais
                )
                user_turn = None
                continue
   
            guard = check_output(texto, ids_reais)
            if not guard.ok:
                texto = ""
                bruto_turno.append("\n⟦── guard re-stream ──⟧\n")
                sep = _CoTSplit(think)
                async for kind, val in self._llm.stream(messages + [{"role": "system", "content": guard.reason}], no_think=not think):
                    if kind == "text":
                        bruto_turno.append(val)
                        for tg, piece in sep.feed(val):
                            if tg == "reply":
                                texto += piece
                            yield (tg, piece)
                for tg, piece in sep.flush():
                    if tg == "reply":
                        texto += piece
                    yield (tg, piece)
                if not check_output(texto, ids_reais).ok:
                    texto = "Não consegui fazer isso agora."
            if user_turn:
                history = history + [user_turn]
            # texto já é SÓ a resposta (o _CoTSplit removeu o raciocínio por-chamada) → salva limpo,
            # sem CoT antigo no histórico (não "imita" raciocínio com think off) e economiza contexto.
            reply_salvo = texto.strip()
            history = history + [{"role": "assistant", "content": reply_salvo}]
            await self._session_store.set(session_id, _strip(history))
            log_turno(session_id, user_message, "".join(bruto_turno), think=think)   # turno BRUTO inteiro (todos os passos, com <think>) p/ auditoria
            self._flush_trace(session_id)
            return
        yield ("reply", "[aviso] limite de passos atingido; respondo com o que apurei até aqui.")
    
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
    ) ->  tuple[list[dict], bool, bool, list[tuple]]:
        passos: list[tuple[str, str]] = []
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
        success = False
        for tc in msg.tool_calls:
            name = tc.name
            payload = tc.arguments
            
            if self._is_repeat(name, payload, seen):
                obs = "[loop cortado] repetição da mesma ação detectada."
            else:
                self._remember_call(name, payload, seen)
                obs, exec_ok = await self._execute(name, payload, active, device_id, ctx)
                success = exec_ok
                
                
            if isinstance(obs, str) and obs.startswith("data:image/"):
                obs = normalize_image_uri(obs)
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
        
            passos.append((tc.name, trace_txt))
        
            history = history + [
                {
                    "role": "tool", 
                    "tool_call_id": tc.id, 
                    "content": tool_content
                }
            ]
            self._trace(session_id, name, payload, obs,  trace_txt)
            
            
        return (history, saw_image, success, passos)

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
    ) -> tuple[str, bool]:
        tool = active.get(name)
        if tool is None:
            return f"[erro] ferramenta '{name}' não existe", False
        
        if tool.action_class == "destructive" and not await self._confirm(name, payload):
            trace(f"[cancelado] ação destrutiva '{name}' não confirmada pelo usuário.")
            return f"[cancelado] ação destrutiva '{name}' não confirmada pelo usuário.", False
        
        verify = tool.before(payload, ctx)
        if not verify.ok:
            trace(f"[bloqueado] {verify.reason}" )
            return f"[bloqueado] {verify.reason}", False
        
        if tool.side == "server":
            result =  await active.run(name, payload)
        else:
            parsed = tool.input_schema.model_validate(payload)
            result = await self._device_gateway.dispatch(device_id, tool, parsed)
        
        confirm = tool.after(result, ctx)
        if not confirm.ok:
            trace(f"[falha] {confirm.reason}")
            return f"[falha] {confirm.reason}", False
        
        trace(f"[execute tool] {name} ({payload}) device:{device_id}")
        return  result, True
    
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
            {"type": "image_url", "image_url": {"url": normalize_image_uri(image)}}
        ]
    }

