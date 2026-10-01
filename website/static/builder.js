/* builder.js — the topical paper builder on /papers/{board}/{subject}.
 *
 * Chapters are grouped by the paper that examines them when a subject's papers
 * cover different content (A Level Maths P1/P3/P4/P5, Physics AS vs A2, 9618
 * P1-P4, O Level/IGCSE CS P1 vs P2 ...); chapters from any group can be mixed.
 * Every chapter shows its subtopics as chips: tick the chapter for all of it, or
 * tap chips for just those subtopics (the box then shows "partly"; ticking it
 * takes the whole chapter). Up to 4 chapters per paper.
 *
 * Two kinds of paper: a practice booklet (mark scheme after each question) or a
 * mock test (exam cover, random questions, mark scheme as a separate file that
 * unlocks when the student finishes). Build -> /papers/view/{id} in a new tab.
 * The exact pool size comes from POST /api/booklets/count (debounced).
 */
import { api, UpgradeRequiredError } from "/auth.js?v=20261001a";

const root = document.getElementById("builder");
const SYL = root?.dataset.syllabus;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const st = {
  tree: null, byName: new Map(),
  picks: new Map(),          // chapter name -> null (whole chapter) | Set(subtopics)
  closed: new Set(),         // collapsed group sections
  showSubs: store.get("bld.showSubs", true),
  y0: null, y1: null,
  papers: new Set(),         // empty = every component
  kind: "booklet",           // booklet | test
  maxQ: 20, includeMs: true,
  pool: null, poolMarks: 0, counting: false, filter: "", msg: "",
};

if (root && SYL) init();

async function init() {
  root.innerHTML = `<div class="bld-loading" role="status"><span class="bld-spin"></span>Loading chapters…</div>`;
  try {
    st.tree = await api(`/api/topical/${SYL}/tree`);
  } catch (e) {
    root.innerHTML = `<p class="bld-error" role="alert">Couldn't load the chapters: ${esc(e.message)}</p>`;
    return;
  }
  st.tree.chapters.forEach((c) => st.byName.set(c.name, c));
  st.y0 = st.tree.year_min; st.y1 = st.tree.year_max;
  const q = new URLSearchParams(location.search);
  // ?pick=A&pick=B (or A|B): pre-tick chapters - chapter pages, notes, "Build it again"
  const wants = q.getAll("pick").flatMap((x) => x.split("|")).filter((x) => st.byName.has(x));
  wants.slice(0, st.tree.max_chapters || 4).forEach((w) => st.picks.set(w, null));
  const want = wants.length > 0;
  if (q.get("mode") === "test") st.kind = "test";
  render();
  if (want || q.get("mode")) requestAnimationFrame(() => root.scrollIntoView({ block: "start" }));
  recount();
  loadRecent();
}

// ── Counts under the current filters ────────────────────────────────────────
function inYears(byYear) {
  let n = 0;
  for (const [y, c] of Object.entries(byYear || {})) if (+y >= st.y0 && +y <= st.y1) n += c;
  return n;
}
/** Questions in a chapter under the year range and paper filter; limited to
 *  `papers` (a group's components) when given. */
function chapterCount(ch, papers = null) {
  let use = papers ? papers.map(String) : null;
  if (st.papers.size) use = (use || [...st.papers]).filter((p) => st.papers.has(p));
  if (!use) return inYears(ch.counts_by_year);
  return use.reduce((n, p) => n + inYears((ch.paper_year || {})[p]), 0);
}
function groups() {
  const t = st.tree;
  if (t.groups?.length) return t.groups;
  return [{ key: "all", papers: null, title: "", chapters: t.chapters.map((c) => c.name) }];
}

// ── Render ──────────────────────────────────────────────────────────────────
const LEVEL_NAME = { AS: "AS Level", A2: "A Level" };

