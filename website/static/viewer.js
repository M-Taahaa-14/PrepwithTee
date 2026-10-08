/* viewer.js — /papers/view/{id}: build loader, then the booklet rendered in-site.
 *
 *   loader   polls /api/booklets/{id}/status and shows the real build stages
 *   pages    pdf-pane.js (PDF.js, lazy pages, annotation layer so contents
 *            links and the fillable answer sheet work)
 *   contents drawer built from the page map (Q number, source, chapter)
 *   chips    per question: Explain / Guide me / Mark scheme -> ai-panel.js
 *   tests    a mock test (kind "test") has no chips: Test / Mark scheme tabs, a
 *            countdown, and the separate mark scheme unlocks on "Finish test"
 *   sharing  the teacher who built it gets Share (assign to their students /
 *            groups, a share link, who opened / finished) and Edit (back to the
 *            builder's review step). A student it was shared with finishes on
 *            the server, which decides whether the mark scheme opens
 *            (after finishing / straight away / teacher keeps it).
 */
import { api } from "/auth.js?v=20261005c";
import { openAiPanel } from "/ai-panel.js?v=20260927a";
import { PdfPane, debounce } from "/pdf-pane.js?v=20261005a";
import { paperButton } from "/paper-theme.js?v=20260928a";
import { createAnnotator } from "/annotate.js?v=20261005c";

const SNIP_V = "20261005a";                 // = main.js SNIP_V
const S = JSON.parse(document.getElementById("vw-state").textContent);
const root = document.getElementById("vw");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// The viewer fills the window under the site header, whatever its height.
const header = document.querySelector(".site-header");
const sizeTop = () => document.documentElement.style.setProperty(
  "--vw-top", `${header ? header.getBoundingClientRect().bottom : 0}px`);
sizeTop();
window.addEventListener("resize", sizeTop);
// Only the stage scrolls. scrollIntoView (focus moves, find-in-page) can still
// nudge an overflow:hidden window and hide the toolbar, so pin it back.
window.addEventListener("scroll", () => {
  if (window.scrollY) window.scrollTo(0, 0);
}, { passive: true });

const TEST = S.kind === "test";
const SHARED = S.role === "shared";
const CROP = "Cropping questions from the original papers";
const STAGES = TEST ? [
  ["Picking questions", 1],
  [CROP, 4],
  ["Writing the separate mark scheme", 64],
  ["Finishing your paper", 96],
] : [
  ["Picking questions", 1],
  ["Mixing your chapters together", 3],
  [CROP, 5],
  ["Adding official mark schemes", 60],
  ["Building the clickable contents page", 90],
  ["Finishing your paper", 96],
];
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ── Loader ──────────────────────────────────────────────────────────────────
function loader(st) {
  const p = st.progress || 0;
  const done = STAGES.filter(([, at]) => p > at).length;
  const detail = (st.stage || "").split(" · ")[1];
  root.dataset.state = "loading";
  root.innerHTML = `
    <section class="vw-load" aria-live="polite">
      <div class="vw-load-card">
        <p class="vw-eyebrow">${TEST ? "Mock test" : "Topical paper"}</p>
        <h1>${esc(S.title.split(" — ")[0])}</h1>
        <div class="vw-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
             aria-valuenow="${p}"><i style="width:${Math.max(4, p)}%"></i></div>
        <ol class="vw-stages">${STAGES.map(([label], i) => `
          <li class="${i < done ? "is-done" : i === done ? "is-now" : ""}">
            <span class="vw-dot" aria-hidden="true">${i < done ? "✓" : ""}</span>
            ${label}${i === done && detail && label === CROP ? ` <b>${esc(detail)}</b>` : ""}
          </li>`).join("")}</ol>
        <p class="vw-tip">${TEST ? "Tip: work under exam conditions — the mark scheme unlocks when you press <b>Finish test</b>."
          : "Tip: stuck on a question? Tap <b>Guide me</b> for a hint before you open the full <b>Explain</b>."}</p>
      </div>
    </section>`;
}

