/* yearly.js — /yearly/{board}/{subject}[/{year}] and /mcq/... listing pages:
 * instant filter over the sittings, and the student's done ticks / marks. */
const listRoot = document.querySelector(".yr-years") || document.querySelector(".yr-list");
const syllabus = document.querySelector("[data-syllabus]")?.dataset.syllabus
  || location.pathname.match(/-(\w{4})(?:\/|$)/)?.[1];

// Year chips jump to a year: open it (only the newest two start open).
function openYear() {
  const el = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if (el?.tagName === "DETAILS") { el.open = true; el.scrollIntoView({ block: "start" }); }
}
window.addEventListener("hashchange", openYear);
// same chip twice = no hashchange, so also after every chip click
document.querySelector(".yr-jump")?.addEventListener("click", (e) => {
  if (e.target.closest("a")) setTimeout(openYear);
});
openYear();

// Filter: every word must match the row's text ("12 m/j 2019" narrows).
const input = document.querySelector("[data-yr-filter]");
if (input) {
  input.addEventListener("input", () => {
    const words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    document.querySelectorAll(".yr-year").forEach((year) => {
      let any = false;
      year.querySelectorAll(".yr-row").forEach((row) => {
        const hay = `${row.textContent} ${row.dataset.key}`.toLowerCase();
        const ok = words.every((w) => hay.includes(w));
        row.hidden = !ok;
        any ||= ok;
      });
      year.hidden = !any;
      if (words.length && any) year.open = true;
    });
  });
}

// Done ticks for a signed-in student (silently nothing when signed out).
const state = (() => {
  try { return JSON.parse(document.getElementById("cat-state").textContent); } catch { return {}; }
})();
if (listRoot && syllabus && state.signedIn) {
  fetch(`/api/papers-progress?syllabus=${encodeURIComponent(syllabus)}`, { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : { papers: [] }))
    .then(({ papers }) => {
      const done = new Map();
      for (const p of papers || []) {
        if (p.status !== "confident") continue;
        done.set(`${p.year}|${p.session}|${p.paper}|${p.variant ?? ""}`, p);
      }
      document.querySelectorAll(".yr-row").forEach((row) => {
        const p = done.get(row.dataset.key);
        if (!p) return;
        row.classList.add("is-done");
        const tick = row.querySelector(".yr-done");
        tick.removeAttribute("aria-hidden");
        tick.setAttribute("aria-label", "Done");
        if (p.score != null && p.max_score) tick.dataset.score = `${p.score}/${p.max_score}`;
      });
    })
    .catch(() => {});
}
