// OkapiAI — interface web (vanilla JS)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  token: localGet("okapi_token"),
  user: JSON.parse(localGet("okapi_user") || "null"),
  langs: [],
  minSimilar: 10,
};

function localGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} }
const langName = (c) => state.langs.find((l) => l.code === c)?.name || c;
const withToken = (url) => (url && state.token ? `${url}?token=${encodeURIComponent(state.token)}` : url);

async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const res = await fetch(path, { method, headers, body });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (res.status === 401 && state.token) { setSession(null); }
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg).join(", ") : d || `Erreur ${res.status}`);
  }
  return data;
}

// ---------- Session ----------
function setSession(data) {
  state.token = data?.token || null;
  state.user = data?.user || null;
  localSet("okapi_token", state.token);
  localSet("okapi_user", state.user ? JSON.stringify(state.user) : null);
  renderAccount();
}

function renderAccount() {
  const el = $("#account");
  if (state.user) {
    el.innerHTML = `<span class="muted">Connecté : <b>${esc(state.user.username)}</b>${state.user.is_admin ? " (admin)" : ""}</span>
      <button class="secondary" id="logout">Déconnexion</button>`;
    $("#logout").onclick = () => setSession(null);
  } else {
    el.innerHTML = `<button id="login-btn">Se connecter</button>`;
    $("#login-btn").onclick = openLogin;
  }
  if (!state.user?.is_admin && $("#tab-admin")?.classList.contains("active")) {
    $('nav [data-tab="chat"]').click();  // plus admin : on quitte le panneau
  }
  $("#admin-tab").hidden = !state.user?.is_admin;
}

function openLogin() { $("#login-msg").textContent = ""; $("#login-dialog").showModal(); }
function requireLogin() {
  if (state.user) return true;
  openLogin();
  return false;
}

$("#login-form").addEventListener("submit", async (e) => {
  const action = e.submitter?.value;
  if (action === "cancel") return;
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const data = await api(`/api/auth/${action === "register" ? "register" : "login"}`,
      { method: "POST", json: { username: f.get("username"), password: f.get("password") } });
    const fromAdmin = onAdminUrl();
    setSession(data);
    $("#login-dialog").close();
    e.target.reset();
    if (fromAdmin) {
      if (state.user?.is_admin) $("#admin-tab").click();
      else alert(`Le compte « ${state.user.username} » n'est pas administrateur : le panneau admin lui est fermé.`);
    }
  } catch (err) { $("#login-msg").textContent = err.message; $("#login-msg").className = "msg err"; }
});

// ---------- Onglets ----------
const tabLoaders = {};
$$("nav button").forEach((b) => b.addEventListener("click", () => {
  $$("nav button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
  // l'adresse suit l'onglet : /admin pour le panneau admin, / pour le reste
  const path = b.dataset.tab === "admin" ? "/admin" : "/";
  if (location.pathname !== path) history.replaceState(null, "", path);
  tabLoaders[b.dataset.tab]?.();
}));

// ---------- Lien direct /admin ----------
const onAdminUrl = () => location.pathname.replace(/\/+$/, "") === "/admin";
function openAdminFromUrl() {
  if (state.user?.is_admin) { $("#admin-tab").click(); return; }
  // pas (encore) admin : on montre le panneau verrouillé et on propose la connexion
  $$("nav button").forEach((x) => x.classList.remove("active"));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-admin"));
  loadAdmin();
  openLogin();
  $("#login-msg").textContent = state.user
    ? `Le compte « ${state.user.username} » n'est pas administrateur. Connectez-vous avec un compte admin.`
    : "Connectez-vous avec un compte administrateur pour accéder au panneau.";
  $("#login-msg").className = "msg";
}

function fillLangSelects() {
  const opts = (filter) => state.langs.filter(filter).map((l) => `<option value="${l.code}">${esc(l.name)}</option>`).join("");
  const all = opts(() => true);
  const congo = opts((l) => l.code !== "fr");
  $$("select.lang").forEach((s) => (s.innerHTML = all));
  $("#learn-lang").innerHTML = congo;
  $("#prop-filter").innerHTML += congo;
  // valeurs par défaut : langue congolaise -> français
  for (const [src, tgt] of [["#chat-src", "#chat-tgt"], ["#voice-src", "#voice-tgt"]]) { $(src).value = "ln"; $(tgt).value = "fr"; }
  $("#contrib-form [name=source_lang]").value = "ln";
  $("#contrib-form [name=target_lang]").value = "fr";
}

// ---------- Enregistreur audio ----------
function makeRecorder() {
  let rec, chunks = [], stream;
  return {
    get active() { return rec?.state === "recording"; },
    async start() {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = ["audio/webm", "audio/ogg", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported?.(t));
      rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.start();
    },
    stop() {
      return new Promise((resolve) => {
        rec.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type: (rec.mimeType || "audio/webm").split(";")[0] }));
        };
        rec.stop();
      });
    },
  };
}
const extFor = (blob) => ({ "audio/ogg": "ogg", "audio/mp4": "m4a" }[blob.type] || "webm");

