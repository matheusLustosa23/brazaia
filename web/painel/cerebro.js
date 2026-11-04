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
  filtro: { areas: new Set(), tipos: new Set(), periodo: null },   // vazio = "Todos"; periodo = {rotulo, desde, ate}
  rotulos: false,
  expandidas: new Set(),    // áreas (lobos) abertas
  abertos: new Set(),       // entidades com as conexões à mostra
  forcados: new Set(),      // entidades abertas pela lista/busca mesmo com o lobo recolhido
  gruposAbertos: new Set(), // grupos (Peito, Costas…) com os itens à mostra
  vista: "grafo",
  ltDias: 0,                // 0 = tudo (o histórico costuma ser antigo)
  iniciado: false,
  pilha: [],                // ids das fichas anteriores (← Voltar)
  destaque: new Set(),      // ids acesos pela busca (o resto apaga; as regiões brilham)
};

// cor por área (a "frente" do agente): a mesma em nó, legenda e chips
const AREA_COR = {
  voce: "#22e5ff", academia: "#6dff8b", estudos: "#ffd23f", trabalho: "#ff3fd8",
  pessoas: "#a78bff", financas: "#3dffc5", pessoal: "#ff8a3d", geral: "#7f8db3",
};
const AREA_NOME = {
  voce: "Você", academia: "Academia", estudos: "Estudos", trabalho: "Trabalho",
  pessoas: "Pessoas", financas: "Finanças", pessoal: "Pessoal", geral: "Geral",
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
  marcarNivel();
  if (CER.vista === "lista") renderListaCerebro();
  if (CER.sel) await abrirFicha(CER.sel, { semZoom: true }).catch(() => { CER.sel = null; fichaVazia(); });
}

// ── grafo: um cérebro com neurônios ─────────────────────────────────────────────────────────────────────
// Cada ÁREA mora num lobo (Trabalho no frontal, Academia no córtex motor, Estudos no parietal, Pessoas no
// temporal, Finanças no cerebelo…). Entidade = neurônio (corpo + dendritos + emoji do tipo); ligação = axônio
// curvo com faíscas de sinapse. Começa RECOLHIDO (você + lobos): clicar num lobo abre o que mora nele;
// clicar numa entidade abre as conexões dela (clicar de novo recolhe).

const EMOJI_TIPO = {
  dono: "🧑", exercicio: "🏋️", "grupo muscular": "💪", treino: "🔥", disciplina: "📚", tema: "🧩",
  instituicao: "🎓", projeto: "🛠️", empresa: "🏢", ferramenta: "🔧", pessoa: "👤", meta: "🎯", lugar: "📍",
  financa: "💰", conta: "🧾", cartao: "💳", fluxo: "🔁", geral: "✨",
};
const EMOJI_AREA = { voce: "🧑", academia: "🏋️", estudos: "📚", trabalho: "💼", pessoas: "👥", financas: "💰", pessoal: "🌱", geral: "✨" };
function emojiDe(n) {
  if (n.dono) return "🧑";
  if (n.hub) return EMOJI_AREA[n.area] || "✨";
  const nome = (n.nome || "").toLowerCase();
  if (n.tipo === "grupo muscular" && /perna|panturrilha|gl[uú]teo|coxa/.test(nome)) return "🦵";
  return EMOJI_TIPO[n.tipo] || "✨";
}

// lobos: posição de cada área no cérebro (unidades de S = "raio" do cérebro), vista lateral olhando à esquerda
const LOBO = {
  trabalho: { x: -0.58, y: -0.18, nome: "lobo frontal" },
  academia: { x: 0.05, y: -0.5, nome: "córtex motor" },
  estudos: { x: 0.52, y: -0.3, nome: "lobo parietal" },
  pessoas: { x: -0.08, y: 0.32, nome: "lobo temporal" },
  financas: { x: 0.62, y: 0.52, nome: "cerebelo" },
  pessoal: { x: -0.36, y: 0.08, nome: "sistema límbico" },
  geral: { x: 0.68, y: 0.05, nome: "lobo occipital" },
};
const LOBOS_LIVRES = [{ x: -0.42, y: 0.12 }, { x: 0.3, y: 0.18 }, { x: -0.3, y: -0.45 }];
function loboDe(area, i = 0) {
  return LOBO[area] || { ...LOBOS_LIVRES[i % LOBOS_LIVRES.length], nome: nomeArea(area) };
}

let ESCALA = 320;                          // "raio" do cérebro em unidades do grafo (cresce com o que está aberto)

function hashId(v) {
  let h = 2166136261;
  for (const c of String(v)) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return (h >>> 0) / 4294967295;
}

function hierarquia() {
  // grupo = alvo de ligação vinda de outra entidade da MESMA área (Supino —grupo→ Peito): Peito é grupo, Supino é item dele
  const d = CER.dados;
  const porId = new Map(d.entidades.map((e) => [e.id, e]));
  const paisDe = new Map(), filhos = new Map();
  for (const r of d.relacoes) {
    const a = porId.get(r.de), b = porId.get(r.para);
    if (!a || !b || a.area !== b.area || a.nome === DONO || b.nome === DONO) continue;
    (paisDe.get(a.id) || paisDe.set(a.id, new Set()).get(a.id)).add(b.id);
    (filhos.get(b.id) || filhos.set(b.id, []).get(b.id)).push(a.id);
  }
  return { paisDe, filhos };
}

function visiveis() {
  // 3 níveis: área recolhida (só o lobo) → área aberta (grupos + itens sem grupo) → grupo aberto (os itens dele)
  const d = CER.dados;
  const porId = new Map(d.entidades.map((e) => [e.id, e]));
  const { paisDe, filhos } = hierarquia();
  const vis = new Set();
  for (const e of d.entidades) {
    if (e.nome === DONO) { vis.add(e.id); continue; }
    if (!passaFiltro(e)) continue;
    if (CER.forcados.has(e.id) || CER.filtro.tipos.size) { vis.add(e.id); continue; }   // busca / filtro de tipo
    if (!CER.expandidas.has(e.area)) continue;
    const pais = paisDe.get(e.id);
    const ehGrupo = filhos.has(e.id);
    if (ehGrupo || !pais || [...pais].some((p) => CER.gruposAbertos.has(p))) vis.add(e.id);
  }
  for (const r of d.relacoes) {                              // entidade aberta → mostra quem está ligado a ela
    if (CER.abertos.has(r.de) && porId.get(r.para) && passaFiltro(porId.get(r.para))) vis.add(r.para);
    if (CER.abertos.has(r.para) && porId.get(r.de) && passaFiltro(porId.get(r.de))) vis.add(r.de);
  }
  return vis;
}

function dadosGrafo() {
  const d = CER.dados;
  const dono = d.entidades.find((e) => e.nome === DONO);
  const vis = visiveis();
  const contaArea = {};
  for (const e of d.entidades) if (e.nome !== DONO && passaFiltro(e)) contaArea[e.area] = (contaArea[e.area] || 0) + 1;
  const areas = Object.keys(contaArea);
  ESCALA = 300 + 26 * Math.sqrt(vis.size);
  const nodes = [], links = [];
  areas.forEach((a, i) => {
    const l = loboDe(a, i);
    const ocultas = d.entidades.filter((e) => e.area === a && e.nome !== DONO && !vis.has(e.id)).length;
    nodes.push({ id: `area:${a}`, hub: true, area: a, nome: nomeArea(a), lobo: l.nome, total: contaArea[a], ocultas,
                 fx: l.x * ESCALA, fy: l.y * ESCALA });
  });
  const porId = new Map(d.entidades.map((e) => [e.id, e]));
  const pais = new Set();                                    // "grupo": alvo de ligação vinda da mesma área (Peito ← Supino)
  for (const r of d.relacoes) {
    const a = porId.get(r.de), b = porId.get(r.para);
    if (a && b && a.area === b.area && b.nome !== DONO) pais.add(b.id);
  }
  const { filhos } = hierarquia();
  for (const e of d.entidades) {
    if (!vis.has(e.id)) continue;
    const ocultos = (filhos.get(e.id) || []).filter((f) => !vis.has(f) && passaFiltro(porId.get(f))).length;
    nodes.push({ id: e.id, nome: e.nome, tipo: e.tipo, area: e.area, dono: e.nome === DONO, peso: e.n_obs + e.n_reg,
                 n_obs: e.n_obs, n_reg: e.n_reg, pai: pais.has(e.id), ocultos, ...(e.nome === DONO ? { fx: 0, fy: 0 } : {}) });
  }
  if (dono) for (const a of areas) links.push({ source: dono.id, target: `area:${a}`, virtual: true, area: a });
  for (const e of d.entidades) if (vis.has(e.id) && e.nome !== DONO && contaArea[e.area]) links.push({ source: `area:${e.area}`, target: e.id, virtual: true, area: e.area });
  for (const r of d.relacoes) if (vis.has(r.de) && vis.has(r.para)) links.push({ source: r.de, target: r.para, tipo: r.tipo, id: r.id });
  return { nodes, links };
}

