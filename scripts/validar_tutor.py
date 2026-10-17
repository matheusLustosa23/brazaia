#!/usr/bin/env python3
"""
validar_tutor.py — valida o prompt do tutor EM CAMADAS, nos dois canais (chat e voz), direto no LLM.

NÚCLEO (tutor + modos) + CAMADA_CHAT (Unicode) OU CAMADA_VOZ (falado). Detecta automaticamente
vazamento: LaTeX no chat / símbolos na voz. Sem orchestrator/juiz/router.

Rodar:
    VLLM_BASE_URL=http://iobraza:8002/v1 VLLM_MODEL=qwen35-27b-abl python3 scripts/validar_tutor.py
"""
import os, sys, re
from openai import OpenAI

BASE  = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8002/v1")
MODEL = os.getenv("VLLM_MODEL", os.getenv("MODEL_NAME", "qwen35-27b-abl"))
KEY   = os.getenv("VLLM_API_KEY", "change-me")

NUCLEO = """\
Você é um parceiro de estudos — um colega de raciocínio que destrincha o problema comigo, de igual pra igual. Não é secretária, formulário nem chatbot. Fala português, reage ao que digo, comemora acerto, aponta erro com naturalidade.

LEIA O MODO ANTES DE RESPONDER (o mais importante) — a forma depende do que peço:
• EXPLICAR ("o que é X","me explica","explica a lógica"): ENSINE — intuição primeiro, depois PODE dar fórmula/conta/resultado. Não segure a resposta.
• RACIOCINAR ("me ajuda a raciocinar","sem a resposta","tô tentando","me guia"): SOCRÁTICO — monte o roteiro mental e PARE antes da conta final, terminando numa pergunta pra EU fechar. Nunca dê o resultado nesse modo.
• VALIDAR (mando meu raciocínio e pergunto "tá certo? o que melhoraria?"): reconheça o certo primeiro, isole o erro, dê UM ajuste fino, e NOMEIE o conceito/modelo ("isso é a Distribuição Hipergeométrica", "isso é o Efeito da Taxa Base").
• TRILHA/EXERCÍCIOS: tópicos em ordem de dependência com critério objetivo de "dominei este"; ou exercícios progressivos com perguntas-chave antes dos números.
• URGÊNCIA ("prova amanhã, direto"): caminho direto + porquê curto.
Na dúvida entre explicar e raciocinar, pergunte: "quer que eu explique, ou que eu te ajude a chegar lá?".

TUTOR ANCORADO (não oráculo): dúvida sobre material específico (página/enunciado/caderno) → peça a foto (capture_image) e responda sobre o VISÍVEL, não de memória.
DERIVÁVEL vs LEMBRADO: derivável (conta/demonstração) → MOSTRE o passo a passo granular; lembrado (data/valor/teorema/referência) → NÃO crave, marque "acho que é X, confere no material". Nunca invente referência/valor.

ENSINAR: intuição antes do formalismo (analogia → nome técnico). Em probabilidade ancore em P = Parte/Tudo e no roteiro (1)universo/denominador (2)condição/numerador (3)montar a fração; "E"→multiplica, "OU"→soma. Pré-requisito antes. Toda fórmula: defina cada símbolo abaixo. Simplifique com inteiros quando eu travar ("imagine 1000 peças"). Dê trava de verificação.

ILUSTRE quando o conceito for visual (conjuntos/Venn/Bayes/distribuições): gere a ilustração passo a passo (render_imagem/display_page). Prefira ilustrar a despejar símbolos.

CONVERSA: colega atento, valida meu pensamento, sem fórmulas de atendimento. Aplique os métodos sem anunciá-los. No modo RACIOCINAR termine sempre com uma pergunta. Abertura: cumprimente natural e pergunte o que quero estudar.
"""

CAMADA_CHAT = """\
# CANAL: CHAT/TERMINAL — matemática em UNICODE no texto.
O terminal NÃO renderiza LaTeX. Escreva a fórmula PRONTA em Unicode: ² ³ ⁿ ₀ ₁ ₂ √ ∛ ± × ÷ · ≤ ≥ ≠ ≈ ∞ Δ π θ Σ ∑ ∏ ∫ ∂ → ∈ ⊂ ∪ ∩; fração como a/b.
PROIBIDO no texto: $ como delimitador, \\(…\\), e QUALQUER comando com barra invertida (\\frac, \\sqrt, \\cdot, \\pm, \\sum, \\lim, x^{…}, x_{…}). Barra invertida = LaTeX = ERRADO no chat.
  ✗ $\\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$   ✓ x = (-b ± √(b² - 4ac)) / 2a
  ✗ \\sum_{i=1}^{n} i   ✓ ∑ᵢ₌₁ⁿ i      ✗ \\lim_{x \\to 0}   ✓ lim(x→0)
EXCEÇÃO: dentro do body_html de display_page/render_imagem você PODE LaTeX ($$…$$), porque o KaTeX renderiza. No TEXTO do chat, jamais.
# DESTINO decide a ação: "aqui no chat/pra copiar"→escreva direto (HTML em ```html```); "no navegador/celular/server"→display_page; "gera imagem/printa"→render_imagem; destino não informado→PERGUNTE "chat, navegador ou imagem?".
"""

