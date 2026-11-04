"""Dados de EXEMPLO no cérebro — pra testar o painel e o agente com o cérebro cheio, e tirar depois sem deixar rastro.

Tudo que este script grava leva fonte='exemplo'; `limpar` apaga só isso (o que você ou o agente gravaram fica).
Usa o MESMO serviço do agente (CerebroService), então as regras (normalização, correção com histórico,
tipo → área) são as reais.

Uso (na raiz do repo, com o agente rodando ou não — SQLite em WAL aguenta):
  python ops/cerebro_exemplo.py status                 # quanto há de exemplo e de dado real
  python ops/cerebro_exemplo.py popular                # insere o cérebro de exemplo (não duplica se já houver)
  python ops/cerebro_exemplo.py limpar                 # apaga só o que é exemplo
  python ops/cerebro_exemplo.py popular --db outro.db  # num banco à parte (ex.: pra testar sem mexer no real)
Depois de popular/limpar: `braza restart --agent` (o agente guarda em memória o bloco do contexto).

O que entra: você (preferências, particularidades), Pessoal (plano de carreira, vida social), Finanças (contas
fixas e cartões com vencimento e pagamentos de jul–out), Estudos (Estácio, Métodos Ágeis, Engenharia de Produto,
Gerência de Projetos, Machine Learning, Claude) e Academia (a semana de 07 a 11/09/2026:
seg Peito+Tríceps+Panturrilha · ter Quadríceps+Abdominal · qua Costas+Bíceps+Panturrilha ·
qui Posterior+Abdominal · sex Ombro+Antebraço+Panturrilha — 4 séries de 6, "cada lado" nos de halter/barra).
Se já existir um treino de peito em 07/09 (o seu, real), a segunda-feira de exemplo é pulada.
"""
import argparse
import asyncio
import datetime as dt
import os
import random
import sqlite3
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from application.services.cerebro_service import CerebroService          # noqa: E402
from infrastructure.memory.cerebro_store import SqliteCerebroStore         # noqa: E402

F = "exemplo"
HOJE = dt.datetime(2026, 11, 4, 12, 0)

SEMANA = {   # dia → (nome do treino, grupo principal, {grupo: [(exercício, kg, cada lado?)]}); kg None = sem carga
    dt.date(2026, 9, 7): ("Peito + Tríceps + Panturrilha", "Peito", {
        "Peito": [("Supino inclinado", 16, True), ("Supino máquina reto", 20, True), ("Peito polia baixa", 10, True),
                  ("Peito polia alta", 20, True), ("Crucifixo", 35, False)],
        "Tríceps": [("Tríceps polia", 20, False), ("Tríceps banco altere", 15, False), ("Tríceps francês altere", 8, False)],
        "Panturrilha": [("Panturrilha sentado", 20, False), ("Panturrilha em pé", 15, True)]}),
    dt.date(2026, 9, 8): ("Quadríceps + Abdominal", "Quadríceps", {
        "Quadríceps": [("Agachamento livre", 20, True), ("Leg press", 120, False), ("Cadeira extensora", 45, False), ("Hack", 40, False)],
        "Abdominal": [("Abdominal supra", None, False), ("Abdominal infra", None, False), ("Prancha", None, False)]}),
    dt.date(2026, 9, 9): ("Costas + Bíceps + Panturrilha", "Costas", {
        "Costas": [("Puxada frontal", 45, False), ("Remada baixa", 40, False), ("Remada curvada", 20, True), ("Pulldown", 25, False)],
        "Bíceps": [("Rosca direta", 12, True), ("Rosca martelo", 10, True), ("Rosca scott", 15, True)],
        "Panturrilha": [("Panturrilha sentado", 20, False), ("Panturrilha em pé", 15, True)]}),
    dt.date(2026, 9, 10): ("Posterior + Abdominal", "Posterior", {
        "Posterior": [("Stiff", 20, True), ("Mesa flexora", 35, False), ("Cadeira flexora", 40, False), ("Elevação pélvica", 60, False)],
        "Abdominal": [("Abdominal supra", None, False), ("Abdominal infra", None, False), ("Prancha", None, False)]}),
    dt.date(2026, 9, 11): ("Ombro + Antebraço + Panturrilha", "Ombro", {
        "Ombro": [("Desenvolvimento halteres", 12, True), ("Elevação lateral", 7, True), ("Elevação frontal", 7, True),
                  ("Crucifixo inverso", 30, False)],
        "Antebraço": [("Rosca punho", 8, True), ("Rosca inversa", 10, True)],
        "Panturrilha": [("Panturrilha sentado", 20, False), ("Panturrilha em pé", 15, True)]}),
}


