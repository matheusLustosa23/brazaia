// Cérebro do agente no painel — grafo vivo (force-graph) + ficha editável + linha do tempo + revisar.
// Usa os utilitários de painel.js ($, el, api, aviso, relativo, dataHora). Tudo passa pelo MESMO serviço que o
// agente usa: editar uma observação = corrigir (a antiga fica no histórico), igual ao remember(substitui=…).
"use strict";

const CER = {
  dados: null,              // panorama: entidades, relacoes, tipos, totais
  grafo: null,              // instância do ForceGraph
  sel: null,                // id da entidade aberta na ficha
  hover: null,              // nó sob o mouse
  vizinhos: new Set(),      // ids ligados ao nó em foco (pra destacar)
  areasOff: new Set(),      // áreas escondidas pelo filtro
  rotulos: false,
  vista: "grafo",
  ltDias: 30,
  rvDias: 7,
  iniciado: false,
};

// cor por área (a "frente" do agente): a mesma em nó, legenda e chips
const AREA_COR = {
  voce: "#22e5ff", academia: "#6dff8b", estudos: "#ffd23f", trabalho: "#ff3fd8",
  pessoas: "#a78bff", financas: "#3dffc5", geral: "#7f8db3",
};
const AREA_NOME = {
  voce: "Você", academia: "Academia", estudos: "Estudos", trabalho: "Trabalho",
  pessoas: "Pessoas", financas: "Finanças", geral: "Geral",
};
const corArea = (a) => AREA_COR[a] || AREA_COR.geral;
const nomeArea = (a) => AREA_NOME[a] || (a ? a[0].toUpperCase() + a.slice(1) : "Geral");
const DONO = "Você";

// ── carregar ────────────────────────────────────────────────────────────────────────────────────────────
async function cerCarregar() {
  CER.dados = await api("/cerebro");
  const t = CER.dados.totais;
  $("#cer-resumo").textContent =
    `${t.entidades} entidade(s) · ${t.observacoes} observação(ões) · ${t.historico} no histórico · ` +
    `${t.registros} registro(s) · ${t.relacoes} ligação(ões)`;
  montarAreas();
  desenharGrafo();
  if (CER.sel) await abrirFicha(CER.sel, { semZoom: true }).catch(() => { CER.sel = null; fichaVazia(); });
}

// ── grafo ───────────────────────────────────────────────────────────────────────────────────────────────
function dadosGrafo() {
  const d = CER.dados;
  const dono = d.entidades.find((e) => e.nome === DONO);
  const nodes = [], links = [];
  const visiveis = d.entidades.filter((e) => e.nome === DONO || !CER.areasOff.has(e.area));
  const areas = [...new Set(visiveis.filter((e) => e.nome !== DONO).map((e) => e.area))];

  // nós "hub" de área: dão a forma de constelação (Você → áreas → coisas), como o grafo do Obsidian
  for (const a of areas) nodes.push({ id: `area:${a}`, hub: true, area: a, nome: nomeArea(a), peso: 0 });
  for (const e of visiveis) {
    nodes.push({ id: e.id, nome: e.nome, tipo: e.tipo, area: e.area, dono: e.nome === DONO,
                 peso: e.n_obs + e.n_reg, n_obs: e.n_obs, n_reg: e.n_reg });
  }
  if (dono) for (const a of areas) links.push({ source: dono.id, target: `area:${a}`, virtual: true, area: a });
  for (const e of visiveis) if (e.nome !== DONO) links.push({ source: `area:${e.area}`, target: e.id, virtual: true, area: e.area });
  const ids = new Set(visiveis.map((e) => e.id));
  for (const r of d.relacoes) {
    if (ids.has(r.de) && ids.has(r.para)) links.push({ source: r.de, target: r.para, tipo: r.tipo, id: r.id });
  }
  return { nodes, links };
}

function raio(n) {
  if (n.dono) return 15;
  if (n.hub) return 7;
  return 5 + Math.sqrt(n.peso || 0) * 2.4;
}

function focoDe(n) {
  CER.vizinhos = new Set();
  if (!n || !CER.grafo) return;
  CER.vizinhos.add(n.id);
  for (const l of CER.grafo.graphData().links) {
    const s = typeof l.source === "object" ? l.source.id : l.source;
    const t = typeof l.target === "object" ? l.target.id : l.target;
    if (s === n.id) CER.vizinhos.add(t);
    if (t === n.id) CER.vizinhos.add(s);
  }
}

