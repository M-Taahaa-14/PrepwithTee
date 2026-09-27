/* paper-theme.js — the "paper" light/dark switch on every PDF viewer.
 *
 * Separate from the site theme on purpose: some students want a dark site but
 * white paper (it matches the printed exam), others want black paper at night.
 * Dark paper = the PDF canvas inverted with its hues kept (viewer.css), so a
 * red diagram stays red. Stored in localStorage "pwt-paper" ("dark" | "light")
 * and applied as <html data-paper="dark"> by the inline head script of each
 * viewer page, so it never flashes white first.
 *
 * Any element with [data-paper-toggle] becomes the switch (event delegation),
 * and annotate.js watches data-paper to swap its ink palette (pastel on dark
 * paper, high-contrast on white).
 */
const root = document.documentElement;

export const paperIsDark = () => root.dataset.paper === "dark";

const SUN = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z"/></svg>';

/** Toolbar button HTML: shows what the paper will turn INTO. */
export function paperButton(cls = "vw-tbtn vw-paper") {
  return `<button type="button" class="${cls}" data-paper-toggle aria-pressed="${paperIsDark()}"
    title="Paper colour: switch between white and black paper">${paperIsDark() ? SUN : MOON}<span>${paperIsDark() ? "White paper" : "Dark paper"}</span></button>`;
}

export function setPaper(dark) {
  if (dark) root.dataset.paper = "dark"; else delete root.dataset.paper;
  try { localStorage.setItem("pwt-paper", dark ? "dark" : "light"); } catch { /* private mode */ }
  document.querySelectorAll("[data-paper-toggle]").forEach((b) => {
    b.setAttribute("aria-pressed", String(dark));
    b.innerHTML = `${dark ? SUN : MOON}<span>${dark ? "White paper" : "Dark paper"}</span>`;
  });
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-paper-toggle]")) setPaper(!paperIsDark());
});

// Shift+D toggles too (the viewers already use single letters for tools).
document.addEventListener("keydown", (e) => {
  if (e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && e.key === "D"
      && !e.target.matches?.("input, textarea, [contenteditable]")) setPaper(!paperIsDark());
});
