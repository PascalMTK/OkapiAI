// OkapiAI — logique de l'interface, reliée à l'API (backend FastAPI)
// Le visuel (Tailwind) est défini dans index.html ; ce fichier remplit la page avec les vraies données.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icons = () => window.lucide?.createIcons();

function localGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} }

const state = {
  token: localGet("okapi_token"),
  user: JSON.parse(localGet("okapi_user") || "null"),
  langs: [],
  features: { ai_conversation: false, speech_recognition: [] },
  minSimilar: 10,
  modes: {},
};
const langName = (c) => state.langs.find((l) => l.code === c)?.name || c;
const isCongolese = (c) => c && c !== "fr";
const withToken = (url) => (url && state.token ? `${url}?token=${encodeURIComponent(state.token)}` : url);

// ---------- API ----------
async function api(path, { method = "GET", json, form } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const res = await fetch(path, { method, headers, body });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (res.status === 401 && state.token) setSession(null);
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg).join(", ") : d || `Erreur ${res.status}`);
  }
  return data;
}

// ---------- Notifications ----------
function showToast(message, type = "info") {
  const colors = {
    success: "border-emerald-300 dark:border-emerald-500/40 bg-emerald-50/95 dark:bg-emerald-950/95 text-emerald-900 dark:text-emerald-200",
    info: "border-blue-300 dark:border-okapi-blue/50 bg-white/95 dark:bg-obsidian-900/95 text-slate-800 dark:text-slate-100",
    error: "border-rose-300 dark:border-okapi-red/50 bg-rose-50/95 dark:bg-rose-950/95 text-rose-900 dark:text-rose-200",
  };
  const icon = { success: "check-circle-2", info: "sparkles", error: "alert-circle" }[type] || "sparkles";
  const toast = document.createElement("div");
  toast.className = `pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-xl text-xs sm:text-sm font-semibold transition-all duration-300 translate-y-2 opacity-0 ${colors[type] || colors.info}`;
  toast.innerHTML = `<i data-lucide="${icon}" class="w-4 h-4 flex-shrink-0 text-okapi-blue dark:text-okapi-cyan"></i><span>${esc(message)}</span>`;
  $("#toast-container").appendChild(toast);
  icons();
  requestAnimationFrame(() => toast.classList.remove("translate-y-2", "opacity-0"));
  setTimeout(() => { toast.classList.add("opacity-0", "translate-y-2"); setTimeout(() => toast.remove(), 300); }, 4000);
}

// ---------- Thème clair / sombre (mémorisé) ----------
function applyTheme(dark) {
  document.documentElement.classList.toggle("dark", dark);
  $("#theme-icon-moon").classList.toggle("hidden", dark);
  $("#theme-icon-sun").classList.toggle("hidden", !dark);
}
function initTheme() {
  applyTheme(localGet("okapi_theme") === "dark");
  $("#theme-toggle").addEventListener("click", () => {
    const dark = !document.documentElement.classList.contains("dark");
    applyTheme(dark);
    localSet("okapi_theme", dark ? "dark" : "light");
  });
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
    el.innerHTML = `
      <div class="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-blue-50 dark:bg-okapi-blue/10 border border-blue-200 dark:border-okapi-blue/25 text-xs">
        <span class="w-2 h-2 rounded-full bg-amber-500 dark:bg-okapi-yellow"></span>
        <span class="font-bold text-slate-800 dark:text-slate-200">${esc(state.user.username)}</span>
        ${state.user.is_admin ? `<span class="text-amber-600 dark:text-okapi-yellow font-extrabold ml-1">admin</span>` : ""}
      </div>
      <button id="logout" type="button" class="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-blue-50 hover:bg-blue-100 dark:bg-okapi-blue/15 dark:hover:bg-okapi-blue/25 border border-blue-200 dark:border-okapi-blue/30 text-xs sm:text-sm font-bold text-blue-800 dark:text-slate-100 transition-colors cursor-pointer">
        <i data-lucide="log-out" class="w-4 h-4 text-okapi-blue dark:text-okapi-cyan"></i><span>Déconnexion</span>
      </button>`;
    $("#logout").onclick = () => { setSession(null); showToast("Vous êtes déconnecté.", "info"); };
  } else {
    el.innerHTML = `
      <button id="login-btn" type="button" class="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-okapi-blue to-blue-600 text-white text-xs sm:text-sm font-bold shadow-md shadow-okapi-blue/25 transition-all cursor-pointer">
        <i data-lucide="log-in" class="w-4 h-4"></i><span>Connexion</span>
      </button>`;
    $("#login-btn").onclick = () => openLogin();
  }
  icons();
  const isAdmin = !!state.user?.is_admin;
  $("#admin-tab").classList.toggle("hidden", !isAdmin);
  if (!isAdmin && !$("#tab-admin").classList.contains("hidden") && !onAdminUrl()) activateTab("chat");
}

function openLogin(message = "", isError = false) {
  const msg = $("#login-msg");
  msg.textContent = message;
  msg.className = `text-xs min-h-[16px] ${isError ? "text-okapi-red" : "text-blue-700 dark:text-okapi-cyan"}`;
  if (!$("#login-dialog").open) $("#login-dialog").showModal();
}
function requireLogin() {
  if (state.user) return true;
  openLogin("Connectez-vous (ou créez un compte) pour contribuer.");
  return false;
}

function initLoginDialog() {
  const dialog = $("#login-dialog");
  $("#close-login-btn").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const action = e.submitter?.dataset.action === "register" ? "register" : "login";
    const f = new FormData(e.target);
    const fromAdmin = onAdminUrl();
    try {
      const data = await api(`/api/auth/${action}`, { method: "POST",
        json: { username: String(f.get("username")).trim(), password: f.get("password") } });
      setSession(data);
      dialog.close();
      e.target.reset();
      showToast(action === "register" ? `Bienvenue sur OkapiAI, ${data.user.username} !` : `Bon retour, ${data.user.username} !`, "success");
      if (fromAdmin) {
        if (state.user.is_admin) activateTab("admin");
        else showToast(`Le compte « ${state.user.username} » n'est pas administrateur.`, "error");
      }
      refreshCurrentTab();
    } catch (err) { openLogin(err.message, true); }
  });
}

// ---------- Navigation ----------
const tabLoaders = {};
function activateTab(tab) {
  $$(".nav-btn").forEach((btn) => {
    const on = btn.dataset.tab === tab;
    btn.classList.toggle("active", on);
    ["bg-blue-100/80", "dark:bg-okapi-blue/20", "text-blue-700", "dark:text-okapi-cyan", "border", "border-blue-300", "dark:border-okapi-blue/40", "shadow-2xs"]
      .forEach((c) => btn.classList.toggle(c, on));
    ["text-slate-600", "dark:text-slate-400", "hover:text-slate-900", "dark:hover:text-slate-200", "hover:bg-slate-100", "dark:hover:bg-white/5"]
      .forEach((c) => btn.classList.toggle(c, !on));
  });
  $$(".tab-section").forEach((sec) => sec.classList.toggle("hidden", sec.id !== `tab-${tab}`));
  const path = tab === "admin" ? "/admin" : "/";
  if (location.pathname !== path) history.replaceState(null, "", path);
  tabLoaders[tab]?.();
}
function refreshCurrentTab() {
  const current = $$(".tab-section").find((s) => !s.classList.contains("hidden"))?.id.replace("tab-", "");
  if (current) tabLoaders[current]?.();
}
function initNavigation() {
  $$(".nav-btn").forEach((btn) => btn.addEventListener("click", () => activateTab(btn.dataset.tab)));
}

