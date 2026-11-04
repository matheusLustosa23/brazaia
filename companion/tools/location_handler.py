import asyncio

from companion._json import dumps
from companion.localizacao import ler_estado, ler_localizacao
from companion.runtime import runtime


@runtime.register_tool("get_location")
async def get_location_handler(args: dict) -> str:
    """Pedido do server (get_location): leitura PRECISA agora. Ponto → JSON; falha → '[erro] motivo'."""
    r = await asyncio.to_thread(ler_localizacao, True)
    return dumps(r) if isinstance(r, dict) else f"[erro] {r}"


@runtime.register_tool("get_estado")
async def get_estado_handler(args: dict) -> str:
    return dumps(await asyncio.to_thread(ler_estado))