function raio(n) {
  if (n.dono) return 17;
  if (n.hub) return 13;
  if (n.pai) return 11 + Math.sqrt(n.peso || 0) * 1.2;
  return 6 + Math.sqrt(n.peso || 0) * 1.6;
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

// ── o cérebro (desenhado no fundo, em coordenadas do grafo: acompanha zoom e arraste) ────────────────────
function desenharCerebro(ctx, escala) {
  const S = ESCALA;
  const P = (x, y) => [x * S, y * S];
  ctx.save();
  // contorno lateral (frente à esquerda): testa, topo, nuca, base do temporal
  const contorno = new Path2D();
  contorno.moveTo(...P(-0.92, 0.05));
  contorno.bezierCurveTo(...P(-1.0, -0.42), ...P(-0.62, -0.82), ...P(-0.12, -0.8));
  contorno.bezierCurveTo(...P(0.35, -0.86), ...P(0.86, -0.66), ...P(0.95, -0.22));
  contorno.bezierCurveTo(...P(1.02, 0.08), ...P(0.92, 0.3), ...P(0.74, 0.36));
  contorno.bezierCurveTo(...P(0.55, 0.42), ...P(0.42, 0.44), ...P(0.3, 0.42));
  contorno.bezierCurveTo(...P(0.12, 0.58), ...P(-0.25, 0.6), ...P(-0.45, 0.48));
  contorno.bezierCurveTo(...P(-0.7, 0.42), ...P(-0.88, 0.3), ...P(-0.92, 0.05));
  const cerebelo = new Path2D();
  cerebelo.moveTo(...P(0.3, 0.42));
  cerebelo.bezierCurveTo(...P(0.42, 0.78), ...P(0.86, 0.76), ...P(0.9, 0.5));
  cerebelo.bezierCurveTo(...P(0.92, 0.38), ...P(0.8, 0.34), ...P(0.74, 0.36));
  const tronco = new Path2D();
  tronco.moveTo(...P(0.18, 0.5));
  tronco.bezierCurveTo(...P(0.2, 0.75), ...P(0.24, 0.92), ...P(0.3, 1.02));
  tronco.moveTo(...P(0.33, 0.6));
  tronco.bezierCurveTo(...P(0.34, 0.78), ...P(0.38, 0.92), ...P(0.42, 1.02));

  const g = ctx.createRadialGradient(0, 0, S * 0.1, 0, 0, S * 1.05);
  g.addColorStop(0, "rgba(34,229,255,0.10)");
  g.addColorStop(0.6, "rgba(120,80,255,0.06)");
  g.addColorStop(1, "rgba(255,63,216,0.03)");
  ctx.fillStyle = g;
  ctx.fill(contorno);
  ctx.fillStyle = "rgba(109,255,139,0.04)";
  ctx.fill(cerebelo);

  ctx.lineWidth = 2 / escala;
  ctx.shadowColor = "#22e5ff";
  ctx.shadowBlur = 18;
  ctx.strokeStyle = "rgba(34,229,255,0.55)";
  ctx.stroke(contorno);
  ctx.strokeStyle = "rgba(109,255,139,0.35)";
  ctx.stroke(cerebelo);
  ctx.strokeStyle = "rgba(34,229,255,0.25)";
  ctx.stroke(tronco);
  ctx.shadowBlur = 0;

  // giros e sulcos (as "dobras"): curvas tênues, mais o sulco central e a fissura lateral
  ctx.strokeStyle = "rgba(34,229,255,0.13)";
  ctx.lineWidth = 1.4 / escala;
  const giros = [
    [[-0.8, -0.2], [-0.65, -0.5], [-0.4, -0.55], [-0.35, -0.3]],
    [[-0.75, 0.1], [-0.6, -0.15], [-0.5, 0.05], [-0.45, -0.1]],
    [[-0.3, -0.7], [-0.2, -0.45], [-0.05, -0.6], [0.05, -0.35]],
    [[0.2, -0.75], [0.3, -0.5], [0.45, -0.65], [0.55, -0.4]],
    [[0.6, -0.55], [0.75, -0.35], [0.6, -0.2], [0.82, -0.05]],
    [[-0.5, 0.35], [-0.3, 0.25], [-0.15, 0.45], [0.05, 0.3]],
    [[0.1, -0.15], [0.25, -0.05], [0.3, 0.15], [0.5, 0.05]],
    [[0.45, 0.55], [0.6, 0.48], [0.7, 0.62], [0.82, 0.52]],
  ];
  for (const [a, b, c, d] of giros) {
    ctx.beginPath();
    ctx.moveTo(...P(...a));
    ctx.bezierCurveTo(...P(...b), ...P(...c), ...P(...d));
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(255,63,216,0.22)";
  ctx.lineWidth = 1.8 / escala;
  ctx.beginPath();                                          // sulco central
  ctx.moveTo(...P(-0.08, -0.8)); ctx.bezierCurveTo(...P(-0.02, -0.55), ...P(-0.15, -0.35), ...P(-0.05, -0.12)); ctx.stroke();
  ctx.beginPath();                                          // fissura lateral (Sylvius)
  ctx.moveTo(...P(-0.62, 0.22)); ctx.bezierCurveTo(...P(-0.3, 0.12), ...P(0.0, 0.12), ...P(0.35, -0.02)); ctx.stroke();

  // regiões acesas pela busca: um brilho no lobo de cada área onde o assunto mora (tipo ressonância)
  if (CER.destaque.size) {
    const conta = {};
    for (const n of CER.grafo.graphData().nodes) if (CER.destaque.has(n.id)) conta[n.area] = (conta[n.area] || 0) + 1;
    for (const n of CER.grafo.graphData().nodes) {
      if (!n.hub || !conta[n.area] || !Number.isFinite(n.x)) continue;
      const rr = S * (0.22 + Math.min(0.18, conta[n.area] * 0.02));
      const pulso = 0.85 + Math.sin(Date.now() / 500) * 0.15;
      const gl = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, rr);
      gl.addColorStop(0, corArea(n.area) + "55");
      gl.addColorStop(0.55, corArea(n.area) + "22");
      gl.addColorStop(1, corArea(n.area) + "00");
      ctx.globalAlpha = pulso;
      ctx.fillStyle = gl;
      ctx.beginPath();
      ctx.arc(n.x, n.y, rr, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  // nome do lobo perto de cada área
  ctx.font = `600 ${Math.max(11 / escala, 4.5)}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  for (const n of CER.grafo.graphData().nodes) {
    if (!n.hub || !Number.isFinite(n.x)) continue;
    ctx.fillStyle = corArea(n.area) + "aa";
    ctx.fillText(n.lobo.toUpperCase(), n.x, n.y - raio(n) - 14 / escala);
  }
  ctx.restore();
}

function desenharNo(n, ctx, escala) {
  if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return;     // 1º quadro: a física ainda não posicionou
  const r = raio(n);
  const cor = n.dono ? AREA_COR.voce : corArea(n.area);
  const foco = CER.hover || (CER.sel != null ? { id: CER.sel } : null);
  const busca = CER.destaque.size > 0;
  const aceso = busca && (CER.destaque.has(n.id) || n.dono || (n.hub && areasAcesas().has(n.area)));
  const apagado = busca && !CER.hover ? !aceso : foco && CER.vizinhos.size && !CER.vizinhos.has(n.id);
  const selecionado = CER.sel === n.id;
  const aberto = CER.abertos.has(n.id) || (n.hub && CER.expandidas.has(n.area));
  const t = Date.now();
  ctx.save();
  ctx.globalAlpha = apagado ? 0.16 : 1;

  // dendritos: ramos curtos e tortos saindo do corpo (posição fixa por id)
  const h = hashId(n.id);
  const nd = n.hub ? 7 : n.dono ? 9 : 4 + Math.floor(h * 3);
  ctx.strokeStyle = cor + (n.hub ? "88" : "66");
  ctx.lineWidth = Math.max(0.8, r / 9);
  for (let i = 0; i < nd; i++) {
    const a = (i / nd) * Math.PI * 2 + h * 6.28;
    const len = r * (0.9 + hashId(`${n.id}:${i}`) * 0.9);
    const x1 = n.x + Math.cos(a) * r, y1 = n.y + Math.sin(a) * r;
    const x2 = n.x + Math.cos(a + 0.35) * (r + len), y2 = n.y + Math.sin(a + 0.35) * (r + len);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.quadraticCurveTo(n.x + Math.cos(a - 0.2) * (r + len * 0.6), n.y + Math.sin(a - 0.2) * (r + len * 0.6), x2, y2);
    ctx.stroke();
    ctx.beginPath();                                          // botão sináptico na ponta
    ctx.arc(x2, y2, Math.max(0.9, r / 10), 0, Math.PI * 2);
    ctx.fillStyle = cor;
    ctx.fill();
  }

  if (busca && CER.destaque.has(n.id)) {                      // achado pela busca: auréola amarela
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 5 + Math.sin(t / 300) * 1.5, 0, 2 * Math.PI);
    ctx.strokeStyle = "#ffe14d";
    ctx.lineWidth = 2;
    ctx.shadowColor = "#ffe14d";
    ctx.shadowBlur = 14;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  if (n.dono || selecionado) {                                // pulso
    const p = (t % 2400) / 2400;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 4 + p * 16, 0, 2 * Math.PI);
    ctx.strokeStyle = cor;
    ctx.globalAlpha = (apagado ? 0.08 : 0.6) * (1 - p);
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.globalAlpha = apagado ? 0.16 : 1;
  }

  // corpo do neurônio
  ctx.shadowColor = cor;
  ctx.shadowBlur = selecionado ? 30 : 18;
  ctx.beginPath();
  ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
  const g = ctx.createRadialGradient(n.x - r / 3, n.y - r / 3, r / 8, n.x, n.y, r);
  g.addColorStop(0, "#ffffff");
  g.addColorStop(0.3, cor);
  g.addColorStop(1, "#0a0e18");
  ctx.fillStyle = g;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.lineWidth = selecionado ? 2.4 : 1.2;
  ctx.strokeStyle = selecionado ? "#ffffff" : cor;
  ctx.stroke();

  // área recolhida: anel tracejado girando + quantos estão escondidos
  if ((n.hub && n.ocultas > 0) || (n.pai && n.ocultos > 0)) {
    const qtd = n.hub ? n.ocultas : n.ocultos;
    ctx.save();
    ctx.setLineDash([3, 3]);
    ctx.lineDashOffset = -(t / 60) % 12;
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 5, 0, 2 * Math.PI);
    ctx.strokeStyle = cor;
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();
    // contador legível em qualquer zoom: ~11px na tela no mínimo
    const br = Math.max(11 / escala, r * 0.62);
    const bx = n.x + r * 0.9 + br * 0.3, by = n.y - r * 0.9 - br * 0.3;
    ctx.beginPath();
    ctx.arc(bx, by, br, 0, 2 * Math.PI);
    ctx.fillStyle = "#06080e";
    ctx.fill();
    ctx.strokeStyle = cor;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = cor;
    ctx.font = `700 ${br * 1.05}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(`+${qtd}`, bx, by + 0.5);
  } else if (!n.hub && !n.dono && aberto) {
    ctx.beginPath();
    ctx.arc(n.x, n.y, r + 3, 0, 2 * Math.PI);
    ctx.strokeStyle = cor + "99";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // emoji do tipo no centro
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  if (n.hub || n.dono || n.pai) {                            // emoji só no GRUPO (lobo, você, Peito…), não em cada item
    ctx.font = `${r * 1.05}px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`;
    ctx.fillText(emojiDe(n), n.x, n.y + r * 0.05);
  }

  const poucos = filtrando() && CER.grafo.graphData().nodes.length <= 40;        // filtrado e enxuto: nomeia todos
  const mostrar = CER.rotulos || poucos || n.dono || n.hub || n.pai || selecionado || (busca && CER.destaque.has(n.id))
    || (CER.hover && CER.vizinhos.has(n.id)) || escala > 1.6;
  if (mostrar) {
    const fonte = Math.max((n.hub || n.dono ? 14 : 11) / escala, n.hub || n.dono ? 7 : 4);
    ctx.font = `${n.hub || n.dono ? "700 " : "500 "}${fonte}px system-ui, sans-serif`;
    ctx.textBaseline = "top";
    const texto = n.hub ? n.nome.toUpperCase() : n.nome;
    const y = n.y + r + (n.hub ? 9 : 6);
    ctx.lineWidth = 3 / escala;
    ctx.strokeStyle = "rgba(6,8,14,0.85)";
    ctx.strokeText(texto, n.x, y);
    ctx.fillStyle = n.hub ? cor : "#e6ecff";
    ctx.fillText(texto, n.x, y);
  }
  ctx.restore();
}

function areasAcesas() {
  const s = new Set();
  for (const e of CER.dados.entidades) if (CER.destaque.has(e.id)) s.add(e.area);
  return s;
}

// ligação como conexão neural: axônio com brilho, ramos finos ao longo e botão sináptico na chegada
function desenharAxonio(l, ctx, escala) {
  const a = l.source, b = l.target;
  if (typeof a !== "object" || !Number.isFinite(a.x) || !Number.isFinite(b.x)) return;
  const cor = corLink(l);
  const cp = l.__controlPoints;                                // a mesma curva que as partículas percorrem
  const ponto = (t) => {
    if (!cp) return [a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t];
    const u = 1 - t;
    return [u * u * a.x + 2 * u * t * cp[0] + t * t * b.x, u * u * a.y + 2 * u * t * cp[1] + t * t * b.y];
  };
  const caminho = () => {
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    if (cp) ctx.quadraticCurveTo(cp[0], cp[1], b.x, b.y); else ctx.lineTo(b.x, b.y);
  };
  ctx.save();
  if (l.virtual) {                                              // ligação ao lobo: dendrito tênue
    ctx.setLineDash([2 / escala * 2, 4 / escala * 2]);
    caminho();
    ctx.strokeStyle = cor;
    ctx.lineWidth = 0.8 / Math.sqrt(escala);
    ctx.stroke();
    ctx.restore();
    return;
  }
  caminho();                                                    // bainha (brilho largo)
  ctx.strokeStyle = cor.slice(0, 7) + "26";
  ctx.lineWidth = 6 / Math.sqrt(escala);
  ctx.stroke();
  caminho();                                                    // axônio
  ctx.strokeStyle = cor;
  ctx.lineWidth = 1.6 / Math.sqrt(escala);
  ctx.stroke();
  const h = hashId(`${l.id}`);                                  // ramos curtos (posição fixa por ligação)
  ctx.lineWidth = 0.8 / Math.sqrt(escala);
  for (const t of [0.3, 0.55, 0.78]) {
    const [x, y] = ponto(t), [x2, y2] = ponto(t + 0.02);
    const ang = Math.atan2(y2 - y, x2 - x) + (hashId(`${l.id}${t}`) > 0.5 ? 1 : -1) * (0.8 + h * 0.5);
    const len = 7 + h * 6;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.cos(ang) * len, y + Math.sin(ang) * len);
    ctx.stroke();
  }
  const [sx, sy] = ponto(0.93);                                 // botão sináptico
  ctx.beginPath();
  ctx.arc(sx, sy, 2.4, 0, Math.PI * 2);
  ctx.fillStyle = cor;
  ctx.shadowColor = cor;
  ctx.shadowBlur = 8;
  ctx.fill();
  if (escala >= 1.1 && l.tipo) {                                // nome da ligação
    const [mx, my] = ponto(0.5);
    ctx.shadowBlur = 0;
    ctx.font = `${Math.max(9 / escala, 2.6)}px system-ui, sans-serif`;
    ctx.fillStyle = "#ff9cf0";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(l.tipo, mx, my - 4 / escala);
  }
  ctx.restore();
}

function corLink(l) {
  const foco = CER.hover || (CER.sel != null ? { id: CER.sel } : null);
  const s = typeof l.source === "object" ? l.source.id : l.source;
  const t = typeof l.target === "object" ? l.target.id : l.target;
  const noFoco = foco && (s === foco.id || t === foco.id);
  if (CER.destaque.size && !CER.hover) {                        // busca: só as ligações entre os acesos
    const ok = (CER.destaque.has(s) || typeof s === "string") && (CER.destaque.has(t) || typeof t === "string");
    if (l.virtual) return corArea(l.area) + (ok ? "70" : "0c");
    return ok ? "#ff3fd8" : "#ff3fd81a";
  }
  if (l.virtual) {
    const c = corArea(l.area);
    return noFoco ? c + "99" : foco ? c + "12" : c + "40";
  }
  return noFoco ? "#ff3fd8" : foco ? "#ff3fd833" : "#ff3fd8b0";
}

// mantém cada neurônio perto do lobo da sua área e dentro do cérebro
function forcaLobos() {
  let nodes = [];
  const f = (alpha) => {
    for (const n of nodes) {
      if (n.fx != null || n.hub) continue;
      const alvo = CER.grafo ? CER.grafo.graphData().nodes.find((h) => h.hub && h.area === n.area) : null;
      if (alvo && Number.isFinite(alvo.x)) {
        n.vx += (alvo.x - n.x) * 0.12 * alpha;
        n.vy += (alvo.y - n.y) * 0.12 * alpha;
      }
      const cy = -0.12 * ESCALA;                                         // elipse "dentro do crânio"
      const ex = n.x / (ESCALA * 0.82), ey = (n.y - cy) / (ESCALA * 0.58);
      const d = Math.sqrt(ex * ex + ey * ey);
      if (d > 1) { n.vx -= (n.x - n.x / d) * 0.5 * alpha; n.vy -= ((n.y - cy) - (n.y - cy) / d) * 0.5 * alpha; }
    }
  };
  f.initialize = (ns) => { nodes = ns; };
  return f;
}

// colisão: cada neurônio ocupa o espaço do corpo + dendritos + o nome embaixo (sem amontoar)
function forcaColisao() {
  let nodes = [];
  const f = () => {
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < nodes.length; j++) {
        const b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const min = raio(a) + raio(b) + 26;
        const d2 = dx * dx + dy * dy;
        if (d2 >= min * min || d2 === 0) continue;
        const d = Math.sqrt(d2), empurra = (min - d) / d * 0.5;
        const fa = a.fx != null ? 0 : b.fx != null ? 1 : 0.5;          // fixo (você/lobo) não se mexe
        const fb = b.fx != null ? 0 : a.fx != null ? 1 : 0.5;
        a.x -= dx * empurra * fa; a.y -= dy * empurra * fa;
        b.x += dx * empurra * fb; b.y += dy * empurra * fb;
      }
    }
  };
  f.initialize = (ns) => { nodes = ns; };
  return f;
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
      .nodeLabel((n) => n.hub
        ? `${n.nome} · ${n.lobo} · ${n.total} ${n.ocultas ? `(clique pra abrir ${n.ocultas})` : "(clique pra recolher)"}`
        : `${emojiDe(n)} ${n.nome} · ${n.tipo}${n.n_obs ? ` · ${n.n_obs} obs` : ""}${n.n_reg ? ` · ${n.n_reg} reg` : ""}`)
      .nodeCanvasObject(desenharNo)
      .nodePointerAreaPaint((n, cor, ctx) => { ctx.fillStyle = cor; ctx.beginPath(); ctx.arc(n.x, n.y, raio(n) + 4, 0, 2 * Math.PI); ctx.fill(); })
      .onRenderFramePre((ctx, escala) => desenharCerebro(ctx, escala))
      .linkColor(corLink)
      .linkWidth((l) => (l.virtual ? 0.8 : 2.2))
      .linkCurvature((l) => (l.virtual ? 0.12 : 0.28))          // axônios curvos
      .linkLineDash((l) => (l.virtual ? [2, 4] : null))
      .linkDirectionalParticles((l) => (l.virtual ? 1 : 3))
      .linkDirectionalParticleWidth((l) => (l.virtual ? 1.4 : 2.8))
      .linkDirectionalParticleSpeed((l) => (l.virtual ? 0.004 : 0.007))
      .linkDirectionalParticleColor((l) => (l.virtual ? corArea(l.area) : "#ff9cf0"))
      .linkCanvasObjectMode(() => "replace")
      .linkCanvasObject(desenharAxonio)
      .onNodeHover((n) => { CER.hover = n || null; focoDe(n || (CER.sel != null ? { id: CER.sel } : null)); caixa.style.cursor = n ? "pointer" : ""; })
      .onNodeClick((n) => clicarNo(n))
      .onBackgroundClick(() => fecharFicha())
      .cooldownTicks(260)
      .autoPauseRedraw(false);                                   // pulso, dendritos e sinapses sempre vivos
    CER.grafo.d3Force("charge").strength((n) => (n.hub ? -200 : -70));
    CER.grafo.d3Force("link").distance((l) => (l.virtual ? 45 : 38)).strength((l) => {
      if (l.virtual) return 0.12;
      const a = l.source, b = l.target;                        // ligação entre lobos diferentes puxa pouco
      return typeof a === "object" && typeof b === "object" && a.area !== b.area ? 0.03 : 0.45;
    });
    CER.grafo.d3Force("lobos", forcaLobos());
    CER.grafo.d3Force("center", null);
    CER.grafo.d3Force("colisao", forcaColisao());                         // o padrão puxa tudo pro meio e briga com os lobos
    new ResizeObserver(() => CER.grafo.width(caixa.clientWidth).height(caixa.clientHeight)).observe(caixa);
    setTimeout(() => enquadrarCerebro(0), 60);
  }
  // preserva posições dos que já existiam (não "explode" a cada recarga); novos nascem no lobo da área
  const antigos = new Map(CER.grafo.graphData().nodes.map((n) => [n.id, n]));
  const hubs = new Map(dados.nodes.filter((n) => n.hub).map((n) => [n.area, n]));
  for (const n of dados.nodes) {
    const v = antigos.get(n.id);
    if (v && !n.hub && !n.dono) { n.x = v.x; n.y = v.y; n.vx = v.vx; n.vy = v.vy; }
    else if (!n.hub && !n.dono) {
      const h = hubs.get(n.area);
      if (h) { n.x = h.fx + (hashId(n.id) - 0.5) * 30; n.y = h.fy + (hashId(`y${n.id}`) - 0.5) * 30; }
    }
  }
  CER.grafo.graphData(dados);
  CER.grafo.d3ReheatSimulation();
  focoDe(CER.sel != null ? { id: CER.sel } : null);
  legenda();
}

