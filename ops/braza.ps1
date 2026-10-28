# ops/braza.ps1 — toggle vLLM (WSL) + agente (Windows), GPU-aware, com pausa pra jogar.
# EXEMPLO preenchido: ajuste caminhos/IPs/GPUs pro seu caso. Nao e necessario pro agente
# generico (uvicorn main:app direto). Passo a passo em ops/README.md.
param([Parameter(Position=0)][string]$cmd = "status")

# ---- config (ajuste se precisar) ----
$GitBash     = 'C:\Program Files\Git\bin\bash.exe'
$AgentScript = '/c/workspace/brazaia/ops/subir_agente.sh'
$PidFile     = Join-Path $env:USERPROFILE '.braza_agente.pid'
$VllmUrl     = 'http://iobraza:8002/v1/models'
$AgentUrl    = 'http://100.79.27.100:8080/api/v1/health'
$Gpu0Limite  = 2000   # MiB em uso na 3090 acima disso = tem jogo/app -> nao sobe

function Gpu0Used { [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0) | Select-Object -First 1) }
function Esperar($url,$seg){ for($i=0;$i -lt $seg;$i++){ try{ Invoke-RestMethod $url -TimeoutSec 2 | Out-Null; return $true }catch{ Start-Sleep 1 } }; return $false }
function WslAlive {
  if (-not (wsl -u root -- pgrep -f "sleep 2147483647" 2>$null)) {
    $vbs = Join-Path $env:TEMP 'braza-ka.vbs'
    'CreateObject("Wscript.Shell").Run "wsl -u root -- sleep 2147483647", 0, False' | Set-Content -Encoding ASCII $vbs
    Start-Process wscript.exe $vbs -WindowStyle Hidden
    Start-Sleep 3
  }
}


switch ($cmd) {
  "start" {
    $u = Gpu0Used
    if ($u -gt $Gpu0Limite) {
      Write-Host "3090 com $u MiB em uso (jogo/app?). Fecha e tenta de novo - nao vou matar nada." -ForegroundColor Yellow
      break
    }
    WslAlive
    Write-Host "Subindo vLLM (3090)..."
    wsl -u root systemctl start vllm
    if (-not (Esperar $VllmUrl 180)) {
      Write-Host "vLLM nao respondeu. Ver: wsl -u root journalctl -u vllm -n 50" -ForegroundColor Red
      break
    }
    Write-Host "vLLM no ar. Subindo agente (2060)..."
    $old = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess
    if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue; Start-Sleep 1 }   # libera a 8080 (evita Errno 10048)
    $p = Start-Process $GitBash -ArgumentList '-lc', $AgentScript -WindowStyle Hidden -PassThru
    $p.Id | Out-File $PidFile
    if (Esperar $AgentUrl 60) { Write-Host "Tudo no ar. Agente PID $($p.Id)." -ForegroundColor Green }
    else { Write-Host "Agente nao respondeu em 60s (ver log do agente)." -ForegroundColor Red }
  }

  "stop" {
    if (Test-Path $PidFile) {
      $ap = Get-Content $PidFile
      taskkill /PID $ap /T /F 2>$null | Out-Null
      Remove-Item $PidFile -ErrorAction SilentlyContinue
      Write-Host "Agente parado."
    } else { Write-Host "Sem PID do agente (ja parado?)." }
    $old = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess
    if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue }   # mata agente orfao ainda na 8080
    wsl -u root systemctl stop vllm
    Write-Host "vLLM parado. 3090 liberada. (WSL/iobraza seguem vivos)" -ForegroundColor Green
  }

  "status" {
    nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader
    Write-Host ("vLLM:   " + (((wsl -u root systemctl is-active vllm) | Out-String).Trim()))
    $ag = if (Test-Path $PidFile) { "rodando (PID " + (Get-Content $PidFile) + ")" } else { "parado" }
    Write-Host "Agente: $ag"
  }

  default { Write-Host "Uso: braza start | stop | status" }
}