function bubble(log, who, html) {
  const div = document.createElement("div");
  div.className = `bubble ${who}`;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

function speak(text, lang) {
  // Les navigateurs n'ont des voix que pour le français / swahili (selon l'appareil)
  if (!("speechSynthesis" in window) || !["fr", "sw"].includes(lang)) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang === "fr" ? "fr-FR" : "sw-KE";
  speechSynthesis.speak(u);
}

function translationHtml(r) {
  if (!r?.translation) return "";
  const meta = { dataset: "dataset validé", modele: "modèle IA", mot_a_mot: "mot à mot (partiel)" }[r.method] || "";
  return `<div class="meta">${esc(meta)}${r.confidence ? ` · ${Math.round(r.confidence * 100)}%` : ""}</div>
    ${r.audio_url ? `<audio controls src="${esc(r.audio_url)}"></audio>` : ""}`;
}

// ---------- Modes (Converser / Traduire) ----------
const modes = {};
const modeOf = (name) => modes[name];
function setupModes() {
  $$(".modes[data-modes]").forEach((group) => {
    const name = group.dataset.modes;
    const scope = group.closest(".card") || group.closest(".tab");
    const apply = (mode) => {
      modes[name] = mode;
      scope.dataset.modeScope = mode;
      $$("button", group).forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
      group.dispatchEvent(new CustomEvent("modechange", { detail: mode }));
    };
    $$("button", group).forEach((b) => (b.onclick = () => apply(b.dataset.mode)));
    apply($("button.active", group)?.dataset.mode || $("button", group).dataset.mode);
  });
}

// Une conversation se fait dans une langue congolaise
function ensureCongolese(select) { if (select.value === "fr") select.value = "ln"; }

// ---------- Conversation ----------
const convHistory = { chat: [], voice: [] };

function renderAnswer(log, lang, userMsg, a, key) {
  const label = { dataset: "✅ réponse validée par la communauté", ia: "🤖 réponse IA" }[a.method] || "";
  let html = a.reply
    ? `<div class="reply">${esc(a.reply)}</div>
       ${a.reply_fr ? `<details class="fr"><summary>🇫🇷 En français</summary>${esc(a.reply_fr)}</details>` : ""}
       ${a.audio_url ? `<audio controls src="${esc(a.audio_url)}"></audio>` : ""}
       <div class="meta">${label}${a.method === "ia" && a.hint ? ` · ${esc(a.hint)}` : ""}</div>`
    : `<div>🤔 ${esc(a.hint || "Je ne sais pas encore répondre.")}</div>`;
  html += `<div class="actions"><button type="button" class="secondary b-teach">${a.reply ? "✏️ Corriger" : "🧑‍🏫 Apprendre une réponse"}</button></div>`;
  const b = bubble(log, "bot", html);
  $(".b-teach", b).onclick = () => showTeach(b, lang, userMsg, a.reply);
  if (a.reply) {
    convHistory[key].push({ role: "user", text: userMsg }, { role: "assistant", text: a.reply });
    convHistory[key] = convHistory[key].slice(-20);
    if (!a.audio_url) speak(a.reply, lang);
  }
}

function showTeach(b, lang, msg, current) {
  if ($(".teach", b)) return;
  const form = document.createElement("form");
  form.className = "teach";
  form.innerHTML = `<input placeholder="La bonne réponse en ${esc(langName(lang))}" value="${esc(current || "")}" required>
    <button>Envoyer</button>`;
  b.appendChild(form);
  $("input", form).focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (!requireLogin()) return;
    const reply = $("input", form).value.trim();
    if (!reply) return;
    try {
      const r = await api("/api/contributions/text", { method: "POST",
        json: { kind: "dialogue", source_lang: lang, source_text: msg, target_lang: lang, target_text: reply } });
      form.outerHTML = `<div class="meta">✅ ${esc(r.message)}</div>`;
    } catch (err) { alert(err.message); }
  };
}

