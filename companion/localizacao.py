"""Localização e bateria do device + FILA local das leituras periódicas.

Duas formas de ler:
  sob demanda (get_location, alguém pediu)  → preciso: GPS; se não achar, rede; se não, a última conhecida
  rastreador (processo contínuo, mantido vivo pelo supervisor.sh) → ADAPTATIVO, como a Linha do tempo do Google
      (medido no export do S24: mediana de 42 s entre pontos em movimento, ≥ 5 min parado):
      a cada 30 s lê a "última conhecida" do Android (instantânea e de graça — aproveita o que o Google já leu);
      sem posição fresca: em movimento pede GPS; parado, 1 ponto a cada 2 min.
  periódica (a cada 15 min, termux-job-scheduler) → só RESERVA se o rastreador estiver morto. O Android
      (Doze/App Standby) adia esse job por horas — medido 04/11: nada das 13:14 às 16h com o celular conectado.

A periódica NÃO depende do server: grava numa fila em disco (~/.brazaia_loc_fila.jsonl). O connect esvazia a
fila quando está conectado e só apaga cada ponto depois do "ack" do server — server fora = nada se perde.

Uso:
  python -m companion.localizacao rastrear    # o rastreador contínuo (o supervisor sobe sozinho)
  python -m companion.localizacao coletar     # 1 leitura barata + bateria → fila (reserva do agendador)
  python -m companion.localizacao teste       # lê agora (preciso) e mostra; não grava
  python -m companion.localizacao fila        # quantos pontos esperando o server
"""
import json, math, os, re, shutil, subprocess, sys, time, uuid
from contextlib import contextmanager

try:
    import fcntl                                  # trava da fila (Termux/Linux); no Windows não há rastreador
except ImportError:
    fcntl = None

FILA = os.path.expanduser("~/.brazaia_loc_fila.jsonl")
PID_RASTREADOR = os.path.expanduser("~/.brazaia_rastreador.pid")
ESTADO = os.path.expanduser("~/.brazaia_estado.json")
_IS_TERMUX = shutil.which("termux-location") is not None


def plataforma() -> str:
    if _IS_TERMUX:
        return "termux"
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _rodar(cmd: list[str], timeout: float, env: dict | None = None) -> tuple[int, str]:
    """Roda e devolve (rc, stdout+stderr). Estourou o tempo → (124, 'timeout')."""
    # Windows: o companion de fundo roda SEM console (VBS escondido); um filho de console (powershell) herdando
    # isso morre com 0xC0000142 (DLL init). CREATE_NO_WINDOW dá a ele um console próprio, invisível.
    kw = {"creationflags": 0x08000000, "stdin": subprocess.DEVNULL} if os.name == "nt" else {}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **env} if env else None, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as e:
        return 127, str(e)


# ── localização ────────────────────────────────────────────────────────────────────────────────────────
def _termux(provedor: str, modo: str, timeout: float) -> dict | str:
    rc, out = _rodar(["termux-location", "-p", provedor, "-r", modo], timeout)
    try:
        d = json.loads(out)
    except ValueError:
        return f"{provedor}/{modo}: {out.strip()[:120] or f'rc={rc}'}"
    if "latitude" not in d:                                   # {"API_ERROR": "..."} = sem permissão, GPS desligado…
        return f"{provedor}/{modo}: {str(d)[:120]}"
    idade = (d.get("elapsedMs") or 0) / 1000 if modo == "last" else 0
    return {"lat": d["latitude"], "lon": d["longitude"], "precisao_m": d.get("accuracy"),
            "fonte": (d.get("provider") or provedor) if modo != "last" else "ultima_conhecida",
            "quando": time.time() - idade}


_PS_WINDOWS = r"""
Add-Type -AssemblyName System.Device
$w = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::High)
$w.Start($false) | Out-Null
$t = 0; while (($w.Status -ne 'Ready') -and ($w.Permission -ne 'Denied') -and ($t -lt 150)) { Start-Sleep -Milliseconds 100; $t++ }
if ($w.Permission -eq 'Denied') { 'NEGADA'; exit }
$l = $w.Position.Location
if ($l.IsUnknown) { 'DESCONHECIDA' } else { '{0};{1};{2}' -f $l.Latitude, $l.Longitude, $l.HorizontalAccuracy }
"""


