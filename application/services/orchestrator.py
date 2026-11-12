from __future__ import annotations

import asyncio, orjson, re, time

from typing import Awaitable, Callable,BinaryIO
from collections.abc import AsyncIterator

from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry
from domain.tools.guard import ToolCtx
from domain.contracts import SessionStore
from domain.entities.message import Completion, ToolCall
from application.services.context_service import ContextManager
from application.services.helpers import _strip, persist_image, normalize_image_uri
from application.guards.output import check_output
from application.services._trace import trace
from application.services._turnlog import log_turno
from application.services._flowlog import flow, curto
from application.prompts import build_system, blocos_tarefa, HONESTIDADE, VISION_STYLE
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.storage.file_store import FileStore

MAX_STEPS = 25    # pedidos encadeados reais chegam a 15+ ações (sessão b8343208: 15 + 1 retry)
_FALHA_TOOL = re.compile(r"\[(erro|timeout|falha)")   # prefixo que as tools usam p/ dizer que falharam
LIMITE_PASSOS = ("Limite de passos do turno atingido: NÃO chame mais ferramentas. Responda AGORA ao usuário "
                 "com o que já foi feito e apurado, e diga o que ficou faltando.")

ConfirmFn = Callable[[str, dict], Awaitable[bool]]

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


_STASH_MIN = 400   # chars: 'body' de texto >= isso vira elisão ⟨conteúdo omitido⟩ no histórico (economia)


