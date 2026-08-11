import orjson
from domain.contracts import LLMClient
from application.services._trace import trace


_INSTR_DIVERGENCIA = (
    "O plano previa ferramentas — cada slot tem um id, a tool e o PORQUÊ dela. O modelo chamou uma FORA do plano, também com um porquê. Julgue.\n\n"
    "Ferramentas (o que cada uma faz):\n{tools}\n\n"
    "RESTRIÇÕES das ferramentas (respeite ao julgar e ao sugerir proxima_tool):\n"
    "  - display_page NÃO renderiza LaTeX/fórmula — é só pra páginas/tabelas de TEXTO. Conteúdo com fórmula "
    "($…$, \\frac, \\sqrt, etc.) vai em display_math. NUNCA sugira display_page pra fórmula.\n"
    "  - render_math só GERA a imagem da fórmula (devolve image_id); NÃO mostra em device. Pra exibir, é open_image/display_math.\n"
    "  - display_math MOSTRA a fórmula (LaTeX) na tela do device.\n\n"
    "Pedido do dono: {pedido}\n"
    "Plano ainda não executado (id · tool ← por que estava no plano):\n{restante_rotulado}\n"
    "O modelo chamou '{chamou}' (args: {args})\n"
    "  porque, nas palavras dele: \"{porque_llm}\"\n\n"
    "aceita = true se '{chamou}' AJUDA o pedido: passo necessário antes de um do plano, OU faz o trabalho tão bem/melhor. "
    "false se é downgrade (faz menos), tool errada, ou ação não pedida.\n"
    "substitui = a lista dos IDs (o número em [id=N]) dos slots que '{chamou}' cobre por completo. "
    "RACIOCINE pelo PORQUÊ de cada slot, mas RESPONDA com o id. Inclua um id SÓ se o alvo/intenção é o MESMO do '{chamou}'; "
    "NUNCA o id de um slot de OUTRO alvo (outra imagem, outro device), mesmo que a tool tenha o mesmo nome. "
    "[] se '{chamou}' só adiciona. Se aceita=false, substitui=[].\n\n"
    "IMPORTANTE: 'aceita' e 'substitui' são INDEPENDENTES. Uma ação CORRETA/necessária que só ADICIONA um passo "
    "(não cobre nenhum slot) = aceita=TRUE, substitui=[]. NUNCA marque aceita=false só porque não substitui slot — "
    "aceita=false é EXCLUSIVO pra chamada ERRADA (downgrade, tool errada, ação não pedida). Se você concluiu que a "
    "ferramenta está certa e é a ação ideal agora, é aceita=true (mesmo que o plano não a listasse).\n\n"
    "Exemplo: plano tem '[id=2] render_math ← renderizar a fórmula no navegador' e '[id=5] open_image ← abrir a foto do celular no ubuntu'; "
    "o modelo chamou 'display_math' porque 'mostrar a fórmula no navegador' → substitui=['2'] "
    "(o id do slot da fórmula; o id=5 da foto fica).\n\n"
    "Quando aceita=false, NÃO devolva nudge cego — analise a INTENÇÃO do modelo:\n"
    "  - se a intenção FAZ SENTIDO, aponte a ferramenta que REALMENTE a atende (pode NÃO ser a próxima do plano — a ordem do plano pode estar errada);\n"
    "  - se NÃO faz sentido, cruze a trajetória com o plano e ache o PRÓXIMO PASSO IDEAL.\n"
    "  Preencha 'proxima_tool' (nome da ferramenta) e 'motivo' (1-2 linhas: por que a chamada não encaixa e por que a proxima_tool encaixa, ancorado na trajetória).\n\n"
    "Trajetória real até agora (ferramenta -> resultado):\n{trajetoria}\n\n"
    "Responda em JSON: {{\"aceita\": bool, \"substitui\": [ids], \"proxima_tool\": \"<nome ou vazio>\", \"motivo\": \"<vazio se aceita>\"}}."
    )

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

