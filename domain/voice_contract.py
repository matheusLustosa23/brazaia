from typing import Protocol, runtime_checkable
from collections.abc import AsyncIterator


@runtime_checkable
class VoiceASR(Protocol):
    """Speech-to-Text. Stateless: recebe PCM int16 16kHz, devolve texto.
    O modelo é carregado uma vez (no lifespan) e compartilhado entre conexões."""

    async def transcribe(self, pcm: bytes, language: str | None = "pt") -> str | None: ...

@runtime_checkable
class VoiceTTS(Protocol):
    """Text-to-Speech. Recebe tokens (async) do LLM, devolve PCM int16 24kHz por sentença."""
    def stream(self, tokens: AsyncIterator[str]) -> AsyncIterator[bytes]: ...