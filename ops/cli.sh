#!/usr/bin/env bash
# ops/cli.sh — abre o CLI do companion (chat com o agente) a partir do BASH do server: WSL ou Git Bash.
# (No PowerShell o equivalente é `braza cli`.)
#
# Uso:  bash /mnt/c/workspace/brazaia/ops/cli.sh [--device NOME]      (WSL)
#       bash /c/workspace/brazaia/ops/cli.sh [--device NOME]          (Git Bash)
#       atalho sugerido (~/.bashrc):  alias braza-cli='bash /mnt/c/workspace/brazaia/ops/cli.sh'
#
# --device NOME  nome do device com que o CLI se registra no agente. Default: server-wsl (WSL) / server-cli
#                (Git Bash). NUNCA 'server': é o companion de fundo do watchdog — o CLI tomaria o lugar dele
#                e, ao sair, o agente apagaria o registro (o companion de fundo ficaria sem rota).
#
# WSL: roda com um Python LINUX (venv próprio e leve em ~/.venvs/brazaia-cli, criado no 1º uso com o mesmo
#      conjunto mínimo do Termux) → render de terminal Linux, sem os bugs do console do Windows.
# Git Bash: usa o .venv do Windows; só dentro do Windows Terminal (mintty puro não é console → recusa).
set -euo pipefail

DEVICE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -d|--device) DEVICE="${2:-}"; shift 2 ;;
    -h|--help)   sed -n '2,15p' "$0"; exit 0 ;;
    *)           DEVICE="$1"; shift ;;                     # aceita o nome solto: cli.sh meu-pc
  esac
done

case "$(uname -s)" in
  Linux*)  MODO=wsl;     REPO=/mnt/c/workspace/brazaia; DEVICE="${DEVICE:-server-wsl}" ;;
  MINGW*|MSYS*) MODO=gitbash; REPO=/c/workspace/brazaia; DEVICE="${DEVICE:-server-cli}" ;;
  *) echo "ambiente $(uname -s) não suportado (use WSL, Git Bash ou 'braza cli' no PowerShell)"; exit 1 ;;
esac
if [ "$DEVICE" = "server" ]; then
  echo "device 'server' é do companion de fundo (watchdog) — escolha outro nome (ex.: --device server-cli)"; exit 1
fi

# chave da API: a mesma do agente (.env.dev do repo); env já setado tem prioridade
if [ -z "${AGENT_API_KEY:-}" ]; then
  AGENT_API_KEY="$(grep -E '^AGENT_API_KEY=' "$REPO/.env.dev" | head -1 | cut -d= -f2- | tr -d '\r"'"'")"
fi
export AGENT_API_KEY
export SERVER_WS_URL="${SERVER_WS_URL:-ws://100.79.27.100:8080/api/v1}"
export DEVICE_ID="$DEVICE" DEVICE_NAME="$DEVICE"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1   # sem __pycache__ cruzando Linux/Windows no mesmo repo

if ! curl -s -m 5 -o /dev/null "http://100.79.27.100:8080/api/v1/health"; then
  echo "agente fora do ar (100.79.27.100:8080) → no PowerShell: braza start"; exit 1
fi

cd "$REPO"
if [ "$MODO" = wsl ]; then
  VENV="$HOME/.venvs/brazaia-cli"
  export PATH="$HOME/.local/bin:$PATH"                      # uv mora aqui (shell não-login não carrega o .profile)
  if [ ! -x "$VENV/bin/python" ]; then                    # 1º uso: venv Linux só com o que o CLI importa
    echo "criando o venv do CLI em $VENV (só na 1ª vez)…"
    command -v uv >/dev/null || { echo "precisa do uv no WSL (curl -LsSf https://astral.sh/uv/install.sh | sh)"; exit 1; }
    uv venv -q --python 3.12 "$VENV"
    uv pip install -q --python "$VENV/bin/python" -r companion/requirements-termux.txt
  fi
  exec "$VENV/bin/python" -m companion.cli
else
  if [ "${TERM_PROGRAM:-}" = mintty ]; then               # mintty puro não é console do Windows; via winpty o
    echo "o Git Bash (mintty) não é console do Windows → o CLI quebra o render."   # ANSI do banner vira '?[1m…'
    echo "abra o Git Bash pelo Windows Terminal, ou use o WSL:  wsl -- bash /mnt/c/workspace/brazaia/ops/cli.sh"
    exit 1
  fi
  exec "$REPO/.venv/Scripts/python.exe" -m companion.cli   # Windows Terminal/SSH = ConPTY (console de verdade)
fi
