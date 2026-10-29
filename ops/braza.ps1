# ops/braza.ps1 — toggle + WATCHDOG do vLLM (WSL) + agente (Windows). GPU-aware, pausa pra jogar.
# Regra: SEMPRE disponível. O watchdog checa a SAÚDE DA API (não só o PID) e reergue o agente sozinho.
# `stop` cria uma flag de pausa (pra jogo) que o watchdog respeita; `start`/`restart` removem a flag.
# EXEMPLO preenchido: ajuste caminhos/IPs/GPUs. Passo a passo em ops/README.md.
param([Parameter(Position=0)][string]$cmd = "status")

# ---- config (ajuste se precisar) ----
$GitBash     = 'C:\Program Files\Git\bin\bash.exe'
$AgentScript = '/c/workspace/brazaia/ops/subir_agente.sh'
$PidFile     = Join-Path $env:USERPROFILE '.braza_agente.pid'
$PauseFlag   = Join-Path $env:USERPROFILE '.braza_paused'      # existe = pausado p/ jogo (watchdog ignora)
$WatchLog    = Join-Path $env:USERPROFILE '.braza_watchdog.log'
$VllmUrl     = 'http://iobraza:8002/v1/models'
$AgentUrl    = 'http://100.79.27.100:8080/api/v1/health'
$TsIp        = '100.79.27.100'   # IP Tailscale do Windows onde o agente BINDA (--host). Sem ele, o agente nao sobe.
$Gpu0Limite  = 2000   # MiB em uso na 3090 acima disso (SEM vLLM) = tem jogo/app -> nao sobe

function Gpu0Used { [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0) | Select-Object -First 1) }
function Esperar($url,$seg){ for($i=0;$i -lt $seg;$i++){ try{ Invoke-RestMethod $url -TimeoutSec 5 | Out-Null; return $true }catch{ Start-Sleep 1 } }; return $false }
# TimeoutSec folgado: o /health consulta o vLLM e pode levar ~2s (mais ainda no load) -> evita o watchdog reiniciar um agente SAUDAVEL
function AgentHealthy { try { Invoke-RestMethod $AgentUrl -TimeoutSec 8 | Out-Null; return $true } catch { return $false } }
function VllmActive { return ((((wsl -u root systemctl is-active vllm) | Out-String).Trim()) -eq "active") }
function PidAlive {
  if (-not (Test-Path $PidFile)) { return $false }
  return ($null -ne (Get-Process -Id ([int](Get-Content $PidFile)) -ErrorAction SilentlyContinue))
}
function WslAlive {
  if (-not (wsl -u root -- pgrep -f "sleep 2147483647" 2>$null)) {
    $vbs = Join-Path $env:TEMP 'braza-ka.vbs'
    'CreateObject("Wscript.Shell").Run "wsl -u root -- sleep 2147483647", 0, False' | Set-Content -Encoding ASCII $vbs
    Start-Process wscript.exe $vbs -WindowStyle Hidden
    Start-Sleep 3
  }
}
function EnsureVllm { WslAlive; if (-not (VllmActive)) { wsl -u root systemctl start vllm; Esperar $VllmUrl 180 | Out-Null } }
# o agente binda no IP tailscale; se ele nao existe, o uvicorn morre no startup (Cannot assign requested address)
function TsIpPresente { return ($null -ne (Get-NetIPAddress -IPAddress $TsIp -ErrorAction SilentlyContinue)) }
function EnsureTailscale {
  if (TsIpPresente) { return $true }
  try { Start-Service Tailscale -ErrorAction SilentlyContinue } catch {}   # sobe o servico do Windows se parado
  if (Get-Command tailscale -ErrorAction SilentlyContinue) { try { & tailscale up 2>$null | Out-Null } catch {} }
  for ($i=0; $i -lt 30; $i++) { if (TsIpPresente) { return $true }; Start-Sleep 2 }  # espera o IP ser atribuido (ate 60s)
  return (TsIpPresente)
}
function StartAgent {
  if (-not (EnsureTailscale)) { return $false }   # sem IP tailscale o agente nao consegue bindar (--host $TsIp) -> nem tenta
  # libera a 8080 (mata agente travado/orfao) e sobe de novo; espera a API responder de verdade
  $old = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess
  if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue; Start-Sleep 1 }
  $p = Start-Process $GitBash -ArgumentList '-lc', $AgentScript -WindowStyle Hidden -PassThru
  $p.Id | Out-File $PidFile
  return (Esperar $AgentUrl 60)
}

