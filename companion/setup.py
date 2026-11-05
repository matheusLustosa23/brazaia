import os, shutil, stat, subprocess
from companion import DADOS, caminho
from companion.plataform import _IS_TERMUX, _asset

# Scripts de boot/supervisor são instalados em ~/.brazaia (DADOS), copiados de DENTRO do pacote — o celular não
# precisa mais do repositório (antes: ~/brazaia era o repo e os scripts vinham de "companion/boot/...").

def _mais_x(p: str) -> None:
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IRUSR)

def setup_termux() -> None:
    home = os.path.expanduser("~")
    # as libs já vieram com o pacote (pip install …whl[cli]); nada a instalar aqui
    sc, icons, tasks = f"{home}/.shortcuts", f"{home}/.shortcuts/icons", f"{home}/.shortcuts/tasks"
    os.makedirs(icons, exist_ok=True)
    os.makedirs(tasks, exist_ok=True)
    # 1) entry-point em tasks/ → roda em BACKGROUND (sem abrir o terminal)
    atalho = f"{tasks}/Fala Comigo"
    with open(atalho, "w") as f:
        f.write("#!/data/data/com.termux/files/usr/bin/bash\n"
                'python -m companion.gravador start\n')   # pacote instalado: roda de qualquer pasta
    _mais_x(atalho)
    # 2) ícone (asset que já existe, quadrado) → copia (sem imagemagick)
    shutil.copy(_asset("braza_logo_termux.png"), f"{icons}/Fala Comigo.png")
    # (gravador é .py agora — não precisa de +x)
    # 3) permissão das pastas (o Termux:Widget exige leitura+exec) + canal da notificação
    os.chmod(sc, 0o700)
    os.chmod(tasks, 0o700)
    subprocess.run(["termux-notification-channel", "brazaia", "Brazaia"], check=False)  # posicional (id nome)
    # 4) config por-dispositivo (FORA do repo) — cria template se não existir
    envf = f"{home}/.brazaia.env"
    if not os.path.exists(envf):
        with open(envf, "w") as f:
            f.write('export SERVER_WS_URL="ws://100.79.27.100:8080/api/v1"\n'
                    'export DEVICE_ID="celular_01"\n'
                    'export DEVICE_NAME="Celular"\n')
        print(f"criado {envf} — confira o IP do server (SERVER_WS_URL)")
    print("setup ok — agora arraste o widget 'Fala Comigo' na tela inicial")


def baixar_tailscale(bindir: str) -> bool:
    """Binários estáticos do Tailscale (tailscale + tailscaled) da página oficial → bindir. Internet pública,
    sem proxy (ainda não há tailnet). Antes era cópia à mão de um download antigo ("spike")."""
    import io, json, platform, tarfile, urllib.request
    arq = {"aarch64": "arm64", "arm64": "arm64", "armv7l": "arm", "armv8l": "arm", "x86_64": "amd64"}.get(platform.machine())
    if not arq:
        print(f"⚠ arquitetura {platform.machine()} sem binário do Tailscale conhecido"); return False
    try:
        idx = json.load(urllib.request.urlopen("https://pkgs.tailscale.com/stable/?mode=json", timeout=30))
        nome = idx["Tarballs"][arq]
        print(f"baixando {nome}…")
        dados = urllib.request.urlopen(f"https://pkgs.tailscale.com/stable/{nome}", timeout=300).read()
        with tarfile.open(fileobj=io.BytesIO(dados)) as tar:
            for m in tar.getmembers():
                base = m.name.rsplit("/", 1)[-1]
                arq = tar.extractfile(m) if m.isfile() else None     # None = não é arquivo comum (pasta/link)
                if base in ("tailscale", "tailscaled") and arq is not None:
                    with open(f"{bindir}/{base}", "wb") as f:
                        f.write(arq.read())
                    _mais_x(f"{bindir}/{base}")
        return os.path.exists(f"{bindir}/tailscaled")
    except Exception as e:
        print(f"⚠ não consegui baixar o Tailscale: {e}"); return False


