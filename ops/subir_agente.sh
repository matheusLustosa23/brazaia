#!/usr/bin/env bash
# ops/subir_agente.sh — sobe o AGENTE na GPU secundaria (CUDA_VISIBLE_DEVICES=1), deixando a
# principal pro vLLM. EXEMPLO preenchido: ajuste pro seu caso. Roda da RAIZ do projeto (nao de ops/).
# Agente generico = `uv run --no-sync uvicorn main:app --host <ip> --port <porta>` (ver ops/README.md).
export CUDA_DEVICE_ORDER=PCI_BUS_ID      # 0=3090, 1=2060 (determinístico)
export CUDA_VISIBLE_DEVICES=1            # o agente só enxerga a 2060 → STT/Piper vão pra ela
cd /c/workspace/brazaia
source .venv/Scripts/activate
# loga tudo em agente.log (gitignored) — o braza sobe escondido, entao e aqui que vc le o traceback.
exec uv run --no-sync uvicorn main:app --host 100.79.27.100 --port 8080 >> /c/workspace/brazaia/agente.log 2>&1