function enquadrarCerebro(ms = 700) {
  // o cérebro inteiro na tela (não só os nós): largura ≈ 2·S, altura ≈ 1.85·S (com cerebelo e tronco)
  const caixa = $("#cer-grafo");
  const z = Math.min(caixa.clientWidth / (2.1 * ESCALA), caixa.clientHeight / (1.95 * ESCALA));
  CER.grafo.centerAt(0, ESCALA * 0.1, ms);
  CER.grafo.zoom(z, ms);
}

function clicarNo(n) {
  if (n.hub) {                                                 // lobo: abre/recolhe o que mora nele
    const abrir = !CER.expandidas.has(n.area);
    abrir ? CER.expandidas.add(n.area) : CER.expandidas.delete(n.area);
    if (!abrir) for (const e of CER.dados.entidades) if (e.area === n.area) { CER.abertos.delete(e.id); CER.forcados.delete(e.id); CER.gruposAbertos.delete(e.id); }
    salvarExpansao();
    desenharGrafo();
    if (abrir) setTimeout(() => { CER.grafo.centerAt(n.x, n.y, 700); CER.grafo.zoom(1.8, 700); }, 50);
    return;
  }
  if (n.dono) { abrirFicha(n.id); return; }
  if (n.pai) {                                                  // grupo: abre/recolhe os itens dele
    CER.gruposAbertos.has(n.id) ? CER.gruposAbertos.delete(n.id) : CER.gruposAbertos.add(n.id);
    salvarExpansao();
    desenharGrafo();
    if (CER.sel !== n.id) abrirFicha(n.id);
    return;
  }
  if (CER.sel === n.id && CER.abertos.has(n.id)) {              // 2º clique: recolhe as conexões
    CER.abertos.delete(n.id);
    desenharGrafo();
    return;
  }
  CER.abertos.add(n.id);
  desenharGrafo();
  abrirFicha(n.id);
}

