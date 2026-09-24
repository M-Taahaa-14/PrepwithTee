/* viewer.js — /papers/view/{id}: build loader, then the booklet rendered in-site.
 *
 *   loader   polls /api/booklets/{id}/status and shows the real build stages
 *   pages    PDF.js, lazily rendered as they scroll into view; the annotation
 *            layer keeps contents links and the fillable answer sheet working
 *   contents drawer built from the page map (Q number, source, chapter)
 *   chips    per question: Mark scheme / Explain / Guide me. The side panel is
 *            the same one the AI help (P1-c) will fill; today it shows the
 *            official mark scheme (or the MCQ answer letter).
 */
import { api } from "/auth.js?v=20260829a";

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
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

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
        <p class="vw-tip">Tip: open a question's <b>Mark scheme</b> from the chip beside it —
           Explain and Guide me are coming next.</p>
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
const V = { doc: null, map: null, scale: 1, fit: 1, fitted: true, pages: [], obs: null, current: null };

async function open() {
  if (!(await waitReady())) return;
  loader({ progress: 99, stage: "Opening" });
  const meta = await api(`/api/booklets/${S.id}`);
  V.map = meta.page_map_json || { questions: [] };
  V.doc = await pdfjsLib.getDocument({ url: `/api/booklets/${S.id}/pdf`,
                                        withCredentials: true }).promise;
  shell();
  const first = await V.doc.getPage(1);
  V.base = first.getViewport({ scale: 1 });
  fitWidth();
  layout();
  window.addEventListener("resize", debounce(refit, 200));
}

function shell() {
  root.dataset.state = "ready";
  const qs = V.map.questions || [];
  root.innerHTML = `
    <header class="vw-tools">
      <a class="vw-back" href="${S.subjectUrl}#builder" title="Back to the builder">←</a>
      <button type="button" class="vw-tbtn" data-act="toc" aria-expanded="false"
              aria-controls="vw-toc">☰ <span>Contents</span></button>
      <h1 class="vw-title" title="${esc(S.title)}">${esc(S.title)}</h1>
      <span class="vw-pageno" aria-live="polite">Page <b id="vw-pn">1</b> / ${V.doc.numPages}</span>
      <div class="vw-zoom" role="group" aria-label="Zoom">
        <button type="button" class="vw-tbtn" data-act="out" aria-label="Zoom out">−</button>
        <button type="button" class="vw-tbtn" data-act="fit" id="vw-z">100%</button>
        <button type="button" class="vw-tbtn" data-act="in" aria-label="Zoom in">+</button>
      </div>
      <a class="vw-btn vw-dl" href="/api/booklets/${S.id}/pdf?download=1">⤓ <span>Download</span></a>
    </header>
    <div class="vw-body">
      <nav class="vw-toc" id="vw-toc" hidden aria-label="Contents">
        <div class="vw-toc-head">${qs.length} questions</div>
        <ol>${qs.map((q) => `
          <li><button type="button" data-goto="${q.seq}">
            <b>Q${q.seq}</b><span>${esc(q.ref)}</span><em>${esc(q.topic || "")}</em>
          </button></li>`).join("")}</ol>
      </nav>
      <div class="vw-stage" id="vw-stage" tabindex="0" aria-label="Paper"></div>
      <aside class="vw-panel" id="vw-panel" hidden aria-label="Question help"></aside>
    </div>
    <div class="vw-qbar" id="vw-qbar" hidden></div>`;
}

function fitWidth() {
  const stage = document.getElementById("vw-stage");
  const gutter = window.innerWidth >= 1000 ? 150 : 24;
  V.fit = Math.min(1.6, Math.max(0.4, (stage.clientWidth - gutter) / V.base.width));
  if (V.fitted) V.scale = V.fit;
}

// The stage changes width when the contents drawer or the side panel opens:
// a page that was fitted to the width is fitted again.
function refit() {
  const was = V.fitted;
  fitWidth();
  if (was) setScale(V.fit, true);
}

function setScale(s, fitted = false) {
  const stage = document.getElementById("vw-stage");
  const ratio = stage.scrollTop / Math.max(1, stage.scrollHeight);
  V.scale = Math.min(3, Math.max(0.4, s));
  V.fitted = fitted || Math.abs(V.scale - V.fit) < 0.001;
  layout();
  stage.scrollTop = ratio * stage.scrollHeight;
}

