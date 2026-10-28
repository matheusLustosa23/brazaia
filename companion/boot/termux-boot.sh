#!/data/data/com.termux/files/usr/bin/bash
# companion/boot/termux-boot.sh — entry do Termux:Boot (CS1).
# Instalado em ~/.termux/boot/00-brazaia.sh pelo `python -m companion.setup`.
# Roda no boot do aparelho (precisa do app Termux:Boot instalado): segura wake-lock
# e sobe o supervisor, que mantem o tailscaled vivo + na tailnet.
termux-wake-lock
"$HOME/brazaia/supervisor.sh" &