// ── Failure ─────────────────────────────────────────────────────────────────
// Every failed build says WHAT happened and WHAT to do (the server classifies
// it: busy, interrupted, timeout, too_big, missing_source, internal). Problems
// only Tee can fix open the report form straight away.
function failed(info) {
  const st = typeof info === "string" ? { error: info } : (info || {});
  const code = st.error_code || "internal";
  const retry = st.retryable !== false;
  const me = S.me || {};
  root.dataset.state = "failed";
  root.innerHTML = `
    <section class="vw-load"><div class="vw-load-card vw-fail" role="alert">
      <p class="vw-eyebrow">Your paper wasn't built</p>
      <h1>${esc(st.error_title || "We couldn't build this paper")}</h1>
      <p>${esc(st.error || "Something went wrong on our side. Please try again.")}</p>
      <div class="vw-fail-acts">
        ${retry ? `<button type="button" class="vw-btn" data-fail="retry">Try again</button>` : ""}
        <a class="vw-btn ${retry ? "vw-btn-ghost" : ""}" href="${esc(S.rebuildUrl || S.subjectUrl + "#builder")}">Change my selection</a>
        <button type="button" class="vw-btn vw-btn-ghost" data-fail="report"
                aria-expanded="${st.attention ? "true" : "false"}" aria-controls="vw-report">Report this problem</button>
      </div>
      <form id="vw-report" class="vw-report" ${st.attention ? "" : "hidden"}>
        <p class="vw-report-lead">Tell Tee what happened - the technical details of this build are
          attached automatically, so you only need to add anything else you noticed.</p>
        <label>Your name <input name="name" required minlength="2" maxlength="120" value="${esc(me.name)}"></label>
        <label>Email (so we can tell you when it's fixed)
          <input name="email" type="email" required value="${esc(me.email)}"></label>
        <label><span>What were you trying to build? <span class="vw-opt">(optional)</span></span>
          <textarea name="message" rows="3" maxlength="1200"
            placeholder="e.g. I picked 4 chapters with 40 questions from 2015-2025"></textarea></label>
        <div class="vw-snips"></div>
        <p class="vw-ref">Reference: <code>${esc(S.id)} · ${esc(code)}</code></p>
        <div class="vw-fail-acts"><button class="vw-btn" type="submit">Send to Tee</button></div>
        <p class="vw-report-msg" role="status"></p>
      </form>
    </div></section>`;
  root.querySelector('[data-fail="retry"]')?.addEventListener("click", retryBuild);
  const form = root.querySelector("#vw-report");
  root.querySelector('[data-fail="report"]').addEventListener("click", (e) => {
    form.hidden = !form.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!form.hidden));
    if (!form.hidden) form.querySelector("input,textarea")?.focus();
  });
  // Optional screenshot of the page (snip.js), loaded when the form is first opened.
  const field = form.querySelector(".vw-snips");
  const mount = () => {
    if (form._snips) return;
    form._snips = { get: () => [] };
    import(`/snip.js?v=${SNIP_V}`).then((m) => {
      form._snips = m.snipField(field, { v: SNIP_V, hide: () => [] });
    }).catch(() => { field.hidden = true; });
  };
  if (!form.hidden) mount();
  root.querySelector('[data-fail="report"]').addEventListener("click", mount);
  form.addEventListener("submit", (e) => sendReport(e, form, st, code));
}

async function sendReport(e, form, st, code) {
  e.preventDefault();
  const btn = form.querySelector('[type="submit"]');
  const msg = form.querySelector(".vw-report-msg");
  const f = new FormData(form);
  const note = String(f.get("message") || "").trim();
  btn.disabled = true;
  msg.textContent = "Sending…";
  try {
    await api("/api/feedback", { method: "POST", body: {
      type: "issue", page: location.pathname, snips: form._snips ? form._snips.get() : [],
      name: String(f.get("name") || "").trim(), email: String(f.get("email") || "").trim(),
      message: `${note || "(no message)"}\n\n--- Topical paper build failed ---\n` +
               `Booklet: ${S.id}\nPaper: ${S.title}\nSubject: ${S.syllabus}\n` +
               `Cause: ${code}${st.skipped ? ` (${st.skipped} question(s) had missing source papers)` : ""}\n` +
               `Shown to student: ${st.error || "-"}\nBrowser: ${navigator.userAgent}` } });
    form.innerHTML = `<p class="vw-report-done">Thanks - Tee has your report and will get back to you by email.</p>`;
  } catch (err) {
    btn.disabled = false;
    msg.textContent = err.message || "Couldn't send - please try again.";
  }
}

