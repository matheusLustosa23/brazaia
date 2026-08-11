"""Bateria TOTAL de orquestração — roda todas as tools por HTTP e produz um relatório final
parseando o router_trace.log (só as linhas geradas nesta rodada).

Cobre: tools sozinhas · encarrilhadas · repetidas na mesma frase · multi 4–7 tools · honestidade.
Avalia: nº de tools no plano · tools executadas · divergências (juiz) · omissões · bloqueios · force · iterações.

Uso:
    uv run python scripts/bateria_total.py
    BASE=http://IP:8080/api/v1 KEY=change-me uv run python scripts/bateria_total.py
    uv run python scripts/bateria_total.py --grupo MULTI       # só um grupo
Assume ubuntu+celular conectados e 'server' offline (casos de honestidade).
"""
import os, sys, json, time, re, urllib.request

BASE = os.getenv("BASE", "http://100.72.108.111:8080/api/v1")
KEY = os.getenv("KEY", "change-me")
TRACE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "router_trace.log")

TESTS = {
 "SINGLES": [
  ("S01_render",   "renderiza a formula de bhaskara"),
  ("S02_dmath",    "mostra a materia de derivadas na tela do ubuntu"),
  ("S03_dpage",    "faz uma tabela comparando 3 planos de internet no ubuntu"),
  ("S04_notify",   "avisa no ubuntu que o deploy terminou"),
  ("S05_lembrar",  "anota que amanha tenho reuniao as 10 da manha"),
  ("S06_capture",  "olha a webcam e me diz o que voce ve"),
  ("S07_chit",     "oi, tudo bem?"),
  ("S08_render2",  "gera a equacao da energia cinetica"),
  ("S09_notifycel","manda um aviso pro celular que o build passou"),
  ("S10_dmathcel", "abre uma lista de exercicios de fracao no navegador do celular"),
 ],
 "PARES": [
  ("P01_rn_ub",    "gera a formula de bhaskara e manda pro ubuntu"),
  ("P02_ro_cel",   "renderiza a formula da area do circulo e abre em tela cheia no celular"),
  ("P03_cap_not",  "tira uma foto da webcam e manda pro ubuntu"),
  ("P04_dm_not",   "mostra os exercicios de logaritmo no ubuntu e me avisa no celular"),
  ("P05_lem_not",  "anota que tenho prova quinta e avisa o ubuntu disso"),
  ("P06_rn_cel",   "gera a formula de limites e manda pro celular"),
  ("P07_ro_ub",    "gera a fatoracao de x2-5x+6 e abre em tela cheia no ubuntu"),
  ("P08_cap_open", "tira uma foto da webcam e abre em tela cheia no ubuntu"),
  ("P09_dp_not",   "faz um card de boas vindas no ubuntu e avisa o celular"),
  ("P10_dm_nav",   "gera um problema de produtos notaveis e mostra no navegador do celular"),
 ],
 "REPETIDAS": [
  ("D01_2notify",  "avisa o ubuntu e o celular que o backup terminou"),
  ("D02_2cap",     "captura a frontal e a traseira do celular"),
  ("D03_2render",  "gera a formula de bhaskara e a formula da area do circulo"),
  ("D04_2open",    "gera bhaskara e area do circulo e abre as duas em tela cheia no ubuntu"),
  ("D05_2notmsg",  "avisa o ubuntu que o build passou e depois que o deploy subiu"),
  ("D06_2dmath",   "mostra derivadas no ubuntu e integrais no celular"),
  ("D07_2notdev",  "avisa o ubuntu e o celular do backup, e depois avisa o ubuntu do restart"),
  ("D08_2rn",      "gera as formulas de bhaskara e de limites e manda as duas pro ubuntu"),
 ],
 "MULTI": [
  ("M01_4tool", "captura a webcam, gera a formula de bhaskara, manda a formula pro ubuntu e abre a foto capturada em tela cheia no ubuntu"),
  ("M02_5tool", "gera a formula de bhaskara e manda pro ubuntu, gera a formula da area do circulo e manda pro celular, e anota que revisei geometria"),
  ("M03_6tool", "captura a traseira do celular, gera bhaskara, mostra a formula no navegador do ubuntu, manda a formula pro celular, abre a foto capturada em tela cheia no ubuntu, e anota que estudei"),
  ("M04_7tool", "captura uma foto do ubuntu, renderiza a formula dos produtos notaveis, notifica o ubuntu que a formula foi renderizada, abre a foto do ubuntu no celular em tela cheia, captura a traseira do celular, renderiza a formula no navegador do ubuntu, e por fim abre a foto do celular em tela cheia no ubuntu"),
  ("M05_5mix",  "gera bhaskara, mostra no navegador do ubuntu, manda pro celular, anota que estudei, e avisa o ubuntu que terminei"),
 ],
 "HONESTIDADE": [
  ("H01_notoff",  "avisa no server que o deploy terminou"),
  ("H02_dmoff",   "mostra a materia de derivadas no server"),
  ("H03_openoff", "gera a formula de bhaskara e abre em tela cheia no server"),
  ("H04_camnf",   "captura uma foto do tablet e me diz o que ve"),
  ("H05_noimg",   "abre a ultima foto em tela cheia no ubuntu"),
  ("H06_noload",  "olha de novo aquela foto que apareceu antes"),
  ("H07_swap",    "manda a formula de bhaskara pro server"),
  ("H08_mixoff",  "gera bhaskara, manda pro ubuntu, e abre em tela cheia no server"),
 ],
}


