import orjson
from domain.contracts import LLMClient
from application.services._trace import trace


_INSTR_DIVERGENCIA = (
        "Você é o juiz. O plano previa umas ferramentas; o modelo chamou uma FORA do plano.\n"
        "Decida se essa troca ENTREGA pro dono o mesmo resultado que o pedido exige — ou se foi erro.\n\n"
        "Ferramentas (o que cada uma faz / quando usar):\n{tools}\n\n"
        "Pedido do dono: {pedido}\n"
        "Ferramentas do PLANO ainda não executadas: {restante}\n"
        "O modelo chamou '{chamou}' (args: {args}), que NÃO está no plano.\n\n"
        "REGRAS:\n"
        "- aceita = true SÓ se '{chamou}' entrega pro dono o MESMO resultado que o pedido pede. "
        "Tocar no assunto não basta: se o dono quer algo MOSTRADO/ABERTO/ENVIADO e '{chamou}' apenas gera e "
        "GUARDA (não exibe, não envia), o dono não veria nada → é um DOWNGRADE → aceita = false.\n"
        "- IMAGEM ≠ PÁGINA. 'render_math' cria uma IMAGEM que fica GUARDADA (não aparece sozinha). "
        "'display_math' MOSTRA uma PÁGINA no navegador. Se o dono pediu pra MOSTRAR/ABRIR/VER matemática numa "
        "página/tela/navegador e o modelo chamou 'render_math', o dono NÃO veria nada → aceita = false "
        "(o plano tinha 'display_math', mantenha ele — NÃO substitua). O contrário PODE: 'display_math' já mostra, "
        "então cobre um plano que previa 'render_math'.\n"
        "- substitui = ferramentas do PLANO que '{chamou}' torna REDUNDANTES por fazer o MESMO papel COMPLETO. "
        "Nunca liste uma que '{chamou}' cobre só pela metade — essa continua no plano. [] se '{chamou}' só ADICIONA. "
        "Se aceita = false, substitui DEVE ser [].\n\n"
        "Exemplos:\n"
        "- pedido 'abre a matemática numa página no ubuntu', plano ['display_math'], chamou 'render_math' → "
        "{{\"aceita\": false, \"substitui\": []}}  (render_math não mostra; a página não apareceria)\n"
        "- pedido 'gera a fórmula, me mostra e me lembra de revisar', plano ['render_math','open_image','lembrar'], "
        "chamou 'display_math' → {{\"aceita\": true, \"substitui\": [\"render_math\", \"open_image\"]}}  "
        "(a página já mostra tudo; 'lembrar' continua pendente)\n\n"
        "Responda em JSON: {{\"aceita\": bool, \"substitui\": [nomes do plano]}}.")

_INSTR_OMISSAO = (
    "O modelo NÃO chamou nenhuma ferramenta; só escreveu um texto. Nenhuma ação aconteceu. "
    "Classifique o texto em RESPONDER (entrega ao dono e encerra) ou EXECUTAR (força a ferramenta que faltou).\n\n"
    "Texto do modelo: \"{texto}\"\n\n"
    "Decida NESTA ordem:\n"
    "1) O texto faz uma PERGUNTA ao dono (tem '?', pede decisão/permissão/confirmação/alternativa) "
    "OU ADMITE que NÃO deu ('não consegui', 'não foi possível', 'não abri/enviei/mostrei', 'deu erro', "
    "'falhou', 'offline', 'não encontrei', 'ilegível')? -> RESPONDER. "
    "Isso VENCE mesmo que o texto cite a ação ou ofereça alternativa — quem decide é o dono.\n"
    "2) SENÃO: o texto AFIRMA que a ação foi FEITA ('pronto, enviei', 'aqui está a foto', 'já mostrei/"
    "abri/anotei') ou só ANUNCIA que vai fazer ('vou capturar', 'agora envio') sem ter chamado? "
    "-> EXECUTAR (a tool não rodou, então é falso: force).\n\n"
    "Exemplos:\n"
    "  - 'não abri a imagem, o ubuntu está offline. abro em outro?' -> RESPONDER\n"
    "  - 'deu erro ao gerar a fórmula, tento de novo?' -> RESPONDER\n"
    "  - 'posso registrar isso na memória, confirma?' -> RESPONDER\n"
    "  - 'a foto ficou preta, não consegui ler' -> RESPONDER\n"
    "  - 'pronto, enviei a notificação!' -> EXECUTAR\n"
    "  - 'aqui está a foto que tirei' -> EXECUTAR\n"
    "  - 'já mostrei os exercícios na tela' -> EXECUTAR\n"
    "  - 'vou capturar e enviar' -> EXECUTAR"
)



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
        trace(f"[JUIZ (divergencia)] {data}")
        return bool(data.get("aceita")), [tool for tool in data.get("substitui", []) if tool in restante]
    
    async def classifica_omissao(self, pedido: str, texto: str, tools: str) -> str:
        if not (texto or "").strip():
            return "EXECUTAR"
        schema = {"type": "object", "required": ["decisao"],
                  "properties": {"decisao": {"type": "string", "enum": ["RESPONDER", "EXECUTAR"]}}}
        response = await self._llm.complete(
            messages=[{"role": "system", "content": _INSTR_OMISSAO.format(texto=texto)}],
            temperature=0.0,
            extra_body={"response_format": {"type": "json_schema",
                        "json_schema": {"name": "omissao", "schema": schema}}})
        decisao = orjson.loads(response.content or "{}").get("decisao", "EXECUTAR")
        trace(f"[JUIZ (omissao)] {decisao}")
        return decisao
    
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
        trace(f"[JUIZ (turno)] {txt}")
        return (not txt.upper().startswith("FALTOU"), txt)
        
    
    