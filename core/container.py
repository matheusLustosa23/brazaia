from dataclasses import dataclass

from domain.contracts import LLMClient, DeviceRegistry, SessionStore
from domain.tools.base import ToolRegistry
from application.services.context_service import ContextManager
from application.services.memory_service import MemoryService
from application.services.orchestrator import Orchestrator
from application.services.device_service import DeviceService
from application.services.device_handshake import DeviceHandshakeService
from infrastructure.devices.device_gateway import DeviceGateway


@dataclass(frozen=True)
class AIContainer:
    llm: LLMClient
    context: ContextManager
    tools: ToolRegistry
    memory: MemoryService
    session_store: SessionStore


@dataclass(frozen=True)
class DeviceContainer:
    registry: DeviceRegistry
    service: DeviceService
    gateway: DeviceGateway
    handshake: DeviceHandshakeService


@dataclass(frozen=True)
class Container:
    """Composition Root oficial da aplicação — Substitui app.state flat."""
    ai: AIContainer
    device: DeviceContainer
    orchestrator: Orchestrator