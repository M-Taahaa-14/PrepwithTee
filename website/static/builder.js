/* builder.js — the topical paper builder on /papers/{board}/{subject}.
 *
 * Pick up to 4 chapters (whole, or any of their subtopics), filter by years
 * and paper, choose how many questions, Build -> the booklet opens in a new
 * tab at /papers/view/{id}, where a loader shows the real build stages.
 * The exact pool size comes from POST /api/booklets/count (debounced); chapter
 * counts under the filters are computed here from the tree's per-year data.
 */
import { api, UpgradeRequiredError } from "/auth.js?v=20260829a";

const root = document.getElementById("builder");
const SYL = root?.dataset.syllabus;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const st = {
  tree: null,
  picks: new Map(),          // chapter name -> null (whole chapter) | Set(subtopics)
  open: new Set(),           // expanded chapters
  y0: null, y1: null,
  papers: new Set(),         // empty = all components
  maxQ: 20, includeMs: true,
  pool: null, poolMarks: 0, counting: false, filter: "", msg: "",
};

if (root && SYL) init();

async function init() {
  root.innerHTML = `<div class="bld-loading" role="status">Loading chapters…</div>`;
  try {
    st.tree = await api(`/api/topical/${SYL}/tree`);
  } catch (e) {
    root.innerHTML = `<p class="bld-error" role="alert">Couldn't load the chapters: ${esc(e.message)}</p>`;
    return;
  }
  st.y0 = st.tree.year_min; st.y1 = st.tree.year_max;
  const want = new URLSearchParams(location.search).get("pick");
  if (want && st.tree.chapters.some((c) => c.name === want)) {
    st.picks.set(want, null);
    st.open.add(want);
  }
  render();
  if (want) requestAnimationFrame(() => root.scrollIntoView({ block: "start" }));
  recount();
  loadRecent();
}

// ── Counts under the current filters ────────────────────────────────────────
function inYears(byYear) {
  let n = 0;
  for (const [y, c] of Object.entries(byYear || {})) if (+y >= st.y0 && +y <= st.y1) n += c;
  return n;
}
function chapterCount(ch) {
  if (!st.papers.size) return inYears(ch.counts_by_year);
  let n = 0;
  for (const p of st.papers) n += inYears((ch.paper_year || {})[p]);
  return n;
}