function desenharNo(n, ctx, escala) {
  if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return;     // 1º quadro: a física ainda não posicionou
  const r = raio(n);
  const cor = n.dono ? AREA_COR.voce : corArea(n.area);
  const foco = CER.hover || (CER.sel != null ? { id: CER.sel } : null);
  const apagado = foco && CER.vizinhos.size && !CER.vizinhos.has(n.id);
  const selecionado = CER.sel === n.id;
  ctx.save();
  ctx.globalAlpha = apagado ? 0.18 : 1;

  if (n.dono) {                                     // o dono pulsa
    const t = (Date.now() % 2400) / 2400;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 4 + t * 14, 0, 2 * Math.PI);
    ctx.strokeStyle = cor;
    ctx.globalAlpha = (apagado ? 0.1 : 0.55) * (1 - t);
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.globalAlpha = apagado ? 0.18 : 1;
  }

  ctx.shadowColor = cor;
  ctx.shadowBlur = selecionado ? 28 : n.hub ? 10 : 16;
  ctx.beginPath();
  if (n.hub) {                                      // hub de área: losango
    ctx.moveTo(n.x, n.y - r); ctx.lineTo(n.x + r, n.y); ctx.lineTo(n.x, n.y + r); ctx.lineTo(n.x - r, n.y); ctx.closePath();
    ctx.fillStyle = "#0a0e18";
    ctx.fill();
    ctx.lineWidth = 1.6;
    ctx.strokeStyle = cor;
    ctx.stroke();
  } else {
    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
    const g = ctx.createRadialGradient(n.x - r / 3, n.y - r / 3, r / 6, n.x, n.y, r);
    g.addColorStop(0, "#ffffff");
    g.addColorStop(0.35, cor);
    g.addColorStop(1, cor + "aa");
    ctx.fillStyle = g;
    ctx.fill();
    if (selecionado) { ctx.lineWidth = 2.5; ctx.strokeStyle = "#ffffff"; ctx.stroke(); }
  }
  ctx.shadowBlur = 0;

  const mostrar = CER.rotulos || n.dono || n.hub || selecionado || (CER.hover && CER.vizinhos.has(n.id)) || escala > 1.6;
  if (mostrar) {
    const fonte = Math.max(10 / escala, n.dono ? 5 : 3.2);
    ctx.font = `${n.hub ? "600 " : ""}${fonte}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const texto = n.hub ? n.nome.toUpperCase() : n.nome;
    ctx.fillStyle = n.hub ? cor : "#e6ecff";
    ctx.globalAlpha = apagado ? 0.18 : n.hub ? 0.85 : 1;
    ctx.fillText(texto, n.x, n.y + r + 2);
  }
  ctx.restore();
}

function corLink(l) {
  const foco = CER.hover || (CER.sel != null ? { id: CER.sel } : null);
  const s = typeof l.source === "object" ? l.source.id : l.source;
  const t = typeof l.target === "object" ? l.target.id : l.target;
  const noFoco = foco && (s === foco.id || t === foco.id);
  if (l.virtual) {
    const c = corArea(l.area);
    return noFoco ? c + "aa" : foco ? c + "14" : c + "38";
  }
  return noFoco ? "#ff3fd8" : foco ? "#ff3fd833" : "#ff3fd8aa";
}

function desenharGrafo() {
  const caixa = $("#cer-grafo");
  if (typeof ForceGraph === "undefined") { caixa.textContent = "biblioteca do grafo não carregou"; return; }
  const dados = dadosGrafo();
  if (!CER.grafo) {
    CER.grafo = ForceGraph()(caixa)
      .backgroundColor("rgba(0,0,0,0)")
      .nodeId("id")
      .nodeVal((n) => raio(n) ** 2 / 4)
      .nodeLabel((n) => n.hub ? `${n.nome}` : `${n.nome} · ${n.tipo}${n.n_obs ? ` · ${n.n_obs} obs` : ""}${n.n_reg ? ` · ${n.n_reg} reg` : ""}`)
      .nodeCanvasObject(desenharNo)
      .nodePointerAreaPaint((n, cor, ctx) => { ctx.fillStyle = cor; ctx.beginPath(); ctx.arc(n.x, n.y, raio(n) + 3, 0, 2 * Math.PI); ctx.fill(); })
      .linkColor(corLink)
      .linkWidth((l) => (l.virtual ? 1 : 2))
      .linkLineDash((l) => (l.virtual ? [2, 3] : null))
      .linkDirectionalParticles((l) => (l.virtual ? 0 : 3))
      .linkDirectionalParticleWidth(2.6)
      .linkDirectionalParticleSpeed(0.006)
      .linkDirectionalParticleColor(() => "#ff9cf0")
      .linkCanvasObjectMode(() => "after")
      .linkCanvasObject((l, ctx, escala) => {                    // nome da ligação no meio do traço
        if (l.virtual || !l.tipo || escala < 1.1) return;
        const a = l.source, b = l.target;
        if (typeof a !== "object") return;
        ctx.save();
        ctx.font = `${Math.max(9 / escala, 2.6)}px system-ui, sans-serif`;
        ctx.fillStyle = "#ff9cf0";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(l.tipo, (a.x + b.x) / 2, (a.y + b.y) / 2 - 3 / escala);
        ctx.restore();
      })
      .onNodeHover((n) => { CER.hover = n || null; focoDe(n || (CER.sel != null ? { id: CER.sel } : null)); caixa.style.cursor = n ? "pointer" : ""; })
      .onNodeClick((n) => {
        if (n.hub) { CER.grafo.centerAt(n.x, n.y, 600); CER.grafo.zoom(2.2, 600); return; }
        abrirFicha(n.id);
      })
      .onBackgroundClick(() => { CER.sel = null; focoDe(null); fichaVazia(); })
      .cooldownTicks(200)
      .autoPauseRedraw(false);                                   // mantém o pulso do dono e as partículas vivos
    CER.grafo.d3Force("charge").strength(-140);
    CER.grafo.d3Force("link").distance((l) => {
      const s = typeof l.source === "object" ? l.source : {};
      return l.virtual ? (s.dono ? 110 : 55) : 45;
    });
    new ResizeObserver(() => CER.grafo.width(caixa.clientWidth).height(caixa.clientHeight)).observe(caixa);
    setTimeout(() => CER.grafo.zoomToFit(700, 60), 900);
  }
  // preserva posições dos nós que já existiam (não "explode" a cada recarga)
  const antigos = new Map(CER.grafo.graphData().nodes.map((n) => [n.id, n]));
  for (const n of dados.nodes) {
    const v = antigos.get(n.id);
    if (v) { n.x = v.x; n.y = v.y; n.vx = v.vx; n.vy = v.vy; }
    if (n.dono) { n.fx = 0; n.fy = 0; }                          // Você fica no centro
  }
  CER.grafo.graphData(dados);
  focoDe(CER.sel != null ? { id: CER.sel } : null);
  legenda();
}

function legenda() {
  const ents = CER.dados.entidades;
  $("#cer-legenda").replaceChildren(
    el("span", {}, el("i", { class: "leg-no" }), "entidade (tamanho = quanto ele sabe)"),
    el("span", {}, el("i", { class: "leg-hub" }), "área"),
    el("span", {}, el("i", { class: "leg-rel" }), "ligação"),
    ...(ents.length <= 1 ? [el("span", { class: "leg-dica" }, "Cérebro vazio: converse com o agente ou use ＋ Entidade")] : []));
}

function montarAreas() {
  const contagem = {};
  for (const e of CER.dados.entidades) if (e.nome !== DONO) contagem[e.area] = (contagem[e.area] || 0) + 1;
  const caixa = $("#cer-areas");
  caixa.replaceChildren(...Object.entries(contagem).sort((a, b) => b[1] - a[1]).map(([a, n]) =>
    el("button", {
      type: "button", class: CER.areasOff.has(a) ? "" : "sel", style: `--c:${corArea(a)}`, title: "mostrar/esconder",
      onclick: () => { CER.areasOff.has(a) ? CER.areasOff.delete(a) : CER.areasOff.add(a); montarAreas(); desenharGrafo(); },
    }, el("i", { class: "bolinha" }), `${nomeArea(a)} ${n}`)));
}

function irPara(id) {
  const n = CER.grafo && CER.grafo.graphData().nodes.find((x) => x.id === id);
  if (n && n.x != null) { CER.grafo.centerAt(n.x, n.y, 700); CER.grafo.zoom(2.6, 700); }
}

// ── ficha ───────────────────────────────────────────────────────────────────────────────────────────────
function fichaVazia() {
  $("#cer-ficha").replaceChildren(el("div", { class: "vazio" },
    "Toque num nó do grafo para abrir a ficha: o que ele sabe, o que mudou, as ligações e o que aconteceu."));
}

const SEM_CAT = "observacao";
const chipCat = (c) => el("span", { class: "chip cat" }, c);

async function abrirFicha(id, { semZoom = false } = {}) {
  const f = await api(`/cerebro/entidades/${id}`);
  CER.sel = id;
  focoDe({ id });
  if (!semZoom) irPara(id);
  const e = f.entidade;
  const eDono = e.nome === DONO;
  const cor = corArea(e.area);
  const atuais = f.observacoes.filter((o) => !o.invalido_em);
  const porId = new Map(f.observacoes.map((o) => [o.id, o]));

  // cabeçalho (nome editável, tipo, área)
  const titulo = el("h2", { class: "ficha-nome", style: `--c:${cor}` }, e.nome);
  const bNome = el("button", { type: "button", class: "mini", title: "renomear" }, "✎");
  bNome.hidden = eDono;
  bNome.addEventListener("click", () => {
    const entrada = el("input", { type: "text", value: e.nome, "aria-label": "novo nome" });
    const ok = el("button", { type: "button", class: "neon mini" }, "ok");
    const salvar = async () => {
      try { await api(`/cerebro/entidades/${id}`, { method: "PATCH", body: JSON.stringify({ nome: entrada.value }) }); aviso("Renomeado"); await cerCarregar(); }
      catch (x) { aviso(x.message, true); }
    };
    ok.addEventListener("click", salvar);
    entrada.addEventListener("keydown", (k) => { if (k.key === "Enter") salvar(); if (k.key === "Escape") abrirFicha(id, { semZoom: true }); });
    titulo.replaceChildren(entrada, ok);
    entrada.focus();
  });
  const listaTipos = "cer-tipos-lista";
  const tipo = el("input", { type: "text", value: e.tipo, list: listaTipos, class: "inline", "aria-label": "tipo", disabled: eDono });
  const area = el("select", { class: "inline", "aria-label": "área", disabled: eDono },
    Object.keys(AREA_NOME).filter((a) => a !== "voce" || eDono).map((a) => el("option", { value: a, selected: a === e.area }, nomeArea(a))));
  const salvarTipo = async () => {
    try {
      await api(`/cerebro/entidades/${id}`, { method: "PATCH", body: JSON.stringify({ tipo: tipo.value, area: area.value }) });
      aviso(`Tipo/área salvos (a área vale pra todo tipo “${tipo.value}”)`); await cerCarregar();
    } catch (x) { aviso(x.message, true); }
  };
  tipo.addEventListener("change", salvarTipo);
  area.addEventListener("change", salvarTipo);

  const cab = el("div", { class: "ficha-cab" },
    el("div", { class: "linha1" }, titulo, bNome),
    el("div", { class: "ficha-meta" },
      el("label", {}, "tipo ", tipo, el("datalist", { id: listaTipos }, CER.dados.tipos.map((t) => el("option", { value: t.nome })))),
      el("label", {}, "área ", area)),
    el("div", { class: "ficha-nums" },
      el("span", {}, el("b", {}, atuais.length), " obs"),
      el("span", {}, el("b", {}, f.observacoes.length - atuais.length), " no histórico"),
      el("span", {}, el("b", {}, f.relacoes.length), " ligações"),
      el("span", {}, el("b", {}, f.registros.length), " registros")));

  // observações agrupadas por categoria, com edição (= correção) e histórico
  const cats = {};
  for (const o of atuais) (cats[o.categoria] ||= []).push(o);
  const blocoObs = el("div", { class: "ficha-sec" }, el("h3", {}, "O que ele sabe"));
  if (!atuais.length) blocoObs.append(el("p", { class: "meta" }, "Nada ainda."));
  for (const [cat, lista] of Object.entries(cats).sort()) {
    blocoObs.append(el("div", { class: "cat-tit" }, chipCat(cat)));
    for (const o of lista) blocoObs.append(itemObs(o, porId, id));
  }
  blocoObs.append(formObs(id, Object.keys(cats)));

  // ligações
  const blocoRel = el("div", { class: "ficha-sec" }, el("h3", {}, "Ligações"));
  if (!f.relacoes.length) blocoRel.append(el("p", { class: "meta" }, "Sem ligações."));
  for (const r of f.relacoes) {
    const outro = r.de_id === id ? { id: r.para_id, nome: r.para } : { id: r.de_id, nome: r.de };
    blocoRel.append(el("div", { class: "rel-item" },
      el("span", {}, r.de_id === id ? "" : el("a", { href: "#", onclick: (ev) => { ev.preventDefault(); abrirFicha(outro.id); } }, r.de), " —",
        el("b", { class: "rel-tipo" }, r.tipo), "→ ",
        r.de_id === id ? el("a", { href: "#", onclick: (ev) => { ev.preventDefault(); abrirFicha(outro.id); } }, r.para) : e.nome),
      el("button", { type: "button", class: "mini perigo", title: "apagar ligação", onclick: async () => {
        if (!confirm(`Apagar a ligação ${r.de} —${r.tipo}→ ${r.para}?`)) return;
        await api(`/cerebro/relacoes/${r.id}`, { method: "DELETE" }); aviso("Ligação apagada"); await cerCarregar();
      } }, "🗑")));
  }
  blocoRel.append(formRel(id));

  // registros (+ gráfico se houver números)
  const blocoReg = el("div", { class: "ficha-sec" }, el("h3", {}, "O que aconteceu"));
  if (!f.registros.length) blocoReg.append(el("p", { class: "meta" }, "Nenhum registro."));
  else {
    if (f.metricas.length) {
      const sel = el("select", { class: "inline", "aria-label": "métrica" }, f.metricas.map((m) => el("option", { value: m, selected: m === (f.metricas.includes("carga_kg") ? "carga_kg" : f.metricas[0]) }, m)));
      const g = el("div", {});
      const pintar = () => g.replaceChildren(grafico(f.registros, sel.value));
      sel.addEventListener("change", pintar);
      blocoReg.append(el("div", { class: "linha-form" }, el("span", { class: "meta" }, "evolução de"), sel), g);
      pintar();
    }
    for (const r of f.registros.slice(0, 15)) blocoReg.append(itemReg(r));
    if (f.registros.length > 15) blocoReg.append(el("p", { class: "meta" }, `+${f.registros.length - 15} na Linha do tempo`));
  }

  const perigo = eDono ? null : el("div", { class: "ficha-sec" },
    el("button", { type: "button", class: "perigo", onclick: async () => {
      if (!confirm(`Apagar “${e.nome}” DE VEZ, com ${f.observacoes.length} observação(ões), ${f.relacoes.length} ligação(ões) e ${f.registros.length} registro(s)?`)) return;
      try { await api(`/cerebro/entidades/${id}`, { method: "DELETE" }); aviso(`“${e.nome}” apagado`); CER.sel = null; fichaVazia(); await cerCarregar(); }
      catch (x) { aviso(x.message, true); }
    } }, "Apagar entidade"));

  $("#cer-ficha").replaceChildren(cab, blocoObs, blocoRel, blocoReg, perigo);
  $("#cer-ficha").scrollTop = 0;
}

function itemObs(o, porId, entId) {
  const hist = [];
  let s = o.substitui;
  while (s && porId.get(s) && hist.length < 5) { hist.push(porId.get(s)); s = porId.get(s).substitui; }
  const texto = el("div", { class: "obs-texto" }, o.texto);
  const bEd = el("button", { type: "button", class: "mini", title: "corrigir (a versão atual vai pro histórico)" }, "✎");
  bEd.addEventListener("click", () => {
    const area = el("textarea", { "aria-label": "texto corrigido" });
    area.value = o.texto;
    const ok = el("button", { type: "button", class: "neon mini" }, "salvar correção");
    ok.addEventListener("click", async () => {
      try {
        await api("/cerebro/observacoes", { method: "POST", body: JSON.stringify({ entidade_id: entId, categoria: o.categoria, texto: area.value, substitui: o.id }) });
        aviso("Corrigido — a anterior ficou no histórico"); await cerCarregar();
      } catch (x) { aviso(x.message, true); }
    });
    texto.replaceChildren(area, el("div", { class: "linha-form" }, ok,
      el("button", { type: "button", class: "mini", onclick: () => abrirFicha(entId, { semZoom: true }) }, "cancelar")));
    area.focus();
  });
  const bInv = el("button", { type: "button", class: "mini", title: "não vale mais (fica no histórico)", onclick: async () => {
    await api(`/cerebro/observacoes/${o.id}/invalidar`, { method: "POST" }); aviso("Invalidada — ficou no histórico"); await cerCarregar();
  } }, "⊘");
  const bDel = el("button", { type: "button", class: "mini perigo", title: "apagar de vez (some até do histórico)", onclick: async () => {
    if (!confirm("Apagar de vez esta observação? (some até do histórico)")) return;
    await api(`/cerebro/observacoes/${o.id}`, { method: "DELETE" }); aviso("Apagada"); await cerCarregar();
  } }, "🗑");
  return el("div", { class: "obs-item" },
    el("div", { class: "obs-linha" }, texto, el("div", { class: "obs-acoes" }, bEd, bInv, bDel)),
    el("div", { class: "obs-quando" }, `desde ${dataHora(o.valido_desde)}`),
    hist.length ? el("details", { class: "obs-hist" }, el("summary", {}, `${hist.length} versão(ões) anterior(es)`),
      ...hist.map((h) => el("div", { class: "obs-antes" }, el("s", {}, h.texto), ` · ${dataHora(h.valido_desde)} → ${dataHora(h.invalido_em)}`))) : null);
}

function formObs(entId, cats) {
  const listaId = `cats-${entId}`;
  const cat = el("input", { type: "text", list: listaId, placeholder: "categoria", class: "inline", "aria-label": "categoria" });
  const txt = el("input", { type: "text", placeholder: "nova observação…", "aria-label": "texto" });
  const b = el("button", { type: "button", class: "neon mini" }, "＋");
  const enviar = async () => {
    if (!txt.value.trim()) return;
    try {
      const r = await api("/cerebro/observacoes", { method: "POST", body: JSON.stringify({ entidade_id: entId, categoria: cat.value || SEM_CAT, texto: txt.value }) });
      aviso(r.op === "NOOP" ? "Já estava gravado" : "Gravado"); await cerCarregar();
    } catch (x) { aviso(x.message, true); }
  };
  b.addEventListener("click", enviar);
  txt.addEventListener("keydown", (k) => { if (k.key === "Enter") enviar(); });
  return el("div", { class: "form-linha" }, cat, el("datalist", { id: listaId },
    [...new Set([...cats, "preferencia", "rotina", "trabalho", "objetivo", "saude", "nome", "execucao"])].map((c) => el("option", { value: c }))), txt, b);
}

function formRel(entId) {
  const listaId = `ents-${entId}`;
  const tipo = el("input", { type: "text", placeholder: "ligação (ex.: grupo)", class: "inline", "aria-label": "tipo da ligação" });
  const para = el("input", { type: "text", list: listaId, placeholder: "com quem/o quê", "aria-label": "outra entidade" });
  const b = el("button", { type: "button", class: "neon mini" }, "＋");
  const enviar = async () => {
    try {
      await api("/cerebro/relacoes", { method: "POST", body: JSON.stringify({ de_id: entId, tipo: tipo.value, para: para.value }) });
      aviso("Ligação criada"); await cerCarregar();
    } catch (x) { aviso(x.message, true); }
  };
  b.addEventListener("click", enviar);
  para.addEventListener("keydown", (k) => { if (k.key === "Enter") enviar(); });
  return el("div", { class: "form-linha" }, tipo, para,
    el("datalist", { id: listaId }, CER.dados.entidades.map((e) => el("option", { value: e.nome }))), b);
}

function itemReg(r, comDia = true) {
  return el("div", { class: "reg-item" + (r.eh_sessao ? " sessao" : "") },
    el("div", {},
      el("span", { class: "reg-quando" }, comDia ? `${dataHora(r.quando)}` : new Date(r.quando * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })),
      el("span", { class: "chip" }, r.tipo),
      r.entidade ? el("b", {}, ` ${r.entidade}`) : null,
      Object.keys(r.dados || {}).length ? el("span", { class: "reg-dados" }, ` · ${fmtDados(r.dados)}`) : null,
      r.texto ? el("span", { class: "meta" }, ` · “${r.texto}”`) : null),
    el("button", { type: "button", class: "mini", title: "invalidar (fica no histórico)", onclick: async () => {
      if (!confirm("Invalidar este registro?")) return;
      await api(`/cerebro/registros/${r.id}/invalidar`, { method: "POST" }); aviso("Registro invalidado");
      await cerCarregar(); if (CER.vista === "tempo") await carregarTempo();
    } }, "⊘"));
}

function fmtDados(d) {
  const p = [], r = { ...d };
  if (r.series != null && r.reps != null) { p.push(`${r.series}×${r.reps}`); delete r.series; delete r.reps; }
  for (const [k, u] of [["carga_kg", "kg"], ["peso_kg", "kg"], ["duracao_min", "min"], ["distancia_km", "km"]]) {
    if (r[k] != null) { p.push(`${r[k]} ${u}`); delete r[k]; }
  }
  for (const [k, v] of Object.entries(r)) p.push(`${k}: ${v}`);
  return p.join(" · ");
}

// ── gráfico SVG neon (sem biblioteca) ───────────────────────────────────────────────────────────────────
const CORES_SERIE = ["#22e5ff", "#ff3fd8", "#6dff8b", "#ffd23f", "#a78bff", "#3dffc5", "#ff8a3d"];

function grafico(regs, metrica) {
  // uma linha POR ASSUNTO (supino e crucifixo juntos numa linha só viravam zigue-zague)
  const series = new Map();
  for (const r of regs) {
    if (typeof r.dados?.[metrica] !== "number") continue;
    const k = r.entidade || r.tipo;
    (series.get(k) || series.set(k, []).get(k)).push({ t: r.quando, v: r.dados[metrica] });
  }
  const todas = [...series.values()].flat();
  if (todas.length < 2) return el("p", { class: "meta" }, todas.length ? `um só valor: ${todas[0].v} (${dataHora(todas[0].t)})` : "sem valores");
  for (const pts of series.values()) pts.sort((a, b) => a.t - b.t);
  const W = 720, H = 220, P = { l: 40, r: 14, t: 14, b: 28 };
  const t0 = Math.min(...todas.map((p) => p.t)), t1 = Math.max(...todas.map((p) => p.t));
  let v0 = Math.min(...todas.map((p) => p.v)), v1 = Math.max(...todas.map((p) => p.v));
  if (v0 === v1) { v0 -= 1; v1 += 1; }
  const x = (t) => P.l + ((t - t0) / (t1 - t0 || 1)) * (W - P.l - P.r);
  const y = (v) => H - P.b - ((v - v0) / (v1 - v0)) * (H - P.t - P.b);
  const ns = "http://www.w3.org/2000/svg";
  const s = (tag, a) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(a)) n.setAttribute(k, v); return n; };
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "grafico", role: "img", "aria-label": `evolução de ${metrica}` });
  for (const v of [v0, (v0 + v1) / 2, v1]) {
    svg.append(s("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), stroke: "#1d2a44", "stroke-dasharray": "3 4" }));
    const tx = s("text", { x: P.l - 6, y: y(v) + 4, "text-anchor": "end", fill: "#8794b3", "font-size": "11" });
    tx.textContent = Math.round(v * 10) / 10;
    svg.append(tx);
  }
  const defs = s("defs", {});
  svg.append(defs);
  const leg = [];
  [...series.entries()].forEach(([nome, pts], i) => {
    const cor = CORES_SERIE[i % CORES_SERIE.length];
    const linha = pts.map((p, k) => `${k ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    if (series.size === 1 && pts.length > 1) {                      // uma série: área com degradê
      const id = `g${Math.random().toString(36).slice(2, 8)}`;
      const grad = s("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 });
      grad.append(s("stop", { offset: "0%", "stop-color": cor, "stop-opacity": "0.35" }), s("stop", { offset: "100%", "stop-color": cor, "stop-opacity": "0" }));
      defs.append(grad);
      svg.append(s("path", { d: `${linha} L${x(pts[pts.length - 1].t)},${H - P.b} L${x(pts[0].t)},${H - P.b} Z`, fill: `url(#${id})` }));
    }
    svg.append(s("path", { d: linha, fill: "none", stroke: cor, "stroke-width": "2.2", style: `filter:drop-shadow(0 0 4px ${cor})` }));
    for (const p of pts) {
      const c = s("circle", { cx: x(p.t), cy: y(p.v), r: 3.2, fill: "#06080e", stroke: cor, "stroke-width": "1.6" });
      const tt = s("title", {});
      tt.textContent = `${nome} · ${dataHora(p.t)} · ${p.v}`;
      c.append(tt);
      svg.append(c);
    }
    const ult = pts[pts.length - 1], pri = pts[0];
    const delta = Math.round((ult.v - pri.v) * 10) / 10;
    leg.push(el("span", { class: "serie-leg" }, el("i", { style: `background:${cor};box-shadow:0 0 8px ${cor}` }),
      `${nome}: ${pri.v} → ${ult.v}`, el("b", { class: delta >= 0 ? "sobe" : "desce" }, ` (${delta >= 0 ? "+" : ""}${delta})`)));
  });
  for (const [t, ancora] of [[t0, "start"], [t1, "end"]]) {
    const tx = s("text", { x: x(t), y: H - 8, "text-anchor": ancora, fill: "#8794b3", "font-size": "11" });
    tx.textContent = dataHora(t);
    svg.append(tx);
  }
  return el("div", { class: "grafico-caixa" }, svg, el("div", { class: "series-leg" }, leg));
}

