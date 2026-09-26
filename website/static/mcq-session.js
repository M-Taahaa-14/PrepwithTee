/* mcq-session.js — /mcq/session/{id}: the MCQ solver.
 *
 *   Paper view   the real question paper (full-paper sessions: the original PDF;
 *                topical sets: the questions' own vector crops stacked like an
 *                exam paper) with the answer sheet beside it
 *   One by one   one question, four big A-D buttons, previous / next
 *   Answer sheet bubbles 1..N, flags, filters; a bottom drawer on phones
 *   Clock        the official time (counts down; auto-submits at 0) or a
 *                stopwatch; pause hides the paper; saved every 20 s
 *   Live check   (if chosen at the start) each answer is marked as you go and
 *                then locked; otherwise nothing is revealed until Submit
 *   Results      score ring, per-chapter bars, ✓/✗ grid; every question opens
 *                in review with "why each option" in the AI panel
 *   Annotations  pen/highlighter/shapes on every page and question (annotate.js)
 * Keys: A–D or 1–4 answer · ← → move · F flag · Esc close panel.
 */
import { api } from "/auth.js?v=20260927k";
import { openAiPanel } from "/ai-panel.js?v=20260926r";
import { PdfPane, PDF_OPTS, debounce } from "/pdf-pane.js?v=20260927d";
import { createAnnotator } from "/annotate.js?v=20260927l";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const BOOT = JSON.parse(document.getElementById("mq-state").textContent);
const root = document.getElementById("mq");
const LETTERS = ["A", "B", "C", "D"];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const header = document.querySelector(".site-header");
const sizeTop = () => document.documentElement.style.setProperty(
  "--vw-top", `${header ? header.getBoundingClientRect().bottom : 0}px`);
sizeTop();
window.addEventListener("resize", sizeTop);
window.addEventListener("scroll", () => { if (window.scrollY) window.scrollTo(0, 0); }, { passive: true });
const narrow = () => window.innerWidth < 1000;

const S = {
  d: null,               // the session payload from the API
  view: "paper",         // paper | single | results
  i: 0,                  // current question index
  filter: "all",
  elapsed: 0, running: false, paused: false, tick: null, lastBeat: 0,
  qtime: {},             // qid -> seconds spent (sent with the answer)
  pane: null, ann: null, queue: Promise.resolve(), drawer: false, ready: false,
};
const Q = () => S.d.questions;
const cur = () => Q()[S.i];
const submitted = () => S.d.status === "submitted";
const live = () => !!S.d.settings?.live_check;
const revealed = (q) => submitted() || !!q.key;

// ── Boot ────────────────────────────────────────────────────────────────────
async function boot() {
  try {
    S.d = await api(`/api/mcq/sessions/${BOOT.id}`);
  } catch (e) {
    root.innerHTML = `<section class="vw-load"><div class="vw-load-card"><p class="vw-eyebrow">MCQ practice</p>
      <h1>We couldn't open this session</h1><p>${esc(e.message)}</p>
      <a class="vw-btn" href="${esc(BOOT.backUrl)}">Back</a></div></section>`;
    return;
  }
  S.elapsed = S.d.elapsed_s || 0;
  const want = new URLSearchParams(location.search).get("view");
  S.view = submitted() ? (want === "paper" || want === "single" ? want : "results")
    : (want === "paper" || want === "single" ? want : (S.d.settings?.mode || "paper"));
  const firstOpen = Q().findIndex((q) => !q.answer);
  S.i = Math.max(0, firstOpen);
  shell();
  S.ann = createAnnotator({ mount: document.body });
  S.ann.setVisible(false);                     // appears with the paper, not on intro/results
  if (submitted()) { render(); return; }
  if (S.elapsed === 0) intro();
  else preparing();                            // resuming: the paper loads before the clock runs
  await preload((done, total) => paintPrep(done, total));
  S.ready = true;
  if (S.elapsed === 0) paintPrep(1, 1);
  else { render(); startClock(); }
}

// ── Preload: every question (or the whole paper) is fetched BEFORE the clock
// starts, so no time is spent looking at "Loading question…". ────────────────
let paperDoc = null;
async function preload(progress) {
  if (S.d.pdf_url) {
    paperDoc = pdfjsLib.getDocument({ url: S.d.pdf_url, withCredentials: true, ...PDF_OPTS }).promise;
    progress(0, 1);
    try { const d = await paperDoc; await d.getPage(1); } catch { paperDoc = null; }
    progress(1, 1);
    return;
  }
  const qs = Q();
  let next = 0, done = 0;
  progress(0, qs.length);
  const worker = async () => {
    while (next < qs.length) {
      const q = qs[next++];
      try { await (await cropDoc(q.qid)).getPage(1); } catch { /* the PNG fallback covers it */ }
      progress(++done, qs.length);
    }
  };
  await Promise.all(Array.from({ length: Math.min(6, qs.length) }, worker));
}

function paintPrep(done, total) {
  const box = document.getElementById("mq-prep");
  if (!box) return;
  const ready = S.ready;
  const pct = total ? Math.round((done / total) * 100) : 100;
  box.querySelector("i").style.width = `${ready ? 100 : pct}%`;
  box.querySelector("span").textContent = ready ? "Paper ready ✓"
    : S.d.pdf_url ? "Loading the question paper…" : `Loading questions… ${done}/${total}`;
  box.classList.toggle("is-ready", !!ready);
  const go = document.querySelector("[data-act=begin]");
  if (go) {
    go.disabled = !ready;
    go.textContent = ready ? go.dataset.label : "Preparing your paper…";
  }
}