function layout() {
  const stage = document.getElementById("vw-stage");
  const w = V.base.width * V.scale, h = V.base.height * V.scale;
  document.getElementById("vw-z").textContent = `${Math.round(V.scale / V.fit * 100)}%`;
  V.obs?.disconnect();
  stage.innerHTML = "";
  V.pages = [];
  const byPage = {};
  for (const q of V.map.questions || []) (byPage[q.page] ||= []).push(q);
  for (let n = 1; n <= V.doc.numPages; n++) {
    const pg = document.createElement("div");
    pg.className = "vw-pg";
    pg.dataset.n = n;
    pg.style.width = `${w}px`;
    pg.style.height = `${h}px`;
    pg.setAttribute("aria-label", `Page ${n}`);
    for (const q of byPage[n] || []) {
      const chips = document.createElement("div");
      chips.className = "vw-chips";
      chips.style.top = `${q.y * V.scale}px`;
      chips.innerHTML = `
        <button type="button" data-ms="${q.seq}" class="vw-chip">✓ Mark scheme</button>
        <button type="button" data-soon="explain" class="vw-chip is-soon" title="Coming next">✦ Explain</button>
        <button type="button" data-soon="hint" class="vw-chip is-soon" title="Coming next">💡 Guide me</button>`;
      pg.appendChild(chips);
    }
    stage.appendChild(pg);
    V.pages.push({ el: pg, rendered: false });
  }
  V.obs = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) renderPage(+e.target.dataset.n);
  }, { root: stage, rootMargin: "900px 0px" });
  V.pages.forEach((p) => V.obs.observe(p.el));
  stage.onscroll = debounce(onScroll, 60);
  onScroll();
}

async function renderPage(n) {
  const slot = V.pages[n - 1];
  if (!slot || slot.rendered) return;
  slot.rendered = true;
  const page = await V.doc.getPage(n);
  const vp = page.getViewport({ scale: V.scale });
  const dpr = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(vp.width * dpr);
  canvas.height = Math.floor(vp.height * dpr);
  canvas.style.width = `${vp.width}px`;
  canvas.style.height = `${vp.height}px`;
  slot.el.prepend(canvas);
  await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp,
                      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
                      annotationMode: pdfjsLib.AnnotationMode.ENABLE_FORMS }).promise;
  const layer = document.createElement("div");
  layer.className = "annotationLayer";
  slot.el.style.setProperty("--scale-factor", vp.scale);
  slot.el.insertBefore(layer, canvas.nextSibling);
  const view = vp.clone({ dontFlip: true });
  await new pdfjsLib.AnnotationLayer({ div: layer, page, viewport: view,
                                       accessibilityManager: null, annotationCanvasMap: null })
    .render({ annotations: await page.getAnnotations(), viewport: view, div: layer, page,
              linkService: LINKS, annotationStorage: V.doc.annotationStorage,
              renderForms: true });
}

// Minimal PDF.js link service: contents rows jump inside the viewer, the
// website links (logo, footer) open in a new tab.
const LINKS = {
  externalLinkEnabled: true,
  getDestinationHash: () => "#",
  getAnchorUrl: (h) => h,
  addLinkAttributes(link, url) { link.href = url; link.target = "_blank"; link.rel = "noopener"; },
  async goToDestination(dest) {
    const d = typeof dest === "string" ? await V.doc.getDestination(dest) : dest;
    if (!Array.isArray(d)) return;
    const idx = typeof d[0] === "object" ? await V.doc.getPageIndex(d[0]) : d[0];
    const y = d[1]?.name === "XYZ" && d[3] != null ? V.base.height - d[3] : 0;
    scrollToPage(idx + 1, y);
  },
  goToPage(n) { scrollToPage(n, 0); },
  executeNamedAction() {}, executeSetOCGState() {}, navigateTo(d) { this.goToDestination(d); },
  get pagesCount() { return V.doc?.numPages || 0; }, page: 1, rotation: 0, isInPresentationMode: false,
};

function scrollToPage(n, y = 0) {
  const pg = V.pages[n - 1]?.el;
  if (!pg) return;
  const stage = document.getElementById("vw-stage");
  stage.scrollTo({ top: pg.offsetTop + y * V.scale - 12, behavior: "smooth" });
}

function onScroll() {
  const stage = document.getElementById("vw-stage");
  if (!stage) return;
  const mid = stage.scrollTop + 80;
  let n = 1;
  for (const p of V.pages) { if (p.el.offsetTop <= mid) n = +p.el.dataset.n; else break; }
  document.getElementById("vw-pn").textContent = n;
  // The question being read: the last one that starts above the reading line.
  let cur = null;
  for (const q of V.map.questions || []) {
    const top = V.pages[q.page - 1]?.el.offsetTop + q.y * V.scale;
    if (top <= mid + 40) cur = q; else break;
  }
  if (cur?.seq !== V.current?.seq) { V.current = cur; qbar(); }
}

