"""Cliente do LLM via vLLM (API compatível com OpenAI), em streaming.

Esta é a COSTURA para a entrega 2 (o agente): a pipeline depende só do protocolo `Responder`
(`async stream(history) -> deltas de texto`). Hoje temos `VLLMResponder` (chama o vLLM direto);
amanhã basta implementar um `AgentResponder` (orchestrator: tools/memória/sessão) com a mesma
assinatura e injetar na pipeline — nenhum outro módulo muda.
"""
from __future__ import annotations
from typing import AsyncIterator, Protocol
from openai import AsyncOpenAI


class Responder(Protocol):
    def stream(self, history: list[dict]) -> AsyncIterator[str]:
        """Recebe o histórico [{role, content}] e produz os deltas de texto da resposta."""
        ...


class VLLMResponder:
    """Fala com o vLLM local. Dono do system prompt e dos parâmetros de geração."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.client = AsyncOpenAI(
            base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.request_timeout_s,
        )

    async def stream(self, history: list[dict]) -> AsyncIterator[str]:
        messages = [{"role": "system", "content": self.cfg.system_prompt}]
        messages += history[-self.cfg.history_turns:]
        extra = {}
        if self.cfg.disable_thinking:
            extra = {"chat_template_kwargs": {"enable_thinking": False}}
        stream = await self.client.chat.completions.create(
            model=self.cfg.model, messages=messages, stream=True,
            temperature=self.cfg.temperature, max_tokens=self.cfg.max_tokens,
            extra_body=extra,
        )
        try:
            async for chunk in stream:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    yield delta
        finally:
            # fecha a conexão mesmo em cancelamento (barge-in) → não vaza stream no vLLM
            try:
                await stream.close()
            except Exception:
                pass
