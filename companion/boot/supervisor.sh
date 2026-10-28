#!/data/data/com.termux/files/usr/bin/bash
# companion/boot/supervisor.sh — supervisor do companion no Termux (CS1).
# Garante o tailscaled (userspace) vivo + na tailnet; loop de auto-cura.
# Instalado em ~/brazaia/supervisor.sh pelo `python -m companion.setup` e lancado
# pelo Termux:Boot (companion/boot/termux-boot.sh). Ver companion/boot/README ou ops/README.
set -u
[ -f "$HOME/.brazaia.env" ] && source "$HOME/.brazaia.env"   # TS_AUTHKEY, DEVICE_ID, SERVER_WS_URL
TS="$HOME/ts/bin"
STATE="$HOME/ts/state"
REPO="$HOME/brazaia"                        # onde o repo esta checado no celular
mkdir -p "$STATE" "$HOME/ts"

log() { echo "$(date '+%H:%M:%S') $*" >> "$HOME/ts/supervisor.log"; }

sobe_tailscaled() {
  pgrep -f "tailscaled --tun=userspace" >/dev/null 2>&1 && return
  log "subindo tailscaled (userspace)..."
  "$TS/tailscaled" --tun=userspace-networking --socks5-server=localhost:1055 \
    --state="$STATE/tailscaled.state" --socket="$STATE/tailscaled.sock" \
    >> "$HOME/ts/tsd.log" 2>&1 &
  sleep 3
  "$TS/tailscale" --socket="$STATE/tailscaled.sock" up \
    --auth-key="${TS_AUTHKEY:-}" --hostname="${DEVICE_ID:-celular}" >> "$HOME/ts/tsd.log" 2>&1
  log "tailscale up ip=$("$TS/tailscale" --socket="$STATE/tailscaled.sock" ip -4 2>/dev/null)"
}

sobe_connect() {
  pgrep -f "companion.connect --fg" >/dev/null 2>&1 && return
  log "subindo connect (device no server)..."
  ( cd "$REPO" && python -m companion.connect --fg >> "$HOME/ts/connect.log" 2>&1 ) &
}

while true; do
  sobe_tailscaled           # garante a tailnet
  sobe_connect              # garante a presenca do device no server (CS2b: via SOCKS5)
  sleep 30
done
