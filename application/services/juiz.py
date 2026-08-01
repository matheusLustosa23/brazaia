import orjson
from domain.contracts import LLMClient
from application.services._trace import trace


_INSTR_DIVERGENCIA = (
        "Ferramentas (o que cada uma faz / quando usar):\n{tools}\n\n"
        "Pedido do dono: {pedido}\n"
        "Ferramentas do PLANO ainda não executadas: {restante}\n"
        "O modelo chamou '{chamou}' (args: {args}), que NÃO está no plano.\n"
        "Responda em JSON:\n"
        "- aceita: true se '{chamou}' atende BEM alguma parte do pedido; false se foi escolha errada.\n"
        "- substitui: lista das ferramentas do PLANO acima que '{chamou}' torna REDUNDANTES (faz o mesmo papel); "
        "[] se ela só ADICIONA (não cobre nenhuma do plano).")

_INSTR_OMISSAO = (
        "Ferramentas:\n{tools}\n\n"
        "Pedido do dono: {pedido}\n"
        "Faltava chamar uma ferramenta, mas o modelo só ESCREVEU (não chamou): {texto}\n"
        "RESPONDER = é pergunta/confirmação ao dono OU falha honesta (offline/não encontrado) → entrega o texto pro dono.\n"
        "EXECUTAR = entregou em prosa o que era AÇÃO, ou fingiu que fez → força a ferramenta.")


_INSTR_TURNO = ("Ferramentas (o que cada uma faz):\n{tools}\n\n"
        "Pedido do dono: {pedido}\n"
        "O agente executou (ferramenta → RESULTADO REAL):\n{trajetoria}\n"
        "Resposta final ao dono: {resposta}\n"
        "A trajetória CUMPRIU o pedido? Responda 'CUMPRIU' ou 'FALTOU: <o que faltou/errou, 1 linha>'.")


class Juiz:
    
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
    
    async def aceita_divergencia(
        self, 
        pedido: str, 
        tool_chamada: str, 
        args: dict, 
        restante: list[str], 
        tools: str
    ) -> tuple[bool, list[str]]:
        schema = {
            "type":"object",
            "required":[
                "aceita",
                "substitui"
            ],
            "properties":{
                "aceita": {
                    "type":"boolean"
                },
                "substitui": {
                    "type":"array",
                    "items":{
                        "type":"string",
                        "enum":restante
                    }
                }
            }
        }
        resposta = await self._llm.complete(
            messages=[
                {
                    "role":"system",
                    "content":_INSTR_DIVERGENCIA.format(
                        tools=tools, 
                        pedido=pedido, 
                        chamou=tool_chamada, 
                        args=args,
                        restante=restante
                    )
                }
            ],
            temperature=0.0,
            extra_body={
               "response_format":{
                   "type":"json_schema",
                   "json_schema":{
                       "name":"veredito",
                       "schema":schema
                    }
               }
            }
        )
        data = orjson.loads(resposta.content or "{}")
        trace(f"[JUIZ] {data}")
        return bool(data.get("aceita")), [tool for tool in data.get("substitui", []) if tool in restante]
    
    async def classifica_omissao(self, pedido: str, texto: str, tools: str) -> str:
        if not (texto or "").strip():
            return "EXECUTAR"
        response = await self._llm.complete(
            messages=[
                {
                    "role":"system",
                    "content":_INSTR_OMISSAO.format(
                        tools=tools, 
                        pedido=pedido, 
                        texto=texto
                    )
                }
            ],
            temperature=0.0,
            extra_body={
                "guided_choice":[
                    "RESPONDER",
                    "EXECUTAR"
                ]
            }
        )
        return (response.content or "").strip().upper()
    
    async def finalizou_turno(self, pedido: str, trajetoria: str, resposta: str, tools: str) -> tuple[bool, str]:
        response = await self._llm.complete(
            messages=[
                {
                    "role":"system",
                    "content":_INSTR_TURNO.format(
                        tools=tools, 
                        pedido=pedido, 
                        trajetoria=trajetoria, 
                        resposta=resposta
                    )
                }
            ],
            temperature=0.0
        )
        txt = (response.content or "").strip()
        trace(f"[JUIZ] {txt}")
        return (not txt.upper().startswith("FALTOU"), txt)
        
    
    