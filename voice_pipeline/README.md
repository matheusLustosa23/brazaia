# voice_pipeline — pipeline de voz local (primeira entrega)

Conversa por voz **100% local** com um agente conversacional: captura → VAD → STT → vLLM → TTS →
reprodução com **barge-in**, e **transcrição ao vivo** (você e o agente) no terminal. Conecta-se a um
vLLM já rodando (API OpenAI); **não** hospeda o LLM.

## Arquitetura (módulos trocáveis)

```
mic ─▶ capture ─▶ [buffer] ─▶ vad ─▶ stt (streaming + LocalAgreement-2) ─▶ pipeline
                                                                             │ texto final
                                                                             ▼
                                              transcript ◀── pipeline ──▶ llm (vLLM, streaming)
                                                                             │ deltas
                                                                             ▼
                                              player ◀── tts (por frase) ◀── pipeline
                                                 ▲                              │
                                                 └──────── barge-in ───────────┘
```

| módulo | papel |
|---|---|
| `config.py` | tudo num lugar: modelos, endpoint vLLM, dispositivos, botões de latência |
| `capture.py` | microfone (sounddevice) + `AudioBuffer` thread-safe |
| `vad.py` | detecção de voz por energia + endpoint por silêncio **com reforço semântico** |
| `stt.py` | `Transcriber` (faster-whisper \| Parakeet) + `Stabilizer` (autocorreção) |
| `llm.py` | `VLLMResponder` — streaming do vLLM (**a costura pro agente da entrega 2**) |
| `tts.py` | Kokoro PT-BR + `SentenceChunker` (fala assim que a 1ª frase sai) |
| `playback.py` | `Player` gapless; `clear()` corta na hora (barge-in) |
| `transcript.py` | transcrição ao vivo no terminal (você + agente) |
| `pipeline.py` | orquestração: máquina de estados LISTEN⇄RESPOND + barge-in |

## Instalar

Na venv de voz (CUDA, a mesma onde o torch já roda na 2060S):

```bash
uv pip install sounddevice numpy openai kokoro faster-whisper
# PortAudio no SO (Linux): sudo apt install libportaudio2
# (opcional) upgrade de STT — Parakeet via NeMo:
uv pip install "nemo_toolkit[asr]" cuda-python
```

## Rodar

```bash
# aponte a 2060S e o vLLM, depois rode:
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 \
VLLM_BASE_URL=http://127.0.0.1:8002/v1 VLLM_MODEL=qwen35-27b-abl \
python -m voice_pipeline

python -m voice_pipeline --no-barge-in     # sem fone (half-duplex, evita eco)
python -m voice_pipeline --list-devices    # descobrir índices de mic/alto-falante
STT_ENGINE=parakeet python -m voice_pipeline   # usar Parakeet em vez do Whisper
```

Variáveis úteis: `VLLM_BASE_URL`, `VLLM_MODEL`, `VLLM_API_KEY`, `STT_ENGINE`, `WHISPER_MODEL`,
`TTS_VOICE`, `AUDIO_INPUT_DEVICE`, `AUDIO_OUTPUT_DEVICE`, `BARGE_IN`, `VAD_RMS_THRESHOLD`,
`VAD_END_SILENCE_S`, `STT_HOP_S`. (Para o resto, edite `config.py`.)

## Modo companion (infra no server, I/O em outro device)

Mesma pipeline, dividida por WebSocket: a parte pesada (VAD/STT/LLM/TTS/GPU) roda no **server**; você
conecta de **outro device** só com mic + alto-falante + transcrição. O companion é leve — **não**
precisa de torch/kokoro/whisper, só `sounddevice numpy websockets`.

```
companion (seu device)                         server (GPU)
  mic ──PCM16@16k──────────────▶  WSOutput ◀──  VoicePipeline (VAD/STT/endpoint/LLM/TTS/barge)
  alto-falante ◀──PCM16@24k────────────────────┘        │
  transcrição ◀── partial/final/reply_*/interrupt ──────┘
```

```bash
# no SERVER (GPU):
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 \
VLLM_BASE_URL=http://127.0.0.1:8002/v1 VLLM_MODEL=qwen35-27b-abl \
python -m voice_pipeline.server            # ouve em ws://0.0.0.0:8765 (VOICE_WS_PORT muda a porta)

# no SEU device (só pip install sounddevice numpy websockets):
python -m voice_pipeline.companion --host 100.78.164.45            # com fone (barge-in por voz)
python -m voice_pipeline.companion --host 100.78.164.45 --no-barge-in   # sem fone (half-duplex)
```

Barge-in e half-duplex são decisão do **companion**: com fone, ele streama o mic o tempo todo e o
server detecta a interrupção; sem fone (`--no-barge-in`), o companion segura o mic enquanto a IA fala.
O protocolo WS está no topo de `server.py`. Para expor o server por Tailscale, use o IP do tailnet
como `--host`.

## Decisões de modelo

- **STT = faster-whisper `large-v3-turbo` (padrão).** O turbo vence o `large-v3` em streaming (o
  large-v3 fragmenta por atrasar), roda bem na 2060S em `float16` e já é usado no projeto. Alternativa
  atrás da mesma interface: **Parakeet TDT 0.6B v3** (RNN-T, PT nativo, WER menor, >2000x RTFx) —
  ligue com `STT_ENGINE=parakeet` depois de instalar o NeMo.
- **Autocorreção = LocalAgreement-2.** Re-transcrevemos o buffer que cresce a cada `hop`; só viram
  texto firme as palavras em que dois passos concordam → o parcial para de tremer.
- **TTS = Kokoro (pm_santa, PT-BR).** 82M, leve, latência mínima; sintetiza **por frase** pra começar
  a falar na 1ª sentença (TTFA baixo).
- **Endpoint semântico.** Além do silêncio, se a última palavra é de continuação ("em", "que",
  "para"…) espera mais (`cont_mult`) — não corta no meio da frase.
- **LLM via vLLM direto** (API OpenAI, streaming). O `enable_thinking=False` evita o `<think>` do Qwen.

## Onde ajustar latência × qualidade

- **`STT_HOP_S`** (0.5): menor = parcial mais responsivo, porém mais chamadas de STT. **Maior impacto.**
- **`VAD_END_SILENCE_S`** (1.2): menor = responde mais rápido, mas arrisca cortar pausas.
- **`VAD_RMS_THRESHOLD`** (0.015): calibre ao seu mic/ambiente (muito baixo dispara em ruído).
- **`first_chunk_chars`** (`config.py`, 20): menor = fala antes, porém frases iniciais mais picadas.
- **`beam_size`** (5): 1 acelera o Whisper com leve perda de qualidade.
- **`STT_ENGINE=parakeet`**: o ganho real de latência **e** precisão em PT.
- **Barge-in**: `barge.poll_s`/`barge.frames` controlam rapidez × falso-positivo da interrupção.

## Entrega 2 — evolução pro agente (sem reescrever)

A pipeline depende só do protocolo `Responder` (`async stream(history) -> deltas`). Para plugar o
agente real (orchestrator: tools/memória/sessão), implemente um `AgentResponder` com a mesma
assinatura e injete-o no lugar do `VLLMResponder` em `__main__.py`:

```python
class AgentResponder:
    async def stream(self, history):
        async for delta in orchestrator.run(history):   # tools, memória, sessão
            yield delta
```

Nenhum outro módulo muda. STT, TTS e Player também são injetados — dá pra trocar qualquer peça do
mesmo jeito.
