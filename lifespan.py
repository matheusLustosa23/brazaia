import os, asyncio, logging
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
from infrastructure.tools.capture_image import CaptureImageTool
from infrastructure.tools.load_imagem import LoadImageTool
from infrastructure.tools.display_math import DisplayMathTool
from infrastructure.tools.display_page import DisplayPageTool
from infrastructure.tools.render_math import RenderMathTool
from infrastructure.tools.notify import NotifyTool
from infrastructure.tools.open_image import OpenImageTool
from infrastructure.memory.sqlite_store import SqlLiteMemoryStore
from infrastructure.memory.session_store import SqlLiteSessionStore
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService
from application.services.device_handshake import DeviceHandshakeService
from application.tools.lembrar import LembrarTool
from application.services.tool_router import ToolRouter
from application.services.juiz import Juiz
from domain.tools.base import ToolRegistry
from infrastructure.voice.asr import ASR
from infrastructure.voice.tts import TTS
from infrastructure.vision.sources import VisionRegistry, WebCam
from infrastructure.vision.image_index import ImageIndex

logger = logging.getLogger(__name__)

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
    
    # --- Router ---
    router = ToolRouter(llm)
    
    # --- JUIZ ---
    juiz = Juiz(llm)

    # ── Memory ──
    os.makedirs(os.path.dirname(settings.memory_db_path), exist_ok=True)
    _store = SqlLiteMemoryStore(settings.memory_db_path)
    await _store.init()
    memory = MemoryService(_store)

    # ── Session ──
    os.makedirs(os.path.dirname(settings.session_db_path), exist_ok=True)
    _session_store = SqlLiteSessionStore(settings.session_db_path)
    await _session_store.init()
    
     # -- VISION --
    image_index = ImageIndex()
    vision = VisionRegistry()
    vision.register(WebCam())
    

    # ── Tools ──
    registry = ToolRegistry()
 

    # ── Devices ──
    os.makedirs(os.path.dirname(settings.device_db_path), exist_ok=True)
    device_registry = SqlLiteDeviceRegistry(settings.device_db_path)
    await device_registry.init()

    device_service = DeviceService(device_registry, registry)
    conn_manager = DeviceConnectionManager()
    rpc_manager = DeviceRPCManager(settings.device_ws_timeout)
    device_gateway = DeviceGateway(conn_manager, rpc_manager, device_service)
    device_handshake = DeviceHandshakeService(device_service, device_gateway)
    
    registry.register(LembrarTool(memory))
    registry.register(CaptureImageTool(vision))
    registry.register(LoadImageTool(image_index))
    registry.register(DisplayMathTool(device_gateway))
    registry.register(DisplayPageTool(device_gateway))
    registry.register(RenderMathTool(image_index))
    registry.register(NotifyTool(device_gateway, image_index))
    registry.register(OpenImageTool(device_gateway, image_index))

    # ── Orchestrator ──
    orchestrator = Orchestrator(
        llm=llm,
        context=context,
        tools=registry,
        memory=memory,
        device_gateway=device_gateway,
        session_store=_session_store,
        image_index=image_index,
        router=router,
        juiz=juiz
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
    # --- VOICE ---
    asr = await asyncio.to_thread(
        ASR, settings.voice_stt_model, "cpu", settings.voice_beam_size
    )
    tts = await asyncio.to_thread(TTS, settings.voice_tts_voice)
    
   
    app.state.asr = asr
    app.state.tts = tts
    app.state.image_index = image_index
    app.state.vision = vision
    app.state.container = container

    setup_logging(settings.log_level)
    
    try:
        from infrastructure.render.page import render_page
        await asyncio.to_thread(render_page, r"$x^2$")
        logger.info("katex assets warmed")
    except Exception as e:
        logger.warning("warm do render falhou (segue sem): %s", e) 
        
    yield