function preparing() {
  document.getElementById("mq-main").innerHTML = `
    <div class="mq-intro"><div class="mq-intro-card">
      <p class="vw-eyebrow">Welcome back</p><h1>${esc(S.d.title)}</h1>
      <p class="mq-muted">Your clock is paused while the paper loads.</p>
      <div class="mq-prep" id="mq-prep"><div class="mq-prep-bar"><i></i></div><span>Loading…</span></div>
    </div></div>`;
}

// ── Shell ───────────────────────────────────────────────────────────────────
function shell() {
  root.dataset.state = "ready";
  const d = S.d;
  root.innerHTML = `
    <header class="vw-tools mq-tools">
      <a class="vw-back" href="${esc(BOOT.backUrl)}" title="Back to MCQ practice">←</a>
      <div class="mq-title"><b title="${esc(d.title)}">${esc(d.title)}</b>
        <span>${d.count} questions${live() ? " · live check" : ""} · <i id="mq-save" class="mq-save" aria-live="polite">${submitted() ? "Handed in" : "Answers save as you go"}</i></span></div>
      <div class="pv-seg mq-views" role="tablist" aria-label="View"></div>
      <div class="mq-clock" id="mq-clock" role="timer" aria-live="off">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2"/><path d="M9 2h6"/></svg>
        <b id="mq-time">--:--</b>
        <button type="button" class="mq-pausebtn" data-act="pause" aria-label="Pause" title="Pause (the paper is hidden while paused)">❚❚</button>
      </div>
      <span class="mq-scorechip" id="mq-scorechip" hidden></span>
      <button type="button" class="vw-btn mq-submit" data-act="submit">Submit</button>
    </header>
    <div class="vw-body mq-body">
      <section class="mq-main" id="mq-main"></section>
      <aside class="mq-sheet" id="mq-sheet" aria-label="Answer sheet"></aside>
      <aside class="vw-panel" id="vw-panel" hidden aria-label="Help"></aside>
    </div>
    <button type="button" class="mq-dock" id="mq-dock" data-act="drawer" aria-expanded="false"></button>
    <div class="mq-pause" id="mq-pause" hidden>
      <div class="mq-pause-card"><p class="vw-eyebrow">Paused</p><h2>Take a breath.</h2>
        <p>The paper is hidden and the clock is stopped.</p>
        <button type="button" class="vw-btn" data-act="pause">▶ Resume</button></div>
    </div>`;
  paintViews();
  paintClock();
}

function paintViews() {
  const views = [["paper", "📄", "Paper"], ["single", "▣", "One by one"]];
  if (submitted()) views.unshift(["results", "★", "Results"]);
  root.querySelector(".mq-views").innerHTML = views.map(([k, ico, label]) => `
    <button type="button" role="tab" data-view="${k}" aria-selected="${S.view === k}">
      <span aria-hidden="true">${ico}</span><span class="mq-vlabel">${label}</span></button>`).join("");
  const sub = root.querySelector(".mq-submit");
  const chip = root.querySelector("#mq-scorechip");
  sub.hidden = submitted();
  chip.hidden = !submitted();
  if (submitted()) chip.innerHTML = `<b>${S.d.score}</b>/${S.d.total}`;
  root.querySelector("#mq-clock").classList.toggle("is-done", submitted());
}

function setView(v) {
  if (v === S.view) return;
  S.view = v;
  const url = new URL(location.href);
  url.searchParams.set("view", v);
  history.replaceState(null, "", url);
  if (!submitted() && v !== "results") beat(true);
  render();
}

function render() {
  paintViews();
  closePanel(true);
  const main = document.getElementById("mq-main");
  S.pane?.destroy?.();
  S.pane = null;
  S.ann.detachWithin(main);
  root.dataset.screen = S.view;
  S.ann.setVisible(S.view !== "results");
  if (S.view === "results") renderResults(main);
  else if (S.view === "single") renderSingle(main);
  else renderPaper(main);
  renderSheet();
}

// ── Intro (before the clock starts) ─────────────────────────────────────────
function intro() {
  const d = S.d;
  const mins = d.time_limit_s ? Math.round(d.time_limit_s / 60) : null;
  S.ann.setVisible(false);
  root.classList.add("is-intro");            // the sheet waits for Start
  document.getElementById("mq-main").innerHTML = `
    <div class="mq-intro">
      <div class="mq-intro-card">
        <p class="vw-eyebrow">${d.kind === "paper" ? "Full past paper" : "Topical practice"}</p>
        <h1>${esc(d.title)}</h1>
        <dl class="mq-facts">
          <div><dt>Questions</dt><dd>${d.count}</dd></div>
          <div><dt>Time</dt><dd>${mins ? `${mins} min` : "Untimed"}</dd></div>
          <div><dt>Marking</dt><dd>${live() ? "As you go" : "At the end"}</dd></div>
        </dl>
        <div class="mq-pick-view" role="radiogroup" aria-label="Start in">
          <button type="button" role="radio" data-start-view="paper" aria-checked="${S.view === "paper"}">
            <b>📄 Paper view</b><span>The whole paper with an answer sheet, like the exam hall.</span></button>
          <button type="button" role="radio" data-start-view="single" aria-checked="${S.view === "single"}">
            <b>▣ One by one</b><span>One question at a time with big A–D buttons.</span></button>
        </div>
        <ul class="mq-rules">
          ${mins ? `<li>The clock starts when you press Start and the paper is handed in automatically at 0:00. Pause any time — the paper hides while paused.</li>` : `<li>No time limit — the stopwatch just tells you how long you took.</li>`}
          ${live() ? `<li><b>Live check is on:</b> each answer is marked straight away and then locked.</li>` : `<li>Nothing is marked until you submit, so you can change answers freely.</li>`}
          <li>Flag questions to come back to. Switch between Paper and One-by-one whenever you like.</li>
          <li>Draw on the paper with the pen bar at the bottom. Keys: <kbd>A</kbd>–<kbd>D</kbd> answer, <kbd>←</kbd><kbd>→</kbd> move, <kbd>F</kbd> flag.</li>
        </ul>
        <div class="mq-prep" id="mq-prep"><div class="mq-prep-bar"><i></i></div><span>Loading questions…</span></div>
        <button type="button" class="vw-btn mq-go" data-act="begin" disabled
          data-label="Start ${mins ? `· ${mins}:00` : ""}">Preparing your paper…</button>
      </div>
    </div>`;
  renderSheet();
}