// ── nova entidade (modal) ───────────────────────────────────────────────────────────────────────────────
function novaEntidade() {
  const nome = el("input", { type: "text", placeholder: "nome (ex.: Supino reto, Ana, Cálculo)", "aria-label": "nome" });
  const tipo = el("input", { type: "text", list: "tipos-novo", placeholder: "tipo (ex.: exercicio, pessoa, disciplina)", "aria-label": "tipo" });
  const b = el("button", { type: "button", class: "neon" }, "Criar");
  const criar = async () => {
    try {
      const e = await api("/cerebro/entidades", { method: "POST", body: JSON.stringify({ nome: nome.value, tipo: tipo.value || null }) });
      $("#modal").hidden = true; aviso(`“${e.nome}” criado`); await cerCarregar(); await abrirFicha(e.id);
    } catch (x) { aviso(x.message, true); }
  };
  b.addEventListener("click", criar);
  nome.addEventListener("keydown", (k) => { if (k.key === "Enter") criar(); });
  abrirModal(el("div", { class: "form-modal" }, el("h3", {}, "Nova entidade"),
    el("label", { class: "campo" }, "Nome", nome),
    el("label", { class: "campo" }, "Tipo", tipo, el("datalist", { id: "tipos-novo" }, CER.dados.tipos.map((t) => el("option", { value: t.nome })))),
    el("p", { class: "meta" }, "A área vem do tipo (exercicio → Academia, disciplina → Estudos…). Tipo novo entra em Geral; dá pra mudar na ficha."),
    el("div", { class: "linha-form" }, b)));
  setTimeout(() => nome.focus(), 50);
}