// ---------- Lien direct /admin ----------
const onAdminUrl = () => location.pathname.replace(/\/+$/, "") === "/admin";
function openAdminFromUrl() {
  if (state.user?.is_admin) return activateTab("admin");
  $$(".tab-section").forEach((sec) => sec.classList.toggle("hidden", sec.id !== "tab-admin"));
  loadAdmin();
  openLogin(state.user
    ? `Le compte « ${state.user.username} » n'est pas administrateur. Connectez-vous avec un compte admin.`
    : "Connectez-vous avec un compte administrateur pour accéder au panneau.");
}

// ---------- Modes (Converser / Traduire) ----------
function initModes() {
  $$("[data-modes]").forEach((group) => {
    const name = group.dataset.modes;
    const scope = group.closest("section");
    const buttons = $$(".mode-btn", group);
    const apply = (mode) => {
      state.modes[name] = mode;
      buttons.forEach((b) => {
        const on = b.dataset.mode === mode;
        ["bg-gradient-to-r", "from-okapi-blue", "to-blue-600", "text-white", "shadow-sm"].forEach((c) => b.classList.toggle(c, on));
        ["text-slate-600", "dark:text-slate-400", "hover:text-slate-900", "dark:hover:text-white"].forEach((c) => b.classList.toggle(c, !on));
      });
      $$(".translate-only", scope).forEach((el) => el.classList.toggle("hidden", mode !== "translate"));
      $$(".converse-only", scope).forEach((el) => el.classList.toggle("hidden", mode !== "converse"));
      group.dispatchEvent(new CustomEvent("modechange", { detail: mode }));
    };
    buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.mode)));
    apply($(".mode-btn.active", group)?.dataset.mode || buttons[0].dataset.mode);
  });
}
const modeOf = (name) => state.modes[name];
function ensureCongolese(select) { if (!isCongolese(select.value)) select.value = "ln"; }

// ---------- Langues ----------
function fillLangSelects() {
  const options = (filter) => state.langs.filter(filter)
    .map((l) => `<option value="${l.code}" class="bg-white dark:bg-obsidian-900 text-slate-900 dark:text-white">${esc(l.name)}</option>`).join("");
  $$(".lang-select").forEach((s) => (s.innerHTML = options(() => true)));
  $("#learn-lang").innerHTML = options((l) => isCongolese(l.code));
  $("#prop-filter").innerHTML = `<option value="">Toutes</option>` + options((l) => isCongolese(l.code));
  $("#chat-src").value = "ln"; $("#chat-tgt").value = "fr";
  $("#voice-src").value = "ln"; $("#voice-tgt").value = "fr";
  $("#contrib-form [name=source_lang]").value = "ln";
  $("#contrib-form [name=target_lang]").value = "fr";
}

// ---------- Bulles de discussion ----------
function appendUser(log, html, meta = "") {
  clearPlaceholder(log);
  const w = document.createElement("div");
  w.className = "flex items-start gap-3.5 justify-end";
  w.innerHTML = `<div class="bg-gradient-to-br from-okapi-blue to-blue-700 text-white font-medium rounded-2xl rounded-tr-sm px-4 py-3 text-sm shadow-md max-w-md">
      <div class="u-body">${html}</div>
      ${meta ? `<span class="u-meta block text-[10px] text-okapi-yellow mt-1 font-bold">${esc(meta)}</span>` : ""}
    </div>`;
  log.appendChild(w);
  log.scrollTop = log.scrollHeight;
  return w;
}

function appendBot(log, html, meta = "") {
  clearPlaceholder(log);
  const w = document.createElement("div");
  w.className = "flex items-start gap-3.5 max-w-2xl";
  w.innerHTML = `<div class="w-9 h-9 rounded-xl bg-gradient-to-br from-okapi-blue to-blue-800 flex items-center justify-center text-okapi-yellow font-display font-bold text-xs flex-shrink-0 shadow-sm">AI</div>
    <div class="b-body min-w-0 bg-white dark:bg-obsidian-800/90 border border-slate-200 dark:border-okapi-blue/20 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-800 dark:text-slate-100 leading-relaxed shadow-sm">
      ${meta ? `<span class="inline-block text-[10px] font-bold uppercase tracking-wider text-blue-700 dark:text-okapi-cyan mb-1">${esc(meta)}</span>` : ""}
      ${html}
    </div>`;
  log.appendChild(w);
  log.scrollTop = log.scrollHeight;
  icons();
  return $(".b-body", w);
}

function clearPlaceholder(log) { $(".log-placeholder", log)?.remove(); $(".border-dashed", log)?.remove(); }

const audioTag = (url) => (url ? `<audio controls preload="none" src="${esc(url)}" class="mt-2 h-8 w-full max-w-xs"></audio>` : "");
const smallBtn = "inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-blue-50 hover:bg-blue-100 dark:bg-okapi-blue/15 dark:hover:bg-okapi-blue/25 text-blue-800 dark:text-okapi-cyan border border-blue-200 dark:border-okapi-blue/30 text-xs font-bold transition-colors cursor-pointer";
const inputCls = "w-full bg-slate-50 dark:bg-obsidian-950 border border-slate-300 dark:border-okapi-blue/25 focus:border-okapi-blue rounded-lg px-3 py-1.5 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none";

// Fait parler OkapiAI. Priorité : enregistrement validé > voix OkapiAI (serveur, langues
// nationales) > voix du navigateur (français / swahili). Résout quand la lecture est finie.
let currentAudio = null;
function stopSpeaking() {
  currentAudio?.pause();
  currentAudio = null;
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}
function playUrl(url) {
  return new Promise((resolve) => {
    stopSpeaking();
    const a = new Audio(url);
    currentAudio = a;
    a.onended = a.onerror = () => resolve();
    a.play().catch(() => resolve());
  });
}
// URL de la voix OkapiAI pour une phrase, si le serveur a une voix dans cette langue
const ttsFor = (text, lang) => (text && state.voiceCaps?.tts?.includes(lang)
  ? `/api/tts?lang=${encodeURIComponent(lang)}&text=${encodeURIComponent(text.slice(0, 600))}` : null);

function speak(text, lang, ttsUrl) {
  if (ttsUrl) return playUrl(ttsUrl);
  return new Promise((resolve) => {
    if (!text || !("speechSynthesis" in window) || !["fr", "sw"].includes(lang)) return resolve();
    stopSpeaking();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === "fr" ? "fr-FR" : "sw-KE";
    u.onend = u.onerror = () => resolve();
    speechSynthesis.speak(u);
  });
}

