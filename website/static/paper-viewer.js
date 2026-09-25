/* paper-viewer.js — /yearly/view/{paper_id}: one sitting's question paper,
 * mark scheme and insert in the site viewer (pdf-pane.js).
 *
 *   docs     QP / MS / Insert switcher; "Side by side" puts the question paper
 *            on the left and the mark scheme (or insert) on the right, and the
 *            mark scheme follows the question being read when we know where
 *            each answer starts (ms_entries.rects_json, 2017 on)
 *   chips    Explain / Guide me / Mark scheme per question -> ai-panel.js
 *   progress Mark done, marks out of the paper total, and the official grade
 *            thresholds for the sitting (same data the old library showed)
 */
import { api } from "/auth.js?v=20260927b";
import { openAiPanel } from "/ai-panel.js?v=20260926r";
import { PdfPane, debounce } from "/pdf-pane.js?v=20260927b";
import { createAnnotator } from "/annotate.js?v=20260927b";

let ann = null;                  // the annotation bar, created with the shell

const S = JSON.parse(document.getElementById("vw-state").textContent);
const root = document.getElementById("vw");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const header = document.querySelector(".site-header");
const sizeTop = () => document.documentElement.style.setProperty(
  "--vw-top", `${header ? header.getBoundingClientRect().bottom : 0}px`);
sizeTop();
window.addEventListener("resize", sizeTop);
window.addEventListener("scroll", () => { if (window.scrollY) window.scrollTo(0, 0); }, { passive: true });

const KINDS = ["qp", "ms", "in"].filter((k) => S.files[k]);
const SHORT = { qp: "Question paper", ms: "Mark scheme", in: "Insert" };
const wide = () => window.innerWidth >= 1000;
const V = {
  active: KINDS.includes(S.doc) ? S.doc : KINDS[0],   // single view: the doc shown
  right: S.files.ms ? "ms" : KINDS.find((k) => k !== "qp") || null,   // split: right column
  split: false, follow: true, panes: {}, panel: null,
  progress: null, // {status, score, max_score} for this sitting
};

// ── Shell ───────────────────────────────────────────────────────────────────
function shell() {
  root.dataset.state = "ready";
  const canSplit = !!(S.files.qp && V.right);
  root.innerHTML = `
    <header class="vw-tools pv-tools">
      <a class="vw-back" href="${esc(S.backUrl)}" title="Back to ${esc(S.subjectName)} papers">←</a>
      <h1 class="vw-title" title="${esc(S.title)}">${esc(S.short)}</h1>
      <div class="pv-seg" role="tablist" aria-label="Document">${KINDS.map((k) => `
        <button type="button" role="tab" data-doc="${k}" aria-selected="false">
          <span class="pv-long">${SHORT[k]}</span><span class="pv-abbr">${k === "in" ? "Insert" : k.toUpperCase()}</span></button>`).join("")}
      </div>
      ${canSplit ? `<button type="button" class="vw-tbtn pv-split" data-act="split" aria-pressed="false"
          title="Question paper and ${SHORT[V.right].toLowerCase()} side by side">⇆ <span>Side by side</span></button>` : ""}
      <span class="vw-pageno" aria-live="polite">Page <b id="vw-pn">1</b> / <span id="vw-pt">…</span></span>
      <div class="vw-zoom" role="group" aria-label="Zoom">
        <button type="button" class="vw-tbtn" data-act="out" aria-label="Zoom out">−</button>
        <button type="button" class="vw-tbtn" data-act="fit" id="vw-z">100%</button>
        <button type="button" class="vw-tbtn" data-act="in" aria-label="Zoom in">+</button>
      </div>
      <button type="button" class="vw-tbtn pv-done" data-act="done" aria-pressed="false"
              title="Mark this paper as done">○ <span>Done</span></button>
      <button type="button" class="vw-tbtn" data-act="marks" title="Your marks and the grade thresholds">
        📊 <span>Marks &amp; grades</span></button>
      <a class="vw-btn vw-dl" id="pv-dl" download>⤓ <span>Download</span></a>
    </header>
    <div class="vw-body pv-body">
      ${KINDS.map((k) => `
        <section class="pv-col" data-col="${k}" hidden aria-label="${SHORT[k]}">
          <div class="pv-head" hidden>${SHORT[k]}${k === "ms" && Object.keys(S.msAt).length ? `
            <label class="pv-follow"><input type="checkbox" data-act="follow" checked> Follow the question</label>` : ""}</div>
          <div class="vw-stage" id="pv-${k}" tabindex="0" aria-label="${SHORT[k]} pages"></div>
        </section>`).join("")}
      <aside class="vw-panel" id="vw-panel" hidden aria-label="Help"></aside>
    </div>
    <div class="vw-qbar" id="vw-qbar" hidden></div>`;
}

