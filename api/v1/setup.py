from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from domain.exceptions.base import AgentError
from schemas.shared import ApiResponse
from api.v1.routers import device_ws, health_router


def register_routers(app: FastAPI) -> None:
    """Inclui os routers da v1 sob /api/v1."""
    app.include_router(health_router.router, prefix="/api/v1")
    app.include_router(device_ws.router, prefix="/api/v1")


def register_exception_handlers(app: FastAPI) -> None:
    """Todo erro sai pelo MESMO envelope ApiResponse. JSONResponse SÓ aqui."""

    @app.exception_handler(AgentError)
    async def _agent_error(_: Request, exc: AgentError) -> JSONResponse:
        body = ApiResponse.error(exc.status, exc.message).model_dump(exclude_none=True)
        return JSONResponse(status_code=exc.status, content=body)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        body = ApiResponse.error(exc.status_code, str(exc.detail)).model_dump(exclude_none=True)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        body = ApiResponse.error(422, "erro de validação").model_dump(exclude_none=True)
        return JSONResponse(status_code=422, content=body)