def _windows() -> dict | str:
    rc, out = _rodar(["powershell", "-NoProfile", "-Command", _PS_WINDOWS], 25)
    out = out.strip().replace(",", ".")
    if out.count(";") == 2:
        lat, lon, prec = (float(x) for x in out.split(";"))
        return {"lat": lat, "lon": lon, "precisao_m": prec, "fonte": "windows", "quando": time.time()}
    if "NEGADA" in out:
        return "localização do Windows negada (Configurações → Privacidade → Localização)"
    return f"windows: {out[:120] or f'rc={rc}'}"


def _linux() -> dict | str:
    demo = next((p for p in ("/usr/libexec/geoclue-2.0/demos/where-am-i", "/usr/lib/geoclue-2.0/demos/where-am-i")
                 if os.path.exists(p)), None)
    if not demo:
        return "linux: GeoClue não instalado (sem fonte de localização)"
    # LC_ALL=C: em pt_BR ele escreve "-16,708100" (vírgula). -t 20: a 1ª posição pode levar uns 10-15 s.
    rc, out = _rodar([demo, "-t", "20", "-a", "8"], 25, env={"LC_ALL": "C"})
    num = r"(-?\d+(?:[.,]\d+)?)"
    lat = re.search(r"Latitude:\s*" + num, out)
    lon = re.search(r"Longitude:\s*" + num, out)
    prec = re.search(r"Accuracy:\s*" + num, out)
    f = lambda m: float(m[1].replace(",", "."))
    if lat and lon:
        fonte = "geoclue-ip" if "ipf fallback" in out or "GeoIP" in out else "geoclue"   # ip = só a cidade
        return {"lat": f(lat), "lon": f(lon), "precisao_m": f(prec) if prec else None,
                "fonte": fonte, "quando": time.time()}
    return f"linux/geoclue: {out.strip()[:120] or f'rc={rc}'}"


def _fixa() -> dict | None:
    """Device que NÃO se mexe (o server em casa): BRAZA_LOCALIZACAO_FIXA="lat,lon" no ambiente/.env dele.
    Desktop não tem GPS — sem isto ele estima por Wi-Fi (~100 m) ou pelo IP (~10 km, a cidade do provedor)."""
    v = os.getenv("BRAZA_LOCALIZACAO_FIXA", "").replace(";", ",")
    try:
        lat, lon = (float(x) for x in v.split(",")[:2])
    except ValueError:
        return None
    return {"lat": lat, "lon": lon, "precisao_m": 10.0, "fonte": "fixa", "quando": time.time()}


def ler_localizacao(preciso: bool = True) -> dict | str:
    """Ponto {lat, lon, precisao_m, fonte, quando} ou o MOTIVO de não ter lido (str)."""
    fixa = _fixa()
    if fixa:
        return fixa
    p = plataforma()
    if p == "termux":
        # pior caso ≈ 20+12+6 s — cabe nos 45 s que o server espera
        tentativas = ([("gps", "once", 20), ("network", "once", 12)] if preciso else [("network", "once", 20)])
        motivos = []
        for prov, modo, t in tentativas + [("passive", "last", 6)]:
            r = _termux(prov, modo, t)
            if isinstance(r, dict):
                return r
            motivos.append(r)
        return "; ".join(motivos)
    if p == "windows":
        return _windows()
    if p == "linux":
        return _linux()
    return f"{p}: sem leitor de localização"


# ── bateria ────────────────────────────────────────────────────────────────────────────────────────────
def ler_estado() -> dict:
    """{"bateria": 0-100, "carregando": bool} — vazio se o device não tem bateria ou não deu pra ler."""
    p = plataforma()
    try:
        if p == "termux":
            rc, out = _rodar(["termux-battery-status"], 10)
            d = json.loads(out)
            return {"bateria": d.get("percentage"), "carregando": d.get("status") in ("CHARGING", "FULL")}
        if p == "linux":
            for bat in sorted(os.listdir("/sys/class/power_supply")):
                base = f"/sys/class/power_supply/{bat}"
                if os.path.exists(f"{base}/capacity"):
                    cap = int(open(f"{base}/capacity").read().strip())
                    st = open(f"{base}/status").read().strip() if os.path.exists(f"{base}/status") else ""
                    return {"bateria": cap, "carregando": st in ("Charging", "Full")}
            return {}
        if p == "windows":
            rc, out = _rodar(["powershell", "-NoProfile", "-Command",
                              "$b=Get-CimInstance Win32_Battery; if($b){'{0};{1}' -f $b.EstimatedChargeRemaining,$b.BatteryStatus}"], 15)
            if ";" in out:
                cap, st = out.strip().split(";")
                return {"bateria": int(cap), "carregando": st.strip() in ("2", "6", "7", "8", "9")}
            return {}                                         # desktop sem bateria
    except (OSError, ValueError, KeyError):
        return {}
    return {}