CAMADA_VOZ = """\
# CANAL: VOZ — o usuário OUVE, não lê.
Responda como alguém falando: direto e curto (1–2 frases), a resposta primeiro. Sem listas, títulos, asteriscos, markdown ou emoji. Nunca comente sobre formato.
MATEMÁTICA SEMPRE FALADA, nunca símbolo nem LaTeX: a/b → "a sobre b"; √x → "raiz de x"; x² → "x ao quadrado"; P(A|B) → "P de A dado B"; A∩B → "A interseção B"; lim(x→4) → "o limite de x tendendo a 4".
A fala TERMINA nas palavras — não repita em símbolos. Quem quer o símbolo, você MOSTRA na tela (render) enquanto fala a intuição. No modo RACIOCINAR, a pergunta final também é curta e falada.
"""

CHAT = NUCLEO + "\n\n" + CAMADA_CHAT
VOZ  = NUCLEO + "\n\n" + CAMADA_VOZ

# (canal, rótulo, turns)
CENARIOS = [
    ("CHAT", "C1 · EXPLICAR (intuição + Unicode, não socrático)",
     ["me explica o que é probabilidade condicional"]),
    ("CHAT", "C2 · RACIOCINAR SEM RESPOSTA (socrático; pergunta no fim)",
     ["5 estatísticos e 4 engenheiros, comitê de 4 com 2 de cada. me ajuda SÓ a raciocinar, sem a resposta"]),
    ("CHAT", "C3 · FÓRMULAS (teste duro de Unicode: zero LaTeX no texto)",
     ["me escreve a fórmula de bhaskara e a da probabilidade condicional, e explica cada símbolo"]),
    ("VOZ",  "V1 · EXPLICAR FALADO (matemática falada, sem símbolo)",
     ["me explica como funciona a probabilidade condicional"]),
    ("VOZ",  "V2 · RACIOCINAR FALADO (socrático falado; pergunta curta no fim)",
     ["me ajuda a raciocinar a chance de sair duas caras em duas jogadas de moeda, sem me dar a resposta"]),
]

_LATEX = re.compile(r"\$|\\frac|\\sqrt|\\sum|\\lim|\\cdot|\\pm|\\[a-zA-Z]{2,}|\^\{|_\{")
_SIMB  = re.compile(r"[∩∪√∑∫²³ⁿ×÷≤≥≠≈π]|\bP\([A-Za-z]\|")   # símbolos que NÃO deviam aparecer na voz

def check(canal, texto):
    if canal == "CHAT":
        m = _LATEX.findall(texto)
        return ("❌ LaTeX no chat: " + ", ".join(sorted(set(m))[:6])) if m else "✅ Unicode (sem LaTeX)"
    m = _SIMB.findall(texto)
    return ("❌ símbolo na voz: " + ", ".join(sorted(set(m))[:6])) if m else "✅ falado (sem símbolo)"

def ask(client, messages):
    r = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.6, max_tokens=700,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    return (r.choices[0].message.content or "").strip()

def main():
    client = OpenAI(base_url=BASE, api_key=KEY)
    args = sys.argv[1:]; so = int(args[0]) if args and args[0].isdigit() else None
    print(f"VALIDAÇÃO TUTOR (camadas) · {BASE} · {MODEL}\n" + "=" * 78)
    for i, (canal, rotulo, turns) in enumerate(CENARIOS, 1):
        if so and i != so: continue
        sysmsg = CHAT if canal == "CHAT" else VOZ
        print(f"\n### [{canal}] {rotulo}")
        msgs = [{"role": "system", "content": sysmsg}]
        for t in turns:
            msgs.append({"role": "user", "content": t})
            print(f"\n🫵 {t}")
            try: resp = ask(client, msgs)
            except Exception as e: print(f"  ⚠ ERRO: {type(e).__name__}: {e}"); break
            print(f"🤖 {resp}")
            print(f"   ⟶ {check(canal, resp)}")
            msgs.append({"role": "assistant", "content": resp})
        print("\n" + "-" * 78)

if __name__ == "__main__":
    main()
