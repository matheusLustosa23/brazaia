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
    "- 'mostra/abre/vê MATEMÁTICA no navegador/tela/página pra ler/resolver/estudar' → display_math "
    "(uma PÁGINA). ÚNICA pra matemática em página — NUNCA display_page nem render_math+open_image.\n"
    "- 'gera/renderiza a fórmula como IMAGEM' → render_math; +notify se 'envie/manda'; "
    "+open_image SÓ se 'abre a IMAGEM em tela cheia'.\n"
    "- 'faz/mostra tabela/lista/card/resumo' (genérico, sem matemática) → display_page.\n"
    "- ANALISAR/VERIFICAR/CONFERIR/OLHAR a câmera ou uma resolução/foto → capture_image (foto nova) "
    "ou load_image (re-olhar a última). NUNCA display_math/display_page — analisar ≠ mostrar.\n"
    "- 'avisa/notifica' → notify. 'tira foto' → capture_image. 'abrir uma imagem que já existe' → open_image.\n"
    "- Matemática, escolha UM caminho: IMAGEM = render_math (+notify se 'envie', +open_image se 'abre a imagem'); "
    "PÁGINA = display_math SOZINHA (navegador/tela/ler/resolver). NUNCA render_math + display_math juntos.\n"
    "\n"
    "Exemplos (pedido → plano):\n"
    "- \"mostra a matéria de derivadas na tela\" → [\"display_math\"]\n"
    "- \"preciso de um problema de matemática no navegador do celular\" → [\"display_math\"]\n"
    "- \"gere um problema de matemática e abre em uma página no ubuntu\" → [\"display_math\"]\n"
    "- \"renderize um exercício de matemática em uma página no navegador\" → [\"display_math\"]\n"
    "- \"faz uma tabela dos planos e mostra\" → [\"display_page\"]\n"
    "- \"gera bhaskara e abre a IMAGEM em tela cheia\" → [\"render_math\", \"open_image\"]\n"
    "- \"gere a fórmula e envie pro celular\" → [\"render_math\", \"notify\"]\n"
    "- \"olha a câmera do celular e vê se minha resolução está certa\" → [\"capture_image\"]\n"
    "- \"analise de novo a imagem / a resposta não foi essa\" → [\"load_image\"]\n"
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
        
    