// ── Paper view ──────────────────────────────────────────────────────────────
function marker(q) {
  const state = q.key ? (q.correct ? "is-right" : "is-wrong") : q.answer ? "is-answered" : "";
  return `<button type="button" class="mq-mark ${state}${q.flagged ? " is-flagged" : ""}" data-go="${q.n}"
      aria-label="${q.label}${q.answer ? `, answer ${q.answer}` : ", not answered"}">
      <span class="mq-mark-n">${q.n}</span><span class="mq-mark-a">${q.answer || "·"}</span></button>
    ${revealed(q) && q.key ? `<button type="button" class="vw-chip" data-open="explain" data-n="${q.n}">✦ Why</button>`
      : !submitted() ? `<button type="button" class="vw-chip" data-open="hint" data-n="${q.n}">💡 Hint</button>` : ""}`;
}

function renderPaper(main) {
  main.innerHTML = `<div class="vw-stage mq-stage" id="mq-stage" tabindex="0" aria-label="Question paper"></div>`;
  const stage = document.getElementById("mq-stage");
  if (S.d.pdf_url) {
    const qs = Q().map((q) => ({ ...q, seq: q.n }));
    S.pane = new PdfPane(stage, {
      questions: qs, chips: true, chipHTML: marker,
      onQuestion: (q) => { if (q) setCurrent(q.n - 1, false); },
      onPageEl: (el, n) => S.ann.attach(el, `mcq:${S.d.id}:q0`, n),
    });
    S.pane.load(paperDoc || S.d.pdf_url).then(() => S.pane.scrollToQuestion(S.i + 1)).catch((e) => {
      stage.innerHTML = `<p class="mq-empty">Couldn't load the paper: ${esc(e.message)}</p>`;
    });
  } else {
    stage.classList.add("mq-stack");
    stage.innerHTML = `<div class="mq-sheetpaper">
      <header class="mq-paperhead"><span>PrepWithTee · MCQ practice</span><b>${esc(S.d.title)}</b></header>
      ${Q().map((q) => `
        <article class="mq-q" id="mq-q${q.n}" data-n="${q.n}">
          <div class="mq-qbar">
            <span class="mq-qnum">${q.n}</span>
            <span class="mq-qref">${esc(q.ref)}</span>
            ${q.topic ? `<span class="mq-qtopic">${esc(q.topic)}</span>` : ""}
            <span class="mq-qside">${marker(q)}</span>
          </div>
          <div class="mq-crop" data-qid="${q.qid}"><span class="mq-crop-wait">Loading question…</span></div>
        </article>`).join("")}
    </div>`;
    const obs = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const box = e.target;
        obs.unobserve(box);
        S.ann.attach(box, `mcq:${S.d.id}:q${box.dataset.qid}`, 0);
        drawCrop(box, +box.dataset.qid).then(() => S.ann.repaint());
      }
    }, { root: stage, rootMargin: "800px 0px" });
    stage.querySelectorAll(".mq-crop").forEach((b) => obs.observe(b));
    stage.onscroll = debounce(() => {
      const mid = stage.scrollTop + stage.clientHeight * 0.3;
      let n = 1;
      for (const a of stage.querySelectorAll(".mq-q")) { if (a.offsetTop <= mid) n = +a.dataset.n; else break; }
      setCurrent(n - 1, false);
    }, 80);
    requestAnimationFrame(() => scrollToQ(S.i, false));
  }
}

function scrollToQ(i, smooth = true) {
  if (S.view === "single") { S.i = i; renderSingle(document.getElementById("mq-main")); renderSheet(); return; }
  if (S.pane) { S.pane.scrollToQuestion(i + 1); setCurrent(i, false); return; }
  const a = document.getElementById(`mq-q${i + 1}`);
  const stage = document.getElementById("mq-stage");
  if (a && stage) stage.scrollTo({ top: a.offsetTop - 12, behavior: smooth ? "smooth" : "auto" });
  setCurrent(i, false);
}

// Vector crop of one question, fitted to its box (PDF.js; sharp at any zoom).
const cropDocs = new Map();
function cropDoc(qid) {
  if (!cropDocs.has(qid)) {
    cropDocs.set(qid, pdfjsLib.getDocument({ url: `/api/question/${qid}/crop.pdf`, ...PDF_OPTS }).promise);
  }
  return cropDocs.get(qid);
}
async function drawCrop(box, qid) {
  const w = box.clientWidth;
  if (!w) return;
  const doc = cropDoc(qid);
  try {
    const page = await (await doc).getPage(1);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: w / base.width });
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.className = "mq-crop-canvas";
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = `${vp.width}px`;
    canvas.style.height = `${vp.height}px`;
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp,
                        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise;
    box.querySelector(".mq-crop-canvas")?.remove();
    box.querySelector(".mq-crop-wait")?.remove();
    box.style.height = `${vp.height}px`;
    box.prepend(canvas);
  } catch {
    // Fall back to the pre-rendered PNG of the crop.
    box.querySelector(".mq-crop-wait")?.remove();
    box.style.height = "";
    box.insertAdjacentHTML("afterbegin",
      `<img class="mq-crop-img" src="/api/question/${qid}/preview" alt="Question" loading="lazy">`);
  }
}