async function retryBuild(e) {
  e.currentTarget.disabled = true;
  try {
    await api(`/api/booklets/${S.id}/retry`, { method: "POST" });
  } catch (err) {
    // 409 = it's no longer failed (another tab retried it) - just wait for it.
    if (!/failed state/.test(err.message || "")) { failed({ error: err.message, error_code: "retry" }); return; }
  }
  loader({ progress: 0, stage: "Trying again" });
  open().catch(lostContact);
}

function lostContact(e) {
  failed({ error_title: "We lost contact with the server",
           error: `${e?.message || "The connection dropped."} Your paper may still be building - ` +
                  "check your internet connection and press Try again, or open it later from My papers.",
           error_code: "network", retryable: true });
}

// A single failed status poll (a blip on mobile data, a worker restarting)
// used to end the page with a bare error. Keep polling; give up only when the
// server has been unreachable for ~45 s.
async function waitReady() {
  let misses = 0;
  for (;;) {
    let st;
    try { st = await api(`/api/booklets/${S.id}/status`, { timeout: 15000 }); misses = 0; }
    catch (e) {
      if (/not found/i.test(e.message || "") || ++misses >= 6) { lostContact(e); return false; }
      await new Promise((r) => setTimeout(r, 1500 * misses));
      continue;
    }
    if (st.status === "ready") { S.skipped = st.skipped || 0; return true; }
    if (st.status === "failed" || st.status === "expired") {
      failed(st.status === "expired" ? { ...st, error_title: "This paper has expired", retryable: false } : st);
      return false;
    }
    loader(st);
    await new Promise((r) => setTimeout(r, 900));
  }
}

// ── Viewer ──────────────────────────────────────────────────────────────────
let pane = null;
let questions = [];

async function open() {
  if (!(await waitReady())) return;
  loader({ progress: 99, stage: "Opening" });
  const meta = await api(`/api/booklets/${S.id}`);
  questions = (meta.page_map_json || { questions: [] }).questions || [];
  shell();
  if (S.skipped) {
    const n = S.skipped;
    root.insertAdjacentHTML("afterbegin", `<p class="vw-note" role="status">${n} question${n === 1 ? " was" : "s were"}
      left out because ${n === 1 ? "its" : "their"} original paper is missing on our server - the rest of your paper is complete.
      <button type="button" aria-label="Dismiss">×</button></p>`);
    root.querySelector(".vw-note button").addEventListener("click", (e) => e.currentTarget.parentElement.remove());
  }
  const ann = createAnnotator({ mount: document.body });
  pane = new PdfPane(document.getElementById("vw-stage"), {
    questions, ranged: true, uniform: true,      // first page long before the whole file
    onPageEl: (el, n) => ann.attach(el, `booklet:${S.id}`, n),
    onPage: (n) => { document.getElementById("vw-pn").textContent = n; },
    onZoom: (label) => { document.getElementById("vw-z").textContent = label; },
    onQuestion: qbar,
  });
  panes.paper = pane;
  annotator = ann;
  await pane.load(`/api/booklets/${S.id}/pdf`);
  document.getElementById("vw-pt").textContent = pane.numPages;
  window.addEventListener("resize", debounce(() => pane.refit(), 200));
  if (TEST && finished()) showPart("ms");
}

// ── Mock tests: paper / mark scheme, timer, finish ──────────────────────────
const panes = { paper: null, ms: null };
let annotator = null;
let part = "paper";
// A shared student's "finished" and "may see the scheme" come from the server;
// the owner's own tests keep the local unlock.
const finished = () => (SHARED ? !!S.finished : store.get(`test-done:${S.id}`) === "1");
const msOpen = () => (SHARED ? !!S.ms_open : finished());
const minutes = Math.max(5, Math.round(S.totalMarks || 20));   // the cover's "1 minute per mark"

