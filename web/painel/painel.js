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
    cardLocal(d), cardNotificar(d), cardCamera(d), cardAbrir(d), cardEstado(d));
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

function desenharUltimas() {
  iniciarMapa();
  if (!mapa) return;
  grupoTrilha.clearLayers();
  grupoPontos.clearLayers();
  const coords = [];
  for (const d of estado.devices) {
    const p = d.localizacao;
    if (!p) continue;
    coords.push([p.lat, p.lon]);
    if (p.precisao_m && p.precisao_m <= 1000) {    // anel de ±10 km (IP) só atrapalha a leitura
      L.circle([p.lat, p.lon], { radius: p.precisao_m, color: "#22e5ff", weight: 1, fillOpacity: 0.06 }).addTo(grupoPontos);
    }
    pino([p.lat, p.lon], d.nome || d.id, p.quando, () => escolherNoMapa(d.id)).addTo(grupoPontos);
  }
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

let mostrarLinha = true;
try { mostrarLinha = localStorage.getItem("painel.linha") !== "0"; } catch { /* sem storage */ }

function escolherNoMapa(id) {
  estado.filtro.device = id;
  $("#f-device").value = id;
  recarregar();
}

async function carregarTrilha() {
  iniciarMapa();
  const f = estado.filtro;
  if (!f.device) { desenharUltimas(); return; }
  const q = new URLSearchParams({ desde: String(f.desde ?? 0) });
  if (f.ate != null) q.set("ate", String(f.ate));
  const { pontos } = await api(`/devices/${encodeURIComponent(f.device)}/localizacoes?${q}`);
  grupoPontos.clearLayers();
  grupoTrilha.clearLayers();
  const d = dev(f.device);
  const nome = d?.nome || f.device;
  if (!pontos.length) {
    $("#resumo-mapa").textContent = `${nome}: nenhuma posição nesse intervalo.`;
    renderCompartilhar(nome, d?.localizacao);
    return;
  }
  const cron = pontos.slice().reverse();
  const ll = cron.map((p) => [p.lat, p.lon]);
  if (mostrarLinha) {
    L.polyline(trechosLimpos(cron), { color: "#ff3fd8", weight: 3, opacity: 0.8, lineJoin: "round" }).addTo(grupoTrilha);
  }
  const passo = Math.max(1, Math.ceil(cron.length / 1500));      // milhares de bolinhas travam o navegador
  for (let i = 0; i < cron.length; i += passo) {
    const p = cron[i];
    const visita = p.fonte === "google-visita";
    L.circleMarker([p.lat, p.lon], visita
      ? { radius: 7, color: "#ff3fd8", weight: 2, fillOpacity: 0.15 }               // lugar visitado (Google)
      : { radius: 3.5, color: COR_FONTE(p.fonte), weight: 1, fillOpacity: 0.9 })
      .bindTooltip(`${visita ? "visita · " : ""}${dataHora(p.quando)}${p.precisao_m ? ` · ±${Math.round(p.precisao_m)} m` : ""}` +
        `${p.fonte && !visita ? ` · ${p.fonte}` : ""}`)
      .addTo(grupoTrilha);
  }
  const ult = cron[cron.length - 1];
  pino([ult.lat, ult.lon], nome, ult.quando).addTo(grupoTrilha);
  mapa.fitBounds(ll, { maxZoom: 16, padding: [40, 40] });
  $("#resumo-mapa").textContent = `${nome}: ${pontos.length} posição(ões) de ${dataHora(cron[0].quando)} a ${dataHora(ult.quando)}` +
    " · ciano = GPS, verde = rede, rosa = Google, círculo vazado = lugar visitado";
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
  $("#f-de").value = h ? paraInput(estado.filtro.desde) : "";
  $("#f-ate").value = "";
}

const recarregar = () => carregarTrilha().catch((x) => aviso(x.message, true));
$("#f-device").addEventListener("change", (e) => { estado.filtro.device = e.target.value; recarregar(); });
$("#f-presets").addEventListener("click", (e) => {
  const h = e.target.dataset?.h;
  if (h === undefined) return;
  aplicarPreset(Number(h));
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
}

try { const c = localStorage.getItem("painel.camada"); if (c && CAMADAS[c]) $("#f-camada").value = c; } catch { /* sem storage */ }
aplicarPreset(24);
window.addEventListener("hashchange", mostrarAba);
$("#btn-atualizar").addEventListener("click", async () => {
  const b = $("#btn-atualizar");
  b.disabled = true;
  await atualizar();
  if (abaAtual() === "mapa") await carregarTrilha().catch((x) => aviso(x.message, true));
  b.disabled = false;
  aviso("Atualizado");
});
document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
setInterval(() => { if (!document.hidden) atualizar(); }, ATUALIZA_MS);
atualizar().then(mostrarAba);