async function pane(kind) {
  if (V.panes[kind]) return V.panes[kind];
  const stage = document.getElementById(`pv-${kind}`);
  const p = new PdfPane(stage, {
    questions: kind === "qp" ? S.questions : [],
    onPage: (n) => { if (kind === primary()) document.getElementById("vw-pn").textContent = n; },
    onZoom: (label) => { if (kind === primary()) document.getElementById("vw-z").textContent = label; },
    onQuestion: kind === "qp" ? onQuestion : null,
    // Drawings belong to the file: the same paper opened again shows them.
    onPageEl: (el, n) => ann?.attach(el, `paper:${S.files[kind].id}`, n),
  });
  V.panes[kind] = p;
  p.ready = p.load(S.files[kind].url).then(() => {
    if (kind === primary()) document.getElementById("vw-pt").textContent = p.numPages;
    return p;
  });
  return p;
}

const primary = () => (V.split ? "qp" : V.active);
const visible = () => (V.split ? ["qp", V.right] : [V.active]);

async function show() {
  const vis = visible();
  root.classList.toggle("is-split", V.split);
  document.querySelectorAll(".pv-col").forEach((col) => {
    col.hidden = !vis.includes(col.dataset.col);
    col.querySelector(".pv-head").hidden = !V.split;
  });
  document.querySelectorAll("[data-doc]").forEach((b) => {
    const on = V.split ? b.dataset.doc === V.right || b.dataset.doc === "qp" : b.dataset.doc === V.active;
    b.setAttribute("aria-selected", String(on));
  });
  const sb = root.querySelector("[data-act=split]");
  if (sb) sb.setAttribute("aria-pressed", String(V.split));
  const f = S.files[V.split ? V.right : V.active];
  const dl = document.getElementById("pv-dl");
  dl.href = f.url;
  dl.setAttribute("download", f.filename);
  for (const k of vis) {
    const p = await pane(k);
    await p.ready;
    p.refit();
  }
  const p = V.panes[primary()];
  document.getElementById("vw-pt").textContent = p.numPages;
  document.getElementById("vw-pn").textContent = p.pageNo;
  document.getElementById("vw-z").textContent = p.zoomLabel;
  qbar(V.split || V.active === "qp" ? V.panes.qp?.current : null);
}

function setDoc(kind) {
  if (V.split) {
    if (kind === "qp") return;
    V.right = kind;
  } else {
    V.active = kind;
  }
  const url = new URL(location.href);
  if (kind === "qp") url.searchParams.delete("doc"); else url.searchParams.set("doc", kind);
  history.replaceState(null, "", url);
  show();
}

function refitAll() { visible().forEach((k) => V.panes[k]?.refit()); }

// ── Following the mark scheme ───────────────────────────────────────────────
function onQuestion(q) {
  if (V.split || V.active === "qp") qbar(q);
  if (!q || !V.split || V.right !== "ms" || !V.follow) return;
  const at = S.msAt[`${q.number}|${q.sub}`] || S.msAt[`${q.number}|`];
  if (at) V.panes.ms?.scrollToPage(at.page, at.y);
}

function qbar(q) {
  const bar = document.getElementById("vw-qbar");
  if (!bar) return;
  document.body.classList.toggle("has-dock", !!q);
  if (!q) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.innerHTML = `<b>${esc(q.label)}</b><span>${esc(q.topic || "")}</span>
    <button type="button" data-open="explain" data-seq="${q.seq}" class="vw-chip">✦ Explain</button>
    <button type="button" data-open="ms" data-seq="${q.seq}" class="vw-chip">✓ MS</button>`;
}

// ── Side panel: AI help, or marks & grades ──────────────────────────────────
function openSide(render) {
  const panel = document.getElementById("vw-panel");
  const wasHidden = panel.hidden;
  panel.hidden = false;
  root.classList.add("has-panel");
  render(panel);
  if (wasHidden && wide()) refitAll();
}

function closePanel() {
  const panel = document.getElementById("vw-panel");
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  panel.innerHTML = "";
  root.classList.remove("has-panel");
  if (wide()) refitAll();
}

function openQuestion(seq, tab) {
  const q = S.questions.find((x) => x.seq === +seq);
  if (q) openSide((panel) => openAiPanel(panel, q, { tab, onClose: closePanel }));
}

