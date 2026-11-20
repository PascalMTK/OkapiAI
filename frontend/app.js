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
async function api(path, { method = "GET", json, form, signal } = {}) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const res = await fetch(path, { method, headers, body, signal });
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
  if (tab !== "voice") liveStop();  // quitter l'onglet coupe la conversation vocale
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
// Préférences du visiteur (peuvent être indisponibles : navigation privée…)
const prefGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const prefSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sans importance */ } };
function fillLangSelects() {
  const options = (filter) => state.langs.filter(filter)
    .map((l) => `<option value="${l.code}" class="bg-white dark:bg-obsidian-900 text-slate-900 dark:text-white">${esc(l.name)}</option>`).join("");
  $$(".lang-select").forEach((s) => (s.innerHTML = options(() => true)));
  $("#learn-lang").innerHTML = options((l) => isCongolese(l.code));
  $("#prop-filter").innerHTML = `<option value="">Toutes</option>` + options((l) => isCongolese(l.code));
  $("#chat-src").value = "ln"; $("#chat-tgt").value = "fr";
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
  const savedSrc = prefGet("okapi.chatLang");
  if (savedSrc && [...src.options].some((o) => o.value === savedSrc)) src.value = savedSrc;
  src.addEventListener("change", () => {
    convHistory.chat = []; if (modeOf("chat") === "converse") ensureCongolese(src);
    prefSet("okapi.chatLang", src.value);
  });
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

// ---------- Voix live : conversation en direct avec OkapiAI ----------
// L'utilisateur a toujours la priorité : le micro reste ouvert en permanence et, dès qu'il
// parle, OkapiAI se tait (s'il parlait) ou abandonne sa réponse en cours (s'il réfléchissait)
// pour l'écouter. Le son est capté en continu : le début de la phrase n'est jamais perdu.
const LIVE_RATE = 16000;            // ce que la reconnaissance vocale attend
const LIVE_PREROLL_S = 0.6;         // son gardé avant le début détecté de la parole
const LIVE_END_SILENCE_MS = 850;    // fin de phrase (une pause plus longue est recollée par `carry`)
const live = {
  on: false, state: "idle", lang: "auto", history: [], start: null,
  stream: null, ctx: null, mic: null, proc: null, buf: null, noise: 0.01,
  ring: [], ringLen: 0,             // derniers instants de son (pré-écoute)
  utter: null, utterLen: 0,         // phrase en cours d'enregistrement
  carry: null,                      // phrase précédente, si l'utilisateur a complété pendant la réflexion
  speechMs: 0, quietMs: 0, idleMs: 0, spoke: false, echo: 0, bargeMs: 0,
  player: null, playAnalyser: null, stopPlayback: null, request: null, raf: null,
};
const LIVE_STATUS = {
  idle: "Appuyez sur « Commencer » pour parler avec OkapiAI",
  listening: "Je vous écoute…",
  thinking: "OkapiAI réfléchit… (vous pouvez continuer à parler)",
  speaking: "OkapiAI parle… parlez quand vous voulez, il s'arrêtera",
  paused: "En pause — parlez ou touchez l'orbe pour reprendre",
};

function liveSetState(s, text) {
  live.state = s;
  const orb = $("#live-orb");
  orb.dataset.state = s;
  if (s !== "speaking") orb.classList.remove("no-level");
  if (s !== "listening" && s !== "speaking") orb.style.setProperty("--lvl", 0);
  $("#live-status").textContent = text || LIVE_STATUS[s];
  $("#live-dot").classList.toggle("animate-pulse", live.on);
}

function liveCaption(user, bot, botFr) {
  if (user !== undefined) $("#live-user").textContent = user ? (user === "…" ? "…" : `« ${user} »`) : "";
  if (bot !== undefined) $("#live-bot").textContent = bot || "";
  if (botFr !== undefined) $("#live-bot-fr").textContent = botFr || "";
  $("#live-bot-fr").classList.toggle("hidden", !$("#live-fr").checked || !$("#live-bot-fr").textContent);
}

function liveLog(who, text, fr, lang, note) {
  if (!text) return;
  const row = document.createElement("div");
  row.className = who === "user" ? "text-right" : "";
  row.innerHTML = `<span class="inline-block max-w-[85%] px-3 py-2 rounded-xl ${who === "user"
      ? "bg-gradient-to-br from-okapi-blue to-blue-700 text-white"
      : "bg-slate-100 dark:bg-obsidian-800 text-slate-800 dark:text-slate-100"}">${esc(text)}
    ${fr ? `<span class="block text-[11px] opacity-70 italic mt-0.5">${esc(fr)}</span>` : ""}
    ${lang || note ? `<span class="block text-[10px] opacity-60 mt-0.5">${esc([lang && langName(lang), note].filter(Boolean).join(" · "))}</span>` : ""}</span>`;
  $("#live-history").appendChild(row);
  $("#live-history").scrollTop = $("#live-history").scrollHeight;
}

// ---- Son : capture continue, ré-échantillonnée à 16 kHz ----
function liveRms(x) {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / Math.max(1, x.length));
}
function liveResample(x, from) {
  if (from === LIVE_RATE) return Float32Array.from(x);
  const ratio = from / LIVE_RATE, n = Math.floor(x.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {            // moyenne sur la fenêtre : filtre anti-repliement simple
    const a = Math.floor(i * ratio), b = Math.min(x.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b; j++) s += x[j];
    out[i] = s / Math.max(1, b - a);
  }
  return out;
}
function liveConcat(chunks, len) {
  const out = new Float32Array(len);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}
function liveWav(samples) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, LIVE_RATE, true); v.setUint32(28, LIVE_RATE * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
  return new Blob([buf], { type: "audio/wav" });
}

