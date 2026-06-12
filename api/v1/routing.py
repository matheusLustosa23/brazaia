from typing import Any
from fastapi.routing import APIRoute
from schemas.shared import ApiResponse


class ExcludeNoneRoute(APIRoute):
    """Omite campos nulos na resposta (envelope enxuto) sem classe de resposta custom.
    A serialização continua sendo a do Pydantic — NÃO usamos ORJSONResponse."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # FastAPI sempre passa este kwarg explícito (default False), então
        # setdefault não basta — forçamos para omitir nulos sempre.
        kwargs["response_model_exclude_none"] = True
        super().__init__(*args, **kwargs)


def error_responses() -> dict[int | str, dict[str,Any]]:
    return {
        "4XX": {"model": ApiResponse, "description": "Erro de cliente (envelope ApiResponse)"},
        "5XX": {"model": ApiResponse, "description": "Erro interno (envelope ApiResponse)"},
    }