import os, shutil, stat, subprocess
from companion.plataform import _IS_TERMUX, _asset

def _mais_x(p: str) -> None:
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IRUSR)

def setup_termux() -> None:
    home = os.path.expanduser("~")
    sc, icons, tasks = f"{home}/.shortcuts", f"{home}/.shortcuts/icons", f"{home}/.shortcuts/tasks"
    os.makedirs(icons, exist_ok=True)
    os.makedirs(tasks, exist_ok=True)
    # 1) entry-point em tasks/ → roda em BACKGROUND (sem abrir o terminal)
    atalho = f"{tasks}/Fala Comigo"
    with open(atalho, "w") as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n"
                'cd "$HOME/brazaia" && python -m companion.gravador start\n')   # chama o gravador Python
    _mais_x(atalho)
    # 2) ícone (asset que já existe, quadrado) → copia (sem imagemagick)
    shutil.copy(_asset("braza_logo_termux.png"), f"{icons}/Fala Comigo.png")
    # (gravador é .py agora — não precisa de +x)
    # 3) permissão das pastas (o Termux:Widget exige leitura+exec) + canal da notificação
    os.chmod(sc, 0o700)
    os.chmod(tasks, 0o700)
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


def setup_tailscale_termux() -> None:
    """CS1 — instala o supervisor do Tailscale nativo no Termux: move os binarios
    (do spike ~/ts/tailscale_*/) -> ~/ts/bin, instala supervisor.sh e o entry do
    Termux:Boot (do repo), e garante o TS_AUTHKEY no ~/.brazaia.env."""
    import glob
    home = os.path.expanduser("~")
    bindir = f"{home}/ts/bin"; os.makedirs(bindir, exist_ok=True)

    for nome in ("tailscale", "tailscaled"):              # 1) binarios -> ~/ts/bin
        destino = f"{bindir}/{nome}"
        if not os.path.exists(destino):
            achados = glob.glob(f"{home}/ts/tailscale_*/{nome}")
            if achados: shutil.copy(achados[0], destino); _mais_x(destino)
            else: print(f"⚠ '{nome}' nao achado em ~/ts/tailscale_*/ — rode o download do spike antes")

    os.makedirs(f"{home}/brazaia", exist_ok=True)         # 2) supervisor -> ~/brazaia/
    shutil.copy("companion/boot/supervisor.sh", f"{home}/brazaia/supervisor.sh")
    _mais_x(f"{home}/brazaia/supervisor.sh")

    os.makedirs(f"{home}/.termux/boot", exist_ok=True)    # 3) entry do Termux:Boot
    shutil.copy("companion/boot/termux-boot.sh", f"{home}/.termux/boot/00-brazaia.sh")
    _mais_x(f"{home}/.termux/boot/00-brazaia.sh")

    envf = f"{home}/.brazaia.env"                         # 4) TS_AUTHKEY no env
    txt = open(envf).read() if os.path.exists(envf) else ""
    if "TS_AUTHKEY" not in txt:
        with open(envf, "a") as f: f.write('\nexport TS_AUTHKEY="tskey-auth-COLE_A_SUA_AQUI"\n')
        print(f"⚠ ponha a sua auth-key em {envf} (TS_AUTHKEY)")
    print("CS1 ok — supervisor + Termux:Boot instalados. (precisa do app Termux:Boot)")


if __name__ == "__main__":
    if _IS_TERMUX:
        setup_termux()
        setup_tailscale_termux()
    else:
        print("setup é só do Termux; no desktop não precisa")
