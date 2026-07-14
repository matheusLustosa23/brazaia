import asyncio
from companion.runtime import runtime
from companion.plataform import notify

@runtime.register_tool("notify")
async def notify_handler(args : dict) -> str:
    return await asyncio.to_thread(notify, args.get("title","Alerta"), args.get("message",""))