// ── Progress: done, marks, thresholds ───────────────────────────────────────
const same = (p) => p.year === S.year && p.session === S.session && +p.paper === +S.paper &&
  String(p.variant ?? "") === String(S.variant ?? "");

async function loadProgress() {
  try {
    const d = await api(`/api/papers-progress?syllabus=${encodeURIComponent(S.syllabus)}`);
    V.progress = (d.papers || []).find(same) || null;
  } catch { V.progress = null; }
  paintDone();
}

function paintDone() {
  const b = root.querySelector("[data-act=done]");
  if (!b) return;
  const done = V.progress?.status === "confident";
  b.setAttribute("aria-pressed", String(done));
  b.classList.toggle("is-on", done);
  b.innerHTML = `${done ? "✓" : "○"} <span>${done ? "Done" : "Mark done"}</span>`;
  b.title = done ? "Marked as done — click to undo" : "Mark this paper as done";
}

async function saveProgress(fields) {
  const body = { syllabus: S.syllabus, year: S.year, session: S.session, paper: S.paper,
                 variant: String(S.variant ?? ""), ...fields };
  await api("/api/papers-progress", { method: "POST", body });
  V.progress = { ...(V.progress || {}), ...body };
  paintDone();
}

async function toggleDone() {
  const done = V.progress?.status === "confident";
  try {
    await saveProgress({ status: done ? "not_started" : "confident",
                         score: V.progress?.score ?? null, max_score: V.progress?.max_score ?? null });
    toast(done ? "Marked as not done" : "Nice — paper marked as done");
  } catch (e) { toast(`Couldn't save: ${e.message}`); }
}

const GRADES = [["astar", "A*"], ["a", "A"], ["b", "B"], ["c", "C"], ["d", "D"], ["e", "E"], ["f", "F"], ["g", "G"]];

function chips(t) {
  if (!t) return `<p class="ai-muted">Not published for this component.</p>`;
  return `<div class="pv-th">${GRADES.filter(([k]) => t[`grade_${k}`] != null).map(([k, g]) =>
    `<span class="pv-th-g" data-g="${g}"><b>${g}</b>${t[`grade_${k}`]}</span>`).join("")}</div>`;
}

function gradeFor(t, score) {
  if (!t || score == null) return null;
  for (const [k, g] of GRADES) if (t[`grade_${k}`] != null && score >= t[`grade_${k}`]) return g;
  return "U";
}

let TH = null;
async function thresholds() {
  if (TH) return TH;
  const syl = encodeURIComponent(S.syllabus);
  const [th, op] = await Promise.all([
    api(`/api/grade-thresholds?syllabus=${syl}&year=${S.year}&session=${S.session}`).catch(() => ({ thresholds: [] })),
    api(`/api/grade-options?syllabus=${syl}&year=${S.year}&session=${S.session}`).catch(() => ({ options: [] })),
  ]);
  const V_ = String(S.variant || "");
  const comp = (th.thresholds || []).find((t) => t.year === S.year && t.session === S.session &&
    String(t.paper) === String(S.paper) && String(t.variant || "") === V_) || null;
  const opts = (op.options || []).filter((o) => o.year === S.year && o.session === S.session &&
    o.max_mark > 0 && (!V_ || (o.components || "").split(/[\s,]+/).filter(Boolean)
      .every((c) => c.length >= 2 && c.slice(-1) === V_)));
  TH = { comp, opts };
  return TH;
}

