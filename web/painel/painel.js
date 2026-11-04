// Painel do agente — JS puro, sem build. Dados via /api/v1/painel/* (cookie de sessão do painel).
"use strict";

const API = "/api/v1/painel";
const ATUALIZA_MS = 10_000;

// ── util ────────────────────────────────────────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined) n.append(f);
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
  return new Date(epoch * 1000).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

let avisoTimer;
function aviso(texto, erro = false) {
  const a = $("#aviso");
  a.textContent = texto;
  a.className = "aviso" + (erro ? " erro" : "");
  a.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => (a.hidden = true), 3500);
}

async function api(caminho, opcoes = {}) {
  const r = await fetch(API + caminho, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...opcoes,
  });
  if (r.status === 401) {
    location.reload(); // cookie expirou → a página mostra como entrar
    throw new Error("não autorizado");
  }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ── devices ─────────────────────────────────────────────────────────────────────────────────────────────
async function notificar(d, botao) {
  botao.disabled = true;
  try {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/notificar`, {
      method: "POST",
      body: JSON.stringify({ title: "Painel", message: "Teste de notificação pelo painel" }),
    });
    aviso(r.ok ? `Notificação enviada pra ${d.nome}` : `Falhou: ${r.resultado}`, !r.ok);
  } catch (e) {
    aviso(`Erro: ${e.message}`, true);
  } finally {
    botao.disabled = false;
  }
}

// ── mapa ────────────────────────────────────────────────────────────────────────────────────────────────
let mapa, camadaPontos, camadaTrilha, mapaEnquadrado = false;

function iniciarMapa() {
  if (mapa || typeof L === "undefined") return;
  mapa = L.map("mapa", { zoomControl: true, attributionControl: true }).setView([-15.79, -47.88], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap",
  }).addTo(mapa);
  camadaPontos = L.layerGroup().addTo(mapa);
  camadaTrilha = L.layerGroup().addTo(mapa);
}

function desenharPontos(devices) {
  iniciarMapa();
  if (!mapa) return;
  camadaPontos.clearLayers();
  const coords = [];
  for (const d of devices) {
    const p = d.localizacao;
    if (!p) continue;
    const ll = [p.lat, p.lon];
    coords.push(ll);
    if (p.precisao_m) L.circle(ll, { radius: p.precisao_m, weight: 1, fillOpacity: 0.08 }).addTo(camadaPontos);
    L.marker(ll, { title: d.nome || d.id })
      .bindPopup(`<b>${d.nome || d.id}</b><br>${relativo(p.quando)} · ${dataHora(p.quando)}` +
                 (p.precisao_m ? `<br>±${Math.round(p.precisao_m)} m` : "") + (p.fonte ? ` · ${p.fonte}` : ""))
      .addTo(camadaPontos);
  }
  $("#legenda-mapa").textContent = coords.length
    ? `Última posição de ${coords.length} device(s). “Trilha 24h” num cartão mostra o caminho.`
    : "Nenhum device mandou posição ainda — rode o setup de permissões no celular.";
  if (coords.length && !mapaEnquadrado) {          // enquadra só na 1ª vez: depois o zoom é do dono
    mapa.fitBounds(coords, { maxZoom: 15, padding: [30, 30] });
    mapaEnquadrado = true;
  }
}

async function trilha(d, botao) {
  botao.disabled = true;
  try {
    const { pontos } = await api(`/devices/${encodeURIComponent(d.id)}/localizacoes?horas=24`);
    camadaTrilha.clearLayers();
    if (!pontos.length) { aviso(`${d.nome}: sem posições nas últimas 24 h`); return; }
    const ll = pontos.slice().reverse().map((p) => [p.lat, p.lon]);
    L.polyline(ll, { weight: 3, opacity: 0.8 }).addTo(camadaTrilha);
    for (const p of pontos) L.circleMarker([p.lat, p.lon], { radius: 3, weight: 1 })
      .bindTooltip(dataHora(p.quando)).addTo(camadaTrilha);
    mapa.fitBounds(ll, { maxZoom: 16, padding: [30, 30] });
    aviso(`${d.nome}: ${pontos.length} posição(ões) nas últimas 24 h`);
    $("#mapa").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (e) {
    aviso(`Erro: ${e.message}`, true);
  } finally {
    botao.disabled = false;
  }
}

async function localizarAgora(d, botao) {
  botao.disabled = true;
  botao.textContent = "Localizando…";
  try {
    const r = await api(`/devices/${encodeURIComponent(d.id)}/localizar`, { method: "POST" });
    if (r.ok) {
      aviso(`${d.nome}: ${r.ponto.lat.toFixed(5)}, ${r.ponto.lon.toFixed(5)}` +
            (r.ponto.precisao_m ? ` (±${Math.round(r.ponto.precisao_m)} m)` : ""));
      mapa && mapa.setView([r.ponto.lat, r.ponto.lon], 16);
      await carregarDevices();
    } else {
      aviso(`${d.nome}: não leu — ${r.motivo}`, true);
    }
  } catch (e) {
    aviso(`Erro: ${e.message}`, true);
  } finally {
    botao.disabled = false;
    botao.textContent = "Localizar agora";
  }
}

// ── cartão ──────────────────────────────────────────────────────────────────────────────────────────────
const NOME_PERM = {
  camera: "câmera", microfone: "microfone", localizacao: "localização", localizacao_fundo: "localização 2º plano",
  arquivos: "arquivos", notificacao: "notificação", bateria: "sem economia", navegador: "navegador",
};

function chipPermissao(nome, valor) {
  const classe = valor === "ok" ? "ok" : valor === "manual" ? "manual" : valor === "n/a" ? "na" : "negada";
  const icone = { ok: "✓", manual: "✋", na: "—", negada: "✗" }[classe];
  return el("span", { class: `chip ${classe}`, title: `${NOME_PERM[nome] || nome}: ${valor}` },
    `${icone} ${NOME_PERM[nome] || nome}`);
}

function cartaoDevice(d) {
  const online = d.conectado;
  const estado = online
    ? el("div", { class: "estado" }, el("b", {}, "Conectado"), ` ${relativo(d.conectado_desde)} · desde ${dataHora(d.conectado_desde)}`)
    : el("div", { class: "estado" }, el("b", {}, "Offline"), ` · último sinal ${relativo(d.ultima_vez)}`);

  const info = [];
  const e = d.estado || {};
  if (typeof e.bateria === "number") {
    info.push(el("span", {}, el("span", { class: "rot" }, "bateria "),
      `${e.bateria}%${e.carregando ? " ⚡" : ""}`, d.estado_em ? el("span", { class: "rot" }, ` (${relativo(d.estado_em)})`) : null));
  }
  const p = d.localizacao;
  info.push(p
    ? el("span", {}, el("span", { class: "rot" }, "posição "), `${relativo(p.quando)}`,
        p.precisao_m ? el("span", { class: "rot" }, ` ±${Math.round(p.precisao_m)} m`) : null)
    : el("span", { class: "rot" }, "sem posição"));

  const perms = Object.entries(d.permissoes || {});
  const tools = d.tools || [];
  const podeLocalizar = online && tools.includes("get_location");

  const bNotif = el("button", { type: "button", title: "Manda uma notificação de teste" }, "Notificar");
  bNotif.disabled = !online || !tools.includes("notify");
  bNotif.addEventListener("click", () => notificar(d, bNotif));
  const bLoc = el("button", { type: "button", title: podeLocalizar ? "Lê a posição agora (GPS)" : "device offline ou sem localização" }, "Localizar agora");
  bLoc.disabled = !podeLocalizar;
  bLoc.addEventListener("click", () => localizarAgora(d, bLoc));
  const bTrilha = el("button", { type: "button", title: "Caminho das últimas 24 h no mapa" }, "Trilha 24h");
  bTrilha.disabled = !p;
  bTrilha.addEventListener("click", () => trilha(d, bTrilha));

  return el("article", { class: `device ${online ? "online" : "offline"}` },
    el("div", { class: "linha1" },
      el("span", { class: "ponto", "aria-hidden": "true" }),
      el("div", {}, el("div", { class: "nome" }, d.nome || d.id), el("div", { class: "id" }, d.id)),
      d.plataforma ? el("span", { class: "plataforma" }, d.plataforma) : null,
    ),
    estado,
    el("div", { class: "linha-info" }, info),
    perms.length
      ? el("div", { class: "chips", title: "permissões (setup)" }, perms.map(([k, v]) => chipPermissao(k, v)))
      : el("div", { class: "meta" }, "permissões não verificadas (python -m companion permissoes)"),
    tools.length
      ? el("div", { class: "chips", title: "o que este device executa" }, tools.map((t) => el("span", { class: "chip" }, t)))
      : null,
    el("div", { class: "acoes" }, bNotif, bLoc, bTrilha),
  );
}

async function carregarDevices() {
  const { devices } = await api("/devices");
  const lista = $("#lista-devices");
  lista.replaceChildren(...(devices.length ? devices.map(cartaoDevice) : [el("p", { class: "vazio" }, "Nenhum device registrado.")]));
  const on = devices.filter((d) => d.conectado).length;
  $("#resumo-devices").textContent = `${on} conectado(s) de ${devices.length}`;
  desenharPontos(devices);
}

// ── abas + ciclo ────────────────────────────────────────────────────────────────────────────────────────
const CARREGAR = { devices: carregarDevices };

function abaAtual() {
  const a = location.hash.slice(1);
  return document.getElementById(`aba-${a}`) ? a : "devices";
}

async function atualizar() {
  const aba = abaAtual();
  try {
    if (CARREGAR[aba]) await CARREGAR[aba]();
    $("#status").textContent = `atualizado ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  } catch (e) {
    $("#status").textContent = `sem conexão (${e.message})`;
  }
}

function mostrarAba() {
  const aba = abaAtual();
  document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== `aba-${aba}`));
  document.querySelectorAll("#abas a").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === aba));
  if (aba === "devices" && mapa) setTimeout(() => mapa.invalidateSize(), 0);   // mapa criado com a aba escondida
  atualizar();
}

window.addEventListener("hashchange", mostrarAba);
document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
setInterval(() => { if (!document.hidden) atualizar(); }, ATUALIZA_MS);
mostrarAba();