// Réponse de traduction
function translationMeta(r) {
  const m = { dataset: "Dataset validé", modele: "Modèle IA", mot_a_mot: "Mot à mot (partiel)" }[r.method];
  return m ? `${m}${r.confidence ? ` • ${Math.round(r.confidence * 100)} %` : ""}` : "";
}

// ---------- Conversation ----------
const convHistory = { chat: [], voice: [] };

function renderAnswer(log, lang, userMsg, a, key) {
  const meta = {
    dataset: "Réponse validée par la communauté",
    ia: "Réponse IA — peut contenir des erreurs",
    lexique: "Dictionnaire (Wiktionnaire · Wikipédia)",
    base: "Phrase de base — corrigez-la si besoin",
    inconnu: "Mot inconnu — apprenez-le au bot",
  }[a.method] || "";
  const html = a.reply
    ? `<p class="text-base font-semibold">${esc(a.reply)}</p>
       ${a.reply_fr ? `<details class="mt-1 text-xs text-slate-500 dark:text-slate-400"><summary class="cursor-pointer text-blue-700 dark:text-okapi-cyan font-semibold">🇫🇷 En français</summary><p class="mt-1 italic">${esc(a.reply_fr)}</p></details>` : ""}
       ${audioTag(a.audio_url)}
       ${a.example ? `<div class="mt-2 p-2.5 rounded-lg bg-amber-50 dark:bg-okapi-yellow/10 border border-amber-200 dark:border-okapi-yellow/25 text-xs">
          <span class="font-bold text-amber-800 dark:text-okapi-yellow">📖 Exemple, lu par un locuteur :</span>
          <span class="italic text-slate-800 dark:text-slate-200">« ${esc(a.example.text)} »</span>
          <span class="block text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">${esc(a.example.source)}</span>
          ${audioTag(a.example.audio_url)}</div>` : ""}`
    : `<p>🤔 ${esc(a.hint || "Je ne sais pas encore répondre.")}</p>`;
  const listen = a.reply && (a.tts_url || a.audio_url)
    ? `<button type="button" class="b-listen ${smallBtn}"><i data-lucide="volume-2" class="w-3.5 h-3.5"></i>Écouter</button>` : "";
  const body = appendBot(log, html + `<div class="mt-2.5 flex flex-wrap gap-2">${listen}<button type="button" class="b-teach ${smallBtn}">
      <i data-lucide="${a.reply ? "pencil" : "graduation-cap"}" class="w-3.5 h-3.5"></i>${a.reply ? "Corriger" : "Apprendre une réponse"}</button></div>`, meta);
  $(".b-teach", body).onclick = () => showTeach(body, lang, userMsg, a.reply);
  const say = () => (a.audio_url ? playUrl(a.audio_url) : speak(a.reply, lang, a.tts_url));
  if ($(".b-listen", body)) $(".b-listen", body).onclick = say;
  if (!a.reply) return Promise.resolve();
  convHistory[key].push({ role: "user", text: userMsg }, { role: "assistant", text: a.reply });
  convHistory[key] = convHistory[key].slice(-20);
  return say();  // OkapiAI répond à voix haute
}

function showTeach(body, lang, msg, current) {
  if ($(".teach", body)) return;
  const form = document.createElement("form");
  form.className = "teach mt-2.5 flex gap-2";
  form.innerHTML = `<input class="${inputCls}" placeholder="La bonne réponse en ${esc(langName(lang))}" value="${esc(current || "")}" required>
    <button class="px-3 py-1.5 rounded-lg bg-gradient-to-r from-okapi-blue to-blue-600 text-white text-xs font-bold cursor-pointer">Envoyer</button>`;
  body.appendChild(form);
  $("input", form).focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (!requireLogin()) return;
    const reply = $("input", form).value.trim();
    if (!reply) return;
    try {
      const r = await api("/api/contributions/text", { method: "POST",
        json: { kind: "dialogue", source_lang: lang, source_text: msg, target_lang: lang, target_text: reply } });
      form.outerHTML = `<p class="mt-2 text-xs font-semibold text-emerald-600 dark:text-emerald-400">✓ ${esc(r.message)}</p>`;
      showToast("Merci ! Votre réponse a été ajoutée au dataset de collecte.", "success");
    } catch (err) { showToast(err.message, "error"); }
  };
}

async function sendConverse(log, lang, text, key) {
  try {
    const a = await api("/api/converse", { method: "POST", json: { lang, message: text, history: convHistory[key] } });
    return renderAnswer(log, lang, text, a, key);
  } catch (err) { appendBot(log, `<p>⚠️ ${esc(err.message)}</p>`); }
}

// ---------- Chat ----------
function initChat() {
  const log = $("#chat-log"), input = $("#chat-input"), src = $("#chat-src"), tgt = $("#chat-tgt");
  $("#chat-swap").addEventListener("click", () => { const t = src.value; src.value = tgt.value; tgt.value = t; });
  $$(".quick-prompt").forEach((chip) => chip.addEventListener("click", () => {
    if (chip.dataset.lang) src.value = chip.dataset.lang;
    input.value = chip.textContent.trim();
    $("#chat-form").requestSubmit();
  }));
  src.addEventListener("change", () => { convHistory.chat = []; if (modeOf("chat") === "converse") ensureCongolese(src); });
  const onChatMode = (mode) => {
    if (mode === "converse") ensureCongolese(src);
    input.placeholder = mode === "converse"
      ? "Écrivez en lingala, swahili, kikongo ou tshiluba… ou demandez « que veut dire ndako ? »"
      : "Écrivez le mot ou la phrase à traduire…";
  };
  $('[data-modes="chat"]').addEventListener("modechange", (e) => onChatMode(e.detail));
  onChatMode(modeOf("chat"));  // état initial (le mode est appliqué avant cet écouteur)

  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    const converse = modeOf("chat") === "converse";
    appendUser(log, esc(text), converse ? langName(src.value) : `${langName(src.value)} → ${langName(tgt.value)}`);
    input.value = "";
    if (converse) return sendConverse(log, src.value, text, "chat");
    try {
      const r = await api("/api/chat", { method: "POST", json: { text, source_lang: src.value, target_lang: tgt.value } });
      appendBot(log, `<p>${esc(r.reply)}</p>${audioTag(r.audio_url)}`, translationMeta(r));
      if (r.translation) speak(r.translation, r.target_lang, r.audio_url ? null : ttsFor(r.translation, r.target_lang));
    } catch (err) { appendBot(log, `<p>⚠️ ${esc(err.message)}</p>`); }
  });
}

