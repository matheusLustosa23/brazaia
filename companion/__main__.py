"""python -m companion — entrada ÚNICA do companion: abre o CLI (chat) com o device conectado em segundo plano.

Dentro do CLI:  /voz (fala vira texto no input) · /live [fone] (painel de voz, conversa falada na MESMA sessão)

Uso:
  python -m companion [--device NOME]        CLI (chat + device + voz + live)
  python -m companion connect [--fg|status|stop|--watch]
                                             só o device, sem chat (= python -m companion.connect)
  python -m companion voz [stream|wake|once] voz no terminal sem painel (= python -m companion.voice)
  python -m companion replica …              réplica no tutor: o pedido de estudo vai pro agente em modo tutor
  python -m companion permissoes [ver]       pede/testa as permissões do device uma vez (câmera, mic, localização…)
  python -m companion localizacao [teste|coletar|fila]   lê a posição/bateria; coletar = o que roda de 15 em 15 min
  python -m companion acervo add ARQUIVO…    manda PDF/Word/PowerPoint/MD pro acervo (o agente passa a consultar)

O companion de FUNDO do server sobe com `python -m companion.connect --fg` (ops/subir_companion.sh): o braza
procura esse nome na linha de comando, então ele continua com o módulo explícito.
"""
import os, runpy, sys


def _uso() -> None:
    print((__doc__ or "").split("Uso:")[1].split("O companion de FUNDO")[0].rstrip())


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        _uso(); return
    if args and args[0] in ("connect", "voz", "replica", "permissoes", "localizacao", "acervo"):   # delega pro módulo
        modulo = {"connect": "companion.connect", "voz": "companion.voice", "replica": "companion.replica",
                  "permissoes": "companion.permissoes", "localizacao": "companion.localizacao",
                  "acervo": "companion.acervo"}[args[0]]
        sys.argv = [modulo] + args[1:]
        runpy.run_module(modulo, run_name="__main__", alter_sys=True)
        return
    i = 0
    while i < len(args):                                           # CLI: --device NOME / -d NOME
        if args[i] in ("--device", "-d") and i + 1 < len(args):
            os.environ["DEVICE_ID"] = os.environ["DEVICE_NAME"] = args[i + 1]; i += 2
            os.environ["BRAZA_DEVICE_EXPLICITO"] = "1"             # nome próprio → o CLI conecta como device separado
        else:
            print(f"argumento desconhecido: {args[i]}"); _uso(); sys.exit(2)
    import asyncio
    from companion.cli import main as cli_main
    asyncio.run(cli_main())


if __name__ == "__main__":
    main()
