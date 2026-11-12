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
from infrastructure.tools.see_file import SeeFileTool
from infrastructure.tools.create_file import CreateFileTool
from infrastructure.tools.screenshot import ScreenshotTool
from infrastructure.tools.notify import NotifyTool
from infrastructure.tools.open_file import OpenFileTool
from infrastructure.tools.calculate import CalculateTool
from infrastructure.tools.list_devices import ListDevicesTool
from infrastructure.tools.get_location import GetLocationTool
from infrastructure.tools.search_docs import SearchDocsTool
from infrastructure.tools.read_doc import ReadDocTool
from infrastructure.tools.web import WebFetchTool, WebSearchTool
from infrastructure.tools.spotify import SpotifyTool
from infrastructure.spotify.cliente import SpotifyCliente
from infrastructure.acervo.acervo import Acervo
from infrastructure.memory.session_store import SqlLiteSessionStore
from application.services.context_service import ContextManager
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService
from application.services.device_handshake import DeviceHandshakeService
from application.tools.salvar import SalvarTool       # EXPERIMENTO cérebro: tool de salvar (texto livre)
from domain.tools.base import ToolRegistry
from infrastructure.voice.asr import make_asr
from infrastructure.voice.vad import make_vad
from infrastructure.voice.tts import make_tts
from infrastructure.vision.sources import VisionRegistry, WebCam
from infrastructure.storage.file_store import FileStore

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
        count_tokens=lambda msgs: tokenizer.count_tokens(msgs),   # usa tokenizer_path (alias do vLLM não carrega)
        llm=llm,
    )
    
    # ── Session ──
    os.makedirs(os.path.dirname(settings.session_db_path), exist_ok=True)
    _session_store = SqlLiteSessionStore(settings.session_db_path)
    await _session_store.init()
    
     # -- VISION / STORAGE --
    store = FileStore()                       # armazém unificado de artefatos (imagem/html/…) por file_id
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
    
    registry.register(SalvarTool())                 # EXPERIMENTO cérebro
    registry.register(CaptureImageTool(vision))
    registry.register(SeeFileTool(store))
    registry.register(CreateFileTool(store))
    registry.register(ScreenshotTool(store))
    registry.register(NotifyTool(device_gateway, store))
    registry.register(OpenFileTool(device_gateway, store))
    registry.register(CalculateTool())
    registry.register(ListDevicesTool(device_gateway))
    registry.register(GetLocationTool(device_gateway))
    acervo = Acervo(settings.acervo_dir, settings.acervo_db_path)   # material das disciplinas e documentos
    app.state.acervo = acervo                                        # rota /acervo (enviar pelo CLI/celular/painel)
    registry.register(SearchDocsTool(acervo))
    registry.register(ReadDocTool(acervo))
    registry.register(SpotifyTool(SpotifyCliente(settings.spotify_client_id,      # música (Spotify Connect, pela API)
                                                 settings.spotify_client_secret.get_secret_value(),
                                                 settings.spotify_token_path)))
    registry.register(WebSearchTool(settings.searxng_url))     # busca na web (SearXNG próprio)
    registry.register(WebFetchTool(acervo, settings.web_user_agent))   # lê a página e guarda no acervo (coleção web)

    # ── Orchestrator ──
    orchestrator = Orchestrator(
        llm=llm,
        context=context,
        tools=registry,
        device_gateway=device_gateway,
        session_store=_session_store,
        file_store=store,
        acervo=acervo,
    )

    # ── Sub-Containers ──
    ai_container = AIContainer(
        llm=llm,
        context=context,
        tools=registry,
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
    # --- VOICE (opcional: se a dep de um engine faltar, desabilita sem derrubar a API) ---
    if not settings.voice_piper_model:
        for p in ("models/pt_BR-faber-medium.onnx", "pt_BR-faber-medium.onnx"):
            if os.path.exists(p):
                settings.voice_piper_model = p
                break
    try:
        asr = await asyncio.to_thread(make_asr, settings)
        vad = await asyncio.to_thread(make_vad, settings)
        tts = await asyncio.to_thread(make_tts, settings, settings.voice_tts_sr)
    except Exception as e:
        asr = vad = tts = None
        logger.warning("voz desabilitada: %s", e)

    app.state.asr = asr
    app.state.vad = vad
    app.state.tts = tts
    app.state.file_store = store
    app.state.vision = vision
    app.state.container = container

    setup_logging(settings.log_level)
    
    try:
        from infrastructure.render.render import render
        await asyncio.to_thread(render, "<p>$$x^2$$</p>")
        logger.info("katex assets warmed")
    except Exception as e:
        logger.warning("warm do render falhou (segue sem): %s", e) 
        
    yield