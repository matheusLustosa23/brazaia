import asyncio, os, subprocess, sys, time
from companion.config import load_config

REC = os.path.expanduser("~/rec.aac")
IMG = os.path.expanduser("~/brazaia/companion/assets/images/braza_logo_full.png")
CHAMAR = "cd $HOME/brazaia && python -m companion.gravador"       # como a notificação chama de volta

def _notif(titulo: str, botao: str, acao: str) -> None:
    subprocess.run(["termux-notification", "--id", "42", "--ongoing", "--alert-once",
                    "--priority", "max", "--image-path", IMG, "--title", titulo,
                    "--button1", botao, "--button1-action", f"{CHAMAR} {acao}"])

def start() -> None:
    if os.path.exists(REC):
        os.remove(REC)                                            # mic-record NÃO sobrescreve → apaga o turno anterior
    subprocess.run(["termux-microphone-record", "-e", "aac", "-c", "1", "-b", "128", "-l", "0", "-f", REC])
    _notif("🔴 Ouvindo…", "Parar", "parar")

def parar() -> None:
    from companion.voice_turn import enviar_arquivo             # LAZY: start() não paga o import de websockets/voice_turn
    subprocess.run(["termux-microphone-record", "-q"]); time.sleep(1)
    try:
        texto = asyncio.run(enviar_arquivo(load_config(), REC))   # manda pro server + toca + RETORNA a transcrição
    except Exception as e:
        texto = f"[erro: {e}]"                                    # server fora? não trava a notificação
    subprocess.run(["termux-toast", f"[você disse] {texto}"])     # DEBUG na hora
    with open(os.path.expanduser("~/voz_debug.log"), "a") as f:   # DEBUG histórico
        f.write(f"[você disse] {texto}\n")
    _notif("🎙️ Fala Comigo", "Falar de novo", "start")

if __name__ == "__main__":
    (parar if (len(sys.argv) > 1 and sys.argv[1] == "parar") else start)()