function liveStartUtterance(withPreroll) {
  const pre = withPreroll ? live.ring.slice() : [];
  live.utter = pre;
  live.utterLen = pre.reduce((n, c) => n + c.length, 0);
  live.speechMs = 0; live.quietMs = 0; live.idleMs = 0;
  live.spoke = withPreroll;
}

// Appelé ~20 fois par seconde avec le son du micro : c'est ici que l'utilisateur prend la main
function liveOnAudio(raw, ms) {
  const chunk = liveResample(raw, live.ctx.sampleRate);
  live.ring.push(chunk); live.ringLen += chunk.length;
  while (live.ringLen - live.ring[0].length > LIVE_PREROLL_S * LIVE_RATE) live.ringLen -= live.ring.shift().length;
  if (!live.on) return;
  const level = liveRms(raw);

  if (live.state === "speaking") {
    // La voix d'OkapiAI revient un peu dans le micro (écho) : on apprend son niveau pour
    // ne réagir qu'à une vraie voix, plus forte que cet écho. Dès que l'utilisateur parle, il se tait.
    const threshold = Math.max(0.03, live.noise * 3, live.echo * 2.5);
    if (level > threshold) live.bargeMs += ms;
    else { live.bargeMs = 0; live.echo = live.echo * 0.97 + level * 0.03; }
    if (live.bargeMs >= 250) liveBargeIn();
    return;
  }
  if (live.state === "thinking") {
    // Pendant la transcription, on n'interrompt jamais : sinon un bruit ou un « allô ? » annulait
    // la demande en boucle et OkapiAI ne répondait jamais. Pendant que l'IA prépare sa réponse,
    // l'utilisateur peut compléter sa phrase, mais il faut vraiment parler (≥ 0,7 s).
    if (live.phase !== "answer") return;
    if (level > Math.max(0.035, live.noise * 3.5)) live.bargeMs += ms;
    else live.bargeMs = Math.max(0, live.bargeMs - ms);
    if (live.bargeMs >= 700) liveBargeIn();
    return;
  }
  if (live.state === "paused") {
    if (level > Math.max(0.02, live.noise * 2.5)) { live.speechMs += ms; if (live.speechMs > 150) liveListen(true); }
    else live.speechMs = 0;
    return;
  }
  if (live.state !== "listening" || !live.utter) return;

  live.utter.push(chunk); live.utterLen += chunk.length;
  const loud = level > Math.max(0.015, live.noise * 2.5);
  if (loud) { live.speechMs += ms; live.quietMs = 0; if (live.speechMs > 150) live.spoke = true; }
  else if (live.spoke) live.quietMs += ms;
  else live.idleMs += ms;
  if (live.spoke && live.quietMs > LIVE_END_SILENCE_MS) return liveEndUtterance();
  if (live.spoke && live.utterLen > 25 * LIVE_RATE) return liveEndUtterance();   // phrase très longue
  if (!live.spoke && live.idleMs > 15000) { live.utter = null; liveSetState("paused"); }
}

