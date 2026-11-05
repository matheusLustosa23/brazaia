#!/data/data/com.termux/files/usr/bin/bash
# companion/boot/instalar.sh — instalação INICIAL de um device Termux, do zero, com um KIT.
#   bash instalar.sh <KIT>
# O KIT (gerado no servidor: ops/companion_kit.py; depois o painel) traz servidor, nome do device e a auth-key do
# Tailscale. Ordem obrigatória: o servidor só é alcançável PELA TAILNET → primeiro o Tailscale, depois o pacote.
# Manual continua só: instalar os apps (Termux, Termux:API, Termux:Boot, Termux:Widget) e tocar "Permitir".
set -e
KIT="${1:?uso: bash instalar.sh <KIT>}"
echo "1/6 pacotes do Termux (pode levar alguns minutos num Termux novo)…"
# À vista e sem pergunta: com a saída escondida, uma pergunta do dpkg sobre arquivo de configuração
# ("manter o atual? [Y/n]") travava o script sem ninguém ver (04/11, 1º celular novo). confdef/confold = padrão.
DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold python termux-api curl
eval "$(python - "$KIT" <<'PY'
import base64, json, sys
k = sys.argv[1]; d = json.loads(base64.urlsafe_b64decode(k + "=" * (-len(k) % 4)))
print(f'SERVIDOR="{d["servidor"]}"; TS_AUTHKEY="{d["ts_authkey"]}"; DEVICE_ID="{d["device_id"]}"')
PY
)"
TS="$HOME/ts/bin"; STATE="$HOME/ts/state"; mkdir -p "$TS" "$STATE"
# Tailscale SEMPRE com PATH limpo: no init ele procura o termux-clipboard-set no PATH e, se ACHA, faz a syscall
# faccessat2 — que alguns Androids bloqueiam (seccomp → SIGSYS: bad system call). Medido 04/11 num Android 15:
# mesma 1.104.4 do S24 crashava; com PATH=/system/bin roda. Não precisa de nada do Termux no PATH (userspace).
TSX="env PATH=/system/bin"

if [ ! -x "$TS/tailscaled" ]; then
  echo "2/6 baixando o Tailscale…"
  ARQ=$(python -c "import platform;print({'aarch64':'arm64','armv7l':'arm','armv8l':'arm','x86_64':'amd64'}[platform.machine()])")
  NOME=$(curl -s https://pkgs.tailscale.com/stable/?mode=json | python -c "import sys,json;print(json.load(sys.stdin)['Tarballs']['$ARQ'])")
  curl -s "https://pkgs.tailscale.com/stable/$NOME" | tar xz -C "$HOME/ts"
  cp "$HOME"/ts/tailscale_*/tailscale "$HOME"/ts/tailscale_*/tailscaled "$TS/"; chmod +x "$TS"/*
fi
echo "3/6 entrando na tailnet…"
pgrep -f "tailscaled --tun=userspace" >/dev/null || { $TSX "$TS/tailscaled" --tun=userspace-networking \
  --socks5-server=localhost:1055 --state="$STATE/tailscaled.state" --socket="$STATE/tailscaled.sock" \
  >> "$HOME/ts/tsd.log" 2>&1 & sleep 3; }
$TSX "$TS/tailscale" --socket="$STATE/tailscaled.sock" up --auth-key="$TS_AUTHKEY" --hostname="$DEVICE_ID"
echo "4/6 baixando o companion do servidor ($SERVIDOR)…"
P="--socks5-hostname localhost:1055"
ARQUIVO=$(curl -s $P "http://$SERVIDOR/api/v1/companion/versao" | python -c "import sys,json;print(json.load(sys.stdin)['arquivo'])")
mkdir -p "$HOME/.brazaia/pacote"
curl -s $P -o "$HOME/.brazaia/pacote/$ARQUIVO" "http://$SERVIDOR/api/v1/companion/pacote/$ARQUIVO"
echo "5/6 instalando ($ARQUIVO)…"
pip install -q "$HOME/.brazaia/pacote/$ARQUIVO[cli]"
echo "6/6 configurando (boot, supervisor, localização, permissões)…"
cd "$HOME" && python -m companion.setup --kit "$KIT"
nohup "$HOME/.brazaia/supervisor.sh" >/dev/null 2>&1 &
echo "pronto: device $DEVICE_ID no ar (ver: python -m companion connect status)"