def _db_padrao() -> str:
    return os.path.join(RAIZ, "data", "cerebro.db")


def status(db: str) -> None:
    c = sqlite3.connect(db)
    q = lambda sql, *args: c.execute(sql, args).fetchone()[0]
    print(db)
    print("  entidades:", q("SELECT COUNT(*) FROM entidades"))
    print("  observações:", q("SELECT COUNT(*) FROM observacoes"), "· de exemplo:", q("SELECT COUNT(*) FROM observacoes WHERE fonte = ?", F))
    print("  registros:", q("SELECT COUNT(*) FROM registros"), "· de exemplo:", q("SELECT COUNT(*) FROM registros WHERE fonte = ?", F))
    print("  ligações:", q("SELECT COUNT(*) FROM relacoes"))


def limpar(db: str) -> None:
    """Apaga o que é exemplo; depois tira entidades que ficaram órfãs (sem observação, sem registro e sem
    ligação com algo que ainda tem dado). O dono e o que você/o agente gravaram ficam."""
    c = sqlite3.connect(db)
    ids = [r[0] for r in c.execute("SELECT id FROM observacoes WHERE fonte = ?", (F,))]
    c.executemany("DELETE FROM obs_fts WHERE rowid = ?", [(i,) for i in ids])
    c.execute("UPDATE observacoes SET substitui = NULL WHERE substitui IN (SELECT id FROM observacoes WHERE fonte = ?)", (F,))
    c.execute("DELETE FROM observacoes WHERE fonte = ?", (F,))
    c.execute("UPDATE registros SET sessao = NULL WHERE sessao IN (SELECT id FROM registros WHERE fonte = ?)", (F,))
    c.execute("UPDATE registros SET substitui = NULL WHERE substitui IN (SELECT id FROM registros WHERE fonte = ?)", (F,))
    c.execute("DELETE FROM registros WHERE fonte = ?", (F,))
    dono = {r[0] for r in c.execute("SELECT id FROM entidades WHERE nome = 'Você'")}
    com_dado = {r[0] for r in c.execute(
        "SELECT entidade_id FROM observacoes UNION SELECT entidade_id FROM registros WHERE entidade_id IS NOT NULL")} - dono
    # o grupo de um exercício real (Peito ← Supino) fica, mesmo sem dado próprio; ligações do Você não seguram nada
    alvo = {r[0] for r in c.execute("SELECT para_id FROM relacoes WHERE de_id IN (%s)" % ",".join("?" * len(com_dado)),
                                    tuple(com_dado))} if com_dado else set()
    manter = com_dado | alvo | dono
    todas = [r[0] for r in c.execute("SELECT id FROM entidades")]
    sai = [i for i in todas if i not in manter]
    c.executemany("DELETE FROM relacoes WHERE de_id = ? OR para_id = ?", [(i, i) for i in sai])
    c.executemany("DELETE FROM entidades WHERE id = ?", [(i,) for i in sai])
    c.execute("DELETE FROM relacoes WHERE de_id NOT IN (SELECT id FROM entidades) OR para_id NOT IN (SELECT id FROM entidades)")
    c.commit()
    print(f"limpo: {len(ids)} observações de exemplo, {len(sai)} entidades órfãs")
    status(db)


