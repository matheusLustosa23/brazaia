"""Registro DETERMINÍSTICO do que acontece no estudo (tutor → cérebro).

Por quê: medido 04/11 (qwen35-27b-abl, think on, 2/2): o tutor corrige os exercícios muito bem, mas NÃO chama
log/remember no meio da correção — mesmo com a regra colada na regra de correção (a atenção está no aluno).
Abrir/fechar a sessão ele chama sozinho (é o assunto do turno); os ACERTOS e as DIFICULDADES ficam com o
servidor: depois de cada turno do tutor, uma chamada curta (sem raciocínio, JSON) lê a correção e extrai
{tema, acertos, total, dificuldades}. Se o turno não foi correção, volta vazio e nada é gravado.
"""
from __future__ import annotations

import orjson

from application.services._flowlog import curto, flow
from application.services.cerebro_service import CerebroService
from domain.contracts import LLMClient

_PROMPT = """Você lê um trecho de aula particular e responde SÓ um JSON.
A ÚLTIMA fala do tutor CORRIGE respostas que o aluno deu a exercícios/perguntas?
- Não → {"correcao": false}
- Sim → {"correcao": true, "tema": "<assunto dos exercícios, curto, ex. 'Pilares do Scrum'>",
         "acertos": <quantas o aluno acertou POR INTEIRO>, "total": <quantas foram corrigidas>,
         "dificuldades": ["<cada erro de CONCEITO do aluno, 1 frase curta, ex. 'acha que o Scrum Master cobra a equipe'>"]}
Meio certo conta como erro. Não invente: use só o que está na correção."""


def _ja_registrou(turno: list[dict]) -> bool:
    """O próprio modelo já chamou log(tipo=exercicios) neste turno → não duplica."""
    for m in turno:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            if fn.get("name") == "log" and "exercic" in (fn.get("arguments") or ""):
                return True
    return False


async def registrar_correcao(llm: LLMClient, cerebro: CerebroService, session_id: str, disciplina: str | None,
                             pergunta_anterior: str, resposta_aluno: str, correcao: str,
                             turno: list[dict]) -> dict | None:
    if not correcao or _ja_registrou(turno):
        return None
    msgs = [{"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"TUTOR (antes):\n{pergunta_anterior[-2500:]}\n\nALUNO:\n{resposta_aluno[-1500:]}"
                                        f"\n\nTUTOR (última fala):\n{correcao[-3500:]}"}]
    try:
        out = await llm.complete(msgs, no_think=True, max_tokens=300, temperature=0,
                                 response_format={"type": "json_object"})
        d = orjson.loads(out.content or "{}")
    except Exception as e:                                   # registro é bônus: nunca derruba o turno
        flow(session_id, "estudo", f"✗ extração falhou: {e}")
        return None
    if not d.get("correcao") or not isinstance(d.get("total"), int) or d["total"] <= 0:
        return None
    tema = (d.get("tema") or disciplina or "Estudo").strip()[:80]
    acertos = max(0, min(int(d.get("acertos") or 0), d["total"]))
    difs = [str(x).strip()[:200] for x in (d.get("dificuldades") or []) if str(x).strip()][:4]
    if disciplina is None:                                   # o modelo não abriu a sessão: abre aqui, pra os
        aberta = await cerebro.sessao_aberta()               # exercícios ficarem DENTRO de um estudo (linha do tempo)
        if aberta is None or aberta.tipo != "estudo":
            r = await cerebro.registrar("abrir", "estudo", tema, texto="aberta pelo registro automático", fonte=session_id)
            flow(session_id, "estudo", curto(r, 200))
    r = await cerebro.registrar("registrar", "exercicios", tema, {"acertos": acertos, "total": d["total"]},
                                "; ".join(difs)[:300], fonte=session_id)
    flow(session_id, "estudo", curto(r, 300))
    for dif in difs:
        r = await cerebro.lembrar(dif, "dificuldade", tema, "tema",
                                  relacao="disciplina" if disciplina else None, com=disciplina, fonte=session_id)
        flow(session_id, "estudo", curto(r, 200))
    return {"tema": tema, "acertos": acertos, "total": d["total"], "dificuldades": difs}
