import logging, time

from collections.abc import AsyncIterator
from domain.voice_contract import VoiceASR, VoiceTTS
from application.services.orchestrator import Orchestrator
logger = logging.getLogger(__name__)


VOICE_STYLE = """\
Você está numa conversa por VOZ. O usuário OUVE, não lê. Responda como uma pessoa \
responderia falando — direto e curto.

Regra principal — BREVIDADE:
- Responda em 1 ou 2 frases. Vá direto ao ponto que foi perguntado.
- Dê a resposta primeiro. Não recapitule o histórico, não liste etapas, não explique seu \
raciocínio a menos que peçam.
- Assunto longo → dê só o essencial e ofereça continuar ("quer que eu detalhe?").
- Pergunta curta = resposta curta. Só se estenda com "explica/detalha/passo a passo" explícito.

Tom:
- Coloquial e natural, como falando com um colega. Frases corridas, sem marcações visuais \
(listas, títulos, asteriscos, emojis, markdown).
- Nunca faça meta-comentário sobre formato, voz ou que você está sendo breve.

Exemplos:
P: "Onde a gente parou?"
✓ "Paramos no script do wake word."
✗ "Na última interação fizemos uma análise dos arquivos X e Y, depois editamos o wake.py nas \
linhas tais, commitamos e discutimos o threshold..."

P: "Deu certo o treino?"
✓ "Deu, o modelo ficou pronto. O recall ainda tá baixo, mas dá pra usar."
✗ "O treino concluiu com accuracy 0.80, recall 0.51 e 3.7 falsos positivos por hora..."
"""

class VoiceService:
    """Orquestra o ASR para UM turno de voz. Criado por conexão WS (mantém o
    buffer de áudio do turno). O modelo de ASR em si é compartilhado e stateless."""
    
    def __init__(self, asr: VoiceASR, orchestrator: Orchestrator, tts: VoiceTTS, session_id: str = "voice"):
        self._asr = asr
        self._audio = bytearray()
        self._orchestrator = orchestrator
        self._last_reply = ""
        self._tts = tts
        self._session_id = session_id
        
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
        
        async def tee(session_id: str) -> AsyncIterator[str]:
            async for tok in  self._orchestrator.run(session_id=session_id,user_message=text, extra_system=VOICE_STYLE):
                parts.append(tok)
                yield tok
        
        async for pcm in self._tts.stream(tee(self._session_id)):
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
                session_id=self._session_id,
                user_message=text,
                extra_system=VOICE_STYLE
            )
        ]
        logger.info("voice_reply_text ms=%d chars=%d",
                    round((time.monotonic() - t0) * 1000), len("".join(tokens)))
        return "".join(tokens)
     