def aplicar_kit(kit: str) -> None:
    """KIT = base64 de {servidor, device_id, device_name, ts_authkey} — gerado no servidor (ops/companion_kit.py,
    depois o painel). Grava/atualiza o ~/.brazaia.env: assim a única coisa manual é a chave do Tailscale, que vem nele."""
    import base64, json
    d = json.loads(base64.urlsafe_b64decode(kit + "=" * (-len(kit) % 4)))
    envf = os.path.expanduser("~/.brazaia.env")
    linhas = [l for l in (open(envf).read().splitlines() if os.path.exists(envf) else [])
              if not l.removeprefix("export ").split("=", 1)[0].strip() in
              ("SERVER_WS_URL", "DEVICE_ID", "DEVICE_NAME", "TS_AUTHKEY", "SOCKS_PROXY")]
    linhas += [f'export SERVER_WS_URL="ws://{d["servidor"]}/api/v1"', f'export DEVICE_ID="{d["device_id"]}"',
               f'export DEVICE_NAME="{d["device_name"]}"', f'export TS_AUTHKEY="{d["ts_authkey"]}"',
               'export SOCKS_PROXY="socks5://localhost:1055"']
    with open(envf, "w") as f:
        f.write("\n".join(linhas) + "\n")
    os.chmod(envf, 0o600)                                  # tem a chave do Tailscale
    print(f"kit aplicado: device {d['device_id']} → {d['servidor']} ({envf})")


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
            elif not baixar_tailscale(bindir): print(f"⚠ '{nome}' não instalado — sem ele o device não entra na tailnet")

    os.makedirs(DADOS, exist_ok=True)                     # 2) supervisor -> ~/.brazaia/
    shutil.copy(caminho("boot", "supervisor.sh"), f"{DADOS}/supervisor.sh")
    _mais_x(f"{DADOS}/supervisor.sh")

    os.makedirs(f"{home}/.termux/boot", exist_ok=True)    # 3) entry do Termux:Boot
    shutil.copy(caminho("boot", "termux-boot.sh"), f"{home}/.termux/boot/00-brazaia.sh")
    _mais_x(f"{home}/.termux/boot/00-brazaia.sh")

    shutil.copy(caminho("boot", "healthcheck.sh"), f"{DADOS}/healthcheck.sh")   # 3b) watchdog
    _mais_x(f"{DADOS}/healthcheck.sh")
    subprocess.run(["termux-job-scheduler", "--script", f"{DADOS}/healthcheck.sh",  # a cada 15min, sobrevive a kill/reboot
                    "--period-ms", "900000", "--persisted", "true", "--job-id", "1"], check=False)

    envf = f"{home}/.brazaia.env"                         # 4) TS_AUTHKEY no env
    txt = open(envf).read() if os.path.exists(envf) else ""
    if "TS_AUTHKEY" not in txt:
        with open(envf, "a") as f: f.write('\nexport TS_AUTHKEY="tskey-auth-COLE_A_SUA_AQUI"\n')
        print(f"⚠ ponha a sua auth-key em {envf} (TS_AUTHKEY)")
    if "SOCKS_PROXY" not in txt:                           # CS2b: companion sai pelo tailscaled nativo
        with open(envf, "a") as f: f.write('export SOCKS_PROXY="socks5://localhost:1055"\n')
    print("CS1/CS2b ok — supervisor + Termux:Boot + SOCKS_PROXY. (precisa do app Termux:Boot)")


def _destinos_scripts() -> dict[str, str]:
    """Script de dentro do pacote → onde ele fica instalado no device."""
    return {"supervisor.sh": f"{DADOS}/supervisor.sh", "healthcheck.sh": f"{DADOS}/healthcheck.sh",
            "localizacao.sh": f"{DADOS}/localizacao.sh",
            "termux-boot.sh": os.path.expanduser("~/.termux/boot/00-brazaia.sh")}


