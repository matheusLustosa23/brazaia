from contextlib import asynccontextmanager
from fastapi import FastAPI
from core import get_settings
from observability.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: instancia placeholders de LLMClient/DeviceRouter no app.state.
    Núcleo desacoplado — tudo por injeção. Shutdown: fecha recursos."""
    settings = get_settings()
    app.state.settings = settings
    # placeholders — implementação real em feat-llm-client / feat-companion-actuator
    app.state.llm = None        # -> LLMClient (Slice C deixa o slot)
    app.state.device_router = None  # -> DeviceRouter (Slice C)
    setup_logging(settings.log_level)
    yield
    # shutdown: await app.state.llm.aclose() etc. quando existirem
