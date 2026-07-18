from companion.runtime import runtime
from companion.plataform import notify, show_html

@runtime.register_tool("notify")
async def notify_handler(args : dict) -> str:
    return await notify(args.get("title", "Alerta"), args.get("message", ""))

@runtime.register_tool("display_page")
async def display_page_handler(args: dict) -> str:
    return await show_html(args["html"])