function chapterHTML(ch, g, gi, i) {
  const t = st.tree, max = t.max_chapters;
  const picked = st.picks.has(ch.name);
  const sel = st.picks.get(ch.name);
  const partial = picked && sel instanceof Set;
  const disabled = !picked && st.picks.size >= max;
  const n = chapterCount(ch, g.papers);
  const q = st.filter.trim().toLowerCase();
  const nameHit = !q || ch.display.toLowerCase().includes(q);
  const subHits = q ? ch.subtopics.filter((s) => s.name.toLowerCase().includes(q)) : [];
  const hidden = q && !nameHit && !subHits.length;
  const id = `c${gi}-${i}`;
  const chips = ch.subtopics.map((s) => {
    const on = picked && (!partial || sel.has(s.name));
    const hit = q && s.name.toLowerCase().includes(q);
    const c = inYears(s.counts_by_year);
    return `<button type="button" class="bld-subchip${on ? " is-on" : ""}${hit ? " is-hit" : ""}${c ? "" : " is-zero"}"
        data-sub="${esc(s.name)}" data-ch="${esc(ch.name)}" aria-pressed="${on}">
        <span>${esc(s.name)}</span><em>${c}</em></button>`;
  }).join("");
  const showChips = ch.subtopics.length && (st.showSubs || picked || subHits.length);
  return `<li class="bld-ch${picked ? " is-picked" : ""}${disabled ? " is-disabled" : ""}${n ? "" : " is-empty"}"
        ${hidden ? "hidden" : ""}>
      <div class="bld-ch-row">
        <input type="checkbox" id="${id}" data-ch="${esc(ch.name)}" ${picked && !partial ? "checked" : ""}
               ${partial ? 'data-partial="1"' : ""} ${disabled ? 'aria-disabled="true"' : ""}>
        <label for="${id}" class="bld-ch-name">${esc(ch.display)}</label>
        ${partial ? `<span class="bld-partial">${sel.size}/${ch.subtopics.length} subtopics</span>` : ""}
        <span class="bld-count" title="Questions under your filters">${n.toLocaleString()}<small> Q</small></span>
      </div>
      ${showChips ? `<div class="bld-subchips" role="group" aria-label="Subtopics of ${esc(ch.display)}">${chips}</div>` : ""}
    </li>`;
}

