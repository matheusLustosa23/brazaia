# ops/braza.ps1 — toggle + WATCHDOG do stack brazaia: vLLM (WSL) + agente + companion (Windows).
# GPU-aware (pausa pra jogar). Regra: SEMPRE disponível — o watchdog checa SAÚDE e reergue sozinho.
#
# Uso:
#   braza start [--all|--vllm|--agent|--companion]     # default: --all
#   braza stop  [--all|--vllm|--agent|--companion]     # default: --all
#   braza restart [mesmas flags]                       # default: --all
#   braza status                                       # estado de tudo
#   braza watchdog                                     # mantém agente + companion vivos (loop)
#   braza logs [--agent|--vllm|--companion]            # acompanha o log (tail -f)
# Ex.: braza start --vllm   |   braza restart --agent --companion   |   braza stop --companion
param(
  [Parameter(Position=0)][string]$cmd = "status",
  [Parameter(ValueFromRemainingArguments=$true)][string[]]$rest
)

# ---- config (ajuste se precisar) ----
$GitBash     = 'C:\Program Files\Git\bin\bash.exe'
$Repo        = 'C:\workspace\brazaia'
$AgentScript = '/c/workspace/brazaia/ops/subir_agente.sh'
$CompScript  = '/c/workspace/brazaia/ops/subir_companion.sh'
$PidFile     = Join-Path $env:USERPROFILE '.braza_agente.pid'
$PauseFlag   = Join-Path $env:USERPROFILE '.braza_paused'      # existe = pausado p/ jogo (watchdog ignora)
$WatchLog    = Join-Path $env:USERPROFILE '.braza_watchdog.log'
$AgentLog    = Join-Path $Repo 'agente.log'
$CompLog     = Join-Path $Repo 'companion.log'
$VllmUrl     = 'http://iobraza:8002/v1/models'
$AgentUrl    = 'http://100.79.27.100:8080/api/v1/health'
$TsIp        = '100.79.27.100'   # IP Tailscale onde o agente BINDA (--host). Sem ele, o agente nao sobe.
$Gpu0Limite  = 2000              # MiB em uso na 3090 acima disso (SEM vLLM) = tem jogo/app -> nao sobe

# ---- alvos (flags) ----  sem flag = tudo. Aceita PT/EN e 0-2 tracos (--agent, --agente, agente...)
$flags = @($rest) | Where-Object { $_ }
$norm  = @()
foreach ($f in $flags) {
  switch -regex ($f.ToLower()) {
    '^-{0,2}(all|tudo)$'            { $norm += '--all' }
    '^-{0,2}(vllm)$'               { $norm += '--vllm' }
    '^-{0,2}(agent|agente)$'       { $norm += '--agent' }
    '^-{0,2}(companion|companheiro|comp)$' { $norm += '--companion' }
    default { Write-Host "flag '$f' nao reconhecida (use: --all --vllm --agent --companion)" -ForegroundColor Yellow }
  }
}
$allTgt   = ($norm -contains '--all') -or ($flags.Count -eq 0)   # sem flag nenhuma = tudo; flag errada = so o aviso
$tgtVllm  = $allTgt -or ($norm -contains '--vllm')
$tgtAgent = $allTgt -or ($norm -contains '--agent')
$tgtComp  = $allTgt -or ($norm -contains '--companion')

