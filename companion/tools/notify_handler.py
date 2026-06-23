from companion.runtime import runtime

@runtime.register_tool("notify")
async def notify_handler(args : dict) -> str:
    """Executa chamadas do sistema nativo de notificações."""
    title = args.get("title", "Alerta")
    message = args.get("message", "")

    print(f"🔔 [NOTIFICAÇÃO SISTEMA] {title}: {message}")
    return f"Sucesso: Notificação disparada no device para: {title}"