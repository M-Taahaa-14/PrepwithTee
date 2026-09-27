/* site-search.js - the header search palette (Ctrl K, "/", or the Search button).
 *
 * Loaded on demand by main.js. Fetches /api/search/index once (pages, subject
 * sections, every syllabus chapter, every note - see website/search.py) and
 * filters it in the browser, so results appear as you type with no network
 * wait. Arrow keys move, Enter opens, Esc closes.
 */
const KIND = {
  page: ["Page", "lav"], subject: ["Topical", "lav"], yearly: ["By year", "blue"], mcq: ["MCQ", "orange"],
  test: ["Mock test", "green"], notes: ["Notes", "teal"], resources: ["Resources", "yellow"],
  chapter: ["Chapter", "pink"], note: ["Note", "teal"],
};
const QUICK = [
  ["Topical papers", "/papers/topical"], ["Papers by year", "/yearly"], ["MCQ practice", "/mcq"],
  ["Mock tests", "/papers/mock-tests"], ["Revision notes", "/notes"], ["Resources", "/resources"],
  ["My papers", "/my-papers"], ["Every page", "/explore"],
];

let rows = null;
let loading = null;
let dlg = null;

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function load() {
  if (rows) return Promise.resolve(rows);
  if (!loading) {
    loading = fetch("/api/search/index", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        rows = d.map((r) => ({ ...r, _t: r.t.toLowerCase(), _all: `${r.t} ${r.s} ${r.q || ""}`.toLowerCase() }));
        return rows;
      })
      .catch(() => { loading = null; return []; });
  }
  return loading;
}

/* Every word must appear somewhere; title hits, word starts and exact codes rank higher. */
function rank(q) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length || !rows) return [];
  const out = [];
  for (const r of rows) {
    let score = 0;
    let ok = true;
    for (const w of words) {
      const inAll = r._all.indexOf(w);
      if (inAll < 0) { ok = false; break; }
      const inTitle = r._t.indexOf(w);
      if (inTitle === 0) score += 12;
      else if (inTitle > 0) score += r._t[inTitle - 1] === " " ? 8 : 4;
      else score += 1;
    }
    if (!ok) continue;
    if (r._t === q.toLowerCase()) score += 20;
    if (r.k === "page" || r.k === "subject") score += 2;
    out.push([score, r]);
  }
  out.sort((a, b) => b[0] - a[0] || a[1].t.length - b[1].t.length);
  return out.slice(0, 40).map((x) => x[1]);
}

function highlight(text, q) {
  let html = esc(text);
  for (const w of q.toLowerCase().split(/\s+/).filter((x) => x.length > 1)) {
    const re = new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig");
    html = html.replace(re, "<mark>$1</mark>");
  }
  return html;
}

function build() {
  dlg = document.createElement("div");
  dlg.className = "ss-back";
  dlg.hidden = true;
  dlg.innerHTML = `
    <div class="ss" role="dialog" aria-modal="true" aria-label="Search PrepWithTee">
      <label class="ss-field">
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>
        <input type="search" placeholder="Search subjects, chapters, notes, tools…" autocomplete="off"
          spellcheck="false" role="combobox" aria-expanded="true" aria-controls="ss-list" aria-autocomplete="list">
        <button type="button" class="ss-close" aria-label="Close search">Esc</button>
      </label>
      <div class="ss-body"><ul class="ss-list" id="ss-list" role="listbox"></ul></div>
      <p class="ss-foot"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>Enter</kbd> open</span>
        <span><kbd>Esc</kbd> close</span></p>
    </div>`;
  document.body.appendChild(dlg);
  const input = dlg.querySelector("input");
  const list = dlg.querySelector(".ss-list");
  let sel = 0;

  function render() {
    const q = input.value.trim();
    let items;
    if (!q) {
      list.innerHTML = `<li class="ss-head">Jump to</li>` + QUICK.map(([t, u], i) =>
        `<li role="option" id="ss-o${i}"><a href="${u}" class="ss-item"><span class="ss-kind ss-t-lav">Go</span>
         <span class="ss-text"><b>${esc(t)}</b></span></a></li>`).join("");
    } else if (!rows) {
      list.innerHTML = `<li class="ss-empty">Loading…</li>`;
      return;
    } else {
      items = rank(q);
      list.innerHTML = items.length ? items.map((r, i) => {
        const [label, tone] = KIND[r.k] || ["Page", "lav"];
        return `<li role="option" id="ss-o${i}"><a href="${esc(r.u)}" class="ss-item">
          <span class="ss-kind ss-t-${tone}">${label}</span>
          <span class="ss-text"><b>${highlight(r.t, q)}</b><small>${esc(r.s)}</small></span></a></li>`;
      }).join("") : `<li class="ss-empty">Nothing matches <b>${esc(q)}</b>. Try a subject, a code like 5054, or a chapter name.</li>`;
    }
    sel = 0;
    mark();
  }
  function opts() { return [...list.querySelectorAll('[role="option"]')]; }
  function mark() {
    const o = opts();
    o.forEach((li, i) => li.setAttribute("aria-selected", String(i === sel)));
    if (o[sel]) {
      input.setAttribute("aria-activedescendant", o[sel].id);
      o[sel].scrollIntoView({ block: "nearest" });
    }
  }
  input.addEventListener("input", () => { load().then(render); render(); });
  input.addEventListener("keydown", (e) => {
    const o = opts();
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(o.length - 1, sel + 1); mark(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); mark(); }
    else if (e.key === "Enter") {
      const a = o[sel]?.querySelector("a");
      if (a) { e.preventDefault(); location.href = a.href; }
    }
  });
  dlg.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } });
  dlg.addEventListener("mousedown", (e) => { if (e.target === dlg) close(); });
  dlg.querySelector(".ss-close").addEventListener("click", close);
  dlg._render = render;
}

let lastFocus = null;
export function open(initial = "") {
  if (!dlg) build();
  lastFocus = document.activeElement;
  dlg.hidden = false;
  document.documentElement.classList.add("ss-open");
  const input = dlg.querySelector("input");
  input.value = initial;
  dlg._render();
  input.focus();
  load().then(() => dlg._render());
}

export function close() {
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  document.documentElement.classList.remove("ss-open");
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