async def popular(db: str) -> None:
    random.seed(11)
    st = SqliteCerebroStore(db)
    await st.init()
    c = CerebroService(st)
    ja = sqlite3.connect(db).execute("SELECT COUNT(*) FROM observacoes WHERE fonte = ?", (F,)).fetchone()[0]
    if ja:
        print(f"já há {ja} observações de exemplo — rode `limpar` antes de popular de novo")
        return

    for t, a in (("meta", "pessoal"), ("habito", "pessoal"), ("conta", "financas"), ("cartao", "financas"),
                 ("instituicao", "estudos"), ("lugar", "geral")):
        await st.definir_area(t, a)

    async def L(texto, cat, ent="Você", tipo=None, rel=None, com=None):
        return await c.lembrar(texto, cat, entidade=ent, tipo=tipo, relacao=rel, com=com, fonte=F)

    async def E(nome, tipo):
        e = await st.entidade(nome, tipo)
        if e.tipo != tipo and e.tipo == "geral":
            await st.mudar_tipo(e.id, tipo)
        return await st.achar_entidade(nome)

    async def ligar(de, tipo, para):
        a, b = await st.achar_entidade(de), await st.achar_entidade(para)
        await st.relacionar(a.id, tipo, b.id)

    async def reg(tipo, quando, assunto, dados=None, texto="", sessao=None, eh_sessao=False):
        e = await st.achar_entidade(assunto) if assunto else None
        return await st.registrar(tipo, quando.timestamp(), entidade_id=e.id if e else None, dados=dados or {},
                                  texto=texto, sessao=sessao, eh_sessao=eh_sessao, fonte=F)

    # você
    await L("se chama Matheus", "nome")
    await L("engenheiro de dados na Disbral", "trabalho", rel="trabalha em", com="Disbral")
    await L("cursa Engenharia de Software na Estácio", "estudo", rel="estuda em", com="Estácio")
    a = await L("prefere resposta direta", "preferencia")
    await c.lembrar("prefere direto, mas com exemplos práticos", "preferencia", substitui=int(a.split("#")[1].split()[0]), fonte=F)
    await L("gosta de estudar com exemplos resolvidos", "particularidade")
    await L("aprende melhor com ilustrações e diagramas", "particularidade")
    await L("aprende implementando: quer o porquê antes do código", "particularidade")
    await L("curte visual neon/escuro, dados em gráfico e mapa", "gosto")
    await L("treina à noite, 5 dias por semana", "rotina")

    # pessoal
    await E("Plano de carreira", "meta"); await ligar("Você", "tem", "Plano de carreira")
    await L("migrar pra engenharia de ML em 2027", "objetivo", "Plano de carreira")
    await L("aprender Machine Learning do zero ao deploy", "passo", "Plano de carreira")
    await L("melhorar o portfólio com 3 cases fortes", "passo", "Plano de carreira")
    await E("Machine Learning", "tema"); await ligar("Plano de carreira", "inclui", "Machine Learning")
    await E("Portfólio", "projeto"); await ligar("Plano de carreira", "inclui", "Portfólio")
    await L("README com arquitetura, demo em vídeo e deploy", "fazer", "Portfólio")
    await E("Vida social", "meta"); await ligar("Você", "quer", "Vida social")
    await L("planeja sair mais vezes", "objetivo", "Vida social")
    await L("socializar mais: 1 rolê por semana", "meta", "Vida social")
    await E("Turma da faculdade", "pessoa"); await ligar("Vida social", "com", "Turma da faculdade")
    await E("Time de dados", "pessoa"); await ligar("Time de dados", "da", "Disbral")
    for d in (2, 9, 17, 23, 30, 38):
        await reg("saida", HOJE - dt.timedelta(days=d, hours=-8), "Vida social", {}, random.choice(["bar", "cinema", "churrasco", "jantar"]))

    # finanças
    await E("Contas fixas", "conta"); await E("Cartões", "cartao")
    for nome, dia, valor, de, tipo_de in (("Mensalidade da faculdade", 10, 689.0, "Estácio", "instituicao"),
                                         ("Assinatura Claude", 15, 110.0, "Claude", "ferramenta"),
                                         ("Mensalidade da academia", 5, 129.9, "Academia", "lugar"),
                                         ("Internet", 12, 119.9, None, None), ("Barbearia", 20, 45.0, None, None)):
        await E(nome, "conta"); await ligar(nome, "faz parte", "Contas fixas")
        await L("corte a cada 15 dias" if nome == "Barbearia" else f"vence todo dia {dia}", "vencimento", nome)
        await L(f"lembrar 2 dias antes · ~R$ {valor:.2f}", "lembrete", nome)
        if de:
            await E(de, tipo_de); await ligar(nome, "de", de)
        for m in (7, 8, 9, 10):
            for _ in range(2 if nome == "Barbearia" else 1):
                v = valor if nome == "Mensalidade da faculdade" else round(valor * random.uniform(.97, 1.03), 2)
                await reg("pagamento", dt.datetime(2026, m, min(dia + random.randint(-2, 0), 28), 10), nome, {"valor_rs": v})
    for nome, dia, base in (("Fatura Nubank", 8, 1850.0), ("Fatura Inter", 17, 620.0)):
        await E(nome, "cartao"); await ligar(nome, "de", "Cartões")
        await L(f"vence todo dia {dia}", "vencimento", nome)
        await L("conferir parcelamentos antes de pagar", "lembrete", nome)
        for m in (7, 8, 9, 10):
            await reg("pagamento", dt.datetime(2026, m, dia, 9), nome, {"valor_rs": round(base * random.uniform(.8, 1.25), 2)})

    # estudos
    await E("Estácio", "instituicao"); await L("Engenharia de Software · 2026.3", "curso", "Estácio")
    for disc, (temas, nota) in {
        "Métodos Ágeis": (["Manifesto Ágil", "XP", "Scrum", "Kanban"], "prova em 26/11"),
        "Engenharia de Produto": (["Discovery", "MVP", "OKRs", "Métricas de produto"], "trabalho final: canvas de produto"),
        "Gerência de Projetos": (["Medidas de Esforço", "Cronograma (CPM)"], "prova feita em 26/10"),
    }.items():
        await E(disc, "disciplina"); await ligar(disc, "cursa em", "Estácio"); await L(nota, "avaliacao", disc)
        for t in temas:
            await E(t, "tema"); await ligar(t, "parte de", disc)
    for tema, txt, cat in (("Scrum", "3 pilares e timeboxes (≤8h/15min/≤4h/≤3h)", "conteudo"), ("Scrum", "errou timeboxes na réplica", "dificuldade"),
                           ("XP", "5 valores e papéis (Coach, Tracker…)", "conteudo"), ("Kanban", "WIP limit e lead time", "conteudo"),
                           ("Discovery", "entrevista com usuário antes de construir", "conteudo"), ("MVP", "menor coisa que valida a hipótese", "conteudo"),
                           ("OKRs", "objetivo qualitativo + 3 resultados medíveis", "conteudo"), ("Medidas de Esforço", "COCOMO é onde mais erra", "dificuldade")):
        await L(txt, cat, tema)
    for t in ("Regressão linear", "Árvores de decisão", "Redes neurais", "MLOps", "LLMs e agentes"):
        await E(t, "tema"); await ligar(t, "parte de", "Machine Learning")
    await L("começar pelo curso do Andrew Ng + Kaggle", "plano", "Machine Learning")
    await E("Claude", "ferramenta"); await L("estudando agentes, tool use e prompts", "estudo", "Claude")
    await ligar("Claude", "ajuda em", "LLMs e agentes")
    for assunto, n, faixa in (("Scrum", 6, (25, 60)), ("Kanban", 3, (20, 40)), ("Discovery", 4, (30, 60)),
                              ("Medidas de Esforço", 8, (40, 90)), ("Regressão linear", 4, (40, 80)), ("LLMs e agentes", 6, (30, 120))):
        for i in range(n):
            dados = {"duracao_min": random.randint(*faixa) // 5 * 5}
            if assunto in ("Medidas de Esforço", "Scrum"):
                dados["acertos"] = min(10, 5 + i // 2 + random.randint(0, 2))
            await reg("estudo", HOJE - dt.timedelta(days=random.randint(1, 45), hours=random.randint(0, 6)), assunto, dados)

    # trabalho
    await E("Disbral", "empresa")
    for p, txt in (("Telemetria Sascar", "producer Java/Kafka da telemetria Sascar"), ("Telemetry Persistence", "persistência + migrations SQL"),
                   ("Tower API", "API do Tower (core + services)")):
        await E(p, "projeto"); await ligar(p, "de", "Disbral"); await L(txt, "contexto", p)
    await E("Brazaia", "projeto"); await ligar("Brazaia", "vai pro", "Portfólio")
    await L("agente pessoal local: voz, tutor, cérebro e painel", "contexto", "Brazaia")
    for f_ in ("Qwen 27B no vLLM", "FastAPI", "Termux", "Claude"):
        await E(f_, "ferramenta"); await ligar("Brazaia", "usa", f_)
    for quando, txt in (("2026-10-27 22:00", "voz ao vivo validada"), ("2026-11-03 21:40", "M1 · cérebro"), ("2026-11-04 09:25", "M2 · registros"),
                        ("2026-11-04 10:05", "P1 · painel"), ("2026-11-04 10:40", "P2 · localização"), ("2026-11-04 11:50", "P3 · cérebro no painel")):
        await reg("entrega", dt.datetime.fromisoformat(quando), "Brazaia", {}, txt)

    # academia: a semana de 07 a 11/09
    await E("Academia", "lugar"); await L("treina na academia do bairro, à noite", "rotina", "Academia")
    peito_real = sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM registros WHERE eh_sessao = 1 AND fonte <> ? AND date(quando, 'unixepoch', 'localtime') = '2026-09-07'",
        (F,)).fetchone()[0]
    for dia, (nome, principal, grupos) in SEMANA.items():
        if dia == dt.date(2026, 9, 7) and peito_real:
            print("segunda 07/09: já há o treino de peito real — pulei o de exemplo")
        for g, exs in grupos.items():
            await E(g, "grupo muscular")
            for ex, _, _ in exs:
                e = await E(ex, "exercicio")
                if not any(r["tipo"] == "grupo" for r in await st.relacoes_com_id(e.id)):
                    await ligar(ex, "grupo", g)
        if dia == dt.date(2026, 9, 7) and peito_real:
            continue
        ini = dt.datetime.combine(dia, dt.time(19, 0))
        sess = await reg("treino", ini, principal, {}, nome, eh_sessao=True)
        t = ini
        for g, exs in grupos.items():
            for ex, kg, lado in exs:
                t += dt.timedelta(minutes=6)
                if kg is None:
                    dados = {"series": 3, "duracao_s": 60} if ex == "Prancha" else {"series": 4, "reps": 15}
                else:
                    dados = {"series": 4, "reps": 6, "carga_kg": kg}
                await reg("serie", t, ex, dados, "cada lado" if lado else "", sessao=sess.id)
        await st.fechar_sessao(sess.id, (t + dt.timedelta(minutes=5)).timestamp())
    for ex, txt, cat in (("Supino inclinado", "banco na 3ª posição", "execucao"), ("Remada curvada", "lombar reta, puxa no umbigo", "execucao"),
                         ("Agachamento livre", "joelho estala — amplitude até 90°", "saude"), ("Stiff", "sente o posterior, não a lombar", "execucao"),
                         ("Prancha", "meta: 2 min", "meta")):
        await L(txt, cat, ex)
    status(db)


def main() -> None:
    ap = argparse.ArgumentParser(description="dados de exemplo no cérebro (fonte='exemplo')")
    ap.add_argument("acao", choices=["status", "popular", "limpar"])
    ap.add_argument("--db", default=_db_padrao())
    a = ap.parse_args()
    if a.acao == "status":
        status(a.db)
    elif a.acao == "limpar":
        limpar(a.db)
    else:
        asyncio.run(popular(a.db))


if __name__ == "__main__":
    main()