function nivel(qual) {
  // Áreas = só os lobos · Grupos = lobos abertos com os grupos (itens recolhidos) · Tudo = tudo aberto
  const ents = CER.dados.entidades;
  CER.expandidas = new Set(qual === "areas" ? [] : ents.map((e) => e.area));
  CER.gruposAbertos = new Set(qual === "tudo" ? [...hierarquia().filhos.keys()] : []);
  CER.abertos = new Set();
  CER.forcados = new Set();
  salvarExpansao();
  desenharGrafo();
  marcarNivel();
  setTimeout(() => enquadrarCerebro(), 300);
}

function nivelAtual() {
  const areas = new Set(CER.dados.entidades.filter((e) => e.nome !== DONO).map((e) => e.area));
  const grupos = [...hierarquia().filhos.keys()];
  if (![...areas].some((a) => CER.expandidas.has(a))) return "areas";
  if ([...areas].every((a) => CER.expandidas.has(a))) {
    if (grupos.length && grupos.every((g) => CER.gruposAbertos.has(g))) return "tudo";
    if (!CER.gruposAbertos.size) return "grupos";
  }
  return "";
}

function marcarNivel() {
  const atual = CER.dados ? nivelAtual() : "areas";
  document.querySelectorAll("#cer-nivel button").forEach((b) => b.classList.toggle("sel", b.dataset.n === atual));
}

