import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Anexa request-id e mede latência por request; loga estruturado.

    Modelo 'cebola': tudo antes de `call_next` roda na ENTRADA; `call_next`
    passa o controle à rota e devolve a Response; tudo depois roda na SAÍDA.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        t0 = time.perf_counter()
        base = {"rid": rid, "method": request.method, "path": request.url.path}
        try:
            response = await call_next(request)
        except Exception:
            dt_ms = (time.perf_counter() - t0) * 1000
            logger.exception("request_failed", extra={"extra_fields": {**base, "ms": round(dt_ms, 2)}})
            raise  # re-lança o erro ORIGINAL, sem mascarar
        dt_ms = (time.perf_counter() - t0) * 1000
        logger.info("request", extra={"extra_fields": {**base, "ms": round(dt_ms, 2), "status": response.status_code}})
        response.headers["x-request-id"] = rid
        return response