function render() {
  const t = st.tree, max = t.max_chapters;
  const gs = groups();
  const grouped = gs.length > 1 || gs[0].key !== "all";

  const sections = gs.map((g, gi) => {
    const chs = g.chapters.map((name) => st.byName.get(name)).filter(Boolean);
    const total = chs.reduce((n, ch) => n + chapterCount(ch, g.papers), 0);
    const pickedHere = chs.filter((ch) => st.picks.has(ch.name)).length;
    const closed = st.closed.has(g.key) && !st.filter;
    const list = `<ol class="bld-list">${chs.map((ch, i) => chapterHTML(ch, g, gi, i)).join("")}</ol>`;
    if (!grouped) return list;
    return `<section class="bld-sec" id="bld-g-${esc(g.key)}" data-level="${esc(g.level || "")}">
      <button type="button" class="bld-sec-head" data-sec="${esc(g.key)}" aria-expanded="${!closed}">
        <span class="bld-sec-eyebrow">${esc(g.eyebrow)}${g.level ? ` <i class="bld-level bld-level-${g.level}">${LEVEL_NAME[g.level]}</i>` : ""}</span>
        <span class="bld-sec-title">${esc(g.title)}</span>
        <span class="bld-sec-meta">${chs.length} chapters · ${total.toLocaleString()} Q${pickedHere ? ` · <b>${pickedHere} picked</b>` : ""}</span>
        <svg viewBox="0 0 10 6" width="12" height="8" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
      </button>
      <div class="bld-sec-body" ${closed ? "hidden" : ""}>${list}</div>
    </section>`;
  }).join("");

  const jump = grouped ? `<nav class="bld-jump" aria-label="Jump to a paper">${gs.map((g) =>
    `<a href="#bld-g-${esc(g.key)}">${esc(g.eyebrow.replace("Papers ", "P").replace("Paper ", "P").replace(" & ", "&"))}
      <span>${esc(g.title)}</span>${g.level ? `<i class="bld-level bld-level-${g.level}">${g.level}</i>` : ""}</a>`).join("")}</nav>` : "";

  const slots = Array.from({ length: max }, (_, k) => {
    const name = [...st.picks.keys()][k];
    if (!name) return `<li class="bld-slot is-empty"><span>Chapter ${k + 1}</span></li>`;
    const ch = st.byName.get(name);
    const sel = st.picks.get(name);
    return `<li class="bld-slot"><span>${esc(ch.display)}${sel instanceof Set ?
      `<small>${[...sel].map(esc).join(" · ")}</small>` : "<small>Whole chapter</small>"}</span>
      <button type="button" data-unpick="${esc(name)}" aria-label="Remove ${esc(ch.display)}">×</button></li>`;
  }).join("");

  const years = [];
  for (let y = t.year_max; y >= t.year_min; y--) years.push(y);
  const yOpts = (sel) => years.map((y) => `<option ${y === sel ? "selected" : ""}>${y}</option>`).join("");
  const comps = (t.components || []).map((c) => {
    const on = st.papers.has(String(c.paper));
    return `<button type="button" class="bld-chip${on ? " is-on" : ""}" data-paper="${c.paper}"
      aria-pressed="${on}" title="${esc(c.title || c.label)}">${esc(c.label)}${c.level ? ` <i>${c.level}</i>` : ""}</button>`;
  }).join("");

  const pool = st.pool;
  const maxAllowed = Math.max(1, Math.min(t.max_questions, pool ?? t.max_questions));
  if (st.maxQ > maxAllowed) st.maxQ = maxAllowed;
  const avgMarks = pool ? st.poolMarks / pool : 0;
  const canBuild = st.picks.size > 0 && pool > 0;
  const test = st.kind === "test";

  const focusId = document.activeElement?.id;   // keep keyboard users in place
  // A text box being typed in is carried over as the SAME element: a fresh copy
  // + focus() put the caret at the start, so "circle" typed as "c" + "ircle"
  // came out "ircle" + "c" (feedback 2026-09-30).
  const typing = document.activeElement?.matches?.("input[type=search], input[type=text]") &&
    root.contains(document.activeElement) ? document.activeElement : null;
  const caret = typing ? [typing.selectionStart, typing.selectionEnd, typing.selectionDirection] : null;
  root.innerHTML = `
  <div class="bld-grid">
    <div class="bld-main">
      <div class="bld-head">
        <div>
          <p class="bld-eyebrow">Topical paper builder</p>
          <h2>Pick your chapters</h2>
          <p>Tick up to ${max} chapters for all of them, or tap the subtopics you want.
             ${grouped ? "Chapters are grouped by the paper that examines them — you can mix papers." : ""}</p>
        </div>
      </div>
      <div class="bld-tools">
        <label class="bld-search"><span class="sr-only">Search chapters and subtopics</span>
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M13 13l4 4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          <input type="search" id="bld-filter" placeholder="Search chapters or subtopics"
                 value="${esc(st.filter)}" autocomplete="off"></label>
        <label class="bld-switch"><input type="checkbox" id="bld-showsubs" ${st.showSubs ? "checked" : ""}>
          <span>Show all subtopics</span></label>
      </div>
      ${jump}
      ${sections}
    </div>
    <aside class="bld-side" id="bld-side" aria-label="Paper options">
      <div class="bld-kind" role="radiogroup" aria-label="Kind of paper">
        <button type="button" role="radio" data-kind="booklet" aria-checked="${!test}">
          <b>Practice booklet</b><span>Mark scheme after each question</span></button>
        <button type="button" role="radio" data-kind="test" aria-checked="${test}">
          <b>Mock test</b><span>Exam cover · separate mark scheme</span></button>
      </div>
      <div class="bld-block">
        <div class="bld-label">Your chapters <b>${st.picks.size}/${max}</b></div>
        <ol class="bld-slots">${slots}</ol>
        <p class="bld-msg${st.msg ? " is-on" : ""}" role="status" id="bld-msg">${esc(st.msg)}</p>
      </div>
      <div class="bld-block">
        <label class="bld-label" for="bld-y0">Years</label>
        <div class="bld-years">
          <select id="bld-y0" aria-label="From year">${yOpts(st.y0)}</select>
          <span aria-hidden="true">to</span>
          <select id="bld-y1" aria-label="To year">${yOpts(st.y1)}</select>
        </div>
      </div>
      ${comps ? `<div class="bld-block"><div class="bld-label">Papers <span class="bld-dim">${st.papers.size ? `${st.papers.size} picked` : "all"}</span></div>
        <div class="bld-chips">${comps}</div></div>` : ""}
      <div class="bld-block">
        <label class="bld-label" for="bld-n">Questions
          <span class="bld-pool">${st.counting ? "counting…" :
            pool == null ? "" : `${pool.toLocaleString()} available`}</span></label>
        <div class="bld-qty">
          <input type="range" id="bld-n" min="1" max="${maxAllowed}" value="${st.maxQ}"
                 ${pool ? "" : "disabled"}>
          <output for="bld-n" class="bld-big">${pool ? st.maxQ : "–"}</output>
        </div>
        <p class="bld-hint" id="bld-est">${estimate(avgMarks)}</p>
      </div>
      ${test ? `<p class="bld-note">Questions are picked at random from your chapters. The mark
          scheme is a separate file that unlocks when you finish.</p>` :
        `<label class="bld-toggle"><input type="checkbox" id="bld-ms" ${st.includeMs ? "checked" : ""}>
          <span>Mark scheme after each question</span></label>`}
      <button type="button" class="cat-btn bld-go" id="bld-go" ${canBuild ? "" : "disabled"}>
        ${test ? "Build mock test" : "Build booklet"} <span aria-hidden="true">↗</span></button>
      <p class="bld-hint bld-center">Opens in a new tab</p>
      <div class="bld-recent" id="bld-recent"></div>
    </aside>
  </div>
  <div class="bld-mbar" ${st.picks.size ? "" : "hidden"}>
    <span><b>${st.picks.size}/${max}</b> chapters · ${pool ? `${st.maxQ} of ${pool.toLocaleString()} Q` : "…"}</span>
    <a href="#bld-side" class="bld-mbar-opt">Options</a>
    <button type="button" class="cat-btn" data-build ${canBuild ? "" : "disabled"}>Build ↗</button>
  </div>`;
  const fresh = typing && document.getElementById(typing.id);
  if (fresh && fresh !== typing) {
    fresh.replaceWith(typing);
    typing.focus({ preventScroll: true });
    try { typing.setSelectionRange(...caret); } catch { /* not a text field */ }
  } else if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true });
  document.body.classList.toggle("has-dock", st.picks.size > 0);
  root.querySelectorAll("input[data-partial]").forEach((i) => (i.indeterminate = true));
  renderRecent();
}