// ── Render ──────────────────────────────────────────────────────────────────
function render() {
  const t = st.tree, max = t.max_chapters;
  const full = st.picks.size >= max;
  const q = st.filter.trim().toLowerCase();
  const chapters = t.chapters.map((ch, i) => {
    const picked = st.picks.has(ch.name);
    const subsSel = st.picks.get(ch.name);
    const partial = picked && subsSel instanceof Set;
    const hidden = q && !ch.display.toLowerCase().includes(q) &&
                   !ch.subtopics.some((s) => s.name.toLowerCase().includes(q));
    const disabled = !picked && full;
    const n = chapterCount(ch);
    const isOpen = st.open.has(ch.name);
    const subs = ch.subtopics.map((s, j) => {
      const on = picked && (!partial || subsSel.has(s.name));
      return `<li><label class="bld-sub${disabled ? " is-disabled" : ""}">
          <input type="checkbox" data-sub="${esc(s.name)}" data-ch="${esc(ch.name)}"
                 id="sub-${i}-${j}" ${on ? "checked" : ""} ${disabled ? "disabled" : ""}>
          <span>${esc(s.name)}</span><em>${inYears(s.counts_by_year)}</em></label></li>`;
    }).join("");
    return `<li class="bld-ch${picked ? " is-picked" : ""}${disabled ? " is-disabled" : ""}"
                ${hidden ? "hidden" : ""} ${n === 0 ? 'data-empty="1"' : ""}>
      <div class="bld-ch-row">
        <input type="checkbox" id="ch-${i}" data-ch="${esc(ch.name)}"
               ${picked ? "checked" : ""} ${disabled ? "disabled" : ""}
               ${partial ? 'data-partial="1"' : ""} aria-describedby="chn-${i}">
        <label for="ch-${i}" class="bld-ch-name">${esc(ch.display)}</label>
        <span class="bld-count" id="chn-${i}">${n.toLocaleString()} Q</span>
        ${ch.subtopics.length ? `<button type="button" class="bld-expand" data-toggle="${esc(ch.name)}"
            aria-expanded="${isOpen}" aria-controls="subs-${i}"
            aria-label="${isOpen ? "Hide" : "Show"} subtopics of ${esc(ch.display)}">
            ${partial ? `<span class="bld-partial">${subsSel.size}/${ch.subtopics.length}</span>` : ""}
            <svg viewBox="0 0 10 6" width="10" height="6" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>` : ""}
      </div>
      ${ch.subtopics.length ? `<ul class="bld-subs" id="subs-${i}" ${isOpen ? "" : "hidden"}>${subs}</ul>` : ""}
    </li>`;
  }).join("");

  const slots = Array.from({ length: max }, (_, k) => {
    const name = [...st.picks.keys()][k];
    if (!name) return `<li class="bld-slot is-empty">Chapter ${k + 1}</li>`;
    const ch = t.chapters.find((c) => c.name === name);
    const sel = st.picks.get(name);
    return `<li class="bld-slot"><span>${esc(ch.display)}${sel instanceof Set ?
      ` <small>· ${sel.size} subtopic${sel.size === 1 ? "" : "s"}</small>` : ""}</span>
      <button type="button" data-unpick="${esc(name)}" aria-label="Remove ${esc(ch.display)}">×</button></li>`;
  }).join("");

  const years = [];
  for (let y = t.year_max; y >= t.year_min; y--) years.push(y);
  const yOpts = (sel) => years.map((y) => `<option ${y === sel ? "selected" : ""}>${y}</option>`).join("");
  const comps = (t.components || []).map((c) => `
    <button type="button" class="bld-chip${st.papers.has(String(c.paper)) ? " is-on" : ""}"
            data-paper="${c.paper}" aria-pressed="${st.papers.has(String(c.paper))}">${esc(c.label)}</button>`).join("");

  const pool = st.pool;
  const maxAllowed = Math.max(1, Math.min(t.max_questions, pool ?? t.max_questions));
  if (st.maxQ > maxAllowed) st.maxQ = maxAllowed;
  const avgMarks = pool ? st.poolMarks / pool : 0;
  const canBuild = st.picks.size > 0 && pool > 0;

  const scrollY = root.querySelector(".bld-list")?.scrollTop || 0;
  const focusId = document.activeElement?.id;   // keep keyboard users in place
  root.innerHTML = `
  <div class="bld-grid">
    <div class="bld-main">
      <div class="bld-head">
        <div>
          <h2>Build a topical paper</h2>
          <p>Tick up to ${max} chapters — whole, or just the subtopics you need.
             Questions from every pick are mixed together.</p>
        </div>
        <label class="bld-search"><span class="sr-only">Filter chapters</span>
          <input type="search" id="bld-filter" placeholder="Filter chapters or subtopics"
                 value="${esc(st.filter)}" autocomplete="off"></label>
      </div>
      <ol class="bld-list">${chapters}</ol>
    </div>
    <aside class="bld-side" aria-label="Paper options">
      <div class="bld-block">
        <div class="bld-label">Your chapters <b>${st.picks.size}/${max}</b></div>
        <ol class="bld-slots">${slots}</ol>
        <p class="bld-msg${st.msg ? " is-on" : ""}" role="status" id="bld-msg">${esc(st.msg)}</p>
      </div>
      <div class="bld-block bld-row">
        <label class="bld-label" for="bld-y0">Years</label>
        <div class="bld-years">
          <select id="bld-y0" aria-label="From year">${yOpts(st.y0)}</select>
          <span aria-hidden="true">to</span>
          <select id="bld-y1" aria-label="To year">${yOpts(st.y1)}</select>
        </div>
      </div>
      ${comps ? `<div class="bld-block"><div class="bld-label">Paper</div>
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
        <p class="bld-hint">${pool ? `≈ ${Math.round(avgMarks * st.maxQ)} marks · about
          ${Math.max(5, Math.round(avgMarks * st.maxQ * 1.2 / 5) * 5)} minutes` :
          st.picks.size ? "No questions match — widen the years or paper." : "Pick a chapter to begin."}</p>
      </div>
      <label class="bld-block bld-toggle">
        <input type="checkbox" id="bld-ms" ${st.includeMs ? "checked" : ""}>
        <span>Mark scheme after each question</span>
      </label>
      <button type="button" class="cat-btn bld-go" id="bld-go" ${canBuild ? "" : "disabled"}>
        Build paper <span aria-hidden="true">↗</span></button>
      <p class="bld-hint bld-center">Opens in a new tab</p>
      <div class="bld-recent" id="bld-recent"></div>
    </aside>
  </div>
  <div class="bld-mbar" ${st.picks.size ? "" : "hidden"}>
    <span><b>${st.picks.size}/${max}</b> chapters · ${pool ? `${st.maxQ} of ${pool.toLocaleString()} Q` : "…"}</span>
    <a href="#bld-n" class="bld-mbar-opt">Options</a>
    <button type="button" class="cat-btn" data-build ${canBuild ? "" : "disabled"}>Build ↗</button>
  </div>`;
  root.querySelector(".bld-list").scrollTop = scrollY;
  if (focusId) document.getElementById(focusId)?.focus({ preventScroll: true });
  document.body.classList.toggle("has-dock", st.picks.size > 0);
  root.querySelectorAll("input[data-partial]").forEach((i) => (i.indeterminate = true));
  renderRecent();
}

function flash(msg) {
  st.msg = msg;
  const el = document.getElementById("bld-msg");
  if (el) { el.textContent = msg; el.classList.add("is-on"); }
}

// ── Events ──────────────────────────────────────────────────────────────────
root?.addEventListener("change", (e) => {
  const t = e.target;
  const ch = t.dataset.ch;
  if (t.dataset.sub !== undefined) {
    const all = st.tree.chapters.find((c) => c.name === ch).subtopics.map((s) => s.name);
    let sel = st.picks.has(ch) ? st.picks.get(ch) : new Set();
    if (sel === null) sel = new Set(all);
    t.checked ? sel.add(t.dataset.sub) : sel.delete(t.dataset.sub);
    if (!sel.size) st.picks.delete(ch);
    else st.picks.set(ch, sel.size === all.length ? null : sel);
    st.open.add(ch);
    changed();
  } else if (ch !== undefined) {
    if (t.checked) st.picks.set(ch, null); else st.picks.delete(ch);
    changed();
  } else if (t.id === "bld-y0" || t.id === "bld-y1") {
    st[t.id === "bld-y0" ? "y0" : "y1"] = +t.value;
    if (st.y0 > st.y1) [st.y0, st.y1] = [st.y1, st.y0];
    changed();
  } else if (t.id === "bld-ms") {
    st.includeMs = t.checked;
  }
});

root?.addEventListener("input", (e) => {
  if (e.target.id === "bld-n") {
    st.maxQ = +e.target.value;
    const out = root.querySelector(".bld-big");
    if (out) out.textContent = st.maxQ;
    const hint = out?.closest(".bld-block").querySelector(".bld-hint");
    if (hint && st.pool) {
      const avg = st.poolMarks / st.pool;
      hint.textContent = `≈ ${Math.round(avg * st.maxQ)} marks · about ${
        Math.max(5, Math.round(avg * st.maxQ * 1.2 / 5) * 5)} minutes`;
    }
  } else if (e.target.id === "bld-filter") {
    st.filter = e.target.value;
    const q = st.filter.trim().toLowerCase();
    root.querySelectorAll(".bld-ch").forEach((li, i) => {
      const ch = st.tree.chapters[i];
      li.hidden = !!q && !ch.display.toLowerCase().includes(q) &&
                  !ch.subtopics.some((s) => s.name.toLowerCase().includes(q));
    });
  }
});

root?.addEventListener("click", (e) => {
  const tog = e.target.closest("[data-toggle]");
  if (tog) {
    const ch = tog.dataset.toggle;
    st.open.has(ch) ? st.open.delete(ch) : st.open.add(ch);
    const list = document.getElementById(tog.getAttribute("aria-controls"));
    list.hidden = !st.open.has(ch);
    tog.setAttribute("aria-expanded", st.open.has(ch));
    return;
  }
  const un = e.target.closest("[data-unpick]");
  if (un) { st.picks.delete(un.dataset.unpick); changed(); return; }
  const chip = e.target.closest("[data-paper]");
  if (chip) {
    const p = chip.dataset.paper;
    st.papers.has(p) ? st.papers.delete(p) : st.papers.add(p);
    changed();
    return;
  }
  // A click on a disabled chapter explains why instead of doing nothing.
  const dis = e.target.closest(".bld-ch.is-disabled");
  if (dis) flash(`You can combine up to ${st.tree.max_chapters} chapters. Remove one to add another.`);
  if (e.target.closest("#bld-go, [data-build]")) build();
});

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
    if (seq === countSeq) { st.pool = 0; flash(e.message); }
  } finally {
    if (seq === countSeq) { st.counting = false; render(); }
  }
}

// ── Build ───────────────────────────────────────────────────────────────────
async function build() {
  const btn = document.getElementById("bld-go");
  if (!btn || !st.picks.size || !st.pool) return;
  // Open the tab synchronously inside the click, or popup blockers eat it.
  const win = window.open("", "_blank");
  if (win) {
    win.document.write(`<title>Setting up your paper…</title><body style="font:16px system-ui;
      display:grid;place-items:center;height:100vh;margin:0;color:#4C2E72;background:#FDF9F3">
      Setting up your paper…</body>`);
  }
  btn.disabled = true;
  btn.textContent = "Building…";
  try {
    const r = await api("/api/booklets", { method: "POST",
      body: { ...selection(), max_questions: st.maxQ, include_ms: st.includeMs } });
    if (win) win.location.href = r.url; else location.href = r.url;
    loadRecent();
  } catch (e) {
    win?.close();
    if (e instanceof UpgradeRequiredError) {
      flash(`${e.message} — see plans on the pricing page.`);
    } else {
      flash(e.message || "Couldn't start the build. Try again.");
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Build paper <span aria-hidden="true">↗</span>';
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
      esc(b.title.split(" — ")[0])}</a><span>${b.questions} Q</span></li>`).join("")}</ul>` : "";
}
