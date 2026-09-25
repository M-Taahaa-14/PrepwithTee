/* viewer.js — /papers/view/{id}: build loader, then the booklet rendered in-site.
 *
 *   loader   polls /api/booklets/{id}/status and shows the real build stages
 *   pages    pdf-pane.js (PDF.js, lazy pages, annotation layer so contents
 *            links and the fillable answer sheet work)
 *   contents drawer built from the page map (Q number, source, chapter)
 *   chips    per question: Explain / Guide me / Mark scheme -> ai-panel.js
 */
import { api } from "/auth.js?v=20260829a";
import { openAiPanel } from "/ai-panel.js?v=20260926p";
import { PdfPane, debounce } from "/pdf-pane.js?v=20260926p";
import { createAnnotator } from "/annotate.js?v=20260926p";

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

const STAGES = [
  ["Picking questions", 1],
  ["Mixing your chapters together", 3],
  ["Cropping questions from the original papers", 5],
  ["Adding official mark schemes", 60],
  ["Building the clickable contents page", 90],
  ["Finishing your booklet", 96],
];

// ── Loader ──────────────────────────────────────────────────────────────────
function loader(st) {
  const p = st.progress || 0;
  const done = STAGES.filter(([, at]) => p > at).length;
  const detail = (st.stage || "").split(" · ")[1];
  root.dataset.state = "loading";
  root.innerHTML = `
    <section class="vw-load" aria-live="polite">
      <div class="vw-load-card">
        <p class="vw-eyebrow">Topical paper</p>
        <h1>${esc(S.title.split(" — ")[0])}</h1>
        <div class="vw-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
             aria-valuenow="${p}"><i style="width:${Math.max(4, p)}%"></i></div>
        <ol class="vw-stages">${STAGES.map(([label], i) => `
          <li class="${i < done ? "is-done" : i === done ? "is-now" : ""}">
            <span class="vw-dot" aria-hidden="true">${i < done ? "✓" : ""}</span>
            ${label}${i === done && detail && i === 2 ? ` <b>${esc(detail)}</b>` : ""}
          </li>`).join("")}</ol>
        <p class="vw-tip">Tip: stuck on a question? Tap <b>Guide me</b> for a hint before
           you open the full <b>Explain</b>.</p>
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
    questions,
    onPageEl: (el, n) => ann.attach(el, `booklet:${S.id}`, n),
    onPage: (n) => { document.getElementById("vw-pn").textContent = n; },
    onZoom: (label) => { document.getElementById("vw-z").textContent = label; },
    onQuestion: qbar,
  });
  await pane.load(`/api/booklets/${S.id}/pdf`);
  document.getElementById("vw-pt").textContent = pane.numPages;
  window.addEventListener("resize", debounce(() => pane.refit(), 200));
}

function shell() {
  root.dataset.state = "ready";
  root.innerHTML = `
    <header class="vw-tools">
      <a class="vw-back" href="${S.subjectUrl}#builder" title="Back to the builder">←</a>
      <button type="button" class="vw-tbtn" data-act="toc" aria-expanded="false"
              aria-controls="vw-toc">☰ <span>Contents</span></button>
      <h1 class="vw-title" title="${esc(S.title)}">${esc(S.title)}</h1>
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
  else if (act === "toc") {
    const toc = document.getElementById("vw-toc");
    toc.hidden = !toc.hidden;
    e.target.closest("[data-act]").setAttribute("aria-expanded", String(!toc.hidden));
    refitSoon();
  }
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
