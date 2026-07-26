# Companion (brazaia)

Cliente de dispositivo do brazaia — **captura voz e reproduz a resposta**. É **I/O puro**: o
**server** processa tudo (decodifica → ASR → LLM → TTS). Roda no **desktop** (sounddevice) e no
**Termux/Android** (CLI do Termux:API, sem ffmpeg/sounddevice).

## Provisionamento do zero — Termux (celular novo)

```bash
# 1) libs de sistema — SÓ o que o companion usa (nada do server)
pkg update -y && pkg install -y python termux-api git

# 2) apps no F-Droid: Termux · Termux:API · Termux:Widget

# 3) clonar (repo privado → git pede login/token do GitHub)
cd ~ && git clone https://github.com/matheusLustosa23/brazaia.git brazaia
cd ~/brazaia

# 4) deps Python do COMPANION — SÓ isto.  NÃO rode 'pip install .' nem 'uv sync'
#    (esses puxam o server: fastapi, torch, faster-whisper, vllm… — nada disso vai pro celular)
pip install -r companion/requirements-termux.txt        # = websockets

# 5) setup do companion: atalho do widget + ícone + canal + template ~/.brazaia.env
python -m companion.setup

# 6) apontar pro server
nano ~/.brazaia.env          # confira SERVER_WS_URL e DEVICE_ID
```

Depois: **arrastar o widget "Fala Comigo" na home 1×** + conceder permissões (**microfone** /
**sobrepor a outras telas**).

> **Só do companion:** os únicos pacotes são `python termux-api git` (sistema) + `websockets` (pip).
> **Nada** do server. Os passos finais (login no clone, fixar widget, permissões) são o mínimo
> irredutível — gestos que nenhum app automatiza (trava do Android/GitHub).

**Atualizar depois:** `cd ~/brazaia && git pull` (+ `python -m companion.setup` se mudou atalho/ícone).

## Provisionamento — Desktop (Linux/Windows)

```bash
uv sync
python -m companion.voice           # wake word ("braza")
python -m companion.voice turn      # um turno único
```

## Configuração

No **Termux** fica em `~/.brazaia.env` (o `gravador.sh` faz `source`); no **desktop**, variáveis de
ambiente. Fora do repo (valor por-dispositivo).

| variável | o quê |
|---|---|
| `SERVER_WS_URL` | base do WS do server — ex.: `ws://100.79.27.100:8080/api/v1` (**sem** `/ws/...`) |
| `DEVICE_ID` / `DEVICE_NAME` | identidade do dispositivo |
| `DEVICE_TOKEN` | token de auth (opcional) |
