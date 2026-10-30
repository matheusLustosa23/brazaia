# ops/ — Guia: agente local sempre no ar + toggle pra jogar

Automação **opcional** pra deixar o vLLM + o agente subindo **sozinhos no boot** (sem login manual), com um comando pra **ligar/desligar** (pausar a GPU pra jogar), tudo auto-recuperável após reboot/sleep.

> **Nada daqui é necessário pro agente.** Pra rodar o agente em qualquer máquina, com o vLLM já no ar:
> ```bash
> uv run --no-sync uvicorn main:app --host <ip> --port <porta>   # VLLM_BASE_URL no .env
> ```
> O `ops/` é só a conveniência de "ligou o PC = tudo pronto". Os scripts aqui são um **exemplo preenchido** — ajuste os valores (usuário, IPs, modelo, GPUs) pro seu caso.

## Cenário / pré-requisitos
- Windows + **WSL2** (a GPU é compartilhada entre Windows e WSL).
- **Tailscale** (pra alcançar o agente de fora pela rede privada).
- 1+ GPU. Com **2 GPUs** dá pra deixar o vLLM numa e o agente na outra (sem brigar); com 1, usa o toggle.
- O agente roda **no Windows** (STT na GPU); o **vLLM roda no WSL**.

---

## Passo 1 — WSL com systemd
Em `/etc/wsl.conf` (no WSL):
```ini
[boot]
systemd=true

[user]
default=<seu-usuario-wsl>
```
Aplica: `wsl --shutdown` (no PowerShell) e reabre. Confirma: `systemctl is-system-running` (active/degraded = systemd on).

## Passo 2 — Tailscale do WSL confiável
Se tiver 2 instalações brigando (snap + apt), desativa a do snap:
```bash
sudo systemctl disable --now snap.tailscale.tailscaled.service
```
O `tailscaled` padrão sobe o `tailscale0` **sem IPv4** → força o `--tun` via override:
```bash
sudo systemctl edit tailscaled      # cole, com o ExecStart certo da sua instalação:
#   [Service]
#   ExecStart=
#   ExecStart=/usr/sbin/tailscaled --tun=tailscale0 --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --port=41641
#   Restart=always
sudo systemctl daemon-reload && sudo systemctl restart tailscaled
ip -4 addr show tailscale0          # tem que mostrar o IP 100.x na interface
```

## Passo 3 — vLLM instalado + serviço
1. Instala o vLLM na venv do WSL e baixa o modelo (ver `subir_27b.sh` — **ajuste model/paths/GPU/util**).
2. Instala o serviço (template em `ops/vllm.service`, **ajuste `User=` e o `ExecStart`**):
   ```bash
   sudo cp ops/vllm.service /etc/systemd/system/vllm.service
   sudo systemctl daemon-reload
   sudo systemctl disable vllm        # NÃO sobe no boot — o braza controla
   ```
   - **Gotcha 1:** o systemd não lê o `.bashrc` → todo env (ex.: `VLLM_USE_FLASHINFER_SAMPLER=0`, `CUDA_*`) vai **dentro** do `subir_27b.sh`.
   - **Gotcha 2:** sem `After=network-online.target` (num boot frio do WSL ele pendura esperando a rede).
   - **Gotcha 3:** `--gpu-memory-utilization` no limite → o KV cache pode faltar por pouco; suba um fio (ex.: 0.93→0.94).

## Passo 4 — agente na outra GPU (opcional, se tiver 2)
`subir_agente.sh` sobe o agente fixado na GPU menor (`CUDA_VISIBLE_DEVICES=1`) e faz bind **só no IP do Tailscale** (`--host <ip-tailscale>`, não `0.0.0.0` → não expõe na LAN). Assim vLLM e agente coexistem.

- **Gotcha (screenshot):** o agente usa o chromium do Playwright pra tirar print do HTML (`create_file`/`screenshot`). Rode **uma vez** na venv do agente: `uv run playwright install chromium`. Sem isso o `chrome.exe --screenshot` é usado como fallback, mas ele sai `rc=0 sem PNG` quando o agente roda **sem console/janela** (VBS Hidden) — por isso o Playwright é o caminho padrão.

## Passo 5 — o toggle `braza`
`braza.ps1` (PowerShell) com `start`/`stop`/`status`: **ajuste os caminhos, IPs e o `$Gpu0Limite`**.
- `start`: checa a GPU livre (se tiver jogo, **avisa, não mata**) → sobe um **keep-alive** (senão o WSL se desliga ao fim do comando) → `systemctl start vllm` → espera o health → sobe o agente.
- `stop`: mata o agente + para o vLLM (libera a GPU pro jogo; WSL/Tailscale seguem vivos).

## Passo 6 — login automático do usuário
O **WSL só boota com uma sessão de usuário** → precisa de auto-login.
- `netplwiz` → desmarca "Os usuários devem digitar um nome e senha" → senha.
- Se a caixa não aparecer (Win11/Hello): `reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device" /v DevicePasswordLessBuildVersion /t REG_DWORD /d 0 /f` → reabre o `netplwiz`.

## Passo 7 — boot automático (sem janelas)
Na pasta Startup do usuário, um `.vbs` que roda o `braza-start.cmd` **oculto**:
```vbs
CreateObject("Wscript.Shell").Run "C:\caminho\do\repo\ops\braza-start.cmd", 0, False
```
O `braza-start.cmd` espera uns 25s, loga, e chama `braza.ps1 start`. No boot: usuário entra sozinho → o `.vbs` dispara → WSL boota (keep-alive segura) → vLLM + agente no ar.

## Passo 8 — testar
```powershell
.\ops\braza.ps1 stop ; wsl --shutdown ; Start-Sleep 8
.\ops\braza.ps1 start        # tem que subir tudo com o WSL frio, sem travar
# e um reboot sem tocar em nada: do outro device, curl http://<ip>:<porta>/api/v1/health
```

---

## Segredos (NUNCA no git)
Config e chaves ficam em `~/.brazaia.env` (fora do repo): `TS_AUTHKEY`, URLs, device id. A senha do auto-login fica no Windows. Nada disso é versionado (`.env*` está no `.gitignore`).
