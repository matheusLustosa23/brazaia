"""Artefatos gerados pelo agente (HTML, imagens…) — listar os de uma sessão e baixar um pelo file_id.

É o que deixa o dono ABRIR depois o que o agente produziu (ex.: o material de uma réplica do tutor), de
qualquer device: o CLI baixa e abre localmente (/arquivos, /abrir).
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from api.v1.dependencies import require_api_key

router = APIRouter(prefix="/files", tags=["files"])

_MIME = {"html": "text/html; charset=utf-8", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "webp": "image/webp", "json": "application/json", "txt": "text/plain; charset=utf-8",
         "md": "text/markdown; charset=utf-8", "csv": "text/csv; charset=utf-8"}


@router.get("", dependencies=[Depends(require_api_key)])
async def listar(session_id: str, request: Request):
    """Artefatos de uma sessão, do mais antigo pro mais novo."""
    return {"files": request.app.state.file_store.listar(session_id)}


@router.get("/{file_id}", dependencies=[Depends(require_api_key)])
async def baixar(file_id: str, request: Request):
    """O arquivo em si (o nome sugerido usa o título, quando houver)."""
    store = request.app.state.file_store
    caminho = store.path(file_id)
    if caminho is None:
        raise HTTPException(status_code=404, detail=f"file_id {file_id} não encontrado")
    ext = os.path.splitext(caminho)[1].lstrip(".").lower()
    titulo = (store.meta(file_id).get("title") or file_id).strip()
    nome = "".join(c if c.isalnum() or c in " -_." else "_" for c in titulo)[:80].strip() or file_id
    return FileResponse(caminho, media_type=_MIME.get(ext, "application/octet-stream"), filename=f"{nome}.{ext}")
