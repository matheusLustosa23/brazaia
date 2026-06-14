from fastapi import FastAPI
from api.v1.setup import register_exception_handlers, register_routers
from core.config import get_settings
from lifespan import lifespan
from observability.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    # SEM default_response_class / ORJSONResponse — serialização pelo Pydantic
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    register_routers(app)
    app.add_middleware(RequestContextMiddleware)
    return app


app = create_app()