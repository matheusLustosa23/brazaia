"""Adapter de STT (fala -> texto) para streaming.

Implementa o port VoiceASR. Além dos motores (Whisper/Parakeet), traz:
- Stabilizer: autocorreção ao vivo (LocalAgreement-2) — firma só o que estabiliza.
- collapse_repeats / is_hallucination: redes contra alucinação do Whisper no silêncio/ruído.
"""
from domain.voice_contract import Word, VoiceASR


def _remove_coladas(palavras: list[str]) -> list[str]:
    """Remove palavra idêntica à imediatamente anterior ('sim sim' -> 'sim')."""
    resultado: list[str] = []
    for palavra in palavras:
        if resultado and resultado[-1].lower() == palavra.lower():
            continue
        resultado.append(palavra)
    return resultado


def collapse_repeats(texto: str) -> str:
    """Colapsa blocos de 1–3 palavras repetidos 3+ vezes (alucinação em ruído: 'E aí E aí E aí')."""
    palavras = texto.split()
    total = len(palavras)
    resultado: list[str] = []
    i = 0
    while i < total:
        colapsou = False
        for tamanho_bloco in (3, 2, 1):
            if i + tamanho_bloco * 3 <= total:
                bloco = palavras[i:i + tamanho_bloco]
                fim = i + tamanho_bloco
                repeticoes = 1
                while (
                    fim + tamanho_bloco <= total
                    and [
                            p.lower() for p in palavras[fim:fim + tamanho_bloco]
                        ]
                    == [p.lower() for p in bloco]
                ):
                    repeticoes += 1
                    fim += tamanho_bloco
                if repeticoes >= 3:
                    resultado += bloco          # guarda UMA cópia e pula as repetições
                    i = fim
                    colapsou = True
                    break
        if not colapsou:
            resultado.append(palavras[i])
            i += 1
    return " ".join(resultado)


# frases-fantasma que o Whisper "completa" no silêncio (treino com fim de vídeo do YouTube)
_FRASES_FANTASMA = {"obrigado", "obrigada", "tchau", "valeu", "pessoal", "gente", "muito", "até", "logo",
                    "amara", "org", "legenda", "legendas", "i", "think", "okay", "ok", "you", "thank",
                    "thanks", "bye", "so", "um", "uh", "the"}


def is_hallucination(texto: str) -> bool:
    """True se o texto é curto (≤4 palavras) E só com palavras-fantasma — turno a descartar."""
    limpo = texto.strip().lower().strip(".,;:!?… ")
    if not limpo:
        return True
    palavras = [p.strip(".,;:!?…") for p in limpo.split()]
    return len(palavras) <= 4 and all(p in _FRASES_FANTASMA for p in palavras if p)


class Stabilizer:
    """LocalAgreement-2: firma ('committed') só o prefixo em que a hipótese atual concorda com a anterior.

    A cada passo re-transcrevemos a janela inteira; o fim muda, o começo estabiliza.
    'committed' = palavras definitivas (não mudam na tela); 'provisorias' = ainda instáveis.
    """
    def __init__(self):
        self.committed: list[str] = []        # palavras já firmadas (definitivas)
        self.provisorias: list[Word] = []     # última hipótese instável (com tempos)

    def reset(self):
        self.committed = []
        self.provisorias = []

    def step(self, hipotese: list[Word]) -> tuple[str, str, float]:
        """Recebe a nova hipótese; firma o prefixo que concorda com a hipótese anterior.

        Retorna (texto_firme, texto_provisorio, fim_da_última_palavra_firmada_em_s).
        """
        prefixo_concordante: list[Word] = []
        for anterior, nova in zip(self.provisorias, hipotese):
            if anterior.texto == nova.texto:
                prefixo_concordante.append(nova)
            else:
                break                          # na 1ª divergência, para de firmar

        for palavra in prefixo_concordante:
            self.committed.append(palavra.texto)   # o que concordou vira definitivo
        self.provisorias = hipotese[len(prefixo_concordante):]   # o resto segue provisório

        fim_firme = prefixo_concordante[-1].fim if prefixo_concordante else 0.0
        texto_firme = " ".join(self.committed)
        texto_provisorio = " ".join(p.texto for p in self.provisorias)
        return texto_firme, texto_provisorio, fim_firme

    def flush(self) -> str:
        """Fim do turno: tudo que restou vira definitivo; tira repetições e devolve o texto final."""
        for palavra in self.provisorias:
            self.committed.append(palavra.texto)
        final = collapse_repeats(" ".join(_remove_coladas(self.committed))).strip()
        self.reset()
        return final

    def tail_word(self) -> str:
        """Última palavra dita (o Endpointer usa pra segurar o turno em 'de', 'para', 'e'...)."""
        todas = self.committed + [p.texto for p in self.provisorias]
        return todas[-1].lower().strip(".,;:!?…") if todas else ""

    def has_text(self) -> bool:
        return bool(self.committed or self.provisorias)