class Orchestrator:
    """Application service: cérebro do agente. Depende só de contratos (domain/),
    nunca de infrastructure/. Injeção por lifespan/dependencies."""
    
    def __init__(
        self,
        llm: LLMClient,
        context: ContextManager,
        tools: ToolRegistry,
        device_gateway: DeviceGateway,
        session_store: SessionStore,
        file_store: FileStore,
        acervo=None,
        *,
        confirm: ConfirmFn | None = None,
        audit_log: BinaryIO | None = None
    ) -> None:
        self._llm = llm
        self._context = context
        self._tools = tools
        self._bg: set[asyncio.Task] = set()                 # tarefas de 2º plano
        self._device_gateway = device_gateway
        self._confirm = confirm or deny_by_default
        self._audit_log = audit_log
        self._session_store = session_store
        self._traces: dict[str, list[dict]] = {}
        self._file_store = file_store
        self._acervo = acervo                                  # documentos que o dono mandou (lista curta no system)

    
    async def run_react(self, session_id, user_message, *, image=None, device_id=None, extra_system=None, think=True,
                        modo: str = "chat") -> AsyncIterator[tuple]:
        history = await self._session_store.get(session_id)
        n_hist0 = len(history)                              # o que vier depois disto é o turno atual
        if modo == "tutor":
            # Tutor SEMPRE raciocina. Medido 04/11 (qwen35-27b-abl): com think=False ele responde de cabeça
            # 3/3 — não chama search_docs (inventa a "fonte") nem log; com think=True: search_docs → read_doc
            # → log(abrir) → resposta. O CLI em think "off" só não mostra o raciocínio.
            think = True
        memory_block = ""   # cérebro removido (feat/cerebro) — sem bloco de memória no contexto
        # extra_system (ex.: build_system("voz")) é o system COMPLETO quando vem; senão o do modo (chat|tutor).
        system = extra_system if extra_system else self._system_prompt(modo, user_message)
        if self._acervo is not None:                        # sem isto ele não sabe que o documento existe e responde genérico
            anexos = [d for d in self._acervo.docs() if d["colecao"] not in ("estacio", "web")][-15:]
            if anexos:
                system += ("\n\nDocumentos que o dono te mandou (consulte com search_docs/read_doc quando a pergunta "
                           "tocar nesses assuntos, mesmo sem ele citar o documento): "
                           + "; ".join(f"“{d['titulo']}” (doc={d['id']})" for d in anexos) + ".")
        if device_id:                                       # o modelo não sabia de onde o dono fala → abria no "server"
            system += (f"\n\nO dono está falando com você pelo device '{device_id}'. Pediu pra abrir/mostrar sem "
                       f"dizer onde → use ESTE device.")
        # thinking OFF: desligado pelo TEMPLATE (chat_template_kwargs.enable_thinking=False), via no_think=not think
        # na chamada ao llm.stream lá embaixo. O soft-switch "/no_think" no prompt é IGNORADO pelo abliterado
        # (medido: pensou 3/3) — por isso foi removido. thinking ON: não induz formato; o modelo emite o CoT
        # nativo entre <think>…</think> e o CLI separa por essas tags (_SepThink).
        active = self._tools.for_device(await self._device_gateway.capabilities(device_id))
        user_turn = _user_turn(user_message, image)
        t_turno = time.monotonic()
        flow(session_id, "user", f"{curto(user_message, 300)!r} · device={device_id} · img={'sim' if image else 'não'} "
                                 f"· think={think} · hist={len(history)} msgs · tools={','.join(active.get_all_tool_names())}")
        seen: set[tuple[str, bytes]] = set()
        ids_reais: set[str] = set()
        for _m in history:                                  # semeia ids de turnos ANTERIORES (regra b): um id já
            _c = _m.get("content")                          # presente no histórico é válido. Sem isso o check_output
            if isinstance(_c, str):                         # acusava falso ("id que nenhuma tool produziu neste turno")
                ids_reais.update(re.findall(r"(?:file_id|image_id)=([0-9a-f]{12})", _c))
            elif isinstance(_c, list):
                for _b in _c:
                    if isinstance(_b, dict) and isinstance(_b.get("text"), str):
                        ids_reais.update(re.findall(r"(?:file_id|image_id)=([0-9a-f]{12})", _b["text"]))
        saw_image = False
        bruto_turno: list[str] = []   # TUDO que foi streamado no turno (todos os passos) → log bruto p/ auditar o thinking
        for _step in range(MAX_STEPS):
            if saw_image and VISION_STYLE not in system:
                system = f"{system}\n\n{VISION_STYLE}"
            messages = self._context.build(system, memory_block, _enxuga_autoria(history, manter_ultimo=True), user_turn or {})
            max_tok = self._context.max_saida(messages)        # saída dinâmica: nunca estoura a janela
            usado = self._context.count(messages)
            if _step == 0:                                      # rodapé de contexto: 1x por turno, com o prompt REAL
                yield ("event", {"evento": "contexto",
                                 "usado": usado,
                                 "total": self._context.budget,
                                 "reservado": self._context.reserved,
                                 "model": getattr(self._llm, "model", "")})   # fakes de teste não têm → ""
            flow(session_id, f"llm#{_step + 1}", f"→ prompt {usado} tok ({len(messages)} msgs) · max_saida={max_tok}")
            t_llm = time.monotonic(); t_1o = 0.0
            n_tok = {"think": 0, "reply": 0, "tool": 0}; txt_think = ""
            texto = ""
            frag: dict[int, dict] = {}                          # index -> {"id","name","args"}
            bruto_turno.append(f"\n⟦── chamada {_step + 1} ──⟧\n")   # marca o limite de CADA llm.stream no log bruto
            sep = _CoTSplit(think)                               # separa raciocínio/resposta DESTA chamada (por-chamada = confiável)
            async for kind, val in self._llm.stream(
                messages, tools=active.as_openai_tools(), tool_choice="auto", no_think=not think,
                max_tokens=max_tok
            ):
                if not t_1o:
                    t_1o = time.monotonic()                     # 1º delta (texto OU tool) → latência até o 1º token
                if kind == "text":
                    bruto_turno.append(val)
                    for tg, piece in sep.feed(val):
                        n_tok[tg] += 1
                        if tg == "reply":
                            texto += piece                      # texto = só a RESPOSTA (raciocínio fica fora do guard/save)
                        else:
                            txt_think += piece
                        yield (tg, piece)                       # etiquetado: ('think'|'reply', pedaço)
                else:                                           # ("tool_call_delta", tcd cru)
                    n_tok["tool"] += 1                          # args da tool também são geração (ex.: body do create_file)
                    f = frag.setdefault(val.index, {"id": "", "name": "", "args": ""})
                    if val.id:
                        f["id"] = val.id
                    if val.function and val.function.name:
                        f["name"] += val.function.name
                    if val.function and val.function.arguments:
                        f["args"] += val.function.arguments
                        # args AO VIVO: o cliente mostra a tool sendo montada (ex.: body HTML) em vez de esperar mudo
                        yield ("event", {"evento": "tool_args", "index": val.index, "tool": f["name"],
                                         "delta": val.function.arguments})
            for tg, piece in sep.flush():                        # fecha a chamada (raciocínio que não fechou </think>)
                n_tok[tg] += 1
                if tg == "reply":
                    texto += piece
                else:
                    txt_think += piece
                yield (tg, piece)
            dt = time.monotonic() - t_llm
            n = n_tok["think"] + n_tok["reply"] + n_tok["tool"]
            saida = (f"tool_calls={','.join(f['name'] for _, f in sorted(frag.items()))}" if frag else "texto")
            flow(session_id, f"llm#{_step + 1}", f"← {dt:.1f}s · 1º token {(t_1o - t_llm) if t_1o else 0:.1f}s "
                                                 f"· think={n_tok['think']} reply={n_tok['reply']} tool={n_tok['tool']} pedaços "
                                                 f"({n / dt if dt else 0:.0f}/s) · saída={saida}")
            if txt_think:
                flow(session_id, "think", curto(txt_think, 400))
            if texto:
                flow(session_id, "reply", curto(texto, 400))
            if frag:                                            # tool(s) → executa, resultado REAL volta
                cortadas = [f["name"] for _, f in sorted(frag.items()) if not _args_ok(f["args"])]
                if cortadas:
                    # a chamada da tool veio CORTADA (bateu no teto de saída escrevendo o argumento — ex.: um HTML
                    # enorme no create_file). Antes isto derrubava o turno com JSONDecodeError; agora avisa e salva.
                    flow(session_id, "tool", f"✗ argumentos cortados em {', '.join(cortadas)} "
                                             f"({sum(len(f['args']) for f in frag.values())} chars) — teto de saída {max_tok}")
                    aviso = (f"Não consegui terminar: o conteúdo de {', '.join(cortadas)} passou do limite do que eu gero "
                             f"de uma vez e foi cortado. Peça em partes menores (ex.: um tópico por arquivo).")
                    yield ("reply", aviso)
                    if user_turn:
                        history = history + [user_turn]
                    history = history + [{"role": "assistant", "content": aviso}]
                    await self._session_store.set(session_id, _strip(_enxuga_autoria(history, manter_ultimo=False)))
                    log_turno(session_id, user_message, "".join(bruto_turno), think=think)
                    yield ("event", {"evento": "fim", "finish_reason": "length"})
                    return
                tool_calls = [
                    ToolCall(id=f["id"] or f"call_{i}", name=f["name"], arguments=orjson.loads(f["args"] or "{}"))
                    for i, f in sorted(frag.items())
                ]
                resp = Completion(content=texto or None, tool_calls=tool_calls, finish_reason="tool_calls")
                yield ("event", {"evento": "etapa", "fase": "inicio", "emoji": "🔧", "nome": "executando ferramentas"})
                async for _item in self._handle_tool_calls(
                    session_id, history,
                    user_turn,
                    resp,
                    active,
                    device_id,
                    seen,
                    user_message,
                    ids_reais
                ):
                    if _item[0] == "event":                     # passo (exec/ok/erro) → repassa ao stream
                        yield _item
                    else:                                       # ("result", (history, saw_image, ok, passos))
                        history, saw_image, _ok, _passos = _item[1]
                yield ("event", {"evento": "etapa", "fase": "fim"})
                user_turn = None
                continue
   
            guard = check_output(texto, ids_reais)
            if not guard.ok:
                flow(session_id, "guard", f"✗ reprovado: {curto(guard.reason, 300)} → re-stream")
                # a resposta reprovada JÁ foi streamada pro cliente → avisa pra ele descartar o que mostrou
                yield ("event", {"evento": "guard", "ok": False, "acao": "refazendo", "motivo": guard.reason})
                texto = ""
                bruto_turno.append("\n⟦── guard re-stream ──⟧\n")
                sep = _CoTSplit(think)
                _msgs = messages + [{"role": "system", "content": guard.reason}]
                async for kind, val in self._llm.stream(_msgs, no_think=not think, max_tokens=self._context.max_saida(_msgs)):
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
                    flow(session_id, "guard", "✗ re-stream reprovado de novo → resposta padrão")
                    texto = "Não consegui fazer isso agora."
                    yield ("event", {"evento": "guard", "ok": False, "acao": "padrao", "motivo": "re-stream reprovado de novo"})
                    yield ("reply", texto)                      # sem isso o cliente nunca via a resposta padrão (só ia pro histórico)
                else:
                    flow(session_id, "guard", f"✓ re-stream ok: {curto(texto, 300)}")
            if user_turn:
                history = history + [user_turn]
            # texto já é SÓ a resposta (o _CoTSplit removeu o raciocínio por-chamada) → salva limpo,
            # sem CoT antigo no histórico (não "imita" raciocínio com think off) e economiza contexto.
            reply_salvo = texto.strip()
            history = history + [{"role": "assistant", "content": reply_salvo}]
            await self._session_store.set(session_id, _strip(_enxuga_autoria(history, manter_ultimo=False)))
            log_turno(session_id, user_message, "".join(bruto_turno), think=think)   # turno BRUTO inteiro (todos os passos, com <think>) p/ auditoria
            self._flush_trace(session_id)
            flow(session_id, "fim", f"stop · {time.monotonic() - t_turno:.1f}s · {_step + 1} chamada(s) LLM "
                                    f"· resposta {len(reply_salvo)} chars")
            yield ("event", {"evento": "fim", "finish_reason": "stop"})
            return
        # estourou MAX_STEPS: 1 chamada FINAL sem tools responde com o que já foi apurado, e o turno é salvo
        # (antes só avisava "respondo com o que apurei" sem responder, e o turno — tools inclusas — se perdia)
        flow(session_id, "limite", f"estourou MAX_STEPS={MAX_STEPS} → resposta final sem tools")
        messages = self._context.build(system, memory_block, _enxuga_autoria(history, manter_ultimo=True), user_turn or {})
        messages = messages + [{"role": "system", "content": LIMITE_PASSOS}]
        bruto_turno.append("\n⟦── resposta final (limite de passos) ──⟧\n")
        texto = ""
        sep = _CoTSplit(think)
        async for kind, val in self._llm.stream(messages, no_think=not think, max_tokens=self._context.max_saida(messages)):
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
        if not texto.strip() or not check_output(texto, ids_reais).ok:
            texto = "Atingi o limite de passos e não consegui concluir. Me diga como prefere seguir."
            yield ("reply", texto)
        if user_turn:
            history = history + [user_turn]
        history = history + [{"role": "assistant", "content": texto.strip()}]
        await self._session_store.set(session_id, _strip(_enxuga_autoria(history, manter_ultimo=False)))
        log_turno(session_id, user_message, "".join(bruto_turno), think=think)
        self._flush_trace(session_id)
        flow(session_id, "fim", f"length · {time.monotonic() - t_turno:.1f}s · resposta {len(texto.strip())} chars")
        yield ("event", {"evento": "fim", "finish_reason": "length"})
    
    def _system_prompt(self, modo: str = "chat", pedido: str = "") -> str:
        if modo == "tutor":                                 # sessão de estudo: metodologia + regras de tool + ferramentas
            # + SÓ o bloco da tarefa pedida (cronograma/montagem/exercícios) — foi o que venceu na pesquisa
            return (build_system("tutor", blocos_tarefa(pedido)) + "\n" + HONESTIDADE +
                    "\nFerramentas:\n" + self._tools.describe_all())
        return(
            "Você é o assistente pessoal local do dono. Aja por FERRAMENTAS: toda AÇÃO "
            "(criar/gerar/mostrar/abrir/enviar/capturar) é uma CHAMADA de ferramenta, nunca narração. "
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
    ) ->  AsyncIterator[tuple]:
        passos: list[tuple[str, str]] = []
        # args CHEIOS no histórico do turno (o modelo vê o body real do create_file mais recente); o body
        # grande só é enxugado na visão pro modelo (_enxuga_autoria) e ao salvar. stash_map = só pro log.
        stash_map = {tc.id: self._stash_args(tc.arguments) for tc in msg.tool_calls}
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
                            "arguments": orjson.dumps(tc.arguments).decode()   # cheios; enxuga na visão/ao salvar
                        }
                    }
                    for tc in msg.tool_calls
                ]
            }
        ]
        saw_image = False
        ctx = ToolCtx(fala_do_usuario=user_msg, ids_reais=ids_reais, session_id=session_id, device_id=device_id)
        success = False
        for tc in msg.tool_calls:
            name = tc.name
            payload = tc.arguments
            yield ("event", {"evento": "passo", "id": tc.id, "tool": name,   # cria/acende a linha do checklist
                             "estado": "executando", "porque": _porque(name, payload), "improvisado": True})
            exec_ok = False
            flow(session_id, "tool", f"▶ {name} args={curto(orjson.dumps(stash_map[tc.id]).decode(), 300)}")   # args enxutos (sem body gigante)
            t_tool = time.monotonic()
            if self._is_repeat(name, payload, seen):
                obs = "[loop cortado] repetição da mesma ação detectada."
            else:
                self._remember_call(name, payload, seen)
                obs, exec_ok = await self._execute(name, payload, active, device_id, ctx)
                success = exec_ok
            dt_tool = time.monotonic() - t_tool


            if isinstance(obs, str) and obs.startswith("data:image/"):
                obs = normalize_image_uri(obs)
                img_id = persist_image(obs, session_id, device_id, self._file_store)
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
                # ids REAIS que a tool devolveu (create_file/screenshot põem o file_id no próprio retorno)
                ids_reais.update(re.findall(r"(?:file_id|image_id)=([0-9a-f]{12})", obs))
                # fonte/dado chega INTEIRO (material, memória, registros, localização): resumir a fonte é o que
                # faz o modelo inventar. As outras só são resumidas se forem enormes (summarize decide).
                tool_content = obs if name in _NAO_RESUMIR else await self._context.summarize(obs, foco=f"resultado de {name}")
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
            flow(session_id, "tool", f"{'✓' if exec_ok else '✗'} {name} {dt_tool:.2f}s · obs {len(obs) if isinstance(obs, str) else '?'} chars "
                                     f"→ {curto(trace_txt if exec_ok else obs, 300)}")
            det = _det_curto(trace_txt if exec_ok else obs)          # vira o detalhe (└) do passo
            yield ("event", {"evento": "passo", "id": tc.id, "tool": name,
                             "estado": "ok" if exec_ok else "erro", "detalhe": det})

        yield ("result", (history, saw_image, success, passos))

    def _stash_args(self, arguments: dict) -> dict:
        """A TOOL sempre recebe os args CHEIOS; só a CÓPIA do histórico enxuga o 'body' gigante do
        create_file, pra economizar contexto. No histórico o body vira uma ELISÃO neutra
        (⟨conteúdo omitido…⟩) — SEM file_id, pra o modelo NÃO imitar um marcador no lugar do conteúdo
        (bug observado) e pra ficar legível. O artefato já foi guardado pela própria tool, que devolve o
        file_id no RESULTADO (reabrir/fotografar depois via open_file/screenshot). Devolve só o slim."""
        slim = dict(arguments)
        v = arguments.get("body")
        if isinstance(v, str) and len(v) >= _STASH_MIN:
            slim["body"] = f"⟨conteúdo omitido do histórico · {len(v)} chars⟩"   # neutro, sem file_id
        return slim

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
            result =  await active.run(name, payload, ctx)
        else:
            parsed = tool.input_schema.model_validate(payload)
            result = await self._device_gateway.dispatch(device_id, tool, parsed)
        
        confirm = tool.after(result, ctx)
        if not confirm.ok:
            trace(f"[falha] {confirm.reason}")
            return f"[falha] {confirm.reason}", False
        
        trace(f"[execute tool] {name} ({payload}) device:{device_id}")
        if isinstance(result, str) and _FALHA_TOOL.match(result):   # a tool rodou mas DEVOLVEU erro ([erro…]/[timeout]/[falha])
            return result, False
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

    async def list_sessions(self) -> list[dict]:
        return await self._session_store.list_sessions()

    async def meta_sessao(self, session_id: str) -> dict:
        return await self._session_store.get_meta(session_id)

    async def definir_sessao(self, session_id: str, *, titulo: str | None = None, tags: list[str] | None = None,
                             modo: str | None = None) -> None:
        await self._session_store.set_meta(session_id, titulo=titulo, tags=tags, modo=modo)

    async def historico(self, session_id: str) -> list[dict]:
        return await self._session_store.get(session_id)

    async def narrativa(self, session_id: str) -> list[dict]:
        return await self._session_store.get_narrative(session_id)

    async def salvar_narrativa(self, session_id: str, card: dict) -> None:
        await self._session_store.append_narrative(session_id, card)

    async def contexto_atual(self, session_id: str) -> dict:
        """Contexto que o PRÓXIMO turno vai ocupar (system + memória + histórico) — rodapé ao retomar
        uma sessão e no fim de cada turno (o histórico cresceu)."""
        history = await self._session_store.get(session_id)
        messages = self._context.build(self._system_prompt(), "",
                                       _enxuga_autoria(history, manter_ultimo=True), {})
        return {"usado": self._context.count(messages), "total": self._context.budget,
                "reservado": self._context.reserved, "model": getattr(self._llm, "model", "")}
            
