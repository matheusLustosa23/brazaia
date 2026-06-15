from typing import Any
import orjson
from openai import (
    AsyncOpenAI,
    APITimeoutError,
    APIConnectionError,
    InternalServerError
)
from openai.types.chat import ChatCompletion
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError
)
from core.config import Settings
from domain.entities.message import Completion, ToolCall, Usage
from domain.exceptions.llm_exceptions import LLMUnavailable,LLMTimeout

_TRANSIENT = (APIConnectionError, InternalServerError)


class OpenAILLMClient:
    """Implementação do contrato `LLMClient` sobre o vLLM. Único acoplamento com `openai`."""
    
    def __init__(self, s: Settings) -> None:
        self._c = AsyncOpenAI(
            base_url=s.vllm_base_url,
            api_key=s.vllm_api_key.get_secret_value(),
            timeout=s.llm_timeout_s,
            max_retries=0
        )
        self._model = s.model_name
        self._retries = s.llm_max_retries
        self._backoff = s.llm_backoff_base_s
        
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **opts: Any
    ) -> Completion:
        """Chamada não-stream. Function calling NATIVO via `tools`/`tool_choice`."""
        kwargs: dict[str, Any] = dict(model=self._model,messages=messages,**opts)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        try:
            r = await self._call(**kwargs)
        except RetryError as e:
            raise LLMUnavailable("vLLM indisponível após retries") from e.last_attempt.exception()
        return self._normalize(r)
        
    async def _call(self, **kwargs: Any) -> ChatCompletion:
        @retry(
            stop=stop_after_attempt(self._retries),
            wait=wait_exponential(multiplier=self._backoff),
            retry=retry_if_exception_type(_TRANSIENT),
            reraise=False
        )
        async def _do() -> ChatCompletion:
            try:
                return await self._c.chat.completions.create(**kwargs)
            except APITimeoutError as e:
                raise LLMTimeout("timeout na chamada ao vLLM") from e
        return await _do()
    
    @staticmethod
    def _normalize(r: ChatCompletion) -> Completion:
        msg = r.choices[0].message
        tools_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            if tc.type != 'function':
                continue
            try:
                args = orjson.loads(tc.function.arguments or "{}")
            except orjson.JSONDecodeError:
                args = {}
            tools_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args
                )
            )
        u = r.usage 
        if u is None:
            usage = Usage()
        else:
            usage = Usage(u.prompt_tokens,u.completion_tokens,u.total_tokens)
        return Completion(
            content=msg.content,
            tool_calls=tools_calls,
            finish_reason=r.choices[0].finish_reason,
            usage=usage
        )
    
    async def health(self) -> dict[str, str | None]:
        """Status do engine via /v1/models. Degrada, não derruba a API."""
        try:
            models = await self._c.models.list()
            return {"vllm": "up", "model": models.data[0].id}
        except APITimeoutError:
            return {"vllm": "timeout", "model": None}
        except Exception:
            return  {"vllm": "down", "model": None}
        