// ── One by one ──────────────────────────────────────────────────────────────
const singleParts = {
  head: (q) => `
    <span class="mq-qcount">Question <b>${q.n}</b> <small>of ${Q().length}</small></span>
    <span class="mq-qref">${esc(q.ref)}</span>
    ${q.topic ? `<span class="mq-qtopic">${esc(q.topic)}</span>` : ""}
    ${!submitted() ? `<button type="button" class="mq-flagbtn" data-flag="${q.n}" aria-pressed="${q.flagged}">⚑ <span>${q.flagged ? "Flagged" : "Flag"}</span></button>` : ""}`,
  opts: (q) => LETTERS.map((L) => {
    const cls = [q.answer === L ? "is-picked" : "", q.key && L === q.key ? "is-key" : "",
      q.key && q.answer === L && L !== q.key ? "is-miss" : ""].join(" ");
    const off = submitted() || (live() && q.key && q.answer !== L);
    return `<button type="button" class="mq-opt ${cls}" role="radio" aria-checked="${q.answer === L}"
      data-pick="${q.n}|${L}" ${off ? "disabled" : ""}><span class="mq-opt-l">${L}</span></button>`;
  }).join(""),
  nav: (q) => `
    <button type="button" class="mq-navbtn" data-act="prev" ${S.i === 0 ? "disabled" : ""}>← <span>Previous</span></button>
    ${!revealed(q) && !submitted() ? `<button type="button" class="mq-navbtn mq-hint" data-open="hint" data-n="${q.n}">💡 <span>Hint</span></button>` : ""}
    ${S.i < Q().length - 1
      ? `<button type="button" class="mq-navbtn mq-next" data-act="next">${q.answer || submitted() ? "Next" : "Skip"} <span aria-hidden="true">→</span></button>`
      : !submitted() ? `<button type="button" class="mq-navbtn mq-next" data-act="submit">Finish ✓</button>`
      : `<button type="button" class="mq-navbtn mq-next" data-view="results">Results ★</button>`}`,
};

function renderSingle(main) {
  const q = cur();
  main.innerHTML = `
    <div class="mq-single" id="mq-single">
      <div class="mq-qhead">${singleParts.head(q)}</div>
      <div class="mq-card"><div class="mq-crop" data-qid="${q.qid}"><span class="mq-crop-wait">Loading question…</span></div></div>
      <div class="mq-opts" role="radiogroup" aria-label="Your answer to question ${q.n}">${singleParts.opts(q)}</div>
      <div class="mq-feedback" id="mq-feedback" aria-live="polite">${feedback(q)}</div>
      <nav class="mq-nav">${singleParts.nav(q)}</nav>
    </div>`;
  const box = main.querySelector(".mq-crop");
  S.ann.attach(box, `mcq:${S.d.id}:q${q.qid}`, 0);
  drawCrop(box, q.qid).then(() => S.ann.repaint());
  S.qStart = performance.now();
}

function feedback(q) {
  if (!q.key) {
    if (submitted() && !q.has_key) return `<p class="mq-fb mq-fb-none">No official answer is available for this question.</p>`;
    return "";
  }
  if (!q.answer) {
    return `<div class="mq-fb mq-fb-blank"><b>Not answered.</b> The answer is <b>${q.key}</b>.
      <button type="button" class="mq-why" data-open="explain" data-n="${q.n}">✦ Why is it ${q.key}?</button></div>`;
  }
  return q.correct
    ? `<div class="mq-fb mq-fb-right"><b>✓ Correct</b> — ${q.key}.
        <button type="button" class="mq-why" data-open="explain" data-n="${q.n}">✦ See the working</button></div>`
    : `<div class="mq-fb mq-fb-wrong"><b>✗ Not quite.</b> You chose ${q.answer}; the answer is <b>${q.key}</b>.
        <button type="button" class="mq-why" data-open="explain" data-n="${q.n}">✦ Why is ${q.answer} wrong?</button></div>`;
}

// ── Answer sheet ────────────────────────────────────────────────────────────
function counts() {
  const qs = Q();
  return {
    answered: qs.filter((q) => q.answer).length,
    flagged: qs.filter((q) => q.flagged).length,
    wrong: qs.filter((q) => q.key && !q.correct).length,
  };
}

