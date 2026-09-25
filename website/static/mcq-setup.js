/* mcq-setup.js — the "Start practice" card on /mcq/{board}/{subject}.
 *   Full past paper: year -> session -> paper/variant
 *   Topical: chapters (with how many marked MCQs each has), how many, years
 *   Then: view (paper / one by one), timer (official / none / custom), live check.
 * Also lists sessions to resume and recent results. ?paper=<id> or
 * ?topics=A|B pre-selects (links from the yearly pages and the results screen).
 */
import { api } from "/auth.js?v=20260829a";

const box = document.getElementById("mq-setup");
const code = box?.dataset.syllabus;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SESS = { m: "Feb/March", s: "May/June", w: "Oct/Nov" };
const SESS_ORDER = { m: 0, s: 1, w: 2 };
const OFFICIAL = { "9702-1": 75, "5054-1": 60, "5070-1": 60, "0625-1": 45, "0625-2": 45, "0620-1": 45, "0620-2": 45 };

const U = {
  tab: "paper", papers: [], topics: [], mcqPapers: [], comps: [],
  year: null, session: null, paperId: null,
  picked: new Set(), count: 20, yFrom: null, yTo: null,
  view: "paper", timer: "official", minutes: 30, live: false, busy: false,
};

async function init() {
  if (!box) return;
  box.innerHTML = `<div class="mqs-card mqs-loading"><p>Loading papers…</p></div>`;
  let t, p, s;
  try {
    [t, p, s] = await Promise.all([
      api(`/api/mcq/topics?syllabus=${code}`),
      api(`/api/mcq/papers?syllabus=${code}`),
      api(`/api/mcq/sessions?syllabus=${code}`).catch(() => ({ sessions: [] })),
    ]);
  } catch (e) {
    box.innerHTML = `<div class="mqs-card"><p>Couldn't load the papers: ${esc(e.message)}</p></div>`;
    return;
  }
  U.mcqPapers = t.papers;
  U.topics = t.topics;
  U.comps = t.papers.slice();
  U.papers = p.papers.filter((x) => t.papers.includes(x.paper));
  U.yFrom = t.year_min;
  U.yTo = t.year_max;
  U.sessions = s.sessions || [];
  const qs = new URLSearchParams(location.search);
  const want = +qs.get("paper");
  const pre = qs.get("topics");
  if (want && U.papers.some((x) => x.id === want)) {
    const x = U.papers.find((y) => y.id === want);
    Object.assign(U, { tab: "paper", year: x.year, session: x.session, paperId: x.id });
  } else if (pre) {
    U.tab = "topical";
    pre.split("|").forEach((n) => { if (U.topics.some((x) => x.name === n)) U.picked.add(n); });
  }
  if (!U.year && U.papers.length) {
    U.year = U.papers[0].year;
  }
  try {
    const saved = JSON.parse(localStorage.getItem("pwt-mcq-setup") || "{}");
    if (saved.view) U.view = saved.view;
    if (saved.timer) U.timer = saved.timer;
    if (saved.minutes) U.minutes = saved.minutes;
    if (typeof saved.live === "boolean") U.live = saved.live;
    if (saved.count) U.count = saved.count;
  } catch { /* ignore */ }
  render();
  if (want || pre) box.scrollIntoView({ block: "start" });
}

function papersFor(year, session) {
  return U.papers.filter((x) => x.year === year && (!session || x.session === session));
}

function selected() {
  return U.papers.find((x) => x.id === U.paperId) || null;
}

function officialMins() {
  if (U.tab === "paper") {
    const p = selected();
    return p ? OFFICIAL[`${code}-${p.paper}`] || 45 : null;
  }
  const comp = (U.comps[0] ?? U.mcqPapers[0]);
  return Math.max(1, Math.round((OFFICIAL[`${code}-${comp}`] || 45) / 40 * U.count));
}

