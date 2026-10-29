@echo off
rem ops/braza-start.cmd — chamado pelo launcher .vbs na pasta Startup (boot). Especifico do rig do autor.
rem 1) sobe vLLM+agente (limpa pausa);  2) deixa o WATCHDOG rodando (reergue o agente se a API cair).
timeout /t 25 /nobreak > nul
echo ==== braza boot %date% %time% ==== >> C:\workspace\brazaia\braza-boot.log
powershell -NoProfile -ExecutionPolicy Bypass -File C:\workspace\brazaia\ops\braza.ps1 start    >> C:\workspace\brazaia\braza-boot.log 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File C:\workspace\brazaia\ops\braza.ps1 watchdog >> C:\workspace\brazaia\braza-boot.log 2>&1
