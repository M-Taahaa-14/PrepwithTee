/* notes-page.js — a revision note page (/notes/.../{note}, rendered by notes.py).
 *   maths    KaTeX auto-render (\( \) inline, \[ \] display)
 *   progress a thin reading-progress bar at the top
 *   ticks    notes you have read get a ✓ in the sidebar (this device)
 *   drawer   the sidebar slides in on phones */
const article = document.querySelector(".nt-article");
const READ_KEY = "pwt-notes-read";

function mathWhenReady(tries = 40) {
  if (window.renderMathInElement) {
    window.renderMathInElement(document.querySelector(".nt-body"), {
      delimiters: [{ left: "\\[", right: "\\]", display: true }, { left: "\\(", right: "\\)", display: false },
                   { left: "$$", right: "$$", display: true }],
      throwOnError: false,
    });
  } else if (tries) setTimeout(() => mathWhenReady(tries - 1), 100);
}
mathWhenReady();

function read() {
  try { return JSON.parse(localStorage.getItem(READ_KEY) || "{}"); } catch { return {}; }
}
function paintTicks() {
  const done = read();
  document.querySelectorAll(".nt-side [data-note]").forEach((a) =>
    a.classList.toggle("is-read", !!done[a.dataset.note]));
}

const bar = document.querySelector(".nt-progress i");
let marked = false;
function onScroll() {
  const r = article.getBoundingClientRect();
  const total = article.offsetHeight - window.innerHeight;
  const pct = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 1;
  if (bar) bar.style.width = `${pct * 100}%`;
  if (!marked && pct > 0.8) {                    // read to the end -> tick it
    marked = true;
    try {
      const d = read();
      d[article.dataset.note] = Date.now();
      localStorage.setItem(READ_KEY, JSON.stringify(d));
    } catch { /* private mode */ }
    paintTicks();
  }
}
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();
paintTicks();

const side = document.getElementById("nt-side");
const btn = document.querySelector("[data-nt-side]");
btn?.addEventListener("click", () => {
  const open = !side.classList.contains("is-open");
  side.classList.toggle("is-open", open);
  btn.setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (e) => {
  if (side?.classList.contains("is-open") && !side.contains(e.target) && !e.target.closest("[data-nt-side]")) {
    side.classList.remove("is-open");
    btn?.setAttribute("aria-expanded", "false");
  }
});
