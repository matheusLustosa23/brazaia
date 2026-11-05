"""Gera o KIT de um device novo + o bloco pra colar no Termux (instala do zero com um comando).

  python ops/companion_kit.py --device S25 --nome "Celular 2" --ts-key tskey-auth-...   [--servidor 100.79.27.100:8080]

Por enquanto a auth-key do Tailscale é criada à mão (admin do Tailscale: single-use, pré-autorizada, expira em
pouco tempo, com tag). Na fase de identidade o PAINEL gera a chave pela API (escopo mínimo) e mostra este bloco.
O bloco contém a chave: trate como segredo (não cole em chat/log).
"""
import argparse
import base64
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--device", required=True)
ap.add_argument("--nome", required=True)
ap.add_argument("--ts-key", required=True)
ap.add_argument("--servidor", default="100.79.27.100:8080")
a = ap.parse_args()
kit = base64.urlsafe_b64encode(json.dumps({"servidor": a.servidor, "device_id": a.device, "device_name": a.nome,
                                           "ts_authkey": a.ts_key}).encode()).decode().rstrip("=")
script = (Path(__file__).resolve().parents[1] / "companion" / "boot" / "instalar.sh").read_bytes().replace(b"\r\n", b"\n")
# UMA linha só, com o script em base64: copiar várias linhas do terminal do Windows pode trazer CRLF, e o bash
# do Termux quebra com \r (o heredoc nem fecha). Base64 não tem quebra de linha nem acento → cola igual em qualquer lugar.
b64 = base64.b64encode(script).decode()
print("# cole a linha abaixo no Termux do device novo (depois de: pkg update -y && pkg upgrade -y)")
print(f"echo {b64} | base64 -d > ~/instalar.sh && bash ~/instalar.sh {kit}")
