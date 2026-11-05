# ops/braza.ps1 — toggle + WATCHDOG do stack brazaia: vLLM (WSL) + agente + companion (Windows) + busca (SearXNG/Docker).
# GPU-aware (pausa pra jogar). Regra: SEMPRE disponível — o watchdog checa SAÚDE e reergue sozinho.
#
# Uso:
#   braza start [--all|--vllm|--agent|--companion|--busca]  # default: --all
#   braza stop  [--all|--vllm|--agent|--companion]     # default: --all
#   braza restart [mesmas flags]                       # default: --all
#   braza status                                       # estado de tudo
#   braza watchdog                                     # mantém agente + companion vivos (loop)
#   braza logs [--agent|--vllm|--companion]            # acompanha o log (tail -f)
#   braza cli [--device NOME]                          # abre o CLI do companion AQUI (chat com o agente)
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
# busca na web: SearXNG em Docker (Docker Desktop), so em 127.0.0.1:8888 (o agente usa no mesmo Windows)
$DockerExe   = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$SearxNome   = 'searxng'
$SearxImagem = 'searxng/searxng:latest'
$SearxPorta  = 8888
$SearxUrl    = "http://127.0.0.1:$SearxPorta/search?q=teste&format=json"
$SearxConf   = Join-Path $Repo 'ops\searxng'
$SearxSecret = Join-Path $env:USERPROFILE '.braza_searxng_secret'   # fora do git

# ---- alvos (flags) ----  sem flag = tudo. Aceita PT/EN e 0-2 tracos (--agent, --agente, agente...)
$flags = @($rest) | Where-Object { $_ }
if ($cmd -eq 'cli') { $cliArgs = $flags; $flags = @() }      # o cli tem argumentos proprios (--device)
$norm  = @()
foreach ($f in $flags) {
  switch -regex ($f.ToLower()) {
    '^-{0,2}(all|tudo)$'            { $norm += '--all' }
    '^-{0,2}(vllm)$'               { $norm += '--vllm' }
    '^-{0,2}(agent|agente)$'       { $norm += '--agent' }
    '^-{0,2}(companion|companheiro|comp)$' { $norm += '--companion' }
    '^-{0,2}(busca|searxng|search)$' { $norm += '--busca' }
    default { Write-Host "flag '$f' nao reconhecida (use: --all --vllm --agent --companion --busca)" -ForegroundColor Yellow }
  }
}
$allTgt   = ($norm -contains '--all') -or ($flags.Count -eq 0)   # sem flag nenhuma = tudo; flag errada = so o aviso
$tgtVllm  = $allTgt -or ($norm -contains '--vllm')
$tgtAgent = $allTgt -or ($norm -contains '--agent')
$tgtComp  = $allTgt -or ($norm -contains '--companion')
$tgtBusca = $allTgt -or ($norm -contains '--busca')

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