async function showPart(which) {
  if (which === "ms" && !msOpen()) return;
  part = which;
  document.querySelectorAll("[data-part]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.part === which)));
  document.getElementById("vw-stage").hidden = which !== "paper";
  const ms = document.getElementById("vw-stage-ms");
  ms.hidden = which !== "ms";
  document.querySelector(".vw-dl").href = `/api/booklets/${S.id}/pdf?download=1${which === "ms" ? "&part=ms" : ""}`;
  document.querySelector(".vw-dl-ink").href = `/api/booklets/${S.id}/pdf?annotated=1${which === "ms" ? "&part=ms" : ""}`;
  pane = panes[which] || pane;
  if (which === "ms" && !panes.ms) {
    panes.ms = new PdfPane(ms, {
      questions: [], ranged: true, uniform: true,
      onPageEl: (el, n) => annotator.attach(el, `booklet:${S.id}:ms`, n),
      onPage: (n) => { if (part === "ms") document.getElementById("vw-pn").textContent = n; },
      onZoom: (label) => { document.getElementById("vw-z").textContent = label; },
    });
    pane = panes.ms;
    await panes.ms.load(`/api/booklets/${S.id}/pdf?part=ms`);
  }
  document.getElementById("vw-pt").textContent = pane.numPages || "…";
  pane.refit?.();
}

async function finishTest() {
  const keeps = SHARED && S.ms_policy === "teacher_only";
  if (!finished() && !confirm(keeps ? "Finish the test? Your teacher will be told you're done."
                                    : "Finish the test and unlock the mark scheme?")) return;
  try {
    const r = await api(`/api/booklets/${S.id}/finish`, { method: "POST" });
    if (SHARED) { S.finished = true; S.ms_open = r.ms_open; }
  } catch (e) {
    if (SHARED) { alert(e.message || "Couldn't reach the server - try again."); return; }
  }
  store.set(`test-done:${S.id}`, "1");
  timer.stop();
  document.querySelector("[data-act=finish]")?.remove();
  const lock = document.querySelector('[data-part="ms"]');
  if (!msOpen()) {
    lock.title = "Your teacher keeps the mark scheme for this test";
    lock.textContent = "✓ Finished";
    return;
  }
  lock.disabled = false;
  lock.removeAttribute("title");
  lock.textContent = "Mark scheme";
  showPart("ms");
}

const timer = {
  left: minutes * 60, id: null,
  fmt(sec) {
    const m = Math.floor(Math.abs(sec) / 60), r = Math.abs(sec) % 60;
    return `${sec < 0 ? "+" : ""}${m}:${String(r).padStart(2, "0")}`;
  },
  paint() {
    const el = document.getElementById("vw-timer");
    if (!el) return;
    el.querySelector("b").textContent = this.fmt(this.left);
    el.classList.toggle("is-low", this.left <= 300 && this.left > 0);
    el.classList.toggle("is-over", this.left <= 0);
  },
  toggle() {
    if (this.id) { this.stop(); return; }
    this.id = setInterval(() => { this.left -= 1; this.paint(); }, 1000);
    const el = document.getElementById("vw-timer");
    el.setAttribute("aria-pressed", "true");
    el.querySelector("span").textContent = "Pause";
  },
  stop() {
    clearInterval(this.id); this.id = null;
    const el = document.getElementById("vw-timer");
    if (!el) return;
    el.setAttribute("aria-pressed", "false");
    el.querySelector("span").textContent = "Start";
  },
};

function shell() {
  root.dataset.state = "ready";
  root.innerHTML = `
    <header class="vw-tools">
      <a class="vw-back" href="${S.subjectUrl}#builder" title="Back to the builder">←</a>
      ${TEST ? `<div class="vw-seg" role="tablist" aria-label="Paper or mark scheme">
          <button type="button" role="tab" data-part="paper" aria-selected="true">Test</button>
          <button type="button" role="tab" data-part="ms" aria-selected="false" ${msOpen() ? "" : "disabled"}
            ${msOpen() ? "" : `title="${SHARED && S.ms_policy === "teacher_only" ? "Your teacher keeps the mark scheme for this test" : "Unlocks when you finish the test"}"`}>${msOpen() ? "Mark scheme" : finished() ? "✓ Finished" : "🔒 Mark scheme"}</button>
        </div>` : `<button type="button" class="vw-tbtn" data-act="toc" aria-expanded="false"
              aria-controls="vw-toc">☰ <span>Contents</span></button>`}
      <h1 class="vw-title" title="${esc(S.title)}">${esc(S.title)}</h1>
      ${TEST ? `<button type="button" class="vw-tbtn vw-timer" id="vw-timer" data-act="timer" aria-pressed="false"
          title="Suggested time: about ${minutes} minutes">⏱ <b>${timer.fmt(timer.left)}</b> <span>Start</span></button>
        ${finished() ? "" : '<button type="button" class="vw-btn vw-finish" data-act="finish">Finish test</button>'}` : ""}
      <span class="vw-pageno" aria-live="polite">Page <b id="vw-pn">1</b> / <span id="vw-pt">…</span></span>
      <div class="vw-zoom" role="group" aria-label="Zoom">
        <button type="button" class="vw-tbtn" data-act="out" aria-label="Zoom out">−</button>
        <button type="button" class="vw-tbtn" data-act="fit" id="vw-z">100%</button>
        <button type="button" class="vw-tbtn" data-act="in" aria-label="Zoom in">+</button>
      </div>
      ${TEST && (S.role === "owner" || S.role === "staff") ? `<a class="vw-tbtn" href="${esc(S.editUrl)}"
          title="Back to Review &amp; customise with these questions - build a new version">✎ <span>Edit</span></a>` : ""}
      ${S.can_share ? `<button type="button" class="vw-btn vw-btn-ghost" data-act="share">⇪ <span>Share</span></button>` : ""}
      ${paperButton()}
      <a class="vw-tbtn vw-dl-ink" href="/api/booklets/${S.id}/pdf?annotated=1"
         title="Download with your pen, highlighter and text marks">✎ <span>With my ink</span></a>
      <a class="vw-btn vw-dl" href="/api/booklets/${S.id}/pdf?download=1">⤓ <span>Download</span></a>
    </header>
    <div class="vw-body">
      <nav class="vw-toc" id="vw-toc" hidden aria-label="Contents">
        <div class="vw-toc-head">${questions.length} questions</div>
        <ol>${questions.map((q) => `
          <li><button type="button" data-goto="${q.seq}">
            <b>Q${q.seq}</b><span>${esc(q.ref)}</span><em>${esc(q.topic || "")}</em>
          </button></li>`).join("")}</ol>
      </nav>
      <div class="vw-stage" id="vw-stage" tabindex="0" aria-label="Paper"></div>
      ${TEST ? '<div class="vw-stage" id="vw-stage-ms" tabindex="0" aria-label="Mark scheme" hidden></div>' : ""}
      <aside class="vw-panel" id="vw-panel" hidden aria-label="Question help"></aside>
    </div>
    <div class="vw-qbar" id="vw-qbar" hidden></div>`;
}

function refitSoon() {
  if (window.innerWidth >= 1000) pane?.refit();
}

function qbar(q) {
  const bar = document.getElementById("vw-qbar");
  document.body.classList.toggle("has-dock", !!q);
  if (!q) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.innerHTML = `<b>Q${q.seq}</b><span>${esc(q.topic || "")}</span>
    <button type="button" data-open="explain" data-seq="${q.seq}" class="vw-chip">✦ Explain</button>
    <button type="button" data-open="hint" data-seq="${q.seq}" class="vw-chip">💡 Hint</button>
    ${q.qid ? `<a href="/whiteboard/new?q=${q.qid}" target="_blank" rel="noopener" class="vw-chip">🖊️ Board</a>` : ""}`;
}

// ── Side panel (ai-panel.js: Explain · Guide me · Mark scheme · Ask) ─────────
function openPanel(seq, tab = "explain") {
  const q = questions.find((x) => x.seq === +seq);
  if (!q) return;
  const panel = document.getElementById("vw-panel");
  const wasHidden = panel.hidden;
  panel.hidden = false;
  root.classList.add("has-panel");
  if (wasHidden) refitSoon();
  openAiPanel(panel, q, { tab, onClose: closePanel });
}

function closePanel() {
  const panel = document.getElementById("vw-panel");
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  root.classList.remove("has-panel");
  refitSoon();
}

// ── Events ──────────────────────────────────────────────────────────────────
root.addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "in") pane?.zoomIn();
  else if (act === "out") pane?.zoomOut();
  else if (act === "fit") pane?.zoomFit();
  else if (act === "close") closePanel();
  else if (act === "timer") timer.toggle();
  else if (act === "finish") finishTest();
  else if (act === "share") openShare();
  else if (act === "toc") {
    const toc = document.getElementById("vw-toc");
    toc.hidden = !toc.hidden;
    e.target.closest("[data-act]").setAttribute("aria-expanded", String(!toc.hidden));
    refitSoon();
  }
  const tab = e.target.closest("[data-part]");
  if (tab && !tab.disabled) showPart(tab.dataset.part);
  const go = e.target.closest("[data-goto]");
  if (go) {
    pane?.scrollToQuestion(go.dataset.goto);
    if (window.innerWidth < 900) document.getElementById("vw-toc").hidden = true;
  }
  const openBtn = e.target.closest("[data-open]");
  if (openBtn) openPanel(openBtn.dataset.seq, openBtn.dataset.open);
});

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.key === "Escape") closePanel();
  if ((e.ctrlKey || e.metaKey) && (e.key === "=" || e.key === "+")) { e.preventDefault(); pane?.zoomIn(); }
  if ((e.ctrlKey || e.metaKey) && e.key === "-") { e.preventDefault(); pane?.zoomOut(); }
});