function renderSheet() {
  const el = document.getElementById("mq-sheet");
  if (!el) return;
  const c = counts();
  const qs = Q();
  const filters = submitted()
    ? [["all", "All"], ["wrong", `Wrong ${c.wrong}`], ["flagged", `Flagged ${c.flagged}`]]
    : [["all", "All"], ["open", `Unanswered ${qs.length - c.answered}`], ["flagged", `Flagged ${c.flagged}`]];
  const show = (q) => S.filter === "all" || (S.filter === "open" && !q.answer)
    || (S.filter === "flagged" && q.flagged) || (S.filter === "wrong" && q.key && !q.correct);
  el.innerHTML = `
    <div class="mq-sheet-head">
      <b>Answer sheet</b>
      <span>${submitted() ? `${S.d.score}/${S.d.total} correct` : `${c.answered}/${qs.length} answered`}</span>
      <button type="button" class="mq-sheet-x" data-act="drawer" aria-label="Close answer sheet">✕</button>
    </div>
    <div class="mq-progress" aria-hidden="true"><i style="width:${Math.round(100 * (submitted() ? S.d.score / Math.max(1, S.d.total) : c.answered / Math.max(1, qs.length)))}%"></i></div>
    <div class="mq-filter" role="tablist">${filters.map(([k, label]) => `
      <button type="button" role="tab" data-filter="${k}" aria-selected="${S.filter === k}">${label}</button>`).join("")}</div>
    <ol class="mq-rows">${qs.filter(show).map((q) => {
      const st = q.key ? (q.correct ? " is-right" : " is-wrong") : "";
      return `
      <li class="mq-row${q.n - 1 === S.i ? " is-current" : ""}${st}" data-n="${q.n}">
        <button type="button" class="mq-num" data-go="${q.n}" aria-label="Go to question ${q.n}">${q.n}</button>
        <span class="mq-bubbles" role="radiogroup" aria-label="Question ${q.n}">${LETTERS.map((L) => {
          const cls = [q.answer === L ? "is-on" : "", q.key === L ? "is-key" : "",
            q.key && q.answer === L && L !== q.key ? "is-miss" : ""].join(" ");
          const lock = submitted() || (live() && q.key);
          return `<button type="button" class="mq-bub ${cls}" role="radio" aria-checked="${q.answer === L}"
            aria-label="${L}" data-pick="${q.n}|${L}" ${lock ? "disabled" : ""}>${L}</button>`;
        }).join("")}</span>
        <button type="button" class="mq-flag${q.flagged ? " is-on" : ""}" data-flag="${q.n}"
          aria-pressed="${q.flagged}" aria-label="Flag question ${q.n}" ${submitted() ? "disabled" : ""}>⚑</button>
      </li>`;
    }).join("") || `<li class="mq-empty">Nothing here.</li>`}</ol>
    ${submitted() ? `<div class="mq-sheet-foot"><button type="button" class="vw-btn" data-view="results">★ Results</button></div>`
      : `<div class="mq-sheet-foot"><button type="button" class="vw-btn" data-act="submit">Submit answers</button></div>`}`;
  el.querySelector(".mq-row.is-current")?.scrollIntoView({ block: "nearest" });
  const dock = document.getElementById("mq-dock");
  dock.innerHTML = submitted()
    ? `<b>${S.d.score}/${S.d.total}</b><span>correct · answer sheet</span><i aria-hidden="true">▴</i>`
    : `<b>${c.answered}/${qs.length}</b><span>answered${c.flagged ? ` · ${c.flagged} flagged` : ""}</span><i aria-hidden="true">▴</i>`;
}

function setCurrent(i, redraw = true) {
  if (i === S.i && !redraw) return;
  noteTime();
  S.i = Math.max(0, Math.min(Q().length - 1, i));
  if (redraw) scrollToQ(S.i);
  document.querySelectorAll(".mq-row").forEach((r) => r.classList.toggle("is-current", +r.dataset.n === S.i + 1));
  document.querySelector(`.mq-row[data-n="${S.i + 1}"]`)?.scrollIntoView({ block: "nearest" });
}

function noteTime() {
  const q = cur();
  if (!q || !S.running || !S.qStart) { S.qStart = performance.now(); return; }
  const now = performance.now();
  S.qtime[q.qid] = (S.qtime[q.qid] || q.time_s || 0) + (now - S.qStart) / 1000;
  S.qStart = now;
}

// ── Answering ───────────────────────────────────────────────────────────────
function send(body) {
  // One request at a time, in order: the server merges into one JSON document.
  S.pending = (S.pending || 0) + 1;
  saveState("Saving…");
  const p = S.queue.then(() => api(`/api/mcq/sessions/${S.d.id}/answer`, { method: "PUT", body }));
  S.queue = p.catch(() => {}).then(() => {
    S.pending -= 1;
    if (!S.pending) saveState("All answers saved");
  });
  p.catch(() => saveState("Not saved — check your connection", true));
  return p;
}

function saveState(msg, bad = false) {
  const el = document.getElementById("mq-save");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("is-bad", bad);
}

async function pick(n, L) {
  if (submitted() || S.paused) return;
  const q = Q()[n - 1];
  if (!q || (live() && q.key)) return;
  if (!S.running) startClock();
  const before = q.answer;
  q.answer = q.answer === L && !live() ? null : L;      // tap again to clear (not in live check)
  noteTime();
  refresh(q);
  try {
    const r = await send({ qid: q.qid, answer: q.answer, time_s: Math.round(S.qtime[q.qid] || q.time_s || 0) });
    if (r.key) {
      q.key = r.key;
      q.correct = r.correct;
      refresh(q);
      if (S.view === "single") document.getElementById("mq-feedback")?.classList.add("is-in");
    }
  } catch (e) {
    q.answer = before;
    refresh(q);
    toast(`Not saved: ${e.message}`);
  }
}

async function flag(n) {
  if (submitted()) return;
  const q = Q()[n - 1];
  q.flagged = !q.flagged;
  refresh(q);
  try { await send({ qid: q.qid, flagged: q.flagged, only_flag: true }); }
  catch (e) { q.flagged = !q.flagged; refresh(q); toast(`Not saved: ${e.message}`); }
}