function salvarExpansao() {
  try {
    localStorage.setItem("cer.expandidas", JSON.stringify([...CER.expandidas]));
    localStorage.setItem("cer.grupos", JSON.stringify([...CER.gruposAbertos]));
  } catch { /* sem storage */ }
  marcarNivel();
}

function legenda() {
  const ents = CER.dados.entidades;
  $("#cer-legenda").replaceChildren(
    el("span", {}, "🧠 lobo → abre os grupos · grupo (+N) → abre os itens · item → mostra as conexões (de novo recolhe)"),
    el("span", {}, el("i", { class: "leg-rel" }), "ligação"),
    ...(ents.length <= 1 ? [el("span", { class: "leg-dica" }, "Cérebro vazio: converse com o agente ou use ＋ Entidade")] : []));
}

// ── filtros em cards (Todos · Área · Tipo) + linha de ativos ────────────────────────────────────────────
function ativaNoPeriodo(e, p) {
  // teve registro ou observação em algum dia do período? (dias = número do dia UTC)
  if (!p) return true;
  const d0 = Math.floor((p.desde || 0) / 86400), d1 = Math.floor((p.ate || Date.now() / 1000) / 86400);
  return (e.dias || []).some((d) => d >= d0 && d <= d1);
}

function passaFiltro(e, ignorar = null) {
  if (e.nome === DONO) return true;
  const f = CER.filtro;
  if (ignorar !== "areas" && f.areas.size && !f.areas.has(e.area)) return false;
  if (ignorar !== "tipos" && f.tipos.size && !f.tipos.has(e.tipo)) return false;
  if (ignorar !== "periodo" && !ativaNoPeriodo(e, f.periodo)) return false;
  return true;
}

function filtrando() {
  return CER.filtro.areas.size + CER.filtro.tipos.size > 0 || !!CER.filtro.periodo;
}

function noFiltro(nomeEntidade) {
  // registro/observação entra na visão se a entidade dele passa nos filtros (e na busca, se houver)
  const e = CER.dados.entidades.find((x) => x.nome === nomeEntidade);
  if (!e) return !filtrando() && !CER.destaque.size;
  return passaFiltro(e, "periodo") && (!CER.destaque.size || CER.destaque.has(e.id));
}

const PRESETS = [["Tudo", 0], ["Hoje", 1], ["7 dias", 7], ["30 dias", 30], ["90 dias", 90]];

function escolherPeriodo(rotulo, dias, desde = null, ate = null) {
  if (!dias && desde == null) CER.filtro.periodo = null;
  else if (desde != null) CER.filtro.periodo = { rotulo, desde, ate };
  else {
    const ini = new Date(); ini.setHours(0, 0, 0, 0); ini.setDate(ini.getDate() - (dias - 1));
    CER.filtro.periodo = { rotulo, desde: ini.getTime() / 1000, ate: null };
  }
  aplicarFiltros();
}

function alternarFiltro(grupo, valor) {
  // 1º clique com "Todos" ativo: fica SÓ este. Depois: soma/tira. Esvaziou: volta pra Todos.
  const set = CER.filtro[grupo];
  set.has(valor) ? set.delete(valor) : set.add(valor);
  if (grupo === "areas" && set.has(valor)) CER.expandidas.add(valor);          // escolher a área abre o lobo
  aplicarFiltros();
}

function limparFiltros() {
  CER.filtro = { areas: new Set(), tipos: new Set(), periodo: null };
  if ($("#cer-busca").value) { $("#cer-busca").value = ""; limparDestaque(); }
  aplicarFiltros();
}

function aplicarFiltros() {
  montarFiltros();
  desenharGrafo();
  const erro = (x) => aviso(x.message, true);
  if (CER.vista === "lista") renderListaCerebro();
  if (CER.vista === "tempo") carregarTempo().catch(erro);            // as visões só mostram; quem filtra é a barra
  if (CER.vista === "revisar") carregarRevisar().catch(erro);
  if (filtrando() && CER.vista === "grafo") setTimeout(() => enquadrarCerebro(), 250);
}

function fcard({ rotulo, n, cor, sel, onclick, titulo }) {
  return el("button", { type: "button", class: `fcard${sel ? " sel" : ""}${n === 0 ? " zero" : ""}`, style: `--c:${cor}`,
    title: titulo || "", onclick },
    el("b", {}, String(n)), el("span", {}, el("i", { class: "bolinha" }), rotulo));
}