class WhisperASR:
    """faster-whisper (ctranslate2). Motor padrão do projeto. Implementa VoiceASR."""
    def __init__(self, settings):
        from faster_whisper import WhisperModel
        device = settings.voice_stt_device
        compute = settings.voice_stt_compute
        modelo = settings.voice_stt_model
        if device in ("auto", "cuda"):
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if device == "cpu":                          # rebaixa p/ caber na CPU (voz vira opcional)
            if modelo.startswith("large"):
                modelo = "base"                      # large na CPU é inviável p/ realtime
            if compute in ("", "float16"):
                compute = "int8"
        if not compute:
            compute = "float16"
        import os
        threads = max(1, (os.cpu_count() or 8) // 2)
        print(f"[stt] whisper {modelo} @ {device} ({compute})", flush=True)
        self.modelo = WhisperModel(modelo, device=device, compute_type=compute,
                                   cpu_threads=threads, num_workers=1)
        self.idioma = settings.voice_language
        self.beam = settings.voice_beam_size

    def transcribe_words(self, audio, prompt="") -> list[Word]:
        segmentos, _ = self.modelo.transcribe(
            audio, language=self.idioma, beam_size=self.beam, word_timestamps=True,
            condition_on_previous_text=False, initial_prompt=prompt or None, vad_filter=False,
            no_repeat_ngram_size=3, temperature=0.0, hallucination_silence_threshold=0.5)
        return [Word(w.word.strip(), w.start, w.end)
                for segmento in segmentos for w in (segmento.words or [])]


class ParakeetASR:
    """NVIDIA Parakeet (NeMo). Alternativa — confunde PT<->ES, NÃO é o padrão.

    O import é lazy: o NeMo só é exigido se voice_stt_engine == 'parakeet'.
    """
    def __init__(self, settings):
        import nemo.collections.asr as nemo_asr   # type: ignore
        self.modelo = nemo_asr.models.ASRModel.from_pretrained(model_name=settings.voice_parakeet_model)
        try:
            self.modelo = self.modelo.to("cuda").eval()
        except Exception:
            pass
        self.stride = settings.voice_parakeet_stride

    def transcribe_words(self, audio, prompt="") -> list[Word]:
        try:
            hipoteses = self.modelo.transcribe([audio], timestamps=True, batch_size=1, verbose=False)
        except TypeError:
            hipoteses = self.modelo.transcribe([audio], timestamps=True)
        if not hipoteses:
            return []
        tempos = getattr(hipoteses[0], "timestamp", None)
        lista_palavras = tempos.get("word") if isinstance(tempos, dict) else None
        resultado: list[Word] = []
        for item in (lista_palavras or []):
            texto = (item.get("word") or "").strip()
            if not texto:
                continue
            inicio, fim = item.get("start"), item.get("end")
            if inicio is None:                       # alguns modelos só dão offsets em frames
                inicio = item.get("start_offset", 0) * self.stride
                fim = item.get("end_offset", 0) * self.stride
            resultado.append(Word(texto, float(inicio), float(fim)))
        return resultado


def make_asr(settings) -> VoiceASR:
    """Fábrica: escolhe o adapter de STT por settings.voice_stt_engine (default = whisper)."""
    if settings.voice_stt_engine == "parakeet":
        return ParakeetASR(settings)
    return WhisperASR(settings)