# ── fila ───────────────────────────────────────────────────────────────────────────────────────────────
@contextmanager
def _trava():
    """O rastreador ESCREVE e o connect REESCREVE (no ack) o mesmo arquivo: sem trava, um ponto gravado entre
    a leitura e o replace do connect sumia."""
    if fcntl is None:
        yield
        return
    with open(FILA + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def enfileirar(ponto: dict, origem: str = "periodica") -> None:
    ponto = {**ponto, "id": uuid.uuid4().hex[:12], "origem": origem}
    with _trava(), open(FILA, "a", encoding="utf-8") as f:
        f.write(json.dumps(ponto) + "\n")


def pendentes(limite: int = 200) -> list[dict]:
    if not os.path.exists(FILA):
        return []
    out = []
    for linha in open(FILA, encoding="utf-8"):
        try:
            out.append(json.loads(linha))
        except ValueError:
            continue                                          # linha cortada (queda no meio da escrita)
        if len(out) >= limite:
            break
    return out


def remover(ids: list[str]) -> None:
    """Tira da fila só o que o server confirmou (ack). Reescreve atômico (tmp + rename)."""
    if not ids or not os.path.exists(FILA):
        return
    tirar = set(ids)
    with _trava():
        restantes = []
        for l in open(FILA, encoding="utf-8"):
            try:
                if json.loads(l).get("id") not in tirar:
                    restantes.append(l if l.endswith("\n") else l + "\n")
            except ValueError:
                continue                                      # linha cortada: descarta (não tem como reenviar)
        tmp = FILA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(restantes)
        os.replace(tmp, FILA)


def salvar_estado(estado: dict) -> None:
    if estado:
        with open(ESTADO, "w", encoding="utf-8") as f:
            json.dump({**estado, "quando": time.time()}, f)


def estado_salvo() -> dict:
    try:
        return json.load(open(ESTADO, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def coletar() -> None:
    """RESERVA (agendador, 15 min): leitura barata → fila; bateria → arquivo. Sem rede, sem server.
    Rastreador vivo → não faz nada (ele já cobre, com muito mais frequência)."""
    if _rastreador_vivo():
        return
    r = ler_localizacao(preciso=False)
    if isinstance(r, dict):
        enfileirar(r)
        print(time.strftime("%H:%M"), "ponto na fila:", round(r["lat"], 5), round(r["lon"], 5), r.get("fonte"))
    else:
        print(time.strftime("%H:%M"), "sem localização:", r)
    salvar_estado(ler_estado())


# ── rastreador contínuo (adaptativo) ───────────────────────────────────────────────────────────────────
TICK_S = 30            # de quanto em quanto tempo olha (o Google: ~30–45 s em movimento)
PARADO_S = 120         # parado: 1 ponto a cada 2 min (o Google no S24, parado no trabalho: 09:14, 09:16, 09:18…)
FRESCO_S = 60          # "última conhecida" mais velha que isto não serve como posição de agora
RAIO_M = 40            # andou menos que isto (ou que a precisão) = parado


def _dist_m(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


_motivos: list[str] = []          # por que as leituras do tick falharam (vai pro log quando fica sem ponto)


def _fix(provedor: str, modo: str, timeout: float) -> dict | None:
    """Uma leitura do termux-location com a IDADE real do fix (elapsedMs) e o provedor que mediu."""
    rc, out = _rodar(["termux-location", "-p", provedor, "-r", modo], timeout)
    try:
        d = json.loads(out)
    except ValueError:
        _motivos.append(f"{provedor}/{modo}: {out.strip()[:80] or f'rc={rc}'}")
        return None
    if "latitude" not in d:
        _motivos.append(f"{provedor}/{modo}: {str(d)[:80]}")
        return None
    idade = (d.get("elapsedMs") or 0) / 1000 if modo == "last" else 0
    return {"lat": d["latitude"], "lon": d["longitude"], "precisao_m": d.get("accuracy"),
            "velocidade_ms": d.get("speed"), "fonte": d.get("provider") or provedor,
            "quando": time.time() - idade, "idade_s": idade}


def _mais_fresca() -> dict | None:
    """A 'última conhecida' mais nova entre GPS e rede — instantânea: não liga o GPS, aproveita quem ligou."""
    fixes = [f for f in (_fix("gps", "last", 8), _fix("network", "last", 8)) if f]
    return min(fixes, key=lambda f: f["idade_s"]) if fixes else None


def _rastreador_vivo() -> bool:
    try:
        pid = int(open(PID_RASTREADOR).read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def rastrear() -> None:
    if _rastreador_vivo():
        print("rastreador já está rodando"); return
    with open(PID_RASTREADOR, "w") as f:
        f.write(str(os.getpid()))
    print(time.strftime("%d/%m %H:%M:%S"), "rastreador no ar (tick 30 s, parado 1 ponto/2 min)", flush=True)
    ultimo: dict | None = None
    ultimo_mov = 0.0                  # última vez que andou de verdade
    ultimo_estado = 0.0
    while True:
        t0 = time.time()
        try:
            movendo = t0 - ultimo_mov < PARADO_S
            _motivos.clear()
            p = _mais_fresca()
            if p is None or p["idade_s"] > FRESCO_S:
                vencido = ultimo is None or t0 - ultimo["quando"] >= PARADO_S
                if movendo or vencido:        # sem posição fresca: pede uma (GPS se está andando, rede se parado)
                    velha = p
                    p = (_fix("gps", "once", 20) if movendo else None) or _fix("network", "once", 15)
                    if p is None and not movendo:
                        p = _fix("gps", "once", 20)          # rede não respondeu (04/11: parado 16:17→16:33 sem ponto)
                    if p is None:
                        p = velha
                    sem_ponto = t0 - (ultimo["quando"] if ultimo else t0)
                    if (p is None or ultimo is None or p["quando"] <= ultimo["quando"] + 1) and sem_ponto >= 2 * PARADO_S:
                        print(time.strftime("%H:%M:%S"), f"sem posição nova há {round(sem_ponto)}s",
                              f"(última conhecida: {round(velha['idade_s'])}s)" if velha else "(sem última conhecida)",
                              "· falhas:", "; ".join(_motivos) or "nenhuma (leitura repetida)", flush=True)
            if p is not None and (ultimo is None or p["quando"] > ultimo["quando"] + 1):
                d = _dist_m(ultimo, p) if ultimo else float("inf")
                andou = ultimo is None or d > max(RAIO_M, min(p.get("precisao_m") or 0, 150)) \
                    or (p.get("velocidade_ms") or 0) > 1.5
                if andou and ultimo is not None:
                    ultimo_mov = t0
                if andou or t0 - ultimo["quando"] >= PARADO_S:
                    ponto = {k: v for k, v in p.items() if k not in ("idade_s", "velocidade_ms")}
                    enfileirar(ponto, origem="rastreador")
                    ultimo = p
                    print(time.strftime("%H:%M:%S"), "andando" if t0 - ultimo_mov < PARADO_S else "parado",
                          round(p["lat"], 5), round(p["lon"], 5), p["fonte"], f"±{round(p.get('precisao_m') or 0)}m",
                          f"idade {round(p['idade_s'])}s", flush=True)
            if t0 - ultimo_estado >= PARADO_S:
                salvar_estado(ler_estado())
                ultimo_estado = t0
        except Exception as e:                # nunca morre por uma leitura ruim
            print(time.strftime("%H:%M:%S"), "erro:", e, flush=True)
        time.sleep(max(1.0, TICK_S - (time.time() - t0)))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "teste"
    if cmd == "rastrear":
        rastrear()
    elif cmd == "coletar":
        coletar()
    elif cmd == "fila":
        print(f"{len(pendentes(10_000))} ponto(s) esperando o server em {FILA}")
    else:
        print("plataforma:", plataforma())
        print("localização:", ler_localizacao(preciso=True))
        print("estado:", ler_estado())