function refresh(q) {
  renderSheet();
  if (S.view === "single" && cur() === q) {
    // Re-render the controls only: the drawn question (and its ink) stays.
    const main = document.getElementById("mq-main");
    main.querySelector(".mq-qhead").innerHTML = singleParts.head(q);
    main.querySelector(".mq-opts").innerHTML = singleParts.opts(q);
    main.querySelector(".mq-feedback").innerHTML = feedback(q);
    main.querySelector(".mq-nav").innerHTML = singleParts.nav(q);
  } else if (S.view === "paper") {
    document.querySelectorAll(`.vw-chips[data-seq="${q.n}"], .mq-q[data-n="${q.n}"] .mq-qside`).forEach((el) => {
      el.innerHTML = marker(q);
    });
  }
}

// ── Clock ───────────────────────────────────────────────────────────────────
function fmt(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

function paintClock() {
  const t = document.getElementById("mq-time");
  const box = document.getElementById("mq-clock");
  if (!t) return;
  const lim = S.d.time_limit_s;
  const left = lim ? lim - S.elapsed : null;
  t.textContent = lim ? fmt(left) : fmt(S.elapsed);
  box.title = lim ? `${fmt(left)} left of ${fmt(lim)}` : "Time taken (untimed)";
  box.classList.toggle("is-low", !!lim && left <= 300 && !submitted());
  box.classList.toggle("is-crit", !!lim && left <= 60 && !submitted());
  box.style.setProperty("--p", lim ? Math.min(1, S.elapsed / lim) : 0);
  const pb = box.querySelector(".mq-pausebtn");
  pb.hidden = submitted();
  pb.textContent = S.paused ? "▶" : "❚❚";
  pb.setAttribute("aria-label", S.paused ? "Resume" : "Pause");
  if (submitted()) t.textContent = fmt(S.elapsed);
}

function startClock() {
  if (S.running || submitted()) return;
  S.running = true;
  S.paused = false;
  let last = performance.now();
  S.qStart = last;
  S.tick = setInterval(() => {
    const now = performance.now();
    S.elapsed += (now - last) / 1000;
    last = now;
    paintClock();
    if (S.d.time_limit_s && S.elapsed >= S.d.time_limit_s) {
      stopClock();
      toast("Time's up — your answers have been handed in.");
      submit(true);
      return;
    }
    if (now - S.lastBeat > 20000) beat();
  }, 250);
  paintClock();
}

function stopClock() {
  clearInterval(S.tick);
  S.running = false;
}

function beat(withMode = false) {
  S.lastBeat = performance.now();
  if (submitted()) return;
  const body = { elapsed_s: Math.round(S.elapsed) };
  if (withMode && (S.view === "paper" || S.view === "single")) body.mode = S.view;
  api(`/api/mcq/sessions/${S.d.id}/clock`, { method: "PUT", body }).catch(() => {});
}

function togglePause() {
  if (submitted()) return;
  S.paused = !S.paused;
  if (S.paused) { noteTime(); stopClock(); S.paused = true; beat(); }
  else startClock();
  document.getElementById("mq-pause").hidden = !S.paused;
  root.classList.toggle("is-paused", S.paused);
  paintClock();
}

// Save the clock when the tab goes away (keepalive survives the unload).
window.addEventListener("pagehide", () => {
  if (!S.d || submitted()) return;
  fetch(`/api/mcq/sessions/${S.d.id}/clock`, { method: "PUT", keepalive: true, credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ elapsed_s: Math.round(S.elapsed) }) });
});

// ── Submit + results ────────────────────────────────────────────────────────
async function submit(auto = false) {
  if (submitted()) return;
  if (!auto) {
    const c = counts();
    const blank = Q().length - c.answered;
    const ok = await confirmBox(
      "Hand in your answers?",
      `${c.answered} of ${Q().length} answered${blank ? ` · <b>${blank} unanswered</b>` : ""}${c.flagged ? ` · ${c.flagged} flagged` : ""}.
       You can't change answers after this.`,
      blank ? "Submit anyway" : "Submit");
    if (!ok) return;
  }
  noteTime();
  stopClock();
  await S.queue;
  try {
    await api(`/api/mcq/sessions/${S.d.id}/clock`, { method: "PUT", body: { elapsed_s: Math.round(S.elapsed) } });
    S.d = await api(`/api/mcq/sessions/${S.d.id}/submit`, { method: "POST" });
  } catch (e) {
    toast(`Couldn't submit: ${e.message}`);
    if (!auto) startClock();
    return;
  }
  S.elapsed = S.d.elapsed_s || S.elapsed;
  S.filter = "all";
  document.getElementById("mq-pause").hidden = true;
  root.classList.remove("is-paused");
  paintClock();
  S.view = "results";
  history.replaceState(null, "", location.pathname + "?view=results");
  render();
}

function ring(pct) {
  const r = 52, c = 2 * Math.PI * r;
  return `<svg class="mq-ring" viewBox="0 0 120 120" aria-hidden="true">
    <circle cx="60" cy="60" r="${r}" class="mq-ring-bg"/>
    <circle cx="60" cy="60" r="${r}" class="mq-ring-fg" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct)}"/></svg>`;
}

function verdict(p) {
  return p >= 0.9 ? ["Outstanding", "A* territory — keep it sharp."]
    : p >= 0.75 ? ["Strong", "Clean up the few slips below and you're there."]
    : p >= 0.6 ? ["Getting there", "Your weakest chapters are listed below — start with those."]
    : p >= 0.4 ? ["Keep going", "Work through the wrong ones with the explanations."]
    : ["A starting point", "Go through every explanation, then try a topical set on your weakest chapter."];
}

