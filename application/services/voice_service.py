import logging, time

from collections.abc import AsyncIterator
from domain.voice_contract import VoiceASR, VoiceTTS
from application.services.orchestrator import Orchestrator
logger = logging.getLogger(__name__)


VOICE_STYLE = """\
Você está numa conversa por VOZ: o usuário OUVE a resposta, não lê. Marcações visuais \
(listas, títulos, asteriscos, números ordenados, emojis, markdown) prejudicam a fala — não use nenhuma.

Como responder:
- Comece direto pela resposta. Nunca abra explicando que está adaptando, formatando ou que vai falar.
- Frases corridas e naturais, tom coloquial, como alguém conversando pessoalmente. \
Use vírgulas e pontos como pausas, não quebras estruturais.
- Nunca faça meta-comentário sobre formato ou voz.

Casos especiais:
- Listas (ingredientes, passos): apresente de forma narrativa e conectada ("primeiro", "depois", "além disso").
- Números e dados: fale por extenso no contexto ("três em cada cinco" em vez de "3/5").
- Incerteza: diga naturalmente ("não tenho certeza, mas acho que...").
"""

class VoiceService:
    """Orquestra o ASR para UM turno de voz. Criado por conexão WS (mantém o
    buffer de áudio do turno). O modelo de ASR em si é compartilhado e stateless."""
    
    def __init__(self, asr: VoiceASR, orchestrator: Orchestrator, tts: VoiceTTS):
        self._asr = asr
        self._audio = bytearray()
        self._orchestrator = orchestrator
        self._last_reply = ""
        self._tts = tts
    
    @property
    def last_reply(self) -> str:
        return self._last_reply
    
    async def reply_audio(self, text: str) -> AsyncIterator[bytes]:
        """UMA passada do LLM: tee em (1) coleta de texto e (2) TTS. Yield de PCM 24kHz;
        o texto completo fica em self.last_reply."""
        if self._tts is None:
            raise RuntimeError("TTS indisponível")
        parts: list[str] = []
        t0, first = time.monotonic(), True
        
        async def tee() -> AsyncIterator[str]:
            async for tok in  self._orchestrator.run(session_id="voice",user_message=text, extra_system=VOICE_STYLE):
                parts.append(tok)
                yield tok
        
        async for pcm in self._tts.stream(tee()):
            if first:
                logger.info("voice_tts_ttft_ms=%d", round((time.monotonic() - t0) * 1000))
                first = False
            yield pcm
        
        self._last_reply = "".join(parts)
    
    def feed(self, chunk: bytes) -> None:
        """Acumula o áudio do turno. Instantâneo — NÃO transcreve (não bloqueia o loop)."""
        self._audio.extend(chunk)
    
    async def transcribe(self) -> str | None:
        """Transcrição única do turno inteiro — chamada no turn_end (batch)."""
        if not self._audio:
            return None
        return await self._asr.transcribe(bytes(self._audio))
    
 
    def reset(self) -> None:
        self._audio = bytearray()
    
    async def reply_text(self, text: str) -> str: 
        t0 = time.monotonic()
        tokens = [
            tok 
            async for tok in self._orchestrator.run(
                session_id="voice",
                user_message=text,
                extra_system=VOICE_STYLE
            )
        ]
        logger.info("voice_reply_text ms=%d chars=%d",
                    round((time.monotonic() - t0) * 1000), len("".join(tokens)))
        return "".join(tokens)
     