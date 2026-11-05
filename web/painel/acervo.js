// Acervo no painel — documentos que o agente consulta. Usa $, el, api, aviso, abrirModal de painel.js.
"use strict";

const AC = { docs: [], iniciado: false };
const APIAC = "/api/v1/acervo";

async function acApi(caminho = "", opcoes = {}) {
  const form = opcoes.body instanceof FormData;
  const r = await fetch(APIAC + caminho, { credentials: "same-origin", headers: form ? {} : { "Content-Type": "application/json" }, ...opcoes });
  if (r.status === 401) { location.reload(); throw new Error("não autorizado"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.message || j.detail || `${r.status}`);
  return j;
}

async function acCarregar() {
  AC.docs = (await acApi("")).docs;
  const porCol = {};
  for (const d of AC.docs) {
    const grupo = d.colecao === "estacio" ? `Estácio · ${d.meta.disciplina || "—"}` : d.colecao;
    (porCol[grupo] ||= []).push(d);
  }
  const kb = Math.round(AC.docs.reduce((s, d) => s + d.bytes, 0) / 1024);
  $("#ac-resumo").textContent = `${AC.docs.length} documento(s) · ${kb} KB de texto · o agente consulta antes de responder (search_docs / read_doc).`;
  const ordem = Object.keys(porCol).sort((a, b) => (a.startsWith("Estácio") ? 1 : 0) - (b.startsWith("Estácio") ? 1 : 0) || a.localeCompare(b));
  $("#ac-lista").replaceChildren(...(ordem.length ? ordem.map((g) => el("div", { class: "card ac-grupo" },
    el("h3", {}, `${g.startsWith("Estácio") ? "🎓" : "📎"} ${g}`, el("span", { class: "li-conta" }, ` ${porCol[g].length}`)),
    ...porCol[g].sort((a, b) => (a.meta.ordem || 0) - (b.meta.ordem || 0) || a.titulo.localeCompare(b.titulo)).map(acItem)))
    : [el("div", { class: "vazio" }, "Acervo vazio. Arraste um documento acima.")]));
}

function acItem(d) {
  const extra = d.meta.enviado_em ? `enviado ${d.meta.enviado_em}` : d.meta.ordem ? `tema ${d.meta.ordem}` : "";
  return el("div", { class: "ac-item" },
    el("button", { type: "button", class: "ac-nome", title: "ver o sumário", onclick: () => acSumario(d) },
      el("b", {}, d.titulo), el("span", { class: "meta" }, ` · ${Math.max(1, Math.round(d.bytes / 1024))} KB${extra ? " · " + extra : ""}`)),
    el("button", { type: "button", class: "mini perigo", title: "tirar do acervo", onclick: async () => {
      if (!confirm(`Tirar “${d.titulo}” do acervo? O agente deixa de consultá-lo.`)) return;
      try { await acApi(`/${d.id}`, { method: "DELETE" }); aviso("Removido"); await acCarregar(); } catch (e) { aviso(e.message, true); }
    } }, "🗑"));
}

async function acSumario(d) {
  try {
    const s = await acApi(`/sumario/${d.id}`);
    abrirModal(el("div", { class: "ac-sumario" },
      el("h3", {}, d.titulo), el("p", { class: "meta" }, `${d.id} · ${s.secoes.length} seção(ões) — é assim que o agente navega (read_doc)`),
      ...s.secoes.filter((x) => x.chars >= 60).map((x) => el("div", { class: "ac-sec", style: `padding-left:${x.caminho.split(" > ").length - 1}rem` },
        el("span", { class: "reg-quando" }, `§${x.n}`), ` ${x.titulo}`, el("span", { class: "meta" }, ` · ${(x.chars / 1000).toFixed(1)} mil${x.partes > 1 ? ` · ${x.partes} partes` : ""}`)))));
  } catch (e) { aviso(e.message, true); }
}

async function acEnviar(arquivos) {
  const lista = $("#ac-envios");
  const colecao = $("#ac-colecao").value.trim() || "anexos";
  for (const f of arquivos) {
    const linha = el("div", { class: "ac-envio" }, el("span", { class: "spinner" }), ` ${f.name}`);
    lista.prepend(linha);
    try {
      const fd = new FormData();
      fd.append("arquivo", f);
      fd.append("colecao", colecao);
      const r = await acApi("", { method: "POST", body: fd });
      linha.replaceChildren(`✅ ${f.name} → `, el("b", {}, r.doc), el("span", { class: "meta" }, ` · ${r.secoes} seção(ões) · ${Math.round(r.chars / 1000)} mil caracteres`));
    } catch (e) {
      linha.replaceChildren(`❌ ${f.name}: ${e.message}`);
      linha.classList.add("erro");
    }
  }
  await acCarregar();
}

let acTimer;
async function acBuscar(q) {
  if (!q.trim()) { $("#ac-trechos").replaceChildren(); return; }
  const { trechos } = await acApi(`/busca?q=${encodeURIComponent(q)}`);
  $("#ac-trechos").replaceChildren(...(trechos.length ? trechos.map((t) => el("div", { class: "ac-trecho" },
    el("div", {}, el("b", {}, [t.disciplina, t.titulo].filter(Boolean).join(" · ")), el("span", { class: "meta" }, ` › ${t.caminho}`)),
    el("div", { class: "meta" }, t.trecho))) : [el("p", { class: "meta" }, "nada encontrado")]));
}

window.acervoAbrir = async () => {
  if (!AC.iniciado) {
    AC.iniciado = true;
    const drop = $("#ac-drop"), entrada = $("#ac-arq");
    drop.addEventListener("click", () => entrada.click());
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") entrada.click(); });
    entrada.addEventListener("change", () => { acEnviar([...entrada.files]); entrada.value = ""; });
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("sobre"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("sobre"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("sobre"); acEnviar([...e.dataTransfer.files]); });
    $("#ac-busca").addEventListener("input", (e) => { clearTimeout(acTimer); acTimer = setTimeout(() => acBuscar(e.target.value).catch((x) => aviso(x.message, true)), 300); });
  }
  try { await acCarregar(); } catch (e) { aviso(`Acervo: ${e.message}`, true); }
};
