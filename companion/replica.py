"""python -m companion replica — RÉPLICA no tutor: manda o mesmo pedido de estudo pro AGENTE em modo tutor.

Fluxo combinado (desde 27/10/2026): tudo que for gerado nos estudos é replicado no tutor, do jeito que o aluno
pediria (informal, curto — nunca uma especificação pronta), pra comparar e ver onde o prompt precisa de reforço.
Agora a réplica roda no agente de verdade (tools, sessão, artefatos): fica numa sessão com título e etiqueta
"replica", que o dono abre depois no CLI (/sessoes replica → /sessao N → /arquivos → /abrir N).

Uso:
  python -m companion replica --titulo "réplica · Projeto Ágil T1" "me explica o manifesto ágil do zero"
  python -m companion replica --sessao <id> "agora faz o deck ilustrado desse tema"   # continua a mesma réplica
  python -m companion replica --lista                                               # réplicas recentes
  python -m companion replica --baixar <id> [--para PASTA]                          # baixa os artefatos (comparar)
Opções: --think liga o raciocínio (padrão: desligado, igual ao uso normal).
"""
import argparse, asyncio, os, sys, time

from companion.config import load_config
from companion.chat_client import chat_stream, listar_sessoes, listar_arquivos, baixar_arquivo

TAG = "replica"
DEVICE = "replica"            # device sem conexão → só tools de servidor (gera artefato, não abre em nenhuma tela)


async def _rodar(cfg, pedido: str, sessao: str | None, titulo: str | None, think: bool) -> str | None:
    sid, t0, resposta = sessao, time.monotonic(), []
    print(f"🫵 {pedido}\n", flush=True)
    async for ev in chat_stream(pedido, sessao, cfg, think=think, modo="tutor",
                                titulo=titulo if not sessao else None, tags=[TAG] if not sessao else None):
        if "session_id" in ev:
            sid = ev["session_id"]
        elif ev.get("evento") == "passo":
            desc = ev.get("porque") or ev.get("tool")
            if ev.get("estado") == "executando":
                print(f"  ▸ {desc}", flush=True)
            else:
                print(f"  {'✔' if ev.get('estado') == 'ok' else '✗'} {desc} → {str(ev.get('detalhe', ''))[:100]}", flush=True)
        elif ev.get("evento") == "tool_args":                       # tool sendo montada (também tem "delta")
            continue
        elif "delta" in ev and not ev.get("think") and "evento" not in ev:
            resposta.append(ev["delta"])
        elif ev.get("success") is False or "error" in ev:
            print(f"⚠ erro do servidor: {ev.get('message') or ev.get('error')}", flush=True)
    texto = "".join(resposta).strip()
    print("\n🤖 " + (texto or "(sem texto — veja os passos e os arquivos)"))
    print(f"\n— {time.monotonic() - t0:.0f}s · sessão {sid}")
    if sid:
        for a in await listar_arquivos(cfg, sid):
            print(f"  📄 {a['file_id']} · {a.get('ext')} · {a.get('title') or ''} ({a.get('bytes', 0) // 1024} KB)")
    return sid


async def _lista(cfg) -> None:
    for s in (await listar_sessoes(cfg, TAG))[:20]:
        quando = time.strftime("%d/%m %H:%M", time.localtime(s.get("updated_at") or 0))
        print(f"{s['session_id']} · {quando} · {s.get('turnos', 0)} turnos · {s.get('titulo') or s.get('preview', '')}")


async def _baixar(cfg, sid: str, pasta: str) -> None:
    os.makedirs(pasta, exist_ok=True)
    for a in await listar_arquivos(cfg, sid):
        dados, nome = await baixar_arquivo(cfg, a["file_id"])
        destino = os.path.join(pasta, f"{a['file_id']}_{nome}")
        with open(destino, "wb") as f:
            f.write(dados)
        print(f"  ⬇ {destino} ({len(dados) // 1024} KB)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m companion replica", description="Réplica no tutor (agente em modo tutor).")
    ap.add_argument("pedido", nargs="?", help="o pedido, do jeito que o aluno pediria")
    ap.add_argument("--titulo", help='nome da sessão (ex.: "réplica · Projeto Ágil T1")')
    ap.add_argument("--sessao", help="continua uma réplica existente (session_id)")
    ap.add_argument("--lista", action="store_true", help="lista as réplicas recentes")
    ap.add_argument("--baixar", metavar="SESSAO", help="baixa os artefatos de uma réplica")
    ap.add_argument("--para", default=os.path.expanduser("~/estudos/_teste-tutor/agente"), help="pasta do --baixar")
    ap.add_argument("--think", action="store_true", help="liga o raciocínio do modelo")
    a = ap.parse_args()
    os.environ.setdefault("DEVICE_ID", DEVICE)
    cfg = load_config()
    cfg.device_id = DEVICE
    if a.lista:
        asyncio.run(_lista(cfg))
    elif a.baixar:
        asyncio.run(_baixar(cfg, a.baixar, a.para))
    elif a.pedido:
        if not a.sessao and not a.titulo:
            ap.error('réplica nova precisa de --titulo (ex.: --titulo "réplica · Projeto Ágil T1")')
        asyncio.run(_rodar(cfg, a.pedido, a.sessao, a.titulo, a.think))
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
