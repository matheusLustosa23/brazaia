from typing import Any
import re
import logging
import orjson
from openai import (
    AsyncOpenAI,
    APITimeoutError,
    APIConnectionError,
    InternalServerError
)
from openai.types.chat import ChatCompletion, ChatCompletionChunk
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
from collections.abc import AsyncIterator

_TRANSIENT = (APIConnectionError, InternalServerError)
_salvage_log = logging.getLogger("router_trace")

_TOOLCALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def _salvage_first_toolcall(content: str) -> tuple[str, dict] | None:
    """O Qwen3-VL às vezes batela vários <tool_call> num turno e escapa as aspas do valor
    do 2º+ bloco (\\"A = ...\\"). O hermes_tool_parser faz json.loads em CADA bloco e, ao
    falhar num, dropa TODOS → volta content bruto com tools=[]. Recupera o 1º bloco (sempre
    válido nos testes) e executa; o loop re-pede o resto (o open_image vem com o id REAL no
    turno seguinte). Delimita por TAG (não por chave — JSON tem braces aninhados) e tenta
    consertar o \\" como fallback caso o próprio 1º bloco venha degradado."""
    m = _TOOLCALL_RE.search(content or "")
    if not m:
        return None
    raw = m.group(1)
    for cand in (raw, raw.replace('\\"', '"')):
        try:
            d = orjson.loads(cand)
        except orjson.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("name"):
            return d["name"], (d.get("arguments") or {})
    return None


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
        self._max_out = s.reserved_output_tokens
        
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
        **opts: Any
    ) -> Completion:
        """Chamada não-stream. Function calling NATIVO via `tools`/`tool_choice`."""
        kwargs: dict[str, Any] = dict(model=self._model,messages=messages,**opts)
        kwargs.setdefault("max_tokens", self._max_out)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
            kwargs.setdefault("parallel_tool_calls", False) 
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
        content = msg.content
        if not tools_calls and content and "<tool_call>" in content:
            sc = _salvage_first_toolcall(content)
            if sc:
                name, args = sc
                _salvage_log.info(
                    "[salvage] hermes dropou o batch — recuperei 1o tool_call: %s", name
                )
                tools_calls.append(ToolCall(id="salvage-0", name=name, arguments=args))
                content = content[:content.index("<tool_call>")].strip() or None
        return Completion(
            content=content,
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
    
    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
        **opts: Any
    ) -> AsyncIterator[tuple[str, Any]]:
        """Itera deltas. Cada item: ('text', str) ou ('tool_call_delta', obj).

        O vLLM emite tool-calls em fragmentos (índice, nome parcial, arguments parciais).
        O acúmulo/parse final dos arguments fica a cargo do consumidor (feat-agent-loop).
        """
        kwargs: dict[str, Any] = dict(model=self._model, messages=messages, stream=True, **opts)
        kwargs.setdefault("max_tokens", self._max_out)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
            kwargs.setdefault("parallel_tool_calls", False) 
        try:
            s: AsyncIterator[ChatCompletionChunk] = await self._c.chat.completions.create(**kwargs)
            async for chunk in s:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield ("text", delta.content)
                for tcd in (delta.tool_calls or []):
                    yield ("tool_call_delta", tcd)
        except APITimeoutError as e:
            raise LLMTimeout("timeout no streaming do vLLM") from e
        except _TRANSIENT as e:
            raise LLMUnavailable("vLLM caiu durante o streaming") from e
        