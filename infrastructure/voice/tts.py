import asyncio
from  collections.abc import AsyncIterator
import numpy as np
from kokoro import KPipeline
import re 

try:
    from emoji import replace_emoji
except ImportError:
    replace_emoji = None
    
    
def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)      # blocos de código
    text = re.sub(r"`([^`]*)`", r"\1", text)                # `inline`
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)    # [txt](url) -> txt
    text = re.sub(r"[*_#~>|]+", " ", text)                  # markdown: * _ # ~ > |
    text = re.sub(r"^\s*[-•·]\s+", "", text, flags=re.M)    # marcadores de lista
    text = replace_emoji(text, "") if replace_emoji else re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+", "", text)  # emojis
    return re.sub(r"\s+", " ", text).strip()

class TTS:
    """Kokoro 82M na CPU, pt-BR (lang_code='p'). Saída: PCM int16 a 24kHz."""
    
    SAMPLE_RATE = 24_000
    
    def __init__(self, voice = "pf_dora"):
        self._pipe = KPipeline(lang_code="p")
        self._voice = voice
        
    async def stream(self, tokens: AsyncIterator[str]) -> AsyncIterator[bytes]:
        buf = ""
        async for tok in tokens:
            buf += tok
            if buf and buf[-1] in ".!?…\n":
                fala = clean_for_speech(buf) 
                if fala and (pcm := await asyncio.to_thread(self._synth, fala)):
                    yield pcm
                buf = ""
        fala = clean_for_speech(buf)
        if fala and buf.split() and (pcm := await asyncio.to_thread(self._synth, fala)):
            yield pcm
    
    def _synth(self, texto: str) -> bytes | None:
        chunks = [
           r.audio.numpy()
           for r in self._pipe(texto, self._voice)
           if r.audio is not None
        ]
        
        if not chunks:
            return None
        
        return (np.concatenate(chunks) * 32767).astype(np.int16).tobytes()