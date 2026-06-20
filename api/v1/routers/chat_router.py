from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.v1.dependencies import get_orchestrator, require_api_key
from api.v1.routing import ExcludeNoneRoute, error_responses
from api.v1.sse import sse_event
from schemas.chat_schema import ChatData, ChatRequest
from schemas.shared import ApiResponse
from application.services.orchestrator import Orchestrator

router = APIRouter(prefix="/chat", tags=["chat"], route_class=ExcludeNoneRoute)


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
    session_id = req.session_id or orch.create_session()
    if not req.stream:
        reply = "".join(
            [
                tok async for tok in orch.run(
                    session_id=session_id,
                    device_id=req.device_id,
                    user_message=req.message,
                )
            ]
        )
        return ApiResponse.ok(ChatData(session_id=session_id, reply=reply))
    async def gen(): 
        parts: list[str] = []
        try:
            yield sse_event({"session_id": session_id}, event="start")
            async for token in orch.run(
                session_id=session_id,
                user_message=req.message,
                device_id=req.device_id
            ):
                if await request.is_disconnected():
                    break
                parts.append(token)
                yield sse_event({"delta": token}, event="token")
            yield sse_event({"done": True, "reply": "".join(parts)}, event="end")
                
        except Exception as exc:
            err = ApiResponse.error(500, str(exc)).model_dump(exclude_none=True)
            yield sse_event(err, event="error")
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        
    )