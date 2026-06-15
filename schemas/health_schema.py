from pydantic import BaseModel


class HealthData(BaseModel):
    status: str = "ok"
    vllm: str | None = None     # NOVOS — campos nulos são omitidos pelo ExcludeNoneRoute
    model: str | None = None
