import orjson
from domain.contracts import LLMClient
from application.services._trace import trace


_INSTR_DIVERGENCIA = (
    "O plano previa umas ferramentas; o modelo chamou uma FORA do plano. Decida se foi um bom movimento.\n\n"
    "Ferramentas (o que cada uma faz):\n{tools}\n\n"
    "Pedido do dono: {pedido}\n"
    "Ferramentas do PLANO ainda não executadas: {restante}\n"
    "O modelo chamou '{chamou}' (args: {args}), fora do plano.\n\n"
    "aceita = true se '{chamou}' AJUDA a atender o pedido, seja:\n"
    "  (a) um PASSO NECESSÁRIO antes de um do plano (ex.: gerar a imagem com render_math antes de notify/open_image), OU\n"
    "  (b) uma ferramenta que faz o trabalho pedido TÃO BEM OU MELHOR que a do plano (ex.: display_math MOSTRA "
    "a página no navegador, cobrindo render_math+open_image).\n"
    "aceita = false se '{chamou}' é a escolha ERRADA:\n"
    "  - DOWNGRADE: faz MENOS do que o pedido precisa. Ex.: o dono quer MOSTRAR/ABRIR matemática numa página "
    "(plano tem display_math) e o modelo chamou render_math, que só GERA uma imagem guardada e NÃO mostra — o dono não veria nada.\n"
    "  - ferramenta que NÃO serve o pedido (ex.: lembrar pra 'avisar'; capture_image pra 'olhar de novo' o que já existe), OU\n"
    "  - uma ação que o dono NÃO pediu.\n\n"
    "substitui = ferramentas do PLANO cujo trabalho '{chamou}' cobre POR COMPLETO (torna redundantes). "
    "[] se '{chamou}' só ADICIONA um passo (não cobre nenhuma). Se aceita=false, substitui=[].\n\n"
    "Exemplos:\n"
    "- pedido 'abre a matemática numa página', plano ['display_math'], chamou 'render_math' -> "
    "{{\"aceita\": false, \"substitui\": []}} (render só gera, não mostra; downgrade)\n"
    "- pedido 'gera a fórmula, me mostra e me lembra de revisar', plano ['render_math','open_image','lembrar'], "
    "chamou 'display_math' -> {{\"aceita\": true, \"substitui\": [\"render_math\",\"open_image\"]}} (a página mostra tudo; lembrar continua)\n"
    "- pedido 'manda a fórmula pro ubuntu', plano ['notify'], chamou 'render_math' -> "
    "{{\"aceita\": true, \"substitui\": []}} (precisa gerar a imagem antes de enviar; só adiciona)\n"
    "- pedido 'avisa o ubuntu', plano ['notify'], chamou 'lembrar' -> {{\"aceita\": false, \"substitui\": []}} (lembrar não avisa)\n"
    "- pedido 'abre a fórmula de bhaskara em tela cheia', plano ['open_image'], chamou 'render_math' -> "
    "{{\"aceita\": true, \"substitui\": []}} (a imagem não existe ainda; gera antes de abrir; só adiciona)\n"
    "- pedido 'mostra os exercícios de derivada pra resolver', plano ['display_math'], chamou 'display_page' -> "
    "{{\"aceita\": false, \"substitui\": []}} (display_page é HTML genérico e NÃO renderiza a matemática; downgrade)\n\n"
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



_INSTR_TURNO = (
    "Você confere se o agente cumpriu o pedido do dono, olhando o RESULTADO REAL de cada ferramenta.\n\n"
    "Ferramentas (o que cada uma faz):\n{tools}\n\n"
    "Pedido do dono: {pedido}\n"
    "Trajetória (ferramenta -> RESULTADO REAL):\n{trajetoria}\n"
    "Resposta final ao dono: {resposta}\n\n"
    "Quebre o pedido nas suas PARTES/alvos (ex.: 'mostra no ubuntu E avisa no celular' = 2 partes; "
    "'abre numa página' exige MOSTRAR, não só gerar). Julgue CADA parte pela trajetória.\n\n"
    "cumpriu = false (FALTOU) se qualquer um:\n"
    "  - uma parte foi PULADA em silêncio — sem NENHUMA tentativa dela na trajetória (ex.: pediu ubuntu E "
    "celular, mas só há tentativa pro ubuntu);\n"
    "  - a ferramenta usada NÃO faz o que o pedido pedia (ex.: render_math só GERA imagem guardada, não "
    "MOSTRA página; lembrar ANOTA na memória, não AVISA/notifica);\n"
    "  - a resposta AFIRMA algo que a trajetória NÃO confirma — esconde/mente a falha (diz 'enviei' mas o "
    "resultado foi [bloqueado]; descreve uma imagem sem ter capturado).\n"
    "cumpriu = true (CUMPRIU) se CADA parte foi: (i) atendida com sucesso real, OU (ii) TENTADA e falhou "
    "por motivo EXTERNO (device offline, câmera indisponível) COM a resposta relatando isso honestamente. "
    "Ou seja: falha externa + tentativa na trajetória + resposta sincera = CUMPRIU (o agente fez o que dava).\n\n"
    "Responda JSON: {{\"cumpriu\": bool, \"motivo\": \"1 linha: o que faltou/errou, ou 'ok'\"}}."
)

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
        schema = {"type":"object","required":["cumpriu","motivo"],
                  "properties":{"cumpriu":{"type":"boolean"},"motivo":{"type":"string"}}}
        response = await self._llm.complete(
            messages=[{"role":"system","content":_INSTR_TURNO.format(
                tools=tools, pedido=pedido, trajetoria=trajetoria, resposta=resposta)}],
            temperature=0.0,
            extra_body={"response_format":{"type":"json_schema","json_schema":{"name":"turno","schema":schema}}})
        data = orjson.loads(response.content or "{}")
        cumpriu = bool(data.get("cumpriu", True))
        trace(f"[JUIZ (turno)] cumpriu={cumpriu} · {data.get('motivo','')}")
        return (cumpriu, data.get("motivo",""))
        
    
    