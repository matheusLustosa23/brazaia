from __future__ import annotations
from pydantic import BaseModel
from typing import Generic, TypeVar


T = TypeVar("T")

class ErrorResponse(BaseModel):
    """Detalhe opcional de erro (campo/código), embarcado no envelope quando útil."""
    field: str | None = None
    code: str | None = None

class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int

class ApiResponse(BaseModel, Generic[T]):
    """Envelope único do projeto: {status, success, message, data, pagination}.
    Campos nulos são omitidos via ExcludeNoneRoute. Serializado pelo Pydantic (Rust)."""
    status: int = 200
    success: bool = True
    message: str | None = None
    data: T | None = None
    pagination: PaginationMeta | None = None

    @classmethod
    def ok(
        cls,
        data: T | None = None,
        *,
        message: str | None = None,
        status: int = 200,
        pagination: PaginationMeta | None = None,
    ) -> ApiResponse[T]:
        return cls(
            status=status,
            success=True,
            message=message,
            data=data,
            pagination=pagination,
        )

    @classmethod
    def error(cls, status: int, message: str) -> ApiResponse[None]:
        # parametriza explicitamente p/ None — cls(...) seria ApiResponse[T] (genérico invariante)
        return ApiResponse[None](status=status, success=False, message=message, data=None)
