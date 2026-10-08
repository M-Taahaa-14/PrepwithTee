/* builder-review.js — step 2 of the topical builder: "Review & customise".
 *
 * Step 1 (builder.js) picks chapters, years and papers. This step shows the
 * actual questions before anything is built (tutor, 2026-10-08 - mock tests are
 * mainly for teachers, who need to see what goes in):
 *   - a mix panel: per chapter / subtopic, how many MCQ and how many theory
 *     questions (or fill to a mark target), and which difficulties to draw from;
 *   - the list itself, Section A (multiple choice) then Section B (structured),
 *     each question as a card: thumbnail, source, chapter, marks, difficulty;
 *     Preview (full question + mark scheme), Swap, Lock, Remove, drag / ↑↓ to
 *     reorder inside its section, + Add questions from the whole selection;
 *   - Undo, Reshuffle unlocked, Build.
 * Difficulty is teachers' ratings only (no estimate yet): teachers rate from the
 * card or the preview, everyone sees the median.
 *
 * The draft is an ordered id list kept in localStorage per subject + selection,
 * so a reload doesn't lose a teacher's work. Build sends the exact ids
 * (POST /api/booklets {ids}); the server checks every one is in the selection.
 */
import { api, UpgradeRequiredError } from "/auth.js?v=20261005c";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode / full */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const DIFF = { 1: "Easy", 2: "Medium", 3: "Hard" };
const DIFF_KEYS = ["1", "2", "3", "unrated"];
const DIFF_LABEL = { 1: "Easy", 2: "Medium", 3: "Hard", unrated: "Unrated" };
const HISTORY_MAX = 30;

let ctx = null;        // { root, syl, selection(), kind, includeMs, onBack(), onKind(k) }
let rv = null;         // review state

/** Open the review step. `fromIds` = an existing paper's questions (Edit this paper). */
export async function openReview(context, { fromIds = null } = {}) {
  ctx = context;
  const sel = ctx.selection();
  const sig = JSON.stringify(sel);
  const saved = fromIds ? null : store.get(key(), null);
  rv = {
    sig, questions: [], locked: new Set(), history: [], buckets: [], plan: {}, hasMcq: false,
    canRate: false, pool: 0, mode: "count", marksTarget: 40, diff: new Set(), busy: true, msg: "",
    drawer: null,            // {type: "preview"|"browse", ...}
  };
  render();
  try {
    if (fromIds?.length) {
      await draft({ locked: fromIds, plan: {} }, { keepOrder: fromIds });
    } else if (saved && saved.sig === sig && saved.ids?.length) {
      rv.mode = saved.mode || "count"; rv.marksTarget = saved.marksTarget || 40;
      rv.diff = new Set(saved.diff || []);
      await draft({ locked: saved.ids, plan: {} }, { keepOrder: saved.ids, locked: saved.locked || [] });
    } else {
      await draft({ max_questions: ctx.maxQ });
    }
  } catch (e) {
    rv.msg = e.message || "Couldn't load the questions.";
  }
  rv.busy = false;
  render();
  ctx.root.scrollIntoView({ block: "start" });
}

function key() { return `bld.draft.${ctx.syl}`; }
function save() {
  store.set(key(), { sig: rv.sig, ids: rv.questions.map((q) => q.id), locked: [...rv.locked],
                     mode: rv.mode, marksTarget: rv.marksTarget, diff: [...rv.diff] });
}

// ── Server calls ────────────────────────────────────────────────────────────
async function draft(extra, { keepOrder = null, locked = null } = {}) {
  const body = { ...ctx.selection(), ...extra };
  if (rv.diff.size && !("difficulty" in body)) body.difficulty = [...rv.diff];
  const d = await api("/api/booklets/draft", { method: "POST", body });
  rv.buckets = d.buckets; rv.hasMcq = d.has_mcq; rv.canRate = d.can_rate; rv.pool = d.pool;
  if (!extra.plan || Object.keys(extra.plan).length) rv.plan = d.plan;
  else rv.plan = planFromList(d.questions);
  let qs = d.questions;
  if (keepOrder) {                         // the order the user had, not the server's
    const pos = new Map(keepOrder.map((id, i) => [id, i]));
    qs = [...qs].sort((a, b) => (pos.get(a.id) ?? 1e9) - (pos.get(b.id) ?? 1e9));
  }
  rv.questions = sectioned(qs);
  if (locked) rv.locked = new Set(locked.filter((id) => qs.some((q) => q.id === id)));
  save();
}