_INSTR_CORRIGE_OMISSAO = (
    "O agente NÃO chamou ferramenta — só escreveu um texto — mas o pedido do dono AINDA tem passos. "
    "Determine a PRÓXIMA ferramenta que ele deveria chamar agora, pela INTENÇÃO do texto e pela trajetória.\n\n"
    "Ferramentas (o que cada uma faz):\n{tools}\n\n"
    "RESTRIÇÕES: display_page NÃO renderiza LaTeX — fórmula vai em display_math; render_math só GERA imagem "
    "(não mostra em device).\n\n"
    "Pedido do dono: {pedido}\n"
    "Plano ainda não executado (id · tool ← por que estava no plano):\n{restante}\n"
    "Trajetória real até agora (ferramenta -> resultado):\n{trajetoria}\n"
    "O que o agente escreveu (sem agir): \"{texto}\"\n\n"
    "Se a intenção do texto aponta uma ferramenta clara, use ELA (pode NÃO ser a próxima do plano — a ordem pode "
    "estar errada). Senão, cruze a trajetória com o plano e escolha o PRÓXIMO PASSO IDEAL.\n"
    "Responda JSON: {{\"proxima_tool\": \"<nome da ferramenta>\", \"motivo\": \"<1 linha: o que falta e por que essa tool>\"}}."
)


class Juiz:
    
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
    
    async def aceita_divergencia(
        self, 
        pedido: str, 
        tool_chamada: str, 
        args: dict, 
        porque_llm: str,
        restante: list[dict[str, str]], 
        tools: str,
        trajetoria: str = "",
    ) -> tuple[bool, list[str], str, str]:
        ids = [str(s["id"]) for s in restante]
        schema = {
            "type":"object",
            "required":["aceita","substitui","proxima_tool","motivo"],
            "properties":{
                "aceita":{"type":"boolean"},
                "substitui":{"type":"array","items":{"type":"string","enum":ids}},
                "proxima_tool":{"type":"string"},
                "motivo":{"type":"string"},
            },
        }
        restante_txt = "\n".join(f"  - [id={s['id']}] {s['tool']} ← \"{s['porque']}\"" for s in restante)
        resposta = await self._llm.complete(
            messages=[
                {
                    "role":"system",
                    "content":_INSTR_DIVERGENCIA.format(
                        tools=tools,
                        pedido=pedido, 
                        restante_rotulado=restante_txt,
                        chamou=tool_chamada, 
                        args=args, 
                        porque_llm=porque_llm, 
                        trajetoria=trajetoria or "(nada ainda)"
                    )
                }
            ],
            temperature=0.0,
            extra_body={"response_format":{"type":"json_schema","json_schema":{"name":"veredito","schema":schema}}})
        data = orjson.loads(resposta.content or "{}")
        trace(f"[JUIZ (divergencia)] {data}")
        return (
            bool(data.get("aceita")),
                [i for i in data.get("substitui",[]) if i in ids],
                data.get("proxima_tool",""),
                data.get("motivo","")
            )
    
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
    
    async def corrige_omissao(self, pedido, texto, restante, trajetoria, tools) -> tuple[str, str]:
        restante_txt = "\n".join(f"  - [id={s['id']}] {s['tool']} ← \"{s['porque']}\"" for s in restante)
        schema = {"type":"object","required":["proxima_tool","motivo"],
                  "properties":{"proxima_tool":{"type":"string"},"motivo":{"type":"string"}}}
        resposta = await self._llm.complete(
            messages=[{"role":"system","content":_INSTR_CORRIGE_OMISSAO.format(
                tools=tools, pedido=pedido, restante=restante_txt,
                trajetoria=trajetoria or "(nada ainda)", texto=texto)}],
            temperature=0.0,
            extra_body={"response_format":{"type":"json_schema","json_schema":{"name":"corretivo","schema":schema}}})
        data = orjson.loads(resposta.content or "{}")
        trace(f"[corretivo omissao] {data}")
        return data.get("proxima_tool",""), data.get("motivo","")
    
    async def aprova_turno(self, pedido: str, trajetoria: str, resposta: str, tools: str) -> tuple[bool, str]:
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
        
    
    