from typing import Callable, Awaitable

class CompanionRuntime:
    """Encapsula o mapa de execução local de ferramentas. Elimina o estado global mutável."""
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict], Awaitable[str]]] = {}
    
    def register_tool(self, name: str):
       """Decorator acoplado à instância para auto-discovery de plugins."""
       def decorator(fn: Callable[[dict], Awaitable[str]]):
           self._handlers[name] = fn
           return fn
       
       return decorator
   
    async def execute(self, action: dict) -> str:
       """Despacha a execução para o handler correspondente."""
       name = action.get("name","")
       args = action.get("arguments", {})
       
       handler = self._handlers.get(name)
       if not handler:
           return f"[erro companion] handler '{name}' não registrado localmente."
       
       try:
           return await handler(args)
       except Exception as e:
           return f"[erro execução local] {type(e).__name__}: {e}"
       
    def list_tools(self) -> list[str]:
        return list(self._handlers.keys())

runtime = CompanionRuntime()