async function sendConverse(log, lang, text, key) {
  try {
    const a = await api("/api/converse", { method: "POST", json: { lang, message: text, history: convHistory[key] } });
    renderAnswer(log, lang, text, a, key);
  } catch (err) { bubble(log, "bot", `⚠️ ${esc(err.message)}`); }
}

// ---------- Chat ----------
$("#chat-swap").onclick = () => { const a = $("#chat-src").value; $("#chat-src").value = $("#chat-tgt").value; $("#chat-tgt").value = a; };
$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#chat-input").value.trim();
  if (!text) return;
  const log = $("#chat-log");
  bubble(log, "me", esc(text));
  $("#chat-input").value = "";
  if (modeOf("chat") === "converse") return sendConverse(log, $("#chat-src").value, text, "chat");
  try {
    const r = await api("/api/chat", { method: "POST",
      json: { text, source_lang: $("#chat-src").value, target_lang: $("#chat-tgt").value } });
    bubble(log, "bot", esc(r.reply) + translationHtml(r));
    if (r.translation) speak(r.translation, r.target_lang);
  } catch (err) { bubble(log, "bot", `⚠️ ${esc(err.message)}`); }
});
bubble($("#chat-log"), "bot", "Mbote ! Jambo ! Choisissez une langue et parlez-moi : je vous réponds dans la même langue. Le mode « Traduire » traduit vos phrases.");

// ---------- Voix live ----------
const voiceRec = makeRecorder();
function updateVoiceHint() {
  const l = state.langs.find((x) => x.code === $("#voice-src").value);
  $("#voice-hint").textContent = l?.asr
    ? "Parlez, puis appuyez de nouveau pour arrêter : votre voix sera transcrite et traduite."
    : `La reconnaissance automatique n'est pas encore disponible pour le ${l?.name || "cette langue"} : après l'enregistrement, tapez ce que vous avez dit. Vos enregistrements aideront à entraîner ce modèle !`;
}
$("#voice-src").addEventListener("change", updateVoiceHint);

$("#rec-btn").onclick = async () => {
  const btn = $("#rec-btn");
  if (!voiceRec.active) {
    try { await voiceRec.start(); } catch { alert("Micro inaccessible. Autorisez l'accès au micro."); return; }
    btn.classList.add("recording"); btn.innerHTML = "⏹️<br>Arrêter";
    return;
  }
  btn.classList.remove("recording"); btn.innerHTML = "🎙️<br>Appuyer pour parler";
  const blob = await voiceRec.stop();
  const src = $("#voice-src").value, tgt = $("#voice-tgt").value;
  const log = $("#voice-log");
  const me = bubble(log, "me", `<audio controls src="${URL.createObjectURL(blob)}"></audio><div class="meta">Transcription…</div>`);
  const form = new FormData();
  form.append("audio", blob, `voix.${extFor(blob)}`);
  if (modeOf("voice") === "converse") {
    form.append("lang", src);
    form.append("history", JSON.stringify(convHistory.voice));
    try { renderVoiceConverse(me, await api("/api/voice/converse", { method: "POST", form }), src); }
    catch (err) { $(".meta", me).textContent = `⚠️ ${err.message}`; }
    return;
  }
  form.append("source_lang", src); form.append("target_lang", tgt);
  try {
    const r = await api("/api/voice/chat", { method: "POST", form });
    renderVoiceTurn(me, r, src, tgt);
  } catch (err) { $(".meta", me).textContent = `⚠️ ${err.message}`; }
};