function planFromList(qs) {
  const plan = {};
  for (const b of rv.buckets) plan[b.key] = { mcq: 0, theory: 0 };
  for (const q of qs) {
    const p = plan[q.bucket] || (plan[q.bucket] = { mcq: 0, theory: 0 });
    p[q.mcq ? "mcq" : "theory"]++;
  }
  return plan;
}

const sectioned = (qs) => [...qs.filter((q) => q.mcq), ...qs.filter((q) => !q.mcq)];

function remember() {
  rv.history.push({ questions: rv.questions.slice(), locked: new Set(rv.locked) });
  if (rv.history.length > HISTORY_MAX) rv.history.shift();
}
function change(fn) { remember(); fn(); rv.questions = sectioned(rv.questions); save(); render(); }

/** Apply the mix panel: keep locked questions, redraw the rest to the plan. */
async function applyMix() {
  remember();
  rv.busy = true; rv.msg = ""; render();
  const keep = rv.questions.filter((q) => rv.locked.has(q.id)).map((q) => q.id);
  const extra = { locked: keep, plan: rv.plan, seed: Math.floor(Math.random() * 2 ** 31) };
  if (rv.mode === "marks") extra.marks_target = rv.marksTarget;
  try {
    await draft(extra, { keepOrder: rv.questions.map((q) => q.id), locked: keep });
    if (!rv.questions.length) rv.msg = "Nothing matches that mix — loosen the difficulty filter or add counts.";
  } catch (e) { rv.msg = e.message; rv.history.pop(); }
  rv.busy = false; render();
}

// ── Totals ──────────────────────────────────────────────────────────────────
function totals(qs = rv.questions) {
  const t = { n: qs.length, marks: 0, mcq: 0, theory: 0, diff: { 1: 0, 2: 0, 3: 0, unrated: 0 }, by: {} };
  for (const q of qs) {
    t.marks += q.marks || 0;
    t[q.mcq ? "mcq" : "theory"]++;
    t.diff[q.difficulty?.value || "unrated"]++;
    t.by[q.bucket] = (t.by[q.bucket] || 0) + 1;
  }
  return t;
}

// ── Render ──────────────────────────────────────────────────────────────────
function render() {
  if (!rv) return;
  const test = ctx.kind === "test";
  const t = totals();
  const mins = Math.max(5, test ? t.marks : Math.round(t.marks * 1.2 / 5) * 5);
  const mcqQs = rv.questions.filter((q) => q.mcq), thQs = rv.questions.filter((q) => !q.mcq);
  const both = mcqQs.length && thQs.length;
  let n = 0;
  const section = (title, qs, kind) => qs.length ? `
    <section class="rv-sec" data-sec-kind="${kind}" aria-label="${esc(title)}">
      <h3>${both ? esc(title) : kind === "mcq" ? "Multiple choice" : "Structured questions"}
        <span>${qs.length} Q · ${qs.reduce((s, q) => s + (q.marks || 0), 0)} marks</span></h3>
      <ol class="rv-cards">${qs.map((q) => cardHTML(q, ++n, qs)).join("")}</ol>
    </section>` : "";
  const focus = document.activeElement?.dataset?.focusKey;
  // A box being typed in is carried over as the SAME element - a fresh copy +
  // focus() moves the caret to the start (the builder's "selcric" bug).
  const typing = focus && document.activeElement.matches("input[type=search], input[type=number]")
    ? document.activeElement : null;

  ctx.root.innerHTML = `
  <div class="rv" aria-busy="${rv.busy}">
    <div class="rv-top">
      <button type="button" class="rv-back" data-rv="back">← Chapters</button>
      <div class="rv-title"><p class="bld-eyebrow">Step 2 of 2</p><h2>Review &amp; customise</h2></div>
      <div class="bld-kind rv-kind" role="radiogroup" aria-label="Kind of paper">
        <button type="button" role="radio" data-rv-kind="booklet" aria-checked="${!test}"><b>Practice booklet</b></button>
        <button type="button" role="radio" data-rv-kind="test" aria-checked="${test}"><b>Mock test</b></button>
      </div>
    </div>
    ${summaryHTML(t, mins, test)}
    <p class="rv-msg${rv.msg ? " is-on" : ""}" role="status">${esc(rv.msg)}</p>
    <div class="rv-limit" id="rv-limit" hidden></div>
    <div class="rv-grid">
      ${mixHTML(t)}
      <div class="rv-list">
        ${rv.busy && !rv.questions.length ? `<div class="bld-loading" role="status"><span class="bld-spin"></span>Picking questions…</div>` : ""}
        ${!rv.busy && !rv.questions.length ? `<div class="rv-empty"><b>No questions yet.</b>
            <span>Set the mix on the left and press <i>Apply mix</i>, or add questions one by one.</span></div>` : ""}
        ${section("Section A — Multiple choice", mcqQs, "mcq")}
        ${section("Section B — Structured questions", thQs, "theory")}
        <button type="button" class="rv-add" data-rv="add">+ Add questions</button>
      </div>
    </div>
    ${drawerHTML()}
  </div>`;
  const fresh = focus && ctx.root.querySelector(`[data-focus-key="${CSS.escape(focus)}"]`);
  if (fresh && typing && fresh !== typing) {
    fresh.replaceWith(typing);
    typing.focus({ preventScroll: true });
  } else fresh?.focus({ preventScroll: true });
  if (rv.limit && window.PWTLimit) window.PWTLimit.inline(document.getElementById("rv-limit"), rv.limit);
}