// ---------- Enregistreur audio ----------
// Enregistreur micro. `onSilence` (optionnel) : appelé quand l'utilisateur a parlé puis
// s'est tu ~1,2 s (détection de fin de phrase pour le mode mains libres), ou après 20 s.
function makeRecorder() {
  let rec, chunks = [], stream, ctx, timer;
  return {
    get active() { return rec?.state === "recording"; },
    async start(onSilence) {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const type = ["audio/webm", "audio/ogg", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported?.(t));
      rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.start();
      if (!onSilence) return;
      ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const t0 = performance.now();
      let spoke = false, quietSince = null, noise = 0.01;
      timer = setInterval(() => {
        analyser.getFloatTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
        const now = performance.now();
        if (now - t0 < 400) { noise = Math.max(noise, rms); return; }  // bruit de fond
        if (rms > Math.max(0.02, noise * 2.5)) { spoke = true; quietSince = null; }
        else if (spoke) quietSince ??= now;
        if ((spoke && quietSince && now - quietSince > 1200) || now - t0 > 20000) {
          clearInterval(timer); timer = null;
          onSilence(spoke);
        }
      }, 80);
    },
    stop() {
      clearInterval(timer); timer = null;
      ctx?.close(); ctx = null;
      return new Promise((resolve) => {
        if (!rec || rec.state !== "recording") return resolve(null);
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

// ---------- Voix live ----------
const voiceLang = (c) => (c === "auto" ? "Détection automatique" : langName(c));
const handsFree = () => $("#voice-handsfree")?.checked && modeOf("voice") === "converse";

function updateVoiceHint() {
  const code = $("#voice-src").value;
  const caps = state.voiceCaps || { asr: [], tts: [], auto_detect: [] };
  const l = state.langs.find((x) => x.code === code);
  const hands = handsFree();
  if (code === "auto" || l?.asr) {
    $("#voice-hint").textContent = hands
      ? "Appuyez une fois sur le micro puis parlez naturellement : OkapiAI vous répond à voix haute et réécoute."
      : "Appuyez sur le micro, parlez, puis appuyez de nouveau : OkapiAI transcrit et vous répond à voix haute.";
  } else {
    $("#voice-hint").textContent = `Appuyez sur le micro et parlez. La transcription automatique n'existe pas encore pour le ${l?.name || "cette langue"} : vous taperez ce que vous avez dit.`;
  }
  const names = (codes) => codes.map(langName).join(", ") || "aucune";
  $("#voice-asr-info").textContent = `Reconnaissance vocale : ${names(caps.asr.filter(isCongolese))}. `
    + `Voix d'OkapiAI : ${names(caps.tts.filter(isCongolese))}.`
    + (caps.auto_detect.length > 1 ? ` « Détection automatique » reconnaît seule : ${names(caps.auto_detect)}.` : "");
}

function fillVoiceSrc() {
  const sel = $("#voice-src");
  const auto = (state.voiceCaps?.auto_detect || []).length > 1;
  $('option[value="auto"]', sel)?.remove();
  if (auto && modeOf("voice") === "converse") {
    sel.insertAdjacentHTML("afterbegin", `<option value="auto" class="bg-white dark:bg-obsidian-900 text-slate-900 dark:text-white">🌍 Détection automatique</option>`);
  }
}

function setRecVisual(on) {
  const btn = $("#rec-btn");
  ["from-sky-400", "via-okapi-blue", "to-blue-700"].forEach((c) => btn.classList.toggle(c, !on));
  ["from-okapi-red", "to-rose-700"].forEach((c) => btn.classList.toggle(c, on));
  $("#rec-label").textContent = on ? "Stop" : "Parler";
  $("#mic-ring-1").classList.toggle("hidden", !on);
  $("#mic-ring-2").classList.toggle("hidden", !on);
}

function initVoice() {
  const rec = makeRecorder();
  const log = $("#voice-log");
  let session = false;  // mode mains libres : la conversation continue jusqu'à « Stop »
  const ensureVoiceLang = () => {
    const sel = $("#voice-src");
    if (modeOf("voice") === "converse" && sel.value !== "auto") ensureCongolese(sel);
  };
  fillVoiceSrc();
  if ($('#voice-src option[value="auto"]')) $("#voice-src").value = "auto";
  $("#voice-src").addEventListener("change", () => { convHistory.voice = []; ensureVoiceLang(); updateVoiceHint(); });
  $("#voice-handsfree").addEventListener("change", updateVoiceHint);
  $('[data-modes="voice"]').addEventListener("modechange", () => {
    const keep = $("#voice-src").value;
    fillVoiceSrc();
    $("#voice-src").value = $(`#voice-src option[value="${keep}"]`) ? keep : "ln";
    ensureVoiceLang();
    updateVoiceHint();
  });

  const setHint = (t) => ($("#voice-hint").textContent = t);

  async function listen() {
    stopSpeaking();
    try {
      await rec.start(handsFree() ? (spoke) => (spoke ? finish() : endSession("Je n'ai rien entendu. Appuyez sur le micro pour reprendre.")) : undefined);
    } catch { session = false; return showToast("Micro inaccessible : autorisez l'accès au micro dans le navigateur.", "error"); }
    setRecVisual(true);
    setHint(handsFree() ? "🎙️ Je vous écoute… parlez, je réponds dès que vous vous arrêtez." : "Écoute en cours… appuyez de nouveau pour terminer.");
  }

  function endSession(message) {
    session = false;
    stopSpeaking();
    rec.stop();
    setRecVisual(false);
    updateVoiceHint();
    if (message) setHint(message);
  }

  async function finish() {
    setRecVisual(false);
    const blob = await rec.stop();
    if (!blob) return;
    setHint("⏳ OkapiAI réfléchit…");
    const src = $("#voice-src").value, tgt = $("#voice-tgt").value;
    const me = appendUser(log, `<audio controls src="${URL.createObjectURL(blob)}" class="h-8 max-w-[240px]"></audio>`, "Transcription…");
    const form = new FormData();
    form.append("audio", blob, `voix.${extFor(blob)}`);
    let spoken = Promise.resolve(), understood = true;
    try {
      if (modeOf("voice") === "converse") {
        form.append("lang", src);
        form.append("history", JSON.stringify(convHistory.voice));
        const r = await api("/api/voice/converse", { method: "POST", form });
        understood = Boolean(r.transcript);
        spoken = renderVoiceConverse(me, r, src);
      } else {
        form.append("source_lang", src); form.append("target_lang", tgt);
        spoken = renderVoiceTranslate(me, await api("/api/voice/chat", { method: "POST", form }), src, tgt);
      }
    } catch (err) { $(".u-meta", me).textContent = `⚠️ ${err.message}`; understood = false; }
    setHint("🔊 OkapiAI vous répond…");
    await spoken;
    // Mains libres : on réécoute automatiquement après la réponse parlée
    if (session && handsFree() && understood) return listen();
    endSession(session && !understood ? "Je n'ai pas compris. Appuyez sur le micro pour réessayer, ou corrigez le texte." : "");
  }

  $("#rec-btn").addEventListener("click", async () => {
    if (session || rec.active) {
      if (handsFree()) return endSession("Conversation terminée. Appuyez sur le micro pour recommencer.");
      session = false;
      return finish();
    }
    session = true;
    listen();
  });
}

const voiceInput = (cls, placeholder, value) =>
  `<input class="${cls} mt-2 w-full rounded-lg px-3 py-1.5 text-sm bg-white/15 border border-white/30 text-white placeholder-white/70 focus:outline-none focus:border-okapi-yellow" placeholder="${esc(placeholder)}" value="${esc(value || "")}">`;
const voiceBtn = (cls, label) =>
  `<button type="button" class="${cls} px-3 py-1 rounded-lg bg-white/15 hover:bg-white/25 border border-white/30 text-xs font-bold cursor-pointer">${label}</button>`;

function renderVoiceConverse(me, r, selected) {
  const lang = r.lang || selected;  // langue détectée en mode automatique
  $(".u-meta", me).textContent = selected === "auto" ? `${langName(lang)} (détecté)` : langName(lang);
  const box = document.createElement("form");
  box.innerHTML = voiceInput("vt-src", `Ce que vous avez dit (${langName(lang)})`, r.transcript) +
    `<div class="mt-2 flex gap-2">${voiceBtn("vt-send", r.answer ? "Renvoyer corrigé" : "Envoyer")}</div>`;
  $(".u-body", me).appendChild(box);
  const send = () => { const t = $(".vt-src", box).value.trim(); if (t) sendConverse($("#voice-log"), lang, t, "voice"); };
  $(".vt-send", box).onclick = send;
  box.onsubmit = (e) => { e.preventDefault(); send(); };
  if (r.answer) return renderAnswer($("#voice-log"), lang, r.transcript, r.answer, "voice");
  $(".vt-src", box).focus();
  return Promise.resolve();
}

function renderVoiceTranslate(me, r, src, tgt) {
  $(".u-meta", me).textContent = `${langName(src)} → ${langName(tgt)}`;
  const box = document.createElement("div");
  box.innerHTML = voiceInput("vt-src", `Ce que vous avez dit (${langName(src)})`, r.transcript) +
    voiceInput("vt-tgt", `Traduction (${langName(tgt)})`, r.translation?.translation) +
    `<div class="mt-2 flex flex-wrap gap-2">${voiceBtn("vt-translate", "Traduire")}${voiceBtn("vt-save", "💾 Ajouter au dataset")}</div>
     <p class="vt-msg mt-1 text-[11px] text-okapi-yellow font-semibold"></p>`;
  $(".u-body", me).appendChild(box);
  const log = $("#voice-log");
  let spoken = Promise.resolve();
  if (r.translation?.translation) {
    appendBot(log, `<p class="text-base font-semibold">${esc(r.translation.translation)}</p>${audioTag(r.translation.audio_url)}`, translationMeta(r.translation));
    spoken = r.translation.audio_url ? playUrl(r.translation.audio_url)
      : speak(r.translation.translation, tgt, ttsFor(r.translation.translation, tgt));
  }
  $(".vt-translate", box).onclick = async () => {
    const text = $(".vt-src", box).value.trim();
    if (!text) return;
    try {
      const t = await api("/api/chat", { method: "POST", json: { text, source_lang: src, target_lang: tgt } });
      if (t.translation) $(".vt-tgt", box).value = t.translation;
      appendBot(log, `<p>${esc(t.reply)}</p>${audioTag(t.audio_url)}`, translationMeta(t));
    } catch (err) { showToast(err.message, "error"); }
  };
  $(".vt-save", box).onclick = async () => {
    if (!requireLogin()) return;
    const form = new FormData();
    form.append("audio_file", r.audio_file);
    form.append("source_lang", src); form.append("source_text", $(".vt-src", box).value.trim());
    form.append("target_lang", tgt); form.append("target_text", $(".vt-tgt", box).value.trim());
    try {
      const res = await api("/api/contributions/voice", { method: "POST", form });
      $(".vt-msg", box).textContent = `✓ ${res.message}`;
      $(".vt-save", box).disabled = true;
      showToast("Votre voix a été ajoutée au dataset de collecte.", "success");
    } catch (err) { $(".vt-msg", box).textContent = `⚠️ ${err.message}`; }
  };
  return spoken;
}

// ---------- Contribuer ----------
const contribRec = { rec: makeRecorder(), blob: null };
const STATUS_LABEL = { collecte: "En collecte", en_attente_admin: "En attente admin", approuve: "Approuvée", rejete: "Rejetée" };
const statusBadge = (s) => {
  const cls = s === "approuve" ? "bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    : s === "rejete" ? "bg-rose-100 dark:bg-rose-500/15 text-rose-700 dark:text-rose-400"
    : "bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-400";
  return `<span class="px-2 py-0.5 rounded-md text-[10px] font-bold whitespace-nowrap ${cls}">${STATUS_LABEL[s] || esc(s)}</span>`;
};
const progressBar = (n, req) => `<div class="w-full h-1.5 rounded-full bg-slate-200 dark:bg-obsidian-950 overflow-hidden">
  <div class="h-full drc-swoosh rounded-full transition-all" style="width:${Math.min(100, Math.round((n / req) * 100))}%"></div></div>`;
const pairLabel = (p) => p.kind === "dialogue" ? `💬 Dialogue · ${langName(p.source_lang)}` : `${langName(p.source_lang)} → ${langName(p.target_lang)}`;

function resetContribRecorder() {
  contribRec.blob = null;
  $("#contrib-audio").classList.add("hidden");
  $("#contrib-rec-status").textContent = "Optionnel";
  $("#contrib-rec-status").classList.remove("text-emerald-600", "dark:text-emerald-400", "font-semibold");
}

function initContribute() {
  const recBtn = $("#contrib-rec-btn");
  recBtn.addEventListener("click", async () => {
    const label = $("span", recBtn);
    if (!contribRec.rec.active) {
      try { await contribRec.rec.start(); } catch { return showToast("Micro inaccessible.", "error"); }
      label.textContent = "Arrêter l'enregistrement";
      recBtn.classList.add("ring-2", "ring-okapi-red");
      return;
    }
    contribRec.blob = await contribRec.rec.stop();
    recBtn.classList.remove("ring-2", "ring-okapi-red");
    label.textContent = "Réenregistrer";
    const audio = $("#contrib-audio");
    audio.src = URL.createObjectURL(contribRec.blob);
    audio.classList.remove("hidden");
    $("#contrib-rec-status").textContent = "Voix attachée ✓";
    $("#contrib-rec-status").classList.add("text-emerald-600", "dark:text-emerald-400", "font-semibold");
  });

  $('[data-modes="contrib"]').addEventListener("modechange", (e) => {
    if (e.detail === "converse") ensureCongolese($("#contrib-form [name=source_lang]"));
    $("span", recBtn).textContent = e.detail === "converse" ? "Enregistrer la réponse à voix haute" : "Enregistrer la prononciation";
  });

  $("#contrib-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!requireLogin()) return;
    const f = new FormData(e.target);
    if (modeOf("contrib") === "converse") { f.set("kind", "dialogue"); f.set("target_lang", f.get("source_lang")); }
    else f.set("kind", "traduction");
    try {
      let res;
      if (contribRec.blob) {
        f.append("audio", contribRec.blob, `voix.${extFor(contribRec.blob)}`);
        res = await api("/api/contributions/voice", { method: "POST", form: f });
      } else {
        res = await api("/api/contributions/text", { method: "POST", json: Object.fromEntries(f) });
      }
      showToast(res.message, "success");
      $("#contrib-form [name=source_text]").value = "";
      $("#contrib-form [name=target_text]").value = "";
      resetContribRecorder();
      loadProposals(); loadMine();
    } catch (err) { showToast(err.message, "error"); }
  });
  $("#prop-filter").addEventListener("change", loadProposals);
}

async function loadProposals() {
  const el = $("#proposals");
  const lang = $("#prop-filter").value;
  try {
    const list = await api(`/api/contributions/proposals${lang ? `?lang=${lang}` : ""}`);
    el.innerHTML = list.length ? list.map((p) => `
      <div class="p-3.5 rounded-xl bg-slate-50 dark:bg-obsidian-900/80 border border-slate-200 dark:border-okapi-blue/15 space-y-2.5">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[11px] font-bold text-blue-700 dark:text-okapi-cyan">${esc(pairLabel(p))}</span>
          <span class="text-[11px] text-slate-500 dark:text-slate-400 font-semibold">${p.support}/${p.required} personnes</span>
        </div>
        <div class="text-xs space-y-1">
          <p class="text-slate-900 dark:text-slate-200 font-semibold">« ${esc(p.source_text)} »</p>
          <p class="text-slate-600 dark:text-slate-400">→ ${p.kind === "dialogue" ? "réponse : " : ""}« ${esc(p.target_text)} »</p>
        </div>
        ${progressBar(p.support, p.required)}
        <div class="flex justify-end pt-1">
          ${p.voted
            ? `<span class="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400" title="Un seul vote par personne">✓ Déjà confirmé</span>`
            : `<button type="button" data-confirm="${p.id}" class="${smallBtn}">✓ Je confirme</button>`}
        </div>
      </div>`).join("")
      : `<p class="text-center py-6 text-xs text-slate-400 dark:text-slate-500 border border-dashed border-slate-300 dark:border-okapi-blue/25 rounded-xl">Aucune proposition en cours. Soyez le premier à contribuer !</p>`;
    $$("[data-confirm]", el).forEach((b) => (b.onclick = async () => {
      if (!requireLogin()) return;
      b.disabled = true;
      try {
        const r = await api(`/api/contributions/proposals/${b.dataset.confirm}/confirm`, { method: "POST", form: new FormData() });
        showToast(r.message, "success");
        loadProposals(); loadMine();
      } catch (err) { b.disabled = false; showToast(err.message, "error"); }
    }));
  } catch (err) { el.innerHTML = `<p class="text-xs text-okapi-red">⚠️ ${esc(err.message)}</p>`; }
}

async function loadMine() {
  const el = $("#mine");
  if (!state.user) {
    $("#mine-count").textContent = "0";
    el.innerHTML = `<p class="text-xs text-slate-500 dark:text-slate-400">Connectez-vous pour voir vos contributions.</p>`;
    return;
  }
  try {
    const list = await api("/api/contributions/mine");
    $("#mine-count").textContent = list.length;
    el.innerHTML = list.length ? list.map((c) => `
      <div class="p-3 rounded-xl bg-slate-50 dark:bg-obsidian-900/60 border border-slate-200 dark:border-white/5 flex items-center justify-between gap-3 text-xs">
        <div class="min-w-0">
          <p class="text-slate-800 dark:text-slate-200 font-semibold truncate">${c.type === "dialogue" ? "💬 " : ""}${c.kind === "voix" ? "🎙️ " : ""}${esc(c.source_text)}</p>
          <p class="text-slate-500 truncate">${esc(c.target_text)}</p>
          ${c.audio_url ? `<audio controls preload="none" src="${esc(withToken(c.audio_url))}" class="mt-1 h-7 max-w-[200px]"></audio>` : ""}
        </div>
        ${c.status === "collecte"
          ? `<span class="px-2 py-0.5 rounded-md text-[10px] font-bold whitespace-nowrap bg-amber-100 dark:bg-amber-500/15 text-amber-800 dark:text-amber-400">${c.support}/${c.required}</span>`
          : statusBadge(c.status)}
      </div>`).join("")
      : `<p class="text-xs text-slate-500 dark:text-slate-400">Vous n'avez encore rien envoyé.</p>`;
  } catch (err) { el.innerHTML = `<p class="text-xs text-okapi-red">⚠️ ${esc(err.message)}</p>`; }
}
tabLoaders.contribute = () => { loadProposals(); loadMine(); };

// ---------- Apprendre ----------
const learnState = { mode: "cards", cards: [], index: 0, flipped: false, score: 0, step: 0 };
const emptyLearn = (lang) => `<div class="text-center max-w-md space-y-3">
  <div class="mx-auto w-12 h-12 rounded-2xl bg-blue-100 dark:bg-okapi-blue/15 flex items-center justify-center text-okapi-blue dark:text-okapi-cyan"><i data-lucide="sprout" class="w-6 h-6"></i></div>
  <p class="font-display font-bold text-lg text-slate-900 dark:text-white">Pas encore de phrases validées en ${esc(langName(lang))}</p>
  <p class="text-sm text-slate-600 dark:text-slate-400">Les cartes et les quiz utilisent uniquement les données validées par la communauté et l'admin. Contribuez pour les remplir !</p>
</div>`;

function setLearnButtons(mode) {
  const on = ["bg-okapi-blue", "text-white", "shadow-md"], off = ["bg-white", "dark:bg-obsidian-900", "text-slate-700", "dark:text-slate-200"];
  const [a, b] = mode === "cards" ? [$("#learn-cards-btn"), $("#learn-quiz-btn")] : [$("#learn-quiz-btn"), $("#learn-cards-btn")];
  on.forEach((c) => { a.classList.add(c); b.classList.remove(c); });
  off.forEach((c) => { a.classList.remove(c); b.classList.add(c); });
}

async function showCards() {
  learnState.mode = "cards"; setLearnButtons("cards");
  const area = $("#learn-area"), lang = $("#learn-lang").value;
  try { learnState.cards = await api(`/api/learn/cards?lang=${lang}&limit=20`); }
  catch (err) { area.innerHTML = `<p class="text-okapi-red text-sm">⚠️ ${esc(err.message)}</p>`; return; }
  learnState.index = 0; learnState.flipped = false;
  if (!learnState.cards.length) { area.innerHTML = emptyLearn(lang); icons(); return; }
  renderCard();
}

function renderCard() {
  const area = $("#learn-area"), cards = learnState.cards, c = cards[learnState.index];
  const flipped = learnState.flipped;
  area.innerHTML = `<div class="w-full max-w-md space-y-6 text-center">
    <div class="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 font-semibold">
      <span>Carte ${learnState.index + 1} sur ${cards.length}</span>
      <span class="text-amber-600 dark:text-amber-400">Cliquez sur la carte pour la retourner</span>
    </div>
    <div id="flashcard" class="cursor-pointer relative w-full min-h-56 rounded-2xl bg-gradient-to-br from-white via-blue-50/70 to-sky-100/80 dark:from-obsidian-800 dark:to-obsidian-950 border-2 border-blue-200 dark:border-okapi-blue/30 hover:border-okapi-blue dark:hover:border-okapi-yellow/60 p-6 flex flex-col items-center justify-center shadow-lg transition-all duration-300">
      <span class="text-[11px] uppercase tracking-widest font-extrabold text-amber-600 dark:text-okapi-yellow mb-3">${esc(langName(flipped ? c.meaning_lang : c.lang))}</span>
      <p class="font-display font-bold text-xl sm:text-2xl text-slate-900 dark:text-white">${esc(flipped ? c.meaning : c.text)}</p>
    </div>
    ${c.audio_url ? `<audio controls preload="none" src="${esc(c.audio_url)}" class="mx-auto h-9"></audio>` : ""}
    <div class="flex items-center justify-center gap-3">
      <button type="button" id="prev-card" class="px-4 py-2.5 rounded-xl bg-white hover:bg-slate-100 dark:bg-white/5 dark:hover:bg-white/10 border border-slate-300 dark:border-okapi-blue/20 text-sm font-semibold text-slate-700 dark:text-slate-200 transition-colors cursor-pointer">← Précédente</button>
      <button type="button" id="next-card" class="px-5 py-2.5 rounded-xl bg-gradient-to-r from-okapi-blue to-blue-600 text-white text-sm font-bold shadow-md shadow-okapi-blue/25 transition-colors cursor-pointer">Suivante →</button>
    </div>
  </div>`;
  $("#flashcard").onclick = () => {
    learnState.flipped = !learnState.flipped;
    if (learnState.flipped) speak(c.meaning, c.meaning_lang);
    renderCard();
  };
  $("#prev-card").onclick = () => { learnState.index = (learnState.index - 1 + cards.length) % cards.length; learnState.flipped = false; renderCard(); };
  $("#next-card").onclick = () => { learnState.index = (learnState.index + 1) % cards.length; learnState.flipped = false; renderCard(); };
}

async function showQuiz() {
  learnState.mode = "quiz"; setLearnButtons("quiz");
  const area = $("#learn-area"), lang = $("#learn-lang").value;
  let q;
  try { q = await api(`/api/learn/quiz?lang=${lang}`); }
  catch { area.innerHTML = emptyLearn(lang).replace("Pas encore de phrases validées", "Pas assez de phrases validées pour un quiz"); icons(); return; }
  area.innerHTML = `<div class="w-full max-w-lg space-y-6">
    <div class="flex items-center justify-between text-xs font-bold">
      <span class="text-slate-500 dark:text-slate-400">Quiz ${esc(langName(lang))} • Question ${learnState.step + 1}</span>
      <span class="px-2.5 py-1 rounded-full bg-emerald-100 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400">Score : ${learnState.score} / ${learnState.step}</span>
    </div>
    <div class="p-6 rounded-2xl bg-blue-50/70 dark:bg-obsidian-900/90 border border-blue-200 dark:border-okapi-blue/25 text-center">
      <p class="text-xs text-slate-500 dark:text-slate-400 mb-2 font-medium">Que signifie cette expression ?</p>
      <h3 class="font-display font-bold text-xl sm:text-2xl text-blue-800 dark:text-okapi-yellow">« ${esc(q.question)} »</h3>
      ${q.audio_url ? `<audio controls preload="none" src="${esc(q.audio_url)}" class="mx-auto mt-3 h-9"></audio>` : ""}
    </div>
    <div class="space-y-2.5">${q.choices.map((c, i) => `
      <button type="button" data-i="${i}" class="quiz-opt w-full text-left p-4 rounded-xl bg-white hover:bg-blue-50 dark:bg-obsidian-900 dark:hover:bg-obsidian-800 border border-slate-200 dark:border-okapi-blue/20 hover:border-okapi-blue text-sm font-semibold text-slate-800 dark:text-slate-200 transition-all cursor-pointer shadow-2xs">${esc(c)}</button>`).join("")}
    </div>
  </div>`;
  $$(".quiz-opt", area).forEach((btn) => btn.addEventListener("click", () => {
    const ok = q.choices[btn.dataset.i] === q.answer;
    learnState.step += 1;
    if (ok) { learnState.score += 1; showToast("Bonne réponse !", "success"); }
    else showToast(`Réponse attendue : « ${q.answer} »`, "error");
    showQuiz();
  }));
}

function initLearn() {
  $("#learn-cards-btn").addEventListener("click", showCards);
  $("#learn-quiz-btn").addEventListener("click", () => { learnState.score = 0; learnState.step = 0; showQuiz(); });
  $("#learn-lang").addEventListener("change", () => (learnState.mode === "quiz" ? showQuiz() : showCards()));
}
tabLoaders.learn = () => (learnState.mode === "quiz" ? showQuiz() : showCards());

// ---------- Admin ----------
const adminCard = "glass-panel rounded-2xl p-4 sm:p-5";
const EMPTY_ADMIN = {
  en_attente_admin: (s) => `Aucune proposition n'attend votre validation.<br>
    Une proposition arrive ici quand <b>${s.min_similar} personnes différentes</b> ont envoyé une traduction ou un dialogue similaire.
    ${s.propositions.collecte ? `<br>${s.propositions.collecte} proposition(s) en cours de collecte : choisissez « En collecte » pour les voir.`
      : "<br>Aucune contribution pour l'instant : commencez par l'onglet « Contribuer »."}`,
  collecte: () => "Aucune proposition en cours de collecte.",
  approuve: () => "Aucune proposition approuvée pour l'instant.",
  rejete: () => "Aucune proposition rejetée.",
};

async function loadAdmin() {
  if (!state.user?.is_admin) {
    $("#admin-stats").innerHTML = "";
    $("#admin-list").innerHTML = `<div class="${adminCard} text-center text-sm text-slate-600 dark:text-slate-300">🔒 Connectez-vous avec un compte administrateur pour accéder à ce panneau.</div>`;
    return;
  }
  $("#admin-list").innerHTML = `<div class="${adminCard} text-center text-sm text-slate-500">Chargement…</div>`;
  try { await renderAdmin(); }
  catch (err) {
    $("#admin-list").innerHTML = `<div class="${adminCard} text-center space-y-3">
      <p class="text-sm text-okapi-red font-semibold">⚠️ Impossible de charger le panneau admin : ${esc(err.message)}</p>
      <button type="button" id="admin-retry" class="${smallBtn}">Réessayer</button></div>`;
    $("#admin-retry").onclick = loadAdmin;
  }
}

async function renderAdmin() {
  const s = await api("/api/admin/stats");
  state.minSimilar = s.min_similar;
  const P = s.propositions;
  const stat = (label, value, color, sub) => `<div class="glass-panel rounded-2xl p-4">
      <p class="text-xs font-semibold text-slate-500 dark:text-slate-400">${label}</p>
      <p class="font-display font-black text-2xl ${color} mt-1">${value}</p>
      <span class="text-[11px] text-slate-500 dark:text-slate-400">${sub}</span></div>`;
  $("#admin-stats").innerHTML = [
    stat("Dataset de collecte", s.dataset_collecte, "text-slate-900 dark:text-white", `dont ${s.contributions_voix} avec voix`),
    stat("En attente admin", P.en_attente_admin, "text-amber-600 dark:text-okapi-yellow", `Seuil ≥ ${s.min_similar} atteint`),
    stat("Dataset d'entraînement", s.dataset_entrainement, "text-emerald-600 dark:text-emerald-400", "Prêt pour l'entraînement"),
    stat("Utilisateurs", s.users, "text-okapi-blue", `${P.collecte} proposition(s) en collecte`),
  ].join("");

  const status = $("#admin-status").value;
  const list = await api(`/api/admin/propositions?status=${status}`);
  const pending = status === "en_attente_admin";
  const field = "w-full bg-white dark:bg-obsidian-900 border border-slate-300 dark:border-okapi-blue/25 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-white focus:outline-none focus:border-okapi-blue";
  $("#admin-list").innerHTML = list.length ? list.map((p) => `
    <div class="${adminCard} space-y-3" data-pid="${p.id}">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-xs font-bold text-amber-600 dark:text-amber-400">#${p.id} · ${esc(pairLabel(p))}${p.kind === "dialogue" ? " (message → réponse)" : ""}</span>
        <span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-400 font-semibold">${p.support}/${p.required} contributeurs</span>
      </div>
      ${pending ? `<div class="grid gap-2"><input class="a-src ${field}" value="${esc(p.source_text)}"><input class="a-tgt ${field}" value="${esc(p.target_text)}"></div>`
        : `<div><p class="text-sm font-bold text-slate-900 dark:text-white">« ${esc(p.source_text)} »</p><p class="text-sm text-slate-600 dark:text-slate-400">→ « ${esc(p.target_text)} »</p></div>`}
      <p class="text-xs text-slate-500 dark:text-slate-400">Variantes : ${p.variants.map((v) => `« ${esc(v.source_text)} » → « ${esc(v.target_text)} » (×${v.count})`).join(" · ")}</p>
      ${p.audios.map((a) => `<div class="flex items-center gap-2 text-xs text-slate-500">🎙️ ${esc(a.user)} <audio controls preload="none" src="${esc(withToken(a.url))}" class="h-8"></audio></div>`).join("")}
      ${pending ? `<div class="flex flex-wrap gap-2 pt-1">
        <button type="button" data-act="approve" class="px-3.5 py-2 rounded-xl bg-emerald-100 hover:bg-emerald-200 dark:bg-emerald-500/20 dark:hover:bg-emerald-500/30 text-emerald-800 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-500/30 text-xs font-bold transition-colors cursor-pointer">✓ Approuver → dataset d'entraînement</button>
        <button type="button" data-act="reject" class="px-3.5 py-2 rounded-xl bg-rose-100 hover:bg-rose-200 dark:bg-rose-500/15 dark:hover:bg-rose-500/25 text-rose-800 dark:text-rose-400 border border-rose-300 dark:border-rose-500/30 text-xs font-bold transition-colors cursor-pointer">✕ Rejeter</button>
      </div>` : ""}
    </div>`).join("")
    : `<div class="${adminCard} p-8 text-center text-sm text-slate-500 dark:text-slate-400 leading-relaxed">${EMPTY_ADMIN[status]?.(s) || "Rien à afficher."}</div>`;

  $$("#admin-list [data-act]").forEach((b) => (b.onclick = async () => {
    const card = b.closest("[data-pid]");
    let json;
    if (b.dataset.act === "approve") {
      json = { source_text: $(".a-src", card).value.trim(), target_text: $(".a-tgt", card).value.trim() };
      if (!json.source_text || !json.target_text) return showToast("Les deux textes sont obligatoires.", "error");
    } else {
      const note = prompt("Raison du rejet (optionnel) :", "");
      if (note === null) return;  // « Annuler » : on ne rejette pas
      json = { note: note.trim() || null };
    }
    $$("button", card).forEach((x) => (x.disabled = true));
    try {
      await api(`/api/admin/propositions/${card.dataset.pid}/${b.dataset.act}`, { method: "POST", json });
      showToast(b.dataset.act === "approve" ? "Ajoutée au dataset d'entraînement." : "Proposition rejetée.", b.dataset.act === "approve" ? "success" : "info");
    } catch (err) { showToast(err.message, "error"); }
    loadAdmin();
  }));
}

function initAdmin() {
  $("#admin-status").addEventListener("change", loadAdmin);
  $("#admin-export").addEventListener("click", async () => {
    const res = await fetch("/api/admin/export/entrainement.jsonl", { headers: { Authorization: `Bearer ${state.token}` } });
    if (!res.ok) return showToast(`Export impossible (erreur ${res.status}). Reconnectez-vous puis réessayez.`, "error");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await res.blob()), download: "okapi_entrainement.jsonl" });
    document.body.appendChild(a); a.click(); a.remove();
    showToast("Dataset d'entraînement exporté.", "success");
  });
}
tabLoaders.admin = loadAdmin;

// ---------- État du serveur ----------
function setApiStatus(ok) {
  const el = $("#api-status");
  el.className = `${ok ? "text-emerald-600 dark:text-emerald-400" : "text-okapi-red"} flex items-center gap-1.5 font-semibold`;
  el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-okapi-red"}"></span>${ok ? "API connectée" : "API injoignable"}`;
}

// ---------- Démarrage ----------
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  initLoginDialog();
  initNavigation();
  renderAccount();
  try {
    state.langs = await api("/api/languages");
    state.voiceCaps = await api("/api/voice/capabilities").catch(() => null);
    setApiStatus(true);
  } catch {
    setApiStatus(false);
    showToast("Le serveur OkapiAI ne répond pas.", "error");
    return;
  }
  fillLangSelects();
  initModes();
  initChat();
  initVoice();
  initContribute();
  initLearn();
  initAdmin();
  updateVoiceHint();
  icons();

  api("/api/features").then((f) => {
    state.features = f;
    const via = (f.ai_providers || []).join(" + ");
    $("#ai-badge-text").textContent = f.ai_conversation ? `IA active${via ? ` (${via})` : ""}` : "Réponses du dataset";
    $("#ai-badge").title = f.ai_conversation ? `Conversation libre avec l'IA (${via}), ancrée sur le dataset validé`
      : "L'IA n'est pas activée sur le serveur : le bot répond avec les dialogues validés par la communauté";
  }).catch(() => {});

  const afterSession = () => { if (onAdminUrl()) openAdminFromUrl(); else activateTab("chat"); };
  if (state.token) {
    api("/api/auth/me").then((u) => setSession({ token: state.token, user: u })).catch(() => {}).finally(afterSession);
  } else afterSession();
});