function renderVoiceConverse(me, r, lang) {
  $(".meta", me).remove();
  const box = document.createElement("form");
  box.innerHTML = `<input class="vt-src" placeholder="Ce que vous avez dit (${esc(langName(lang))})" value="${esc(r.transcript || "")}">
    <div class="row" style="margin-top:6px"><button type="submit" class="secondary">${r.answer ? "Renvoyer corrigé" : "Envoyer"}</button></div>`;
  me.appendChild(box);
  if (r.answer) renderAnswer($("#voice-log"), lang, r.transcript, r.answer, "voice");
  else $(".vt-src", box).focus();
  box.onsubmit = (e) => {
    e.preventDefault();
    const text = $(".vt-src", box).value.trim();
    if (text) sendConverse($("#voice-log"), lang, text, "voice");
  };
}

function renderVoiceTurn(me, r, src, tgt) {
  $(".meta", me).remove();
  const box = document.createElement("div");
  box.innerHTML = `
    <input class="vt-src" placeholder="Ce que vous avez dit (${esc(langName(src))})" value="${esc(r.transcript || "")}">
    <input class="vt-tgt" placeholder="Traduction (${esc(langName(tgt))})" value="${esc(r.translation?.translation || "")}" style="margin-top:6px">
    <div class="row" style="margin-top:6px">
      <button class="secondary vt-translate" type="button">Traduire</button>
      <button class="rec-small vt-save" type="button">💾 Ajouter au dataset</button>
    </div><div class="meta vt-msg"></div>`;
  me.appendChild(box);
  if (r.translation?.translation) {
    bubble($("#voice-log"), "bot", esc(r.translation.translation) + translationHtml(r.translation));
    speak(r.translation.translation, tgt);
  }
  $(".vt-translate", box).onclick = async () => {
    const text = $(".vt-src", box).value.trim();
    if (!text) return;
    const t = await api("/api/chat", { method: "POST", json: { text, source_lang: src, target_lang: tgt } });
    if (t.translation) $(".vt-tgt", box).value = t.translation;
    bubble($("#voice-log"), "bot", esc(t.reply) + translationHtml(t));
  };
  $(".vt-save", box).onclick = async () => {
    if (!requireLogin()) return;
    const msg = $(".vt-msg", box);
    const form = new FormData();
    form.append("audio_file", r.audio_file);
    form.append("source_lang", src); form.append("source_text", $(".vt-src", box).value.trim());
    form.append("target_lang", tgt); form.append("target_text", $(".vt-tgt", box).value.trim());
    try {
      const res = await api("/api/contributions/voice", { method: "POST", form });
      msg.textContent = `✅ ${res.message}`;
      $(".vt-save", box).disabled = true;
    } catch (err) { msg.textContent = `⚠️ ${err.message}`; }
  };
}

// ---------- Contribuer ----------
function setupInlineRecorder(container) {
  const rec = makeRecorder();
  const btn = $("button", container), player = $("audio", container);
  container.blob = null;
  btn.onclick = async () => {
    if (!rec.active) {
      try { await rec.start(); } catch { alert("Micro inaccessible."); return; }
      btn.classList.add("recording"); btn.textContent = "⏹️ Arrêter l'enregistrement";
    } else {
      container.blob = await rec.stop();
      btn.classList.remove("recording"); btn.textContent = "🎙️ Réenregistrer";
      player.src = URL.createObjectURL(container.blob); player.hidden = false;
    }
  };
  container.reset = () => { container.blob = null; player.hidden = true; btn.textContent = "🎙️ Enregistrer ma voix (optionnel)"; };
}
setupInlineRecorder($("[data-recorder=contrib]"));

$("#contrib-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!requireLogin()) return;
  const f = new FormData(e.target), msg = $("#contrib-msg");
  const recBox = $("[data-recorder=contrib]");
  if (modeOf("contrib") === "converse") {
    f.set("kind", "dialogue");
    f.set("target_lang", f.get("source_lang"));
  } else f.set("kind", "traduction");
  try {
    let res;
    if (recBox.blob) {
      f.append("audio", recBox.blob, `voix.${extFor(recBox.blob)}`);
      res = await api("/api/contributions/voice", { method: "POST", form: f });
    } else {
      res = await api("/api/contributions/text", { method: "POST", json: Object.fromEntries(f) });
    }
    msg.textContent = `✅ ${res.message}`; msg.className = "msg ok";
    $("[name=source_text]", e.target).value = ""; $("[name=target_text]", e.target).value = "";
    recBox.reset();
    loadProposals(); loadMine();
  } catch (err) { msg.textContent = err.message; msg.className = "msg err"; }
});

