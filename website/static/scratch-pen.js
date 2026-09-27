/* scratch-pen.js — the pen button on every page that isn't a PDF viewer.
 *
 * Draws on one layer over the whole web page (ink scrolls with the content),
 * with the same tools as the paper viewers. Nothing is saved: a reload clears
 * it. The PDF viewers (booklets, yearly papers, MCQ sessions) run their own
 * annotator that saves per page, so this stays out of their way.
 * Loaded by auth.js and main.js; the flag makes sure it starts once.
 */
const V = "20260928a";

function start() {
  if (window.__pwtScratchPen) return;
  window.__pwtScratchPen = true;
  // PDF viewers have their own, saved annotations.
  if (document.getElementById("vw") || document.getElementById("mq") || document.querySelector(".an-bar")) return;
  if (!document.querySelector('link[href*="annotate.css"]')) {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = `/annotate.css?v=${V}`;
    document.head.appendChild(css);
  }
  import(`/annotate.js?v=${V}`).then(({ createAnnotator }) => {
    if (document.querySelector(".an-bar")) return;     // a viewer mounted one meanwhile
    // scratch ink follows the SITE theme (there is no paper here)
    const ann = createAnnotator({ persist: false, collapsed: true,
                                  dark: () => document.documentElement.dataset.theme === "dark" });
    ann.attachViewport(`scratch:${location.pathname}`);
  }).catch(() => { /* optional feature */ });
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
