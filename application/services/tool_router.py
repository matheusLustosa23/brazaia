import orjson
from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry

_INSTR_PLAN = (
    "Você planeja QUAIS ferramentas o pedido do usuário exige, EM ORDEM de execução.\n"
    "- Liste todas as necessárias, na ordem certa (gerar antes de enviar).\n"
    "- PODE repetir a mesma ferramenta se o pedido pedir a ação 2x (ex.: avisar duas coisas).\n"
    "- Conversa/pergunta que se responde falando → plano vazio [].\n"
    "Ferramentas:\n{tools}"
)

class ToolRouter:
    """Planner upfront: pedido → lista ORDENADA de tools (guided JSON). Degrada p/ [] em erro."""
    
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        
    async def plan(self, user_message: str, active: ToolRegistry) -> list[str]:
        
        names = active.get_all_tool_names()
        
        schema = {
            "type": "object",
            "properties": {
                "plano": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": names
                    },
                    "maxItems": 10
                }
            }
        }
        
        messages = [
            {
                "role": "system", 
                "content": _INSTR_PLAN.format(tools=active.as_openai_tools())
            },
            {
                "role": "user",
                "content": user_message
            }
        ]
        try:
            response = await self._llm.complete(
                messages=messages,
                temperature=0.0,
                extra_body = {
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "plano",
                            "schema": schema
                        }
                    }
                }
            )
            plano = orjson.loads(response.content or "{}").get("plano", [])
            print(f"[router-agente] {plano}")
        except Exception: 
            return []
        return [t for t in plano if t in names]
        
    