// L'utilisateur parle : OkapiAI lui laisse immédiatement la parole
function liveBargeIn() {
  const was = live.state;
  live.bargeMs = 0;
  if (was === "speaking") live.stopPlayback?.({ interrupted: true });
  if (was === "thinking") {
    live.request?.abort();                 // la réponse en préparation est abandonnée…
    live.request = null;                   // …et ce que l'utilisateur ajoute complète sa phrase
  }
  liveListen(true);
}

function liveListen(fromSpeech = false) {
  if (!live.on) return;
  liveStartUtterance(fromSpeech);
  liveSetState("listening");
}

function liveEndUtterance() {
  let pcm = liveConcat(live.utter, live.utterLen);
  live.utter = null;
  if (live.carry) {                        // phrase précédente + complément, avec une petite pause
    const gap = new Float32Array(Math.round(0.3 * LIVE_RATE));
    pcm = liveConcat([live.carry, gap, pcm], live.carry.length + gap.length + pcm.length);
  }
  // gardée tant que la réponse n'est pas arrivée (au plus 20 s, pour ne pas grossir sans fin)
  live.carry = pcm.length <= 20 * LIVE_RATE ? pcm : null;
  liveSend(pcm);
}

async function liveSend(pcm) {
  if (!live.on) return;
  const ctrl = new AbortController();
  live.request = ctrl;
  live.phase = "transcribe";
  liveSetState("thinking", "Je transcris ce que vous avez dit…");
  liveCaption("…", "", "");
  live.echo = 0; live.bargeMs = 0;
  const form = new FormData();
  form.append("audio", liveWav(pcm), "voix.wav");
  form.append("lang", live.lang);
  let r, a;
  try {
    r = await api("/api/voice/transcribe", { method: "POST", form, signal: ctrl.signal });
    if (live.request !== ctrl) return;
    const lang = r.lang || "ln";
    if (!r.transcript) {                   // rien compris : OkapiAI demande de répéter, dans la langue
      live.carry = null; live.request = null;
      const retry = live.start?.retry?.[lang] || live.start?.retry?.ln;
      liveCaption("", retry?.reply, retry?.reply_fr);
      if (await liveSpeak(retry?.reply, lang, retry?.tts_url)) return;
      return liveListen();
    }
    liveCaption(r.transcript, "", "");
    live.phase = "answer"; live.bargeMs = 0;
    liveSetState("thinking", "OkapiAI réfléchit… (vous pouvez continuer à parler)");
    a = await api("/api/converse", { method: "POST", signal: ctrl.signal,
      json: { lang, message: r.transcript.slice(0, 1000), history: live.history.slice(-20), voice: true } });
    if (live.request !== ctrl) return;
    live.request = null; live.carry = null;   // réponse reçue : la phrase est close
    // Prononciation approximative comprise quand même : on montre aussi ce qui a été entendu,
    // pour que l'apprenant voie la bonne forme
    liveLog("user", r.transcript, null, live.lang === "auto" ? lang : null,
      r.fixes?.length ? `entendu : « ${r.heard} »` : null);
    if (!a?.reply) {
      liveCaption(r.transcript, a?.hint || "Je ne sais pas encore répondre à ça.", "");
      liveLog("bot", a?.hint || "Je ne sais pas encore répondre.");
      return liveListen();
    }
    live.history.push({ role: "user", text: r.transcript }, { role: "assistant", text: a.reply });
    liveCaption(r.transcript, a.reply, a.reply_fr);
    const interrupted = await liveSpeak(a.reply, lang, a.audio_url || a.tts_url);
    liveLog("bot", a.reply, a.reply_fr, null, interrupted ? "interrompu" : null);
    if (!interrupted) liveListen();
  } catch (err) {
    if (err.name === "AbortError" || live.request !== ctrl) return;   // l'utilisateur a repris la parole
    live.request = null; live.carry = null;
    if (live.on) liveSetState("paused", `⚠️ ${err.message} — parlez ou touchez l'orbe pour réessayer`);
  }
}