switch ($cmd) {
  "start" {
    Remove-Item $PauseFlag -ErrorAction SilentlyContinue      # tira a pausa de jogo
    $u = Gpu0Used
    if ((-not (VllmActive)) -and ($u -gt $Gpu0Limite)) {
      Write-Host "3090 com $u MiB em uso (jogo/app?) e vLLM parado. Fecha e tenta de novo." -ForegroundColor Yellow
      break
    }
    EnsureVllm
    if (-not (VllmActive)) { Write-Host "vLLM nao subiu. Ver: wsl -u root journalctl -u vllm -n 50" -ForegroundColor Red; break }
    Write-Host "vLLM no ar. Subindo agente (2060)..."
    if (StartAgent) { Write-Host "Tudo no ar." -ForegroundColor Green }
    elseif (-not (TsIpPresente)) { Write-Host "Tailscale sem o IP $TsIp -> o agente nao tem onde bindar. Confira o Tailscale." -ForegroundColor Red }
    else { Write-Host "Agente nao respondeu em 60s (ver C:\workspace\brazaia\agente.log)." -ForegroundColor Red }
  }

  "restart" {
    Remove-Item $PauseFlag -ErrorAction SilentlyContinue
    EnsureVllm
    Write-Host "Reiniciando SO o agente (vLLM intacto)..."
    if (StartAgent) { Write-Host "Agente no ar." -ForegroundColor Green }
    elseif (-not (TsIpPresente)) { Write-Host "Tailscale sem o IP $TsIp -> o agente nao tem onde bindar. Confira o Tailscale." -ForegroundColor Red }
    else { Write-Host "Agente nao respondeu (ver C:\workspace\brazaia\agente.log)." -ForegroundColor Red }
  }

  "stop" {
    New-Item $PauseFlag -ItemType File -Force | Out-Null       # pausa: o watchdog NAO reergue (ate `braza start`)
    if (Test-Path $PidFile) {
      $ap = Get-Content $PidFile
      taskkill /PID $ap /T /F 2>$null | Out-Null
      Remove-Item $PidFile -ErrorAction SilentlyContinue
      Write-Host "Agente parado."
    } else { Write-Host "Sem PID do agente (ja parado?)." }
    $old = (Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess
    if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue }
    wsl -u root systemctl stop vllm
    Write-Host "vLLM parado. 3090 liberada. (pausado p/ jogo; 'braza start' religa)" -ForegroundColor Green
  }

  "status" {
    nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader
    $vs = "inativo"; if (VllmActive) { $vs = "active" }
    Write-Host "vLLM:   $vs"
    if (TsIpPresente) { Write-Host "Tailscale: $TsIp OK" -ForegroundColor Green }
    else { Write-Host "Tailscale: SEM o IP $TsIp -> o agente nao sobe" -ForegroundColor Red }
    if (Test-Path $PauseFlag)   { Write-Host "Agente: PAUSADO p/ jogo -> braza start" -ForegroundColor Yellow }
    elseif (AgentHealthy)       { Write-Host "Agente: ONLINE (API responde)" -ForegroundColor Green }
    elseif (PidAlive)           { Write-Host "Agente: TRAVADO (processo vivo, API MORTA) -> braza restart" -ForegroundColor Red }
    else                        { Write-Host "Agente: CAIDO -> braza restart" -ForegroundColor Red }
    $wd = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*braza.ps1*watchdog*" }
    if ($wd) { Write-Host "Watchdog: ATIVO (PID $($wd.ProcessId))" -ForegroundColor Green }
    else     { Write-Host "Watchdog: INATIVO -> braza watchdog (ou reinicie pra subir no boot)" -ForegroundColor Yellow }
  }

  "watchdog" {
    Write-Host "Watchdog ON — checa a saude da API a cada 30s e reergue. Log: $WatchLog  (Ctrl+C sai)"
    while ($true) {
      try {
        if (Test-Path $PauseFlag) { Start-Sleep 30; continue }   # pausado p/ jogo -> nao mexe
        EnsureVllm
        if (-not (AgentHealthy)) {
          $causa = if (-not (TsIpPresente)) { "DOWN (tailscale sem IP)" } else { "DOWN" }
          ("{0}  agente {1} -> reerguendo" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $causa) | Out-File -Append $WatchLog
          $subiu = StartAgent
          $st = if ($subiu) { "ONLINE" } elseif (-not (TsIpPresente)) { "FALHOU (tailscale nao subiu)" } else { "FALHOU" }
          ("{0}  agente -> {1}" -f (Get-Date -Format "HH:mm:ss"), $st) | Out-File -Append $WatchLog
        }
      } catch { ("{0}  watchdog erro: {1}" -f (Get-Date -Format "HH:mm:ss"), ($_ | Out-String)) | Out-File -Append $WatchLog }
      Start-Sleep 30
    }
  }

  default { Write-Host "Uso: braza start | stop | restart | status | watchdog" }
}
