import os, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from core import get_settings
from core.container import Container, AIContainer, DeviceContainer
from observability.logging import setup_logging
from infrastructure.devices.device_registry import SqlLiteDeviceRegistry
from infrastructure.devices.device_connection import DeviceConnectionManager
from infrastructure.devices.device_rpc import DeviceRPCManager
from infrastructure.devices.device_gateway import DeviceGateway
from infrastructure.llm.client import OpenAILLMClient
from infrastructure.llm import tokenizer
from infrastructure.tools.echo import EchoTool
from infrastructure.tools.notify import NotifyTool
from infrastructure.memory.sqlite_store import SqlLiteMemoryStore
from infrastructure.memory.session_store import SqlLiteSessionStore
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService
from application.services.device_handshake import DeviceHandshakeService
from application.tools.lembrar import LembrarTool
from domain.tools.base import ToolRegistry
from infrastructure.voice.asr import ASR
from infrastructure.voice.tts import TTS

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings

    # ── LLM ──
    llm = OpenAILLMClient(settings)
    context = ContextManager(
        budget=settings.max_context_tokens,
        reserved_output=settings.reserved_output_tokens,
        count_tokens=lambda msgs: tokenizer.count_tokens(msgs, settings.model_name),
        llm=llm,
    )

    # ── Memory ──
    os.makedirs(os.path.dirname(settings.memory_db_path), exist_ok=True)
    _store = SqlLiteMemoryStore(settings.memory_db_path)
    await _store.init()
    memory = MemoryService(_store)

    # ── Session ──
    os.makedirs(os.path.dirname(settings.session_db_path), exist_ok=True)
    _session_store = SqlLiteSessionStore(settings.session_db_path)
    await _session_store.init()

    # ── Tools ──
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(LembrarTool(memory))
    registry.register(NotifyTool())

    # ── Devices ──
    os.makedirs(os.path.dirname(settings.device_db_path), exist_ok=True)
    device_registry = SqlLiteDeviceRegistry(settings.device_db_path)
    await device_registry.init()

    device_service = DeviceService(device_registry, registry)
    conn_manager = DeviceConnectionManager()
    rpc_manager = DeviceRPCManager(settings.device_ws_timeout)
    device_gateway = DeviceGateway(conn_manager, rpc_manager, device_service)
    device_handshake = DeviceHandshakeService(device_service, device_gateway)

    # ── Orchestrator ──
    orchestrator = Orchestrator(
        llm=llm,
        context=context,
        tools=registry,
        memory=memory,
        device_gateway=device_gateway,
        session_store=_session_store,
    )

    # ── Sub-Containers ──
    ai_container = AIContainer(
        llm=llm,
        context=context,
        tools=registry,
        memory=memory,
        session_store=_session_store,
    )

    device_container = DeviceContainer(
        registry=device_registry,
        service=device_service,
        gateway=device_gateway,
        handshake=device_handshake,
    )

    # ── Container (Composition Root) ──
    container = Container(
        ai=ai_container,
        device=device_container,
        orchestrator=orchestrator,
    )
    asr = await asyncio.to_thread(
        ASR, settings.voice_stt_model, "cpu", settings.voice_beam_size
    )
    tts = await asyncio.to_thread(TTS, settings.voice_tts_voice)
    app.state.asr = asr
    app.state.tts = tts
    app.state.container = container

    setup_logging(settings.log_level)
    yield