function estimate(avgMarks) {
  if (!st.pool) return st.picks.size ? "No questions match — widen the years or papers."
                                     : "Pick a chapter to begin.";
  const marks = Math.round(avgMarks * st.maxQ);
  // a mock test allows the cover's 1 minute per mark; practice gets a little slack
  const mins = st.kind === "test" ? Math.max(5, marks) : Math.max(5, Math.round(marks * 1.2 / 5) * 5);
  return `≈ ${marks} marks · ${st.kind === "test" ? "time allowed" : "about"} ${mins} minutes`;
}

function flash(msg) {
  st.msg = msg;
  const el = document.getElementById("bld-msg");
  if (el) { el.textContent = msg; el.classList.toggle("is-on", !!msg); }
}

// ── Picking ─────────────────────────────────────────────────────────────────
function full(ch) {
  if (st.picks.has(ch) || st.picks.size < st.tree.max_chapters) return false;
  flash(`You can combine up to ${st.tree.max_chapters} chapters. Remove one to add another.`);
  return true;
}
function toggleChapter(ch, on) {
  if (on) { if (full(ch)) return render(); st.picks.set(ch, null); }
  else st.picks.delete(ch);
  changed();
}
function toggleSub(ch, sub) {
  if (full(ch)) return;
  const all = st.byName.get(ch).subtopics.map((s) => s.name);
  let sel = st.picks.has(ch) ? st.picks.get(ch) : new Set();
  if (sel === null) sel = new Set(all);
  sel.has(sub) ? sel.delete(sub) : sel.add(sub);
  if (!sel.size) st.picks.delete(ch);
  else st.picks.set(ch, sel.size === all.length ? null : sel);
  changed();
}

// ── Events ──────────────────────────────────────────────────────────────────
root?.addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.ch !== undefined && t.type === "checkbox") {
    toggleChapter(t.dataset.ch, t.checked);
  } else if (t.id === "bld-y0" || t.id === "bld-y1") {
    st[t.id === "bld-y0" ? "y0" : "y1"] = +t.value;
    if (st.y0 > st.y1) [st.y0, st.y1] = [st.y1, st.y0];
    changed();
  } else if (t.id === "bld-ms") {
    st.includeMs = t.checked;
  } else if (t.id === "bld-showsubs") {
    st.showSubs = t.checked;
    store.set("bld.showSubs", st.showSubs);
    render();
  }
});

let filterTimer = null;
root?.addEventListener("input", (e) => {
  if (e.target.id === "bld-n") {
    st.maxQ = +e.target.value;
    root.querySelector(".bld-big").textContent = st.maxQ;
    document.getElementById("bld-est").textContent = estimate(st.pool ? st.poolMarks / st.pool : 0);
    const bar = root.querySelector(".bld-mbar span");
    if (bar && st.pool) bar.innerHTML = `<b>${st.picks.size}/${st.tree.max_chapters}</b> chapters · ${st.maxQ} of ${st.pool.toLocaleString()} Q`;
  } else if (e.target.id === "bld-filter") {
    st.filter = e.target.value;
    clearTimeout(filterTimer);
    filterTimer = setTimeout(render, 120);
  }
});