function renderResults(main) {
  const d = S.d, rv = d.review || { right: d.score, wrong: 0, blank: 0, topics: [] };
  const pct = d.total ? d.score / d.total : 0;
  const [title, line] = verdict(pct);
  const weak = rv.topics.filter((t) => t.total && t.right / t.total < 0.7).slice(0, 3).map((t) => t.topic);
  const avg = d.count ? Math.round((d.elapsed_s || S.elapsed) / d.count) : 0;
  main.innerHTML = `
    <div class="mq-results">
      <section class="mq-hero">
        <div class="mq-ringwrap">${ring(pct)}<div class="mq-ringtxt"><b>${Math.round(pct * 100)}%</b><span>${d.score}/${d.total}</span></div></div>
        <div class="mq-hero-txt">
          <p class="vw-eyebrow">Results</p>
          <h1>${title}</h1>
          <p>${line}</p>
          <ul class="mq-tally">
            <li class="is-right"><b>${rv.right}</b> correct</li>
            <li class="is-wrong"><b>${rv.wrong}</b> wrong</li>
            <li><b>${rv.blank}</b> blank</li>
            <li><b>${fmt(d.elapsed_s || S.elapsed)}</b> taken · ${avg}s per question</li>
          </ul>
          <div class="mq-actions">
            <button type="button" class="vw-btn" data-review="first-wrong">Review mistakes</button>
            <button type="button" class="mq-btn" data-view="paper">📄 Paper with answers</button>
            <button type="button" class="mq-btn" data-act="report">⤓ PDF report</button>
            ${weak.length ? `<a class="mq-btn" href="${esc(BOOT.backUrl)}?topics=${encodeURIComponent(weak.join("|"))}#start">🎯 Practise weak chapters</a>` : ""}
          </div>
        </div>
      </section>
      <div class="mq-rgrid">
        <section class="mq-card2">
          <h2>Every question</h2>
          <p class="mq-sub">Tap one to see your answer, the right one, and why.</p>
          <div class="mq-tiles">${Q().map((q) => {
            const st = !q.key ? "is-none" : q.correct ? "is-right" : q.answer ? "is-wrong" : "is-blank";
            return `<button type="button" class="mq-tile ${st}" data-review="${q.n}"
              title="Q${q.n}: ${q.answer ? `you ${q.answer}` : "blank"}${q.key ? `, answer ${q.key}` : ""}">
              <span>${q.n}</span><i>${!q.key ? "–" : q.correct ? "✓" : q.answer || "·"}</i></button>`;
          }).join("")}</div>
        </section>
        <section class="mq-card2">
          <h2>By chapter</h2>
          <p class="mq-sub">Weakest first.</p>
          <ul class="mq-bars">${rv.topics.filter((t) => t.total).map((t) => {
            const p = t.right / t.total;
            return `<li><span class="mq-bar-name">${esc(t.topic)}</span><b>${t.right}/${t.total}</b>
              <span class="mq-bar"><i style="width:${Math.round(p * 100)}%" data-tone="${p >= 0.75 ? "good" : p >= 0.5 ? "mid" : "low"}"></i></span></li>`;
          }).join("")}</ul>
        </section>
      </div>
    </div>`;
}

function openReview(n) {
  S.i = n - 1;
  S.view = "single";
  history.replaceState(null, "", location.pathname + "?view=single");
  render();
  const q = cur();
  if (q.key && !q.correct && !narrow()) openPanelFor(q.n, "explain");
}

// ── PDF report (the existing report job) ────────────────────────────────────
async function report() {
  const box = await modal(`
    <p class="vw-eyebrow">PDF report</p><h2>Download your results</h2>
    <p>Every question with your answer, the official answer and a worked explanation for the ones you got wrong.</p>
    <div class="mq-rep" id="mq-rep"><div class="vw-bar"><i style="width:4%"></i></div><p class="mq-sub">Starting…</p></div>`, true);
  try {
    const { job_id } = await api("/api/mcq/report", { method: "POST", body: {
      items: Q().map((q) => ({ question_id: q.qid, your_answer: q.answer || null,
                                time_secs: Math.round(q.time_s || 0) })),
      syllabus: S.d.syllabus, title: S.d.title,
      subtitle: `${S.d.score}/${S.d.total} correct`, time_label: fmt(S.d.elapsed_s || S.elapsed),
      explain: "wrong" } });
    for (;;) {
      await new Promise((r) => setTimeout(r, 1200));
      if (!box.isConnected) return;
      const st = await api(`/api/mcq/report/${job_id}`);
      const pct = st.total ? Math.round(100 * (st.done || 0) / st.total) : 10;
      box.querySelector(".vw-bar i").style.width = `${Math.max(6, pct)}%`;
      box.querySelector(".mq-sub").textContent = st.phase || "Working…";
      if (st.state === "done") {
        box.querySelector("#mq-rep").innerHTML = `<a class="vw-btn" href="/api/mcq/report/${job_id}/pdf" download>⤓ Download PDF</a>`;
        return;
      }
      if (st.state === "error" || st.state === "failed") throw new Error(st.error || "the report failed");
    }
  } catch (e) {
    const rep = box.querySelector("#mq-rep");
    if (rep) rep.innerHTML = `<p class="mq-sub">Couldn't build the report: ${esc(e.message)}</p>`;
  }
}

// ── Side panel ──────────────────────────────────────────────────────────────
function openPanelFor(n, tab) {
  const q = Q()[n - 1];
  if (!q) return;
  const tabs = revealed(q) ? ["explain", "hint", "ms", "ask"] : ["hint"];
  const panel = document.getElementById("vw-panel");
  const was = panel.hidden;
  panel.hidden = false;
  root.classList.add("has-panel");
  openAiPanel(panel, { ...q, seq: q.n, your: q.answer }, { tab, tabs, onClose: () => closePanel() });
  if (was && !narrow()) S.pane?.refit();
}