# ---- busca (SearXNG em Docker) ----
function DockerAlive { docker info --format '{{.ServerVersion}}' 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
function EnsureDocker {
  # Docker Desktop e um app de sessao: se fechou (ou nao abriu no login), abre e espera o daemon responder
  if (DockerAlive) { return $true }
  if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) { Start-Process $DockerExe -WindowStyle Minimized }
  for ($i=0; $i -lt 90; $i++) { Start-Sleep 2; if (DockerAlive) { return $true } }
  return $false
}
function SearxHealthy { try { $r = Invoke-RestMethod $SearxUrl -TimeoutSec 10; return ($null -ne $r.results) } catch { return $false } }
function EnsureSearx {
  if (SearxHealthy) { return $true }
  if (-not (EnsureDocker)) { return $false }
  $existe = docker ps -a --filter "name=^/$SearxNome$" --format '{{.Names}}' 2>$null
  if (-not $existe) {
    if (-not (Test-Path $SearxSecret)) {                      # segredo do SearXNG: gerado 1 vez, fica fora do git
      -join ((48..57) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ }) | Set-Content -NoNewline $SearxSecret
    }
    $sec = (Get-Content $SearxSecret -Raw).Trim()
    docker run -d --name $SearxNome --restart unless-stopped -p "127.0.0.1:${SearxPorta}:8080" `
      -v "${SearxConf}:/etc/searxng" -e "SEARXNG_SECRET=$sec" -e "SEARXNG_BASE_URL=http://127.0.0.1:$SearxPorta/" $SearxImagem | Out-Null
  } else {
    docker start $SearxNome 2>$null | Out-Null
  }
  for ($i=0; $i -lt 30; $i++) { Start-Sleep 2; if (SearxHealthy) { return $true } }
  return $false
}
function StopSearx { docker stop $SearxNome 2>$null | Out-Null; Write-Host "Busca (SearXNG) parada." }

# ---- start/stop por componente ----
function KillAgentProcs {
  # mata TODA janela/processo do agente (por linha de comando) -> nao empilha, mesmo se o watchdog subiu outro
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*subir_agente*" } | ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
  $old = (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue).OwningProcess
  if ($old) { Stop-Process -Id $old -Force -ErrorAction SilentlyContinue }
}
function StartHiddenBash($bashScript, $vbsName) {
  # INVISIVEL de verdade: o git-bash IGNORA -WindowStyle Hidden do Start-Process (abre console proprio).
  # O VBS Run(cmd, 0, False) nao abre janela nenhuma (mesmo truque do keep-alive do WSL). Fecha = nao existe.
  $vbs = Join-Path $env:TEMP $vbsName
  ('CreateObject("Wscript.Shell").Run """' + $GitBash + '"" -lc ' + $bashScript + '", 0, False') | Set-Content -Encoding ASCII $vbs
  Start-Process wscript.exe $vbs -WindowStyle Hidden
}
function StartAgent {
  if (-not (EnsureTailscale)) { return $false }   # sem IP tailscale o agente nao consegue bindar (--host)
  KillAgentProcs; Start-Sleep 1                    # garante 1 so (mata qualquer um que ja exista)
  StartHiddenBash $AgentScript 'braza-agent.vbs'   # sem janela (screenshot usa --headless=old, renderiza sem console)
  return (Esperar $AgentUrl 60)
}
function StopAgent {
  KillAgentProcs
  Remove-Item $PidFile -ErrorAction SilentlyContinue
  Write-Host "Agente parado."
}
function StartCompanion {
  if (CompanionAlive) { Write-Host "Companion ja no ar." -ForegroundColor Green; return $true }
  StartHiddenBash $CompScript 'braza-companion.vbs'   # sem janela (VBS); open_file usa ShellExecute (abre na sessao do usuario)
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

function StartCli($argv) {
  $argv = @($argv)
  # CLI interativo NESTE terminal. Device PROPRIO (default server-cli): se usasse 'server' (o do companion de
  # fundo), o registro no agente seria sobrescrito e, ao sair do CLI, o unregister derrubaria o do watchdog.
  $device = 'server-cli'
  for ($i = 0; $i -lt $argv.Count; $i++) {
    if ($argv[$i] -in @('--device','-d')) { $device = $argv[$i+1]; $i++ } else { $device = $argv[$i] }   # aceita o nome solto
  }
  if (-not $device) { Write-Host "uso: braza cli [--device NOME]" -ForegroundColor Yellow; return }
  if ($device -eq 'server') { Write-Host "device 'server' e do companion de fundo (watchdog) -> escolha outro nome" -ForegroundColor Red; return }
  if (-not (AgentHealthy)) { Write-Host "Agente fora do ar -> braza start (o CLI conversa com a API)." -ForegroundColor Red; return }
  $key = ((Select-String -Path (Join-Path $Repo '.env.dev') -Pattern '^AGENT_API_KEY=').Line -split '=',2)[1].Trim().Trim('"')
  $vars = @{ SERVER_WS_URL = "ws://${TsIp}:8080/api/v1"; DEVICE_ID = $device; DEVICE_NAME = $device;
             AGENT_API_KEY = $key; PYTHONUTF8 = '1'; PYTHONIOENCODING = 'utf-8' }
  $antes = @{}
  foreach ($k in $vars.Keys) {
    $antes[$k] = [Environment]::GetEnvironmentVariable($k, 'Process')
    $forca = $k -in @('DEVICE_ID','DEVICE_NAME')                                          # device: o parametro manda
    if ($forca -or -not $antes[$k]) { [Environment]::SetEnvironmentVariable($k, $vars[$k], 'Process') }   # resto: ja setado = respeita
  }
  $encAntes = [Console]::OutputEncoding
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8                                      # emoji/box do CLI
  Push-Location $Repo
  try { & (Join-Path $Repo '.venv\Scripts\python.exe') -m companion }
  finally {
    Pop-Location
    [Console]::OutputEncoding = $encAntes
    foreach ($k in $vars.Keys) { [Environment]::SetEnvironmentVariable($k, $antes[$k], 'Process') }   # devolve o env da sessao
  }
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
  cli [--device N]   abre o CLI do companion aqui (chat com o agente; device default 'server-cli')
                     no bash/WSL: bash /mnt/c/workspace/brazaia/ops/cli.sh [--device N]
  help               esta ajuda

ALVOS (flags, aceita PT/EN, combinaveis; SEM flag = todos):
  --all | --tudo
  --vllm
  --agent | --agente
  --companion | --companheiro
  --busca | --searxng            (SearXNG no Docker; 'braza stop' de jogo nao para a busca)

EXEMPLOS:
  braza start                 sobe tudo
  braza restart --agente      so o agente
  braza stop --vllm           para o vLLM (libera a 3090 p/ jogo)
  braza restart --agent --companion   agente + companion
  braza logs --companion      log do companion   (--agent | --vllm)
  braza status                ve o estado
  braza cli                   conversa com o agente neste terminal (/sair fecha)
  braza cli --device sala     idem, registrado como device 'sala'
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
    if ($tgtBusca) { if (EnsureSearx) { Write-Host "Busca (SearXNG) no ar." -ForegroundColor Green } else { Write-Host "Busca nao subiu (Docker Desktop aberto? docker logs searxng)." -ForegroundColor Red } }
  }

  "restart" {
    Remove-Item $PauseFlag -ErrorAction SilentlyContinue
    if ($tgtComp)  { StopCompanion }
    if ($tgtAgent) { StopAgent }
    if ($tgtVllm)  { EnsureVllm }                             # vLLM: so garante no ar (restart real = systemctl)
    if ($tgtVllm -and -not (VllmActive)) { Write-Host "vLLM nao subiu (braza logs --vllm)." -ForegroundColor Red }
    if ($tgtAgent) { if (StartAgent) { Write-Host "Agente no ar." -ForegroundColor Green } else { Write-Host "Agente nao respondeu (braza logs --agent)." -ForegroundColor Red } }
    if ($tgtComp)  { StartCompanion | Out-Null }
    if ($tgtBusca -and -not $allTgt) { StopSearx; if (EnsureSearx) { Write-Host "Busca (SearXNG) no ar." -ForegroundColor Green } else { Write-Host "Busca nao subiu." -ForegroundColor Red } }
    elseif ($tgtBusca) { if (EnsureSearx) { Write-Host "Busca (SearXNG) no ar." -ForegroundColor Green } else { Write-Host "Busca nao subiu." -ForegroundColor Red } }
  }

  "stop" {
    if ($tgtVllm)  { New-Item $PauseFlag -ItemType File -Force | Out-Null }   # pausa p/ jogo: watchdog NAO reergue ate 'braza start'
    if ($tgtComp)  { StopCompanion }
    if ($tgtAgent) { StopAgent }
    if ($tgtVllm)  { StopVllm }
    if ($tgtBusca -and -not $allTgt) { StopSearx }          # 'braza stop' (jogo) NAO para a busca: e leve; so com --busca
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
    if (SearxHealthy)   { Write-Host "Busca:     ONLINE (SearXNG 127.0.0.1:$SearxPorta)" -ForegroundColor Green }
    elseif (-not (DockerAlive)) { Write-Host "Busca:     CAIDA (Docker Desktop fechado) -> braza start --busca" -ForegroundColor Red }
    else                { Write-Host "Busca:     CAIDA -> braza start --busca (docker logs searxng)" -ForegroundColor Red }
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
    Write-Host "Watchdog ON — checa agente + companion + busca a cada 30s e reergue. Log: $WatchLog  (Ctrl+C sai)"
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
        if (-not (SearxHealthy)) {
          ("{0}  busca DOWN -> reerguendo (docker/searxng)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) | Out-File -Append $WatchLog
          $b = EnsureSearx
          ("{0}  busca -> {1}" -f (Get-Date -Format "HH:mm:ss"), $(if ($b) { "ONLINE" } else { "FALHOU" })) | Out-File -Append $WatchLog
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

  "cli" { StartCli $cliArgs }

  default { Write-Host "comando '$cmd' desconhecido." -ForegroundColor Yellow; ShowHelp }
}