function summaryHTML(t, mins, test) {
  const bar = (parts) => `<span class="rv-bar">${parts.filter((p) => p.n).map((p) =>
    `<i class="${p.cls}" style="flex:${p.n}" title="${esc(p.label)}: ${p.n}"></i>`).join("")}</span>`;
  const chapters = rv.buckets.map((b, i) => ({ n: t.by[b.key] || 0, label: b.label, cls: `rv-tone-${i % 6}` }));
  const diffs = DIFF_KEYS.map((k) => ({ n: t.diff[k], label: DIFF_LABEL[k], cls: `rv-d-${k}` }));
  return `<div class="rv-sum">
    <div class="rv-sum-main">
      <b>${t.n}</b><span>questions</span>
      <b>${t.marks}</b><span>marks</span>
      <b>${mins}</b><span>min${test ? " allowed" : ""}</span>
      ${rv.hasMcq ? `<em class="rv-split">${t.mcq} MCQ · ${t.theory} theory</em>` : ""}
    </div>
    <div class="rv-sum-bars">
      <div><small>Chapters</small>${bar(chapters)}</div>
      <div><small>Difficulty</small>${bar(diffs)}</div>
    </div>
    <div class="rv-sum-acts">
      <button type="button" class="rv-ghost" data-rv="undo" ${rv.history.length ? "" : "disabled"}>Undo</button>
      <button type="button" class="cat-btn" data-rv="build" ${t.n && !rv.busy ? "" : "disabled"}>
        ${test ? "Build mock test" : "Build booklet"} <span aria-hidden="true">↗</span></button>
    </div>
  </div>`;
}

function stepper(bucket, kind, avail) {
  const v = rv.plan[bucket]?.[kind] ?? 0;
  const k = `${bucket}|${kind}`;
  return `<span class="rv-step${avail ? "" : " is-zero"}">
    <button type="button" data-rv-step="-1" data-k="${esc(k)}" aria-label="Fewer" ${v > 0 ? "" : "disabled"}>−</button>
    <input type="number" min="0" max="${avail}" value="${v}" data-rv-count="${esc(k)}" data-focus-key="c:${esc(k)}"
      aria-label="${kind === "mcq" ? "MCQ" : "Theory"} questions" ${avail ? "" : "disabled"}>
    <button type="button" data-rv-step="1" data-k="${esc(k)}" aria-label="More" ${v < avail ? "" : "disabled"}>+</button>
    <small>of ${avail}</small></span>`;
}