const progress = (n, req) => `<div class="progress" title="${n}/${req}"><div style="width:${Math.min(100, (n / req) * 100)}%"></div></div>`;

async function loadProposals() {
  const lang = $("#prop-filter").value;
  const list = await api(`/api/contributions/proposals${lang ? `?lang=${lang}` : ""}`);
  $("#proposals").innerHTML = list.length ? list.map((p) => `
    <div class="item">
      <div>${p.kind === "dialogue" ? `<span class="tag">💬 dialogue · ${esc(langName(p.source_lang))}</span><br>
        « ${esc(p.source_text)} »<br>→ réponse : <b>${esc(p.target_text)}</b>`
        : `<b>${esc(p.source_text)}</b> <span class="tag">${esc(langName(p.source_lang))}</span><br>
        → ${esc(p.target_text)} <span class="tag">${esc(langName(p.target_lang))}</span>`}</div>
      <div class="row" style="align-items:center">${progress(p.support, p.required)}
        <span class="muted">${p.support}/${p.required}</span>
        <button data-confirm="${p.id}">👍 Je confirme</button></div>
    </div>`).join("") : `<p class="muted">Aucune proposition en cours.</p>`;
  $$("[data-confirm]").forEach((b) => (b.onclick = async () => {
    if (!requireLogin()) return;
    try { const r = await api(`/api/contributions/proposals/${b.dataset.confirm}/confirm`, { method: "POST", form: new FormData() });
      b.textContent = "✅"; b.disabled = true; b.title = r.message; setTimeout(loadProposals, 800);
    } catch (err) { alert(err.message); }
  }));
}
$("#prop-filter").addEventListener("change", loadProposals);

const statusLabel = { collecte: "En collecte", en_attente_admin: "En attente admin", approuve: "Approuvée ✅", rejete: "Rejetée" };
async function loadMine() {
  if (!state.user) { $("#mine").innerHTML = `<p class="muted">Connectez-vous pour voir vos contributions.</p>`; return; }
  const list = await api("/api/contributions/mine");
  $("#mine").innerHTML = list.length ? list.map((c) => `
    <div class="item"><div>${c.type === "dialogue" ? "💬 " : ""}${c.kind === "voix" ? "🎙️ " : ""}<b>${esc(c.source_text)}</b> → ${esc(c.target_text)}
      ${c.audio_url ? `<audio controls src="${esc(withToken(c.audio_url))}"></audio>` : ""}</div>
      <div class="row" style="align-items:center"><span class="tag">${esc(statusLabel[c.status] || c.status)}</span>
      ${c.status === "collecte" ? `${progress(c.support, c.required)}<span class="muted">${c.support}/${c.required}</span>` : ""}</div></div>`).join("")
    : `<p class="muted">Vous n'avez encore rien envoyé.</p>`;
}
tabLoaders.contribute = () => { loadProposals(); loadMine(); };

// ---------- Apprendre ----------
async function showCards() {
  const area = $("#learn-area"), lang = $("#learn-lang").value;
  const cards = await api(`/api/learn/cards?lang=${lang}&limit=20`);
  if (!cards.length) { area.innerHTML = `<p class="muted">Pas encore de données validées en ${esc(langName(lang))}. Contribuez pour enrichir le dataset !</p>`; return; }
  let i = 0;
  const render = () => {
    const c = cards[i];
    area.innerHTML = `<div class="flash">
      <div class="muted">${i + 1} / ${cards.length} · ${esc(langName(c.lang))}</div>
      <div class="word">${esc(c.text)}</div>
      ${c.audio_url ? `<audio controls src="${esc(c.audio_url)}"></audio>` : ""}
      <div class="meaning" id="meaning"></div>
      <div class="row" style="justify-content:center">
        <button class="secondary" id="prev">◀</button>
        <button id="reveal">Voir la traduction</button>
        <button class="secondary" id="next">▶</button></div></div>`;
    $("#reveal").onclick = () => { $("#meaning").textContent = `${c.meaning} (${langName(c.meaning_lang)})`; speak(c.meaning, c.meaning_lang); };
    $("#prev").onclick = () => { i = (i - 1 + cards.length) % cards.length; render(); };
    $("#next").onclick = () => { i = (i + 1) % cards.length; render(); };
  };
  render();
}

