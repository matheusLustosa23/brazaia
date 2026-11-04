"""Permissões do device — pedidas UMA vez no setup, guardadas, e enviadas ao server em toda conexão.

No Android não existe "conceder tudo" por código: cada permissão só aparece na 1ª vez que o Termux:API a USA.
Então o setup USA cada uma em sequência (foto descartável, 1 s de microfone, uma leitura de localização…) e o
dono toca "Permitir" uma vez em cada. Depois disso nada mais pede.

Exceção que nenhum app concede sozinho: localização EM SEGUNDO PLANO ("Permitir o tempo todo", Android 10+) —
o setup abre a tela de configuração do Termux:API e explica o que tocar.

Uso:
  python -m companion permissoes          # pede o que falta (Termux) / testa (desktop) e mostra a tabela
  python -m companion permissoes ver      # só mostra o que está guardado
"""
import json, os, shutil, subprocess, sys, time

from companion.localizacao import _rodar, ler_estado, ler_localizacao, plataforma

ARQ = os.path.expanduser("~/.brazaia_permissoes.json")
NOMES = {"camera": "câmera", "microfone": "microfone", "localizacao": "localização",
         "localizacao_fundo": "localização em 2º plano", "arquivos": "arquivos", "notificacao": "notificação",
         "bateria": "bateria (sem economia)", "navegador": "abrir no navegador"}


def carregar() -> dict:
    """{nome: "ok" | "negada" | "manual" | "n/a" | "falhou: ..."} — o que o setup apurou (vazio se nunca rodou)."""
    try:
        return json.load(open(ARQ, encoding="utf-8")).get("permissoes", {})
    except (OSError, ValueError):
        return {}


def salvar(perms: dict) -> None:
    with open(ARQ, "w", encoding="utf-8") as f:
        json.dump({"permissoes": perms, "quando": time.time(), "plataforma": plataforma()}, f, ensure_ascii=False)


def atualizar(nome: str, valor: str) -> None:
    """Uso em execução (ex.: o get_location falhou por permissão) — mantém o arquivo honesto."""
    perms = carregar()
    if perms.get(nome) != valor:
        perms[nome] = valor
        salvar(perms)


def _passo(nome: str, instrucao: str) -> None:
    print(f"\n▶ {NOMES[nome]}: {instrucao}", flush=True)


def _termux() -> dict:
    p: dict[str, str] = {}
    tmp = os.path.expanduser("~/.perm_teste")

    _passo("notificacao", "vai aparecer uma notificação de teste")
    rc, out = _rodar(["termux-notification", "--id", "brazaia-perm", "--title", "Brazaia",
                      "--content", "teste de permissão"], 15)
    p["notificacao"] = "ok" if rc == 0 else f"falhou: {out.strip()[:80]}"
    _rodar(["termux-notification-remove", "brazaia-perm"], 5)

    _passo("camera", "toque PERMITIR se o Android perguntar (a foto é descartada)")
    rc, out = _rodar(["termux-camera-photo", "-c", "0", tmp + ".jpg"], 30)
    p["camera"] = "ok" if rc == 0 and os.path.exists(tmp + ".jpg") and os.path.getsize(tmp + ".jpg") > 0 \
        else f"negada/falhou: {out.strip()[:80]}"

    _passo("microfone", "toque PERMITIR (grava 1 s e apaga)")
    _rodar(["termux-microphone-record", "-q"], 5)                   # 1 gravação por vez: encerra qualquer resto
    rc, out = _rodar(["termux-microphone-record", "-f", tmp + ".m4a", "-l", "1"], 10)
    time.sleep(2)
    _rodar(["termux-microphone-record", "-q"], 5)
    p["microfone"] = "ok" if os.path.exists(tmp + ".m4a") and os.path.getsize(tmp + ".m4a") > 0 \
        else f"negada/falhou: {out.strip()[:80]}"

    _passo("localizacao", "toque PERMITIR ('Durante o uso do app' serve por enquanto)")
    r = ler_localizacao(preciso=False)
    p["localizacao"] = "ok" if isinstance(r, dict) else f"negada/falhou: {str(r)[:80]}"

    _passo("arquivos", "toque PERMITIR (acesso ao armazenamento: ~/storage)")
    if not os.path.isdir(os.path.expanduser("~/storage")):
        subprocess.run(["termux-setup-storage"], check=False)
        time.sleep(4)
    p["arquivos"] = "ok" if os.path.isdir(os.path.expanduser("~/storage/shared")) else "negada"

    _passo("bateria", "na tela que abrir, escolha 'Permitir' / 'Sem restrições' pro Termux (o Doze mata o companion)")
    subprocess.run(["am", "start", "-a", "android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
                    "-d", "package:com.termux"], capture_output=True)
    input("   (Enter quando terminar) ")
    p["bateria"] = "manual"

    _passo("localizacao_fundo", "abre os ajustes do Termux:API → Permissões → Localização → 'Permitir o tempo todo'. "
           "Sem isso a coleta de 15 em 15 min falha com a tela apagada.")
    subprocess.run(["am", "start", "-a", "android.settings.APPLICATION_DETAILS_SETTINGS",
                    "-d", "package:com.termux.api"], capture_output=True)
    input("   (Enter quando terminar) ")
    p["localizacao_fundo"] = "manual"

    p["navegador"] = "ok" if shutil.which("termux-open") else "n/a"
    for ext in (".jpg", ".m4a"):
        try:
            os.remove(tmp + ext)
        except OSError:
            pass
    return p


def _desktop() -> dict:
    p: dict[str, str] = {"notificacao": "ok", "arquivos": "ok", "navegador": "ok", "bateria": "n/a",
                         "localizacao_fundo": "n/a"}
    try:
        import cv2                                                   # type: ignore
        cap = cv2.VideoCapture(0)
        ok, _ = cap.read()
        cap.release()
        p["camera"] = "ok" if ok else "sem câmera"
    except Exception as e:
        p["camera"] = f"falhou: {type(e).__name__}"
    try:
        import sounddevice as sd                                     # type: ignore
        p["microfone"] = "ok" if any(d.get("max_input_channels", 0) > 0 for d in sd.query_devices()) else "sem microfone"
    except Exception as e:
        p["microfone"] = f"falhou: {type(e).__name__}"
    r = ler_localizacao(preciso=True)
    p["localizacao"] = "ok" if isinstance(r, dict) else f"indisponível: {str(r)[:80]}"
    if ler_estado():
        p["bateria"] = "ok"
    return p


def tabela(perms: dict) -> str:
    if not perms:
        return "(nenhuma permissão verificada ainda — rode: python -m companion permissoes)"
    ic = lambda v: "✅" if v == "ok" else ("✋" if v == "manual" else ("—" if v == "n/a" else "❌"))
    return "\n".join(f"  {ic(v)} {NOMES.get(k, k):<26} {v}" for k, v in perms.items())


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "ver":
        print(tabela(carregar()))
        return
    print(f"Verificando permissões ({plataforma()}) — uma vez só; o resultado vai pro server em toda conexão.")
    perms = _termux() if plataforma() == "termux" else _desktop()
    salvar(perms)
    print("\nResultado:\n" + tabela(perms))
    print(f"\nGuardado em {ARQ}. Reconecte o device (ou reinicie o companion) pro server saber.")


if __name__ == "__main__":
    main()