function montarFiltros() {
  // com busca ativa, os contadores contam SÓ o resultado da busca (encontrados + ligados)
  const ents = CER.dados.entidades.filter((e) => e.nome !== DONO && (!CER.destaque.size || CER.destaque.has(e.id)));
  const f = CER.filtro;
  // contagens "inteligentes": cada grupo conta respeitando o filtro do OUTRO grupo
  const porArea = {}, porTipo = {}, corTipo = {};
  for (const e of ents) {
    if (passaFiltro(e, "areas")) porArea[e.area] = (porArea[e.area] || 0) + 1;
    if (passaFiltro(e, "tipos")) { porTipo[e.tipo] = (porTipo[e.tipo] || 0) + 1; corTipo[e.tipo] = corArea(e.area); }
  }
  const total = ents.filter((e) => passaFiltro(e)).length;
  const porPeriodo = PRESETS.map(([rot, dias]) => {
    const ini = new Date(); ini.setHours(0, 0, 0, 0); ini.setDate(ini.getDate() - (dias - 1));
    const p = dias ? { desde: ini.getTime() / 1000, ate: null } : null;
    return [rot, dias, ents.filter((e) => passaFiltro(e, "periodo") && ativaNoPeriodo(e, p)).length];
  });
  const areas = Object.keys(AREA_NOME).filter((a) => a !== "voce" && (porArea[a] || f.areas.has(a)));
  for (const a of Object.keys(porArea)) if (!areas.includes(a)) areas.push(a);
  const tipos = Object.entries(porTipo).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t]) => t);
  for (const t of f.tipos) if (!tipos.includes(t)) tipos.push(t);

  $("#cer-filtros").replaceChildren(
    el("div", { class: "fgrupo" }, el("div", { class: "frotulo" }, "Total"),
      el("div", { class: "fcards" }, fcard({ rotulo: CER.destaque.size ? "Na busca" : "Todos", n: filtrando() ? total : ents.length,
        cor: CER.destaque.size ? "#ffe14d" : "#e6ecff", sel: !filtrando(), onclick: limparFiltros,
        titulo: CER.destaque.size ? "resultado da busca (sem filtro de área/tipo)" : "mostrar tudo" }))),
    el("div", { class: "fgrupo" }, el("div", { class: "frotulo" }, "Área"),
      el("div", { class: "fcards" }, areas.map((a) => fcard({ rotulo: `${EMOJI_AREA[a] || ""} ${nomeArea(a)}`, n: porArea[a] || 0,
        cor: corArea(a), sel: f.areas.has(a), onclick: () => alternarFiltro("areas", a) })))),
    el("div", { class: "fgrupo" }, el("div", { class: "frotulo" }, "Tipo"),
      el("div", { class: "fcards" }, tipos.map((t) => fcard({ rotulo: `${EMOJI_TIPO[t] || "✨"} ${t}`, n: porTipo[t] || 0,
        cor: corTipo[t] || "#7f8db3", sel: f.tipos.has(t), onclick: () => alternarFiltro("tipos", t) })))),
    grupoPeriodo(porPeriodo));

  const busca = $("#cer-busca").value.trim();
  const chips = [
    ...[...f.areas].map((a) => ["Área", nomeArea(a), () => alternarFiltro("areas", a)]),
    ...[...f.tipos].map((t) => ["Tipo", t, () => alternarFiltro("tipos", t)]),
    ...(f.periodo ? [["Período", f.periodo.rotulo, () => escolherPeriodo("Tudo", 0)]] : []),
    ...(busca ? [["Busca", busca, () => { $("#cer-busca").value = ""; limparDestaque(); montarFiltros(); }]] : []),
  ];
  const ativos = $("#cer-ativos");
  ativos.hidden = !chips.length;
  ativos.replaceChildren(el("span", { class: "frotulo" }, "Ativos"),
    ...chips.map(([g, v, tira]) => el("span", { class: "fchip" }, `${g}: ${v}`,
      el("button", { type: "button", class: "fx", "aria-label": `tirar ${g} ${v}`, onclick: tira }, "×"))),
    el("button", { type: "button", class: "flimpar", onclick: limparFiltros }, "limpar tudo"));
}

function grupoPeriodo(porPeriodo) {
  const f = CER.filtro;
  const de = el("input", { type: "datetime-local", "aria-label": "de", class: "inline", value: f.periodo && f.periodo.rotulo.includes("→") && f.periodo.desde ? paraInput(f.periodo.desde) : "" });
  const ate = el("input", { type: "datetime-local", "aria-label": "até", class: "inline", value: f.periodo && f.periodo.rotulo.includes("→") && f.periodo.ate ? paraInput(f.periodo.ate) : "" });
  const ok = el("button", { type: "button", class: "mini neon", onclick: () => {
    if (!de.value && !ate.value) { escolherPeriodo("Tudo", 0); return; }
    const d = de.value ? new Date(de.value).getTime() / 1000 : 0, a = ate.value ? new Date(ate.value).getTime() / 1000 : null;
    escolherPeriodo(`${de.value ? dataHora(d) : "início"} → ${ate.value ? dataHora(a) : "agora"}`, null, d, a);
  } }, "aplicar");
  const atual = f.periodo ? f.periodo.rotulo : "Tudo";
  return el("div", { class: "fgrupo" }, el("div", { class: "frotulo" }, "Período"),
    el("div", { class: "fcards" },
      porPeriodo.map(([rot, dias, n]) => fcard({ rotulo: `🗓 ${rot}`, n, cor: "#22e5ff", sel: atual === rot,
        onclick: () => escolherPeriodo(rot, dias), titulo: "entidades com algo registrado nesse período" })),
      el("div", { class: "fperiodo" }, el("span", {}, "de"), de, el("span", {}, "até"), ate, ok)));
}

// compat: o resto do código chamava montarAreas()
const montarAreas = montarFiltros;

function irPara(id) {
  if (CER.grafo && !CER.grafo.graphData().nodes.some((x) => x.id === id)) {   // estava recolhida: mostra
    CER.forcados.add(id);
    desenharGrafo();
    setTimeout(() => irPara(id), 1400);                         // espera a física assentar o neurônio novo
    return;
  }
  const n = CER.grafo && CER.grafo.graphData().nodes.find((x) => x.id === id);
  if (n && n.x != null) { CER.grafo.centerAt(n.x, n.y, 700); CER.grafo.zoom(2.6, 700); }
}

// ── ficha ───────────────────────────────────────────────────────────────────────────────────────────────
function fecharFicha() {
  CER.sel = null;
  CER.pilha = [];
  focoDe(null);
  if (CER.resultados) { CER.resultados(); return; }       // com busca ativa, fechar volta pros resultados
  fichaVazia();
  if (CER.vista === "lista") marcarNaLista(null);
}

function fichaVazia() {
  $("#cer-ficha").replaceChildren(el("div", { class: "vazio" },
    "Toque num nó do grafo para abrir a ficha: o que ele sabe, o que mudou, as ligações e o que aconteceu."));
}

const SEM_CAT = "observacao";
const chipCat = (c) => el("span", { class: "chip cat" }, c);

async function abrirFicha(id, { semZoom = false, voltando = false } = {}) {
  const f = await api(`/cerebro/entidades/${id}`);
  if (!voltando && CER.sel != null && CER.sel !== id) CER.pilha.push(CER.sel);   // ← Voltar volta pra esta
  CER.sel = id;
  focoDe({ id });
  if (!semZoom && CER.vista === "grafo") irPara(id);
  if (CER.vista === "lista") marcarNaLista(id);
  const e = f.entidade;
  const eDono = e.nome === DONO;
  const cor = corArea(e.area);
  const atuais = f.observacoes.filter((o) => !o.invalido_em);
  const porId = new Map(f.observacoes.map((o) => [o.id, o]));

  // cabeçalho (nome editável, tipo, área)
  const titulo = el("h2", { class: "ficha-nome", style: `--c:${cor}` }, `${emojiDe({ ...e, dono: eDono })} ${e.nome}`);
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
    const cancelar = el("button", { type: "button", class: "mini", onclick: () => abrirFicha(id, { semZoom: true, voltando: true }) }, "cancelar");
    entrada.addEventListener("keydown", (k) => { if (k.key === "Enter") salvar(); if (k.key === "Escape") cancelar.click(); });
    titulo.replaceChildren(entrada, ok, cancelar);
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

  const anterior = CER.pilha.length ? CER.dados.entidades.find((x) => x.id === CER.pilha[CER.pilha.length - 1]) : null;
  const nav = el("div", { class: "ficha-nav" },
    anterior ? el("button", { type: "button", class: "mini", title: `voltar para ${anterior.nome}`,
      onclick: () => abrirFicha(CER.pilha.pop(), { voltando: true }) }, `← ${anterior.nome}`)
      : CER.resultados ? el("button", { type: "button", class: "mini", onclick: () => { CER.sel = null; CER.resultados(); } }, "← resultados")
      : el("span", {}),
    el("button", { type: "button", class: "mini", title: "fechar a ficha", onclick: fecharFicha }, "✕ fechar"));
  const cab = el("div", { class: "ficha-cab" }, nav,
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
      const sel = el("select", { class: "inline", "aria-label": "métrica" }, f.metricas.map((m) => el("option", { value: m, selected: m === (f.metricas.includes("carga_kg") ? "carga_kg" : f.metricas[0]) }, nomeMedida(m))));
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
      try { await api(`/cerebro/entidades/${id}`, { method: "DELETE" }); aviso(`“${e.nome}” apagado`); CER.pilha = CER.pilha.filter((x) => x !== id); fecharFicha(); await cerCarregar(); }
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
  const cat = el("input", { type: "text", list: listaId, placeholder: "assunto (ex.: execução)", class: "inline",
    "aria-label": "assunto da observação", title: "rótulo do assunto: execução, saúde, preferência, meta…" });
  const txt = el("input", { type: "text", placeholder: "adicionar algo que ele deve saber…", "aria-label": "texto" });
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
      Object.keys(r.dados || {}).length ? el("span", { class: "reg-dados" }, ` · ${fmtDados(r.dados, r.texto)}`) : null,
      textoLivre(r) ? el("span", { class: "meta" }, ` · “${textoLivre(r)}”`) : null),
    el("button", { type: "button", class: "mini", title: "invalidar (fica no histórico)", onclick: async () => {
      if (!confirm("Invalidar este registro?")) return;
      await api(`/cerebro/registros/${r.id}/invalidar`, { method: "POST" }); aviso("Registro invalidado");
      await cerCarregar(); if (CER.vista === "tempo") await carregarTempo();
    } }, "⊘"));
}

