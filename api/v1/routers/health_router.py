from fastapi import APIRouter

from api.v1.routing import ExcludeNoneRoute, error_responses
from schemas.health_schema import HealthData
from schemas.shared import ApiResponse

router = APIRouter(prefix="/health", tags=["health"], route_class=ExcludeNoneRoute)


@router.get("", response_model=ApiResponse[HealthData], responses=error_responses())
async def health() -> ApiResponse[HealthData]:
    """Health estático — sem checar o vLLM (isso vem em feat-ops-robustness)."""
    return ApiResponse.ok(HealthData(status="ok"))