// OkapiAI parle. Résout `true` si l'utilisateur l'a interrompu, `false` à la fin normale.
function liveSpeak(text, lang, url) {
  if (!live.on || !text) return Promise.resolve(false);
  liveSetState("speaking");
  live.echo = 0; live.bargeMs = 0;
  return new Promise((resolve) => {
    let done = false;
    const finish = (how) => {
      if (done) return;
      done = true;
      live.player?.pause();
      live.player = null;
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      live.stopPlayback = null;
      resolve(Boolean(how?.interrupted));
    };
    live.stopPlayback = finish;
    if (url) {
      const a = new Audio(url);
      live.player = a;
      try { live.ctx.createMediaElementSource(a).connect(live.playAnalyser); }
      catch { $("#live-orb").classList.add("no-level"); }
      a.onended = a.onerror = () => finish();
      a.play().catch(() => finish());
    } else if ("speechSynthesis" in window && ["fr", "sw"].includes(lang)) {
      $("#live-orb").classList.add("no-level");
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang === "fr" ? "fr-FR" : "sw-KE";
      u.onend = u.onerror = () => finish();
      speechSynthesis.speak(u);
    } else {
      setTimeout(() => finish(), Math.min(6000, 400 + text.length * 55));  // pas de voix : temps de lecture
    }
  });
}

// ---- Orbe animé ----
function liveAnimate() {
  const orb = $("#live-orb");
  let lvl = 0;
  const level = (an) => { an.getFloatTimeDomainData(live.buf); return liveRms(live.buf); };
  if (live.state === "listening" && live.mic) lvl = Math.min(1, level(live.mic) * 9);
  if (live.state === "speaking" && live.playAnalyser && live.player) lvl = Math.min(1, level(live.playAnalyser) * 6);
  orb.style.setProperty("--lvl", lvl.toFixed(3));
  live.raf = requestAnimationFrame(liveAnimate);
}

async function liveOpenMic() {
  live.stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  live.ctx = new AudioContext();
  const src = live.ctx.createMediaStreamSource(live.stream);
  live.mic = live.ctx.createAnalyser();
  live.mic.fftSize = 1024;
  live.buf = new Float32Array(live.mic.fftSize);
  src.connect(live.mic);
  live.playAnalyser = live.ctx.createAnalyser();
  live.playAnalyser.fftSize = 1024;
  live.playAnalyser.connect(live.ctx.destination);
  // capture continue du micro (le nœud doit être relié à la sortie pour fonctionner, à volume nul)
  live.proc = live.ctx.createScriptProcessor(2048, 1, 1);
  const mute = live.ctx.createGain();
  mute.gain.value = 0;
  src.connect(live.proc); live.proc.connect(mute); mute.connect(live.ctx.destination);
  const ms = (2048 / live.ctx.sampleRate) * 1000;
  live.ring = []; live.ringLen = 0;
  live.proc.onaudioprocess = (e) => liveOnAudio(e.inputBuffer.getChannelData(0), ms);
  // bruit de fond : mesuré pendant 0,5 s
  const t0 = performance.now();
  live.noise = 0.004;
  while (performance.now() - t0 < 500) {
    live.mic.getFloatTimeDomainData(live.buf);
    live.noise = Math.max(live.noise, liveRms(live.buf));
    await new Promise((r) => setTimeout(r, 40));
  }
}

function liveCloseMic() {
  cancelAnimationFrame(live.raf); live.raf = null;
  if (live.proc) live.proc.onaudioprocess = null;
  live.stream?.getTracks().forEach((t) => t.stop());
  live.ctx?.close();
  Object.assign(live, { stream: null, ctx: null, mic: null, proc: null, playAnalyser: null, utter: null, ring: [], ringLen: 0 });
}

