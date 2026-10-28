@echo off
rem ops/braza-start.cmd — chamado pelo launcher .vbs na pasta Startup (boot). Especifico do rig do autor.
timeout /t 25 /nobreak > nul
echo ==== braza boot %date% %time% ==== >> C:\workspace\brazaia\braza-boot.log
powershell -NoProfile -ExecutionPolicy Bypass -File C:\workspace\brazaia\ops\braza.ps1 start >> C:\workspace\brazaia\braza-boot.log 2>&1
