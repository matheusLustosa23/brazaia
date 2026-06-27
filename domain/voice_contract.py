from typing import Protocol, runtime_checkable


@runtime_checkable
class VoiceASR(Protocol):
    """Speech-to-Text. Stateless: recebe PCM int16 16kHz, devolve texto.
    O modelo é carregado uma vez (no lifespan) e compartilhado entre conexões."""

    async def transcribe(self, pcm: bytes, language: str | None = "pt") -> str | None: ...