/* viewer.js — /papers/view/{id}: build loader, then the booklet rendered in-site.
 *
 *   loader   polls /api/booklets/{id}/status and shows the real build stages
 *   pages    pdf-pane.js (PDF.js, lazy pages, annotation layer so contents
 *            links and the fillable answer sheet work)
 *   contents drawer built from the page map (Q number, source, chapter)
 *   chips    per question: Explain / Guide me / Mark scheme -> ai-panel.js
 *   tests    a mock test (kind "test") has no chips: Test / Mark scheme tabs, a
 *            countdown, and the separate mark scheme unlocks on "Finish test"
 */
import { api } from "/auth.js?v=20260927b";
import { openAiPanel } from "/ai-panel.js?v=20260927a";
import { PdfPane, debounce } from "/pdf-pane.js?v=20260927d";
import { createAnnotator } from "/annotate.js?v=20260927e";

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

function failed(msg) {
  root.dataset.state = "failed";
  root.innerHTML = `
    <section class="vw-load"><div class="vw-load-card">
      <p class="vw-eyebrow">Something went wrong</p>
      <h1>We couldn't build this paper</h1>
      <p>${esc(msg || "Please try again.")}</p>
      <a class="vw-btn" href="${S.subjectUrl}#builder">Back to the builder</a>
    </div></section>`;
}

async function waitReady() {
  for (;;) {
    let st;
    try { st = await api(`/api/booklets/${S.id}/status`); }
    catch (e) { failed(e.message); return false; }
    if (st.status === "ready") return true;
    if (st.status === "failed") { failed(st.error); return false; }
    loader(st);
    await new Promise((r) => setTimeout(r, 700));
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
const finished = () => store.get(`test-done:${S.id}`) === "1";
const minutes = Math.max(5, Math.round(S.totalMarks || 20));   // the cover's "1 minute per mark"

async function showPart(which) {
  if (which === "ms" && !finished()) return;
  part = which;
  document.querySelectorAll("[data-part]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.part === which)));
  document.getElementById("vw-stage").hidden = which !== "paper";
  const ms = document.getElementById("vw-stage-ms");
  ms.hidden = which !== "ms";
  document.querySelector(".vw-dl").href = `/api/booklets/${S.id}/pdf?download=1${which === "ms" ? "&part=ms" : ""}`;
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

function finishTest() {
  if (!finished() && !confirm("Finish the test and unlock the mark scheme?")) return;
  store.set(`test-done:${S.id}`, "1");
  timer.stop();
  const lock = document.querySelector('[data-part="ms"]');
  lock.disabled = false;
  lock.removeAttribute("title");
  lock.textContent = "Mark scheme";
  document.querySelector("[data-act=finish]")?.remove();
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
          <button type="button" role="tab" data-part="ms" aria-selected="false" ${finished() ? "" : "disabled"}
            ${finished() ? "" : 'title="Unlocks when you finish the test"'}>${finished() ? "Mark scheme" : "🔒 Mark scheme"}</button>
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
    <button type="button" data-open="hint" data-seq="${q.seq}" class="vw-chip">💡 Hint</button>`;
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

open().catch((e) => failed(e.message));