// ── busca ───────────────────────────────────────────────────────────────────────────────────────────────
let buscaTimer;
async function buscar(q) {
  const caixa = $("#cer-resultados");
  if (!q.trim()) { caixa.hidden = true; return; }
  const r = await api(`/cerebro/busca?q=${encodeURIComponent(q)}`);
  const ents = new Map(CER.dados.entidades.map((e) => [e.nome, e.id]));
  const itens = [
    ...r.entidades.map((e) => el("button", { type: "button", class: "res", onclick: () => { caixa.hidden = true; abrirFicha(e.id); } },
      el("i", { class: "bolinha", style: `--c:${corArea(e.area)}` }), el("b", {}, e.nome), el("span", { class: "meta" }, ` · ${e.tipo}`))),
    ...r.observacoes.map((o) => el("button", { type: "button", class: "res", onclick: () => { caixa.hidden = true; abrirFicha(ents.get(o.entidade) ?? o.entidade_id); } },
      el("b", {}, o.entidade), el("span", { class: "meta" }, ` [${o.categoria}] `), o.texto)),
  ];
  caixa.replaceChildren(...(itens.length ? itens : [el("p", { class: "meta" }, "nada encontrado")]));
  caixa.hidden = false;
}

// ── linha do tempo ──────────────────────────────────────────────────────────────────────────────────────
async function carregarTempo() {
  const tipo = $("#lt-tipo").value, ent = $("#lt-ent").value;
  const q = new URLSearchParams();
  if (tipo) q.set("tipo", tipo);
  if (ent) q.set("entidade_id", ent);
  if (CER.ltDias) q.set("desde", String(Date.now() / 1000 - CER.ltDias * 86400));
  const { registros } = await api(`/cerebro/registros?${q}`);

  // selects (mantém a escolha)
  const tipos = [...new Set(registros.map((r) => r.tipo))].sort();
  if (!tipo) $("#lt-tipo").replaceChildren(el("option", { value: "" }, "Todos"), ...tipos.map((t) => el("option", { value: t }, t)));
  const entsOpt = CER.dados.entidades.filter((e) => e.n_reg > 0);
  $("#lt-ent").replaceChildren(el("option", { value: "" }, "Todos"), ...entsOpt.map((e) => el("option", { value: e.id, selected: String(e.id) === ent }, e.nome)));
  const metricas = [...new Set(registros.flatMap((r) => Object.entries(r.dados || {}).filter(([, v]) => typeof v === "number").map(([k]) => k)))].sort();
  const mAtual = $("#lt-metrica").value;
  $("#lt-metrica").replaceChildren(el("option", { value: "" }, "—"), ...metricas.map((m) => el("option", { value: m, selected: m === mAtual }, m)));

  const m = $("#lt-metrica").value;
  $("#lt-grafico-card").hidden = !m;
  if (m) {
    $("#lt-grafico-titulo").textContent = `Evolução de ${m}${ent ? ` · ${$("#lt-ent").selectedOptions[0].textContent}` : ""}`;
    $("#lt-grafico").replaceChildren(grafico(registros, m));
  }

  // lista por dia
  const dias = new Map();
  for (const r of registros) {
    const d = new Date(r.quando * 1000).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
    (dias.get(d) || dias.set(d, []).get(d)).push(r);
  }
  $("#lt-lista").replaceChildren(...(registros.length ? [...dias.entries()].map(([d, lista]) =>
    el("div", { class: "card lt-dia" }, el("h3", {}, d), ...lista.map((r) => itemReg(r, false))))
    : [el("div", { class: "vazio" }, "Nenhum registro no período. Na academia: “vou começar o treino de peito”, “supino 3 de 12 com 20”…")]));
}