async function liveBegin() {
  stopSpeaking();
  live.lang = $("#live-lang").value;
  live.history = []; live.carry = null; live.request = null;
  $("#live-history").innerHTML = "";
  try { await liveOpenMic(); }
  catch { return showToast("Micro inaccessible : autorisez l'accès au micro dans le navigateur.", "error"); }
  live.on = true;
  $("#live-start").classList.add("hidden");
  $("#live-end").classList.remove("hidden");
  liveAnimate();
  try { live.start = await api(`/api/voice/start?lang=${encodeURIComponent(live.lang)}`); }
  catch { live.start = null; }
  if (!live.on) return;
  if (live.start?.reply) {
    live.history.push({ role: "assistant", text: live.start.reply });
    liveCaption("", live.start.reply, live.start.reply_fr);
    liveLog("bot", live.start.reply, live.start.reply_fr);
    if (await liveSpeak(live.start.reply, live.start.lang, live.start.tts_url)) return;  // interrompu : déjà à l'écoute
  }
  liveListen();
}

function liveStop() {
  if (!live.on && !live.stream) return;
  live.on = false;
  live.request?.abort(); live.request = null; live.carry = null;
  live.stopPlayback?.();
  liveCloseMic();
  $("#live-start").classList.remove("hidden");
  $("#live-end").classList.add("hidden");
  liveSetState("idle", "Conversation terminée. Appuyez sur « Commencer » pour en démarrer une autre.");
}

function liveFillLangs() {
  const caps = state.voiceCaps || { asr: [], tts: [], auto_detect: [] };
  const opts = [];
  if ((caps.auto_detect || []).length > 1) opts.push(["auto", "🌍 Détection automatique"]);
  for (const l of state.langs.filter((x) => isCongolese(x.code) && caps.asr.includes(x.code))) opts.push([l.code, l.name]);
  $("#live-lang").innerHTML = opts.map(([v, n]) =>
    `<option value="${v}" class="bg-white dark:bg-obsidian-900 text-slate-900 dark:text-white">${esc(n)}</option>`).join("");
  // Langue choisie la dernière fois, sinon le lingala (la détection automatique reste proposée)
  const saved = prefGet("okapi.liveLang");
  const pick = [saved, "ln", opts[0]?.[0]].find((v) => v && opts.some(([o]) => o === v));
  if (pick) $("#live-lang").value = pick;
  const names = (codes) => codes.filter(isCongolese).map(langName).join(", ") || "aucune";
  const missing = state.langs.map((l) => l.code).filter((c) => isCongolese(c) && !caps.asr.includes(c));
  $("#live-info").textContent = opts.length
    ? `Reconnaissance vocale : ${names(caps.asr)} · Voix d'OkapiAI : ${names(caps.tts)}. `
      + (missing.length ? `${missing.map(langName).join(" et ")} : pas encore de modèle vocal, utilisez le chat écrit.` : "")
    : "La reconnaissance vocale n'est pas disponible sur ce serveur : utilisez le chat écrit.";
  $("#live-start").disabled = !opts.length;
  $("#live-start").classList.toggle("opacity-50", !opts.length);
}

function initLive() {
  liveFillLangs();
  // La langue se change aussi en pleine conversation : elle vaut dès la phrase suivante
  $("#live-lang").addEventListener("change", (e) => {
    prefSet("okapi.liveLang", e.target.value);
    if (!live.on) return;
    live.lang = e.target.value; live.carry = null;
    showToast(`Langue de la conversation : ${e.target.selectedOptions[0]?.textContent || e.target.value}`);
  });
  $("#live-start").addEventListener("click", liveBegin);
  $("#live-end").addEventListener("click", liveStop);
  $("#live-fr").addEventListener("change", () => liveCaption(undefined, undefined, $("#live-bot-fr").textContent));
  $("#live-orb").addEventListener("click", () => {
    if (!live.on) return liveBegin();
    if (live.state === "speaking" || live.state === "thinking") return liveBargeIn();  // « laisse-moi parler »
    if (live.state === "paused") return liveListen();
    if (live.state === "listening" && live.spoke) return liveEndUtterance();          // « j'ai fini »
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) liveStop(); });
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
  initLive();
  initContribute();
  initLearn();
  initAdmin();
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