function closePanel(quiet = false) {
  const panel = document.getElementById("vw-panel");
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  panel.innerHTML = "";
  root.classList.remove("has-panel");
  if (!quiet && !narrow()) S.pane?.refit();
}

// ── Little UI helpers ───────────────────────────────────────────────────────
function modal(html, dismissable = true) {
  document.querySelector(".mq-modal")?.remove();
  const wrap = document.createElement("div");
  wrap.className = "mq-modal";
  wrap.innerHTML = `<div class="mq-modal-card" role="dialog" aria-modal="true">${html}
    ${dismissable ? `<button type="button" class="mq-modal-x" aria-label="Close">✕</button>` : ""}</div>`;
  document.body.appendChild(wrap);
  wrap.addEventListener("click", (e) => {
    if (e.target === wrap || e.target.closest(".mq-modal-x")) wrap.remove();
  });
  return Promise.resolve(wrap.querySelector(".mq-modal-card"));
}

function confirmBox(title, body, yes) {
  return new Promise((resolve) => {
    modal(`<h2>${title}</h2><p>${body}</p>
      <div class="mq-modal-actions"><button type="button" class="mq-btn" data-no>Keep going</button>
      <button type="button" class="vw-btn" data-yes>${yes}</button></div>`, false).then((card) => {
      const done = (v) => { card.parentElement.remove(); resolve(v); };
      card.querySelector("[data-yes]").onclick = () => done(true);
      card.querySelector("[data-no]").onclick = () => done(false);
      card.querySelector("[data-yes]").focus();
    });
  });
}

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
  t._h = setTimeout(() => t.classList.remove("is-on"), 3400);
}

function toggleDrawer(force) {
  S.drawer = force ?? !S.drawer;
  root.classList.toggle("sheet-open", S.drawer);
  document.getElementById("mq-dock").setAttribute("aria-expanded", String(S.drawer));
}

// ── Events ──────────────────────────────────────────────────────────────────
root.addEventListener("click", (e) => {
  const t = e.target;
  const v = t.closest("[data-view]");
  if (v) { toggleDrawer(false); return setView(v.dataset.view); }
  const sv = t.closest("[data-start-view]");
  if (sv) {
    S.view = sv.dataset.startView;
    root.querySelectorAll("[data-start-view]").forEach((b) => b.setAttribute("aria-checked", String(b === sv)));
    return;
  }
  const p = t.closest("[data-pick]");
  if (p && !p.disabled) { const [n, L] = p.dataset.pick.split("|"); return pick(+n, L); }
  const f = t.closest("[data-flag]");
  if (f && !f.disabled) return flag(+f.dataset.flag);
  const go = t.closest("[data-go]");
  if (go) { toggleDrawer(false); return setCurrent(+go.dataset.go - 1, true); }
  const fl = t.closest("[data-filter]");
  if (fl) { S.filter = fl.dataset.filter; return renderSheet(); }
  const rv = t.closest("[data-review]");
  if (rv) {
    const n = rv.dataset.review === "first-wrong"
      ? (Q().find((q) => q.key && !q.correct)?.n || 1) : +rv.dataset.review;
    return openReview(n);
  }
  const op = t.closest("[data-open]");
  if (op) return openPanelFor(+op.dataset.n, op.dataset.open);
  const act = t.closest("[data-act]")?.dataset.act;
  if (act === "begin") {
    if (!S.ready) return;                       // the clock never runs on an unloaded paper
    root.classList.remove("is-intro"); beat(true); render(); startClock();
  }
  else if (act === "pause") togglePause();
  else if (act === "submit") submit();
  else if (act === "prev") setCurrent(S.i - 1, true);
  else if (act === "next") setCurrent(S.i + 1, true);
  else if (act === "drawer") toggleDrawer();
  else if (act === "report") report();
});

document.addEventListener("keydown", (e) => {
  if (!S.d || e.target.matches?.("input, textarea, select, [contenteditable]") || e.ctrlKey || e.metaKey || e.altKey) return;
  if (document.querySelector(".mq-modal")) { if (e.key === "Escape") document.querySelector(".mq-modal").remove(); return; }
  if (e.key === "Escape") { closePanel(); toggleDrawer(false); return; }
  if (S.view === "results" || !root.querySelector("#mq-sheet .mq-rows") || S.paused) return;
  if (!S.running && !submitted() && S.elapsed === 0 && root.querySelector(".mq-intro")) return;
  const k = e.key.toUpperCase();
  const idx = LETTERS.indexOf(k) >= 0 ? LETTERS.indexOf(k) : ["1", "2", "3", "4"].indexOf(e.key);
  if (idx >= 0 && S.ann.tool === "pointer") { e.preventDefault(); pick(S.i + 1, LETTERS[idx]); return; }
  if (e.key === "ArrowRight" || (e.key === "Enter" && S.view === "single")) { e.preventDefault(); setCurrent(S.i + 1, true); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); setCurrent(S.i - 1, true); }
  else if (k === "F") flag(S.i + 1);
});

window.addEventListener("resize", debounce(() => {
  S.pane?.refit();
  if (S.view === "single") {
    const box = document.querySelector(".mq-single .mq-crop");
    if (box) drawCrop(box, +box.dataset.qid).then(() => S.ann.repaint());
  }
}, 250));

boot();
