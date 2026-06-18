import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core import get_settings
from observability.logging import setup_logging
from infrastructure.devices.device_router import DeviceRouter
from infrastructure.llm.client import OpenAILLMClient
from infrastructure.llm import tokenizer
from infrastructure.tools.echo import EchoTool
from infrastructure.memory.sqlite_store import SqlLiteMemoryStore
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator
from domain.tools.base import ToolRegistry


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
    os.makedirs(os.path.dirname(settings.memory_db_path),exist_ok=True)
    _store = SqlLiteMemoryStore(settings.memory_db_path)
    await _store.init()
    registry = ToolRegistry()
    registry.register(EchoTool())
    app.state.tools = registry
    app.state.device_router = DeviceRouter()
    app.state.memory = MemoryService(_store)
    app.state.orchestrator = Orchestrator(
        llm=app.state.llm,
        context=app.state.context,
        tools=app.state.tools,
        memory=app.state.memory,
        device_router=app.state.device_router,
    )
    setup_logging(settings.log_level)
    yield
    # shutdown: await app.state.llm.aclose() etc. quando existirem
