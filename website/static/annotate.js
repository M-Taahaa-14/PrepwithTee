/* annotate.js — the floating annotation bar + a drawing layer on every page.
 *
 *   const ann = createAnnotator({ mount: document.body });
 *   ann.attach(pageEl, "paper:123", 4);   // any positioned element = one "page"
 *
 * Tools: pointer (scroll/click), select (move · edit text · delete · recolour),
 * pen, highlighter, eraser, line, arrow, rectangle, ellipse, text; 12 inks
 * plus a custom colour picker, 5 sizes. Inks are palette TOKENS ("@blue") drawn
 * with a high-contrast shade on white paper and a pastel twin on dark paper
 * (paper-theme.js / the site theme for scratch ink), so ink written in one mode
 * stays readable in the other. Custom colours are stored as plain hex. While the eraser is on, the bar shows its own options in place of
 * colour/thickness: Partial (cuts through strokes and shapes) | Whole object,
 * and three eraser sizes;
 * undo/redo; clear page. Strokes are stored as fractions of the page (so zoom
 * never matters) and saved per page to /api/annotations, debounced.
 *
 * Pens (Wacom, Surface, Apple Pencil): the layer is touch-action:none whenever a
 * drawing tool is on, so the browser never turns a pen stroke into a scroll
 * (it used to, after a short stroke, with pan-y allowed). Once a stylus has been
 * seen, a finger or palm does not draw: it scrolls the page, done here by hand.
 * Drawing is frame-throttled over a cached image of the finished strokes, so a
 * long stroke on a busy page stays smooth.
 * Scratch mode (createAnnotator({ persist: false }) + attachViewport()): one
 * layer over the whole web page, ink moving with the content as you scroll,
 * NEVER saved - main.js puts it on every page that isn't a PDF viewer.
 * Instruments (not saved): a 15 cm ruler and a 180° protractor, drawn to the
 * paper's real scale (A4, or A4 landscape for mark schemes; CSS cm on web pages).
 * Drag to move, drag the round handle to rotate (1° steps, Shift = 15°). A pen or
 * highlighter stroke that starts on a ruler edge snaps to a straight line along it.
 * Keys: V pointer · S select · P pen · H highlighter · E eraser · T text ·
 *       Delete remove selection · Ctrl+Z / Ctrl+Y.
 */
// [token, light paper, dark paper, name] - website/annot_pdf.py has the same table.
const PALETTE = [
  ["blue", "#1d4ed8", "#93c5fd", "Blue"], ["ink", "#111827", "#f3f4f6", "Black / white"],
  ["red", "#dc2626", "#fca5a5", "Red"], ["green", "#15803d", "#86efac", "Green"],
  ["orange", "#ea580c", "#fdba74", "Orange"], ["purple", "#7e22ce", "#d8b4fe", "Purple"],
  ["pink", "#db2777", "#f9a8d4", "Pink"], ["teal", "#0f766e", "#5eead4", "Teal"],
  ["yellow", "#ca8a04", "#fde68a", "Yellow"], ["sky", "#0284c7", "#7dd3fc", "Sky"],
  ["brown", "#92400e", "#e7c9a9", "Brown"], ["grey", "#4b5563", "#cbd5e1", "Grey"],
];
const PAL = Object.fromEntries(PALETTE.map(([k, l, d, n]) => [k, { l, d, n }]));
// the six colours before the palette became tokens (strokes saved with plain hex)
const LEGACY = { "#1d4ed8": "@blue", "#111827": "@ink", "#dc2626": "@red", "#16a34a": "@green",
                 "#f59e0b": "@orange", "#9333ea": "@purple" };
const SIZES = [0.0015, 0.0022, 0.0042, 0.0085, 0.013];   // fraction of page width
const ERASER_R = [0.008, 0.015, 0.028];            // eraser radius per size, fraction of width
const ICON = {
  pointer: '<path d="M5 3l14 8-6 2-2 6z"/>',
  select: '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M9 9l7 3-3 1-1 3z"/>',
  pen: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
  marker: '<path d="M9 15l-4 5h6l2-3"/><path d="M8 13l7-9 5 4-7 9z"/>',
  eraser: '<path d="M8 20h12"/><path d="M5 15l8-9 6 6-6 7H9z"/>',
  line: '<path d="M5 19L19 5"/>',
  arrow: '<path d="M5 19L19 5"/><path d="M10 5h9v9"/>',
  rect: '<rect x="4" y="6" width="16" height="12" rx="1.5"/>',
  ellipse: '<ellipse cx="12" cy="12" rx="8.5" ry="6"/>',
  text: '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 000 12h3"/>',
  clear: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
  trash: '<path d="M4 7h16"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
  collapse: '<path d="M6 9l6 6 6-6"/>',
  ruler: '<rect x="2.5" y="8" width="19" height="8" rx="1.2" transform="rotate(-30 12 12)"/><path d="M8.6 7.4l1 1.7M11.2 5.9l1.5 2.6M13.8 4.4l1 1.7" transform="translate(-1.2 4.6)"/>',
  protractor: '<path d="M3 17a9 9 0 0118 0z"/><path d="M12 17l4.5-6.5"/><path d="M7 17a5 5 0 0110 0"/>',
  grip: '<circle cx="9" cy="7" r="1.2"/><circle cx="15" cy="7" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="17" r="1.2"/><circle cx="15" cy="17" r="1.2"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const TOOLS = [["pointer", "Pointer — scroll and click (V)"], ["select", "Select — move, edit, delete (S)"],
  ["pen", "Pen (P)"], ["marker", "Highlighter (H)"], ["eraser", "Eraser (E)"]];
const SHAPES = [["line", "Line"], ["arrow", "Arrow"], ["rect", "Rectangle"],
  ["ellipse", "Ellipse"], ["text", "Text (T)"]];
const DRAWS = new Set(["select", "pen", "marker", "eraser", "line", "arrow", "rect", "ellipse", "text"]);
const clamp = (v) => Math.min(1, Math.max(0, v));

// Text boxes (feedback 2026-09-30: "make it like real PDF editors"). A text
// object: {t:"text", x, y (top-left of the text), s (font size, fraction of the
// page width), c, txt, bw? (wrap width), f? font, b? i? u?, al? "c"|"r",
// bg? fill ("paper" = covers what is under it, or an ink token = a tint),
// bd? border}. website/annot_pdf.py draws the same thing into downloads.
const FONTS = {
  sans: ["Sans", '"Hanken Grotesk", system-ui, sans-serif'],
  serif: ["Serif", 'Georgia, "Times New Roman", serif'],
  hand: ["Handwriting", '"Segoe Print", "Bradley Hand", "Chalkboard SE", "Comic Sans MS", cursive'],
  mono: ["Mono", 'Consolas, "SFMono-Regular", Menlo, "Courier New", monospace'],
};
const FILLS = [["", "No fill"], ["paper", "Cover (paper colour)"], ["@yellow", "Yellow"],
  ["@green", "Green"], ["@sky", "Blue"], ["@pink", "Pink"], ["@grey", "Grey"]];
const PT_PER_W = 595;                 // A4 width in points: font size <-> "pt"
const LH = 1.25;                      // line height, as in the editing box
const TEXT_DEFAULTS = { f: "sans", pt: 12, b: false, i: false, u: false, al: "l", bg: "", bd: false };
const TICON = {
  grip: ICON.grip,
  alL: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
  alC: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
  alR: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
  fill: '<path d="M5 12l6-7 7 7-6 6z"/><path d="M19 15s2 2.3 2 3.5a2 2 0 01-4 0c0-1.2 2-3.5 2-3.5z"/>',
  border: '<rect x="4" y="4" width="16" height="16" rx="2"/>',
  dup: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
  trash: ICON.trash,
};

async function req(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`annotations ${r.status}`);
  return r.json();
}

