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

function cartaoDevice(d) {
  const online = d.conectado;
  const estado = online
    ? el("div", { class: "estado" }, el("b", {}, "Conectado"), ` ${relativo(d.conectado_desde)} · desde ${dataHora(d.conectado_desde)}`)
    : el("div", { class: "estado" }, el("b", {}, "Offline"), ` · último sinal ${relativo(d.ultima_vez)}`);

  const botao = el("button", { type: "button", title: "Manda uma notificação de teste" }, "Notificar");
  botao.disabled = !online || !(d.tools || []).includes("notify");
  botao.addEventListener("click", () => notificar(d, botao));

  return el("article", { class: `device ${online ? "online" : "offline"}` },
    el("div", { class: "linha1" },
      el("span", { class: "ponto", "aria-hidden": "true" }),
      el("div", {}, el("div", { class: "nome" }, d.nome || d.id), el("div", { class: "id" }, d.id)),
    ),
    estado,
    el("div", { class: "meta" },
      `último sinal: ${dataHora(d.ultima_vez)} · registrado: ${dataHora(d.registrado_em)}`,
      d.status !== "active" ? ` · status: ${d.status}` : null),
    (d.tools || []).length
      ? el("div", { class: "chips", title: "o que este device executa" }, d.tools.map((t) => el("span", { class: "chip" }, t)))
      : el("div", { class: "meta" }, "sem ferramentas de device"),
    el("div", { class: "acoes" }, botao),
  );
}

async function carregarDevices() {
  const { devices } = await api("/devices");
  const lista = $("#lista-devices");
  lista.replaceChildren(...(devices.length ? devices.map(cartaoDevice) : [el("p", { class: "vazio" }, "Nenhum device registrado.")]));
  const on = devices.filter((d) => d.conectado).length;
  $("#resumo-devices").textContent = `${on} conectado(s) de ${devices.length}`;
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
  atualizar();
}

window.addEventListener("hashchange", mostrarAba);
document.addEventListener("visibilitychange", () => { if (!document.hidden) atualizar(); });
setInterval(() => { if (!document.hidden) atualizar(); }, ATUALIZA_MS);
mostrarAba();