_NAO_RESUMIR = {"search_docs", "read_doc", "get_location", "list_devices", "web_search", "web_fetch"}
_AUTORIA = {"create_file"}    # tools cujo argumento 'body' É o conteúdo autorado (ver _enxuga_autoria)


def _enxuga_autoria(history: list[dict], *, manter_ultimo: bool) -> list[dict]:
    """Cópia do histórico com o 'body' dos create_file trocado pela elisão ⟨conteúdo omitido…⟩ — o mesmo
    tratamento da imagem (inteira dentro do turno, _strip ao salvar). manter_ultimo=True (visão pro modelo):
    o create_file MAIS RECENTE fica inteiro; False (ao salvar): todos enxutos.

    Por quê (medido 03/11, docs/tutor/exp-placeholder): o modelo IMITA o formato da última chamada da mesma
    tool. Se a mais recente tem a elisão no body, ele copia a elisão (50–67% dentro do turno, qualquer
    redação); com a mais recente inteira, escreve conteúdo (1/24). As chamadas continuam visíveis — sumir com
    elas (só a nota do resultado) fez o modelo perder o fio e recriar o mesmo arquivo (sessão 24cc15).
    Custo: no máximo UM body inteiro no contexto (os antigos ficam enxutos; o salvo vem todo enxuto)."""
    ultimo = None
    if manter_ultimo:
        for m in reversed(history):
            achado = [c for c in m.get("tool_calls") or [] if c.get("function", {}).get("name") in _AUTORIA]
            if achado:
                ultimo = achado[-1].get("id")
                break
    out = []
    for m in history:
        calls = m.get("tool_calls")
        if not calls:
            out.append(m)
            continue
        novos = []
        for c in calls:
            f = c.get("function", {})
            if f.get("name") in _AUTORIA and c.get("id") != ultimo:
                try:
                    args = orjson.loads(f.get("arguments") or "{}")
                except orjson.JSONDecodeError:
                    args = None
                body = args.get("body") if isinstance(args, dict) else None
                if isinstance(args, dict) and isinstance(body, str) and len(body) >= _STASH_MIN:
                    args["body"] = f"⟨conteúdo omitido do histórico · {len(body)} chars⟩"
                    c = {**c, "function": {**f, "arguments": orjson.dumps(args).decode()}}
            novos.append(c)
        out.append({**m, "tool_calls": novos})
    return out