export function createAnnotator({ mount = document.body, position = "bottom", persist: saveInk = true,
                                  collapsed = false, unsaved = "Scratch ink — not saved",
                                  dark = () => document.documentElement.dataset.paper === "dark" } = {}) {
  /** A stored colour -> the colour to paint now (token by paper theme, legacy hex, custom hex). */
  const ink = (c) => {
    if (!c) return ink("@blue");
    if (c[0] === "@") { const p = PAL[c.slice(1)] || PAL.blue; return dark() ? p.d : p.l; }
    const old = LEGACY[c.toLowerCase()];
    return old ? ink(old) : c;
  };
  const A = {
    tool: "pointer", color: "@blue", size: 2, collapsed: false, eraseMode: "partial", eraseSize: 1,
    docs: new Map(),      // doc -> Promise<{page: strokes[]}>
    pages: new Map(),     // `${doc}|${page}` -> { el, canvas, strokes, doc, page }
    undo: [], redo: [], saveTimers: new Map(), penSeen: false, listeners: new Set(),
    sel: null,            // { key, i } - the selected object
  };
  try {
    const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
    if (typeof s.color === "string" && (PAL[s.color.slice(1)] || /^#[0-9a-f]{6}$/i.test(s.color))) {
      A.color = LEGACY[s.color.toLowerCase()] || s.color;
    }
    if (s.size >= 0 && s.size < SIZES.length) A.size = s.v === 2 ? s.size : Math.min(SIZES.length - 1, s.size + 1);
    if (s.pos === "top" || s.pos === "bottom") position = s.pos;
    if (s.erase === "stroke" || s.erase === "partial") A.eraseMode = s.erase;
    if (s.esize >= 0 && s.esize < ERASER_R.length) A.eraseSize = s.esize;
  } catch { /* storage may be blocked */ }

  // ── toolbar ────────────────────────────────────────────────────────────────
  const bar = document.createElement("div");
  bar.className = "an-bar";
  bar.dataset.pos = position;
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Annotation tools");
  bar.innerHTML = `
    <button type="button" class="an-grip" data-an="grip" title="Drag to move · double-click to flip top/bottom"
            aria-label="Move toolbar">${svg("grip")}</button>
    <div class="an-group">${TOOLS.map(([k, t]) => `
      <button type="button" data-tool="${k}" title="${t}" aria-label="${t}" aria-pressed="false">${svg(k)}</button>`).join("")}
    </div>
    <span class="an-sep" aria-hidden="true"></span>
    <div class="an-group an-shapes">${SHAPES.map(([k, t]) => `
      <button type="button" data-tool="${k}" title="${t}" aria-label="${t}" aria-pressed="false">${svg(k)}</button>`).join("")}
    </div>
    <span class="an-sep" aria-hidden="true"></span>
    <div class="an-group an-insts">
      <button type="button" data-inst="ruler" title="Ruler — drag, rotate; draw along its edge" aria-label="Ruler" aria-pressed="false">${svg("ruler")}</button>
      <button type="button" data-inst="protractor" title="Protractor — drag, rotate to measure angles" aria-label="Protractor" aria-pressed="false">${svg("protractor")}</button>
    </div>
    <span class="an-sep" aria-hidden="true"></span>
    <div class="an-eraseopts" role="group" aria-label="Eraser options" hidden>
      <div class="an-seg" role="radiogroup" aria-label="Eraser type">
        <button type="button" role="radio" data-erase="partial" aria-checked="true"
                title="Rub out just the part you touch">Partial</button>
        <button type="button" role="radio" data-erase="stroke" aria-checked="false"
                title="Remove a whole stroke, shape or text box">Whole object</button>
      </div>
      <div class="an-esizes" role="radiogroup" aria-label="Eraser size">${ERASER_R.map((_, i) => `
        <button type="button" role="radio" data-esize="${i}" aria-checked="false"
                title="${["Small", "Medium", "Large"][i]} eraser" aria-label="${["Small", "Medium", "Large"][i]} eraser"><i style="--d:${6 + i * 5}px"></i></button>`).join("")}
      </div>
    </div>
    <div class="an-pop-wrap an-inkopt">
      <button type="button" class="an-swatch" data-an="colors" title="Colour" aria-label="Colour"
              aria-haspopup="true" aria-expanded="false"><i></i></button>
      <div class="an-pop an-colors" data-pop="colors" hidden>
        <p class="an-pop-head" data-ink-head>Inks</p>
        <div class="an-swatches">${PALETTE.map(([k, , , n]) => `
          <button type="button" data-color="@${k}" title="${n}" aria-label="${n}"></button>`).join("")}</div>
        <label class="an-custom" title="Any colour"><input type="color" data-custom value="#1d4ed8">
          <span>Custom colour</span></label>
      </div>
    </div>
    <div class="an-pop-wrap an-inkopt">
      <button type="button" class="an-size" data-an="sizes" title="Thickness" aria-label="Thickness"
              aria-haspopup="true" aria-expanded="false"><i></i></button>
      <div class="an-pop" data-pop="sizes" hidden>${SIZES.map((_, i) => `
        <button type="button" data-size="${i}" aria-label="Size ${i + 1}"><i style="--d:${3 + i * 3.5}px"></i></button>`).join("")}</div>
    </div>
    <button type="button" data-an="delete" class="an-del" title="Delete selected (Delete)" aria-label="Delete selected" hidden>${svg("trash")}</button>
    <span class="an-sep" aria-hidden="true"></span>
    <button type="button" data-an="undo" title="Undo (Ctrl+Z)" aria-label="Undo">${svg("undo")}</button>
    <button type="button" data-an="redo" title="Redo (Ctrl+Y)" aria-label="Redo">${svg("redo")}</button>
    <button type="button" data-an="clear" title="Clear this page" aria-label="Clear this page">${svg("clear")}</button>
    <button type="button" class="an-collapse" data-an="collapse" title="Hide tools" aria-label="Hide tools"
            aria-expanded="true">${svg("collapse")}</button>
    <span class="an-saved" aria-live="polite"></span>`;
  mount.appendChild(bar);

  const fab = document.createElement("button");
  fab.type = "button";
  fab.className = "an-fab";
  fab.hidden = true;
  fab.title = "Annotate — pen, highlighter, shapes";
  fab.setAttribute("aria-label", "Show annotation tools");
  fab.innerHTML = svg("pen");
  mount.appendChild(fab);
  fab.onclick = () => setCollapsed(false);

  function persist() {
    try {
      const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
      localStorage.setItem("pwt-annot", JSON.stringify({ ...s, color: A.color, size: A.size, v: 2,
                                                         pos: bar.dataset.pos, erase: A.eraseMode,
                                                         esize: A.eraseSize }));
    } catch { /* ignore */ }
  }

  function paintBar() {
    bar.querySelectorAll("[data-tool]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.tool === A.tool)));
    bar.querySelector(".an-swatch i").style.background = ink(selected()?.c || A.color);
    bar.querySelector(".an-size i").style.setProperty("--d", `${3 + A.size * 3.5}px`);
    bar.querySelector(".an-size i").style.background = ink(A.color);
    bar.dataset.paper = dark() ? "dark" : "light";
    bar.querySelector("[data-ink-head]").textContent = dark() ? "Pastel inks for dark paper" : "High-contrast inks";
    bar.querySelectorAll("[data-color]").forEach((b) => {
      b.style.setProperty("--c", ink(b.dataset.color));
      b.classList.toggle("is-on", b.dataset.color === A.color);
    });
    const custom = bar.querySelector("[data-custom]");
    custom.closest(".an-custom").classList.toggle("is-on", A.color[0] === "#");
    if (A.color[0] === "#") custom.value = A.color;
    bar.querySelectorAll("[data-size]").forEach((b) => b.classList.toggle("is-on", +b.dataset.size === A.size));
    bar.querySelectorAll("[data-erase]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.erase === A.eraseMode)));
    bar.querySelectorAll("[data-esize]").forEach((b) => b.setAttribute("aria-checked", String(+b.dataset.esize === A.eraseSize)));
    const erasing = A.tool === "eraser";                     // eraser options replace colour/thickness
    bar.querySelector(".an-eraseopts").hidden = !erasing;
    bar.querySelectorAll(".an-inkopt").forEach((el) => { el.hidden = erasing; });
    bar.querySelector('[data-an="undo"]').disabled = !A.undo.length;
    bar.querySelector('[data-an="redo"]').disabled = !A.redo.length;
    bar.querySelector('[data-an="delete"]').hidden = !A.sel;
    placeTextBar();
    const drawing = DRAWS.has(A.tool);
    document.documentElement.classList.toggle("an-drawing", drawing);
    document.documentElement.dataset.anTool = A.tool;
    for (const p of A.pages.values()) paintLayer(p);
    A.listeners.forEach((fn) => fn(A.tool));
  }

  function setTool(t) {
    closeEditor(true);
    if (t !== "select" && !(t === "text" && selected()?.t === "text")) A.sel = null;
    A.tool = t;
    closePops();
    paintBar();
  }

  function setCollapsed(v) {
    A.collapsed = v;
    const shown = A.visible !== false;
    bar.hidden = !shown || v;
    fab.hidden = !shown || !v;
    if (v) setTool("pointer");
  }

  function closePops(except) {
    bar.querySelectorAll("[data-pop]").forEach((p) => {
      if (p.dataset.pop !== except) p.hidden = true;
    });
    bar.querySelectorAll("[aria-haspopup]").forEach((b) =>
      b.setAttribute("aria-expanded", String(b.dataset.an === except && !bar.querySelector(`[data-pop="${except}"]`).hidden)));
  }

  bar.addEventListener("input", (e) => {
    if (!e.target.matches("[data-custom]")) return;
    pickColor(e.target.value.toLowerCase());
  });

  function pickColor(c) {
    A.color = c; persist();
    if (TX.ed) { setTextStyle({ c }); return paintBar(); }
    const s = selected();
    if (s) { mutate(A.sel.key, (list) => { list[A.sel.i] = { ...s, c: A.color }; }); return paintBar(); }
    if (!DRAWS.has(A.tool) || A.tool === "eraser" || A.tool === "select") A.tool = "pen";
    return paintBar();
  }

  // Paper (or, for scratch ink, site) theme changed: repaint with the other shades.
  new MutationObserver(() => paintBar()).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-paper", "data-theme"] });

  bar.addEventListener("click", (e) => {
    const er = e.target.closest("[data-erase]");
    if (er) { A.eraseMode = er.dataset.erase; persist(); return paintBar(); }
    const es = e.target.closest("[data-esize]");
    if (es) { A.eraseSize = +es.dataset.esize; persist(); return paintBar(); }
    const inst = e.target.closest("[data-inst]");
    if (inst) return toggleInstrument(inst.dataset.inst);
    const t = e.target.closest("[data-tool]");
    if (t) {
      const k = t.dataset.tool;
      return setTool(A.tool === k && k !== "pointer" ? "pointer" : k);
    }
    const c = e.target.closest("[data-color]");
    if (c) { closePops(); return pickColor(c.dataset.color); }
    if (e.target.closest(".an-custom")) return;          // the colour input handles itself
    const s = e.target.closest("[data-size]");
    if (s) {
      A.size = +s.dataset.size; persist(); closePops();
      const o = selected();
      if (o) mutate(A.sel.key, (list) => { list[A.sel.i] = resized(o, A.size); });
      return paintBar();
    }
    const act = e.target.closest("[data-an]")?.dataset.an;
    if (act === "colors" || act === "sizes") {
      const pop = bar.querySelector(`[data-pop="${act}"]`);
      const open = pop.hidden;
      closePops();
      pop.hidden = !open;
      e.target.closest("[data-an]").setAttribute("aria-expanded", String(open));
    } else if (act === "undo") doUndo();
    else if (act === "redo") doRedo();
    else if (act === "clear") clearPage();
    else if (act === "delete") deleteSelected();
    else if (act === "collapse") {
      setCollapsed(true);
      try {
        const st = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
        localStorage.setItem("pwt-annot", JSON.stringify({ ...st, open: false }));
      } catch { /* ignore */ }
    }
  });
  bar.addEventListener("dblclick", (e) => {
    if (!e.target.closest('[data-an="grip"]')) return;
    bar.dataset.pos = bar.dataset.pos === "top" ? "bottom" : "top";
    bar.style.transform = "";
    persist();
  });
  document.addEventListener("pointerdown", (e) => { if (!bar.contains(e.target)) closePops(); });

  // Drag the bar by its grip; it snaps to the top or bottom centre.
  bar.querySelector('[data-an="grip"]').addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const y0 = e.clientY;
    const move = (ev) => { bar.style.transform = `translate(-50%, ${ev.clientY - y0}px)`; };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      bar.style.transform = "";
      bar.dataset.pos = ev.clientY < window.innerHeight / 2 ? "top" : "bottom";
      persist();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches?.("input, textarea, [contenteditable]")) return;
    if (e.target.closest?.(".pwt-dock, .an-tb")) return;          // the calculator etc. have their own keys
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      if (A.undo.length) { e.preventDefault(); doUndo(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) {
      if (A.redo.length) { e.preventDefault(); doRedo(); }
      return;
    }
    if (A.sel && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); deleteSelected(); return; }
    if (objectKeys(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey || A.collapsed) return;
    const k = { v: "pointer", s: "select", p: "pen", h: "marker", e: "eraser", t: "text" }[e.key.toLowerCase()];
    if (k && A.hotkeys !== false) { setTool(k); }
    if (e.key === "Escape") { if (A.sel) { A.sel = null; paintBar(); } else if (A.tool !== "pointer") setTool("pointer"); }
  });

  // ── pages ──────────────────────────────────────────────────────────────────
  function load(doc) {
    if (!saveInk) return Promise.resolve({});
    if (!A.docs.has(doc)) {
      A.docs.set(doc, req("GET", `/api/annotations?doc=${encodeURIComponent(doc)}`)
        .then((d) => d.pages || {}).catch(() => ({})));
    }
    return A.docs.get(doc);
  }

  // A page's ink layer only holds pixels while the page is near the screen AND
  // has ink (or is being drawn on). Two full-page canvases on every page of a
  // 150-page booklet were gigabytes of memory - the "Chrome lags" feedback.
  const byEl = new WeakMap();
  const near = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const p = byEl.get(e.target);
      if (!p || p.near === e.isIntersecting) continue;
      p.near = e.isIntersecting;
      paintLayer(p);
    }
  }, { rootMargin: "800px 0px" });

  async function attach(el, doc, page) {
    const key = `${doc}|${page}`;
    const prev = A.pages.get(key);
    if (TX.ed?.p.key === key) closeEditor(true);       // zoom / re-layout: finish the edit first
    if (prev && prev.el !== el) near.unobserve(prev.el);
    const canvas = document.createElement("canvas");
    canvas.className = "an-layer";
    el.appendChild(canvas);
    const p = { el, canvas, doc, page, key, strokes: prev ? prev.strokes : null, near: false };
    A.pages.set(key, p);
    byEl.set(el, p);
    near.observe(el);
    bind(p);
    if (!p.strokes) {
      const pages = await load(doc);
      if (A.pages.get(key) !== p) return;          // re-attached meanwhile
      p.strokes = (pages[String(page)] || []).slice();
    }
    paintLayer(p);
    return p;
  }

  function detachWithin(root) {
    for (const [k, p] of A.pages) {
      if (root.contains(p.el) || !p.el.isConnected) { near.unobserve(p.el); A.pages.delete(k); }
    }
  }

  function size(p) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // Whole-page layer: the canvas is the viewport; coordinates are fractions of
    // the page WIDTH on both axes (y can pass 1), so ink stays put when the
    // page grows, and scrolling just shifts the view.
    const cw = p.el.clientWidth, ch = p.el.clientHeight;
    const w = cw, h = p.view ? cw : ch;
    const on = p.view || (p.near && (p.strokes?.length || p.live || p.drag || p.eraserAt));
    const tw = on ? Math.round(cw * dpr) : 0, th = on ? Math.round(ch * dpr) : 0;
    let changed = false;
    if (p.canvas.width !== tw || p.canvas.height !== th) {
      p.canvas.width = tw;
      p.canvas.height = th;
      changed = true;
    }
    return { w, h, dpr, changed, ox: p.view ? window.scrollX : 0, oy: p.view ? window.scrollY : 0 };
  }

  /** Full repaint: rebuild the cached image of the finished strokes, then show it. */
  function paintLayer(p) {
    if (!p.strokes) return;
    const { w, h, dpr, ox, oy } = size(p);
    p.canvas.classList.toggle("is-active", DRAWS.has(A.tool));
    p.canvas.dataset.tool = A.tool === "eraser" ? `eraser-${A.eraseMode}` : A.tool;
    if (!p.canvas.width) {                         // nothing to show: hold no pixels
      if (p.base) { p.base.width = 0; p.base.height = 0; p.base = null; }
      return;
    }
    if (!p.base) p.base = document.createElement("canvas");
    p.base.width = p.canvas.width;
    p.base.height = p.canvas.height;
    const b = p.base.getContext("2d");
    b.setTransform(1, 0, 0, 1, 0, 0);
    b.clearRect(0, 0, p.base.width, p.base.height);
    b.setTransform(dpr, 0, 0, dpr, -ox * dpr, -oy * dpr);
    p.strokes.forEach((s, i) => { if (i !== p.hideIndex) draw(b, s, w, h); });
    blit(p);
  }

  /** Cheap per-frame paint: cached strokes + the stroke being drawn + selection. */
  function blit(p) {
    const { w, h, dpr, changed, ox, oy } = size(p);
    if (!p.canvas.width) return changed ? paintLayer(p) : undefined;
    if (changed || !p.base) return paintLayer(p);
    const ctx = p.canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);
    ctx.drawImage(p.base, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, -ox * dpr, -oy * dpr);
    if (p.live) draw(ctx, p.live, w, h);
    if (A.sel?.key === p.key && p.strokes[A.sel.i] && p.hideIndex !== A.sel.i) drawSelection(ctx, p.strokes[A.sel.i], w, h);
    if (p.eraserAt && A.tool === "eraser") {
      ctx.beginPath();
      ctx.arc(p.eraserAt[0] * w, p.eraserAt[1] * h, ERASER_R[A.eraseSize] * w, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(120,120,140,.8)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  function schedule(p, full = false) {
    p.needFull ||= full;
    if (p.raf) return;
    p.raf = requestAnimationFrame(() => {
      p.raf = 0;
      if (p.needFull) { p.needFull = false; paintLayer(p); } else blit(p);
    });
  }

  function textFont(s, w) {
    const fs = Math.max(4, s.s * w);
    const weight = s.b ? 700 : s.f ? 400 : 600;         // boxes from before fonts were semi-bold
    return { fs, font: `${s.i ? "italic " : ""}${weight} ${fs}px ${(FONTS[s.f] || FONTS.sans)[1]}` };
  }

  /** How a text box lays out at page width w: its lines (own line breaks, then
   *  word-wrapped at bw), each line's width, the box and its padding (a box
   *  with a fill or border gets breathing room around the text). */
  function textLayout(s, w) {
    const { fs, font } = textFont(s, w);
    measure.font = font;
    const max = s.bw ? s.bw * w : Infinity;
    const lines = [];
    for (const para of String(s.txt || "").split("\n")) {
      if (max === Infinity) { lines.push(para); continue; }
      let line = "";
      for (const word of para.split(/(?<=\s)/)) {
        if (line && measure.measureText((line + word).trimEnd()).width > max) { lines.push(line.trimEnd()); line = word; }
        else line += word;
      }
      lines.push(line);
    }
    const widths = lines.map((l) => measure.measureText(l).width);
    const m = measure.measureText("Hg");
    const asc = m.fontBoundingBoxAscent ?? fs * 0.8, desc = m.fontBoundingBoxDescent ?? fs * 0.2;
    const lh = fs * LH;
    return { lines, widths, fs, font, lh, boxW: s.bw ? s.bw * w : Math.max(0, ...widths),
             boxH: lines.length * lh, pad: s.bg || s.bd ? Math.round(fs * 0.35) : 0,
             // baseline inside a line box, exactly where CSS puts it in the editing box
             base: (lh - (asc + desc)) / 2 + asc };
  }

  const fillColour = (bg) => (bg === "paper" ? (dark() ? "#0e0e0e" : "#ffffff") : ink(bg));

  function drawText(ctx, s, w, h) {
    const L = textLayout(s, w);
    const x = s.x * w, y = s.y * h;
    if (s.bg) {
      ctx.globalAlpha = s.bg === "paper" ? 1 : dark() ? 0.32 : 0.26;
      ctx.fillStyle = fillColour(s.bg);
      ctx.fillRect(x - L.pad, y - L.pad, L.boxW + 2 * L.pad, L.boxH + 2 * L.pad);
      ctx.globalAlpha = 1;
      ctx.fillStyle = ink(s.c);                       // the text keeps its own colour
    }
    if (s.bd) {
      ctx.lineWidth = Math.max(1, L.fs * 0.07);
      ctx.strokeRect(x - L.pad, y - L.pad, L.boxW + 2 * L.pad, L.boxH + 2 * L.pad);
    }
    ctx.font = L.font;
    ctx.textBaseline = "alphabetic";
    L.lines.forEach((line, i) => {
      const off = s.al === "c" ? (L.boxW - L.widths[i]) / 2 : s.al === "r" ? L.boxW - L.widths[i] : 0;
      const by = y + i * L.lh + L.base;
      ctx.fillText(line, x + off, by);
      if (s.u && L.widths[i]) ctx.fillRect(x + off, by + L.fs * 0.12, L.widths[i], Math.max(1, L.fs * 0.07));
    });
  }

  /** The object at picker size i: text gets that font size, strokes that width. */
  function resized(o, i) {
    if (o.t === "text") return o;                       // text has its own size control
    return o.w != null ? { ...o, w: SIZES[i] } : o;
  }

  function draw(ctx, s, w, h) {
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = ink(s.c);
    ctx.fillStyle = ink(s.c);
    const lw = Math.max(1, s.w * w);
    if (s.t === "marker") {
      // multiply darkens white paper; on dark paper "screen" lightens it instead
      ctx.globalAlpha = dark() ? 0.4 : 0.32;
      ctx.globalCompositeOperation = dark() ? "screen" : "multiply";
      ctx.lineCap = "butt";
    }
    if (s.t === "pen" || s.t === "marker") {
      const pts = s.pts || [];
      if (pts.length === 1) {
        ctx.beginPath();
        ctx.arc(pts[0][0] * w, pts[0][1] * h, lw / 2, 0, Math.PI * 2);
        ctx.fill();
      }
      if (s.t === "marker") {
        // one path, so overlapping segments don't darken the highlight
        ctx.lineWidth = lw * 3.2;
        ctx.beginPath();
        pts.forEach((q, i) => (i ? ctx.lineTo(q[0] * w, q[1] * h) : ctx.moveTo(q[0] * w, q[1] * h)));
        ctx.stroke();
      } else {
        // Quadratic curves through the midpoints: smooth, and each segment's
        // width follows the pen pressure recorded at that point.
        for (let i = 1; i < pts.length; i++) {
          const a = pts[i - 1], b = pts[i];
          const prev = pts[i - 2] || a;
          const m0 = [(prev[0] + a[0]) / 2 * w, (prev[1] + a[1]) / 2 * h];
          const m1 = [(a[0] + b[0]) / 2 * w, (a[1] + b[1]) / 2 * h];
          ctx.beginPath();
          ctx.lineWidth = lw * (0.55 + 0.9 * (a[2] ?? 0.5));
          ctx.moveTo(m0[0], m0[1]);
          ctx.quadraticCurveTo(a[0] * w, a[1] * h, m1[0], m1[1]);
          ctx.stroke();
        }
      }
    } else if (s.t === "line" || s.t === "arrow") {
      const [x0, y0] = [s.a[0] * w, s.a[1] * h], [x1, y1] = [s.b[0] * w, s.b[1] * h];
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
      if (s.t === "arrow") {
        const ang = Math.atan2(y1 - y0, x1 - x0), L = Math.max(10, lw * 4);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x1 - L * Math.cos(ang - 0.45), y1 - L * Math.sin(ang - 0.45));
        ctx.lineTo(x1 - L * Math.cos(ang + 0.45), y1 - L * Math.sin(ang + 0.45));
        ctx.closePath();
        ctx.fill();
      }
    } else if (s.t === "rect" || s.t === "ellipse") {
      const x = Math.min(s.a[0], s.b[0]) * w, y = Math.min(s.a[1], s.b[1]) * h;
      const rw = Math.abs(s.b[0] - s.a[0]) * w, rh = Math.abs(s.b[1] - s.a[1]) * h;
      ctx.lineWidth = lw;
      ctx.beginPath();
      if (s.t === "rect") ctx.rect(x, y, rw, rh);
      else ctx.ellipse(x + rw / 2, y + rh / 2, rw / 2, rh / 2, 0, 0, Math.PI * 2);
      ctx.stroke();
    } else if (s.t === "text") {
      drawText(ctx, s, w, h);
    }
    ctx.restore();
  }

  // ── geometry ───────────────────────────────────────────────────────────────
  const measure = document.createElement("canvas").getContext("2d");

  /** Bounding box of an object, in page fractions. */
  function bbox(s, w, h) {
    if (s.t === "text") {
      const L = textLayout(s, w);
      const bw = Math.max(L.boxW, L.fs * 0.6);             // an empty line still has a caret's width
      return [s.x - L.pad / w, s.y - L.pad / h, s.x + (bw + L.pad) / w, s.y + (Math.max(L.boxH, L.lh) + L.pad) / h];
    }
    const xs = s.pts ? s.pts.map((q) => q[0]) : [s.a[0], s.b[0]];
    const ys = s.pts ? s.pts.map((q) => q[1]) : [s.a[1], s.b[1]];
    const pad = (s.t === "marker" ? s.w * 1.6 : s.w / 2);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad * (w / h), Math.max(...xs) + pad, Math.max(...ys) + pad * (w / h)];
  }

  const HANDLE = 10;                                   // px, the square resize handles
  const CURSOR = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize",
                   n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", a: "move", b: "move" };
  /** The selected object's handles in page px: text = 4 corners (scale) + the
   *  two sides (wrap width); rectangles / ellipses = 8; lines / arrows = ends. */
  function handles(s, w, h) {
    if (s.t === "line" || s.t === "arrow") return [["a", s.a[0] * w, s.a[1] * h], ["b", s.b[0] * w, s.b[1] * h]];
    if (s.t !== "text" && s.t !== "rect" && s.t !== "ellipse") return [];
    const [x0, y0, x1, y1] = bbox(s, w, h);
    const X0 = x0 * w - 5, Y0 = y0 * h - 5, X1 = x1 * w + 5, Y1 = y1 * h + 5, XM = (X0 + X1) / 2, YM = (Y0 + Y1) / 2;
    const out = [["nw", X0, Y0], ["ne", X1, Y0], ["sw", X0, Y1], ["se", X1, Y1], ["w", X0, YM], ["e", X1, YM]];
    return s.t === "text" ? out : [...out, ["n", XM, Y0], ["s", XM, Y1]];
  }

  /** Which handle of s is under q (page fractions), or null. */
  function onHandle(s, q, w, h) {
    const r = HANDLE / 2 + 7;                           // bigger than drawn: fingers and pens
    for (const [id, x, y] of handles(s, w, h)) {
      if (Math.abs(q[0] * w - x) < r && Math.abs(q[1] * h - y) < r) return id;
    }
    return null;
  }

  function drawSelection(ctx, s, w, h) {
    ctx.save();
    ctx.strokeStyle = "#7c5cf0";
    if (s.t !== "line" && s.t !== "arrow") {
      const [x0, y0, x1, y1] = bbox(s, w, h);
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.5;
      ctx.strokeRect(x0 * w - 5, y0 * h - 5, (x1 - x0) * w + 10, (y1 - y0) * h + 10);
      ctx.setLineDash([]);
    }
    ctx.fillStyle = "#fff";
    ctx.lineWidth = 1.5;
    for (const [id, x, y] of handles(s, w, h)) {
      ctx.beginPath();
      if (id === "a" || id === "b") ctx.arc(x, y, HANDLE / 2 + 1, 0, Math.PI * 2);
      else ctx.rect(x - HANDLE / 2, y - HANDLE / 2, HANDLE, HANDLE);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  function segDist(q, a, b, aspect = 1) {
    const dx = b[0] - a[0], dy = (b[1] - a[1]) * aspect;
    const qy = (q[1] - a[1]) * aspect, qx = q[0] - a[0];
    const t = Math.max(0, Math.min(1, (qx * dx + qy * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(qx - t * dx, qy - t * dy);
  }

  /** Does point q (page fractions) touch object s, within radius r (fraction of width)? */
  function hit(s, q, r, w, h) {
    const k = h / w;                                  // compare distances in width units
    if (s.pts) return s.pts.some((a, i) => segDist(q, a, s.pts[i + 1] || a, k) < r + s.w * (s.t === "marker" ? 1.6 : 0.5));
    if (s.t === "text") {
      const [x0, y0, x1, y1] = bbox(s, w, h);
      return q[0] > x0 - r && q[0] < x1 + r && q[1] > y0 - r / k && q[1] < y1 + r / k;
    }
    if (s.t === "rect" || s.t === "ellipse") return outline(s, 48).some((a, i, L) => i && segDist(q, L[i - 1], a, k) < r + s.w);
    return segDist(q, s.a, s.b, k) < r + s.w;
  }

  /** For "select": anywhere inside a shape or text counts, not just its outline. */
  function grabs(s, q, w, h) {
    if (s.t === "text" || s.t === "rect" || s.t === "ellipse") {
      const [x0, y0, x1, y1] = bbox(s, w, h);
      const m = 0.008;
      return q[0] > x0 - m && q[0] < x1 + m && q[1] > y0 - m && q[1] < y1 + m;
    }
    return hit(s, q, 0.01, w, h);
  }

  /** A shape as points along its outline (for the partial eraser). */
  function outline(s, n = 64) {
    if (s.t === "line" || s.t === "arrow") {
      const L = Math.max(2, Math.ceil(Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) / 0.004));
      return Array.from({ length: L + 1 }, (_, i) =>
        [s.a[0] + (s.b[0] - s.a[0]) * i / L, s.a[1] + (s.b[1] - s.a[1]) * i / L, 0.5]);
    }
    const x0 = Math.min(s.a[0], s.b[0]), x1 = Math.max(s.a[0], s.b[0]);
    const y0 = Math.min(s.a[1], s.b[1]), y1 = Math.max(s.a[1], s.b[1]);
    if (s.t === "rect") {
      const c = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
      const out = [];
      for (let i = 1; i < c.length; i++) {
        const L = Math.max(2, Math.ceil(Math.hypot(c[i][0] - c[i - 1][0], c[i][1] - c[i - 1][1]) / 0.004));
        for (let j = i === 1 ? 0 : 1; j <= L; j++) {
          out.push([c[i - 1][0] + (c[i][0] - c[i - 1][0]) * j / L, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * j / L, 0.5]);
        }
      }
      return out;
    }
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = (x1 - x0) / 2, ry = (y1 - y0) / 2;
    return Array.from({ length: n + 1 }, (_, i) =>
      [cx + rx * Math.cos((i / n) * Math.PI * 2), cy + ry * Math.sin((i / n) * Math.PI * 2), 0.5]);
  }

  function translate(s, dx, dy, free = false) {
    const cy = free ? (v) => Math.max(0, v) : clamp;
    const mv = (q) => [clamp(q[0] + dx), cy(q[1] + dy), ...q.slice(2)];
    if (s.pts) return { ...s, pts: s.pts.map(mv) };
    if (s.t === "text") return { ...s, x: clamp(s.x + dx), y: cy(s.y + dy) };
    return { ...s, a: mv(s.a), b: mv(s.b) };
  }

  function pt(p, e) {
    const r = p.canvas.getBoundingClientRect();
    const pressure = e.pointerType === "pen" && e.pressure > 0 ? e.pressure : 0.5;
    if (p.view) {
      return [clamp((e.clientX - r.left + window.scrollX) / r.width),
              Math.max(0, (e.clientY - r.top + window.scrollY) / r.width), +pressure.toFixed(2)];
    }
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height), +pressure.toFixed(2)];
  }

  function scroller(el) {
    for (let n = el.parentElement; n; n = n.parentElement) {
      const o = getComputedStyle(n).overflowY;
      if ((o === "auto" || o === "scroll") && n.scrollHeight > n.clientHeight) return n;
    }
    return document.scrollingElement;
  }

  // ── input ──────────────────────────────────────────────────────────────────
  function bind(p) {
    const c = p.canvas;
    // Windows' pen press-and-hold would open the context menu mid-stroke.
    c.addEventListener("contextmenu", (e) => { if (DRAWS.has(A.tool)) e.preventDefault(); });
    c.addEventListener("pointerdown", (e) => {
      if (A.swallow) { A.swallow = false; return; }     // this press only ended a text edit
      if (!DRAWS.has(A.tool) || e.button > 0 || !p.strokes) return;
      if (e.pointerType === "pen") { A.penSeen = true; document.documentElement.classList.add("an-pen"); }
      e.preventDefault();
      c.setPointerCapture(e.pointerId);
      // Stylus seen: a finger or palm scrolls instead of drawing.
      if (A.penSeen && e.pointerType === "touch") {
        p.pan = { id: e.pointerId, x: e.clientX, y: e.clientY, el: scroller(p.el) };
        return;
      }
      const q = pt(p, e);
      const { w, h } = size(p);
      if (A.tool === "text") return startText(p, e, q);
      if (A.tool === "select") return startSelect(p, q, w, h, e);
      const sw = SIZES[A.size];
      if (A.tool === "eraser") { p.erasing = { before: null }; p.eraserAt = q; eraseAt(p, q, w, h); }
      else if (A.tool === "pen" || A.tool === "marker") {
        const snap = rulerSnap(p, e);
        p.live = { t: A.tool, c: A.color, w: sw, pts: [snap ? snap.project(q) : q] };
        p.snap = snap;
      }
      else p.live = { t: A.tool, c: A.color, w: sw, a: q.slice(0, 2), b: q.slice(0, 2) };
      schedule(p);
    });
    c.addEventListener("pointermove", (e) => {
      if (p.pan && e.pointerId === p.pan.id) {
        p.pan.el.scrollTop -= e.clientY - p.pan.y;
        p.pan.el.scrollLeft -= e.clientX - p.pan.x;
        p.pan.x = e.clientX; p.pan.y = e.clientY;
        return;
      }
      if (A.tool === "eraser" && DRAWS.has(A.tool) && !p.erasing) {   // show the eraser ring on hover
        p.eraserAt = pt(p, e);
        return schedule(p);
      }
      if (!p.live && !p.erasing && !p.drag) {
        if ((A.tool === "select" || A.tool === "text") && p.strokes) {   // resize / move cursors
          const cur = A.sel?.key === p.key ? p.strokes[A.sel.i] : null;
          const { w, h } = size(p);
          const q = pt(p, e);
          const hd = cur && onHandle(cur, q, w, h);
          c.style.cursor = hd ? CURSOR[hd]
            : A.tool === "text" && topmost(p, q, w, h, (x) => x.t === "text") >= 0 ? "move" : "";
        }
        return;
      }
      e.preventDefault();
      const co = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
      const events = co.length ? co : [e];
      const { w, h } = size(p);
      for (const ev of events) {
        const q = pt(p, ev);
        if (p.erasing) { p.eraserAt = q; eraseAt(p, q, w, h); }
        else if (p.drag) moveSelect(p, q);
        else if (p.live.pts) {
          const last = p.live.pts[p.live.pts.length - 1];
          const qq = p.snap ? p.snap.project(q) : q;
          if (Math.hypot(qq[0] - last[0], qq[1] - last[1]) > 0.0008) p.live.pts.push(qq);
        } else p.live.b = q.slice(0, 2);
      }
      schedule(p, !!(p.erasing || p.drag));
    });
    c.addEventListener("pointerleave", () => { if (!p.erasing) { p.eraserAt = null; schedule(p); } });
    const end = (e) => {
      if (p.pan && e.pointerId === p.pan.id) { p.pan = null; return; }
      if (p.erasing) {
        if (p.erasing.before) commit(p, p.erasing.before);
        p.erasing = null;
      } else if (p.drag) {
        const d = p.drag;
        p.drag = null;
        if (d.moved) commit(p, d.before);
        else if (d.editOnClick && A.sel?.key === p.key) { paintLayer(p); return openEditor(p, A.sel.i); }
      } else if (p.live) {
        const s = p.live;
        p.live = null;
        p.snap = null;
        const tiny = s.a && Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) < 0.004;
        if (!tiny) {
          const before = p.strokes.slice();
          if (s.pts) s.pts = s.pts.map((q) => [+q[0].toFixed(4), +q[1].toFixed(4), q[2]]);
          p.strokes.push(s);
          commit(p, before);
        }
      }
      paintLayer(p);
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("dblclick", (e) => {
      if (A.tool !== "select" && A.tool !== "text") return;
      const q = pt(p, e);
      const { w, h } = size(p);
      const i = topmost(p, q, w, h, (s) => s.t === "text");
      if (i >= 0) openEditor(p, i);
    });
  }

  function topmost(p, q, w, h, only = () => true) {
    for (let i = p.strokes.length - 1; i >= 0; i--) if (only(p.strokes[i]) && grabs(p.strokes[i], q, w, h)) return i;
    return -1;
  }

  // ── select / move ──────────────────────────────────────────────────────────
  function selected() {
    if (!A.sel) return null;
    return A.pages.get(A.sel.key)?.strokes?.[A.sel.i] || null;
  }

  function startSelect(p, q, w, h) {
    const cur = A.sel?.key === p.key ? p.strokes[A.sel.i] : null;
    const hd = cur && onHandle(cur, q, w, h);
    if (hd) {
      const b = bbox(cur, w, h);
      p.drag = { start: q, orig: cur, before: p.strokes.slice(), moved: false, handle: hd, w, h,
                 px: [b[0] * w, b[1] * h, b[2] * w, b[3] * h] };
      return;
    }
    const i = topmost(p, q, w, h);
    const again = cur && i === A.sel.i;                 // a second press on the same object
    const prevKey = A.sel?.key;
    A.sel = i >= 0 ? { key: p.key, i } : null;
    if (prevKey && prevKey !== p.key) { const o = A.pages.get(prevKey); if (o) blit(o); }
    if (i >= 0) {
      const s = p.strokes[i];
      // pressing an already selected text box and letting go = edit it
      p.drag = { start: q, orig: s, before: p.strokes.slice(), moved: false,
                 editOnClick: again && s.t === "text" };
      if (s.c) { A.color = LEGACY[s.c.toLowerCase()] || s.c; }
    }
    paintBar();
  }

  function moveSelect(p, q) {
    const d = p.drag;
    const dx = q[0] - d.start[0], dy = q[1] - d.start[1];
    if (!d.moved && Math.hypot(dx, dy) < 0.003) return;
    d.moved = true;
    p.strokes[A.sel.i] = d.handle ? resizeTo(d, q) : translate(d.orig, dx, dy, !!p.view);
    placeTextBar();
  }

  /** Dragging a handle. Text: the corners scale the text about the opposite
   *  corner, the sides set the wrap width. Shapes: the grabbed edges move.
   *  Lines / arrows: the grabbed end moves. */
  function resizeTo(d, q) {
    const o = d.orig, H = d.handle, { w, h } = d;
    const qx = q[0] * w, qy = q[1] * h;
    if (o.t === "line" || o.t === "arrow") return { ...o, [H]: [clamp(q[0]), Math.max(0, q[1])] };
    if (o.t === "text") {
      const L = textLayout(o, w);
      const minW = Math.max(L.fs * 2, 24);
      if (H === "e") return { ...o, bw: +(Math.max(minW, qx - L.pad - o.x * w) / w).toFixed(4) };
      if (H === "w") {
        const right = o.x * w + L.boxW;
        const nx = Math.min(right - minW, qx + L.pad);
        return { ...o, x: clamp(nx / w), bw: +((right - nx) / w).toFixed(4) };
      }
      const [bx0, by0, bx1, by1] = d.px;
      const ax = H.includes("w") ? bx1 : bx0, ay = H.includes("n") ? by1 : by0;
      const k = Math.max(Math.abs(qx - ax) / Math.max(4, bx1 - bx0), Math.abs(qy - ay) / Math.max(4, by1 - by0));
      const fsz = Math.min(0.16, Math.max(0.006, o.s * Math.max(0.15, Math.min(12, k))));
      const kk = fsz / o.s;
      const W2 = (bx1 - bx0) * kk, H2 = (by1 - by0) * kk, pad2 = L.pad * kk;
      const nx0 = H.includes("w") ? ax - W2 : ax, ny0 = H.includes("n") ? ay - H2 : ay;
      return { ...o, s: +fsz.toFixed(5), x: clamp((nx0 + pad2) / w), y: Math.max(0, (ny0 + pad2) / h),
               ...(o.bw ? { bw: +(o.bw * kk).toFixed(4) } : {}) };
    }
    let x0 = Math.min(o.a[0], o.b[0]), y0 = Math.min(o.a[1], o.b[1]);
    let x1 = Math.max(o.a[0], o.b[0]), y1 = Math.max(o.a[1], o.b[1]);
    if (H.includes("w")) x0 = Math.min(q[0], x1 - 0.005);
    if (H.includes("e")) x1 = Math.max(q[0], x0 + 0.005);
    if (H.includes("n")) y0 = Math.min(q[1], y1 - 0.005);
    if (H.includes("s")) y1 = Math.max(q[1], y0 + 0.005);
    return { ...o, a: [clamp(x0), Math.max(0, y0)], b: [clamp(x1), y1] };
  }

  function deleteSelected() {
    const p = A.sel && A.pages.get(A.sel.key);
    if (!p?.strokes[A.sel.i]) { A.sel = null; return paintBar(); }
    const before = p.strokes.slice();
    p.strokes.splice(A.sel.i, 1);
    A.sel = null;
    commit(p, before);
    paintLayer(p);
  }

  function mutate(key, fn) {
    const p = A.pages.get(key);
    if (!p) return;
    const before = p.strokes.slice();
    fn(p.strokes);
    commit(p, before);
    paintLayer(p);
  }

  // ── eraser ─────────────────────────────────────────────────────────────────
  function eraseAt(p, q, w, h) {
    const r = ERASER_R[A.eraseSize];
    const k = h / w;
    let changed = false;
    const out = [];
    for (const s of p.strokes) {
      if (!hit(s, q, r, w, h)) { out.push(s); continue; }
      changed = true;
      if (A.eraseMode === "stroke" || s.t === "text") continue;        // whole object goes
      // Partial: drop the points under the eraser and split what is left into
      // separate strokes. Shapes become freehand strokes along their outline.
      const pts = s.pts || outline(s);
      const kind = s.pts ? s.t : "pen";
      let run = [];
      const flush = () => { if (run.length > 1) out.push({ t: kind, c: s.c, w: s.w, pts: run }); run = []; };
      for (const a of pts) {
        if (Math.hypot(a[0] - q[0], (a[1] - q[1]) * k) < r) flush();
        else run.push(a);
      }
      flush();
      if (s.t === "arrow") {
        // keep the head if the tip wasn't erased
        if (Math.hypot(s.b[0] - q[0], (s.b[1] - q[1]) * k) >= r) {
          const tail = out[out.length - 1];
          if (tail && tail.pts.at(-1) === pts.at(-1)) {
            const a0 = tail.pts[0];
            out[out.length - 1] = { t: "arrow", c: s.c, w: s.w, a: [a0[0], a0[1]], b: s.b };
          }
        }
      }
    }
    if (changed) {
      if (!p.erasing.before) p.erasing.before = p.strokes.slice();
      p.strokes = out;
    }
  }

  // ── text ───────────────────────────────────────────────────────────────────
  // ── text boxes ─────────────────────────────────────────────────────────────
  // Like the text box in a PDF editor: click to place one (or drag an existing
  // one to move it, click it to type in it), a formatting bar above it (font,
  // size in pt, bold / italic / underline, alignment, colour, fill, border,
  // duplicate, delete), side handles for the wrap width, corner handles to
  // scale it once it is selected. Enter = new line; Esc, Ctrl+Enter or a click
  // outside = done. The editing box is styled exactly like the finished text,
  // which is drawn on the canvas once the edit ends.
  const TX = { ed: null };        // ed = the box being typed in: { p, index, orig, s, wrap, box }
  try {
    const t = JSON.parse(localStorage.getItem("pwt-annot-text") || "{}");
    A.textStyle = { ...TEXT_DEFAULTS, ...(t && typeof t === "object" ? t : {}) };
  } catch { A.textStyle = { ...TEXT_DEFAULTS }; }
  if (!FONTS[A.textStyle.f]) A.textStyle.f = "sans";
  A.textStyle.pt = Math.min(96, Math.max(6, Math.round(+A.textStyle.pt) || 12));
  const PT_STEPS = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 42, 48, 60, 72, 96];
  const stepPt = (s, dir) => {
    const pt = Math.round(s * PT_PER_W);
    return dir > 0 ? PT_STEPS.find((v) => v > pt) ?? 96 : [...PT_STEPS].reverse().find((v) => v < pt) ?? 6;
  };

  /** What gets stored: defaults are left out to keep saves small. */
  function cleanText(o) {
    const out = { t: "text", x: +(+o.x).toFixed(4), y: +(+o.y).toFixed(4), s: +(+o.s).toFixed(5), c: o.c, txt: o.txt || "" };
    if (o.f) out.f = FONTS[o.f] ? o.f : "sans";          // boxes from before fonts keep their look
    if (o.bw) out.bw = +(+o.bw).toFixed(4);
    for (const k of ["b", "i", "u", "bd"]) if (o[k]) out[k] = 1;
    if (o.al === "c" || o.al === "r") out.al = o.al;
    if (o.bg) out.bg = o.bg;
    return out;
  }

  function startText(p, e, q) {
    const { w, h } = size(p);
    const cur = A.sel?.key === p.key ? p.strokes[A.sel.i] : null;
    if (cur && onHandle(cur, q, w, h)) return startSelect(p, q, w, h);
    const i = topmost(p, q, w, h, (x) => x.t === "text");
    if (i >= 0) {                                 // on a text box: drag = move it, click = type in it
      const prevKey = A.sel?.key;
      A.sel = { key: p.key, i };
      if (prevKey && prevKey !== p.key) { const o = A.pages.get(prevKey); if (o) blit(o); }
      p.drag = { start: q, orig: p.strokes[i], before: p.strokes.slice(), moved: false, editOnClick: true };
      paintBar();
      return;
    }
    if (A.sel) { const o = A.pages.get(A.sel.key); A.sel = null; if (o) blit(o); }
    const d = A.textStyle;
    openEditor(p, null, { t: "text", x: q[0], y: q[1], c: A.color, s: d.pt / PT_PER_W, f: d.f,
                          b: d.b, i: d.i, u: d.u, al: d.al, bg: d.bg, bd: d.bd, txt: "" });
  }

  function openEditor(p, index, fresh) {
    closeEditor(true);
    const orig = index == null ? null : p.strokes[index];
    if (index != null && orig?.t !== "text") return;
    const ed = { p, index, orig, s: { ...(orig || fresh) } };
    const wrap = document.createElement("div");
    wrap.className = "an-textwrap";
    wrap.innerHTML = `
      <textarea class="an-text" rows="1" aria-label="Text box" placeholder="Type here"></textarea>
      <span class="an-tx-h" data-h="w" title="Drag to change the width" aria-hidden="true"></span>
      <span class="an-tx-h" data-h="e" title="Drag to change the width" aria-hidden="true"></span>`;
    ed.wrap = wrap;
    ed.box = wrap.querySelector("textarea");
    ed.box.value = ed.s.txt || "";
    (p.view ? document.body : p.el).appendChild(wrap);
    TX.ed = ed;
    A.sel = index == null ? null : { key: p.key, i: index };
    p.hideIndex = index;                              // the box shows it while it is edited
    paintLayer(p);
    styleBox();
    ed.box.focus({ preventScroll: true });
    const n = ed.box.value.length;
    ed.box.setSelectionRange(n, n);
    ed.box.addEventListener("input", () => { ed.s.txt = ed.box.value; styleBox(); placeTextBar(); });
    ed.box.addEventListener("keydown", (ev) => {
      ev.stopPropagation();                           // letters are text, not tool hotkeys
      const mod = ev.ctrlKey || ev.metaKey;
      if (ev.key === "Escape" || (mod && ev.key === "Enter")) { ev.preventDefault(); closeEditor(true); }
      else if (mod && /^[biu]$/i.test(ev.key)) {
        ev.preventDefault();
        const k = ev.key.toLowerCase();
        setTextStyle({ [k]: !ed.s[k] });
      }
    });
    wrap.addEventListener("pointerdown", (ev) => {
      const hnd = ev.target.closest(".an-tx-h");
      ev.stopPropagation();
      if (!hnd) return;
      ev.preventDefault();
      dragWidth(ev, hnd.dataset.h);
    });
    paintBar();
  }

  /** Style the editing box exactly like the finished text will be drawn. */
  function styleBox() {
    const ed = TX.ed;
    if (!ed) return;
    const { p, s, box, wrap } = ed;
    const W = p.el.clientWidth, H = p.view ? W : p.el.clientHeight;
    let L = textLayout({ ...s, txt: box.value || " " }, W);
    const room = Math.max(40, W - s.x * W - L.pad - 4);      // up to the page's right edge
    if (!s.bw && L.boxW > room) { s.bw = room / W; L = textLayout({ ...s, txt: box.value || " " }, W); }
    measure.font = L.font;
    const empty = box.value ? 0 : measure.measureText("Type here").width;
    const contentW = s.bw ? s.bw * W : Math.max(L.boxW, empty) + 2;
    wrap.style.left = `${s.x * W - L.pad}px`;
    wrap.style.top = `${s.y * H - L.pad}px`;
    Object.assign(box.style, {
      font: L.font, lineHeight: `${L.lh}px`, padding: `${L.pad}px`, color: ink(s.c),
      width: `${contentW + 2 * L.pad}px`,
      textAlign: s.al === "c" ? "center" : s.al === "r" ? "right" : "left",
      textDecoration: s.u ? "underline" : "none",
      whiteSpace: s.bw ? "pre-wrap" : "pre",
      background: !s.bg ? "transparent" : s.bg === "paper" ? fillColour("paper")
        : `color-mix(in srgb, ${ink(s.bg)} ${dark() ? 32 : 26}%, transparent)`,
      boxShadow: s.bd ? `inset 0 0 0 ${Math.max(1, L.fs * 0.07)}px ${ink(s.c)}` : "none",
    });
    box.style.height = "0px";
    box.style.height = `${Math.max(box.scrollHeight, Math.max(1, L.lines.length) * L.lh + 2 * L.pad)}px`;
    wrap.classList.toggle("is-wrapped", !!s.bw);
  }

  /** The side handles of the editing box: drag to set the wrap width. */
  function dragWidth(ev, side) {
    const ed = TX.ed;
    const { p, s } = ed;
    const W = p.el.clientWidth;
    const L = textLayout({ ...s, txt: ed.box.value || " " }, W);
    const start = ev.clientX, x0 = s.x * W, bw0 = s.bw ? s.bw * W : L.boxW, right = x0 + bw0;
    const minW = Math.max(L.fs * 2, 24);
    const move = (e) => {
      const dx = e.clientX - start;
      if (side === "e") s.bw = Math.min(W - x0, Math.max(minW, bw0 + dx)) / W;
      else {
        const nx = Math.max(0, Math.min(right - minW, x0 + dx));
        s.x = nx / W;
        s.bw = (right - nx) / W;
      }
      styleBox();
      placeTextBar();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      ed.box.focus({ preventScroll: true });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  /** End the edit: an empty box goes away, anything else is saved (one undo step). */
  function closeEditor(save = true) {
    const ed = TX.ed;
    if (!ed) return;
    TX.ed = null;
    ed.wrap.remove();
    const p = ed.p;
    p.hideIndex = null;
    const txt = ed.box.value.replace(/\s+$/, "").slice(0, 5000);
    const before = p.strokes.slice();
    const at = ed.index != null && p.strokes[ed.index] === ed.orig ? ed.index : null;   // undo may have moved it
    const obj = cleanText({ ...ed.s, txt });
    if (at == null) {
      if (save && txt) { p.strokes.push(obj); A.sel = { key: p.key, i: p.strokes.length - 1 }; commit(p, before); }
    } else if (!txt) {
      p.strokes.splice(at, 1);
      A.sel = null;
      commit(p, before);
    } else if (save && JSON.stringify(obj) !== JSON.stringify(ed.orig)) {
      p.strokes[at] = obj;
      A.sel = { key: p.key, i: at };
      commit(p, before);
    }
    paintLayer(p);
    paintBar();
  }

  // A press anywhere else ends the edit - and only that: it does not also
  // start a new text box where you clicked.
  document.addEventListener("pointerdown", (e) => {
    const ed = TX.ed;
    if (!ed || ed.wrap.contains(e.target) || tb.contains(e.target)) return;
    closeEditor(true);
    if (e.target.classList?.contains("an-layer")) A.swallow = true;
  }, true);
  window.addEventListener("resize", () => { styleBox(); placeTextBar(); });

  // ── the formatting bar ─────────────────────────────────────────────────────
  const tb = document.createElement("div");
  tb.className = "an-tb";
  tb.setAttribute("role", "toolbar");
  tb.setAttribute("aria-label", "Text box formatting");
  const ti = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${TICON[k]}</svg>`;
  tb.innerHTML = `
    <button type="button" class="an-tb-grip" data-tb="move" title="Drag to move the text box"
            aria-label="Move the text box">${ti("grip")}</button>
    <select data-tb="font" aria-label="Font" title="Font">${Object.entries(FONTS).map(([k, [n, css]]) =>
      `<option value="${k}" style="font-family:${css.replace(/"/g, "&quot;")}">${n}</option>`).join("")}</select>
    <span class="an-tb-size">
      <button type="button" data-tb="smaller" aria-label="Smaller text" title="Smaller">−</button>
      <input data-tb="pt" type="number" min="6" max="96" step="1" inputmode="numeric"
             aria-label="Font size in points" title="Font size (pt)">
      <button type="button" data-tb="bigger" aria-label="Bigger text" title="Bigger">+</button>
    </span>
    <span class="an-tb-sep"></span>
    <button type="button" data-tb="b" aria-pressed="false" title="Bold (Ctrl+B)" aria-label="Bold"><b>B</b></button>
    <button type="button" data-tb="i" aria-pressed="false" title="Italic (Ctrl+I)" aria-label="Italic"><i>I</i></button>
    <button type="button" data-tb="u" aria-pressed="false" title="Underline (Ctrl+U)" aria-label="Underline"><u>U</u></button>
    <span class="an-tb-sep"></span>
    ${[["l", "alL", "Align left"], ["c", "alC", "Centre"], ["r", "alR", "Align right"]].map(([v, k, n]) =>
      `<button type="button" data-tb="al" data-v="${v}" aria-pressed="false" title="${n}" aria-label="${n}">${ti(k)}</button>`).join("")}
    <span class="an-tb-sep"></span>
    <button type="button" data-tb="color" aria-haspopup="true" aria-expanded="false" title="Text colour"
            aria-label="Text colour"><i class="an-tb-dot"></i></button>
    <button type="button" data-tb="fill" aria-haspopup="true" aria-expanded="false" title="Box fill"
            aria-label="Box fill">${ti("fill")}<i class="an-tb-bar"></i></button>
    <button type="button" data-tb="bd" aria-pressed="false" title="Border" aria-label="Border">${ti("border")}</button>
    <span class="an-tb-sep"></span>
    <button type="button" data-tb="dup" title="Duplicate (Ctrl+D)" aria-label="Duplicate">${ti("dup")}</button>
    <button type="button" data-tb="del" title="Delete (Del)" aria-label="Delete">${ti("trash")}</button>
    <button type="button" class="an-tb-done" data-tb="done" title="Finish (Esc)">Done</button>
    <div class="an-tb-pop" data-tbpop="color" hidden>${PALETTE.map(([k, , , n]) =>
      `<button type="button" data-tbc="@${k}" title="${n}" aria-label="${n}"></button>`).join("")}</div>
    <div class="an-tb-pop" data-tbpop="fill" hidden>${FILLS.map(([v, n]) =>
      `<button type="button" data-tbf="${v}" title="${n}" aria-label="${n}"></button>`).join("")}</div>`;

  function paintTextBar(s) {
    tb.querySelector('[data-tb="font"]').value = FONTS[s.f] ? s.f : "sans";
    const pt = tb.querySelector('[data-tb="pt"]');
    if (document.activeElement !== pt) pt.value = Math.round(s.s * PT_PER_W);
    for (const k of ["b", "i", "u", "bd"]) tb.querySelector(`[data-tb="${k}"]`).setAttribute("aria-pressed", String(!!s[k]));
    tb.querySelectorAll('[data-tb="al"]').forEach((b) =>
      b.setAttribute("aria-pressed", String((s.al || "l") === b.dataset.v)));
    tb.querySelector(".an-tb-dot").style.background = ink(s.c);
    tb.querySelector(".an-tb-bar").style.background = s.bg ? fillColour(s.bg) : "transparent";
    tb.querySelectorAll("[data-tbc]").forEach((b) => {
      b.style.setProperty("--c", ink(b.dataset.tbc));
      b.classList.toggle("is-on", b.dataset.tbc === s.c);
    });
    tb.querySelectorAll("[data-tbf]").forEach((b) => {
      const v = b.dataset.tbf;
      b.style.setProperty("--c", v ? fillColour(v) : "transparent");
      b.classList.toggle("is-none", !v);
      b.classList.toggle("is-on", (s.bg || "") === v);
    });
    tb.querySelector('[data-tb="done"]').hidden = !TX.ed;
    tb.dataset.paper = dark() ? "dark" : "light";
  }

  /** Show the bar over the box being edited, or the selected text box. */
  function placeTextBar() {
    let p, s, top0, bottom0;
    if (TX.ed) {
      ({ p, s } = TX.ed);
      top0 = parseFloat(TX.ed.wrap.style.top) || 0;
      bottom0 = top0 + TX.ed.wrap.offsetHeight;
    } else {
      const o = selected();
      p = A.sel && A.pages.get(A.sel.key);
      if (o?.t !== "text" || !p?.el.isConnected || A.collapsed || !(A.tool === "select" || A.tool === "text")) {
        closeTbPops();
        tb.remove();
        return;
      }
      s = o;
      const W0 = p.el.clientWidth, H0 = p.view ? W0 : p.el.clientHeight;
      const b = bbox(s, W0, H0);
      top0 = b[1] * H0 - 5;
      bottom0 = b[3] * H0 + 5;
    }
    const host = p.view ? document.body : p.el;
    if (tb.parentNode !== host) host.appendChild(tb);
    paintTextBar(s);
    const W = p.el.clientWidth, H = p.view ? W : p.el.clientHeight;
    const pad = textLayout(s, W).pad;
    const bw = tb.offsetWidth, bh = tb.offsetHeight;
    const maxLeft = Math.max(0, (p.view ? document.documentElement.clientWidth + window.scrollX : W) - bw - 4);
    const left = Math.min(Math.max(p.view ? window.scrollX + 4 : 0, s.x * W - pad - 6), maxLeft);
    let top = top0 - bh - 10;
    // no room above (top of the page, or above the visible area): put it below
    const onScreen = p.view ? top - window.scrollY : p.el.getBoundingClientRect().top + top;
    if (top < 0 || onScreen < 8) top = bottom0 + 10;
    tb.style.left = `${left}px`;
    tb.style.top = `${Math.min(top, Math.max(0, H - bh))}px`;
  }

  function closeTbPops() {
    tb.querySelectorAll("[data-tbpop]").forEach((x) => { x.hidden = true; });
    tb.querySelectorAll("[aria-haspopup]").forEach((x) => x.setAttribute("aria-expanded", "false"));
  }

  function refocus() {
    if (TX.ed && !tb.contains(document.activeElement)) TX.ed.box.focus({ preventScroll: true });
  }

  /** Apply a style to the box being edited, or to the selected text box, and
   *  remember it (not the colour - that is the main bar's) for the next box. */
  function setTextStyle(patch) {
    const keep = {};
    for (const k of ["f", "b", "i", "u", "al", "bg", "bd"]) if (k in patch) keep[k] = patch[k];
    if ("s" in patch) keep.pt = Math.round(patch.s * PT_PER_W);
    if (Object.keys(keep).length) {
      A.textStyle = { ...A.textStyle, ...keep };
      try { localStorage.setItem("pwt-annot-text", JSON.stringify(A.textStyle)); } catch { /* ignore */ }
    }
    if (TX.ed) { Object.assign(TX.ed.s, patch); styleBox(); placeTextBar(); return; }
    const o = selected();
    if (o?.t !== "text") return;
    mutate(A.sel.key, (list) => { list[A.sel.i] = cleanText({ ...o, ...patch }); });
    paintBar();
  }

  tb.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("select, input")) e.preventDefault();      // keep the caret in the box
    e.stopPropagation();
    if (e.target.closest('[data-tb="move"]')) dragTextBox(e);
  });
  tb.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tb], [data-tbc], [data-tbf]");
    if (!b) return;
    const src = TX.ed?.s || selected();
    if (!src) return;
    if (b.dataset.tbc) { A.color = b.dataset.tbc; persist(); setTextStyle({ c: b.dataset.tbc }); closeTbPops(); return refocus(); }
    if ("tbf" in b.dataset) { setTextStyle({ bg: b.dataset.tbf }); closeTbPops(); return refocus(); }
    const k = b.dataset.tb;
    if (k === "b" || k === "i" || k === "u" || k === "bd") setTextStyle({ [k]: !src[k] });
    else if (k === "al") setTextStyle({ al: b.dataset.v });
    else if (k === "smaller" || k === "bigger") setTextStyle({ s: stepPt(src.s, k === "bigger" ? 1 : -1) / PT_PER_W });
    else if (k === "color" || k === "fill") {
      const pop = tb.querySelector(`[data-tbpop="${k}"]`);
      const open = pop.hidden;
      closeTbPops();
      pop.hidden = !open;
      b.setAttribute("aria-expanded", String(open));
    } else if (k === "dup") duplicateSelected();
    else if (k === "del") {
      if (TX.ed) { TX.ed.box.value = ""; closeEditor(true); } else deleteSelected();
    } else if (k === "done") closeEditor(true);
    refocus();
  });
  const setPt = (el) => {
    const v = Math.min(96, Math.max(6, Math.round(+el.value || 12)));
    el.value = v;
    setTextStyle({ s: v / PT_PER_W });
  };
  tb.addEventListener("change", (e) => {
    if (e.target.dataset.tb === "font") setTextStyle({ f: e.target.value });
    if (e.target.dataset.tb === "pt") setPt(e.target);
    refocus();
  });
  tb.addEventListener("keydown", (e) => {
    e.stopPropagation();                               // typing a size is not a tool hotkey
    if (e.key === "Escape") { closeTbPops(); refocus(); }
    if (e.key === "Enter" && e.target.dataset.tb === "pt") { e.preventDefault(); setPt(e.target); refocus(); }
  });

  /** The grip on the bar: move the box (while editing or selected). */
  function dragTextBox(e) {
    const ed = TX.ed;
    const p = ed ? ed.p : A.sel && A.pages.get(A.sel.key);
    const o = ed ? ed.s : selected();
    if (!p || !o) return;
    const W = p.el.clientWidth, H = p.view ? W : p.el.clientHeight;
    const sx = e.clientX, sy = e.clientY, x0 = o.x, y0 = o.y;
    const before = p.strokes.slice(), orig = o, i = A.sel?.i;
    const move = (ev) => {
      const nx = clamp(x0 + (ev.clientX - sx) / W), ny = Math.max(0, y0 + (ev.clientY - sy) / H);
      if (ed) { ed.s.x = nx; ed.s.y = ny; styleBox(); }
      else { p.strokes[i] = { ...orig, x: nx, y: p.view ? ny : Math.min(1, ny) }; schedule(p, true); }
      placeTextBar();
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (!ed && p.strokes[i] !== orig) commit(p, before);
      refocus();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function duplicateSelected() {
    closeEditor(true);
    const o = selected(), p = A.sel && A.pages.get(A.sel.key);
    if (!o || !p) return;
    const { w, h } = size(p);
    const before = p.strokes.slice();
    p.strokes.push(translate(o, 14 / w, 14 / h, !!p.view));
    A.sel = { key: p.key, i: p.strokes.length - 1 };
    commit(p, before);
    paintLayer(p);
  }

  function paste() {
    const p = (A.sel && A.pages.get(A.sel.key)) || nearestPage();
    if (!p?.strokes) return;
    const { w, h } = size(p);
    const off = A.clip.from === p.key ? 14 : 0;
    const copy = translate(A.clip.obj, off / w, off / h, !!p.view);
    A.clip = { obj: copy, from: p.key };              // the next paste steps on again
    const before = p.strokes.slice();
    p.strokes.push(copy);
    A.sel = { key: p.key, i: p.strokes.length - 1 };
    commit(p, before);
    paintLayer(p);
  }

  /** Keys for the selected object: arrows nudge (Shift = 10 px), Ctrl+C / X /
   *  V / D, Enter or F2 types in a selected text box. true = handled. */
  function objectKeys(e) {
    const mod = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
    if (mod && key === "v" && A.clip && !window.getSelection()?.toString()) { e.preventDefault(); paste(); return true; }
    const o = selected(), p = A.sel && A.pages.get(A.sel.key);
    if (!o || !p) return false;
    if (mod && (key === "c" || key === "x")) {
      e.preventDefault();
      A.clip = { obj: JSON.parse(JSON.stringify(o)), from: p.key };
      if (key === "x") deleteSelected(); else flash("Copied");
      return true;
    }
    if (mod && key === "d") { e.preventDefault(); duplicateSelected(); return true; }
    if (!mod && !e.altKey && e.key.startsWith("Arrow")) {
      e.preventDefault();
      const { w, h } = size(p);
      const st = e.shiftKey ? 10 : 1;
      const dx = e.key === "ArrowLeft" ? -st : e.key === "ArrowRight" ? st : 0;
      const dy = e.key === "ArrowUp" ? -st : e.key === "ArrowDown" ? st : 0;
      mutate(p.key, (list) => { list[A.sel.i] = translate(o, dx / w, dy / h, !!p.view); });
      placeTextBar();
      return true;
    }
    if (o.t === "text" && (e.key === "Enter" || e.key === "F2")) { e.preventDefault(); openEditor(p, A.sel.i); return true; }
    return false;
  }

  // ── history + saving ───────────────────────────────────────────────────────
  function commit(p, before) {
    A.undo.push({ key: p.key, before, after: p.strokes.slice() });
    if (A.undo.length > 200) A.undo.shift();
    A.redo = [];
    save(p);
    paintBar();
  }

  function apply(key, strokes) {
    const p = A.pages.get(key);
    if (!p) return false;
    p.strokes = strokes.slice();
    if (A.sel?.key === key && !p.strokes[A.sel.i]) A.sel = null;
    paintLayer(p);
    save(p);
    return true;
  }

  function doUndo() {
    const h = A.undo.pop();
    if (!h) return;
    if (apply(h.key, h.before)) A.redo.push(h);
    paintBar();
  }

  function doRedo() {
    const h = A.redo.pop();
    if (!h) return;
    if (apply(h.key, h.after)) A.undo.push(h);
    paintBar();
  }

  function clearPage() {
    // The page nearest the middle of the screen.
    let best = null, bestD = Infinity;
    for (const p of A.pages.values()) {
      if (!p.el.isConnected || !p.strokes?.length) continue;
      const r = p.el.getBoundingClientRect();
      const d = Math.abs((r.top + r.bottom) / 2 - window.innerHeight / 2);
      if (r.bottom > 0 && r.top < window.innerHeight && d < bestD) { best = p; bestD = d; }
    }
    if (!best) return flash("Nothing to clear on this page");
    const before = best.strokes.slice();
    best.strokes = [];
    A.sel = null;
    commit(best, before);
    paintLayer(best);
  }

  const saved = bar.querySelector(".an-saved");
  function flash(msg) {
    saved.textContent = msg;
    clearTimeout(saved._t);
    saved._t = setTimeout(() => { saved.textContent = ""; }, 2200);
  }

  function save(p) {
    if (!saveInk) {
      if (!A.warned) { A.warned = true; flash(unsaved); }
      return;
    }
    clearTimeout(A.saveTimers.get(p.key));
    A.saveTimers.set(p.key, setTimeout(async () => {
      try {
        await req("PUT", "/api/annotations", { doc: p.doc, page: p.page, strokes: p.strokes });
        const cached = await load(p.doc);
        cached[String(p.page)] = p.strokes.slice();
        flash("Saved");
      } catch { flash("Not saved — check your connection"); }
    }, 700));
  }

  window.addEventListener("resize", () => { for (const p of A.pages.values()) paintLayer(p); });
  paintBar();
  // Phones: start as the small pen button, the full bar would cover the page.
  let remembered = null;
  try { remembered = JSON.parse(localStorage.getItem("pwt-annot") || "{}").open; } catch { /* ignore */ }
  if (collapsed || (window.innerWidth < 700 && remembered !== true)) setCollapsed(true);
  fab.addEventListener("click", () => {
    try {
      const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
      localStorage.setItem("pwt-annot", JSON.stringify({ ...s, open: true }));
    } catch { /* ignore */ }
  });

  function setVisible(v) {
    A.visible = v;
    bar.hidden = !v || A.collapsed;
    fab.hidden = !v || !A.collapsed;
    if (!v && A.tool !== "pointer") setTool("pointer");
  }

  /** One layer over the whole web page (scratch mode). */
  function attachViewport(doc = "scratch") {
    const el = document.createElement("div");
    el.className = "an-viewport";
    mount.appendChild(el);
    const canvas = document.createElement("canvas");
    canvas.className = "an-layer";
    el.appendChild(canvas);
    const p = { el, canvas, doc, page: 0, key: `${doc}|0`, strokes: [], view: true };
    A.pages.set(p.key, p);
    bind(p);
    window.addEventListener("scroll", () => schedule(p, true), { passive: true });
    paintLayer(p);
    return p;
  }

  // ── instruments: ruler + protractor (on screen only, never saved) ──────────
  const INST = { ruler: null, protractor: null };           // kind -> { p, el, x, y, deg }

  /** Pixels per millimetre on this page, at the paper's real size. */
  function pxPerMm(p) {
    if (p.view) return 96 / 25.4;                               // a web page: CSS millimetres
    const w = p.el.clientWidth, h = p.el.clientHeight;
    return w / (w > h ? 297 : 210);                             // A4, or A4 landscape
  }

  function nearestPage() {
    let best = null, bestD = Infinity;
    for (const p of A.pages.values()) {
      if (!p.el.isConnected) continue;
      const r = p.el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) continue;
      const d = Math.abs((Math.max(r.top, 0) + Math.min(r.bottom, window.innerHeight)) / 2 - window.innerHeight / 2);
      if (d < bestD) { best = p; bestD = d; }
    }
    return best;
  }

  function toggleInstrument(kind) {
    if (INST[kind]) { INST[kind].el.remove(); INST[kind] = null; paintInstButtons(); return; }
    const p = nearestPage();
    if (!p) return flash("Open a page first");
    const r = p.el.getBoundingClientRect();
    const vis = { top: Math.max(r.top, 0), bottom: Math.min(r.bottom, window.innerHeight) };
    const it = { kind, p, deg: 0, x: p.el.clientWidth / 2,
                 y: (vis.top + vis.bottom) / 2 - r.top + (kind === "protractor" ? 60 : 0) };
    it.el = document.createElement("div");
    it.el.className = `an-inst an-inst-${kind}`;
    it.el.innerHTML = instrumentSVG(kind, pxPerMm(p)) +
      `<button type="button" class="an-inst-rot" aria-label="Rotate the ${kind}" title="Drag to rotate (Shift: 15° steps)"></button>
       <span class="an-inst-deg">0°</span>
       <button type="button" class="an-inst-x" aria-label="Put the ${kind} away" title="Put away">×</button>`;
    p.el.appendChild(it.el);
    INST[kind] = it;
    placeInstrument(it);
    bindInstrument(it);
    paintInstButtons();
  }

  function paintInstButtons() {
    bar.querySelectorAll("[data-inst]").forEach((b) =>
      b.setAttribute("aria-pressed", String(!!INST[b.dataset.inst])));
  }

  function instrumentSVG(kind, k) {
    if (kind === "ruler") {
      const L = 150 * k, H = 16 * k, t = [];
      for (let mm = 0; mm <= 150; mm++) {
        const x = 6 + mm * k, len = mm % 10 === 0 ? 5 * k : mm % 5 === 0 ? 3.4 * k : 2 * k;
        t.push(`<line x1="${x}" y1="0" x2="${x}" y2="${len}"/>`);
        if (mm % 10 === 0) t.push(`<text x="${x}" y="${len + 3.2 * k}">${mm / 10}</text>`);
      }
      return `<svg class="an-inst-svg" width="${L + 12}" height="${H}" viewBox="0 0 ${L + 12} ${H}">
        <rect class="an-inst-body" x="0" y="0" width="${L + 12}" height="${H}" rx="4"/>
        <g class="an-inst-ticks" style="font-size:${Math.max(8, 2.6 * k)}px">${t.join("")}</g>
        <text class="an-inst-unit" x="${L + 6}" y="${H - 4}" text-anchor="end">cm</text></svg>`;
    }
    const R = 60 * k, pad = 6, t = [];
    for (let d = 0; d <= 180; d++) {
      const a = Math.PI - (d * Math.PI) / 180, len = d % 10 === 0 ? 7 * k : d % 5 === 0 ? 4.5 * k : 2.6 * k;
      const x1 = pad + R + R * Math.cos(a), y1 = pad + R - R * Math.sin(a);
      const x2 = pad + R + (R - len) * Math.cos(a), y2 = pad + R - (R - len) * Math.sin(a);
      t.push(`<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`);
      if (d % 10 === 0) {
        const ro = R - 10.5 * k, ri = R - 15.5 * k;
        const lx = pad + R + ro * Math.cos(a), ly = pad + R - ro * Math.sin(a);
        const ix = pad + R + ri * Math.cos(a), iy = pad + R - ri * Math.sin(a);
        t.push(`<text x="${lx.toFixed(1)}" y="${(ly + 1.2 * k).toFixed(1)}">${d}</text>`);
        t.push(`<text class="an-inst-inner" x="${ix.toFixed(1)}" y="${(iy + 1.2 * k).toFixed(1)}">${180 - d}</text>`);
      }
    }
    return `<svg class="an-inst-svg" width="${2 * R + 2 * pad}" height="${R + pad + 4}" viewBox="0 0 ${2 * R + 2 * pad} ${R + pad + 4}">
      <path class="an-inst-body" d="M${pad} ${pad + R} A${R} ${R} 0 0 1 ${pad + 2 * R} ${pad + R} Z"/>
      <g class="an-inst-ticks" style="font-size:${Math.max(7, 2.3 * k)}px">${t.join("")}</g>
      <line class="an-inst-base" x1="${pad}" y1="${pad + R}" x2="${pad + 2 * R}" y2="${pad + R}"/>
      <circle class="an-inst-centre" cx="${pad + R}" cy="${pad + R}" r="3"/></svg>`;
  }

  /** Where the instrument's origin sits inside its SVG (ruler: centre; protractor: centre of the arc). */
  function origin(it) {
    const svgEl = it.el.querySelector("svg");
    const w = +svgEl.getAttribute("width"), h = +svgEl.getAttribute("height");
    return it.kind === "ruler" ? { ox: w / 2, oy: h / 2, w, h } : { ox: w / 2, oy: h - 4, w, h };
  }

  function placeInstrument(it) {
    const { ox, oy } = origin(it);
    Object.assign(it.el.style, { left: `${it.x - ox}px`, top: `${it.y - oy}px`,
                                 transformOrigin: `${ox}px ${oy}px`, transform: `rotate(${-it.deg}deg)` });
    const d = ((Math.round(it.deg) % 360) + 360) % 360;
    it.el.querySelector(".an-inst-deg").textContent = `${d > 180 ? d - 360 : d}°`;
  }

  function bindInstrument(it) {
    const el = it.el;
    el.querySelector(".an-inst-x").addEventListener("click", () => toggleInstrument(it.kind));
    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".an-inst-x")) return;
      // Pen/highlighter pressed on a ruler EDGE draws along it (hand the press to
      // the page underneath); the middle strip still drags the ruler.
      if (it.kind === "ruler" && (A.tool === "pen" || A.tool === "marker") &&
          !e.target.closest(".an-inst-rot") && rulerSnap(it.p, e)) {
        e.preventDefault();
        it.p.canvas.dispatchEvent(new PointerEvent("pointerdown", {
          bubbles: true, cancelable: true, clientX: e.clientX, clientY: e.clientY,
          pointerId: e.pointerId, pointerType: e.pointerType, pressure: e.pressure,
          button: e.button, buttons: e.buttons, isPrimary: e.isPrimary }));
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      const rot = !!e.target.closest(".an-inst-rot");
      const host = it.p.el.getBoundingClientRect();
      const start = { x: e.clientX, y: e.clientY, ix: it.x, iy: it.y };
      const move = (ev) => {
        if (rot) {
          const cx = host.left + it.x, cy = host.top + it.y;
          let deg = -Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI;
          deg = ev.shiftKey ? Math.round(deg / 15) * 15 : Math.round(deg);
          it.deg = deg;
        } else {
          it.x = start.ix + ev.clientX - start.x;
          it.y = start.iy + ev.clientY - start.y;
        }
        placeInstrument(it);
      };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    });
  }

  /** If a stroke starts on (or just off) a long edge of the ruler on this page,
   *  a projector that pins every point onto that edge line. */
  function rulerSnap(p, e) {
    const it = INST.ruler;
    if (!it || it.p !== p) return null;
    const host = p.el.getBoundingClientRect();
    const x = e.clientX - host.left, y = e.clientY - host.top;
    const a = (-it.deg * Math.PI) / 180, ux = Math.cos(a), uy = Math.sin(a);   // along the ruler
    const nx = -uy, ny = ux;                                                      // across it
    const half = (16 * pxPerMm(p)) / 2, len = (150 * pxPerMm(p)) / 2 + 6;
    const dx = x - it.x, dy = y - it.y;
    const along = dx * ux + dy * uy, across = dx * nx + dy * ny;
    if (Math.abs(along) > len + 10) return null;
    const edge = Math.abs(across - half) < Math.abs(across + half) ? half : -half;
    if (Math.abs(across - edge) > 14) return null;
    const { w, h } = size(p);
    const ex = it.x + nx * edge, ey = it.y + ny * edge;          // a point on the edge line
    return {
      project(q) {
        // page fractions -> element px (the whole-page layer is scrolled)
        const px = q[0] * w - (p.view ? window.scrollX : 0), py = q[1] * h - (p.view ? window.scrollY : 0);
        const t = (px - ex) * ux + (py - ey) * uy;
        const sx = ex + t * ux, sy = ey + t * uy;
        return [(sx + (p.view ? window.scrollX : 0)) / w, (sy + (p.view ? window.scrollY : 0)) / h, q[2]];
      },
    };
  }

  return {
    attach, attachViewport, detachWithin, setVisible,
    repaint: () => { for (const p of A.pages.values()) if (p.el.isConnected) paintLayer(p); },
    setTool, get tool() { return A.tool; },
    onTool: (fn) => A.listeners.add(fn),
    setHotkeys: (on) => { A.hotkeys = on; },
    el: bar,
  };
}
