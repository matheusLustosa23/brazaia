import orjson, traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.v1.dependencies import get_orchestrator, require_api_key
from api.v1.routing import ExcludeNoneRoute, error_responses
from api.v1.sse import sse_event
from application.services._flowlog import flow, curto
from schemas.chat_schema import ChatData, ChatRequest
from schemas.shared import ApiResponse
from application.services.orchestrator import Orchestrator

router = APIRouter(prefix="/chat", tags=["chat"], route_class=ExcludeNoneRoute)


@router.get("/sessions", dependencies=[Depends(require_api_key)])
async def sessions(orch: Orchestrator = Depends(get_orchestrator)):
    """Sessões COM conversa, da mais recente p/ a mais antiga: id, preview (1ª fala), turnos, created_at/updated_at.
    (Vazias ficam de fora: toda requisição sem session_id cria uma, mesmo se o turno falhar.)"""
    return {"sessions": [s for s in await orch.list_sessions() if s["turnos"] > 0]}


@router.get("/sessions/{session_id}", dependencies=[Depends(require_api_key)])
async def sessao(session_id: str, orch: Orchestrator = Depends(get_orchestrator)):
    """Uma sessão p/ retomar: history (o que o LLM vê) + narrative (o que a TELA mostrou, por turno) + contexto."""
    return {"history": await orch.historico(session_id),
            "narrative": await orch.narrativa(session_id),
            "contexto": await orch.contexto_atual(session_id)}


def _card_checklist(passos: list[dict]) -> list[dict]:
    """Eventos 'passo' do turno → checklist da narrativa (executando abre a linha, ok/erro fecha a MESMA por id)."""
    linhas: dict[str, dict] = {}
    for p in passos:
        if p.get("estado") == "executando":
            linhas[p.get("id")] = {"desc": p.get("porque") or p.get("tool") or "", "estado": "ok", "det": ""}
        elif p.get("id") in linhas:
            linhas[p["id"]].update(estado="ok" if p.get("estado") == "ok" else "err", det=p.get("detalhe", ""))
    return list(linhas.values())


@router.post(
    "",
    responses=error_responses(),
    dependencies=[Depends(require_api_key)]
)
async def chat(
    req: ChatRequest,
    request: Request,
    orch: Orchestrator = Depends(get_orchestrator)
):
    session_id = req.session_id or await orch.create_session()
    if not req.stream:
        reply = "".join(
            [
                text async for (kind, text) in orch.run_react(
                    session_id=session_id,
                    device_id=req.device_id,
                    user_message=req.message,
                    image=req.image,
                    think=req.think,              # think=False → enable_thinking=False (explícito, confiável)
                ) if kind == "reply"              # non-stream devolve só a RESPOSTA (raciocínio descartado)
            ]
        )
        return ApiResponse.ok(ChatData(session_id=session_id, reply=reply))
    async def gen():
        parts: list[str] = []
        passos: list[dict] = []                   # eventos 'passo' do turno → checklist da narrativa
        finish: str | None = None
        try:
            yield sse_event({"session_id": session_id}, event="start")
            async for kind, text in orch.run_react(
                session_id=session_id,
                user_message=req.message,
                device_id=req.device_id,
                image=req.image,
                think=req.think,                  # think=False → enable_thinking=False (explícito, confiável)
            ):
                if await request.is_disconnected():
                    flow(session_id, "cliente", "✗ desconectou no meio do stream → turno interrompido")
                    break
                if kind == "event":               # evento estruturado (etapa/passo/contexto/fim) → SSE próprio
                    if text.get("evento") != "tool_args":     # 1 por delta → inundaria o log (o resumo sai na linha llm#N)
                        flow(session_id, "sse", f"{text.get('evento', 'evento')} {curto(orjson.dumps(text).decode(), 300)}")
                    ev = text.get("evento")
                    if ev == "passo":
                        passos.append(text)
                    elif ev == "fim":
                        finish = text.get("finish_reason")
                    elif ev == "guard":
                        parts.clear()                 # o que foi reprovado não é a resposta (nem no 'end' nem na narrativa)
                    yield sse_event(text, event=text.get("evento", "evento"))
                    continue
                if kind == "think":               # raciocínio: marcado com think=True (o CLI mostra na caixa)
                    yield sse_event({"delta": text, "think": True}, event="token")
                else:                             # resposta: delta normal
                    parts.append(text)
                    yield sse_event({"delta": text}, event="token")
            if finish:                            # turno COMPLETO → narrativa (o que a tela mostrou) p/ replay fiel
                await orch.salvar_narrativa(session_id, {
                    "user": req.message, "image": bool(req.image), "checklist": _card_checklist(passos),
                    "reply": "".join(parts), "finish_reason": finish,
                })
                ctx = await orch.contexto_atual(session_id)   # rodapé reflete o histórico que acabou de crescer
                yield sse_event({"evento": "contexto", **ctx}, event="contexto")
            yield sse_event({"done": True, "reply": "".join(parts)}, event="end")

        except Exception as exc:
            flow(session_id, "erro", f"{type(exc).__name__}: {curto(exc, 500)} · trace: {curto(traceback.format_exc(), 1500)}")
            err = ApiResponse.error(500, str(exc)).model_dump(exclude_none=True)
            yield sse_event(err, event="error")
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        
    )