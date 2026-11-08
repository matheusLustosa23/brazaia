// Painel do agente — JS puro, sem build. Dados via /api/v1/painel/* (cookie de sessão do painel).
// Abas: Devices (lista + console de ferramentas do device escolhido) · Mapa (trilha, intervalo, camadas) · Cérebro (P3).
"use strict";

const API = "/api/v1/painel";
const ATUALIZA_MS = 10_000;

const estado = {
  devices: [],
  sel: null,                 // id do device aberto no console
  consoleOnline: null,       // online do device quando o console foi montado (remonta só se mudar)
  filtro: { device: "", horas: 24, desde: null, ate: null },
};

// ── util ────────────────────────────────────────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined && f !== false) n.append(f);
  return n;
}

function relativo(epoch) {
  if (!epoch) return "nunca";
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 60) return "agora";
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `há ${h} h`;
  const d = Math.floor(h / 24);
  return d === 1 ? "ontem" : `há ${d} dias`;
}

function dataHora(epoch) {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function paraInput(epoch) {               // epoch → valor de <input type="datetime-local"> (hora local)
  const d = new Date(epoch * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

let avisoTimer;
function aviso(texto, erro = false) {
  const a = $("#aviso");
  a.textContent = texto;
  a.className = "aviso" + (erro ? " erro" : "");
  a.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => (a.hidden = true), 3800);
}

async function api(caminho, opcoes = {}) {
  const corpoForm = opcoes.body instanceof FormData;
  const r = await fetch(API + caminho, {
    credentials: "same-origin",
    headers: corpoForm ? {} : { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (r.status === 401) { location.reload(); throw new Error("não autorizado"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || j.detail || `${r.status} ${r.statusText}`);
  return j;
}

async function copiar(texto) {
  // clipboard API só existe em HTTPS/localhost; o painel roda em http pela tailnet → fallback com textarea
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(texto); return true; }
  } catch { /* cai no fallback */ }
  const t = el("textarea", { style: "position:fixed;opacity:0;left:-9999px" });
  t.value = texto;
  document.body.append(t);
  t.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  t.remove();
  return ok;
}

function abrirModal(conteudo) {
  $("#modal-conteudo").replaceChildren(conteudo);
  $("#modal").hidden = false;
}
$("#modal-fechar").addEventListener("click", () => ($("#modal").hidden = true));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });

function comCarga(botao, texto, fn) {
  return async () => {
    const antes = botao.textContent;
    botao.disabled = true;
    botao.textContent = texto;
    try { await fn(); } catch (e) { aviso(`Erro: ${e.message}`, true); }
    finally { botao.disabled = false; botao.textContent = antes; }
  };
}

const dev = (id) => estado.devices.find((d) => d.id === id);
const temTool = (d, t) => d.conectado && (d.tools || []).includes(t);

// ── links de localização (pra abrir em outros apps) ─────────────────────────────────────────────────────
function linksLocal(lat, lon) {
  const a = lat.toFixed(6), o = lon.toFixed(6);
  return [
    { nome: "Google Maps", url: `https://www.google.com/maps/search/?api=1&query=${a},${o}` },
    { nome: "Waze", url: `https://waze.com/ul?ll=${a},${o}&navigate=yes` },
    { nome: "Uber", url: `https://m.uber.com/ul/?action=setPickup&pickup=my_location&dropoff[latitude]=${a}&dropoff[longitude]=${o}` },
    { nome: "OpenStreetMap", url: `https://www.openstreetmap.org/?mlat=${a}&mlon=${o}#map=17/${a}/${o}` },
  ];
}

function blocoCompartilhar(nome, p) {
  if (!p) return el("p", { class: "meta" }, "Sem posição guardada.");
  const links = linksLocal(p.lat, p.lon);
  const coords = `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;
  const itens = links.map((l) => el("span", { class: "par" },
    el("a", { class: "btn", href: l.url, target: "_blank", rel: "noopener", title: `abrir no ${l.nome}` }, l.nome),
    el("button", { type: "button", class: "copia", title: `copiar link do ${l.nome}`, "aria-label": `copiar link do ${l.nome}`,
      onclick: async () => aviso(await copiar(l.url) ? `Link do ${l.nome} copiado` : "Não deu pra copiar", false) }, "⧉")));
  itens.push(el("button", { type: "button", title: "copiar latitude, longitude",
    onclick: async () => aviso(await copiar(coords) ? "Coordenadas copiadas" : "Não deu pra copiar") }, "⧉ coordenadas"));
  if (navigator.share) {
    itens.push(el("button", { type: "button", class: "rosa",
      onclick: () => navigator.share({ title: `Posição de ${nome}`, text: `${nome}: ${coords}`, url: links[0].url }).catch(() => {}) },
      "Compartilhar…"));
  }
  return el("div", {},
    el("p", { class: "meta" }, `${nome} · ${coords} · ${relativo(p.quando)} (${dataHora(p.quando)})` +
      (p.precisao_m ? ` · ±${Math.round(p.precisao_m)} m` : "")),
    el("div", { class: "links-share" }, itens));
}

// ── devices: lista ──────────────────────────────────────────────────────────────────────────────────────
function barraBateria(e) {
  if (typeof e?.bateria !== "number") return null;
  const cls = e.bateria < 20 ? "baixa" : e.bateria < 50 ? "media" : "";
  return el("div", { class: "bat" },
    el("div", { class: `bat-barra ${cls}` }, el("i", { style: `width:${Math.max(3, e.bateria)}%` })),
    `${e.bateria}%${e.carregando ? " ⚡" : ""}`);
}

function textoEstado(d) {
  return d.conectado
    ? el("div", { class: "estado" }, el("b", {}, "Conectado"), ` ${relativo(d.conectado_desde)}`)
    : el("div", { class: "estado" }, el("b", {}, "Offline"), ` · visto ${relativo(d.ultima_vez)}`);
}

function cartaoLista(d) {
  return el("button", {
    type: "button",
    class: `device ${d.conectado ? "online" : "offline"} ${estado.sel === d.id ? "sel" : ""}`,
    onclick: () => selecionar(d.id),
  },
    el("div", { class: "linha1" },
      el("span", { class: "ponto", "aria-hidden": "true" }),
      el("div", {}, el("div", { class: "nome" }, d.nome || d.id), el("div", { class: "id" }, d.id)),
      d.plataforma ? el("span", { class: "plataforma" }, d.plataforma) : null),
    textoEstado(d),
    barraBateria(d.estado),
    d.localizacao ? el("div", { class: "estado" }, `📍 ${relativo(d.localizacao.quando)}` +
      (d.localizacao.precisao_m ? ` · ±${Math.round(d.localizacao.precisao_m)} m` : "")) : null,
  );
}

function renderLista() {
  const lista = $("#lista-devices");
  lista.replaceChildren(...(estado.devices.length
    ? estado.devices.map(cartaoLista)
    : [el("div", { class: "vazio" }, "Nenhum device registrado.")]));
  const on = estado.devices.filter((d) => d.conectado).length;
  $("#resumo-devices").textContent = `${on} conectado(s) de ${estado.devices.length}`;
}

function selecionar(id) {
  estado.sel = id;
  estado.consoleOnline = null;
  renderLista();
  renderConsole();
  if (window.innerWidth < 860) $("#console").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── devices: console de ferramentas ─────────────────────────────────────────────────────────────────────
const NOME_PERM = {
  camera: "câmera", microfone: "microfone", localizacao: "localização", localizacao_fundo: "localização 2º plano",
  arquivos: "arquivos", notificacao: "notificação", bateria: "sem economia", navegador: "navegador",
};

function chipPermissao(nome, valor) {
  const classe = valor === "ok" ? "ok" : valor === "manual" ? "manual" : valor === "n/a" ? "na" : "negada";
  const icone = { ok: "✓", manual: "✋", na: "—", negada: "✗" }[classe];
  return el("span", { class: `chip ${classe}`, title: `${NOME_PERM[nome] || nome}: ${valor}` }, `${icone} ${NOME_PERM[nome] || nome}`);
}

function cardNotificar(d) {
  const titulo = el("input", { type: "text", value: "Painel", maxlength: "80", "aria-label": "Título" });
  const msg = el("textarea", { maxlength: "500", placeholder: "Mensagem…", "aria-label": "Mensagem" });
  const b = el("button", { type: "button", class: "neon" }, "Enviar notificação");
  b.disabled = !temTool(d, "notify");
  b.addEventListener("click", comCarga(b, "Enviando…", async () => {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/notificar`, {
      method: "POST", body: JSON.stringify({ title: titulo.value || "Painel", message: msg.value || " " }),
    });
    aviso(r.ok ? `Notificação enviada pra ${d.nome}` : `Falhou: ${r.resultado}`, !r.ok);
    if (r.ok) msg.value = "";
  }));
  return el("div", { class: "card" }, el("h3", {}, "Notificar"),
    el("label", { class: "campo" }, "Título", titulo),
    el("label", { class: "campo", style: "margin-top:.5rem" }, "Mensagem", msg),
    el("div", { class: "linha-form" }, b));
}