let quizScore = { ok: 0, total: 0 };
async function showQuiz() {
  const area = $("#learn-area"), lang = $("#learn-lang").value;
  let q;
  try { q = await api(`/api/learn/quiz?lang=${lang}`); }
  catch (err) { area.innerHTML = `<p class="muted">${esc(err.message)}</p>`; return; }
  area.innerHTML = `<div class="flash">
    <div class="muted">Score : ${quizScore.ok} / ${quizScore.total}</div>
    <div class="muted">Que signifie :</div><div class="word">${esc(q.question)}</div>
    ${q.audio_url ? `<audio controls src="${esc(q.audio_url)}"></audio>` : ""}
    <div class="choices">${q.choices.map((c) => `<button data-c="${esc(c)}">${esc(c)}</button>`).join("")}</div>
    <button id="next-q" style="margin-top:12px" hidden>Question suivante</button></div>`;
  $$("[data-c]", area).forEach((b) => (b.onclick = () => {
    quizScore.total++;
    if (b.dataset.c === q.answer) { quizScore.ok++; b.classList.add("good"); }
    else { b.classList.add("bad"); $$("[data-c]", area).find((x) => x.dataset.c === q.answer)?.classList.add("good"); }
    $$("[data-c]", area).forEach((x) => (x.disabled = true));
    $("#next-q").hidden = false;
  }));
  $("#next-q").onclick = showQuiz;
}
$("#learn-cards-btn").onclick = showCards;
$("#learn-quiz-btn").onclick = showQuiz;
$("#learn-lang").addEventListener("change", showCards);
tabLoaders.learn = showCards;

// ---------- Admin ----------
const EMPTY_ADMIN = {
  en_attente_admin: (s) => `Aucune proposition n'attend votre validation.<br>
    Une proposition arrive ici quand <b>${s.min_similar} personnes différentes</b> ont envoyé une traduction ou un dialogue similaire.
    ${s.propositions.collecte ? `<br>${s.propositions.collecte} proposition(s) sont en cours de collecte : choisissez « En collecte » pour les voir.`
      : "<br>Aucune contribution pour l'instant : commencez par l'onglet « Contribuer »."}`,
  collecte: () => "Aucune proposition en cours de collecte.",
  approuve: () => "Aucune proposition approuvée pour l'instant.",
  rejete: () => "Aucune proposition rejetée.",
};

async function loadAdmin() {
  if (!state.user?.is_admin) {
    $("#admin-stats").innerHTML = "";
    $("#admin-list").innerHTML = `<div class="card"><p>🔒 Connectez-vous avec un compte administrateur pour accéder à ce panneau.</p></div>`;
    return;
  }
  $("#admin-list").innerHTML = `<p class="muted">Chargement…</p>`;
  try {
    await renderAdmin();
  } catch (err) {
    $("#admin-list").innerHTML = `<div class="card"><p class="msg err">⚠️ Impossible de charger le panneau admin : ${esc(err.message)}</p>
      <button type="button" class="secondary" id="admin-retry">Réessayer</button></div>`;
    $("#admin-retry").onclick = loadAdmin;
  }
}