def send(sid: str, msg: str, timeout: int = 240) -> str:
    data = json.dumps({"message": msg, "session_id": sid, "stream": False}).encode()
    req = urllib.request.Request(BASE + "/chat", data=data,
                                 headers={"x-api-key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
            return (d.get("data", {}) or {}).get("reply") or "(VAZIO!)"
    except Exception as e:
        return f"(ERRO: {type(e).__name__})"


def _linhas() -> int:
    return sum(1 for _ in open(TRACE, encoding="utf-8", errors="replace")) if os.path.exists(TRACE) else 0


def relatorio(linhas_novas: list[str]) -> None:
    reqs, cur = [], None
    for l in linhas_novas:
        if "REQUEST:" in l:
            if cur: reqs.append(cur)
            cur = {"req": l.split("REQUEST:")[1].strip()[:50], "plano": 0, "exec": 0,
                   "da": 0, "dr": 0, "om": "", "blq": 0, "force": 0, "it": 0}
        if cur is None: continue
        if "[router-agente] plano=" in l: cur["plano"] = l.count("'tool'")
        if "[execute tool]" in l: cur["exec"] += 1
        if "JUIZ (divergencia)" in l: cur["da" if "'aceita': True" in l else "dr"] += 1
        if "JUIZ (omissao)]" in l: cur["om"] += "R" if "RESPONDER" in l else "E"
        if "[bloqueado]" in l or "[falha]" in l: cur["blq"] += 1
        if re.search(r"\[force", l): cur["force"] += 1
        if "ITERAÇÃO DO LOOP" in l: cur["it"] += 1
    if cur: reqs.append(cur)

    print("\n" + "=" * 92)
    print(f"{'request':<50} {'plan':>4} {'exec':>4} {'div':>6} {'omiss':>6} {'blq':>3} {'frc':>3} {'it':>3}")
    print("-" * 92)
    tf = 0
    for r in reqs:
        div = f"{r['da']}✓/{r['dr']}✗" if (r["da"] + r["dr"]) else "-"
        tf += r["force"]
        print(f"{r['req']:<50} {r['plano']:>4} {r['exec']:>4} {div:>6} {(r['om'] or '-'):>6} {r['blq']:>3} {r['force']:>3} {r['it']:>3}")
    print("-" * 92)
    print(f"requests: {len(reqs)} · FORCE total: {tf}  {'✅' if tf == 0 else '❌ (loop nao aterrado!)'}")
    print("legenda: div=juiz divergencia (aceita/rejeita) · omiss=juiz omissao (R=responder E=executar) · blq=bloqueios · frc=force · it=iteracoes")


def main():
    grupo = None
    if "--grupo" in sys.argv:
        grupo = sys.argv[sys.argv.index("--grupo") + 1].upper()
    base = _linhas()
    print(f">>> BATERIA TOTAL · {BASE} · {time.strftime('%H:%M:%S')}")
    for cat, tests in TESTS.items():
        if grupo and cat != grupo: continue
        print(f"\n--- {cat} ---")
        for sid, msg in tests:
            print(f"[{sid}] {send(sid, msg)[:120].replace(chr(10), ' ')}")
    time.sleep(1.5)
    todas = list(open(TRACE, encoding="utf-8", errors="replace"))
    relatorio(todas[base:])


if __name__ == "__main__":
    main()