root?.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-sub]");
  if (chip) { toggleSub(chip.dataset.ch, chip.dataset.sub); return; }
  const sec = e.target.closest("[data-sec]");
  if (sec) {
    const k = sec.dataset.sec;
    st.closed.has(k) ? st.closed.delete(k) : st.closed.add(k);
    render();
    return;
  }
  const kind = e.target.closest("[data-kind]");
  if (kind) { st.kind = kind.dataset.kind; render(); return; }
  const un = e.target.closest("[data-unpick]");
  if (un) { st.picks.delete(un.dataset.unpick); changed(); return; }
  const paper = e.target.closest("[data-paper]");
  if (paper) {
    const p = paper.dataset.paper;
    st.papers.has(p) ? st.papers.delete(p) : st.papers.add(p);
    changed();
    return;
  }
  const jump = e.target.closest(".bld-jump a");
  if (jump) {
    const key = jump.getAttribute("href").slice("#bld-g-".length);
    if (st.closed.delete(key)) render();
  }
  if (e.target.closest("#bld-go, [data-build]")) build();
});

// A disabled chapter's checkbox still toggles natively; explain instead.
root?.addEventListener("click", (e) => {
  const box = e.target.closest('input[aria-disabled="true"]');
  if (box) { e.preventDefault(); full(box.dataset.ch); }
}, true);

let countTimer = null;
function changed() {
  st.msg = "";
  st.counting = st.picks.size > 0;
  if (!st.picks.size) { st.pool = null; st.poolMarks = 0; }
  render();
  clearTimeout(countTimer);
  if (st.picks.size) countTimer = setTimeout(recount, 250);
}

function selection() {
  return {
    syllabus: SYL, year_from: st.y0, year_to: st.y1,
    papers: st.papers.size ? [...st.papers].map(Number) : null,
    picks: [...st.picks].map(([chapter, sel]) => ({ chapter, subtopics: sel ? [...sel] : [] })),
  };
}

let countSeq = 0;
async function recount() {
  if (!st.picks.size) return;
  const seq = ++countSeq;
  try {
    const r = await api("/api/booklets/count", { method: "POST", body: selection() });
    if (seq !== countSeq) return;                 // a newer selection won
    st.pool = r.pool; st.poolMarks = r.marks;
    if (st.maxQ > r.pool) st.maxQ = Math.max(1, r.pool);
  } catch (e) {
    if (seq === countSeq) { st.pool = 0; st.msg = e.message; }
  } finally {
    if (seq === countSeq) { st.counting = false; render(); }
  }
}

// ── Build ───────────────────────────────────────────────────────────────────
async function build() {
  const btn = document.getElementById("bld-go");
  if (!btn || !st.picks.size || !st.pool) return;
  const test = st.kind === "test";
  // Open the tab synchronously inside the click, or popup blockers eat it.
  const win = window.open("", "_blank");
  if (win) {
    const dark = document.documentElement.dataset.theme === "dark";
    win.document.write(`<title>Setting up your paper…</title><body style="font:16px system-ui;
      display:grid;place-items:center;height:100vh;margin:0;color:${dark ? "#e8ebf1" : "#4C2E72"};
      background:${dark ? "#1c2130" : "#FDF9F3"}">Setting up your ${test ? "mock test" : "paper"}…</body>`);
  }
  btn.disabled = true;
  btn.textContent = "Building…";
  try {
    const r = await api("/api/booklets", { method: "POST",
      body: { ...selection(), max_questions: st.maxQ, include_ms: st.includeMs, kind: st.kind } });
    if (win) win.location.href = r.url; else location.href = r.url;
    loadRecent();
  } catch (e) {
    win?.close();
    flash(e instanceof UpgradeRequiredError ? `${e.message} — see plans on the pricing page.`
                                             : e.message || "Couldn't start the build. Try again.");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `${test ? "Build mock test" : "Build booklet"} <span aria-hidden="true">↗</span>`;
  }
}

// ── Recent papers for this subject ──────────────────────────────────────────
let recent = [];
async function loadRecent() {
  try {
    recent = (await api("/api/booklets")).booklets.filter((b) => b.syllabus === SYL).slice(0, 5);
  } catch { recent = []; }
  renderRecent();
}
function renderRecent() {
  const box = document.getElementById("bld-recent");
  if (!box) return;
  box.innerHTML = recent.length ? `<div class="bld-label">Your recent papers</div><ul>${
    recent.map((b) => `<li><a href="${b.url}" target="_blank" rel="noopener">${
      esc(b.title.split(" — ")[0])}</a><span>${b.kind === "test" ? '<i class="bld-tag">Test</i>' : ""}${b.questions} Q</span></li>`).join("")}</ul>` : "";
}