# ---- helpers ----
function Gpu0Used { [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -i 0) | Select-Object -First 1) }
function Esperar($url,$seg){ for($i=0;$i -lt $seg;$i++){ try{ Invoke-RestMethod $url -TimeoutSec 5 | Out-Null; return $true }catch{ Start-Sleep 1 } }; return $false }
function AgentHealthy { try { Invoke-RestMethod $AgentUrl -TimeoutSec 8 | Out-Null; return $true } catch { return $false } }
function VllmActive { return ((((wsl -u root systemctl is-active vllm) | Out-String).Trim()) -eq "active") }
function PidAlive {
  if (-not (Test-Path $PidFile)) { return $false }
  return ($null -ne (Get-Process -Id ([int](Get-Content $PidFile)) -ErrorAction SilentlyContinue))
}
function CompanionAlive {
  return [bool](Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*companion.connect*" })
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
function TsIpPresente { return ($null -ne (Get-NetIPAddress -IPAddress $TsIp -ErrorAction SilentlyContinue)) }
function EnsureTailscale {
  if (TsIpPresente) { return $true }
  try { Start-Service Tailscale -ErrorAction SilentlyContinue } catch {}
  if (Get-Command tailscale -ErrorAction SilentlyContinue) { try { & tailscale up 2>$null | Out-Null } catch {} }
  for ($i=0; $i -lt 30; $i++) { if (TsIpPresente) { return $true }; Start-Sleep 2 }
  return (TsIpPresente)
}

# ---- start/stop por componente ----
function KillAgentProcs {
  # mata TODA janela/processo do agente (por linha de comando) -> nao empilha, mesmo se o watchdog subiu outro
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*subir_agente*" } | ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
  $old = (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue).OwningProcess
  if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue }
}
function StartAgent {
  if (-not (EnsureTailscale)) { return $false }   # sem IP tailscale o agente nao consegue bindar (--host)
  KillAgentProcs; Start-Sleep 1                    # garante 1 so (mata qualquer um que ja exista)
  # Hidden: sem janela pra fechar (robusto). O chrome do screenshot ganha console proprio via CREATE_NO_WINDOW (shot.py).
  $p = Start-Process $GitBash -ArgumentList '-lc', $AgentScript -WindowStyle Hidden -PassThru
  $p.Id | Out-File $PidFile
  return (Esperar $AgentUrl 60)
}
function StopAgent {
  KillAgentProcs
  Remove-Item $PidFile -ErrorAction SilentlyContinue
  Write-Host "Agente parado."
}
function StartCompanion {
  if (CompanionAlive) { Write-Host "Companion ja no ar." -ForegroundColor Green; return $true }
  # Hidden: sem janela pra fechar. open_file de imagem/pagina usa ShellExecute (abre na sessao do usuario de qualquer forma)
  Start-Process $GitBash -ArgumentList '-lc', $CompScript -WindowStyle Hidden | Out-Null
  for ($i=0; $i -lt 10; $i++) { Start-Sleep 1; if (CompanionAlive) { Write-Host "Companion no ar." -ForegroundColor Green; return $true } }
  Write-Host "Companion nao subiu (ver $CompLog)." -ForegroundColor Red; return $false
}
function StopCompanion {
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*companion.connect*" }
  if ($procs) { $procs | ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }; Write-Host "Companion parado." }
  else { Write-Host "Companion ja estava parado." }
}
function StopVllm { wsl -u root systemctl stop vllm; Write-Host "vLLM parado. 3090 liberada." -ForegroundColor Green }

function TailLog($path, $title, $wsl) {
  Write-Host "== $title ==  (Ctrl+C sai)" -ForegroundColor Cyan
  if ($wsl) { wsl -u root journalctl -u vllm -n 40 -f; return }
  if (-not (Test-Path $path)) { Write-Host "(sem log ainda: $path)" -ForegroundColor Yellow; return }
  Get-Content $path -Tail 40 -Wait
}

function ShowHelp {
  Write-Host @"
braza — gestao do stack (vLLM + agente + companion) no server

COMANDOS:
  start    [alvos]   sobe os componentes            (sem alvo = todos)
  stop     [alvos]   para os componentes            (sem alvo = todos)
  restart  [alvos]   para e sobe de novo            (sem alvo = todos)
  status             estado de tudo (GPU, vLLM, agente, companion, watchdog)
  logs     <alvo>    acompanha o log em tempo real (Ctrl+C sai)
  watchdog           mantem agente + companion vivos (loop; roda no boot)
  help               esta ajuda

ALVOS (flags, aceita PT/EN, combinaveis; SEM flag = todos):
  --all | --tudo
  --vllm
  --agent | --agente
  --companion | --companheiro

EXEMPLOS:
  braza start                 sobe tudo
  braza restart --agente      so o agente
  braza stop --vllm           para o vLLM (libera a 3090 p/ jogo)
  braza restart --agent --companion   agente + companion
  braza logs --companion      log do companion   (--agent | --vllm)
  braza status                ve o estado
"@ -ForegroundColor Cyan
}

if ($cmd -in @('-h','--help','/?','?','ajuda','h')) { $cmd = 'help' }