async function renderAdmin() {
  const s = await api("/api/admin/stats");
  const P = s.propositions;
  $("#admin-stats").innerHTML = [
    ["Utilisateurs", s.users], ["Dataset collecte", s.dataset_collecte], ["dont voix", s.contributions_voix],
    ["Dataset entraînement", s.dataset_entrainement], ["En attente", P.en_attente_admin], ["En collecte", P.collecte],
  ].map(([k, v]) => `<div class="stat"><b>${v}</b><span class="muted">${k}</span></div>`).join("");

  const status = $("#admin-status").value;
  const list = await api(`/api/admin/propositions?status=${status}`);
  const pending = status === "en_attente_admin";
  $("#admin-list").innerHTML = list.length ? list.map((p) => `
    <div class="card" data-pid="${p.id}">
      <div class="row" style="justify-content:space-between"><b>#${p.id} · ${p.kind === "dialogue"
          ? `💬 Dialogue en ${esc(langName(p.source_lang))} (message → réponse)`
          : `${esc(langName(p.source_lang))} → ${esc(langName(p.target_lang))}`}</b>
        <span class="tag">${p.support}/${p.required} contributeurs</span></div>
      ${pending ? `<div class="admin-edit">
          <input class="a-src" value="${esc(p.source_text)}"><input class="a-tgt" value="${esc(p.target_text)}"></div>`
        : `<p><b>${esc(p.source_text)}</b> → ${esc(p.target_text)}</p>`}
      <div class="variants">Variantes : ${p.variants.map((v) => `« ${esc(v.source_text)} » → « ${esc(v.target_text)} » (×${v.count})`).join(" · ")}</div>
      ${p.audios.map((a) => `<div class="muted">🎙️ ${esc(a.user)} <audio controls preload="none" src="${esc(withToken(a.url))}"></audio></div>`).join("")}
      ${pending ? `<div class="row" style="margin-top:8px"><button data-act="approve">✅ Approuver → dataset d'entraînement</button>
        <button class="danger" data-act="reject">✖ Rejeter</button></div>` : ""}
    </div>`).join("") : `<div class="card"><p class="muted">${EMPTY_ADMIN[status]?.(s) || "Rien à afficher."}</p></div>`;

  $$("#admin-list [data-act]").forEach((b) => (b.onclick = async () => {
    const card = b.closest("[data-pid]");
    let json;
    if (b.dataset.act === "approve") {
      json = { source_text: $(".a-src", card).value.trim(), target_text: $(".a-tgt", card).value.trim() };
      if (!json.source_text || !json.target_text) return alert("Les deux textes sont obligatoires.");
    } else {
      const note = prompt("Raison du rejet (optionnel) :", "");
      if (note === null) return;  // « Annuler » : on ne rejette pas
      json = { note: note.trim() || null };
    }
    $$("button", card).forEach((x) => (x.disabled = true));
    try { await api(`/api/admin/propositions/${card.dataset.pid}/${b.dataset.act}`, { method: "POST", json }); }
    catch (err) { alert(err.message); }
    loadAdmin();
  }));
}
$("#admin-status").addEventListener("change", loadAdmin);
$("#admin-export").onclick = async () => {
  const res = await fetch("/api/admin/export/entrainement.jsonl", { headers: { Authorization: `Bearer ${state.token}` } });
  if (!res.ok) return alert(`Export impossible (erreur ${res.status}). Reconnectez-vous puis réessayez.`);
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await res.blob()), download: "okapi_entrainement.jsonl" });
  a.click();
};
tabLoaders.admin = loadAdmin;

// ---------- Démarrage ----------
(async function init() {
  renderAccount();
  state.langs = await api("/api/languages");
  fillLangSelects();
  setupModes();
  $('[data-modes="chat"]').addEventListener("modechange", (e) => e.detail === "converse" && ensureCongolese($("#chat-src")));
  $('[data-modes="voice"]').addEventListener("modechange", (e) => e.detail === "converse" && ensureCongolese($("#voice-src")));
  $('[data-modes="contrib"]').addEventListener("modechange", (e) => {
    if (e.detail === "converse") ensureCongolese($("#contrib-form [name=source_lang]"));
    const btn = $("[data-recorder=contrib] button");
    if (!btn.classList.contains("recording")) btn.textContent = e.detail === "converse"
      ? "🎙️ Enregistrer la réponse à voix haute (optionnel)" : "🎙️ Enregistrer ma voix (optionnel)";
  });
  for (const sel of ["#chat-src", "#voice-src"]) $(sel).addEventListener("change", (e) => {
    const key = sel === "#chat-src" ? "chat" : "voice";
    convHistory[key] = [];  // nouvelle langue = nouvelle conversation
    if (modeOf(key) === "converse") ensureCongolese(e.target);
  });
  api("/api/features").then((f) => {
    $("#ai-badge").textContent = f.ai_conversation ? "🤖 IA active" : "📚 Réponses du dataset uniquement";
    $("#ai-badge").title = f.ai_conversation ? "" : "Activez l'IA côté serveur (clé ANTHROPIC_API_KEY) pour converser librement";
  }).catch(() => {});
  updateVoiceHint();
  const afterSession = () => { if (onAdminUrl()) openAdminFromUrl(); };
  if (state.token) {
    api("/api/auth/me").then((u) => setSession({ token: state.token, user: u })).catch(() => {}).finally(afterSession);
  } else afterSession();
})();
