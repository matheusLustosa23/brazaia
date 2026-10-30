#!/usr/bin/env bash
# ops/subir_companion.sh — sobe o COMPANION do server (device "server": câmera/notify/open_file/screenshot).
# Roda da RAIZ do projeto. Log em companion.log (gitignored). O braza sobe via Start-Process -WindowStyle
# Minimized (NÃO Hidden: open_file de imagem/página abre viewer/navegador e precisa de window-station).
cd /c/workspace/brazaia
source .venv/Scripts/activate
# env do device "server": aponta pro agente local (IP tailscale). ${VAR:-default} => se ja setado, respeita.
export SERVER_WS_URL="${SERVER_WS_URL:-ws://100.79.27.100:8080/api/v1}"
export DEVICE_ID="${DEVICE_ID:-server}"
export DEVICE_NAME="${DEVICE_NAME:-server}"
exec uv run --no-sync python -m companion.connect --fg >> /c/workspace/brazaia/companion.log 2>&1
