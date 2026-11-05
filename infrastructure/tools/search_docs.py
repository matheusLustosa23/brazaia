from pydantic import BaseModel, Field

from domain.tools.base import Tool
from domain.tools.guard import ToolCtx
from infrastructure.acervo.acervo import Acervo


class SearchDocsInput(BaseModel):
    consulta: str = Field(description="O que procurar, em palavras-chave: 'pilares do scrum', 'cocomo esforço', 'probabilidade condicional'.")
    documento: str | None = Field(default=None, description="Opcional: limitar a um documento (id ou parte do nome, ex.: 'scrum').")


class SearchDocsTool(Tool[SearchDocsInput]):
    name = "search_docs"
    description = (
        "Busca no ACERVO (o material das disciplinas do dono e documentos guardados) e devolve os trechos mais "
        "relevantes, cada um com o documento e a seção. Depois leia o que precisar com read_doc(doc, secao).\n"
        "USE ANTES de explicar, resumir ou montar material/exercícios de um conteúdo de disciplina — a resposta "
        "tem que vir do material, não da memória."
    )
    input_schema = SearchDocsInput
    side = "server"
    action_class = "read"
    router_hint = "buscar no material das disciplinas / documentos do acervo"

    def __init__(self, acervo: Acervo) -> None:
        self._acervo = acervo

    async def run(self, payload: SearchDocsInput, ctx: ToolCtx) -> str:
        doc = self._acervo.achar_doc(payload.documento) if payload.documento else None
        if payload.documento and not doc:
            return f"[acervo] não achei o documento '{payload.documento}'. Veja o catálogo com read_doc() sem argumentos."
        achados = self._acervo.buscar(payload.consulta, doc=doc)
        if not achados:
            discs = sorted({d["meta"].get("disciplina", d["colecao"]) for d in self._acervo.docs()})
            return (f"[acervo] nada encontrado para “{payload.consulta}”. O acervo tem: {', '.join(discs) or 'nada ainda'}. "
                    "Tente outras palavras ou veja o catálogo com read_doc().")
        linhas = [f"[acervo] {len(achados)} trecho(s) para “{payload.consulta}”:"]
        for i, a in enumerate(achados, 1):
            fonte = " · ".join(x for x in (a["disciplina"], a["titulo"]) if x)
            linhas.append(f"{i}. {fonte} › {a['caminho']}  (doc={a['doc']} secao={a['secao']})\n   “{a['trecho']}”")
        linhas.append("Leia a(s) seção(ões) com read_doc(doc, secao) antes de responder, e cite a fonte (disciplina · tema · seção).")
        return "\n".join(linhas)
