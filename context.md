# iobraza — Contexto do Projeto

## Visão Geral
Assistente pessoal de IA, voz-first, multi-device, local (Qwen3-VL via vLLM).
Arquitetura em camadas (Tower): `api → application → domain ← infrastructure`.

## Features Completadas (merged em main)

| # | Feature | Branch | PR | Status |
|---|---------|--------|----|--------|
| 1 | LLM Client | `feat/llm-client` | #1 | ✅ |
| 2 | Context Manager | `feat/context-manager` | #2 | ✅ |
| 3 | Tools (base) | `feat/tools` | #3 | ✅ |
| 4 | Personal Memory | `feat/personal-memory` | #4 | ✅ |
| 5 | Agent Loop | `feat/agent-loop` | #5 | ✅ |
| 6 | Chat API | `feat/chat-api` | #6 | ✅ |
| 7 | Session | `feat/session` | #7 | ✅ |
| 8 | Companion Actuator | `feat/companion-actuator` | #8 | ✅ |

## Features Pendentes

### Prioridade MÁXIMA (Urgente)
| Feature | Descrição | Esforço | Docs |
|---------|-----------|---------|------|
| **feat-voice-pipeline v2** | Pipeline de voz completo: wake word + ASR + TTS + offline fallback | 1-2 semanas | `features/feat-voice-pipeline/` |

### Prioridade Alta
| Feature | Descrição | Esforço |
|---------|-----------|---------|
| **feat-tools-memory** | ConsultarTool + EsquecerTool + fix relevance score + system prompt | 1-2 dias |
| **feat-agent-loop-tests** | Testes unitários para o agent loop principal | 1 dia |

### Prioridade Média
| Feature | Descrição | Esforço |
|---------|-----------|---------|
| **feat-access-control** | Auth, rate-limiting, ACL por device | 2-3 dias |
| **feat-ops-robustness** | Health checks, graceful shutdown, structured logging | 1-2 dias |

### Prioridade Baixa (Futuras)
| Feature | Descrição | Esforço |
|---------|-----------|---------|
| **feat-research-subagent** | Sub-agente de pesquisa | 1 semana |
| **feat-integrations** | WhatsApp, calendário, web search | 2+ semanas |

## Estado Atual do Código

### Módulos Principais
```
domain/
├── contracts.py          # Protocolos (LLMClient, MemoryStore, DeviceRegistry, etc.)
├── entities/
│   ├── device.py         # Device entity
│   ├── memory_fact.py    # MemoryFact, FactLink
│   └── message.py        # Completion, ToolCall
└── tools/
    └── base.py           # Tool[InputType], ToolRegistry

application/
├── services/
│   ├── orchestrator.py   # Cérebro do agente (loop principal)
│   ├── memory_service.py # MemoryService (recall, upsert, render_compact)
│   ├── context_service.py # ContextManager (janela de contexto)
│   ├── device_service.py # DeviceService (CRUD)
│   └── device_handshake.py # DeviceHandshakeService
└── tools/
    └── lembrar.py        # LembrarTool

infrastructure/
├── llm/
│   └── client.py         # OpenAILLMClient (vLLM)
├── memory/
│   ├── sqlite_store.py   # SqlLiteMemoryStore (FTS5)
│   └── session_store.py  # SqlLiteSessionStore
├── devices/
│   ├── device_registry.py
│   ├── device_connection.py
│   ├── device_rpc.py
│   └── device_gateway.py
└── tools/
    ├── echo.py           # EchoTool (dummy)
    └── notify.py         # NotifyTool (device-side)

core/
├── config.py             # Settings (pydantic-settings)
└── container.py          # AIContainer + DeviceContainer

api/
└── v1/
    ├── routers/
    │   ├── chat.py       # POST /chat, POST /chat/stream
    │   └── device_ws.py  # WS /ws/device/{device_id}
    └── dependencies.py   # get_llm, get_memory, get_orchestrator

companion/
├── runtime.py            # CompanionRuntime
├── main.py               # Agent entrypoint
├── config.py             # CompanionConfig + load_config()
├── audio.py              # capture_chunks() + play()
├── wake.py               # WakeWord
├── voice_session.py      # VoiceSession
└── tools/
    └── notify_handler.py # @runtime.register_tool("notify")
```

### Módulos Novos (feat-voice-pipeline)
```
domain/
├── entities/audio.py     # AudioChunk dataclass
└── voice.py              # STTEngine, TTSEngine, VoiceService protocols

infrastructure/voice/
├── __init__.py           # build_tts() factory
├── asr.py                # FasterWhisperSTT (CPU int8)
├── tts.py                # Kokoro pt-BR (lang_code='p')
└── tts_piper.py          # Piper TTS (fallback)

application/services/
└── voice_service.py      # VoiceServiceImpl (STT→LLM→TTS)

api/v1/routers/
└── voice_router.py       # WS /ws/voice + POST /voice/text

companion/
├── wake.py               # WakeWord (openwakeword)
├── voice_session.py      # VoiceSession (wake→capture→stream)
├── audio.py              # AudioCapture + AudioPlayback
├── connectivity.py       # ConnectivityMonitor
├── conversation_buffer.py # ConversationBuffer
├── mode_router.py        # ModeRouter (online/offline)
└── offline/
    ├── asr_offline.py    # whisper.cpp
    ├── llm_offline.py    # llama.cpp
    └── tts_offline.py    # Piper TTS
```

### Testes
- **Total:** 34 testes passando
- **Cobertura:** domain, application, infrastructure (memory, tools, context)
- **Faltando:** agent loop, device gateway, companion runtime, voice pipeline

### Porta
- API: `127.0.0.1:8000`
- vLLM: `127.0.0.1:8001`

## Decisões Arquiteturais Importantes

1. **Container Pattern** — `AIContainer` + `DeviceContainer` + `VoiceContainer` (frozen dataclasses)
2. **ToolRegistry = source of truth** — sem ToolCatalog separado
3. **DeviceGateway é facade** — DeviceConnectionManager + DeviceRPCManager
4. **Companion é processo separado** — client, não parte do server
5. **orjson everywhere** — serialização no server e companion
6. **asyncio.Future** — request/response via WebSocket
7. **No frameworks** — sem LangChain/Agno, arquitetura hexagonal custom
8. **ASR/TTS na CPU** — VRAM reservada ao LLM (princípio 7/8)
9. **Wake word on-device** — mic fechado até gatilho (privacidade)
10. **Streaming ponta a ponta** — ASR por chunks, TTS por sentença (TTFT baixo)
11. **Fallback offline** — whisper.cpp + llama.cpp + Piper sobrevivem sem internet
12. **Kokoro como TTS primário** — pt-BR nativo (lang_code='p'), 9 vozes

## Stack de Voz (feat-voice-pipeline v2)

| Componente | Online (Server) | Offline (Device) |
|------------|-----------------|------------------|
| ASR | faster-whisper large-v3-turbo CPU int8 | whisper.cpp base Q5_0 |
| TTS | Kokoro 82M lang_code='p' (fallback: Piper) | Piper TTS pt_BR-* |
| LLM | Qwen3-VL-30B (vLLM) | Phi-3-mini Q4 (llama.cpp) |
| VAD | webrtcvad | — |
| Wake word | — | openwakeword |

## Próximo Passo Imediato
Criar branch `feat/voice-pipeline` e executar Slices A→D conforme `implementacao.md`.