function render() {
  const years = [...new Set(U.papers.map((x) => x.year))];
  const sessions = [...new Set(papersFor(U.year).map((x) => x.session))].sort((a, b) => SESS_ORDER[a] - SESS_ORDER[b]);
  if (!sessions.includes(U.session)) U.session = sessions[sessions.length - 1] || null;
  const variants = papersFor(U.year, U.session).sort((a, b) => a.paper - b.paper || String(a.variant).localeCompare(b.variant));
  if (!variants.some((x) => x.id === U.paperId)) U.paperId = variants[0]?.id || null;
  const p = selected();
  const mins = officialMins();
  const active = U.sessions.filter((s) => s.status === "active");
  const done = U.sessions.filter((s) => s.status === "submitted").slice(0, 6);
  const allYears = [...new Set(U.papers.map((x) => x.year))].sort((a, b) => a - b);
  box.innerHTML = `
    ${active.length ? `
      <div class="mqs-resume">
        <h3>Carry on where you left off</h3>
        <div class="mqs-resume-list">${active.slice(0, 4).map((s) => `
          <a class="mqs-rcard" href="${s.url}">
            <b>${esc(s.title)}</b>
            <span class="mqs-rbar"><i style="width:${Math.round(100 * s.answered / Math.max(1, s.count))}%"></i></span>
            <small>${s.answered}/${s.count} answered · ${s.mode === "single" ? "one by one" : "paper view"}</small>
            <em>Resume →</em>
          </a>`).join("")}</div>
      </div>` : ""}
    <div class="mqs-card">
      <div class="mqs-tabs" role="tablist" aria-label="What to practise">
        <button type="button" role="tab" data-tab="paper" aria-selected="${U.tab === "paper"}">
          <b>📜 Full past paper</b><span>A real ${code} paper, start to finish</span></button>
        <button type="button" role="tab" data-tab="topical" aria-selected="${U.tab === "topical"}">
          <b>🎯 Topical practice</b><span>Mixed questions from the chapters you pick</span></button>
      </div>

      <div class="mqs-panel" ${U.tab === "paper" ? "" : "hidden"}>
        <div class="mqs-field"><span class="mqs-label">Year</span>
          <div class="mqs-chips mqs-years">${years.map((y) => `
            <button type="button" data-year="${y}" aria-pressed="${y === U.year}">${y}</button>`).join("")}</div></div>
        <div class="mqs-field"><span class="mqs-label">Session</span>
          <div class="mqs-chips">${sessions.map((s) => `
            <button type="button" data-session="${s}" aria-pressed="${s === U.session}">${SESS[s] || s}</button>`).join("")}</div></div>
        <div class="mqs-field"><span class="mqs-label">Paper</span>
          <div class="mqs-chips">${variants.map((x) => `
            <button type="button" data-paper-id="${x.id}" aria-pressed="${x.id === U.paperId}">
              ${x.paper}${x.variant || ""}${U.mcqPapers.length > 1 ? ` <small>${x.paper === 1 ? "Core" : "Extended"}</small>` : ""}</button>`).join("")}</div></div>
        ${p ? `<p class="mqs-summary"><b>${code}/${p.paper}${p.variant || ""}</b> · ${SESS[p.session]} ${p.year} ·
          ${p.q_count} questions · ${mins} min
          <a href="/yearly/view/${p.id}" target="_blank" rel="noopener">View the paper ↗</a></p>` : ""}
      </div>

      <div class="mqs-panel" ${U.tab === "topical" ? "" : "hidden"}>
        <div class="mqs-field">
          <span class="mqs-label">Chapters <small>${U.picked.size ? `${U.picked.size} picked` : "pick one or more"}</small>
            <button type="button" class="mqs-link" data-all="${U.picked.size === U.topics.length ? "none" : "all"}">
              ${U.picked.size === U.topics.length ? "Clear" : "Select all"}</button></span>
          <div class="mqs-topics">${U.topics.map((t) => `
            <label class="mqs-topic${U.picked.has(t.name) ? " is-on" : ""}">
              <input type="checkbox" data-topic="${esc(t.name)}" ${U.picked.has(t.name) ? "checked" : ""}>
              <span>${esc(t.name)}</span><em>${t.count}</em></label>`).join("")}</div>
        </div>
        <div class="mqs-row">
          <div class="mqs-field"><span class="mqs-label">Questions</span>
            <div class="mqs-seg">${[10, 20, 30, 40].map((n) => `
              <button type="button" data-count="${n}" aria-pressed="${U.count === n}">${n}</button>`).join("")}</div></div>
          <div class="mqs-field"><span class="mqs-label">Years</span>
            <div class="mqs-years2">
              <select data-yfrom aria-label="From year">${allYears.map((y) => `<option ${y === U.yFrom ? "selected" : ""}>${y}</option>`).join("")}</select>
              <span>to</span>
              <select data-yto aria-label="To year">${allYears.map((y) => `<option ${y === U.yTo ? "selected" : ""}>${y}</option>`).join("")}</select>
            </div></div>
          ${U.mcqPapers.length > 1 ? `
          <div class="mqs-field"><span class="mqs-label">Papers</span>
            <div class="mqs-seg">${U.mcqPapers.map((n) => `
              <button type="button" data-comp="${n}" aria-pressed="${U.comps.includes(n)}">P${n} ${n === 1 ? "Core" : "Extended"}</button>`).join("")}</div></div>` : ""}
        </div>
      </div>

      <div class="mqs-opts">
        <div class="mqs-field"><span class="mqs-label">View</span>
          <div class="mqs-seg">
            <button type="button" data-view="paper" aria-pressed="${U.view === "paper"}">📄 Paper</button>
            <button type="button" data-view="single" aria-pressed="${U.view === "single"}">▣ One by one</button></div></div>
        <div class="mqs-field"><span class="mqs-label">Timer</span>
          <div class="mqs-seg">
            <button type="button" data-timer="official" aria-pressed="${U.timer === "official"}">⏱ Official${mins ? ` ${mins}m` : ""}</button>
            <button type="button" data-timer="none" aria-pressed="${U.timer === "none"}">Untimed</button>
            <button type="button" data-timer="custom" aria-pressed="${U.timer === "custom"}">Custom</button></div>
          ${U.timer === "custom" ? `<label class="mqs-mins"><input type="number" min="1" max="240" value="${U.minutes}" data-minutes> minutes</label>` : ""}</div>
        <label class="mqs-switch">
          <input type="checkbox" data-live ${U.live ? "checked" : ""}>
          <span class="mqs-track" aria-hidden="true"><i></i></span>
          <span><b>Live check</b><small>Mark each answer as I go (then it locks)</small></span>
        </label>
      </div>
      <div class="mqs-go">
        <p class="mqs-err" id="mqs-err" role="alert"></p>
        <button type="button" class="cat-btn cat-btn-gold mqs-start" data-start ${U.busy ? "disabled" : ""}>
          ${U.busy ? "Setting up…" : "Start practice →"}</button>
      </div>
    </div>
    ${done.length ? `
      <div class="mqs-history"><h3>Recent results</h3><ul>${done.map((s) => {
        const pct = s.total ? Math.round(100 * s.score / s.total) : 0;
        return `<li><a href="${s.url}?view=results"><span class="mqs-score" data-tone="${pct >= 75 ? "good" : pct >= 50 ? "mid" : "low"}">${pct}%</span>
          <b>${esc(s.title)}</b><small>${s.score}/${s.total}</small></a></li>`;
      }).join("")}</ul></div>` : ""}`;
}