function qbar() {
  const bar = document.getElementById("vw-qbar");
  const q = V.current;
  document.body.classList.toggle("has-dock", !!q);
  if (!q) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.innerHTML = `<b>Q${q.seq}</b><span>${esc(q.topic || "")}</span>
    <button type="button" data-ms="${q.seq}" class="vw-chip">✓ Mark scheme</button>
    <button type="button" data-soon="explain" class="vw-chip is-soon">✦ Explain</button>`;
}

// ── Side panel ──────────────────────────────────────────────────────────────
async function openPanel(seq) {
  const q = (V.map.questions || []).find((x) => x.seq === +seq);
  if (!q) return;
  const panel = document.getElementById("vw-panel");
  const wasHidden = panel.hidden;
  panel.hidden = false;
  root.classList.add("has-panel");
  if (wasHidden && window.innerWidth >= 1000) refit();
  panel.innerHTML = `
    <div class="vw-panel-head">
      <div><b>Q${q.seq}</b> <span>${esc(q.ref)}</span><em>${esc(q.topic || "")}</em></div>
      <button type="button" class="vw-tbtn" data-act="close" aria-label="Close panel">✕</button>
    </div>
    <div class="vw-tabs" role="tablist">
      <button role="tab" aria-selected="true" type="button">Mark scheme</button>
      <button role="tab" aria-selected="false" type="button" data-soon="explain">Explain</button>
      <button role="tab" aria-selected="false" type="button" data-soon="hint">Guide me</button>
    </div>
    <div class="vw-panel-body" id="vw-pbody"><p class="vw-muted">Loading the mark scheme…</p></div>`;
  const body = document.getElementById("vw-pbody");
  try {
    const ans = await api(`/api/mcq/answer/${q.qid}`);
    if (ans.has_answer) {
      body.innerHTML = `<div class="vw-answer"><span>Correct answer</span><b>${esc(ans.answer)}</b></div>
        <p class="vw-muted">From the official Cambridge mark scheme.</p>`;
      return;
    }
  } catch { /* not MCQ, or no key: fall through to the MS crop */ }
  const img = new Image();
  img.alt = `Official mark scheme for question ${q.seq}`;
  img.className = "vw-ms";
  img.onload = () => { body.innerHTML = ""; body.appendChild(img);
    body.insertAdjacentHTML("beforeend", `<p class="vw-muted">Official Cambridge mark scheme · ${esc(q.ref)}</p>`); };
  img.onerror = () => { body.innerHTML = `<p class="vw-muted">No mark scheme is available for this question yet.</p>`; };
  img.src = `/api/question/${q.qid}/ms-preview`;
}

function closePanel() {
  const panel = document.getElementById("vw-panel");
  if (panel.hidden) return;
  panel.hidden = true;
  root.classList.remove("has-panel");
  if (window.innerWidth >= 1000) refit();
}

// ── Events ──────────────────────────────────────────────────────────────────
root.addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "in") setScale(V.scale * 1.15);
  else if (act === "out") setScale(V.scale / 1.15);
  else if (act === "fit") setScale(V.fit, true);
  else if (act === "close") closePanel();
  else if (act === "toc") {
    const toc = document.getElementById("vw-toc");
    toc.hidden = !toc.hidden;
    e.target.closest("[data-act]").setAttribute("aria-expanded", String(!toc.hidden));
    if (window.innerWidth >= 1000) refit();
  }
  const go = e.target.closest("[data-goto]");
  if (go) {
    const q = V.map.questions.find((x) => x.seq === +go.dataset.goto);
    if (q) scrollToPage(q.page, q.y);
    if (window.innerWidth < 900) document.getElementById("vw-toc").hidden = true;
  }
  const ms = e.target.closest("[data-ms]");
  if (ms) openPanel(ms.dataset.ms);
  const soon = e.target.closest("[data-soon]");
  if (soon) toast(soon.dataset.soon === "hint"
    ? "Guide me (step-by-step hints) is coming in the next update."
    : "Explain (full worked solutions) is coming in the next update.");
});

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.key === "Escape") closePanel();
  if ((e.ctrlKey || e.metaKey) && (e.key === "=" || e.key === "+")) { e.preventDefault(); setScale(V.scale * 1.15); }
  if ((e.ctrlKey || e.metaKey) && e.key === "-") { e.preventDefault(); setScale(V.scale / 1.15); }
});

function toast(msg) {
  let t = document.getElementById("vw-toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "vw-toast";
    t.className = "vw-toast";
    t.setAttribute("role", "status");
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("is-on");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("is-on"), 3200);
}

function debounce(fn, ms) {
  let h;
  return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}

open().catch((e) => failed(e.message));