def instalar_scripts() -> list[str]:
    """Recopia os scripts de boot do pacote (chamado pelo connect DEPOIS de se atualizar). Devolve os que mudaram.
    Sem isto, uma correção no supervisor.sh (ex.: o PATH limpo do Tailscale, 04/11) nunca chegava num device já
    instalado — a atualização trocava só o Python. Troca ATÔMICA (arquivo novo + rename): um bash que esteja rodando
    o script antigo continua lendo a cópia antiga (outro inode) até ser reiniciado — nunca lê metade de cada."""
    mudaram = []
    for nome, destino in _destinos_scripts().items():
        novo = open(caminho("boot", nome), "rb").read()
        if not os.path.exists(os.path.dirname(destino)):
            continue                                       # parte não instalada neste device (ex.: sem Termux:Boot)
        if os.path.exists(destino) and open(destino, "rb").read() == novo:
            continue
        tmp = destino + ".novo"
        with open(tmp, "wb") as f:
            f.write(novo)
        _mais_x(tmp)
        os.replace(tmp, destino)
        mudaram.append(nome)
    return mudaram


def setup_ssh_termux() -> None:
    """Canal de MANUTENÇÃO: sshd do Termux (porta 8022), só por chave — as de companion/boot/ssh_autorizadas.pub.
    Pra quando o companion cair com o celular longe (05/11: celular2 ficou fora sem como entrar). O tailscaled
    userspace repassa o que chega no IP da tailnet pras portas locais → ssh -p 8022 <ip-tailnet> (só pela tailnet)."""
    home = os.path.expanduser("~")
    if not shutil.which("sshd"):
        print("instalando openssh…")
        subprocess.run(["pkg", "install", "-y", "openssh"], check=False)
    if not shutil.which("sshd"):
        print("⚠ openssh não instalou — SSH de manutenção fica sem"); return
    os.makedirs(f"{home}/.ssh", exist_ok=True)
    os.chmod(f"{home}/.ssh", 0o700)
    ak = f"{home}/.ssh/authorized_keys"
    atuais = set(open(ak).read().splitlines()) if os.path.exists(ak) else set()
    novas = [l.strip() for l in open(caminho("boot", "ssh_autorizadas.pub")) if l.strip() and not l.startswith("#")]
    with open(ak, "a") as f:
        for chave in novas:
            if chave not in atuais:
                f.write(chave + "\n")
    os.chmod(ak, 0o600)
    cfg = os.path.join(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"), "etc", "ssh", "sshd_config")
    linhas = [l for l in (open(cfg).read().splitlines() if os.path.exists(cfg) else [])
              if not l.strip().startswith(("PasswordAuthentication", "KbdInteractiveAuthentication"))]
    linhas += ["PasswordAuthentication no", "KbdInteractiveAuthentication no"]   # só chave, nunca senha
    with open(cfg, "w") as f:
        f.write("\n".join(linhas) + "\n")
    subprocess.run(["pkill", "-x", "sshd"], check=False)
    subprocess.run(["sshd"], check=False)                 # o supervisor mantém vivo daqui pra frente
    usuario = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    print(f"SSH ok — porta 8022, só por chave ({len(novas)} autorizadas) · usuário: {usuario}")


def setup_localizacao_termux() -> None:
    """P2 — coleta de localização + bateria a cada 15 min (job 2 do JobScheduler; o job 1 é o healthcheck)."""
    home = os.path.expanduser("~")
    os.makedirs(DADOS, exist_ok=True)
    destino = f"{DADOS}/localizacao.sh"
    shutil.copy(caminho("boot", "localizacao.sh"), destino)
    _mais_x(destino)
    subprocess.run(["termux-job-scheduler", "--script", destino, "--period-ms", "900000",
                    "--persisted", "true", "--job-id", "2"], check=False)
    print("P2 ok — localização + bateria de 15 em 15 min (fila em ~/.brazaia_loc_fila.jsonl)")


if __name__ == "__main__":
    import sys
    from companion import permissoes
    if "--ssh" in sys.argv:                    # device já instalado: só o canal de manutenção
        setup_ssh_termux()
        sys.exit(0)
    if "--kit" in sys.argv:
        aplicar_kit(sys.argv[sys.argv.index("--kit") + 1])
    if _IS_TERMUX:
        setup_termux()
        setup_tailscale_termux()
        setup_localizacao_termux()
        setup_ssh_termux()
    else:
        print("desktop: só as permissões (o resto do setup é do Termux)")
    permissoes.main()                          # por último: pede/testa cada permissão UMA vez e guarda