// ── Share (teachers) ────────────────────────────────────────────────────────
const POLICY = {
  after_finish: "After they press Finish test",
  now: "Straight away",
  teacher_only: "Never - I'll go through it with them",
};
let shareDlg = null;

async function openShare() {
  if (!shareDlg) {
    shareDlg = document.createElement("dialog");
    shareDlg.className = "vw-share";
    shareDlg.setAttribute("aria-label", "Share this paper");
    document.body.appendChild(shareDlg);
    shareDlg.addEventListener("click", onShareClick);
    shareDlg.addEventListener("submit", (e) => e.preventDefault());
  }
  shareDlg.innerHTML = `<div class="vw-share-load">Loading…</div>`;
  if (!shareDlg.open) shareDlg.showModal();
  try {
    renderShare(await api(`/api/booklets/${S.id}/shares`));
  } catch (e) {
    shareDlg.innerHTML = `<p class="vw-share-err">${esc(e.message)}</p>
      <div class="vw-share-foot"><button type="button" class="vw-btn vw-btn-ghost" data-sh="close">Close</button></div>`;
  }
}

function policySelect(name, value) {
  if (!TEST) return "";
  return `<label class="vw-share-field">Mark scheme opens
    <select name="${name}">${Object.entries(POLICY).map(([k, v]) =>
      `<option value="${k}" ${k === value ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>`;
}

const when = (ts) => ts ? new Date(ts).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";

function renderShare(d) {
  const have = new Set(d.shares.map((x) => x.student_id));
  const link = d.link ? location.origin + d.link : "";
  shareDlg.innerHTML = `
    <header class="vw-share-head"><h2>Share this ${TEST ? "test" : "paper"}</h2>
      <button type="button" class="vw-share-x" data-sh="close" aria-label="Close">×</button></header>
    <div class="vw-share-body">
      <section>
        <h3>Give it to my students</h3>
        <p class="vw-share-hint">Each student gets it as homework and opens this same paper with their own ink.</p>
        ${d.groups.length ? `<div class="vw-share-list">${d.groups.map((g) => `<label>
            <input type="checkbox" name="g" value="${g.id}"> 👥 ${esc(g.name)}${g.syllabus ? ` <small>${esc(g.syllabus)}</small>` : ""}</label>`).join("")}</div>` : ""}
        ${d.students.length ? `<div class="vw-share-list">${d.students.map((s) => `<label>
            <input type="checkbox" name="s" value="${esc(s.id)}" ${have.has(s.id) ? "disabled" : ""}>
            ${esc(s.name || s.email)} <small>${have.has(s.id) ? "already has it" : esc(s.syllabus || "")}</small></label>`).join("")}</div>`
          : `<p class="vw-share-hint">No students are assigned to you yet - use the link below.</p>`}
        <div class="vw-share-row">
          <label class="vw-share-field">Due date <input type="date" name="due"></label>
          ${policySelect("policy", "after_finish")}
        </div>
        <label class="vw-share-field">Note for students <textarea name="note" rows="2" maxlength="500"
          placeholder="e.g. Do this without a calculator, 40 minutes."></textarea></label>
        <button type="button" class="vw-btn" data-sh="assign" ${d.students.length || d.groups.length ? "" : "disabled"}>Assign</button>
        <p class="vw-share-msg" role="status"></p>
      </section>
      <section>
        <h3>Share link</h3>
        <p class="vw-share-hint">Anyone who signs in with the link can open it - handy for a WhatsApp group.</p>
        ${link ? `<div class="vw-share-link"><input type="text" readonly value="${esc(link)}" aria-label="Share link">
            <button type="button" class="vw-btn" data-sh="copy">Copy</button></div>
          ${policySelect("lpolicy", d.link_ms_policy)}
          <button type="button" class="vw-btn vw-btn-ghost" data-sh="link-save">Save link setting</button>
          <button type="button" class="vw-btn vw-btn-ghost" data-sh="unlink">Switch the link off</button>`
        : `${policySelect("lpolicy", "after_finish")}
          <button type="button" class="vw-btn" data-sh="link">Create a link</button>`}
      </section>
      <section>
        <h3>Who has it <small>${d.shares.length}</small></h3>
        ${d.shares.length ? `<table class="vw-share-table"><thead><tr><th>Student</th><th>Opened</th>${TEST ? "<th>Finished</th>" : ""}</tr></thead>
          <tbody>${d.shares.map((x) => `<tr><td>${esc(x.name || x.email || "Student")}
              <small>${x.via === "link" ? "via link" : "assigned"}</small></td>
            <td>${x.opened_at ? "✓ " + when(x.opened_at) : "—"}</td>
            ${TEST ? `<td>${x.finished_at ? "✓ " + when(x.finished_at) : "—"}</td>` : ""}</tr>`).join("")}</tbody></table>`
          : `<p class="vw-share-hint">Nobody yet.</p>`}
      </section>
      <section>
        <h3>Print</h3>
        <p class="vw-share-links"><a href="/api/booklets/${S.id}/pdf?download=1">⤓ ${TEST ? "Test" : "Paper"} PDF</a>
          ${TEST ? `<a href="/api/booklets/${S.id}/pdf?download=1&part=ms">⤓ Mark scheme PDF</a>` : ""}</p>
      </section>
    </div>`;
}

async function onShareClick(e) {
  const act = e.target.closest("[data-sh]")?.dataset.sh;
  if (!act) { if (e.target === shareDlg) shareDlg.close(); return; }
  const val = (sel) => shareDlg.querySelector(sel)?.value;
  const btn = e.target.closest("button");
  try {
    if (act === "close") { shareDlg.close(); return; }
    if (act === "copy") {
      const inp = shareDlg.querySelector(".vw-share-link input");
      try { await navigator.clipboard.writeText(inp.value); } catch { inp.select(); document.execCommand("copy"); }
      btn.textContent = "Copied ✓";
      return;
    }
    if (act === "assign") {
      const ids = [...shareDlg.querySelectorAll('input[name="s"]:checked')].map((i) => i.value);
      const groups = [...shareDlg.querySelectorAll('input[name="g"]:checked')].map((i) => +i.value);
      const msg = shareDlg.querySelector(".vw-share-msg");
      if (!ids.length && !groups.length) { msg.textContent = "Tick at least one student or group."; return; }
      btn.disabled = true;
      const r = await api(`/api/booklets/${S.id}/assign`, { method: "POST", body: {
        student_ids: ids, group_ids: groups, due_date: val('input[name="due"]') || null,
        instructions: val('textarea[name="note"]') || null,
        ...(TEST ? { ms_policy: val('select[name="policy"]') } : {}) } });
      await openShare();
      shareDlg.querySelector(".vw-share-msg").textContent =
        `Assigned to ${r.assigned} student${r.assigned === 1 ? "" : "s"}.`;
      return;
    }
    if (act === "link" || act === "link-save") {
      await api(`/api/booklets/${S.id}/link`, { method: "POST",
        body: TEST ? { ms_policy: val('select[name="lpolicy"]') } : {} });
      await openShare();
      return;
    }
    if (act === "unlink") {
      if (!confirm("Switch the link off? Students who already opened it keep the paper.")) return;
      await api(`/api/booklets/${S.id}/link`, { method: "DELETE" });
      await openShare();
    }
  } catch (err) {
    const msg = shareDlg.querySelector(".vw-share-msg");
    if (msg) msg.textContent = err.message || "Something went wrong.";
    else alert(err.message);
    if (btn) btn.disabled = false;
  }
}

open().catch(lostContact);