const NOME_MEDIDA = {
  carga_kg: "Carga (kg)", peso_kg: "Peso (kg)", reps: "Repetições", series: "Séries", duracao_min: "Duração (min)",
  duracao_s: "Duração (s)", distancia_km: "Distância (km)", valor_rs: "Valor (R$)", acertos: "Acertos",
};
const nomeMedida = (m) => NOME_MEDIDA[m] || m.replace(/_/g, " ");

function fmtDados(d, texto = "") {
  // por extenso, igual ao que o agente fala: "4 séries de 6 repetições com 16 kg cada lado"
  const r = { ...d };
  let frase = "";
  if (r.series != null && r.reps != null) frase = `${r.series} séries de ${r.reps} repetições`;
  else if (r.reps != null) frase = `${r.reps} repetições`;
  else if (r.series != null && r.duracao_s != null) { frase = `${r.series} séries de ${r.duracao_s} s`; delete r.duracao_s; }
  else if (r.series != null) frase = `${r.series} séries`;
  delete r.series; delete r.reps;
  const carga = r.carga_kg ?? r.peso_kg;
  delete r.carga_kg; delete r.peso_kg;
  if (carga != null) frase = `${frase ? `${frase} com ` : ""}${carga} kg${texto && texto.startsWith("cada lado") ? ` ${texto}` : ""}`;
  const p = frase ? [frase] : [];
  for (const [k, u] of [["duracao_min", "min"], ["distancia_km", "km"]]) if (r[k] != null) { p.push(`${r[k]} ${u}`); delete r[k]; }
  for (const [k, v] of Object.entries(r)) p.push(`${k}: ${v}`);
  return p.join(" · ");
}

const textoLivre = (r) => (r.texto && !(Object.keys(r.dados || {}).length && r.texto.startsWith("cada lado")) ? r.texto : "");

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