function mixHTML(t) {
  const rows = rv.buckets.map((b, i) => `
    <li class="rv-mix-row">
      <span class="rv-mix-name"><i class="rv-dot rv-tone-${i % 6}"></i>${esc(b.label)}
        <small>${t.by[b.key] || 0} in paper</small></span>
      ${rv.hasMcq ? `<span class="rv-mix-cell"><small>MCQ</small>${stepper(b.key, "mcq", b.mcq)}</span>` : ""}
      <span class="rv-mix-cell"><small>${rv.hasMcq ? "Theory" : "Questions"}</small>${stepper(b.key, "theory", b.theory)}</span>
    </li>`).join("");
  const planned = Object.values(rv.plan).reduce((s, p) => s + (p.mcq || 0) + (p.theory || 0), 0);
  return `<aside class="rv-mix" aria-label="Mix">
    <details class="rv-mix-box" open>
      <summary><b>Mix</b><span>${planned} planned</span></summary>
      <div class="rv-seg" role="radiogroup" aria-label="Fill by">
        <button type="button" role="radio" data-rv-mode="count" aria-checked="${rv.mode === "count"}">By count</button>
        <button type="button" role="radio" data-rv-mode="marks" aria-checked="${rv.mode === "marks"}">To a mark total</button>
      </div>
      ${rv.mode === "marks" ? `<label class="rv-marks">Total marks
          <input type="number" min="1" max="1000" value="${rv.marksTarget}" data-rv="marks" data-focus-key="marks"></label>
        <p class="bld-hint">The counts below become the most from each chapter.</p>` : ""}
      <ol class="rv-mix-rows">${rows}</ol>
      <div class="rv-diff"><small>Difficulty to draw from</small>
        <div class="bld-chips">${DIFF_KEYS.map((k) => `<button type="button" class="bld-chip${rv.diff.has(k) ? " is-on" : ""}"
          data-rv-diff="${k}" aria-pressed="${rv.diff.has(k)}">${DIFF_LABEL[k]}</button>`).join("")}</div>
        <p class="bld-hint">${rv.diff.size ? "Only these." : "All difficulties."} Ratings come from teachers${rv.canRate ? " — rate questions from their cards" : ""}.</p>
      </div>
      <button type="button" class="cat-btn rv-apply" data-rv="apply" ${rv.busy ? "disabled" : ""}>Apply mix</button>
      <p class="bld-hint">Locked questions stay; the rest are drawn again.</p>
      <div class="rv-mix-foot">
        <button type="button" class="rv-ghost" data-rv="clear" ${rv.questions.length ? "" : "disabled"}>Clear list</button>
      </div>
    </details>
  </aside>`;
}

function diffPill(q) {
  const d = q.difficulty || {};
  const v = d.value;
  const who = d.mine && rv.canRate ? "your rating" : d.n ? `${d.n} teacher${d.n > 1 ? "s" : ""}` : "not rated yet";
  return `<span class="rv-pill rv-d-${v || "unrated"}" title="Difficulty: ${v ? DIFF[v] : "unrated"} (${who})">${v ? DIFF[v] : "Unrated"}</span>`;
}

function rater(q) {
  if (!rv.canRate) return "";
  const mine = q.difficulty?.mine;
  return `<span class="rv-rate" role="group" aria-label="Your difficulty rating">${[1, 2, 3].map((v) =>
    `<button type="button" data-rv-rate="${v}" data-id="${q.id}" aria-pressed="${mine === v}"
       title="Rate ${DIFF[v]}${mine === v ? " (tap again to clear)" : ""}" class="rv-d-${v}">${DIFF[v][0]}</button>`).join("")}</span>`;
}

function cardHTML(q, num, sectionQs) {
  const locked = rv.locked.has(q.id);
  const i = sectionQs.indexOf(q);
  const sub = q.subtopic && q.bucket !== q.chapter ? "" : q.subtopic ? ` › ${esc(q.subtopic)}` : "";
  const bi = rv.buckets.findIndex((b) => b.key === q.bucket);
  return `<li class="rv-card${locked ? " is-locked" : ""}" draggable="true" data-id="${q.id}">
    <span class="rv-num" aria-hidden="true">Q${num}</span>
    <button type="button" class="rv-thumb" data-rv="preview" data-id="${q.id}" aria-label="Preview Q${num}">
      <img src="${esc(q.thumb)}" alt="" loading="lazy" decoding="async"></button>
    <div class="rv-info">
      <p class="rv-ref"><b>Q${num}</b> ${esc(q.ref)}</p>
      <p class="rv-tags">
        <span class="rv-tag"><i class="rv-dot rv-tone-${Math.max(0, bi) % 6}"></i>${esc(rv.buckets[bi]?.label || q.chapter)}${sub}</span>
        ${q.marks ? `<span class="rv-tag">${q.marks} mark${q.marks === 1 ? "" : "s"}</span>` : ""}
        ${q.mcq ? `<span class="rv-tag rv-mcq">MCQ</span>` : ""}
        ${diffPill(q)}${rater(q)}
      </p>
      ${q.snippet ? `<p class="rv-snip">${esc(q.snippet)}</p>` : ""}
      <div class="rv-acts">
        <button type="button" data-rv="preview" data-id="${q.id}">Preview</button>
        <button type="button" data-rv="swap" data-id="${q.id}">Swap</button>
        <button type="button" data-rv="lock" data-id="${q.id}" aria-pressed="${locked}"
          title="Locked questions stay when you apply the mix">${locked ? "🔒 Locked" : "Lock"}</button>
        <button type="button" data-rv="up" data-id="${q.id}" aria-label="Move up" data-focus-key="up:${q.id}" ${i > 0 ? "" : "disabled"}>↑</button>
        <button type="button" data-rv="down" data-id="${q.id}" aria-label="Move down" data-focus-key="down:${q.id}" ${i < sectionQs.length - 1 ? "" : "disabled"}>↓</button>
        <button type="button" class="rv-remove" data-rv="remove" data-id="${q.id}" aria-label="Remove Q${num}">Remove</button>
      </div>
    </div>
  </li>`;
}