function cardCamera(d) {
  const sel = el("select", { "aria-label": "Câmera" },
    d.plataforma === "termux"
      ? [el("option", { value: "back" }, "Traseira"), el("option", { value: "front" }, "Frontal")]
      : [el("option", { value: "" }, "Padrão")]);
  const saida = el("div", {});
  const b = el("button", { type: "button", class: "neon" }, "Capturar");
  b.disabled = !temTool(d, "capture_image");
  b.addEventListener("click", comCarga(b, "Capturando…", async () => {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/capturar`, {
      method: "POST", body: JSON.stringify({ camera: sel.value || null }),
    });
    if (!r.ok) { aviso(`Não capturou: ${r.motivo}`, true); return; }
    const ampliar = () => abrirModal(el("img", { src: r.imagem, alt: `foto de ${d.nome}` }));
    const nome = `${d.id}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.jpg`;
    saida.replaceChildren(
      el("img", { class: "preview", src: r.imagem, alt: `foto de ${d.nome}`, onclick: ampliar }),
      el("div", { class: "linha-form" },
        el("button", { type: "button", onclick: ampliar }, "Ampliar"),
        el("a", { class: "btn", href: r.imagem, download: nome }, "Baixar"),
        el("button", { type: "button", class: "rosa", onclick: () => saida.replaceChildren() }, "Remover")));
  }));
  return el("div", { class: "card" }, el("h3", {}, "Câmera"),
    el("div", { class: "linha-form" }, sel, b), saida);
}

function cardAudio(d) {
  // gravar o microfone do device: por N segundos, ou iniciar/parar (sem tempo, até 30 min)
  const pode = temTool(d, "record_audio");
  const seg = el("input", { type: "number", min: "1", max: "300", value: "10", "aria-label": "segundos", class: "seg" });
  const saida = el("div", {});
  const estadoTxt = el("p", { class: "sub" });
  const mostrar = (r) => {
    const player = el("audio", { controls: true, src: r.audio, preload: "auto" });
    saida.replaceChildren(
      el("p", { class: "sub" }, `${r.segundos} s · ${r.kb} KB · id ${r.file_id}`), player,
      el("div", { class: "linha-form" },
        el("a", { class: "btn", href: r.audio, download: r.nome }, "Baixar"),
        el("button", { type: "button", class: "rosa", onclick: () => saida.replaceChildren() }, "Remover")));
  };
  const chamar = (corpo) => api(`/devices/${encodeURIComponent(d.id)}/gravar`, { method: "POST", body: JSON.stringify(corpo) });
  const bGravar = el("button", { type: "button", class: "neon" }, "Gravar");
  const bIniciar = el("button", { type: "button" }, "● Iniciar");
  const bParar = el("button", { type: "button", class: "rosa" }, "■ Parar");
  for (const b of [bGravar, bIniciar, bParar]) b.disabled = !pode;
  bGravar.addEventListener("click", comCarga(bGravar, "Gravando…", async () => {
    const r = await chamar({ acao: "gravar", segundos: Number(seg.value) || 10 });
    if (!r.ok) { aviso(`Não gravou: ${r.motivo}`, true); return; }
    mostrar(r);
  }));
  bIniciar.addEventListener("click", comCarga(bIniciar, "Iniciando…", async () => {
    const r = await chamar({ acao: "iniciar" });
    if (!r.ok) { aviso(`Não iniciou: ${r.motivo}`, true); return; }
    estadoTxt.textContent = r.texto.replace(/^\[ok\] /, "");
  }));
  bParar.addEventListener("click", comCarga(bParar, "Parando…", async () => {
    const r = await chamar({ acao: "parar" });
    if (!r.ok) { aviso(`Não parou: ${r.motivo}`, true); return; }
    estadoTxt.textContent = "";
    mostrar(r);
  }));
  if (pode && d.conectado) {                          // já havia uma gravação rodando? mostra
    chamar({ acao: "status" }).then((r) => { if (r.ok && r.texto && !r.texto.includes("nenhuma")) estadoTxt.textContent = r.texto.replace(/^\[ok\] /, ""); }).catch(() => {});
  }
  return el("div", { class: "card" }, el("h3", {}, "Áudio"),
    d.conectado && !pode ? el("p", { class: "sub" }, "Este device ainda não grava áudio (só o celular, por enquanto).") : null,
    el("div", { class: "linha-form" }, el("label", { class: "campo" }, "Segundos", seg), bGravar),
    el("div", { class: "linha-form" }, bIniciar, bParar), estadoTxt, saida);
}

function cardAbrir(d) {
  let arquivo = null;
  const entrada = el("input", { type: "file", accept: ".html,.htm,image/*", hidden: true });
  const drop = el("div", { class: "drop", tabindex: "0", role: "button" }, "Arraste um HTML ou imagem aqui (ou toque para escolher)");
  const b = el("button", { type: "button", class: "neon" }, `Abrir no ${d.nome || d.id}`);
  b.disabled = true;
  const pode = temTool(d, "display_page") || temTool(d, "open_image");

  const escolher = (f) => {
    if (!f) return;
    if (!/\.(html?|png|jpe?g|webp|gif)$/i.test(f.name) && !f.type.startsWith("image/")) {
      aviso("Só HTML ou imagem (png, jpg, webp, gif)", true); return;
    }
    arquivo = f;
    drop.classList.add("cheio");
    drop.textContent = `${f.name} · ${Math.ceil(f.size / 1024)} KB`;
    b.disabled = !pode;
  };
  drop.addEventListener("click", () => entrada.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") entrada.click(); });
  entrada.addEventListener("change", () => escolher(entrada.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("sobre"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("sobre"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("sobre"); escolher(e.dataTransfer.files[0]); });
  b.addEventListener("click", comCarga(b, "Abrindo…", async () => {
    const fd = new FormData();
    fd.append("arquivo", arquivo);
    const r = await api(`/devices/${encodeURIComponent(d.id)}/abrir`, { method: "POST", body: fd });
    aviso(r.ok ? `${arquivo.name} aberto no ${d.nome}` : `Falhou: ${r.resultado}`, !r.ok);
  }));
  return el("div", { class: "card" }, el("h3", {}, "Abrir no device"),
    el("p", { class: "meta" }, "HTML abre no navegador dele; imagem no visualizador."),
    drop, entrada, el("div", { class: "linha-form" }, b));
}

let miniMapa = null;

function desenharMini(caixa, p) {
  if (miniMapa) { miniMapa.remove(); miniMapa = null; }
  if (!p || typeof L === "undefined") { caixa.hidden = true; return; }
  caixa.hidden = false;
  miniMapa = L.map(caixa, { zoomControl: true, attributionControl: false }).setView([p.lat, p.lon], 15);
  const [url, , cls] = CAMADAS[$("#f-camada").value] || CAMADAS.escuro;
  L.tileLayer(url, { maxZoom: 19, className: cls || "" }).addTo(miniMapa);
  if (p.precisao_m && p.precisao_m <= 1000) {
    L.circle([p.lat, p.lon], { radius: p.precisao_m, color: "#22e5ff", weight: 1, fillOpacity: 0.08 }).addTo(miniMapa);
  }
  L.circleMarker([p.lat, p.lon], { radius: 8, color: "#22e5ff", weight: 2, fillColor: "#22e5ff", fillOpacity: 0.9 }).addTo(miniMapa);
  setTimeout(() => miniMapa && miniMapa.invalidateSize(), 50);
}

function cardLocal(d) {
  const mini = el("div", { class: "mini-mapa", "aria-label": `mapa de ${d.nome}` });
  setTimeout(() => desenharMini(mini, d.localizacao), 0);       // precisa estar no DOM antes do Leaflet
  const corpo = el("div", {}, blocoCompartilhar(d.nome || d.id, d.localizacao));
  const b = el("button", { type: "button", class: "neon" }, "Localizar agora");
  b.disabled = !temTool(d, "get_location");
  b.addEventListener("click", comCarga(b, "Localizando…", async () => {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/localizar`, { method: "POST" });
    if (!r.ok) { aviso(`${d.nome}: não leu — ${r.motivo}`, true); return; }
    aviso(`${d.nome}: posição atualizada` + (r.ponto.precisao_m ? ` (±${Math.round(r.ponto.precisao_m)} m)` : ""));
    corpo.replaceChildren(blocoCompartilhar(d.nome || d.id, r.ponto));
    desenharMini(mini, r.ponto);
    await carregarDevices();
  }));
  const verMapa = el("button", { type: "button", onclick: () => { estado.filtro.device = d.id; location.hash = "#mapa"; } }, "Ver trilha no mapa");
  return el("div", { class: "card card-local" },
    el("h3", {}, "Localização"),
    el("div", { class: "local-grade" }, mini,
      el("div", { class: "local-info" }, corpo, el("div", { class: "linha-form" }, b, verMapa))));
}

