#!/data/data/com.termux/files/usr/bin/bash
# companion/boot/healthcheck.sh — watchdog do supervisor.
# Chamado periodicamente pelo termux-job-scheduler (JobScheduler do Android, que RE-LANCA o
# Termux mesmo depois de morto). Se o supervisor caiu, reergue (detached). Instalado em
# ~/brazaia/healthcheck.sh pelo `python -m companion.setup`.
pgrep -f "brazaia/supervisor.sh" >/dev/null 2>&1 || nohup "$HOME/brazaia/supervisor.sh" >/dev/null 2>&1 &
