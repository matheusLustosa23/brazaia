#!/data/data/com.termux/files/usr/bin/bash
# companion/boot/localizacao.sh — coleta periódica de localização + bateria (P2).
# Chamado de 15 em 15 min pelo termux-job-scheduler (job 2), que sobrevive a kill/reboot.
# NÃO precisa de rede: grava na fila (~/.brazaia_loc_fila.jsonl); o connect entrega ao server quando puder.
# Instalado em ~/brazaia/localizacao.sh pelo `python -m companion.setup`.
mkdir -p "$HOME/ts"
cd "$HOME" && python -m companion.localizacao coletar >> "$HOME/ts/localizacao.log" 2>&1
