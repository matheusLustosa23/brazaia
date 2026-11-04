from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.acervo.acervo import Acervo


class ReadDocInput(BaseModel):
    doc: str | None = Field(default=None, description=(
        "O documento (id que veio do search_docs, ou parte do nome: 'scrum', 'pontos de função'). "
        "Vazio = o CATÁLOGO do acervo (todas as disciplinas e temas)."))
    secao: int | None = Field(default=None, description="Número da seção. Vazio = o SUMÁRIO do documento (as seções com o número de cada).")
    parte: int = Field(default=0, description="Seção grande vem em partes: 0, 1, 2… (o resultado diz quantas há).")


class ReadDocTool(Tool[ReadDocInput]):
    name = "read_doc"
    description = (
        "Lê o ACERVO aos pedaços, sem carregar o documento inteiro: sem nada → catálogo; com doc → sumário "
        "(seções numeradas); com doc e secao → o texto daquela seção (em partes, se for grande).\n"
        "Ex.: 'o que tem no material de métodos ágeis?' → read_doc() e depois read_doc(doc=…); "
        "'me explica os eventos do Scrum' → search_docs → read_doc(doc, secao) → explica com base no texto."
    )
    input_schema = ReadDocInput
    side = "server"
    action_class = "read"
    router_hint = "ler o catálogo, o sumário ou uma seção de um documento do acervo"

    def __init__(self, acervo: Acervo) -> None:
        self._acervo = acervo

    async def run(self, payload: ReadDocInput, ctx: ToolCtx) -> str:
        ac = self._acervo
        if not payload.doc:
            docs = ac.docs()
            if not docs:
                return "[acervo] vazio — nenhum documento importado ainda."
            por: dict[str, list[dict]] = {}
            for d in docs:
                por.setdefault(d["meta"].get("disciplina") or d["colecao"], []).append(d)
            linhas = [f"[acervo] {len(docs)} documento(s):"]
            for disc, ds in por.items():
                linhas.append(f"• {disc}")
                linhas += [f"   - {d['titulo']}  (doc={d['id']})" for d in sorted(ds, key=lambda x: x["meta"].get("ordem") or 0)]
            return "\n".join(linhas)
        doc = ac.achar_doc(payload.doc)
        if not doc:
            return f"[acervo] não achei '{payload.doc}'. Veja o catálogo com read_doc() sem argumentos."
        if payload.secao is None:
            s = ac.sumario(doc)
            assert s is not None
            linhas = [f"[acervo] sumário de {s['meta'].get('disciplina', '')} · {s['titulo']} (doc={doc}):"]
            for x in s["secoes"]:
                if x["chars"] < 60:
                    continue
                recuo = "   " * max(0, x["caminho"].count(" > "))
                partes = f", {x['partes']} partes" if x["partes"] > 1 else ""
                linhas.append(f"{recuo}§{x['n']} {x['titulo']}  ({x['chars'] // 100 / 10} mil chars{partes})")
            linhas.append("Leia com read_doc(doc, secao=N).")
            return "\n".join(linhas)
        r = ac.ler(doc, payload.secao, payload.parte)
        if r is None:
            return f"[acervo] seção {payload.secao} (parte {payload.parte}) não existe em {doc}. Veja o sumário com read_doc(doc)."
        rodape = []
        if r["parte"] + 1 < r["partes"]:
            rodape.append(f"continua: read_doc(doc, secao={r['secao']}, parte={r['parte'] + 1}) — parte {r['parte'] + 1} de {r['partes']}")
        if r["proxima_secao"]:
            rodape.append(f"próxima seção: §{r['proxima_secao']['n']} {r['proxima_secao']['caminho']}")
        return (f"[acervo] {doc} §{r['secao']} {r['caminho']}"
                + (f" (parte {r['parte'] + 1}/{r['partes']})" if r["partes"] > 1 else "") + ":\n\n"
                + r["texto"] + ("\n\n— " + " · ".join(rodape) if rodape else ""))
