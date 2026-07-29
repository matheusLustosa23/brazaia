"""Bancada de estratégia de tool-calling. Pra cada frase, no caminho REAL da voz (com VOICE_STYLE),
compara LADO A LADO 3 estratégias de aproveitar o router:

  auto        → o LLM decide sozinho (tool_choice=auto)
  auto+hint   → injeta a decisão do router como DICA (soft) + auto  → preserva o julgamento
  required    → força a chamada (tool_choice=required)              → cego pro contexto

Router (guided_choice temp0) é a referência. '·'=bate com o router · 'x'=diverge.
Mede a DECISÃO via `complete` (não executa tools). open_image/load_image recebem AMBIENTE
preparado (um image_id semeado no histórico), senão o LLM recusa certo (não há o que abrir).

Uso:
    uv run python scripts/medir_toolcall.py                     # set inteiro (todas as tools)
    uv run python scripts/medir_toolcall.py "tira uma foto"     # só essa frase
    uv run python scripts/medir_toolcall.py "renderiza x" 6     # N=6
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import get_settings
from infrastructure.llm.client import OpenAILLMClient
from infrastructure.llm import tokenizer
from application.services.context_service import ContextManager
from application.services.orchestrator import Orchestrator
from application.services.voice_service import VOICE_STYLE
from application.services.memory_service import MemoryService
from application.services.device_service import DeviceService
from domain.tools.base import ToolRegistry
from infrastructure.memory.sqlite_store import SqlLiteMemoryStore
from infrastructure.memory.session_store import SqlLiteSessionStore
from infrastructure.vision.sources import VisionRegistry, WebCam
from infrastructure.vision.image_index import ImageIndex
from infrastructure.devices.device_registry import SqlLiteDeviceRegistry
from infrastructure.devices.device_connection import DeviceConnectionManager
from infrastructure.devices.device_rpc import DeviceRPCManager
from infrastructure.devices.device_gateway import DeviceGateway
from application.tools.lembrar import LembrarTool
from infrastructure.tools.capture_image import CaptureImageTool
from infrastructure.tools.load_imagem import LoadImageTool
from infrastructure.tools.display_math import DisplayMathTool
from infrastructure.tools.display_page import DisplayPageTool
from infrastructure.tools.render_math import RenderMathTool
from infrastructure.tools.notify import NotifyTool
from infrastructure.tools.open_image import OpenImageTool

# (frase, precisa_de_imagem_no_contexto). Comentário = tool alvo.
_TESTS = [
    ("renderiza um problema de equação aleatório", False),        # render_math
    ("tira uma foto e me manda", False),                          # capture_image
    ("anota que amanhã tenho médico às 3", False),                # lembrar
    ("abre a última foto em tela cheia no celular", True),        # open_image (precisa de id)
    ("avisa no celular que o build terminou", False),             # notify
    ("mostra a matéria de cálculo na tela pra eu resolver", False),  # display_math
    ("faz uma tabela dos planos e mostra no celular", False),     # display_page
    ("olha de novo aquela imagem que apareceu antes", True),      # load_image (precisa de id)
    ("oi, tudo bem?", False),                                     # NENHUMA
    ("que horas são?", False),                                    # NENHUMA
    ("me fala as novidades", False),                              # NENHUMA
]

# Ambiente preparado p/ open_image/load_image: um image_id REAL já na conversa.
_SEED = [
    {"role": "user", "content": "renderiza a fórmula de bhaskara"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call_seed", "type": "function",
         "function": {"name": "render_math", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "call_seed",
     "content": "imagem pronta (image_id=abc123def456). Use em 'notify' ou 'open_image'."},
]

_HINTS = {
    "lembrar": "anotar, guardar ou lembrar um fato, preferência ou config do dono",
    "capture_image": "ver/olhar pela câmera agora, tirar foto, o que estou vendo ou tem na minha frente",
    "load_image": "rever/olhar de novo uma imagem que já apareceu antes nesta conversa",
    "display_math": "mostrar/abrir matemática numa página na tela do device (pra resolver, ler a matéria)",
    "display_page": "montar/mostrar uma página no device: tabela, lista, card, resumo, dashboard",
    "render_math": "gerar/renderizar qualquer conteúdo matemático (equação, expressão, matriz, integral, "
                   "derivada, sistema) como imagem — ainda sem enviar",
    "notify": "notificar, avisar ou mandar um aviso/imagem pra tela do celular",
    "open_image": "abrir uma imagem em tela cheia no device (zoom, ler com calma)",
}
_ROUTER_INSTR = (
    "Você roteia a fala do usuário para UMA ferramenta, ou NENHUMA se for conversa/"
    "pergunta que se responde falando (saudação, novidades, horas, sentimento, opinião).\n"
    "Ferramentas:\n{tools}\nResponda SÓ com o rótulo (nome exato) ou NENHUMA."
)

_DELAY = 0.6         # segundos entre chamadas — gentil com o backend de grammar do vLLM (xgrammar)
_PROMPT_PAUSE = 2.0  # respiro entre frases — deixa o engine assentar
_MAX_TOKENS = 1024   # CAP anti-runaway, mas alto o bastante pro JSON do tool_call caber inteiro.
                     # 200 truncava args grandes (LaTeX/HTML) → JSON quebrado → parser falha → lê "prosa".
                     # 1024 cabe qualquer tool_call e ainda é MUITO abaixo do runaway (~15k) que estourava o vLLM.


def _build():
    s = get_settings()
    s.llm_timeout_s = 600   # bancada paciente: espera o llm responder, sem pressa (vLLM lento não vira timeout)
    llm = OpenAILLMClient(s)
    context = ContextManager(
        budget=s.max_context_tokens, reserved_output=s.reserved_output_tokens,
        count_tokens=lambda m: tokenizer.count_tokens(m, s.model_name), llm=llm,
    )
    memory = MemoryService(SqlLiteMemoryStore(s.memory_db_path))
    session_store = SqlLiteSessionStore(s.session_db_path)
    vision = VisionRegistry(); vision.register(WebCam())
    image_index = ImageIndex()
    registry = ToolRegistry()
    device_registry = SqlLiteDeviceRegistry(s.device_db_path)
    device_service = DeviceService(device_registry, registry)
    device_gateway = DeviceGateway(
        DeviceConnectionManager(), DeviceRPCManager(s.device_ws_timeout), device_service)
    registry.register(LembrarTool(memory))
    registry.register(CaptureImageTool(vision))
    registry.register(LoadImageTool(image_index))
    registry.register(DisplayMathTool(device_gateway))
    registry.register(DisplayPageTool(device_gateway))
    registry.register(RenderMathTool(image_index))
    registry.register(NotifyTool(device_gateway, image_index))
    registry.register(OpenImageTool(device_gateway, image_index))
    orch = Orchestrator(
        llm=llm, context=context, tools=registry, memory=memory,
        device_gateway=device_gateway, session_store=session_store, image_index=image_index)
    return llm, context, registry, orch


async def _router(llm, active, prompt: str) -> str:
    names = active.get_all_tool_names()
    tools_txt = "\n".join(f"- {n}: {_HINTS[n]}" for n in names)
    msgs = [{"role": "system", "content": _ROUTER_INSTR.format(tools=tools_txt)},
            {"role": "user", "content": prompt}]
    try:
        comp = await llm.complete(msgs, temperature=0.0, max_tokens=16,
                                  extra_body={"guided_choice": names + ["NENHUMA"]})
    except Exception:
        return "erro"
    label = (comp.content or "").strip()
    return label if label in names else "NENHUMA"


async def _call(llm, messages, tools, tool_choice: str) -> str:
    """Resiliente: um timeout/erro transitório do vLLM vira 'erro' e não derruba o run inteiro."""
    try:
        comp = await llm.complete(messages, tools=tools, tool_choice=tool_choice, max_tokens=_MAX_TOKENS)
    except Exception:
        return "erro"
    tcs = getattr(comp, "tool_calls", None)
    return tcs[0].name if tcs else "prosa"


def _ok(choice: str, r: str) -> bool:
    return (choice == r) or (r == "NENHUMA" and choice == "prosa")


def _cell(choice: str, r: str) -> str:
    return f"{choice:<13}{'·' if _ok(choice, r) else 'x'}"


def _print_resumo(resumo: list[tuple], n: int) -> None:
    print("\n===== RESUMO (bate com router / N) =====")
    print(f"{'prompt':<40} {'router':>13} {'SEM vs':>7} {'COM vs':>7} {'required':>9}")
    print("─" * 82)
    for prompt, r, ss, sc, sr in resumo:
        print(f"{prompt[:40]:<40} {r:>13} {ss:>7} {sc:>7} {sr:>9}")


async def medir(prompts: list[tuple[str, bool]], n: int, start: int = 1) -> None:
    llm, context, registry, orch = _build()
    active = registry.for_device(None)
    tools = active.as_openai_tools()
    sys_sem = orch._system_prompt()                 # SEM voice_style
    sys_com = sys_sem + "\n\n" + VOICE_STYLE         # COM voice_style (caminho REAL da voz)

    total = len(prompts)
    print(f"N={n} · {total} frases · delay {_DELAY}s · '·'=bate com router 'x'=diverge · começando na frase {start}")
    print("colunas: [auto SEM voice_style]  [auto COM voice_style]  [required (com VS)]\n")
    resumo: list[tuple] = []
    dead = 0   # erros consecutivos → detecta vLLM caído

    for idx, (prompt, needs_img) in enumerate(prompts, 1):
        if idx < start:
            continue
        r = await _router(llm, active, prompt)
        history = _SEED if needs_img else []
        base_sem = context.build(sys_sem, "", history, {"role": "user", "content": prompt})
        base_com = context.build(sys_com, "", history, {"role": "user", "content": prompt})
        is_tool = r != "NENHUMA"

        tag = "  [env: img semeada]" if needs_img else ""
        print(f'=== [{idx}/{total}] "{prompt}"   router → {r}{tag}')
        print(f"   {'#':>2}  {'auto SEM vs':<15} {'auto COM vs':<15} {'required':<15}")
        os_ = oc = orr = 0
        for i in range(1, n + 1):
            ls = await _call(llm, base_sem, tools, "auto")
            lc = await _call(llm, base_com, tools, "auto")
            lr = await _call(llm, base_com, tools, "required") if is_tool else "—"
            for x in (ls, lc, lr):
                dead = dead + 1 if x == "erro" else 0
            if dead >= 6:
                print(f"\n⚠ vLLM parece ter CAÍDO (6+ erros seguidos) na frase [{idx}].")
                print(f"   Reinicie o vLLM e RETOME daqui (não repete 1-{idx-1}):")
                print(f"   FROM={idx} uv run python scripts/medir_toolcall.py {n}\n")
                _print_resumo(resumo, n)
                return
            os_ += _ok(ls, r)
            oc += _ok(lc, r)
            orr += _ok(lr, r) if is_tool else 0
            cr = _cell(lr, r) if is_tool else "—"
            print(f"   {i:>2}  {_cell(ls, r)} {_cell(lc, r):<15} {cr}", flush=True)
            await asyncio.sleep(_DELAY)   # gentil com o xgrammar
        s_req = f"{orr}/{n}" if is_tool else "—"
        print(f"   → SEM vs {os_}/{n} · COM vs {oc}/{n} · required {s_req}\n", flush=True)
        resumo.append((prompt, r, f"{os_}/{n}", f"{oc}/{n}", s_req))
        await asyncio.sleep(_PROMPT_PAUSE)   # respiro entre frases

    _print_resumo(resumo, n)


if __name__ == "__main__":
    args = sys.argv[1:]
    prompts = [(args[0], False)] if args and not args[0].isdigit() else _TESTS
    n = next((int(a) for a in args if a.isdigit()), 10)
    start = int(os.getenv("FROM", "1"))   # retomar após queda: FROM=5 uv run ...
    asyncio.run(medir(prompts, n, start))