def _args_ok(args: str) -> bool:
    """Os argumentos da tool chegaram INTEIROS (JSON objeto válido)? Cortados no teto de saída → False."""
    try:
        return isinstance(orjson.loads(args or "{}"), dict)
    except orjson.JSONDecodeError:
        return False

def card_checklist(passos: list[dict]) -> list[dict]:
    """Eventos 'passo' de um turno → checklist da narrativa (executando abre a linha, ok/erro fecha a MESMA por id).
    Usado pelo chat (chat_router) e pela voz (voice_service) — o replay no CLI fica igual nos dois."""
    linhas: dict[str, dict] = {}
    for p in passos:
        pid = str(p.get("id") or "")
        if p.get("estado") == "executando":
            linhas[pid] = {"desc": p.get("porque") or p.get("tool") or "", "estado": "ok", "det": ""}
        elif pid in linhas:
            linhas[pid].update(estado="ok" if p.get("estado") == "ok" else "err", det=p.get("detalhe", ""))
    return list(linhas.values())

def _porque(name: str, args: dict) -> str:
    """Rótulo da linha do checklist: tool + o arg mais descritivo (ex.: 'calculate · 17*23')."""
    for k in ("title", "expression", "desc", "file_id", "device", "text", "query"):
        v = args.get(k) if isinstance(args, dict) else None
        if isinstance(v, str) and v.strip():
            return f"{name} · {_det_curto(v, 60)}"
    return name

def _det_curto(s: str, n: int = 120) -> str:
    """1ª linha, sem quebra, cortada em n — o detalhe (└) que o checklist mostra sob o passo ok/erro."""
    t = (s or "").strip()
    if not t:
        return ""
    t = t.splitlines()[0]
    return t[:n] + ("…" if len(t) > n else "")

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

