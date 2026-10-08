/* support.js - the PrepWithTee help centre (replaces chatbot-widget.js).
 *
 * One launcher (bottom right) -> a panel with three tabs:
 *   Home         status banner, the student's own account (plan, free allowance
 *                left, a failed booklet, a payment proof waiting) each with the
 *                button that fixes it, search over every page, questions for the
 *                page they're on, and "Talk to Tee".
 *   Chat         the assistant (/api/support/chat): answers + link cards + one-tap
 *                fixes, thumbs up/down, kept in sessionStorage across pages.
 *                "Send this to Tee" hands the chat to Tee's admin Inbox with the
 *                page, browser and recent errors attached (+ optional screenshots).
 *   My requests  what they sent Tee and Tee's replies (badge on new replies).
 *
 * Hidden on full-screen tools (paper viewers, MCQ sessions, the whiteboard
 * editor) - open it there from the account menu ("Help & support") or with
 * window.pwtSupport.open(). Any element with [data-support] opens it too
 * (data-support="chat|home|requests", data-support-ask="question").
 */
(function () {
  "use strict";
  if (window.pwtSupport) return;
  if (/^\/(admin|teach)(\/|$)/.test(location.pathname)) return;

  var V = "20261009a";
  var OWL = "/logo-nav.webp";
  var TEE = "/images/tee-mascot.jpg";
  var STORE = "pwt-help";
  var SEEN = "pwt-help-seen";
  var HAS_THREADS = "pwt-help-threads";
  var HIDE_ON = /^\/(papers\/view|papers\/s|yearly\/view|mcq\/session|whiteboard\/(?!$)[^/]+)/;

  // ── Diagnostics: collected from the moment the page loads ─────────────────
  var diag = { errors: [], failed: [] };
  function pushCapped(list, item) { list.push(item); if (list.length > 8) list.shift(); }
  window.addEventListener("error", function (e) {
    if (!e || !e.message) return;
    pushCapped(diag.errors, String(e.message).slice(0, 200) + (e.filename ? " @ " + String(e.filename).split("/").pop() + ":" + e.lineno : ""));
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    pushCapped(diag.errors, "Promise: " + String((r && r.message) || r).slice(0, 200));
  });
  if (window.fetch && !window.fetch.__pwtHelp) {
    var origFetch = window.fetch;
    var wrapped = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      return origFetch.apply(this, arguments).then(function (res) {
        try {
          var path = new URL(url, location.href);
          if (path.origin === location.origin && /^\/(api|auth)\//.test(path.pathname) && res.status >= 400
              && !/\/api\/support\//.test(path.pathname)) {
            pushCapped(diag.failed, (init && init.method || "GET") + " " + path.pathname + " -> " + res.status);
          }
        } catch (_) {}
        return res;
      }, function (err) {
        pushCapped(diag.failed, "network error: " + String(url).slice(0, 120));
        throw err;
      });
    };
    wrapped.__pwtHelp = true;
    window.fetch = wrapped;
  }
  function collectDiag() {
    var n = navigator, c = n.connection || {};
    return {
      url: location.pathname + location.search, ua: n.userAgent,
      screen: screen.width + "x" + screen.height, viewport: innerWidth + "x" + innerHeight,
      dpr: String(window.devicePixelRatio || 1),
      theme: document.documentElement.getAttribute("data-theme") || "light",
      lang: n.language, tz: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone,
      online: String(n.onLine), connection: c.effectiveType ? c.effectiveType + (c.downlink ? " " + c.downlink + "Mb/s" : "") : "",
      memory: n.deviceMemory ? n.deviceMemory + " GB" : "",
      errors: diag.errors.slice(), failed: diag.failed.slice(),
    };
  }

  // ── State ──────────────────────────────────────────────────────────────────
  function load() {
    try { return JSON.parse(sessionStorage.getItem(STORE)) || {}; } catch (_) { return {}; }
  }
  var state = load();
  state.msgs = Array.isArray(state.msgs) ? state.msgs.slice(-40) : [];
  state.tab = state.tab || "home";
  function save() {
    try { sessionStorage.setItem(STORE, JSON.stringify({ msgs: state.msgs.slice(-40), tab: state.tab })); } catch (_) {}
  }
  var ctx = null, ctxAt = 0, threads = null, searchRows = null, sending = false, view = null;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) {
    u = String(u || "").trim();
    if (/^\/(?!\/)/.test(u)) return u;
    if (/^https:\/\/(wa\.me\/923204884375|(www\.)?prepwithtee\.com)(\/|$|\?)/.test(u)) return u;
    return null;
  }
  function inline(s) {
    // s is already escaped
    s = s.replace(/\[([^\]\n]{1,120})\]\(([^)\s]{1,300})\)/g, function (m, t, u) {
      var ok = safeUrl(u.replace(/&amp;/g, "&"));
      if (!ok) return t;
      var ext = /^https?:/.test(ok);
      return '<a href="' + esc(ok) + '"' + (ext ? ' target="_blank" rel="noopener"' : "") + ">" + t + "</a>";
    });
    // bare paths like "(→ /pricing.html)" or "visit /contact.html"
    s = s.replace(/(^|[\s(→])(\/(?:[a-z0-9-]+\/?)+(?:\.html)?(?:#[a-z0-9-]+)?)(?=[\s).,;!?]|$)/gi, function (m, pre, p) {
      return pre + '<a href="' + p + '">' + p + "</a>";
    });
    s = s.replace(/(^|[^"=])(https:\/\/wa\.me\/923204884375[^\s<)]*)/g, function (m, pre, u) {
      return pre + '<a href="' + u + '" target="_blank" rel="noopener">WhatsApp Tee</a>';
    });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;!?]|$)/g, "$1<em>$2</em>");
    return s;
  }
  function md(text) {
    var lines = esc(text).split(/\r?\n/), out = [], list = false, para = [];
    function flush() { if (para.length) { out.push("<p>" + inline(para.join("<br>")) + "</p>"); para = []; } }
    lines.forEach(function (ln) {
      var m = /^\s*(?:[-•*]|\d+[.)])\s+(.*)$/.exec(ln);
      if (m) {
        flush();
        if (!list) { out.push("<ul>"); list = true; }
        out.push("<li>" + inline(m[1]) + "</li>");
      } else {
        if (list) { out.push("</ul>"); list = false; }
        if (ln.trim()) para.push(ln); else flush();
      }
    });
    flush();
    if (list) out.push("</ul>");
    return out.join("");
  }
  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || "GET", credentials: "same-origin",
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) {
          var det = d && d.detail;
          var msg = typeof det === "string" ? det : (det && (det.message || det.title)) || "Something went wrong - please try again.";
          var e = new Error(msg); e.status = r.status; e.detail = det; throw e;
        }
        return d;
      });
    });
  }
  function track(action) {
    try {
      fetch("/api/support/track", { method: "POST", credentials: "same-origin", keepalive: true,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: action, page: location.pathname }) });
    } catch (_) {}
  }
  function dateStr(ts) {
    try { return new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "short" }); } catch (_) { return ""; }
  }

  // ── Page-aware questions ───────────────────────────────────────────────────
  function pageQuestions() {
    var p = location.pathname;
    if (/^\/papers\/view\//.test(p)) return ["My paper won't load", "How do I use the ruler and protractor?", "Where's the mark scheme?", "Can I download it with my ink?"];
    if (/^\/papers\/mock-tests/.test(p)) return ["How do mock tests work?", "How many free mock tests do I have left?", "Can I choose the questions myself?"];
    if (/^\/papers/.test(p) || /^\/my-papers/.test(p)) return ["Why is my booklet taking long?", "How many free booklets do I have left?", "My booklet failed to build", "How do I pick only some subtopics?"];
    if (/^\/yearly/.test(p)) return ["Do I need an account for past papers?", "Find a specific paper for me", "Where's the insert / mark scheme?"];
    if (/^\/mcq/.test(p)) return ["How does MCQ practice work?", "Can I time myself like the real exam?", "Where are the answers?"];
    if (/pricing|courses|classes/.test(p)) return ["Which plan fits me?", "I paid - when does my plan start?", "Is there a free trial?", "Tell me about the live classes"];
    if (/^\/whiteboard/.test(p)) return ["How many boards can I make for free?", "Can I share a board?", "Can I import a PDF?"];
    if (/^\/notes|^\/resources/.test(p)) return ["Find notes for a chapter", "Can I practise this chapter?", "Where are the syllabus PDFs?"];
    if (/dashboard|profile|progress/.test(p)) return ["How do streaks work?", "How do I change my subjects?", "How many free booklets do I have left?"];
    if (/login|forgot|reset|set-password/.test(p)) return ["I can't log in", "I forgot my password", "Do I need an account?"];
    return ["What can I do for free?", "Which plan fits me?", "Find a past paper for me", "Tell me about the live classes"];
  }

  // ── DOM ────────────────────────────────────────────────────────────────────
  var css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "/support.css?v=" + V;
  document.head.appendChild(css);

  var root = document.documentElement;
  var launch = document.createElement("div");
  launch.className = "hc-launch";
  launch.id = "pwt-chatbot-wrap";          // tools.css / catalog.css move or hide it by this id
  launch.innerHTML =
    '<span class="hc-hint">Help &amp; support</span>' +
    '<button type="button" class="hc-fab pwt-chatbot-fab" aria-expanded="false" aria-controls="hc-panel" aria-label="Help and support">' +
    '<img src="' + OWL + '" alt="" width="40" height="40"><span class="hc-x" aria-hidden="true">✕</span></button>';
  var fab = launch.querySelector(".hc-fab");

  var panel = document.createElement("section");
  panel.className = "hc-panel";
  panel.id = "hc-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "hc-title");
  panel.hidden = true;
  panel.innerHTML =
    '<header class="hc-head"><img src="' + OWL + '" alt="" width="38" height="38">' +
    '<div class="hc-head-txt"><h2 id="hc-title">PrepWithTee help</h2><p><span class="hc-dot"></span><span data-hours>Answers in seconds · Tee replies by email</span></p></div>' +
    '<button type="button" class="hc-icon-btn" data-new title="New chat" aria-label="Start a new chat">↺</button>' +
    '<button type="button" class="hc-icon-btn" data-close title="Close (Esc)" aria-label="Close help">✕</button></header>' +
    '<nav class="hc-tabs" role="tablist" aria-label="Help sections">' +
    '<button type="button" class="hc-tab" role="tab" data-tab="home" id="hc-t-home" aria-controls="hc-v-home">Home</button>' +
    '<button type="button" class="hc-tab" role="tab" data-tab="chat" id="hc-t-chat" aria-controls="hc-v-chat">Chat</button>' +
    '<button type="button" class="hc-tab" role="tab" data-tab="requests" id="hc-t-requests" aria-controls="hc-v-requests" hidden>My requests</button></nav>' +
    '<div class="hc-body">' +
    '<div class="hc-view" id="hc-v-home" role="tabpanel" aria-labelledby="hc-t-home"></div>' +
    '<div class="hc-view" id="hc-v-chat" role="tabpanel" aria-labelledby="hc-t-chat"><div class="hc-msgs" aria-live="polite"></div></div>' +
    '<div class="hc-view" id="hc-v-handoff" role="tabpanel" aria-label="Send to Tee"></div>' +
    '<div class="hc-view" id="hc-v-requests" role="tabpanel" aria-labelledby="hc-t-requests"></div>' +
    "</div>" +
    '<footer class="hc-foot" data-compose><div class="hc-compose">' +
    '<textarea rows="1" maxlength="1000" placeholder="Ask anything - English or Urdu…" aria-label="Your question"></textarea>' +
    '<button type="button" class="hc-send" aria-label="Send"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/></svg></button></div>' +
    '<div class="hc-foot-note"><span>AI assistant · can make mistakes</span><button type="button" data-handoff>Send this to Tee</button></div></footer>';

  function mount() {
    document.body.appendChild(launch);
    document.body.appendChild(panel);
    if (HIDE_ON.test(location.pathname)) launch.hidden = true;
  }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);

  var body = panel.querySelector(".hc-body");
  var vHome = panel.querySelector("#hc-v-home");
  var vChat = panel.querySelector("#hc-v-chat");
  var vHandoff = panel.querySelector("#hc-v-handoff");
  var vReq = panel.querySelector("#hc-v-requests");
  var msgsEl = vChat.querySelector(".hc-msgs");
  var foot = panel.querySelector("[data-compose]");
  var input = foot.querySelector("textarea");
  var sendBtn = foot.querySelector(".hc-send");
  var tabReq = panel.querySelector('[data-tab="requests"]');

  // ── Open / close ───────────────────────────────────────────────────────────
  var lastFocus = null;
  function isOpen() { return !panel.hidden; }
  function open(tab, ask) {
    if (!isOpen()) {
      lastFocus = document.activeElement;
      panel.hidden = false;
      root.classList.add("hc-open");
      if (innerWidth <= 600) root.classList.add("hc-lock");
      fab.setAttribute("aria-expanded", "true");
      refreshContext();
    }
    show(tab || state.tab || "home");
    if (ask) send(ask);
    save();
  }
  function close() {
    if (!isOpen()) return;
    panel.hidden = true;
    root.classList.remove("hc-open", "hc-lock");
    fab.setAttribute("aria-expanded", "false");
    save();
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
    else if (!launch.hidden) fab.focus();
  }
  fab.addEventListener("click", function () { isOpen() ? close() : open(); });
  panel.querySelector("[data-close]").addEventListener("click", close);
  panel.querySelector("[data-new]").addEventListener("click", function () {
    state.msgs = []; save(); renderChat(); show("chat"); input.focus();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen() && !document.querySelector(".snip-overlay, .lc-wrap")) { e.preventDefault(); close(); }
    if (e.key === "Tab" && isOpen() && panel.contains(document.activeElement)) {
      var f = [].filter.call(panel.querySelectorAll("button, a[href], input, textarea, select, [tabindex]:not([tabindex='-1'])"),
        function (el) { return !el.disabled && el.offsetParent !== null; });
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-support]");
    if (!t || panel.contains(t)) return;
    e.preventDefault();
    open(t.getAttribute("data-support") || "home", t.getAttribute("data-support-ask") || null);
  });

  // ── Tabs ───────────────────────────────────────────────────────────────────
  panel.querySelector(".hc-tabs").addEventListener("click", function (e) {
    var b = e.target.closest("[data-tab]");
    if (b) show(b.getAttribute("data-tab"));
  });
  panel.querySelector(".hc-tabs").addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var tabs = [].filter.call(panel.querySelectorAll(".hc-tab"), function (t) { return !t.hidden; });
    var i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    var n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    n.focus(); show(n.getAttribute("data-tab"));
  });
  function show(tab) {
    if (tab === "requests" && tabReq.hidden) tab = "home";
    view = tab;
    if (tab !== "handoff") state.tab = tab;
    [].forEach.call(panel.querySelectorAll(".hc-tab"), function (t) {
      var on = t.getAttribute("data-tab") === (tab === "handoff" ? "chat" : tab);
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    vHome.hidden = tab !== "home";
    vChat.hidden = tab !== "chat";
    vHandoff.hidden = tab !== "handoff";
    vReq.hidden = tab !== "requests";
    foot.hidden = tab !== "chat";
    if (tab === "home") renderHome();
    if (tab === "chat") { renderChat(); setTimeout(function () { if (innerWidth > 600) input.focus(); }, 30); }
    if (tab === "requests") renderRequests();
    if (tab === "handoff") renderHandoff();
    save();
  }

  // ── Context (who they are, what's wrong) ───────────────────────────────────
  function refreshContext(force) {
    if (!force && ctx && Date.now() - ctxAt < 60000) return Promise.resolve(ctx);
    return api("/api/support/context").then(function (d) {
      ctx = d; ctxAt = Date.now();
      var h = panel.querySelector("[data-hours]");
      var dot = panel.querySelector(".hc-dot");
      if (d.hours) { h.textContent = d.hours.open ? "Answers in seconds · Tee replies within hours" : "Answers in seconds · Tee is offline now"; dot.classList.toggle("on", !!d.hours.open); }
      tabReq.hidden = !d.signed_in;
      if (view === "home") renderHome();
      return d;
    }).catch(function () { return ctx; });
  }

  // ── Home ───────────────────────────────────────────────────────────────────
  function btn(a, cls) {
    var c = "hc-btn" + (cls ? " " + cls : "");
    if (a.kind === "link") {
      var u = safeUrl(a.url);
      if (!u) return "";
      var ext = /^https?:/.test(u);
      return '<a class="' + c + (/wa\.me/.test(u) ? " wa" : "") + '" href="' + esc(u) + '"' + (ext ? ' target="_blank" rel="noopener"' : "") +
        ' data-track="link">' + esc(a.label) + "</a>";
    }
    return '<button type="button" class="' + c + '" data-act="' + esc(JSON.stringify(a)) + '">' + esc(a.label) + "</button>";
  }
  function accountCards(d) {
    var out = [];
    (d.booklets || []).filter(function (b) { return b.status === "failed"; }).slice(0, 1).forEach(function (b) {
      var acts = [];
      if (b.retryable) acts.push({ kind: "retry", label: "Try again", booklet_id: b.id });
      acts.push({ kind: "link", label: "Change my selection", url: b.rebuild_url });
      acts.push({ kind: "handoff", label: "Tell Tee" });
      out.push('<div class="hc-card hc-alert bad"><h3>' + esc(b.title) + " didn't build</h3><p><b>" + esc(b.why) + ".</b> " +
        esc(b.message) + '</p><div class="hc-btns">' + acts.map(function (a, i) { return btn(a, i ? "" : "primary"); }).join("") + "</div></div>");
    });
    var p = d.payment;
    if (p && p.status === "pending") {
      out.push('<div class="hc-card hc-alert"><h3>Payment proof received</h3><p>Your proof for <b>' + esc(p.plan_label) + "</b>" +
        (p.period ? " (" + esc(p.period) + ")" : "") + " from " + esc(dateStr(p.created_at)) +
        " is waiting for Tee to confirm the money arrived - usually within 24 hours. You'll get an email.</p></div>");
    } else if (p && p.status === "rejected") {
      out.push('<div class="hc-card hc-alert bad"><h3>Payment proof not approved</h3><p>' +
        (p.note ? "Tee's note: “" + esc(p.note) + "”" : "Tee couldn't match this payment.") +
        '</p><div class="hc-btns">' + btn({ kind: "link", label: "Upload again", url: "/pricing.html#plans" }, "primary") +
        btn({ kind: "handoff", label: "Ask Tee" }) + "</div></div>");
    }
    return out.join("");
  }

  function renderHome() {
    var d = ctx || {};
    var hello = d.signed_in && d.name ? "Hi " + esc(d.name) + " 👋" : "Hi there 👋";
    var b = d.banner ? '<div class="hc-banner ' + esc(d.banner.tone) + '" role="status"><span aria-hidden="true">' +
      (d.banner.tone === "warn" ? "⚠️" : d.banner.tone === "ok" ? "✅" : "ℹ️") + "</span><span>" + esc(d.banner.text) + "</span></div>" : "";
    vHome.innerHTML = b +
      '<p class="hc-hello">' + hello + '</p><p class="hc-sub">How can we help?</p>' +
      '<div class="hc-search"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>' +
      '<input type="search" placeholder="Search papers, chapters, notes, help…" aria-label="Search help and pages" autocomplete="off"><div class="hc-results" role="listbox" aria-label="Results"></div></div>' +
      (d.signed_in ? accountCards(d) : "") +
      '<p class="hc-label">Common questions</p><div class="hc-qs">' +
      pageQuestions().map(function (q) { return '<button type="button" class="hc-q" data-ask="' + esc(q) + '">' + esc(q) + "</button>"; }).join("") + "</div>" +
      '<div class="hc-card"><div class="hc-tee"><img src="' + TEE + '" alt="" width="44" height="44" loading="lazy"><div><h3>Talk to Tee</h3><p>' +
      esc((d.hours && d.hours.text) || "Tee usually replies within a few hours.") + "</p></div></div>" +
      '<div class="hc-btns">' + btn({ kind: "handoff", label: "Send Tee a message" }, "primary") +
      btn({ kind: "link", label: "WhatsApp", url: d.whatsapp_url || "https://wa.me/923204884375" }) + "</div></div>" +
      '<div class="hc-links"><a href="/features">All features &amp; tips</a><a href="/explore">Every page</a>' +
      (window.pwtShortcuts ? '<button type="button" data-hc-keys>Keyboard shortcuts</button>' : "") + (d.signed_in ? "" : '<a href="/login.html">Sign in</a>') + "</div>";
    var sIn = vHome.querySelector(".hc-search input");
    var sOut = vHome.querySelector(".hc-results");
    sIn.addEventListener("input", function () { searchHome(sIn.value, sOut); });
    sIn.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && sIn.value.trim()) { e.preventDefault(); show("chat"); send(sIn.value.trim()); }
      if (e.key === "ArrowDown") { var f = sOut.querySelector(".hc-result"); if (f) { e.preventDefault(); f.focus(); } }
    });
    sOut.addEventListener("keydown", function (e) {
      var items = [].slice.call(sOut.querySelectorAll(".hc-result")), i = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown" && i < items.length - 1) { e.preventDefault(); items[i + 1].focus(); }
      if (e.key === "ArrowUp") { e.preventDefault(); (i > 0 ? items[i - 1] : sIn).focus(); }
    });
  }
  function searchHome(q, out) {
    q = q.trim();
    if (!q) { out.innerHTML = ""; return; }
    var go = function () {
      var words = q.toLowerCase().split(/\s+/).filter(Boolean);
      var hits = (searchRows || []).map(function (r) {
        var t = r.t.toLowerCase(), hay = t + " " + (r.s || "").toLowerCase() + " " + (r.q || "");
        var sc = 0;
        for (var i = 0; i < words.length; i++) {
          if (t.indexOf(words[i]) >= 0) sc += 3; else if (hay.indexOf(words[i]) >= 0) sc += 1; else return null;
        }
        return { r: r, sc: sc };
      }).filter(Boolean).sort(function (a, b) { return b.sc - a.sc; }).slice(0, 5);
      out.innerHTML = '<button type="button" class="hc-result ask" data-ask="' + esc(q) + '"><b>Ask the assistant: “' + esc(q) +
        '”</b><small>Answers about your account, plans, papers and features</small></button>' +
        hits.map(function (h) {
          return '<a class="hc-result" href="' + esc(h.r.u) + '" data-track="search"><b>' + esc(h.r.t) + "</b><small>" + esc(h.r.s || "") + "</small></a>";
        }).join("");
    };
    if (searchRows) return go();
    fetch("/api/search/index").then(function (r) { return r.json(); }).then(function (rows) { searchRows = rows || []; go(); })
      .catch(function () { searchRows = []; go(); });
  }

  // ── Chat ───────────────────────────────────────────────────────────────────
  function msgHtml(m, i) {
    if (m.role === "user") return '<div class="hc-msg user"><div class="hc-bubble">' + md(m.content) + "</div></div>";
    var acts = (m.actions || []).map(function (a, j) { return btn(a, j ? "" : "primary"); }).join("");
    var cards = (m.links || []).map(function (l) {
      var u = safeUrl(l.u);
      return u ? '<a class="hc-linkcard" href="' + esc(u) + '" data-track="card"><span><b>' + esc(l.t) + "</b><small>" + esc(l.s || "") + "</small></span></a>" : "";
    }).join("");
    var vote = m.event_id ? '<div class="hc-vote"><span>Helpful?</span><button type="button" data-vote="1" data-i="' + i + '" aria-label="Yes, helpful" aria-pressed="' +
      (m.vote === 1) + '">👍</button><button type="button" data-vote="-1" data-i="' + i + '" aria-label="Not helpful" aria-pressed="' + (m.vote === -1) + '">👎</button></div>' : "";
    return '<div class="hc-msg bot"><div class="hc-bubble">' + md(m.content) + (cards ? '<div class="hc-cards">' + cards + "</div>" : "") +
      (acts ? '<div class="hc-btns">' + acts + "</div>" : "") + "</div>" + vote + "</div>";
  }
  function renderChat() {
    if (!state.msgs.length) {
      msgsEl.innerHTML = '<div class="hc-empty"><img src="' + OWL + '" alt="" width="64" height="64"><p><b>Ask me anything about PrepWithTee</b><br>' +
        "Your plan and payments, building papers, finding a past paper, classes - in English or Urdu.</p></div>" +
        '<div class="hc-qs">' + pageQuestions().slice(0, 3).map(function (q) {
          return '<button type="button" class="hc-q" data-ask="' + esc(q) + '">' + esc(q) + "</button>";
        }).join("") + "</div>";
    } else {
      msgsEl.innerHTML = state.msgs.map(msgHtml).join("");
    }
    if (sending) msgsEl.insertAdjacentHTML("beforeend", '<div class="hc-msg bot" data-typing><div class="hc-bubble"><span class="hc-typing" aria-label="Typing"><i></i><i></i><i></i></span></div></div>');
    body.scrollTop = body.scrollHeight;
  }
  function send(text) {
    text = String(text || "").trim();
    if (!text || sending) return;
    if (view !== "chat") show("chat");
    state.msgs.push({ role: "user", content: text.slice(0, 1000) });
    sending = true; sendBtn.disabled = true;
    save(); renderChat();
    var history = state.msgs.slice(-9, -1).map(function (m) { return { role: m.role, content: m.content }; });
    api("/api/support/chat", { method: "POST", body: { message: text, history: history, page: location.pathname } })
      .then(function (d) {
        state.msgs.push({ role: "assistant", content: d.reply, links: d.links || [], actions: d.actions || [], event_id: d.event_id, intent: d.intent });
      })
      .catch(function (e) {
        state.msgs.push({ role: "assistant", content: (e && e.message) || "I couldn't connect just now - check your internet and try again.",
          actions: [{ kind: "handoff", label: "Send this to Tee" }] });
      })
      .then(function () {
        sending = false; sendBtn.disabled = false;
        save(); renderChat();
        if (!isOpen()) bumpBadge(1);
      });
  }
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(120, input.scrollHeight) + "px"; }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); var v = input.value; input.value = ""; autosize(); send(v); }
  });
  sendBtn.addEventListener("click", function () { var v = input.value; input.value = ""; autosize(); send(v); input.focus(); });
  foot.querySelector("[data-handoff]").addEventListener("click", function () { show("handoff"); });

  // ── Actions (one-tap fixes) ────────────────────────────────────────────────
  panel.addEventListener("click", function (e) {
    var t = e.target.closest("[data-ask], [data-act], [data-vote], [data-track], [data-hc-keys], [data-goto]");
    if (!t) return;
    if (t.hasAttribute("data-goto")) { show(t.getAttribute("data-goto")); return; }
    if (t.hasAttribute("data-hc-keys")) { close(); window.pwtShortcuts.open(); return; }
    if (t.hasAttribute("data-track")) { track(t.getAttribute("data-track")); return; }
    if (t.hasAttribute("data-ask")) { send(t.getAttribute("data-ask")); return; }
    if (t.hasAttribute("data-vote")) { vote(+t.getAttribute("data-i"), +t.getAttribute("data-vote")); return; }
    var a;
    try { a = JSON.parse(t.getAttribute("data-act")); } catch (_) { return; }
    act(a, t);
  });
  function act(a, el) {
    track(a.kind);
    if (a.kind === "say") return send(a.text || a.label);
    if (a.kind === "handoff") return show("handoff");
    if (a.kind === "retry") {
      el.disabled = true; el.textContent = "Starting…";
      return api("/api/booklets/" + encodeURIComponent(a.booklet_id) + "/retry", { method: "POST" })
        .then(function () { location.href = "/papers/view/" + encodeURIComponent(a.booklet_id); })
        .catch(function (e) { el.disabled = false; el.textContent = a.label; reply(e.message, [{ kind: "handoff", label: "Send this to Tee" }]); });
    }
    if (a.kind === "trial") {
      el.disabled = true; el.textContent = "Starting your trial…";
      return api("/api/me/trial", { method: "POST" })
        .then(function (d) {
          reply("🎉 **Your free " + (d.days || 7) + "-day trial is on.** Everything is unlocked until " + dateStr(d.expires_at) +
            ". Reload any page you have open to see it.", [{ kind: "link", label: "Build a topical paper", url: "/papers/topical" }]);
          refreshContext(true);
        })
        .catch(function (e) { el.disabled = false; el.textContent = a.label; reply(e.message, []); });
    }
  }
  function reply(text, actions) {
    state.msgs.push({ role: "assistant", content: text, actions: actions || [] });
    save(); show("chat");
  }
  function vote(i, v) {
    var m = state.msgs[i];
    if (!m || !m.event_id) return;
    m.vote = v; save(); renderChat();
    api("/api/support/vote", { method: "POST", body: { event_id: m.event_id, vote: v } }).catch(function () {});
    if (v < 0 && !m.offered) {
      m.offered = true;
      reply("Sorry that didn't help. Tee can look at it personally - the reply comes back here and by email.",
        [{ kind: "handoff", label: "Send this to Tee" }]);
    }
  }

  // ── Handoff ────────────────────────────────────────────────────────────────
  var snips = null;
  function renderHandoff() {
    var d = ctx || {};
    var lastQ = "";
    for (var i = state.msgs.length - 1; i >= 0; i--) if (state.msgs[i].role === "user") { lastQ = state.msgs[i].content; break; }
    var dg = collectDiag();
    vHandoff.innerHTML =
      '<div class="hc-card"><h3>Send this to Tee</h3><p>' + esc((d.hours && d.hours.text) || "Tee usually replies within a few hours.") +
      " The reply comes back here" + (d.signed_in ? " (My requests)" : "") + " and by email.</p></div>" +
      '<form class="hc-form" novalidate>' +
      '<label>YOUR NAME<input name="name" autocomplete="name" required value="' + esc(d.full_name || "") + '"></label>' +
      '<label>EMAIL FOR THE REPLY<input name="email" type="email" autocomplete="email" required value="' + esc(d.email || "") + '"></label>' +
      '<label>WHAT DO YOU NEED HELP WITH?<textarea name="message" maxlength="2000" placeholder="What happened, and what did you expect?">' + esc(lastQ) + "</textarea></label>" +
      '<div data-snips></div>' +
      '<details class="hc-diag"><summary>Sent with it automatically</summary><ul>' +
      "<li>This page: " + esc(dg.url) + "</li><li>Your browser and screen size</li>" +
      (state.msgs.length ? "<li>This chat (" + state.msgs.length + " messages)</li>" : "") +
      (dg.errors.length || dg.failed.length ? "<li>" + (dg.errors.length + dg.failed.length) + " error(s) from this page</li>" : "") +
      "</ul></details>" +
      '<p class="hc-err" role="alert" hidden></p>' +
      '<div class="hc-btns"><button type="submit" class="hc-btn primary">Send to Tee</button>' +
      '<button type="button" class="hc-btn" data-back>Back</button></div></form>';
    var form = vHandoff.querySelector("form");
    var err = form.querySelector(".hc-err");
    form.querySelector("[data-back]").addEventListener("click", function () { show(state.msgs.length ? "chat" : "home"); });
    snips = null;
    import("/snip.js?v=20261005a").then(function (m) {
      snips = m.snipField(form.querySelector("[data-snips]"), { v: "20261005a", hide: function () { return [panel, launch]; } });
    }).catch(function () { form.querySelector("[data-snips]").hidden = true; });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var b = form.querySelector("[type=submit]");
      err.hidden = true;
      var payload = {
        name: form.name.value.trim(), email: form.email.value.trim(), message: form.message.value.trim(),
        transcript: state.msgs.map(function (m) { return { role: m.role, content: m.content }; }),
        page: location.pathname + location.search, diag: collectDiag(), snips: snips ? snips.get() : [],
      };
      if (payload.name.length < 2) { err.textContent = "Please enter your name."; err.hidden = false; form.name.focus(); return; }
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(payload.email)) { err.textContent = "Please enter an email Tee can reply to."; err.hidden = false; form.email.focus(); return; }
      if (!payload.message && !payload.transcript.length) { err.textContent = "Tell Tee what you need help with."; err.hidden = false; form.message.focus(); return; }
      b.disabled = true; b.textContent = "Sending…";
      api("/api/support/handoff", { method: "POST", body: payload }).then(function (d) {
        try { localStorage.setItem(HAS_THREADS, "1"); } catch (_) {}
        threads = null;
        vHandoff.innerHTML = '<div class="hc-card hc-done"><b>✓ Sent to Tee</b><p>' + esc((d.hours && d.hours.text) || "") +
          " We'll email " + esc(payload.email) + "." + (ctx && ctx.signed_in ? " You'll also see the reply under My requests." : "") +
          '</p><div class="hc-btns" style="justify-content:center"><button type="button" class="hc-btn" data-goto="chat">Back to chat</button></div></div>';
        state.msgs.push({ role: "assistant", content: "✓ Sent to Tee. " + ((d.hours && d.hours.text) || "") });
        save();
      }).catch(function (e2) {
        b.disabled = false; b.textContent = "Send to Tee";
        err.textContent = e2.message; err.hidden = false;
      });
    });
  }

  // ── My requests + reply badge ──────────────────────────────────────────────
  function seenMap() { try { return JSON.parse(localStorage.getItem(SEEN)) || {}; } catch (_) { return {}; } }
  function unseen(list) {
    var s = seenMap(), n = 0;
    (list || []).forEach(function (t) { if ((t.replies || []).length > (s[t.id] || 0)) n++; });
    return n;
  }
  function loadThreads() {
    return api("/api/support/threads").then(function (d) {
      threads = d.threads || [];
      try { localStorage.setItem(HAS_THREADS, threads.length ? "1" : ""); localStorage.setItem(HAS_THREADS + "-at", String(Date.now())); } catch (_) {}
      paintBadge();
      return threads;
    });
  }
  function renderRequests() {
    vReq.innerHTML = '<p class="hc-empty">Loading…</p>';
    loadThreads().then(function (list) {
      var s = seenMap();
      if (!list.length) {
        vReq.innerHTML = '<div class="hc-empty"><img src="' + OWL + '" alt="" width="64" height="64"><p>Nothing sent to Tee yet.</p>' +
          '<div class="hc-btns" style="justify-content:center">' + btn({ kind: "handoff", label: "Send Tee a message" }, "primary") + "</div></div>";
        return;
      }
      vReq.innerHTML = list.map(function (t) {
        var fresh = (t.replies || []).length > (s[t.id] || 0);
        return '<article class="hc-thread' + (fresh ? " hc-new" : "") + '"><div class="hc-thread-top"><span>' + esc(dateStr(t.at)) +
          (t.page ? " · " + esc(t.page) : "") + '</span><span class="hc-status ' + esc(t.status) + '">' +
          esc(t.status === "new" ? "Waiting" : t.status === "replied" ? "Tee replied" : t.status === "handled" ? "Done" : t.status) + "</span></div>" +
          "<p>" + esc(t.message) + "</p>" +
          (t.replies || []).map(function (r) { return '<div class="hc-reply"><small>Tee · ' + esc(dateStr(r.at)) + "</small>" + esc(r.body) + "</div>"; }).join("") +
          "</article>";
      }).join("");
      list.forEach(function (t) { s[t.id] = (t.replies || []).length; });
      try { localStorage.setItem(SEEN, JSON.stringify(s)); } catch (_) {}
      paintBadge();
    }).catch(function () { vReq.innerHTML = '<p class="hc-empty">Sign in to see your requests.</p>'; });
  }
  var chatUnread = 0;
  function bumpBadge(n) { chatUnread += n; paintBadge(); }
  function paintBadge() {
    var n = chatUnread + unseen(threads);
    var b = fab.querySelector(".hc-badge");
    if (!n || isOpen()) { if (b) b.remove(); } else {
      if (!b) { b = document.createElement("span"); b.className = "hc-badge"; fab.appendChild(b); }
      b.textContent = n > 9 ? "9+" : String(n);
    }
    var tb = tabReq.querySelector(".hc-badge"), u = unseen(threads);
    if (u) { if (!tb) { tb = document.createElement("span"); tb.className = "hc-badge"; tabReq.appendChild(tb); } tb.textContent = String(u); }
    else if (tb) tb.remove();
    fab.setAttribute("aria-label", n ? "Help and support - " + n + " new" : "Help and support");
  }
  fab.addEventListener("click", function () { chatUnread = 0; paintBadge(); });
  // Someone who sent Tee a message: check for a reply now and then (at most every 10 min).
  try {
    if (localStorage.getItem(HAS_THREADS) && Date.now() - (+localStorage.getItem(HAS_THREADS + "-at") || 0) > 600000) {
      setTimeout(function () { loadThreads().catch(function () {}); }, 2500);
    }
  } catch (_) {}

  window.pwtSupport = {
    open: function (tab, ask) { open(tab, ask); },
    ask: function (q) { open("chat", q); },
    close: close,
    report: function () { open("handoff"); },
  };
})();