// ── Drawer: preview / browse (swap + add) ───────────────────────────────────
function drawerHTML() {
  const d = rv.drawer;
  if (!d) return "";
  const head = (title, sub = "") => `<header class="rv-dr-head"><div><h3>${esc(title)}</h3>${sub}</div>
    <button type="button" class="rv-close" data-rv="close" aria-label="Close">×</button></header>`;
  let body = "";
  if (d.type === "preview") {
    const r = d.data;
    body = head(r ? r.ref : "Loading…") + (r ? `
      <div class="rv-dr-body">
        <p class="rv-tags">${diffPill({ difficulty: r.difficulty })}${rater({ id: r.id, difficulty: r.difficulty })}</p>
        <img class="rv-full" src="${esc(r.image)}" alt="The full question">
        <details class="rv-ms"${d.showMs ? " open" : ""}><summary>Show mark scheme</summary>
          ${r.mcq ? `<p class="rv-answer">Answer: <b>${esc(r.answer || "not available")}</b></p>`
                  : `<img class="rv-ms-img" src="${esc(r.ms_image)}" alt="Official mark scheme" loading="lazy">`}
        </details>
      </div>
      <footer class="rv-dr-foot">
        ${rv.questions.some((q) => q.id === r.id)
          ? `<button type="button" data-rv="swap" data-id="${r.id}">Swap this question</button>
             <button type="button" class="rv-remove" data-rv="remove" data-id="${r.id}">Remove</button>`
          : `<button type="button" class="cat-btn" data-rv="use" data-id="${r.id}">${d.swapFor ? "Use this instead" : "Add to paper"}</button>`}
      </footer>` : `<div class="bld-loading"><span class="bld-spin"></span>Loading…</div>`);
  } else {
    const swapping = d.swapFor ? rv.questions.find((q) => q.id === d.swapFor) : null;
    const bucketOpts = [`<option value="">All chapters</option>`, ...rv.buckets.map((b) =>
      `<option value="${esc(b.key)}" ${d.bucket === b.key ? "selected" : ""}>${esc(b.label)}</option>`)].join("");
    body = head(swapping ? `Swap Q${rv.questions.indexOf(swapping) + 1}` : "Add questions",
      swapping ? `<p>${esc(swapping.ref)} · same chapter and type</p>` : "") + `
      <div class="rv-filters">
        <label class="bld-search"><span class="sr-only">Search question text</span>
          <input type="search" data-rv="q" value="${esc(d.q)}" placeholder="Search the question text" data-focus-key="q"></label>
        <select data-rv="bucket" aria-label="Chapter">${bucketOpts}</select>
        ${rv.hasMcq ? `<select data-rv="kind" aria-label="Type">
          <option value="">MCQ + theory</option>
          <option value="mcq" ${d.kind === "mcq" ? "selected" : ""}>MCQ only</option>
          <option value="theory" ${d.kind === "theory" ? "selected" : ""}>Theory only</option></select>` : ""}
        <select data-rv="sort" aria-label="Sort">
          ${[["recent", "Newest first"], ["oldest", "Oldest first"], ["marks_high", "Most marks"], ["marks_low", "Fewest marks"]]
            .map(([v, l]) => `<option value="${v}" ${d.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="bld-chips">${DIFF_KEYS.map((k) => `<button type="button" class="bld-chip${d.diff.has(k) ? " is-on" : ""}"
          data-rv-bdiff="${k}" aria-pressed="${d.diff.has(k)}">${DIFF_LABEL[k]}</button>`).join("")}</div>
      </div>
      <div class="rv-dr-body">
        <p class="rv-count">${d.loading && !d.items.length ? "Searching…" : `${d.total.toLocaleString()} question${d.total === 1 ? "" : "s"}`}</p>
        <ol class="rv-alts">${d.items.map((q) => `<li class="rv-alt">
          <button type="button" class="rv-thumb" data-rv="peek" data-id="${q.id}" aria-label="Preview ${esc(q.ref)}">
            <img src="${esc(q.thumb)}" alt="" loading="lazy"></button>
          <div><p class="rv-ref">${esc(q.ref)}</p>
            <p class="rv-tags">${q.marks ? `<span class="rv-tag">${q.marks} mark${q.marks === 1 ? "" : "s"}</span>` : ""}
              ${q.mcq ? `<span class="rv-tag rv-mcq">MCQ</span>` : ""}${diffPill(q)}</p>
            ${q.snippet ? `<p class="rv-snip">${esc(q.snippet)}</p>` : ""}
            <button type="button" class="cat-btn rv-use" data-rv="use" data-id="${q.id}">${swapping ? "Use this" : "Add"}</button>
          </div></li>`).join("")}</ol>
        ${d.items.length < d.total ? `<button type="button" class="rv-ghost rv-more" data-rv="more" ${d.loading ? "disabled" : ""}>
          ${d.loading ? "Loading…" : "Show more"}</button>` : ""}
      </div>`;
  }
  return `<div class="rv-scrim" data-rv="close"></div>
    <div class="rv-drawer" role="dialog" aria-modal="true" aria-label="${d.type === "preview" ? "Question preview" : "Find questions"}">${body}</div>`;
}

async function openPreview(id, swapFor = null) {
  const back = rv.drawer?.type === "browse" ? rv.drawer : null;
  rv.drawer = { type: "preview", id, data: null, swapFor: swapFor ?? back?.swapFor ?? null, back };
  render();
  try {
    rv.drawer.data = await api(`/api/question/${id}/review`);
  } catch (e) {
    rv.drawer = null; rv.msg = e.message;
  }
  render();
}

function openBrowse(swapFor = null) {
  const q = swapFor ? rv.questions.find((x) => x.id === swapFor) : null;
  rv.drawer = { type: "browse", swapFor, q: "", bucket: q?.bucket || "", kind: q ? (q.mcq ? "mcq" : "theory") : "",
                sort: "recent", diff: new Set(), items: [], total: 0, page: 0, loading: false };
  render();
  browse(true);
}

let browseSeq = 0;
async function browse(reset) {
  const d = rv.drawer;
  if (!d || d.type !== "browse") return;
  const seq = ++browseSeq;
  if (reset) { d.page = 0; d.items = []; }
  d.loading = true; render();
  try {
    const r = await api("/api/booklets/alternatives", { method: "POST", body: {
      ...ctx.selection(), bucket: d.bucket || null, kind: d.kind || null, q: d.q, sort: d.sort,
      difficulty: d.diff.size ? [...d.diff] : null, page: d.page,
      exclude: rv.questions.map((q) => q.id) } });
    if (seq !== browseSeq || rv.drawer !== d) return;
    d.items = reset ? r.questions : d.items.concat(r.questions);
    d.total = r.total;
  } catch (e) {
    if (rv.drawer === d) rv.msg = e.message;
  } finally {
    if (rv.drawer === d && seq === browseSeq) { d.loading = false; render(); }
  }
}

function use(id) {
  const d = rv.drawer;
  const pick = d?.type === "browse" ? d.items.find((q) => q.id === id)
             : d?.back?.items.find((q) => q.id === id);
  const swapFor = d?.swapFor;
  if (!pick) return;
  change(() => {
    if (swapFor) {
      const i = rv.questions.findIndex((q) => q.id === swapFor);
      if (i >= 0) rv.questions.splice(i, 1, pick);
      rv.locked.delete(swapFor);
    } else rv.questions.push(pick);
  });
  if (swapFor) { rv.drawer = null; render(); return; }
  // adding: stay in the browser, minus the one just added
  const b = d.type === "browse" ? d : d.back;
  b.items = b.items.filter((q) => q.id !== id);
  b.total = Math.max(0, b.total - 1);
  rv.drawer = b;
  render();
}

async function rate(id, v) {
  const all = [...rv.questions, ...(rv.drawer?.items || []), ...(rv.drawer?.back?.items || [])];
  const cur = all.find((q) => q.id === id)?.difficulty?.mine ?? rv.drawer?.data?.difficulty?.mine;
  const value = cur === v ? null : v;
  try {
    const r = await api(`/api/questions/${id}/rating`, { method: "PUT", body: { difficulty: value } });
    for (const q of all) if (q.id === id) q.difficulty = r.difficulty;
    if (rv.drawer?.data?.id === id) rv.drawer.data.difficulty = r.difficulty;
    save(); render();
  } catch (e) { rv.msg = e.message; render(); }
}

// ── Build ───────────────────────────────────────────────────────────────────
async function build() {
  const btn = ctx.root.querySelector('[data-rv="build"]');
  if (!rv.questions.length || !btn) return;
  const test = ctx.kind === "test";
  const win = window.open("", "_blank");
  if (win) {
    const dark = document.documentElement.dataset.theme === "dark";
    win.document.write(`<title>Setting up your paper…</title><body style="font:16px system-ui;
      display:grid;place-items:center;height:100vh;margin:0;color:${dark ? "#e8ebf1" : "#4C2E72"};
      background:${dark ? "#1c2130" : "#FDF9F3"}">Setting up your ${test ? "mock test" : "paper"}…</body>`);
  }
  btn.disabled = true; btn.textContent = "Building…";
  try {
    const r = await api("/api/booklets", { method: "POST", body: {
      ...ctx.selection(), ids: rv.questions.map((q) => q.id), kind: ctx.kind,
      include_ms: ctx.includeMs, max_questions: rv.questions.length } });
    if (win) win.location.href = r.url; else location.href = r.url;
    rv.msg = "Built — it opened in a new tab. You can keep editing and build again.";
    rv.limit = null;
    ctx.onBuilt?.();
  } catch (e) {
    win?.close();
    if (e instanceof UpgradeRequiredError && window.PWTLimit) { rv.msg = ""; rv.limit = e.detail; }
    else rv.msg = e.message || "Couldn't start the build. Try again.";
  }
  render();
}

// ── Events (delegated on the builder root; builder.js ignores them in review) ─
export function onImgError(e) {
  if (e.target?.classList?.contains("rv-ms-img")) {
    e.target.replaceWith(Object.assign(document.createElement("p"),
      { className: "bld-hint", textContent: "Mark scheme not available for this question." }));
  }
}

export function onClick(e) {
  const t = e.target.closest("[data-rv],[data-rv-kind],[data-rv-step],[data-rv-mode],[data-rv-diff],[data-rv-bdiff],[data-rv-rate]");
  if (!t) return;
  const id = t.dataset.id ? +t.dataset.id : null;
  if (t.dataset.rvKind) { ctx.onKind(t.dataset.rvKind); render(); return; }
  if (t.dataset.rvMode) { rv.mode = t.dataset.rvMode; save(); render(); return; }
  if (t.dataset.rvDiff) { toggle(rv.diff, t.dataset.rvDiff); save(); render(); return; }
  if (t.dataset.rvBdiff) { toggle(rv.drawer.diff, t.dataset.rvBdiff); browse(true); return; }
  if (t.dataset.rvRate) { rate(id, +t.dataset.rvRate); return; }
  if (t.dataset.rvStep) {
    const [b, k] = t.dataset.k.split("|");
    const avail = rv.buckets.find((x) => x.key === b)?.[k] ?? 0;
    const p = rv.plan[b] || (rv.plan[b] = { mcq: 0, theory: 0 });
    p[k] = Math.max(0, Math.min(avail, (p[k] || 0) + +t.dataset.rvStep));
    render(); return;
  }
  switch (t.dataset.rv) {
    case "back": ctx.onBack(); return;
    case "build": build(); return;
    case "apply": applyMix(); return;
    case "undo": {
      const h = rv.history.pop();
      if (h) { rv.questions = h.questions; rv.locked = h.locked; save(); render(); }
      return;
    }
    case "clear": change(() => { rv.questions = []; rv.locked.clear(); }); return;
    case "add": openBrowse(null); return;
    case "swap": openBrowse(id); return;
    case "preview": openPreview(id); return;
    case "peek": openPreview(id); return;
    case "use": use(id); return;
    case "more": rv.drawer.page++; browse(false); return;
    case "close":
      rv.drawer = rv.drawer?.type === "preview" && rv.drawer.back ? rv.drawer.back : null;
      render(); return;
    case "lock": toggle(rv.locked, id); save(); render(); return;
    case "remove":
      change(() => { rv.questions = rv.questions.filter((q) => q.id !== id); rv.locked.delete(id); });
      if (rv.drawer?.type === "preview") { rv.drawer = null; render(); }
      return;
    case "up": case "down": move(id, t.dataset.rv === "up" ? -1 : 1); return;
  }
}

export function onInput(e) {
  const t = e.target;
  if (t.dataset.rvCount) {
    const [b, k] = t.dataset.rvCount.split("|");
    const avail = rv.buckets.find((x) => x.key === b)?.[k] ?? 0;
    const p = rv.plan[b] || (rv.plan[b] = { mcq: 0, theory: 0 });
    p[k] = Math.max(0, Math.min(avail, Math.floor(+t.value || 0)));
  } else if (t.dataset.rv === "marks") {
    rv.marksTarget = Math.max(1, Math.min(1000, Math.floor(+t.value || 0)));
    save();
  } else if (t.dataset.rv === "q") {
    rv.drawer.q = t.value;
    clearTimeout(onInput.timer);
    onInput.timer = setTimeout(() => browse(true), 250);
  }
}

export function onChange(e) {
  const t = e.target;
  if (t.dataset.rvCount) { render(); return; }
  if (["bucket", "kind", "sort"].includes(t.dataset.rv) && rv.drawer) {
    rv.drawer[t.dataset.rv] = t.value;
    browse(true);
  }
}

export function onKey(e) {
  if (e.key === "Escape" && rv?.drawer) {
    rv.drawer = rv.drawer.type === "preview" && rv.drawer.back ? rv.drawer.back : null;
    render();
  }
}

function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

function move(id, dir) {
  const q = rv.questions.find((x) => x.id === id);
  const same = rv.questions.filter((x) => x.mcq === q.mcq);
  const i = same.indexOf(q), j = i + dir;
  if (j < 0 || j >= same.length) return;
  change(() => {
    [same[i], same[j]] = [same[j], same[i]];
    rv.questions = q.mcq ? [...same, ...rv.questions.filter((x) => !x.mcq)]
                         : [...rv.questions.filter((x) => x.mcq), ...same];
  });
}

// Drag to reorder - only inside a question's own section.
let dragId = null;
export function onDragStart(e) {
  const card = e.target.closest?.(".rv-card");
  if (!card) return;
  dragId = +card.dataset.id;
  card.classList.add("is-dragging");
  e.dataTransfer.effectAllowed = "move";
  try { e.dataTransfer.setData("text/plain", String(dragId)); } catch { /* old browsers */ }
}
export function onDragOver(e) {
  const card = e.target.closest?.(".rv-card");
  if (!card || dragId == null) return;
  const from = rv.questions.find((q) => q.id === dragId);
  const to = rv.questions.find((q) => q.id === +card.dataset.id);
  if (!from || !to || from.mcq !== to.mcq) return;
  e.preventDefault();
}
export function onDrop(e) {
  const card = e.target.closest?.(".rv-card");
  if (!card || dragId == null) return;
  e.preventDefault();
  const targetId = +card.dataset.id, id = dragId;
  dragId = null;
  if (targetId === id) { render(); return; }
  const from = rv.questions.find((q) => q.id === id);
  const to = rv.questions.find((q) => q.id === targetId);
  if (!from || !to || from.mcq !== to.mcq) { render(); return; }
  change(() => {
    const list = rv.questions.filter((q) => q.id !== id);
    const r = card.getBoundingClientRect();
    const after = e.clientY > r.top + r.height / 2;
    list.splice(list.indexOf(to) + (after ? 1 : 0), 0, from);
    rv.questions = list;
  });
}
export function onDragEnd() { dragId = null; ctx.root.querySelectorAll(".is-dragging").forEach((c) => c.classList.remove("is-dragging")); }