function cardEstado(d) {
  const corpo = el("div", {}, barraBateria(d.estado) || el("p", { class: "meta" }, "Sem bateria (desktop) ou ainda não lida."));
  const b = el("button", { type: "button" }, "Atualizar bateria");
  b.disabled = !temTool(d, "get_estado");
  b.addEventListener("click", comCarga(b, "Lendo…", async () => {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/estado`, { method: "POST" });
    if (!r.ok) { aviso(`Não leu: ${r.motivo}`, true); return; }
    corpo.replaceChildren(barraBateria(r.estado) || el("p", { class: "meta" }, "Sem bateria."));
    await carregarDevices();
  }));
  const perms = Object.entries(d.permissoes || {});
  return el("div", { class: "card card-estado" }, el("h3", {}, "Estado e permissões"),
    corpo, el("div", { class: "linha-form" }, b),
    el("p", { class: "meta", style: "margin-top:.8rem" }, "Permissões (setup)"),
    perms.length ? el("div", { class: "chips" }, perms.map(([k, v]) => chipPermissao(k, v)))
      : el("p", { class: "meta" }, "não verificadas — python -m companion permissoes"),
    el("p", { class: "meta", style: "margin-top:.8rem" }, "Ferramentas que ele executa"),
    el("div", { class: "chips" }, (d.tools || []).map((t) => el("span", { class: "chip" }, t))),
    el("p", { class: "meta", style: "margin-top:.8rem" },
      `último sinal ${dataHora(d.ultima_vez)} · registrado ${dataHora(d.registrado_em)}`));
}

function renderConsole() {
  const c = $("#console");
  const d = dev(estado.sel);
  if (!d) {
    c.replaceChildren(el("div", { class: "vazio" }, "Escolha um device à esquerda para usar as ferramentas dele."));
    return;
  }
  estado.consoleOnline = d.conectado;
  c.replaceChildren(
    el("div", { class: "titulo-console" },
      el("h2", {}, d.nome || d.id), d.plataforma ? el("span", { class: "plataforma" }, d.plataforma) : null,
      textoEstado(d),
      d.conectado ? null : el("span", { class: "chip negada" }, "offline — ferramentas desativadas")),
    cardLocal(d), cardNotificar(d), cardCamera(d), cardAudio(d), cardAbrir(d), cardEstado(d));
}

async function carregarDevices() {
  const { devices } = await api("/devices");
  estado.devices = devices;
  renderLista();
  const d = dev(estado.sel);
  // remonta o console só se o device mudou de online/offline (não apaga o que o dono está digitando)
  if (d && d.conectado !== estado.consoleOnline) renderConsole();
  atualizarSelectMapa();
  if (abaAtual() === "mapa" && !estado.filtro.device) desenharUltimas();
  if (abaAtual() === "mapa") renderDestaque();             // online/bateria/alertas a cada 10 s
}

// ── mapa ────────────────────────────────────────────────────────────────────────────────────────────────
let mapa, camadas, camadaAtual, grupoPontos, grupoTrilha, enquadrado = false;

const CAMADAS = {
  // escuro = o mesmo OSM com filtro de cor no CSS (.tiles-escuro): o "dark" da CARTO passou a exigir chave
  escuro: ["https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap", "tiles-escuro"],
  ruas: ["https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", "© OpenStreetMap"],
  satelite: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", "© Esri"],
};

function iniciarMapa() {
  if (mapa || typeof L === "undefined") return;
  mapa = L.map("mapa", { preferCanvas: true }).setView([-15.79, -47.88], 4);   // canvas: aguenta dezenas de milhares de pontos
  camadas = Object.fromEntries(Object.entries(CAMADAS).map(([k, [url, attr, cls]]) =>
    [k, L.tileLayer(url, { maxZoom: 19, attribution: attr, className: cls || "" })]));
  trocarCamada($("#f-camada").value);
  grupoPontos = L.layerGroup().addTo(mapa);
  grupoTrilha = L.layerGroup().addTo(mapa);
  grupoRotulos = L.layerGroup().addTo(mapa);
  mapa.on("zoomend moveend", desenharRotulos);                          // mais zoom → cabem mais horários
  new ResizeObserver(() => mapa.invalidateSize()).observe($("#mapa"));   // borda arrastável / tamanhos P M G
}

function trocarCamada(nome) {
  if (!mapa) return;
  if (camadaAtual) mapa.removeLayer(camadaAtual);
  camadaAtual = camadas[nome] || camadas.escuro;
  camadaAtual.addTo(mapa);
  try { localStorage.setItem("painel.camada", nome); } catch { /* sem storage */ }
}

function atualizarSelectMapa() {
  const s = $("#f-device");
  const atual = estado.filtro.device;
  s.replaceChildren(el("option", { value: "" }, "Todos (última posição)"),
    ...estado.devices.map((d) => el("option", { value: d.id, selected: d.id === atual }, d.nome && d.nome !== d.id ? `${d.nome} (${d.id})` : d.id)));
}

const COR_FONTE = (f = "") => f.startsWith("google") ? "#ff3fd8" : f === "gps" ? "#22e5ff" : "#6dff8b";

function pino(ll, nome, quando, aoClicar) {
  // ponto luminoso + etiqueta "Celular · há 2 min" (atualiza a cada refresh do painel)
  const html = `<span class="pino-ponto"></span><span class="pino-rotulo"><b>${nome}</b> · ${relativo(quando)}</span>`;
  const m = L.marker(ll, { icon: L.divIcon({ className: "pino", html, iconSize: null, iconAnchor: [9, 9] }),
                           title: `${nome} · ${dataHora(quando)}`, riseOnHover: true });
  if (aoClicar) m.on("click", aoClicar);
  return m;
}

// Devices no MESMO lugar (≤ JUNTOS_M) = um marcador só, um nome por linha (antes os rótulos se sobrepunham e não dava
// pra ver que os dois celulares estavam juntos). Clicar num nome abre a trilha daquele device.
const JUNTOS_M = 60;
function agruparDevices(itens) {                  // itens: [{id, nome, lat, lon, quando, precisao_m}]
  const grupos = [];
  for (const it of itens) {
    const g = grupos.find((x) => metros(x, it) <= JUNTOS_M);
    if (g) g.itens.push(it); else grupos.push({ lat: it.lat, lon: it.lon, itens: [it] });
  }
  return grupos;
}

function pinoGrupo(g, { secundario = false } = {}) {
  const linhas = g.itens.map((it) =>
    `<span class="pino-linha" data-id="${it.id}"><b>${it.nome}</b> · ${relativo(it.quando)}</span>`).join("");
  const html = `<span class="pino-ponto"></span><span class="pino-rotulo">${linhas}</span>`;
  const m = L.marker([g.lat, g.lon], {
    icon: L.divIcon({ className: `pino${secundario ? " secundario" : ""}`, html, iconSize: null, iconAnchor: [9, 9] }),
    title: g.itens.map((it) => `${it.nome} · ${dataHora(it.quando)}`).join("\n"), riseOnHover: true,
  });
  m.on("click", (e) => {
    const alvo = e.originalEvent?.target?.closest?.(".pino-linha");
    const id = alvo?.dataset?.id || g.itens[0].id;
    if (id !== estado.filtro.device) escolherNoMapa(id);
  });
  return m;
}

const posicoesDevices = () => estado.devices.filter((d) => d.localizacao).map((d) => ({
  id: d.id, nome: d.nome || d.id, lat: d.localizacao.lat, lon: d.localizacao.lon,
  quando: d.localizacao.quando, precisao_m: d.localizacao.precisao_m }));

function desenharUltimas() {
  iniciarMapa();
  if (!mapa) return;
  grupoTrilha.clearLayers();
  grupoPontos.clearLayers();
  const coords = [];
  const pos = posicoesDevices();
  for (const p of pos) {
    coords.push([p.lat, p.lon]);
    if (p.precisao_m && p.precisao_m <= 1000) {    // anel de ±10 km (IP) só atrapalha a leitura
      L.circle([p.lat, p.lon], { radius: p.precisao_m, color: "#22e5ff", weight: 1, fillOpacity: 0.06 }).addTo(grupoPontos);
    }
  }
  for (const g of agruparDevices(pos)) pinoGrupo(g).addTo(grupoPontos);
  $("#resumo-mapa").textContent = coords.length
    ? `Última posição de ${coords.length} device(s). Escolha um device e o intervalo para ver a trilha.`
    : "Nenhum device mandou posição ainda.";
  if (coords.length && !enquadrado) { mapa.fitBounds(coords, { maxZoom: 15, padding: [40, 40] }); enquadrado = true; }
  renderCompartilhar(null, null);                 // "Todos": nada a compartilhar até escolher um device
}

// ── limpeza da trilha (só pra LINHA; os pontos continuam todos no mapa) ──────────────────────────────
function metros(a, b) {
  const R = 6371000, r = Math.PI / 180;
  const dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function trechosLimpos(cron) {
  // fora da linha: visita do Google (centro do lugar, não um passo do trajeto), precisão ruim (> 250 m: a rede
  // "pula" ±100 m com o celular parado), salto impossível (> 200 km/h) e tremido parado (< 25 m do anterior).
  // Buraco > 1 h entre pontos = começa outro trecho (não liga dias diferentes com um risco reto).
  const trechos = [];
  let atual = [], ult = null;
  for (const p of cron) {
    if (p.fonte === "google-visita") continue;
    if (p.precisao_m && p.precisao_m > 250) continue;
    if (ult) {
      const dt = p.quando - ult.quando, d = metros(ult, p);
      if (dt > 3600) { if (atual.length > 1) trechos.push(atual); atual = []; ult = null; }
      else if (dt > 0 && d / dt > 55) continue;
      else if (d < 25) continue;
    }
    atual.push([p.lat, p.lon]);
    ult = p;
  }
  if (atual.length > 1) trechos.push(atual);
  return trechos;
}

// ── paradas × movimento ──────────────────────────────────────────────────────────────────────────────
// Parada = pontos seguidos que ficam a até RAIO_PARADA m do centro deles por ≥ 5 min (o centro vai sendo a
// média). O resto é movimento. Precisão ruim (> 250 m) não decide nada (a rede "pula" com o celular parado).
// Buraco > 20 min sem nenhum ponto = SEM DADOS (não dá pra afirmar que ficou parado: medido 04/11, o job antigo
// deixou 11:12→12:42 vazio e o mapa "juntava" tudo numa parada só de 6 h 36). O rastreador manda ≤ 5 min parado.
// MIN_PARADA_S = 2 min: o dono lembrou de ter parado 2–3 min e com 5 min não aparecia (04/11)
const RAIO_PARADA = 120, MIN_PARADA_S = 120, BURACO_MAX_S = 20 * 60;
function detectarParadas(cron) {
  const pts = cron.filter((p) => !(p.precisao_m > 250));
  const paradas = [];
  let i = 0;
  while (i < pts.length) {
    let j = i, c = { lat: pts[i].lat, lon: pts[i].lon }, n = 1;
    while (j + 1 < pts.length && metros(c, pts[j + 1]) <= RAIO_PARADA && pts[j + 1].quando - pts[j].quando < BURACO_MAX_S) {
      j++; n++;
      c = { lat: c.lat + (pts[j].lat - c.lat) / n, lon: c.lon + (pts[j].lon - c.lon) / n };
    }
    if (pts[j].quando - pts[i].quando >= MIN_PARADA_S) {
      paradas.push({ inicio: pts[i].quando, fim: pts[j].quando, lat: c.lat, lon: c.lon, n });
      i = j + 1;
    } else i++;
  }
  return paradas;
}

// Buracos: intervalos sem nenhum ponto maiores que BURACO_MAX_S (pra dizer "sem dados", não inventar parada)
function buracos(cron) {
  const out = [];
  for (let i = 1; i < cron.length; i++) {
    if (cron[i].quando - cron[i - 1].quando > BURACO_MAX_S) out.push({ inicio: cron[i - 1].quando, fim: cron[i].quando });
  }
  return out;
}

// Paradas no MESMO lugar (centros a até RAIO_PARADA) viram um marcador só, com todos os intervalos
function agruparLugares(paradas) {
  const lugares = [];
  for (const s of paradas) {
    const l = lugares.find((x) => metros(x, s) <= RAIO_PARADA);
    if (l) l.paradas.push(s); else lugares.push({ lat: s.lat, lon: s.lon, paradas: [s] });
  }
  return lugares;
}

function duracao(s) {
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, "0")}` : ""}`;
}

// Card do ponto (ao clicar): estado, horário, endereço (Nominatim, pelo server), coordenadas, abrir no Maps.
function abrirCard(ll, info) {
  const el = document.createElement("div");
  el.className = "card-ponto";
  const t = (cls, txt) => { const e = document.createElement("div"); e.className = cls; e.textContent = txt; el.append(e); return e; };
  t(`cp-estado ${info.parado ? "parado" : "movendo"}`, info.parado ? "⏸ Parado" : "▶ Em movimento");
  t("cp-hora", info.hora);
  if (info.extra) t("cp-extra", info.extra);
  const end = t("cp-end", "buscando endereço…");
  t("cp-meta", `${ll.lat.toFixed(6)}, ${ll.lng.toFixed(6)}${info.meta ? ` · ${info.meta}` : ""}`);
  const a = document.createElement("a");
  a.href = `https://www.google.com/maps?q=${ll.lat},${ll.lng}`; a.target = "_blank"; a.rel = "noopener";
  a.textContent = "abrir no Google Maps ↗";
  el.append(a);
  L.popup({ maxWidth: 320, className: "popup-ponto" }).setLatLng(ll).setContent(el).openOn(mapa);
  api(`/endereco?lat=${ll.lat}&lon=${ll.lng}`)
    .then((r) => {
      if (r.erro) { end.textContent = r.erro; return; }
      end.replaceChildren();
      for (const [cls, v] of [["cp-lugar", r.lugar], ["cp-rua", r.linha1], ["cp-cidade", r.linha2]]) {
        if (!v) continue;
        const d = document.createElement("div"); d.className = cls; d.textContent = v; end.append(d);
      }
      if (!end.childElementCount) end.textContent = r.completo || "sem endereço para este ponto";
    })
    .catch(() => { end.textContent = "endereço indisponível"; });
}

// ── destaque do device no topo do mapa: online, bateria, parado/andando, última posição + endereço, alertas ──
let situacao = null;                          // {parado, desde, vel, ponto} — calculada na trilha
let enderecoDestaque = { chave: "", texto: "" };

function renderDestaque() {
  const caixa = $("#destaque-device");
  const d = dev(estado.filtro.device);
  if (!d) { caixa.hidden = true; return; }
  caixa.hidden = false;
  const ult = situacao?.ponto || d.localizacao;
  const est = d.estado || {};
  const agora = Date.now() / 1000;
  const item = (rotulo, valor, cls = "") => el("div", { class: `dq-item ${cls}` }, el("span", { class: "dq-rot" }, rotulo), el("b", {}, valor));
  const itens = [
    item("Conexão", d.conectado ? `● online${d.conectado_desde ? ` desde ${new Date(d.conectado_desde * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}` : ""}`
                                : `○ offline · visto ${relativo(d.ultima_vez)}`, d.conectado ? "ok" : "off"),
  ];
  if (est.bateria != null) {
    itens.push(item("Bateria", `${est.bateria}%${est.carregando ? " ⚡ carregando" : ""} · ${relativo(d.estado_em)}`,
      est.bateria <= 20 && !est.carregando ? "alerta" : ""));
  }
  if (situacao) {
    itens.push(situacao.parado
      ? item("Situação", `⏸ parado ${relativo(situacao.desde).replace("há ", "há ")} (desde ${new Date(situacao.desde * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })})`, "parado")
      : item("Situação", `▶ em movimento${situacao.vel != null ? ` · ${Math.round(situacao.vel)} km/h` : ""}`, "movendo"));
  }
  if (ult) {
    const fonte = ult.fonte ? ` · ${ult.fonte}` : "";
    itens.push(item("Última posição", `${dataHora(ult.quando)} · ${relativo(ult.quando)}${ult.precisao_m ? ` · ±${Math.round(ult.precisao_m)} m` : ""}${fonte}`));
  }
  const end = el("div", { class: "dq-end" }, enderecoDestaque.texto || (ult ? "buscando endereço…" : ""));
  const alertas = [];
  if (est.loc_bloqueada_desde) {
    alertas.push(el("div", { class: "dq-alerta" }, `📵 Localização bloqueada pelo Android desde ${new Date(est.loc_bloqueada_desde * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} ` +
      "(o Termux:API não responde com a tela apagada). No celular: Termux:API → Permissões → Localização → “Permitir o tempo todo” e Bateria → “Sem restrições”."));
  } else if (d.conectado && ult && agora - ult.quando > 10 * 60) {
    alertas.push(el("div", { class: "dq-aviso" }, `⚠ Conectado, mas sem posição nova ${relativo(ult.quando)}.`));
  }
  caixa.replaceChildren(el("div", { class: "dq-topo" }, el("h2", {}, d.nome || d.id), ...itens), end, ...alertas);
  if (ult) {
    const chave = `${ult.lat.toFixed(4)},${ult.lon.toFixed(4)}`;
    if (chave !== enderecoDestaque.chave) {
      enderecoDestaque = { chave, texto: "" };
      api(`/endereco?lat=${ult.lat}&lon=${ult.lon}`).then((r) => {
        if (enderecoDestaque.chave !== chave) return;
        enderecoDestaque.texto = r.erro ? "" : ["📍", r.lugar, r.linha1, r.linha2].filter(Boolean).join(" ");
        const e = $("#destaque-device .dq-end"); if (e) e.textContent = enderecoDestaque.texto;
      }).catch(() => {});
    }
  }
}

let mostrarLinha = true;
try { mostrarLinha = localStorage.getItem("painel.linha") !== "0"; } catch { /* sem storage */ }
let mostrarHoras = true;
try { mostrarHoras = localStorage.getItem("painel.horas") !== "0"; } catch { /* sem storage */ }
let grupoRotulos = null;
let rotulosPontos = [];                       // [{ll, txt}] da trilha atual, em ordem cronológica

// Horário em cima de cada ponto da trilha. Só desenha os que NÃO se sobrepõem na tela (guloso, em ordem
// cronológica): com zoom afastado aparecem poucos; aproximando, aparecem os do meio.
function desenharRotulos() {
  if (!grupoRotulos) return;
  grupoRotulos.clearLayers();
  if (!mostrarHoras || !rotulosPontos.length) return;
  const vista = mapa.getBounds().pad(0.1);
  const postos = [];
  const MIN_X = 64, MIN_Y = 22;               // ~ tamanho de uma etiqueta "dd/mm 09:18"
  for (const r of rotulosPontos) {
    if (!vista.contains(r.ll)) continue;
    const pt = mapa.latLngToContainerPoint(r.ll);
    if (postos.some((q) => Math.abs(q.x - pt.x) < MIN_X && Math.abs(q.y - pt.y) < MIN_Y)) continue;
    postos.push(pt);
    L.marker(r.ll, { interactive: false, keyboard: false,
      icon: L.divIcon({ className: `rotulo-hora${r.parada ? " parada" : ""}`, html: `<span>${r.txt}</span>`, iconSize: null }) }).addTo(grupoRotulos);
    if (postos.length >= 150) break;
  }
}

function escolherNoMapa(id) {
  estado.filtro.device = id;
  $("#f-device").value = id;
  recarregar();
}

let trilhaEm = 0;                             // quando a trilha foi carregada (pro refresh automático)
async function carregarTrilha(manterVista = false) {
  trilhaEm = Date.now();
  iniciarMapa();
  const f = estado.filtro;
  if (!f.device) { situacao = null; renderDestaque(); desenharUltimas(); return; }
  const q = new URLSearchParams({ desde: String(f.desde ?? 0) });
  if (f.ate != null) q.set("ate", String(f.ate));
  const { pontos } = await api(`/devices/${encodeURIComponent(f.device)}/localizacoes?${q}`);
  grupoPontos.clearLayers();
  grupoTrilha.clearLayers();
  rotulosPontos = [];
  desenharRotulos();
  const d = dev(f.device);
  const nome = d?.nome || f.device;
  if (!pontos.length) {
    situacao = null;
    renderDestaque();
    $("#resumo-mapa").textContent = `${nome}: nenhuma posição nesse intervalo.`;
    renderCompartilhar(nome, d?.localizacao);
    return;
  }
  const cron = pontos.slice().reverse();
  const ll = cron.map((p) => [p.lat, p.lon]);
  const ult = cron[cron.length - 1];
  const variosDias = new Date(cron[0].quando * 1000).toDateString() !== new Date(ult.quando * 1000).toDateString();
  const hora = (e) => new Date(e * 1000).toLocaleString("pt-BR", variosDias
    ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" });
  const hm = (e) => new Date(e * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

  // paradas: círculo âmbar por LUGAR com cada intervalo "chegou–saiu · quanto tempo". É uma MARCAÇÃO por cima:
  // todos os pontos e a linha crua continuam no mapa (esconder ponto = esconder dado — pedido do dono 04/11)
  const paradas = detectarParadas(cron);
  const semDados = buracos(cron);
  const naParada = (p) => paradas.find((s) => p.quando >= s.inicio && p.quando <= s.fim && metros(s, p) <= RAIO_PARADA);
  const rotParadas = [];
  const intervalo = (s) => `${hm(s.inicio)}–${hm(s.fim)} · ${duracao(s.fim - s.inicio)}`;
  for (const l of agruparLugares(paradas)) {
    const total = l.paradas.reduce((a, s) => a + s.fim - s.inicio, 0);
    const vazios = semDados.filter((b) => l.paradas.some((s) => Math.abs(b.inicio - s.fim) < 60 || Math.abs(b.fim - s.inicio) < 60));
    const info = { parado: true,
      hora: l.paradas.map((s) => `${hora(s.inicio)} → ${hm(s.fim)}`).join("\n"),
      extra: `ficou ${duracao(total)} no total` + (vazios.length ? ` · sem dados: ${vazios.map((b) => `${hm(b.inicio)}–${hm(b.fim)}`).join(", ")}` : "") };
    L.circleMarker([l.lat, l.lon], { radius: 11, color: "#ffb020", weight: 2.5, fillColor: "#ffb020", fillOpacity: 0.28 })
      .bindTooltip(`⏸ parado ${l.paradas.map(intervalo).join(" | ")}`)
      .on("click", (e) => abrirCard(e.latlng, info))
      .addTo(grupoTrilha);
    rotParadas.push({ ll: L.latLng(l.lat, l.lon), txt: `⏸ ${l.paradas.map(intervalo).join("  ·  ")}`, parada: true });
  }

  // linha crua ANTES das bolinhas e sem clique: no canvas, a camada de cima "rouba" o clique (04/11: o card
  // não abria nos pontos de movimento porque a linha estava desenhada por cima deles)
  if (mostrarLinha) {
    L.polyline(trechosLimpos(cron), { color: "#ff3fd8", weight: 3, opacity: 0.8, lineJoin: "round", interactive: false })
      .addTo(grupoTrilha);
  }
  // movimento: bolinhas pela fonte + velocidade desde o ponto anterior
  const passo = Math.max(1, Math.ceil(cron.length / 1500));      // milhares de bolinhas travam o navegador
  const rotMov = [];
  let distMov = 0;
  for (let i = 0; i < cron.length; i++) {
    const p = cron[i], ant = cron[i - 1];
    const parada = naParada(p);
    let vel = null;
    if (ant && !parada && p.quando > ant.quando && !(p.precisao_m > 250)) {
      const d = metros(ant, p);
      vel = (d / (p.quando - ant.quando)) * 3.6;
      if (vel < 200 && p.quando - ant.quando < 3600) distMov += d;
    }
    if (i % passo) continue;
    const visita = p.fonte === "google-visita";
    const meta = [p.precisao_m ? `±${Math.round(p.precisao_m)} m` : "", p.fonte || ""].filter(Boolean).join(" · ");
    const avisos = [];
    if (parada) avisos.push(`dentro da parada ${hm(parada.inicio)}–${hm(parada.fim)}`);
    else if (vel != null && vel < 200) avisos.push(`${Math.round(vel)} km/h desde o ponto anterior`);
    if (p.precisao_m >= 100) avisos.push("precisão de rede (±100 m): um desvio pequeno pode ser tremido do sinal");
    const info = { parado: !!parada, hora: dataHora(p.quando), extra: avisos.join(" · "), meta };
    L.circleMarker([p.lat, p.lon], visita
      ? { radius: 7, color: "#ff3fd8", weight: 2, fillOpacity: 0.15 }               // lugar visitado (Google)
      : { radius: 4, color: COR_FONTE(p.fonte), weight: 1, fillOpacity: 0.9 })
      .bindTooltip(`${hora(p.quando)}${!parada && vel != null && vel < 200 ? ` · ${Math.round(vel)} km/h` : ""}`)
      .on("click", (e) => abrirCard(e.latlng, info))
      .addTo(grupoTrilha);
    if (i < cron.length - 1 && !parada) rotMov.push({ ll: L.latLng(p.lat, p.lon), txt: hora(p.quando) });  // dentro da parada o horário já está na etiqueta dela
  }
  {                                                       // o device escolhido + os OUTROS devices (último ponto)
    const eu = { id: f.device, nome, lat: ult.lat, lon: ult.lon, quando: ult.quando };
    const outros = posicoesDevices().filter((p) => p.id !== f.device);
    const juntos = outros.filter((p) => metros(p, eu) <= JUNTOS_M);            // no mesmo lugar → mesmo marcador
    pinoGrupo({ lat: eu.lat, lon: eu.lon, itens: [eu, ...juntos] }).addTo(grupoTrilha);
    for (const g of agruparDevices(outros.filter((p) => !juntos.includes(p)))) pinoGrupo(g, { secundario: true }).addTo(grupoTrilha);
  }
  {                                                       // situação AGORA pro destaque: está numa parada ou andando
    const s = paradas.find((x) => x.fim >= ult.quando - 1 && metros(x, ult) <= RAIO_PARADA);
    const ant = cron[cron.length - 2];
    const vel = ant && ult.quando > ant.quando ? (metros(ant, ult) / (ult.quando - ant.quando)) * 3.6 : null;
    situacao = estado.filtro.ate == null                  // intervalo no passado: não fala do passado como "agora"
      ? { parado: !!s || (vel != null && vel < 2), desde: s ? s.inicio : ult.quando, vel, ponto: ult } : null;
  }
  renderDestaque();
  rotulosPontos = [...rotParadas, ...rotMov];             // paradas primeiro: ganham o espaço na tela
  if (!manterVista) mapa.fitBounds(ll, { maxZoom: 16, padding: [40, 40] });   // refresh: não mexe no zoom do usuário
  desenharRotulos();
  const tParado = paradas.reduce((a, s) => a + s.fim - s.inicio, 0);
  $("#resumo-mapa").textContent = `${nome}: ${pontos.length} posição(ões) de ${dataHora(cron[0].quando)} a ${dataHora(ult.quando)}` +
    ` · ${paradas.length} parada(s), ${duracao(tParado)} parado · ${(distMov / 1000).toFixed(1)} km em movimento` +
    (semDados.length ? ` · sem dados: ${semDados.map((b) => `${hm(b.inicio)}–${hm(b.fim)}`).join(", ")}` : "") +
    " · âmbar = parado · bolinhas: ciano = GPS, verde = rede, rosa = Google · clique num ponto para ver o endereço";
  renderCompartilhar(nome, ult);
}

function renderCompartilhar(nome, p) {
  // só com um device ESCOLHIDO no campo Device (com "Todos" o card some)
  $("#card-compartilhar").hidden = !estado.filtro.device;
  $("#compartilhar-alvo").textContent = p ? "" : `${nome || "Este device"} não tem posição guardada.`;
  $("#links-share").replaceChildren(p ? blocoCompartilhar(nome, p) : "");
}

function aplicarPreset(h) {
  document.querySelectorAll("#f-presets button").forEach((b) => b.classList.toggle("sel", Number(b.dataset.h) === h));
  estado.filtro.horas = h;
  estado.filtro.desde = h ? Date.now() / 1000 - h * 3600 : 0;     // 0 = desde sempre
  estado.filtro.ate = null;
  // os campos De/Até mostram o intervalo que o preset escolheu (dá pra ajustar a partir dele e Aplicar);
  // estado.filtro.ate segue null = "até agora" (a trilha continua viva, não congela na hora do clique)
  $("#f-de").value = h ? paraInput(estado.filtro.desde) : "";
  $("#f-ate").value = paraInput(Date.now() / 1000);
}

const recarregar = () => carregarTrilha().catch((x) => aviso(x.message, true));
$("#f-device").addEventListener("change", (e) => { estado.filtro.device = e.target.value; recarregar(); });
$("#f-presets").addEventListener("click", (e) => {
  const h = e.target.dataset?.h;
  if (h === undefined) return;
  aplicarPreset(Number(h));
  recarregar();
});
$("#f-limpar").addEventListener("click", () => {          // volta ao padrão: Todos, 24 h até agora
  estado.filtro.device = "";                               // (camada/tamanho/linha/horários = preferência, ficam)
  $("#f-device").value = "";
  situacao = null;
  enquadrado = false;
  aplicarPreset(24);
  recarregar();
});
$("#f-aplicar").addEventListener("click", () => {
  const de = $("#f-de").value, ate = $("#f-ate").value;
  estado.filtro.desde = de ? new Date(de).getTime() / 1000 : 0;
  estado.filtro.ate = ate ? new Date(ate).getTime() / 1000 : null;
  document.querySelectorAll("#f-presets button").forEach((b) => b.classList.remove("sel"));
  if (!estado.filtro.device) aviso("Escolha um device para ver a trilha do intervalo");
  recarregar();
});
$("#f-camada").addEventListener("change", (e) => trocarCamada(e.target.value));
$("#f-horas").classList.toggle("sel", mostrarHoras);
$("#f-horas").addEventListener("click", () => {
  mostrarHoras = !mostrarHoras;
  $("#f-horas").classList.toggle("sel", mostrarHoras);
  try { localStorage.setItem("painel.horas", mostrarHoras ? "1" : "0"); } catch { /* sem storage */ }
  desenharRotulos();
});
$("#f-linha").classList.toggle("sel", mostrarLinha);
$("#f-linha").addEventListener("click", () => {
  mostrarLinha = !mostrarLinha;
  $("#f-linha").classList.toggle("sel", mostrarLinha);
  try { localStorage.setItem("painel.linha", mostrarLinha ? "1" : "0"); } catch { /* sem storage */ }
  recarregar();
});
$("#f-altura").addEventListener("click", (e) => {
  const a = e.target.dataset?.a;
  if (!a) return;
  document.querySelectorAll("#f-altura button").forEach((b) => b.classList.toggle("sel", b.dataset.a === a));
  $("#mapa").style.height = `${a}px`;
});

const caixa = $("#mapa-caixa");
$("#f-cheia").addEventListener("click", () => {
  if (caixa.requestFullscreen) caixa.requestFullscreen().catch(() => aviso("Tela cheia indisponível neste navegador", true));
  else aviso("Tela cheia indisponível neste navegador", true);
});
$("#f-sair-cheia").addEventListener("click", () => document.exitFullscreen && document.exitFullscreen());
document.addEventListener("fullscreenchange", () => {
  $("#f-sair-cheia").hidden = document.fullscreenElement !== caixa;
  setTimeout(() => mapa && mapa.invalidateSize(), 150);
});

// importar Linha do tempo do Google (arrastar o Timeline.json) — com carregando e cancelar
(() => {
  const drop = $("#drop-google"), entrada = $("#arq-google");
  const TEXTO = "Solte o Timeline.json aqui (ou toque para escolher)";
  let controle = null;                                            // AbortController da importação em curso
  const ocioso = () => {
    controle = null;
    drop.classList.remove("carregando");
    drop.removeAttribute("aria-busy");
    drop.replaceChildren(el("span", { class: "drop-texto" }, TEXTO));
  };
  const enviar = async (f) => {
    if (!f || controle) return;
    if (!estado.filtro.device) { aviso("Escolha antes, no campo Device, de qual device é essa Linha do tempo", true); return; }
    controle = new AbortController();
    drop.classList.add("carregando");
    drop.setAttribute("aria-busy", "true");
    drop.replaceChildren(
      el("span", { class: "spinner", "aria-hidden": "true" }),
      el("span", { class: "drop-texto" }, `Importando ${f.name} (${Math.ceil(f.size / 1024 / 1024)} MB)…`),
      el("button", { type: "button", class: "rosa cancelar", onclick: (e) => { e.stopPropagation(); controle && controle.abort(); } }, "✕ Cancelar"));
    try {
      const fd = new FormData();
      fd.append("arquivo", f);
      const r = await api(`/devices/${encodeURIComponent(estado.filtro.device)}/localizacoes/importar`,
                          { method: "POST", body: fd, signal: controle.signal });
      aviso(`${r.lidos} ponto(s) lidos, ${r.novos} novo(s)` + (r.de ? ` · ${dataHora(r.de)} → ${dataHora(r.ate)}` : ""));
      aplicarPreset(0);
      await carregarTrilha();
    } catch (e) {
      aviso(e.name === "AbortError" ? "Importação cancelada" : `Não importou: ${e.message}`, e.name !== "AbortError");
    } finally {
      entrada.value = "";
      ocioso();
    }
  };
  drop.addEventListener("click", () => { if (!controle) entrada.click(); });
  drop.addEventListener("keydown", (e) => { if (!controle && (e.key === "Enter" || e.key === " ")) entrada.click(); });
  entrada.addEventListener("change", () => enviar(entrada.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); if (!controle) drop.classList.add("sobre"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("sobre"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("sobre"); enviar(e.dataTransfer.files[0]); });
})();

// ── abas + ciclo ────────────────────────────────────────────────────────────────────────────────────────
function abaAtual() {
  const a = location.hash.slice(1);
  return document.getElementById(`aba-${a}`) ? a : "devices";
}

async function atualizar() {
  try {
    await carregarDevices();
    // trilha "até agora" com o mapa aberto: recarrega a cada 30 s (pontos novos do rastreador aparecem sozinhos)
    if (abaAtual() === "mapa" && estado.filtro.device && estado.filtro.ate == null && Date.now() - trilhaEm > 30_000) {
      await carregarTrilha(true);
    }
    $("#status").textContent = `● ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  } catch (e) {
    $("#status").textContent = `sem conexão (${e.message})`;
  }
}

function mostrarAba() {
  const aba = abaAtual();
  document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== `aba-${aba}`));
  document.querySelectorAll("#abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
  if (aba === "mapa") {
    iniciarMapa();
    setTimeout(() => mapa && mapa.invalidateSize(), 0);
    atualizarSelectMapa();
    recarregar();
  }
  if (aba === "cerebro" && window.cerebroAbrir) window.cerebroAbrir();
  if (aba === "acervo" && window.acervoAbrir) window.acervoAbrir();
}

try { const c = localStorage.getItem("painel.camada"); if (c && CAMADAS[c]) $("#f-camada").value = c; } catch { /* sem storage */ }
aplicarPreset(24);
window.addEventListener("hashchange", mostrarAba);
$("#btn-atualizar").addEventListener("click", async () => {
  const b = $("#btn-atualizar");
  b.disabled = true;
  await atualizar();
  if (abaAtual() === "mapa") await carregarTrilha().catch((x) => aviso(x.message, true));
  if (abaAtual() === "cerebro" && window.cerebroRecarregar) await window.cerebroRecarregar();
  if (abaAtual() === "acervo" && window.acervoAbrir) await window.acervoAbrir();
  b.disabled = false;
  aviso("Atualizado");
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
setInterval(() => { if (!document.hidden) atualizar(); }, ATUALIZA_MS);
atualizar().then(mostrarAba);
