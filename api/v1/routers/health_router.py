from fastapi import APIRouter, Depends

from api.v1.routing import ExcludeNoneRoute, error_responses
from api.v1.dependencies import get_llm
from domain.contracts import LLMClient
from schemas.health_schema import HealthData
from schemas.shared import ApiResponse

router = APIRouter(prefix="/health", tags=["health"], route_class=ExcludeNoneRoute)


@router.get("", response_model=ApiResponse[HealthData], responses=error_responses())
async def health(llm: LLMClient = Depends(get_llm)) -> ApiResponse[HealthData]:

    h = await llm.health()
    status = "ok" if h["vllm"] == "up" else "degraded"
    return ApiResponse.ok(HealthData(status=status,vllm=h["vllm"],model=h["model"]))