function save() {
  try {
    localStorage.setItem("pwt-mcq-setup", JSON.stringify(
      { view: U.view, timer: U.timer, minutes: U.minutes, live: U.live, count: U.count }));
  } catch { /* ignore */ }
}

async function start() {
  const err = box.querySelector("#mqs-err");
  const body = { syllabus: code, mode: U.view, timer: U.timer, live_check: U.live,
                 minutes: U.timer === "custom" ? U.minutes : null };
  if (U.tab === "paper") {
    if (!U.paperId) { err.textContent = "Pick a paper first."; return; }
    body.paper_id = U.paperId;
  } else {
    if (!U.picked.size) { err.textContent = "Pick at least one chapter."; return; }
    Object.assign(body, { topics: [...U.picked], count: U.count, year_from: U.yFrom, year_to: U.yTo,
                          papers: U.comps.length ? U.comps : null });
  }
  save();
  U.busy = true;
  render();
  try {
    const r = await api("/api/mcq/sessions", { method: "POST", body });
    location.href = r.url;
  } catch (e) {
    U.busy = false;
    render();
    box.querySelector("#mqs-err").textContent = e.message;
  }
}

box?.addEventListener("click", (e) => {
  const t = e.target;
  const set = (fn) => { fn(); render(); };
  const b = (sel) => t.closest(sel);
  if (b("[data-tab]")) return set(() => { U.tab = b("[data-tab]").dataset.tab; });
  if (b("[data-year]")) return set(() => { U.year = +b("[data-year]").dataset.year; U.paperId = null; });
  if (b("[data-session]")) return set(() => { U.session = b("[data-session]").dataset.session; U.paperId = null; });
  if (b("[data-paper-id]")) return set(() => { U.paperId = +b("[data-paper-id]").dataset.paperId; });
  if (b("[data-count]")) return set(() => { U.count = +b("[data-count]").dataset.count; });
  if (b("[data-view]")) return set(() => { U.view = b("[data-view]").dataset.view; });
  if (b("[data-timer]")) return set(() => { U.timer = b("[data-timer]").dataset.timer; });
  if (b("[data-comp]")) return set(() => {
    const n = +b("[data-comp]").dataset.comp;
    U.comps = U.comps.includes(n) ? U.comps.filter((x) => x !== n) : [...U.comps, n];
    if (!U.comps.length) U.comps = [n];
  });
  if (b("[data-all]")) return set(() => {
    if (b("[data-all]").dataset.all === "all") U.topics.forEach((x) => U.picked.add(x.name));
    else U.picked.clear();
  });
  if (b("[data-start]")) start();
});

box?.addEventListener("change", (e) => {
  const t = e.target;
  if (t.matches("[data-topic]")) {
    if (t.checked) U.picked.add(t.dataset.topic); else U.picked.delete(t.dataset.topic);
    render();
  } else if (t.matches("[data-live]")) { U.live = t.checked; }
  else if (t.matches("[data-minutes]")) { U.minutes = Math.max(1, Math.min(240, +t.value || 30)); }
  else if (t.matches("[data-yfrom]")) { U.yFrom = +t.value; if (U.yTo < U.yFrom) U.yTo = U.yFrom; render(); }
  else if (t.matches("[data-yto]")) { U.yTo = +t.value; if (U.yFrom > U.yTo) U.yFrom = U.yTo; render(); }
});

init();