// ── lista (alternativa ao grafo): área → grupo → itens ──────────────────────────────────────────────────
function resumoUltimo(u) {
  if (!u) return "";
  const q = new Date(u.quando * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  const d = Object.keys(u.dados || {}).length ? fmtDados(u.dados, u.texto) : (u.texto || u.tipo);
  return `${q} · ${d}`;
}

function itemLista(e, filho = false) {
  return el("button", { type: "button", class: `li-item${filho ? " filho" : ""}${CER.sel === e.id ? " sel" : ""}`, "data-id": e.id,
    onclick: () => abrirFicha(e.id) },
    el("div", { class: "li-linha" },
      el("span", { class: "li-nome" }, `${emojiDe({ ...e, dono: e.nome === DONO })} ${e.nome}`),
      el("span", { class: "li-num" }, [e.n_obs ? `${e.n_obs} obs` : "", e.n_reg ? `${e.n_reg} reg` : ""].filter(Boolean).join(" · "))),
    e.ultimo ? el("div", { class: "li-ultimo" }, resumoUltimo(e.ultimo)) : null);
}

function renderListaCerebro() {
  const d = CER.dados;
  const q = norm($("#cer-busca").value || "");
  const ents = d.entidades.filter((e) => passaFiltro(e))
    .filter((e) => !q || norm(e.nome).includes(q));
  const porId = new Map(d.entidades.map((e) => [e.id, e]));
  // "pai" = alvo de uma ligação vinda de outra entidade da MESMA área (ex.: Supino —grupo→ Peito)
  const filhosDe = new Map();
  const ehFilho = new Set();
  for (const r of d.relacoes) {
    const a = porId.get(r.de), b = porId.get(r.para);
    if (!a || !b || a.area !== b.area || a.nome === DONO || b.nome === DONO) continue;
    (filhosDe.get(b.id) || filhosDe.set(b.id, []).get(b.id)).push(a);
    ehFilho.add(a.id);
  }
  const areas = new Map();
  for (const e of ents) (areas.get(e.area) || areas.set(e.area, []).get(e.area)).push(e);
  const ordem = ["voce", "academia", "estudos", "trabalho", "pessoas", "financas", "geral"];
  const cards = [...areas.entries()].sort((a, b) => (ordem.indexOf(a[0]) + 99) % 99 - (ordem.indexOf(b[0]) + 99) % 99).map(([area, lista]) => {
    const cor = corArea(area);
    const corpo = [];
    const ids = new Set(lista.map((e) => e.id));
    const pais = lista.filter((e) => filhosDe.has(e.id)).sort((a, b) => a.nome.localeCompare(b.nome));
    for (const p of pais) {
      const filhos = (filhosDe.get(p.id) || []).filter((f) => ids.has(f.id)).sort((a, b) => a.nome.localeCompare(b.nome));
      corpo.push(el("div", { class: "li-grupo" }, itemLista(p), ...filhos.map((f) => itemLista(f, true))));
    }
    const soltos = lista.filter((e) => !filhosDe.has(e.id) && !(ehFilho.has(e.id) && [...filhosDe.entries()].some(([pid, fs]) => ids.has(pid) && fs.some((f) => f.id === e.id))));
    const porTipo = new Map();
    for (const e of soltos) (porTipo.get(e.tipo) || porTipo.set(e.tipo, []).get(e.tipo)).push(e);
    for (const [tipo, itens] of [...porTipo.entries()].sort()) {
      corpo.push(el("div", { class: "li-grupo" }, el("div", { class: "li-tipo" }, tipo),
        ...itens.sort((a, b) => a.nome.localeCompare(b.nome)).map((e) => itemLista(e))));
    }
    return el("div", { class: "card li-area", style: `--c:${cor}` },
      el("h3", {}, el("i", { class: "bolinha" }), ` ${nomeArea(area)}`, el("span", { class: "li-conta" }, ` ${lista.length}`)), ...corpo);
  });
  $("#cer-painel-lista").replaceChildren(...(cards.length ? cards : [el("div", { class: "vazio" }, "Nada aqui (filtro/busca).")]));
}

function marcarNaLista(id) {
  document.querySelectorAll("#cer-painel-lista .li-item").forEach((b) => b.classList.toggle("sel", Number(b.dataset.id) === id));
}

function norm(t) {
  return (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

// ── busca ───────────────────────────────────────────────────────────────────────────────────────────────
let buscaTimer;
async function buscar(q) {
  // acha por NOME, TIPO, ÁREA ("academia") e pelo que ele SABE; inclui o que está LIGADO a cada achado.
  // Tudo que aparece fica aceso no cérebro (e a região do lobo brilha), o resto apaga.
  const alvo = norm(q);
  if (!alvo) { limparDestaque(); return; }
  const d = CER.dados;
  const porId = new Map(d.entidades.map((e) => [e.id, e]));
  const achados = new Map();                                   // id → motivo
  for (const e of d.entidades) {
    if (e.nome === DONO) continue;
    if (norm(e.nome).includes(alvo)) achados.set(e.id, "nome");
    else if (norm(nomeArea(e.area)).includes(alvo) || norm(e.area) === alvo) achados.set(e.id, `área ${nomeArea(e.area)}`);
    else if (norm(e.tipo).includes(alvo)) achados.set(e.id, `tipo ${e.tipo}`);
  }
  let obs = [];
  try {
    const r = await api(`/cerebro/busca?q=${encodeURIComponent(q)}`);
    obs = r.observacoes || [];
    for (const o of obs) if (porId.has(o.entidade_id) && porId.get(o.entidade_id).nome !== DONO && !achados.has(o.entidade_id)) achados.set(o.entidade_id, `“${o.texto}”`);
  } catch { /* busca textual opcional */ }
  const ligados = new Map();                                   // 1 salto pelas ligações
  for (const r of d.relacoes) {
    if (achados.has(r.de) && !achados.has(r.para) && porId.get(r.para)?.nome !== DONO) ligados.set(r.para, `${porId.get(r.de).nome} —${r.tipo}→`);
    if (achados.has(r.para) && !achados.has(r.de) && porId.get(r.de)?.nome !== DONO) ligados.set(r.de, `—${r.tipo}→ ${porId.get(r.para).nome}`);
  }
  CER.destaque = new Set([...achados.keys(), ...ligados.keys()]);
  CER.forcados = new Set([...CER.forcados, ...CER.destaque]);
  desenharGrafo();
  setTimeout(() => enquadrarCerebro(), 250);                   // o cérebro inteiro: ver EM QUE REGIÃO está o assunto

  const item = (id, motivo) => {
    const e = porId.get(id);
    return el("button", { type: "button", class: "res", onclick: () => { CER.daBusca = true; abrirFicha(id); } },
      el("i", { class: "bolinha", style: `--c:${corArea(e.area)}` }), " ", el("b", {}, e.nome),
      el("span", { class: "meta" }, ` · ${e.tipo} · ${motivo}`));
  };
  const porArea = {};
  for (const id of CER.destaque) { const a = porId.get(id).area; porArea[a] = (porArea[a] || 0) + 1; }
  // os resultados vão pro painel da direita: o cérebro fica livre pra mostrar as regiões acesas
  CER.resultados = () => $("#cer-ficha").replaceChildren(
    el("h3", {}, `Busca: “${q}”`),
    el("div", { class: "res-cab" },
      el("span", {}, CER.destaque.size ? `${achados.size} encontrado(s) + ${ligados.size} ligado(s) · ` : "nada encontrado"),
      ...Object.entries(porArea).map(([a, n]) => el("span", { class: "chip", style: `color:${corArea(a)}` }, `${nomeArea(a)} ${n}`)),
      el("button", { type: "button", class: "mini", onclick: () => { $("#cer-busca").value = ""; limparDestaque(); } }, "✕ limpar")),
    ...(achados.size ? [el("div", { class: "res-sec" }, "Encontrado"), ...[...achados].map(([id, m]) => item(id, m))] : []),
    ...(ligados.size ? [el("div", { class: "res-sec" }, "Ligado a isso"), ...[...ligados].map(([id, m]) => item(id, m))] : []));
  CER.sel = null;
  CER.pilha = [];
  CER.resultados();
  $("#cer-ficha").scrollTop = 0;
  montarFiltros();                                             // contadores passam a contar o resultado
}

function limparDestaque() {
  CER.destaque = new Set();
  CER.forcados = new Set();
  CER.resultados = null;
  CER.daBusca = false;
  $("#cer-resultados").hidden = true;
  if (CER.sel == null) fichaVazia();
  montarFiltros();
  desenharGrafo();
}

// ── linha do tempo ──────────────────────────────────────────────────────────────────────────────────────
async function carregarTempo() {
  // só MOSTRA: o que entra é decidido pela barra de filtros (área, tipo, período, busca)
  const p = CER.filtro.periodo;
  const q = new URLSearchParams();
  if (p?.desde) q.set("desde", String(p.desde));
  if (p?.ate) q.set("ate", String(p.ate));
  const { registros: todos } = await api(`/cerebro/registros?${q}`);
  const registros = todos.filter((r) => noFiltro(r.entidade));

  const metricas = [...new Set(registros.flatMap((r) => Object.entries(r.dados || {}).filter(([, v]) => typeof v === "number").map(([k]) => k)))].sort();
  const mAtual = $("#lt-metrica").value;
  $("#lt-metrica").replaceChildren(el("option", { value: "" }, "—"), ...metricas.map((m) => el("option", { value: m, selected: m === mAtual }, nomeMedida(m))));
  const m = $("#lt-metrica").value;
  $("#lt-grafico-titulo").textContent = m ? `Evolução: ${nomeMedida(m)}` : `${registros.length} registro(s) — escolha uma medida pro gráfico`;
  $("#lt-grafico").replaceChildren(m ? grafico(registros, m) : "");

  const dias = new Map();
  for (const r of registros) {
    const d = new Date(r.quando * 1000).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
    (dias.get(d) || dias.set(d, []).get(d)).push(r);
  }
  $("#lt-lista").replaceChildren(...(registros.length ? [...dias.entries()].map(([d, lista]) =>
    el("div", { class: "card lt-dia" }, el("h3", {}, d), ...lista.map((r) => itemReg(r, false))))
    : [el("div", { class: "vazio" }, "Nenhum registro nos filtros/período escolhidos.")]));
}

// ── revisar ─────────────────────────────────────────────────────────────────────────────────────────────
async function carregarRevisar() {
  const p = CER.filtro.periodo;
  const r = await api(`/cerebro/revisar?desde=${p?.desde || 0}`);
  const ate = p?.ate || Infinity;
  r.observacoes = r.observacoes.filter((o) => noFiltro(o.entidade) && o.valido_desde <= ate);
  r.registros = r.registros.filter((x) => noFiltro(x.entidade) && x.quando <= ate);
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
  const comFicha = v === "grafo" || v === "lista";              // grafo e lista dividem a mesma ficha
  montarFiltros();
  $("#cer-v-grafo").hidden = !comFicha;
  $("#cer-v-tempo").hidden = v !== "tempo";
  $("#cer-v-revisar").hidden = v !== "revisar";
  $("#cer-painel-grafo").hidden = v !== "grafo";
  $("#cer-painel-lista").hidden = v !== "lista";
  for (const b of ["#cer-rotulos", "#cer-centro", "#cer-nivel"]) $(b).hidden = v !== "grafo";
  if (v === "lista") renderListaCerebro();
  const erro = (x) => aviso(x.message, true);
  if (v === "tempo") carregarTempo().catch(erro);
  if (v === "revisar") carregarRevisar().catch(erro);
  if (v === "grafo" && CER.grafo) setTimeout(() => CER.grafo.width($("#cer-grafo").clientWidth).height($("#cer-grafo").clientHeight), 0);
}

function ligarEventos() {
  $("#cer-vistas").addEventListener("click", (e) => { if (e.target.dataset?.v) trocarVista(e.target.dataset.v); });
  $("#cer-nova").addEventListener("click", novaEntidade);
  $("#cer-centro").addEventListener("click", () => CER.grafo && enquadrarCerebro());
  $("#cer-nivel").addEventListener("click", (e) => { if (e.target.dataset?.n) nivel(e.target.dataset.n); });
  $("#cer-rotulos").addEventListener("click", () => { CER.rotulos = !CER.rotulos; $("#cer-rotulos").classList.toggle("sel", CER.rotulos); });
  $("#cer-busca").addEventListener("input", (e) => {
    clearTimeout(buscaTimer);
    setTimeout(montarFiltros, 0);                                // a busca vira um chip em "Ativos"
    if (CER.vista === "lista") { renderListaCerebro(); return; }          // na lista, a busca filtra os itens
    buscaTimer = setTimeout(() => buscar(e.target.value).catch(() => {}), 250);
  });
  $("#cer-busca").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.target.value = ""; limparDestaque(); } });
  $("#lt-metrica").addEventListener("change", () => carregarTempo().catch((x) => aviso(x.message, true)));
}

window.cerebroAbrir = async () => {
  if (!CER.iniciado) { CER.iniciado = true; ligarEventos(); }
  if (CER.dados === null && !CER.rotulosDecidido) {      // poucos nós: nomes sempre visíveis
    CER.rotulosDecidido = true;
    const d = await api("/cerebro").catch(() => null);
    CER.rotulos = !!d && d.entidades.length <= 40;
    $("#cer-rotulos").classList.toggle("sel", CER.rotulos);
    try {
      CER.expandidas = new Set(JSON.parse(localStorage.getItem("cer.expandidas") || "[]"));
      CER.gruposAbertos = new Set(JSON.parse(localStorage.getItem("cer.grupos") || "[]"));
    } catch { /* sem storage */ }
  }
  try { await cerCarregar(); } catch (x) { aviso(`Cérebro: ${x.message}`, true); }
  trocarVista(CER.vista);
};
window.cerebroRecarregar = async () => {
  await cerCarregar();
  if (CER.vista === "tempo") await carregarTempo();
  if (CER.vista === "revisar") await carregarRevisar();
};
