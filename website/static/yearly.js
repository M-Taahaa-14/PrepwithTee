/* yearly.js — /yearly/{board}/{subject}[/{year}] and /mcq/... listing pages.
 *   - filters: paper component + session chips, and a text search; every year
 *     is opened while a filter is on so nothing matching stays folded away
 *   - year rail: highlights the year in view; a click opens that year
 *   - the signed-in student's done ticks / marks, and "n done" per year */
const syllabus = document.querySelector("[data-syllabus]")?.dataset.syllabus
  || location.pathname.match(/-(\w{4})(?:\/|$)/)?.[1];
const years = [...document.querySelectorAll(".yr-year")];
const tiles = () => document.querySelectorAll(".yr-tile, .yr-row");

// ── Jump to a year (rail / #y2019) ──────────────────────────────────────────
function openYear() {
  const el = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if (el?.tagName === "DETAILS") { el.open = true; el.scrollIntoView({ block: "start" }); }
}
window.addEventListener("hashchange", openYear);
document.querySelector(".yr-rail")?.addEventListener("click", (e) => {
  if (e.target.closest("a")) setTimeout(openYear);   // same year twice = no hashchange
});
openYear();

// Highlight the year in view on the rail.
const railLinks = new Map([...document.querySelectorAll(".yr-rail a")].map((a) => [a.hash.slice(1), a]));
if (railLinks.size && "IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      railLinks.forEach((a) => a.classList.remove("is-current"));
      railLinks.get(en.target.id)?.classList.add("is-current");
    }
  }, { rootMargin: "-160px 0px -65% 0px" });
  years.forEach((y) => io.observe(y));
}

// ── Filters ─────────────────────────────────────────────────────────────────
const f = { comp: "", sess: "", words: [] };
const input = document.querySelector("[data-yr-filter]");

function apply() {
  const active = f.comp || f.sess || f.words.length;
  let shown = 0;
  for (const year of years) {
    let any = 0;
    year.querySelectorAll(".yr-mrow").forEach((row) => {
      row.hidden = !!f.comp && row.dataset.comp !== f.comp;
    });
    year.querySelectorAll("[data-sess].yr-cell, [data-sess].yr-mh").forEach((c) => {
      c.hidden = !!f.sess && c.dataset.sess !== f.sess;
    });
    year.querySelectorAll(".yr-tile").forEach((t) => {
      const hay = (t.dataset.find + " " + t.textContent).toLowerCase();
      const ok = f.words.every((w) => hay.includes(w));
      t.hidden = !ok;
      const row = t.closest(".yr-mrow"), cell = t.closest(".yr-cell");
      if (ok && !row.hidden && !cell.hidden) any++;
    });
    // hide rows left with no visible tile while searching
    if (f.words.length) {
      year.querySelectorAll(".yr-mrow").forEach((row) => {
        if (!row.hidden && !row.querySelector(".yr-cell:not([hidden]) .yr-tile:not([hidden])")) row.hidden = true;
      });
    }
    const matrix = year.querySelector(".yr-matrix");
    if (matrix) matrix.style.setProperty("--sessions", f.sess ? 1 :
      year.querySelectorAll(".yr-mh[data-sess]").length);
    year.hidden = !any;
    if (active && any) year.open = true;
    const rail = railLinks.get(year.id);
    if (rail) {
      rail.classList.toggle("is-dim", !any);
      rail.querySelector("span").textContent = any;
    }
    shown += any;
  }
  const none = document.querySelector(".yr-none-found");
  if (none) none.hidden = shown > 0;
}

document.querySelector(".yr-bar")?.addEventListener("click", (e) => {
  const chip = e.target.closest(".yr-chip");
  if (!chip) return;
  const key = "comp" in chip.dataset ? "comp" : "sess";
  f[key] = chip.dataset[key];
  chip.parentElement.querySelectorAll(".yr-chip").forEach((c) =>
    c.setAttribute("aria-pressed", String(c === chip)));
  apply();
});
input?.addEventListener("input", () => {
  f.words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
  if (document.querySelector(".yr-tile")) apply();
  else {                                   // MCQ landing page: a flat list of rows
    document.querySelectorAll(".yr-row").forEach((row) => {
      const hay = `${row.textContent} ${row.dataset.key}`.toLowerCase();
      row.hidden = !f.words.every((w) => hay.includes(w));
    });
  }
});

// ── Done ticks for a signed-in student (silently nothing when signed out) ───
const state = (() => {
  try { return JSON.parse(document.getElementById("cat-state").textContent); } catch { return {}; }
})();
if (syllabus && state.signedIn && tiles().length) {
  fetch(`/api/papers-progress?syllabus=${encodeURIComponent(syllabus)}`, { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : { papers: [] }))
    .then(({ papers }) => {
      const done = new Map();
      for (const p of papers || []) {
        if (p.status !== "confident") continue;
        done.set(`${p.year}|${p.session}|${p.paper}|${p.variant ?? ""}`, p);
      }
      tiles().forEach((t) => {
        const p = done.get(t.dataset.key);
        if (!p) return;
        t.classList.add("is-done");
        const tick = t.querySelector(".yr-done");
        tick.removeAttribute("aria-hidden");
        tick.setAttribute("aria-label", "Done");
        if (p.score != null && p.max_score) tick.dataset.score = `${p.score}/${p.max_score}`;
      });
      for (const year of years) {
        const n = year.querySelectorAll(".yr-tile.is-done").length;
        const badge = year.querySelector(".yr-year-done");
        if (badge && n) { badge.hidden = false; badge.textContent = `${n} done`; }
      }
    })
    .catch(() => {});
}
