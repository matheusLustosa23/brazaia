import os, shutil, stat, subprocess
from companion.plataform import _IS_TERMUX, _asset

def _mais_x(p: str) -> None:
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IRUSR)

def setup_termux() -> None:
    home = os.path.expanduser("~")
    sc, icons = f"{home}/.shortcuts", f"{home}/.shortcuts/icons"
    os.makedirs(icons, exist_ok=True)
    # 1) entry-point do widget → chama o gravador Python
    atalho = f"{sc}/Fala Comigo"
    with open(atalho, "w") as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n"
                'cd "$HOME/brazaia" && python -m companion.gravador start\n')   # chama o gravador Python
    _mais_x(atalho)
    # 2) ícone (asset que já existe, quadrado) → copia (sem imagemagick)
    shutil.copy(_asset("braza_logo_termux.png"), f"{icons}/Fala Comigo.png")
    # (gravador é .py agora — não precisa de +x)
    # 3) permissão da pasta (o Termux:Widget exige) + canal da notificação
    os.chmod(sc, 0o700)
    subprocess.run(["termux-notification-channel", "--id", "brazaia",
                    "--name", "Brazaia", "--importance", "max"], check=False)
    # 4) config por-dispositivo (FORA do repo) — cria template se não existir
    envf = f"{home}/.brazaia.env"
    if not os.path.exists(envf):
        with open(envf, "w") as f:
            f.write('export SERVER_WS_URL="ws://100.79.27.100:8080/api/v1"\n'
                    'export DEVICE_ID="celular_01"\n'
                    'export DEVICE_NAME="Celular"\n')
        print(f"criado {envf} — confira o IP do server (SERVER_WS_URL)")
    print("setup ok — agora arraste o widget 'Fala Comigo' na tela inicial")

if __name__ == "__main__":
    setup_termux() if _IS_TERMUX else print("setup é só do Termux; no desktop não precisa")
