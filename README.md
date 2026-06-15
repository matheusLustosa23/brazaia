# iobraza — Agente API

Assistente pessoal de IA, voz-first, multi-device, local (Qwen3-VL via vLLM).
Organização em camadas (Tower): `api → application → domain ← infrastructure`.

## Requisitos
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) (gerência de venv/deps)

## Setup
```bash
uv sync --dev          # cria .venv e instala deps (runtime + dev)
```

## Rodar a API
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080 --reload
curl -s localhost:8080/api/v1/health
```

## Type checking (pyright)

O projeto usa **pyright** como type-checker — é o mesmo motor do Pylance no VS Code,
então editor e CI concordam. Ele é o que **cobra os contratos `Protocol`** (`domain/contracts.py`):
o equivalente Pythonic ao compilador exigindo `implements`. A config vive em `[tool.pyright]`
no `pyproject.toml`.

```bash
uv run pyright                 # checa o projeto todo
uv run pyright domain/         # checa um diretório
```
Meta: **0 errors**. Rode antes de cada commit (e no CI). Erros de contrato (uma implementação
que não satisfaz um `Protocol`, assinatura divergente, etc.) aparecem aqui.

## Convenções
- Respostas HTTP sempre pelo envelope `ApiResponse[T]` + Pydantic — **nunca** `ORJSONResponse`.
- `orjson` só para mensagens WebSocket e logs.
- Segredos via `SecretStr` em `core/config.py`; config 100% por env (`.env.{dev,prod}`).
- vLLM nunca exposto — só `127.0.0.1`.