// ── revisar ─────────────────────────────────────────────────────────────────────────────────────────────
async function carregarRevisar() {
  const r = await api(`/cerebro/revisar?dias=${CER.rvDias}`);
  const ents = new Map(CER.dados.entidades.map((e) => [e.id, e]));
  $("#rv-obs").replaceChildren(...(r.observacoes.length ? r.observacoes.map((o) => {
    const estado = o.invalido_em ? el("span", { class: "chip negada" }, "não vale mais")
      : o.substitui ? el("span", { class: "chip manual" }, "correção") : el("span", { class: "chip ok" }, "nova");
    return el("div", { class: "rv-item" },
      el("div", {}, estado, " ", el("a", { href: "#", onclick: (ev) => { ev.preventDefault(); trocarVista("grafo"); abrirFicha(o.entidade_id); } }, o.entidade),
        el("span", { class: "meta" }, ` [${o.categoria}] · ${dataHora(o.valido_desde)}`)),
      el("div", { class: "obs-linha" }, el("div", { class: "obs-texto" }, o.invalido_em ? el("s", {}, o.texto) : o.texto),
        el("div", { class: "obs-acoes" },
          o.invalido_em ? null : el("button", { type: "button", class: "mini", title: "invalidar", onclick: async () => {
            await api(`/cerebro/observacoes/${o.id}/invalidar`, { method: "POST" }); aviso("Invalidada"); await cerCarregar(); await carregarRevisar();
          } }, "⊘"),
          el("button", { type: "button", class: "mini perigo", title: "apagar de vez", onclick: async () => {
            if (!confirm("Apagar de vez?")) return;
            await api(`/cerebro/observacoes/${o.id}`, { method: "DELETE" }); aviso("Apagada"); await cerCarregar(); await carregarRevisar();
          } }, "🗑"))));
  }) : [el("p", { class: "meta" }, "Nada gravado no período.")]));
  void ents;
  $("#rv-reg").replaceChildren(...(r.registros.length ? r.registros.map((x) => itemReg(x)) : [el("p", { class: "meta" }, "Nenhum registro no período.")]));
}

