#!/usr/bin/env bash
# ops/subir_27b.sh — sobe o vLLM no WSL (cudagraph via --max-num-seqs 1) + reset seguro da GPU + log.
# EXEMPLO preenchido: ajuste model/paths/GPU/util pro seu caso. Rodado pelo servico vllm.service.
# Passo a passo em ops/README.md. ⚠️ Conferir contra o ~/subir_27b.sh do WSL (fonte de verdade).
set -e

# offline (evita tentativas de rede do HF)
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1
export PYTHONUNBUFFERED=1

# GPU + flashinfer — o systemd NAO le o .bashrc, entao o env vai aqui:
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0            # vLLM SEMPRE na 3090 (GPU 0)
export VLLM_USE_FLASHINFER_SAMPLER=0     # sampler PyTorch — evita o JIT do flashinfer (erro FlagHeads)
# ⚠️ NAO exportar PYTORCH_CUDA_ALLOC_CONF=expandable_segments — quebra o repack Marlin (device not ready)

source ~/projetos/iobraza/.venv/bin/activate

# mata instancia antiga e ESPERA a GPU liberar de verdade (evita 'device not ready')
pkill -9 -f vllm || true; pkill -9 -f EngineCore || true
for i in $(seq 1 30); do
  u=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
  echo "GPU em uso: ${u} MiB"
  [ "$u" -lt 500 ] && break
  sleep 2
done

# sobe (SEM --enforce-eager -> cudagraph ligado; --max-num-seqs 1 mantem a captura pequena)
vllm serve ~/models/qwen35-27b-abl-mtp \
  --served-model-name qwen35-27b-abl \
  --kv-cache-dtype fp8 \
  --max-model-len 48000 --max-num-seqs 1 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --gpu-memory-utilization 0.94 \
  --enable-prefix-caching \
  --chat-template ~/models/qwen35-27b-abl-mtp/chat_template.jinja \
  --limit-mm-per-prompt '{"image": 4}' \
  --host 0.0.0.0 --port 8002 \
  2>&1 | tee ~/vllm_27b.log
