import numpy as np, soundfile as sf
from infrastructure.voice.tts import TTS

GREETINGS = [
    "Fala meu patrão!",
    "Fala meu nobre!",
    "E aí, beleza?",
    "Manda o papo!",
    "Diz aí chefe!",
    "Salve salve!",
    "Tô na escuta!",
    "Desembucha!",
    "Opa, cheguei!",
    "Fala parceiro!",
    "Tô ligado, manda!",
    "Fala comigo!",
    "O que ta pegando?"
]

voices = [
    "pm_santa",
    "pm_alex",
    "pf_dora",
    "jf_alpha",
    "af_heart",
    "af_bella"
]

for voice in voices:
    tts = TTS(voice)
    for i, frase in enumerate(GREETINGS):
        pcm = tts._synth(frase)
        assert pcm is not None
        sf.write(
            f"companion/assets/greeting_{voice}_{i}.wav",
             np.frombuffer(pcm, dtype=np.int16), TTS.SAMPLE_RATE
        )