switch ($cmd) {
  "help" { ShowHelp }
  "start" {
    Remove-Item $PauseFlag -ErrorAction SilentlyContinue      # tira a pausa de jogo
    if ($tgtVllm) {
      $u = Gpu0Used
      if ((-not (VllmActive)) -and ($u -gt $Gpu0Limite)) {
        Write-Host "3090 com $u MiB em uso (jogo/app?) e vLLM parado. Fecha e tenta de novo." -ForegroundColor Yellow
      } else {
        EnsureVllm
        if (VllmActive) { Write-Host "vLLM no ar." -ForegroundColor Green }
        else { Write-Host "vLLM nao subiu. Ver: braza logs --vllm" -ForegroundColor Red }
      }
    }
    if ($tgtAgent) {
      if (StartAgent) { Write-Host "Agente no ar." -ForegroundColor Green }
      elseif (-not (TsIpPresente)) { Write-Host "Tailscale sem o IP $TsIp -> agente sem onde bindar." -ForegroundColor Red }
      else { Write-Host "Agente nao respondeu em 60s (braza logs --agent)." -ForegroundColor Red }
    }
    if ($tgtComp) { StartCompanion | Out-Null }
  }

  "restart" {
    Remove-Item $PauseFlag -ErrorAction SilentlyContinue
    if ($tgtComp)  { StopCompanion }
    if ($tgtAgent) { StopAgent }
    if ($tgtVllm)  { EnsureVllm }                             # vLLM: so garante no ar (restart real = systemctl)
    if ($tgtVllm -and -not (VllmActive)) { Write-Host "vLLM nao subiu (braza logs --vllm)." -ForegroundColor Red }
    if ($tgtAgent) { if (StartAgent) { Write-Host "Agente no ar." -ForegroundColor Green } else { Write-Host "Agente nao respondeu (braza logs --agent)." -ForegroundColor Red } }
    if ($tgtComp)  { StartCompanion | Out-Null }
  }

  "stop" {
    if ($tgtVllm)  { New-Item $PauseFlag -ItemType File -Force | Out-Null }   # pausa p/ jogo: watchdog NAO reergue ate 'braza start'
    if ($tgtComp)  { StopCompanion }
    if ($tgtAgent) { StopAgent }
    if ($tgtVllm)  { StopVllm }
    if ($tgtVllm) { Write-Host "(pausado p/ jogo; 'braza start' religa)" -ForegroundColor Green }
  }

  "status" {
    nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader
    $vs = "inativo"; if (VllmActive) { $vs = "active" }
    Write-Host "vLLM:      $vs"
    if (TsIpPresente) { Write-Host "Tailscale: $TsIp OK" -ForegroundColor Green }
    else { Write-Host "Tailscale: SEM o IP $TsIp -> o agente nao sobe" -ForegroundColor Red }
    if (Test-Path $PauseFlag)   { Write-Host "Agente:    PAUSADO p/ jogo -> braza start" -ForegroundColor Yellow }
    elseif (AgentHealthy)       { Write-Host "Agente:    ONLINE (API responde)" -ForegroundColor Green }
    elseif (PidAlive)           { Write-Host "Agente:    TRAVADO (processo vivo, API MORTA) -> braza restart --agent" -ForegroundColor Red }
    else                        { Write-Host "Agente:    CAIDO -> braza start --agent" -ForegroundColor Red }
    if (CompanionAlive) { Write-Host "Companion: ONLINE" -ForegroundColor Green }
    else                { Write-Host "Companion: CAIDO -> braza start --companion" -ForegroundColor Red }
    $wd = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*braza.ps1*watchdog*" }
    if ($wd) { Write-Host "Watchdog:  ATIVO (PID $($wd.ProcessId))" -ForegroundColor Green }
    else     { Write-Host "Watchdog:  INATIVO -> braza watchdog (ou reinicie pra subir no boot)" -ForegroundColor Yellow }
  }

  "logs" {
    if ($flags -contains '--vllm')      { TailLog $null "vLLM (journalctl)" $true }
    elseif ($flags -contains '--companion') { TailLog $CompLog "Companion" $false }
    else                                { TailLog $AgentLog "Agente" $false }   # default: agente
  }

  "watchdog" {
    Write-Host "Watchdog ON — checa agente + companion a cada 30s e reergue. Log: $WatchLog  (Ctrl+C sai)"
    while ($true) {
      try {
        if (Test-Path $PauseFlag) { Start-Sleep 30; continue }   # pausado p/ jogo -> nao mexe
        EnsureVllm
        if (-not (AgentHealthy)) {
          $causa = if (-not (TsIpPresente)) { "DOWN (tailscale sem IP)" } else { "DOWN" }
          ("{0}  agente {1} -> reerguendo" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $causa) | Out-File -Append $WatchLog
          $subiu = StartAgent
          $st = if ($subiu) { "ONLINE" } elseif (-not (TsIpPresente)) { "FALHOU (tailscale)" } else { "FALHOU" }
          ("{0}  agente -> {1}" -f (Get-Date -Format "HH:mm:ss"), $st) | Out-File -Append $WatchLog
        }
        if (-not (CompanionAlive)) {
          ("{0}  companion DOWN -> reerguendo" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) | Out-File -Append $WatchLog
          $c = StartCompanion
          ("{0}  companion -> {1}" -f (Get-Date -Format "HH:mm:ss"), $(if ($c) { "ONLINE" } else { "FALHOU" })) | Out-File -Append $WatchLog
        }
      } catch { ("{0}  watchdog erro: {1}" -f (Get-Date -Format "HH:mm:ss"), ($_ | Out-String)) | Out-File -Append $WatchLog }
      Start-Sleep 30
    }
  }

  default { Write-Host "comando '$cmd' desconhecido." -ForegroundColor Yellow; ShowHelp }
}
