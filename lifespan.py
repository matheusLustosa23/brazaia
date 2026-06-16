from contextlib import asynccontextmanager
from fastapi import FastAPI
from core import get_settings
from observability.logging import setup_logging
from infrastructure.devices.device_router import DeviceRouter
from infrastructure.llm.client import OpenAILLMClient
from infrastructure.llm import tokenizer
from application.services.context_service import ContextManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: instancia placeholders de LLMClient/DeviceRouter no app.state.
    Núcleo desacoplado — tudo por injeção. Shutdown: fecha recursos."""
    settings = get_settings()
    app.state.settings = settings
    # placeholders — implementação real em feat-llm-client / feat-companion-actuator
    app.state.llm = OpenAILLMClient(settings)                      # -> LLMClient (feat-llm-client)
    app.state.context = ContextManager(
        budget=settings.max_context_tokens,
        reserved_output=settings.reserved_output_tokens,
        count_tokens=lambda msgs: tokenizer.count_tokens(msgs, settings.model_name),
        llm=app.state.llm
    )
    app.state.device_router = DeviceRouter()
    setup_logging(settings.log_level)
    yield
    # shutdown: await app.state.llm.aclose() etc. quando existirem
