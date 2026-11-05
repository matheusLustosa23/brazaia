"""Acervo (documentos que o agente consulta) — enviar, listar, remover e buscar.

Uma rota só pra todos os jeitos de mandar um documento: CLI/terminal (`python -m companion acervo add …`),
celular (Termux) e painel (arrastar). Aceita a x-api-key OU o cookie do painel.
O arquivo vira Markdown (markitdown), é cortado em seções/partes e indexado — daí o agente acha com search_docs.
"""
import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from api.v1.dependencies import require_painel

router = APIRouter(prefix="/acervo", tags=["acervo"])
_MAX = 30 * 1024 * 1024


def _ac(request: Request):
    return request.app.state.acervo


@router.post("", dependencies=[Depends(require_painel)])
async def enviar(request: Request, arquivo: UploadFile = File(...), colecao: str = Form("anexos")):
    dados = await arquivo.read()
    if len(dados) > _MAX:
        raise HTTPException(status_code=413, detail="arquivo maior que 30 MB")
    try:   # converter PDF/DOCX pode levar segundos: fora do loop do servidor
        return await asyncio.to_thread(_ac(request).adicionar, arquivo.filename or "documento.txt", dados, colecao or "anexos")
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))


@router.get("", dependencies=[Depends(require_painel)])
async def listar(request: Request, colecao: str | None = None):
    return {"docs": _ac(request).docs(colecao)}


@router.get("/busca", dependencies=[Depends(require_painel)])
async def buscar(request: Request, q: str, doc: str | None = None):
    return {"trechos": _ac(request).buscar(q, doc=doc)}


@router.get("/sumario/{doc_id:path}", dependencies=[Depends(require_painel)])
async def sumario(doc_id: str, request: Request):
    s = _ac(request).sumario(doc_id)
    if s is None:
        raise HTTPException(status_code=404, detail="documento não existe")
    return s


@router.delete("/{doc_id:path}", dependencies=[Depends(require_painel)])
async def remover(doc_id: str, request: Request):
    if not _ac(request).remover(doc_id):
        raise HTTPException(status_code=404, detail="documento não existe")
    return {"ok": True}
