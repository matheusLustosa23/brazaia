from fastapi import APIRouter, Depends

from api.v1.dependencies import get_orchestrator, require_api_key
from api.v1.routing import ExcludeNoneRoute, error_responses
from schemas.chat_schema import ChatData, ChatRequest
from schemas.shared import ApiResponse
from application.services.orchestrator import Orchestrator

router = APIRouter(prefix="/chat", tags=["chat"], route_class=ExcludeNoneRoute)


@router.post(
    "",
    response_model=ApiResponse[ChatData],
    responses=error_responses(),
    dependencies=[Depends(require_api_key)]
)
async def chat(
    req: ChatRequest,
    orch: Orchestrator = Depends(get_orchestrator)
) -> ApiResponse[ChatData]:
    session_id = req.session_id or orch.create_session()
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