function renderMarks(panel) {
  const p = V.progress || {};
  panel.innerHTML = `
    <div class="ai-head"><div><b>Marks &amp; grades</b> <span>${esc(S.short)}</span></div>
      <button type="button" class="ai-x" data-act="close" aria-label="Close panel">✕</button></div>
    <div class="ai-body pv-marks">
      <form class="pv-score" data-marks>
        <label>Your mark<input type="number" min="0" inputmode="numeric" name="score"
               value="${p.score ?? ""}" placeholder="e.g. 52"></label>
        <span aria-hidden="true">/</span>
        <label>Out of<input type="number" min="1" inputmode="numeric" name="max"
               value="${p.max_score ?? ""}"></label>
        <button type="submit" class="ai-btn">Save</button>
      </form>
      <p class="pv-grade" id="pv-grade" aria-live="polite"></p>
      <div id="pv-th"><p class="ai-muted">Loading the official grade thresholds…</p></div>
    </div>`;
  const form = panel.querySelector("[data-marks]");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const score = parseInt(form.score.value, 10), max = parseInt(form.max.value, 10);
    if (Number.isNaN(score) || Number.isNaN(max) || score < 0 || max <= 0 || score > max) {
      toast("Enter a mark between 0 and the paper total.");
      return;
    }
    try {
      await saveProgress({ status: "confident", score, max_score: max });
      toast("Saved — this paper is marked as done");
      paintGrade(panel);
    } catch (err) { toast(`Couldn't save: ${err.message}`); }
  };
  thresholds().then(({ comp, opts }) => {
    const box = panel.querySelector("#pv-th");
    if (!box) return;
    box.innerHTML = `
      <h4 class="pv-h">This paper · official Cambridge thresholds${comp ? ` · out of ${comp.max_mark}` : ""}</h4>
      ${chips(comp)}
      ${opts.length ? `<h4 class="pv-h">Overall grade (weighted total)</h4>${opts.map((o) => `
        <div class="pv-opt"><span><b>${esc(o.option_code)}</b> ${esc(o.components)} · out of ${o.max_mark}</span>
        ${chips(o)}</div>`).join("")}
        <p class="ai-muted">Cambridge scales each paper before comparing with the overall
          boundaries — the <a href="/grade-calculator.html">Grade Calculator</a> does that for you.</p>` : ""}`;
    // The official maximum first: adding up the questions overcounts papers
    // with optional questions (e.g. "answer two of Section B").
    if (!form.max.value) form.max.value = comp?.max_mark || S.totalMarks || "";
    paintGrade(panel);
  });
}

function paintGrade(panel) {
  const out = panel.querySelector("#pv-grade");
  const p = V.progress;
  if (!out || !p || p.score == null || !TH?.comp) { if (out) out.textContent = ""; return; }
  // Thresholds are on the component's own maximum: scale if the student used another total.
  const scaled = p.max_score && TH.comp.max_mark ? Math.round(p.score * TH.comp.max_mark / p.max_score) : p.score;
  const g = gradeFor(TH.comp, scaled);
  out.innerHTML = `${p.score}/${p.max_score} = grade <b>${g}</b> on this paper's ${S.sessionName} ${S.year} thresholds.`;
}

// ── Events ──────────────────────────────────────────────────────────────────
root.addEventListener("click", (e) => {
  const doc = e.target.closest("[data-doc]");
  if (doc) return setDoc(doc.dataset.doc);
  const act = e.target.closest("[data-act]")?.dataset.act;
  const vis = visible().map((k) => V.panes[k]).filter(Boolean);
  if (act === "in") vis.forEach((p) => p.zoomIn());
  else if (act === "out") vis.forEach((p) => p.zoomOut());
  else if (act === "fit") vis.forEach((p) => p.zoomFit());
  else if (act === "split") { V.split = !V.split; show(); }
  else if (act === "close") closePanel();
  else if (act === "done") toggleDone();
  else if (act === "marks") openSide(renderMarks);
  const open = e.target.closest("[data-open]");
  if (open) openQuestion(open.dataset.seq, open.dataset.open);
});

root.addEventListener("change", (e) => {
  if (e.target.matches("[data-act=follow]")) V.follow = e.target.checked;
});

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.key === "Escape") closePanel();
  const vis = visible().map((k) => V.panes[k]).filter(Boolean);
  if ((e.ctrlKey || e.metaKey) && (e.key === "=" || e.key === "+")) { e.preventDefault(); vis.forEach((p) => p.zoomIn()); }
  if ((e.ctrlKey || e.metaKey) && e.key === "-") { e.preventDefault(); vis.forEach((p) => p.zoomOut()); }
});

window.addEventListener("resize", debounce(() => {
  if (V.split && !wide()) { V.split = false; show(); return; }
  refitAll();
}, 200));

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

// ── Start ───────────────────────────────────────────────────────────────────
shell();
ann = createAnnotator({ mount: document.body });
// Wide screens open side by side when there is a mark scheme to show beside it.
if (wide() && window.innerWidth >= 1280 && S.files.qp && V.right && !new URLSearchParams(location.search).has("doc")) {
  V.split = true;
}
show().catch((e) => {
  root.innerHTML = `<section class="vw-load"><div class="vw-load-card">
    <p class="vw-eyebrow">Something went wrong</p><h1>We couldn't open this paper</h1>
    <p>${esc(e.message)}</p><a class="vw-btn" href="${esc(S.backUrl)}">Back to the papers</a></div></section>`;
});
loadProgress();