// ── vistas e eventos ────────────────────────────────────────────────────────────────────────────────────
function trocarVista(v) {
  CER.vista = v;
  document.querySelectorAll("#cer-vistas button").forEach((b) => b.classList.toggle("sel", b.dataset.v === v));
  for (const x of ["grafo", "tempo", "revisar"]) $(`#cer-v-${x}`).hidden = x !== v;
  const erro = (x) => aviso(x.message, true);
  if (v === "tempo") carregarTempo().catch(erro);
  if (v === "revisar") carregarRevisar().catch(erro);
  if (v === "grafo" && CER.grafo) setTimeout(() => CER.grafo.width($("#cer-grafo").clientWidth).height($("#cer-grafo").clientHeight), 0);
}

function ligarEventos() {
  $("#cer-vistas").addEventListener("click", (e) => { if (e.target.dataset?.v) trocarVista(e.target.dataset.v); });
  $("#cer-nova").addEventListener("click", novaEntidade);
  $("#cer-centro").addEventListener("click", () => CER.grafo && CER.grafo.zoomToFit(600, 60));
  $("#cer-rotulos").addEventListener("click", () => { CER.rotulos = !CER.rotulos; $("#cer-rotulos").classList.toggle("sel", CER.rotulos); });
  $("#cer-busca").addEventListener("input", (e) => { clearTimeout(buscaTimer); buscaTimer = setTimeout(() => buscar(e.target.value).catch(() => {}), 250); });
  $("#cer-busca").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; $("#cer-resultados").hidden = true; } });
  $("#lt-tipo").addEventListener("change", () => carregarTempo().catch((x) => aviso(x.message, true)));
  $("#lt-ent").addEventListener("change", () => carregarTempo().catch((x) => aviso(x.message, true)));
  $("#lt-metrica").addEventListener("change", () => carregarTempo().catch((x) => aviso(x.message, true)));
  $("#lt-periodo").addEventListener("click", (e) => {
    const d = e.target.dataset?.d;
    if (d === undefined) return;
    CER.ltDias = Number(d);
    document.querySelectorAll("#lt-periodo button").forEach((b) => b.classList.toggle("sel", b.dataset.d === d));
    carregarTempo().catch((x) => aviso(x.message, true));
  });
  $("#rv-dias").addEventListener("click", (e) => {
    const d = e.target.dataset?.d;
    if (d === undefined) return;
    CER.rvDias = Number(d);
    document.querySelectorAll("#rv-dias button").forEach((b) => b.classList.toggle("sel", b.dataset.d === d));
    carregarRevisar().catch((x) => aviso(x.message, true));
  });
}

window.cerebroAbrir = async () => {
  if (!CER.iniciado) { CER.iniciado = true; ligarEventos(); }
  if (CER.dados === null && !CER.rotulosDecidido) {      // poucos nós: nomes sempre visíveis
    CER.rotulosDecidido = true;
    const d = await api("/cerebro").catch(() => null);
    CER.rotulos = !!d && d.entidades.length <= 40;
    $("#cer-rotulos").classList.toggle("sel", CER.rotulos);
  }
  try { await cerCarregar(); } catch (x) { aviso(`Cérebro: ${x.message}`, true); }
  trocarVista(CER.vista);
};
window.cerebroRecarregar = async () => {
  await cerCarregar();
  if (CER.vista === "tempo") await carregarTempo();
  if (CER.vista === "revisar") await carregarRevisar();
};
