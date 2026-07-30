import orjson
from domain.contracts import LLMClient
from domain.tools.base import ToolRegistry
from application.services._trace import trace

_INSTR_PLAN = (
    "Você planeja QUAIS ferramentas o pedido do usuário exige, EM ORDEM de execução.\n"
    "- Liste SÓ as ferramentas EXPLICITAMENTE necessárias. NÃO adicione extras.\n"
    "- PODE repetir a mesma ferramenta se o pedido pedir a ação 2x (ex.: avisar duas coisas).\n"
    "- Conversa/pergunta que se responde falando → plano vazio [].\n"
    "\n"
    "Distinções (tools de device):\n"
    "- 'mostra/exibe MATEMÁTICA na tela' → display_math (uma PÁGINA). NÃO render_math nem open_image.\n"
    "- 'faz/mostra tabela/lista/card/resumo' → display_page (só ela).\n"
    "- 'gere/renderize a fórmula' (uma IMAGEM) → render_math; +notify se 'envie'; +open_image se 'abra'.\n"
    "- 'avisa/notifica' → notify. 'tira foto' → capture_image. 'abrir imagem que já existe' → open_image.\n"
    "\n"
    "Exemplos (pedido → plano):\n"
    "- \"mostra a matéria de derivadas na tela\" → [\"display_math\"]\n"
    "- \"faz uma tabela dos planos e mostra\" → [\"display_page\"]\n"
    "- \"renderiza bhaskara e abre em tela cheia\" → [\"render_math\", \"open_image\"]\n"
    "- \"gere a fórmula e envie pro celular\" → [\"render_math\", \"notify\"]\n"
    "- \"avisa que o deploy terminou\" → [\"notify\"]\n"
    "- \"oi, tudo bem?\" → []\n"
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
                "content": _INSTR_PLAN.format(tools=active.describe_for_router())
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
            trace(f"[router-agente] plano={plano}")
        except Exception: 
            return []
        return [t for t in plano if t in names]
        
    