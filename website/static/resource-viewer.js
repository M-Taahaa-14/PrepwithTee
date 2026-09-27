/* resource-viewer.js — /resources/view?f=...: one Resources PDF (or image) in
 * the site viewer: back to its folder, page count, zoom, white/dark paper,
 * download, and the annotation bar (saved per page when signed in, under
 * res:<hash>; scratch ink for guests).
 */
import { PdfPane, debounce } from "/pdf-pane.js?v=20260928a";
import { createAnnotator } from "/annotate.js?v=20260928a";
import { paperButton } from "/paper-theme.js?v=20260928a";

const S = JSON.parse(document.getElementById("vw-state").textContent);
const root = document.getElementById("vw");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const header = document.querySelector(".site-header");
const sizeTop = () => document.documentElement.style.setProperty(
  "--vw-top", `${header ? header.getBoundingClientRect().bottom : 0}px`);
sizeTop();
window.addEventListener("resize", sizeTop);

root.dataset.state = "ready";
root.innerHTML = `
  <header class="vw-tools">
    <a class="vw-back" href="${esc(S.backUrl)}" title="Back to ${esc(S.backLabel)}" aria-label="Back to ${esc(S.backLabel)}">←</a>
    <h1 class="vw-title" title="${esc(S.title)}">${esc(S.title)} <small class="rv-from">· ${esc(S.backLabel)}</small></h1>
    ${S.kind === "pdf" ? `<span class="vw-pageno" aria-live="polite">Page <b id="vw-pn">1</b> / <span id="vw-pt">…</span></span>
    <div class="vw-zoom" role="group" aria-label="Zoom">
      <button type="button" class="vw-tbtn" data-act="out" aria-label="Zoom out">−</button>
      <button type="button" class="vw-tbtn" data-act="fit" id="vw-z">100%</button>
      <button type="button" class="vw-tbtn" data-act="in" aria-label="Zoom in">+</button>
    </div>` : ""}
    ${paperButton()}
    <a class="vw-btn vw-dl" href="${esc(S.url)}" download="${esc(S.filename)}">⤓ <span>Download</span></a>
  </header>
  <div class="vw-body"><div class="vw-stage" id="vw-stage" tabindex="0" aria-label="Document"></div></div>`;

const stage = document.getElementById("vw-stage");
const ann = createAnnotator({ mount: document.body, persist: !!S.signedIn,
                             unsaved: "Not saved - sign in to keep your ink" });

if (S.kind === "img") {
  const pg = document.createElement("div");
  pg.className = "vw-pg rv-img-pg";
  pg.innerHTML = `<img class="vw-paper-img" src="${esc(S.url)}" alt="${esc(S.title)}">`;
  stage.appendChild(pg);
  const img = pg.querySelector("img");
  const fit = () => { pg.style.width = `${Math.min(stage.clientWidth - 36, img.naturalWidth || 900)}px`; };
  img.onload = () => { fit(); ann.attach(pg, S.doc, 1); };
  window.addEventListener("resize", debounce(fit, 150));
} else {
  const pane = new PdfPane(stage, {
    ranged: true, chips: false,
    onPage: (n) => { document.getElementById("vw-pn").textContent = n; },
    onZoom: (label) => { document.getElementById("vw-z").textContent = label; },
    onPageEl: (el, n) => ann.attach(el, S.doc, n),
  });
  pane.load(S.url).then(() => {
    document.getElementById("vw-pt").textContent = pane.numPages;
  }).catch((e) => {
    stage.innerHTML = `<div class="vw-load-card rv-err"><p class="vw-eyebrow">Could not open this file</p>
      <p>${esc(e.message)}</p><a class="vw-btn" href="${esc(S.url)}" download>Download it instead</a></div>`;
  });
  root.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "in") pane.zoomIn();
    else if (act === "out") pane.zoomOut();
    else if (act === "fit") pane.zoomFit();
  });
  window.addEventListener("resize", debounce(() => pane.refit(), 200));
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key === "=" || e.key === "+") { e.preventDefault(); pane.zoomIn(); }
    if (e.key === "-") { e.preventDefault(); pane.zoomOut(); }
  });
}
