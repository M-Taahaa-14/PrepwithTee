/* annotate.js — the ink engine + the left annotation rail, on every page.
 *
 *   const ann = createAnnotator({ mount: document.body });
 *   ann.attach(pageEl, "paper:123", 4);   // any positioned element = one "page"
 *
 * The same engine runs the paper viewers (booklets, yearly papers, MCQ
 * sessions, resources), the scratch pen on every other page, and the
 * whiteboard (static/whiteboard/app.js), which passes its own `store`
 * (where pages are saved), `upload` (where pasted images go) and attaches its
 * pages with { camera: true } for the infinite canvas.
 *
 * Rail (left edge): pin · pointer · select · lasso · pen (pen / fineliner /
 * fountain / pencil / dashed, shape snap) · highlighter · eraser (partial /
 * whole object) · shapes (line, arrows, rectangles, ellipse, triangles,
 * quadrilaterals, polygons, star; dashed, filled) · text · sticky note ·
 * stickers & stamps · image · laser · ruler · protractor · compass · five
 * quick colours + a full colour picker (ink/color.js) · size · undo / redo ·
 * clear. Pinned = always open (and on wide screens the paper moves over);
 * unpinned = a slim tab on the left edge that slides the rail out.
 *
 * Objects are stored as fractions of the page (zoom never matters); every
 * object has a short `id`. Inks are palette TOKENS ("@blue") with a light and
 * a pastel shade (paper-theme.js), custom colours are hex (8 digits = see-
 * through). website/annot_pdf.py draws the same objects into downloads -
 * keep the two in step (PALETTE, POLY kinds, stickers.json).
 *
 * Pens (Wacom, Surface, Apple Pencil): the layer is touch-action:none whenever a
 * drawing tool is on; once a stylus has been seen, a finger or palm scrolls.
 * Instruments (never saved): 15 cm ruler (strokes snap to its edge), 180°
 * protractor, compass (needle snaps to ends / intersections, arcs drawn by
 * turning the top, radius lock) - all at the paper's real scale.
 * Keys: V pointer · S select · L lasso · P pen · H highlighter · E eraser ·
 *       T text · N note · K laser · Delete · Ctrl+Z / Ctrl+Y · Ctrl+C/X/V/D.
 */
import { colorPanel, rememberColor } from "/ink/color.js?v=20261005a";
import { POLY, polyCorners, arcPoints, recognise } from "/ink/shapes.js?v=20261005a";
import { loadStickers, stickerImage, stickerLib, stickerCats, stickerSrc } from "/ink/stickers.js?v=20261005a";

export const INK_V = "20261005a";

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
const QUICK = ["@ink", "@blue", "@red", "@green", "@purple"];
const ICON = {
  pointer: '<path d="M5 3l14 8-6 2-2 6z"/>',
  select: '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M9 9l7 3-3 1-1 3z"/>',
  lasso: '<path d="M7 17c-3-1-4-3.5-4-6C3 6.5 7 4 12 4s9 2.5 9 6.5-4 6-8.5 6c-1.6 0-2.8-.2-3.8-.6"/><circle cx="7.5" cy="17.5" r="2"/><path d="M7 19.5c-.5 1.5-1.5 2-3 2"/>',
  pen: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
  fine: '<path d="M5 19L18 6l1 1L6 20z"/><path d="M4 21l1-2 1 1z"/>',
  fountain: '<path d="M12 3l5 8-5 10-5-10z"/><path d="M12 11v4"/><circle cx="12" cy="10" r="1.2"/>',
  pencil: '<path d="M4 20l3.5-1L19 7.5 16.5 5 5 16.5z"/><path d="M14.5 7l2.5 2.5"/><path d="M4 20l1-3.5"/>',
  dash: '<path d="M4 20l2-2M8.5 15.5l2-2M13 11l2-2M17.5 6.5L20 4"/>',
  marker: '<path d="M9 15l-4 5h6l2-3"/><path d="M8 13l7-9 5 4-7 9z"/>',
  eraser: '<path d="M8 20h12"/><path d="M5 15l8-9 6 6-6 7H9z"/>',
  line: '<path d="M5 19L19 5"/>',
  arrow: '<path d="M5 19L19 5"/><path d="M10 5h9v9"/>',
  arrow2: '<path d="M5 19L19 5"/><path d="M10 5h9v9"/><path d="M14 19H5v-9"/>',
  rect: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
  rrect: '<rect x="4" y="6" width="16" height="12" rx="4"/>',
  ellipse: '<ellipse cx="12" cy="12" rx="8.5" ry="6"/>',
  circle: '<circle cx="12" cy="12" r="8"/>',
  tri: '<path d="M12 4l9 16H3z"/>',
  rtri: '<path d="M4 4v16h16z"/>',
  diamond: '<path d="M12 3l8 9-8 9-8-9z"/>',
  para: '<path d="M8 6h13l-5 12H3z"/>',
  trap: '<path d="M8 6h8l5 12H3z"/>',
  pent: '<path d="M12 3l9 6.5-3.4 10.5H6.4L3 9.5z"/>',
  hex: '<path d="M7.5 4h9l4.5 8-4.5 8h-9L3 12z"/>',
  oct: '<path d="M8.5 3h7L21 8.5v7L15.5 21h-7L3 15.5v-7z"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  shapes: '<path d="M3 21l5.5-9 5.5 9z"/><circle cx="16.5" cy="7.5" r="4.5"/>',
  text: '<path d="M5 6V4h14v2"/><path d="M12 4v16"/><path d="M9 20h6"/>',
  note: '<path d="M4 4h16v11l-5 5H4z"/><path d="M15 20v-5h5"/><path d="M8 9h8M8 12.5h5"/>',
  sticker: '<path d="M20 12a8 8 0 11-8-8h3l5 5z"/><path d="M15 4v5h5"/><path d="M8.5 13.5a4 4 0 007 0"/><path d="M9 9.5h.01M13.5 9.5h.01"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-8 8"/>',
  laser: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 000 12h3"/>',
  clear: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
  trash: '<path d="M4 7h16"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
  ruler: '<rect x="2.5" y="8" width="19" height="8" rx="1.2" transform="rotate(-30 12 12)"/><path d="M8.6 7.4l1 1.7M11.2 5.9l1.5 2.6M13.8 4.4l1 1.7" transform="translate(-1.2 4.6)"/>',
  protractor: '<path d="M3 17a9 9 0 0118 0z"/><path d="M12 17l4.5-6.5"/><path d="M7 17a5 5 0 0110 0"/>',
  setsquare: '<path d="M4 20V5l15 15z"/><path d="M8 16v-3.5l3.5 3.5z"/><path d="M4 9h2M4 13h2"/>',
  compass: '<circle cx="12" cy="4.5" r="1.8"/><path d="M11 6.2L6 20M13 6.2L18 20"/><path d="M8 14.5h8"/><path d="M17 17.5l1 2.5"/>',
  pin: '<path d="M9 4h6l-1 6 3 3H7l3-3z"/><path d="M12 13v7"/>',
  pinned: '<path d="M9 4h6l-1 6 3 3H7l3-3z" fill="currentColor"/><path d="M12 13v7"/>',
  hide: '<path d="M15 6l-6 6 6 6"/>',
  palette: '<path d="M12 3a9 9 0 100 18c1.1 0 1.6-.8 1.6-1.6 0-1.3-1-1.7-1-2.9 0-1 .8-1.6 1.8-1.6H17a4 4 0 004-4c0-4.4-4-7.9-9-7.9z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10" cy="7" r="1.2"/><circle cx="15" cy="7.5" r="1.2"/>',
  wand: '<path d="M4 20L15 9"/><path d="M14 4v3M19 9h-3M18 5l-2 2M17 13l-1.5-1.5M10 6l1.5 1.5"/>',
  grip: '<circle cx="9" cy="7" r="1.2"/><circle cx="15" cy="7" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="17" r="1.2"/><circle cx="15" cy="17" r="1.2"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
  unlock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 017.5-2"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const PENS = [["", "pen", "Pen", "Smooth, follows pen pressure"], ["fine", "fine", "Fineliner", "Even width, crisp"],
  ["fountain", "fountain", "Fountain", "Thick and thin, like a nib"], ["pencil", "pencil", "Pencil", "Soft graphite look"],
  ["dash", "dash", "Dashed", "Dashed line"]];
const SHAPE_LIST = [["line", "Line"], ["arrow", "Arrow"], ["arrow2", "Double arrow"], ["rect", "Rectangle"],
  ["rrect", "Rounded rectangle"], ["ellipse", "Ellipse (Shift = circle)"], ["circle", "Circle"],
  ["tri", "Triangle"], ["rtri", "Right-angled triangle"], ["diamond", "Rhombus"], ["para", "Parallelogram"],
  ["trap", "Trapezium"], ["pent", "Pentagon"], ["hex", "Hexagon"], ["oct", "Octagon"], ["star", "Star"]];
const SHAPE_NAME = Object.fromEntries(SHAPE_LIST);
const DRAWS = new Set(["select", "lasso", "pen", "marker", "eraser", "shape", "text", "note", "sticker", "laser"]);
const LEGACY_TOOL = { line: "line", arrow: "arrow", rect: "rect", ellipse: "ellipse" };
const clamp = (v) => Math.min(1, Math.max(0, v));
const uid = () => Math.random().toString(36).slice(2, 10);
const BOX = new Set(["rect", "ellipse", "img", "stk", "note"]);          // defined by corners a, b
const isBox = (s) => BOX.has(s.t) || (s.t === "poly" && !s.pts);
const WHOLE = new Set(["text", "img", "stk", "note"]);                   // the eraser removes these whole

// Text boxes: {t:"text", x, y (top-left), s (font size, fraction of the page
// width), c, txt, bw? (wrap width), f? font, b? i? u?, al? "c"|"r",
// bg? fill ("paper" = covers what is under it, or an ink token = a tint), bd? border}.
const FONTS = {
  sans: ["Sans", '"Hanken Grotesk", system-ui, sans-serif'],
  serif: ["Serif", 'Georgia, "Times New Roman", serif'],
  hand: ["Handwriting", '"Segoe Print", "Bradley Hand", "Chalkboard SE", "Comic Sans MS", cursive'],
  mono: ["Mono", 'Consolas, "SFMono-Regular", Menlo, "Courier New", monospace'],
};
const FILLS = [["", "No fill"], ["paper", "Cover (paper colour)"], ["@yellow", "Yellow"],
  ["@green", "Green"], ["@sky", "Blue"], ["@pink", "Pink"], ["@grey", "Grey"]];
const NOTE_COLORS = ["@yellow", "@pink", "@sky", "@green", "@orange", "@purple"];
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
const BASE = 1000;                    // infinite canvas: px per world unit at 100 %

async function req(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`annotations ${r.status}`);
  return r.json();
}

/** Where paper-viewer ink lives: /api/annotations, one row per page. */
const API_STORE = {
  load: (doc) => req("GET", `/api/annotations?doc=${encodeURIComponent(doc)}`).then((d) => d.pages || {}),
  save: (doc, page, strokes) => req("PUT", "/api/annotations", { doc, page, strokes }),
};

async function apiUpload(blob) {
  const fd = new FormData();
  fd.append("file", blob, `image.${(blob.type.split("/")[1] || "png").replace("jpeg", "jpg")}`);
  const r = await fetch("/api/ink/assets", { method: "POST", body: fd, credentials: "same-origin" });
  if (!r.ok) {
    let msg = "Image not saved";
    try { const d = await r.json(); msg = typeof d.detail === "string" ? d.detail : msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await r.json()).url;
}

const mixHex = (a, b, t) => {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const A = p(a), B = p(b);
  return `#${A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
};

export function createAnnotator({ mount = document.body, persist: saveInk = true,
                                  collapsed = false, unsaved = "Scratch ink — not saved",
                                  dark = () => document.documentElement.dataset.paper === "dark",
                                  store = API_STORE, upload = null, pasteText = false,
                                  pinned: pinDefault = null, push = true, hide = [] } = {}) {
  /** A stored colour -> the colour to paint now (token by paper theme, legacy hex, custom hex). */
  const ink = (c) => {
    if (!c) return ink("@blue");
    if (c[0] === "@") { const p = PAL[c.slice(1)] || PAL.blue; return dark() ? p.d : p.l; }
    const old = LEGACY[c.toLowerCase()];
    return old ? ink(old) : c;
  };
  const scratch = !saveInk;
  const uploader = upload || (saveInk ? apiUpload : async (blob) => URL.createObjectURL(blob));
  const PREF = scratch ? "pwt-annot-scratch" : "pwt-annot";
  const A = {
    tool: "pointer", color: "@blue", size: 2, eraseMode: "partial", eraseSize: 1,
    pen: "", shape: "rect", dash: false, fill: false, recog: true, straight: false, sticker: "star_gold",
    quick: QUICK.slice(), pinned: false, open: false,
    docs: new Map(),      // doc -> Promise<{page: strokes[]}>
    pages: new Map(),     // `${doc}|${page}` -> { el, canvas, strokes, doc, page }
    undo: [], redo: [], saveTimers: new Map(), penSeen: false, listeners: new Set(),
    sel: null,            // { key, i } - one selected object
    msel: null,           // { key, idx: [] } - several (lasso / Shift-click)
    pending: 0, saveState: new Set(),
  };
  let prefs = {};
  try {
    const own = localStorage.getItem(PREF);
    prefs = JSON.parse(own || localStorage.getItem("pwt-annot") || "{}") || {};
    if (!own) delete prefs.pin;                      // the viewers' pin never carries over
  } catch { /* blocked */ }
  {
    const s = prefs;
    const okColor = (c) => typeof c === "string" && (PAL[c.slice(1)] || /^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(c));
    if (okColor(s.color)) A.color = LEGACY[s.color.toLowerCase()] || s.color;
    if (s.size >= 0 && s.size < SIZES.length) A.size = s.v >= 2 ? s.size : Math.min(SIZES.length - 1, s.size + 1);
    if (s.erase === "stroke" || s.erase === "partial") A.eraseMode = s.erase;
    if (s.esize >= 0 && s.esize < ERASER_R.length) A.eraseSize = s.esize;
    if (PENS.some(([k]) => k === s.pen)) A.pen = s.pen;
    if (SHAPE_NAME[s.shape]) A.shape = s.shape;
    if (typeof s.dash === "boolean") A.dash = s.dash;
    if (typeof s.fill === "boolean") A.fill = s.fill;
    if (typeof s.recog === "boolean") A.recog = s.recog;
    if (typeof s.straight === "boolean") A.straight = s.straight;
    if (Array.isArray(s.quick) && s.quick.length === 5 && s.quick.every(okColor)) A.quick = s.quick;
    if (typeof s.sticker === "string") A.sticker = s.sticker;
  }
  const narrow = () => window.innerWidth < 700;
  A.pinned = typeof prefs.pin === "boolean" ? prefs.pin
    : pinDefault != null ? pinDefault : !collapsed && !scratch && window.innerWidth >= 1100;
  if (narrow() && prefs.pin !== true) A.pinned = false;
  A.open = A.pinned;

  // ── the rail ───────────────────────────────────────────────────────────────
  const has = (k) => !hide.includes(k);
  const tbtn = (tool, icon, title, fly = false, extra = "") =>
    `<button type="button" data-tool="${tool}" title="${title}" aria-label="${title}" aria-pressed="false"
      ${fly ? `data-has-fly="${fly}"` : ""} ${extra}>${svg(icon)}${fly ? '<b class="ink-more" aria-hidden="true"></b>' : ""}</button>`;
  const bar = document.createElement("div");
  bar.className = "an-bar ink-rail";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-orientation", "vertical");
  bar.setAttribute("aria-label", "Annotation tools");
  bar.innerHTML = `
    <div class="ink-rail-top">
      <button type="button" class="ink-pin" data-an="pin" aria-pressed="false"></button>
    </div>
    <div class="ink-rail-scroll">
      <div class="ink-grp">
        ${tbtn("pointer", "pointer", "Pointer — scroll and click (V)")}
        ${tbtn("select", "select", "Select — move, resize, edit (S) · Shift-click adds")}
        ${tbtn("lasso", "lasso", "Lasso — circle several things to move them together (L)")}
      </div>
      <div class="ink-grp">
        ${tbtn("pen", "pen", "Pen (P) — tap again for pen types", "pen")}
        ${tbtn("marker", "marker", "Highlighter (H) — tap again for options", "marker")}
        ${tbtn("eraser", "eraser", "Eraser (E) — tap again for options", "eraser")}
      </div>
      <div class="ink-grp">
        ${tbtn("shape", "rect", "Shapes — tap again to choose", "shapes", 'data-shape-btn')}
        ${tbtn("text", "text", "Text box (T)")}
        ${tbtn("note", "note", "Sticky note (N)", "note")}
        ${tbtn("sticker", "sticker", "Stickers & stamps", "stickers")}
        ${has("image") ? `<button type="button" data-an="image" title="Insert an image (or paste one with Ctrl+V)"
            aria-label="Insert an image">${svg("image")}</button>` : ""}
        ${tbtn("laser", "laser", "Laser pointer — fades away, never saved (K)")}
      </div>
      <div class="ink-grp">
        <button type="button" data-inst="ruler" title="Ruler — drag, rotate; draw along its edge" aria-label="Ruler" aria-pressed="false">${svg("ruler")}</button>
        <button type="button" data-inst="protractor" title="Protractor — drag, rotate to measure angles" aria-label="Protractor" aria-pressed="false">${svg("protractor")}</button>
        <button type="button" data-inst="setsquare" title="Set square — 45° or 30°/60°; draw along any edge" aria-label="Set square" aria-pressed="false">${svg("setsquare")}</button>
        <button type="button" data-inst="compass" title="Compass — set the radius, turn the top to draw arcs" aria-label="Compass" aria-pressed="false">${svg("compass")}</button>
      </div>
      <div class="ink-grp ink-colors">
        ${A.quick.map((_, i) => `<button type="button" class="ink-qc" data-qc="${i}"
            title="Colour — right-click or hold to change this slot" aria-label="Quick colour ${i + 1}"><i></i></button>`).join("")}
        <button type="button" class="ink-allc" data-fly="colors" title="All colours" aria-label="All colours"
                aria-haspopup="true" aria-expanded="false"><i></i></button>
        <button type="button" class="ink-size" data-fly="sizes" title="Thickness" aria-label="Thickness"
                aria-haspopup="true" aria-expanded="false"><i></i></button>
      </div>
    </div>
    <div class="ink-rail-foot">
      <button type="button" data-an="delete" class="an-del" title="Delete selected (Delete)" aria-label="Delete selected" hidden>${svg("trash")}</button>
      <button type="button" data-an="undo" title="Undo (Ctrl+Z)" aria-label="Undo">${svg("undo")}</button>
      <button type="button" data-an="redo" title="Redo (Ctrl+Y)" aria-label="Redo">${svg("redo")}</button>
      <button type="button" data-an="clear" title="Clear this page" aria-label="Clear this page">${svg("clear")}</button>
    </div>
    <span class="an-saved" aria-live="polite"></span>
    <input type="file" accept="image/*" data-file hidden>`;
  mount.appendChild(bar);

  const fly = document.createElement("div");
  fly.className = "ink-fly";
  fly.hidden = true;
  fly.setAttribute("role", "dialog");
  mount.appendChild(fly);

  const tab = document.createElement("button");
  tab.type = "button";
  tab.className = "an-tab";
  tab.title = "Annotate — pens, shapes, stickers, ruler, compass";
  tab.setAttribute("aria-label", "Show annotation tools");
  tab.innerHTML = `${svg("pen")}<span>Ink</span>`;
  mount.appendChild(tab);

  function persist() {
    try {
      localStorage.setItem(PREF, JSON.stringify({ color: A.color, size: A.size, v: 3, erase: A.eraseMode,
        esize: A.eraseSize, pen: A.pen, shape: A.shape, dash: A.dash, fill: A.fill, recog: A.recog,
        straight: A.straight, quick: A.quick, sticker: A.sticker, pin: A.pinned }));
    } catch { /* ignore */ }
  }

  // colour picker (one instance, lives in the flyout while it is open)
  let qcSlot = null;                       // replacing quick colour slot i
  const cp = colorPanel({ palette: PALETTE, ink, alpha: true, onPick: (c, final) => {
    if (qcSlot != null) {
      A.quick[qcSlot] = c;
      if (final) persist();
    }
    pickColor(c, final);
  } });

  function paintBar() {
    bar.querySelectorAll("[data-tool]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.tool === A.tool)));
    const sb = bar.querySelector("[data-shape-btn] svg");
    if (sb) sb.innerHTML = ICON[A.shape] || ICON.rect;
    bar.querySelector("[data-tool=pen] svg").innerHTML = ICON[A.pen || "pen"];
    const cur = selected()?.c || A.color;
    bar.querySelectorAll("[data-qc]").forEach((b) => {
      const c = A.quick[+b.dataset.qc];
      b.querySelector("i").style.background = ink(c);
      b.classList.toggle("is-on", c === A.color);
    });
    const allc = bar.querySelector(".ink-allc i");
    allc.style.setProperty("--c", ink(cur));
    bar.querySelector(".ink-allc").classList.toggle("is-on", !A.quick.includes(A.color));
    const sz = bar.querySelector(".ink-size i");
    sz.style.setProperty("--d", `${4 + A.size * 3}px`);
    sz.style.background = ink(A.color);
    bar.dataset.paper = dark() ? "dark" : "light";
    fly.dataset.paper = bar.dataset.paper;
    bar.querySelector('[data-an="undo"]').disabled = !A.undo.length;
    bar.querySelector('[data-an="redo"]').disabled = !A.redo.length;
    bar.querySelector('[data-an="delete"]').hidden = !(A.sel || A.msel);
    const pin = bar.querySelector('[data-an="pin"]');
    pin.innerHTML = svg(A.pinned ? "pinned" : "pin");
    pin.setAttribute("aria-pressed", String(A.pinned));
    pin.title = A.pinned ? "Unpin — tuck the tools away" : "Pin the tools open";
    pin.setAttribute("aria-label", pin.title);
    placeTextBar();
    const drawing = DRAWS.has(A.tool);
    document.documentElement.classList.toggle("an-drawing", drawing);
    document.documentElement.dataset.anTool = A.tool;
    for (const p of A.pages.values()) paintLayer(p);
    if (!fly.hidden) paintFly();
    A.listeners.forEach((fn) => fn(A.tool));
  }

  function setTool(t) {
    if (LEGACY_TOOL[t]) { A.shape = LEGACY_TOOL[t]; t = "shape"; }
    closeEditor(true);
    closeNote(true);
    if (t !== "select" && t !== "lasso" && !(t === "text" && selected()?.t === "text")) { A.sel = null; A.msel = null; }
    A.tool = t;
    paintBar();
  }

  // ── open / pin ─────────────────────────────────────────────────────────────
  function layout() {
    const shown = A.visible !== false;
    bar.hidden = !shown || !A.open;
    tab.hidden = !shown || A.open;
    bar.classList.toggle("is-pinned", A.pinned);
    const pushNow = push && !scratch && shown && A.pinned && A.open && window.innerWidth >= 1100;
    if (document.body.classList.contains("ink-pinned") !== pushNow) {
      document.body.classList.toggle("ink-pinned", pushNow);
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }
    if (bar.hidden) closeFly();
  }
  function setOpen(v) {
    A.open = v;
    A.collapsed = !v;
    if (!v && !A.pinned) setTool("pointer");
    layout();
  }
  tab.addEventListener("click", () => setOpen(true));
  // Unpinned: a click on the page (not while drawing) tucks the rail away.
  document.addEventListener("pointerdown", (e) => {
    if (A.pinned || !A.open || bar.contains(e.target) || fly.contains(e.target) || tab.contains(e.target)) return;
    if (e.target.closest?.(".an-layer.is-active, .an-tb, .an-textwrap, .an-inst, .an-note-ed")) return;
    setOpen(false);
  });
  window.addEventListener("resize", () => layout());

  // ── flyouts ────────────────────────────────────────────────────────────────
  let flyKind = null, flyAnchor = null;
  function closeFly() {
    fly.hidden = true;
    flyKind = null;
    qcSlot = null;
    bar.querySelectorAll("[aria-expanded]").forEach((b) => b.setAttribute("aria-expanded", "false"));
    bar.querySelectorAll(".is-flying").forEach((b) => b.classList.remove("is-flying"));
  }
  function openFly(kind, anchor, slot = null) {
    if (flyKind === kind && flyAnchor === anchor && !fly.hidden) return closeFly();
    closeFly();
    qcSlot = slot;
    flyKind = kind;
    flyAnchor = anchor;
    anchor.classList.add("is-flying");
    if (anchor.hasAttribute("aria-expanded")) anchor.setAttribute("aria-expanded", "true");
    fly.dataset.kind = kind;
    fly.hidden = false;
    fly.innerHTML = "";
    if (kind === "colors") {
      fly.appendChild(cp.el);
      cp.set(qcSlot != null ? A.quick[qcSlot] : (selected()?.c || A.color));
      cp.el.querySelector(".ink-fly-head").textContent = qcSlot != null ? `Quick colour ${qcSlot + 1}` : "Colour";
    } else fly.innerHTML = flyHTML(kind);
    paintFly();
    placeFly();
    if (kind === "stickers") loadStickers(INK_V).then(() => { if (flyKind === "stickers") { fly.innerHTML = flyHTML(kind); paintFly(); placeFly(); } });
  }
  function placeFly() {
    if (fly.hidden || !flyAnchor) return;
    const r = flyAnchor.getBoundingClientRect(), rb = bar.getBoundingClientRect();
    const fh = fly.offsetHeight, vh = window.innerHeight;
    fly.style.left = `${Math.round(rb.right + 8)}px`;
    fly.style.top = `${Math.round(Math.max(8, Math.min(vh - fh - 8, r.top + r.height / 2 - 28)))}px`;
  }
  const sizeRow = (label = "Thickness") => `<p class="ink-fly-head">${label}</p><div class="ink-sizes" role="radiogroup">${SIZES.map((_, i) =>
    `<button type="button" role="radio" data-size="${i}" aria-label="Size ${i + 1}" aria-checked="false"><i style="--d:${3 + i * 3.5}px"></i></button>`).join("")}</div>`;
  const toggle = (k, label, hint = "") => `<label class="ink-toggle"><input type="checkbox" data-opt="${k}">
    <span class="ink-sw" aria-hidden="true"></span><span><b>${label}</b>${hint ? `<small>${hint}</small>` : ""}</span></label>`;
  function flyHTML(kind) {
    if (kind === "pen") {
      return `<p class="ink-fly-head">Pen type</p><div class="ink-pens">${PENS.map(([k, ic, n, h]) =>
        `<button type="button" data-pen="${k}" title="${h}" aria-pressed="false">${svg(ic)}<span>${n}</span></button>`).join("")}</div>
        ${sizeRow()}${toggle("recog", "Shape snap", "Draw a shape and hold still - it turns neat")}`;
    }
    if (kind === "marker") return `${sizeRow()}${toggle("straight", "Straight lines", "Or hold Shift while highlighting")}`;
    if (kind === "eraser") {
      return `<p class="ink-fly-head">Eraser</p>
        <div class="an-seg" role="radiogroup" aria-label="Eraser type">
          <button type="button" role="radio" data-erase="partial" aria-checked="true" title="Rub out just the part you touch">Partial</button>
          <button type="button" role="radio" data-erase="stroke" aria-checked="false" title="Remove a whole stroke, shape or text box">Whole object</button>
        </div>
        <p class="ink-fly-head">Size</p>
        <div class="an-esizes" role="radiogroup" aria-label="Eraser size">${ERASER_R.map((_, i) => `
          <button type="button" role="radio" data-esize="${i}" aria-checked="false"
            title="${["Small", "Medium", "Large"][i]} eraser" aria-label="${["Small", "Medium", "Large"][i]} eraser"><i style="--d:${6 + i * 5}px"></i></button>`).join("")}
        </div>`;
    }
    if (kind === "shapes") {
      return `<p class="ink-fly-head">Shapes</p><div class="ink-shapes">${SHAPE_LIST.map(([k, n]) =>
        `<button type="button" data-shape="${k}" title="${n}" aria-label="${n}" aria-pressed="false">${svg(k)}</button>`).join("")}</div>
        ${toggle("dash", "Dashed outline")}${toggle("fill", "Filled", "A light tint of the colour")}${sizeRow("Outline")}`;
    }
    if (kind === "sizes") return sizeRow();
    if (kind === "note") {
      return `<p class="ink-fly-head">Sticky note colour</p><div class="ink-notec">${NOTE_COLORS.map((c) =>
        `<button type="button" data-notec="${c}" aria-label="${PAL[c.slice(1)].n} note" title="${PAL[c.slice(1)].n}"></button>`).join("")}</div>
        <p class="ink-fly-hint">Tap the page to stick a note, or drag to size it. Double-click a note to write on it.</p>`;
    }
    if (kind === "stickers") {
      const lib = stickerLib();
      const cat = A.stickerCat || "stamps";
      const items = Object.entries(lib).filter(([, s]) => s.cat === cat);
      return `<div class="ink-stk-tabs" role="tablist">${stickerCats().map(([k, n]) =>
        `<button type="button" role="tab" data-stkcat="${k}" aria-selected="${k === cat}">${n}</button>`).join("")}</div>
        <div class="ink-stk-grid${cat === "stamps" ? " is-stamps" : ""}">${items.length ? items.map(([k, s]) =>
          `<button type="button" data-stk="${k}" title="${s.name}" aria-label="${s.name}" aria-pressed="false">
            <img alt="" src="${stickerSrc(k)}" draggable="false"></button>`).join("") : '<p class="ink-fly-hint">Loading…</p>'}</div>
        <p class="ink-fly-hint">Pick one, then tap the page (drag to make it bigger).</p>`;
    }
    return "";
  }
  function paintFly() {
    fly.querySelectorAll("[data-size]").forEach((b) => b.setAttribute("aria-checked", String(+b.dataset.size === A.size)));
    fly.querySelectorAll("[data-size] i").forEach((i) => { i.style.background = ink(A.color); });
    fly.querySelectorAll("[data-pen]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pen === A.pen)));
    fly.querySelectorAll("[data-shape]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.shape === A.shape)));
    fly.querySelectorAll("[data-erase]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.erase === A.eraseMode)));
    fly.querySelectorAll("[data-esize]").forEach((b) => b.setAttribute("aria-checked", String(+b.dataset.esize === A.eraseSize)));
    fly.querySelectorAll("[data-opt]").forEach((x) => { x.checked = !!A[x.dataset.opt]; });
    fly.querySelectorAll("[data-stk]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.stk === A.sticker)));
    fly.querySelectorAll("[data-notec]").forEach((b) => {
      b.style.setProperty("--c", noteFill(b.dataset.notec));
      b.classList.toggle("is-on", b.dataset.notec === (A.noteColor || "@yellow"));
    });
    if (flyKind === "colors") cp.repaint();
  }
  fly.addEventListener("click", (e) => {
    const t = e.target;
    const sz = t.closest("[data-size]");
    if (sz) {
      A.size = +sz.dataset.size; persist();
      applyToSelection((o) => resized(o, A.size));
      return paintBar();
    }
    const pn = t.closest("[data-pen]");
    if (pn) { A.pen = pn.dataset.pen; A.tool = "pen"; persist(); return paintBar(); }
    const sh = t.closest("[data-shape]");
    if (sh) { A.shape = sh.dataset.shape; persist(); setTool("shape"); return closeFly(); }
    const er = t.closest("[data-erase]");
    if (er) { A.eraseMode = er.dataset.erase; persist(); return paintBar(); }
    const es = t.closest("[data-esize]");
    if (es) { A.eraseSize = +es.dataset.esize; persist(); return paintBar(); }
    const sc = t.closest("[data-stkcat]");
    if (sc) { A.stickerCat = sc.dataset.stkcat; fly.innerHTML = flyHTML("stickers"); paintFly(); return placeFly(); }
    const sk = t.closest("[data-stk]");
    if (sk) { A.sticker = sk.dataset.stk; persist(); setTool("sticker"); return closeFly(); }
    const nc = t.closest("[data-notec]");
    if (nc) {
      A.noteColor = nc.dataset.notec;
      const o = selected();
      if (o?.t === "note") mutate(A.sel.key, (list) => { list[A.sel.i] = { ...o, bg: A.noteColor }; });
      setTool("note");
      return closeFly();
    }
  });
  fly.addEventListener("change", (e) => {
    const o = e.target.closest("[data-opt]");
    if (!o) return;
    A[o.dataset.opt] = o.checked; persist();
    if (o.dataset.opt === "dash" || o.dataset.opt === "fill") {
      applyToSelection((x) => {
        if (!(x.t === "line" || x.t === "arrow" || x.t === "rect" || x.t === "ellipse" || x.t === "poly" || x.t === "arc")) return x;
        const y = { ...x };
        if (o.dataset.opt === "dash") { if (o.checked) y.d = 1; else delete y.d; }
        if (o.dataset.opt === "fill" && x.t !== "line" && x.t !== "arrow" && x.t !== "arc") { if (o.checked) y.fl = x.c || A.color; else delete y.fl; }
        return y;
      });
    }
    paintBar();
  });
  fly.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") closeFly(); });
  document.addEventListener("pointerdown", (e) => {
    if (!fly.hidden && !fly.contains(e.target) && !bar.contains(e.target)) closeFly();
  }, true);
  window.addEventListener("resize", placeFly);

  function pickColor(c, final = true) {
    A.color = c;
    if (final) { persist(); if (c[0] === "#") rememberColor(c); }
    if (TX.ed) { setTextStyle({ c }); return paintBar(); }
    if (NOTE.ed) { NOTE.ed.s.bg = c; styleNote(); return; }
    if (A.sel || A.msel) {
      applyToSelection((o) => (o.t === "img" || o.t === "stk") ? o
        : o.t === "note" ? { ...o, bg: c }
        : { ...o, c, ...(o.fl ? { fl: c } : {}) }, !final);
      return paintBar();
    }
    if (!DRAWS.has(A.tool) || ["eraser", "select", "lasso", "sticker", "laser"].includes(A.tool)) A.tool = "pen";
    return paintBar();
  }

  // Paper (or, for scratch ink, site) theme changed: repaint with the other shades.
  new MutationObserver(() => paintBar()).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-paper", "data-theme"] });

  let pressT = null;
  bar.addEventListener("pointerdown", (e) => {
    // hold a tool / quick colour = its options
    const b = e.target.closest("[data-has-fly], [data-qc]");
    if (!b) return;
    clearTimeout(pressT);
    pressT = setTimeout(() => { pressT = "fired"; openFor(b); }, 480);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) =>
    bar.addEventListener(ev, () => { if (pressT !== "fired") clearTimeout(pressT); }));
  bar.addEventListener("contextmenu", (e) => {
    const b = e.target.closest("[data-has-fly], [data-qc]");
    if (!b) return;
    e.preventDefault();
    openFor(b);
  });
  function openFor(b) {
    if (b.dataset.qc != null) return openFly("colors", b, +b.dataset.qc);
    if (b.dataset.tool && A.tool !== b.dataset.tool) setTool(b.dataset.tool);
    openFly(b.dataset.hasFly, b);
  }

  bar.addEventListener("click", (e) => {
    if (pressT === "fired") { pressT = null; return; }          // the press opened a flyout
    const inst = e.target.closest("[data-inst]");
    if (inst) return toggleInstrument(inst.dataset.inst);
    const qc = e.target.closest("[data-qc]");
    if (qc) { closeFly(); return pickColor(A.quick[+qc.dataset.qc]); }
    const fb = e.target.closest("[data-fly]");
    if (fb) return openFly(fb.dataset.fly, fb);
    const t = e.target.closest("[data-tool]");
    if (t) {
      const k = t.dataset.tool;
      if (A.tool === k && t.dataset.hasFly) return openFly(t.dataset.hasFly, t);
      closeFly();
      if (k === "sticker" && !stickerLib()[A.sticker]) { setTool(k); return openFly("stickers", t); }
      return setTool(A.tool === k && k !== "pointer" ? "pointer" : k);
    }
    const act = e.target.closest("[data-an]")?.dataset.an;
    if (act === "undo") doUndo();
    else if (act === "redo") doRedo();
    else if (act === "clear") clearPage();
    else if (act === "delete") deleteSelected();
    else if (act === "image") bar.querySelector("[data-file]").click();
    else if (act === "pin") {
      A.pinned = !A.pinned; persist();
      if (!A.pinned && narrow()) setOpen(false);
      paintBar(); layout();
    }
  });
  bar.querySelector("[data-file]").addEventListener("change", (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) insertImage(f);
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches?.("input, textarea, select, [contenteditable]")) return;
    if (e.target.closest?.(".pwt-dock, .an-tb, .ink-fly")) return;     // the calculator etc. have their own keys
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      if (A.undo.length) { e.preventDefault(); doUndo(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) {
      if (A.redo.length) { e.preventDefault(); doRedo(); }
      return;
    }
    if ((A.sel || A.msel) && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); deleteSelected(); return; }
    if (objectKeys(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey || !A.open) return;
    const k = { v: "pointer", s: "select", l: "lasso", p: "pen", h: "marker", e: "eraser", t: "text",
                n: "note", k: "laser" }[e.key.toLowerCase()];
    if (k && A.hotkeys !== false) setTool(k);
    if (e.key === "Escape") {
      if (!fly.hidden) closeFly();
      else if (A.sel || A.msel) { A.sel = null; A.msel = null; paintBar(); }
      else if (A.tool !== "pointer") setTool("pointer");
    }
  });

  // ── pages ──────────────────────────────────────────────────────────────────
  function load(doc) {
    if (!saveInk) return Promise.resolve({});
    if (!A.docs.has(doc)) {
      A.docs.set(doc, Promise.resolve(store.load(doc)).catch(() => ({})));
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

  const withIds = (list) => list.map((s) => (s && typeof s === "object" && !s.id ? { ...s, id: uid() } : s))
    .filter((s) => s && typeof s === "object" && typeof s.t === "string");

  async function attach(el, doc, page, opts = {}) {
    const key = `${doc}|${page}`;
    const prev = A.pages.get(key);
    if (TX.ed?.p.key === key) closeEditor(true);       // zoom / re-layout: finish the edit first
    if (NOTE.ed?.p.key === key) closeNote(true);
    if (prev && prev.el !== el) near.unobserve(prev.el);
    const canvas = document.createElement("canvas");
    canvas.className = "an-layer";
    el.appendChild(canvas);
    const p = { el, canvas, doc, page, key, strokes: prev ? prev.strokes : (opts.strokes ? withIds(opts.strokes) : null),
                near: false, cam: opts.camera ? (prev?.cam || { x: 0, y: 0, z: 1 }) : null };
    A.pages.set(key, p);
    byEl.set(el, p);
    near.observe(el);
    bind(p);
    // zoom / refit rebuilt this page: keep any ruler, protractor or compass on it
    for (const it of Object.values(INST)) {
      if (it && it.p.key === key && it.p !== p) {
        it.p = p;
        el.appendChild(it.el);
        if (it.kind !== "compass") requestAnimationFrame(() => renderInst(it));     // true scale at the new zoom
      }
    }
    if (!p.strokes) {
      const pages = await load(doc);
      if (A.pages.get(key) !== p) return p;         // re-attached meanwhile
      p.strokes = withIds(pages[String(page)] || []);
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
    // Camera (infinite whiteboard): world units, BASE px each at 100 %.
    const cw = p.el.clientWidth, ch = p.el.clientHeight;
    let w = cw, h = p.view ? cw : ch, ox = p.view ? window.scrollX : 0, oy = p.view ? window.scrollY : 0;
    if (p.cam) { w = h = BASE * p.cam.z; ox = p.cam.x * w; oy = p.cam.y * w; }
    const on = p.view || p.cam || (p.near && (p.strokes?.length || p.live || p.drag || p.eraserAt || p.lasso || p.laser));
    const tw = on ? Math.round(cw * dpr) : 0, th = on ? Math.round(ch * dpr) : 0;
    let changed = false;
    if (p.canvas.width !== tw || p.canvas.height !== th) {
      p.canvas.width = tw;
      p.canvas.height = th;
      changed = true;
    }
    return { w, h, dpr, changed, ox, oy };
  }

  /** Page fractions -> where things go in px: the host element and the offset
   *  to take off (camera pages are scrolled by the camera). */
  function local(p) {
    const { w, h, ox, oy } = size(p);
    return { w, h, dx: p.cam ? ox : 0, dy: p.cam ? oy : 0, host: p.view ? document.body : p.el };
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
    const vis = p.cam ? [ox / w, oy / h, (ox + p.el.clientWidth) / w, (oy + p.el.clientHeight) / h] : null;
    p.strokes.forEach((s, i) => {
      if (i === p.hideIndex) return;
      if (vis) {                                   // infinite canvas: skip what is off screen
        const bb = bbox(s, w, h);
        if (bb[2] < vis[0] || bb[0] > vis[2] || bb[3] < vis[1] || bb[1] > vis[3]) return;
      }
      draw(b, s, w, h, p);
    });
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
    if (p.live) draw(ctx, p.live, w, h, p);
    if (A.sel?.key === p.key && p.strokes[A.sel.i] && p.hideIndex !== A.sel.i) drawSelection(ctx, p.strokes[A.sel.i], w, h);
    if (A.msel?.key === p.key) drawMulti(ctx, p, w, h);
    if (p.lasso?.length > 1) {
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = "#7c5cf0";
      ctx.fillStyle = "rgba(124, 92, 240, .07)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      p.lasso.forEach((q, i) => (i ? ctx.lineTo(q[0] * w, q[1] * h) : ctx.moveTo(q[0] * w, q[1] * h)));
      ctx.closePath();
      ctx.fill(); ctx.stroke();
      ctx.restore();
    }
    if (p.laser?.length) drawLaser(ctx, p, w, h);
    if (p.snapAt) {
      ctx.save();
      ctx.strokeStyle = "#e11d48"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(p.snapAt[0] * w, p.snapAt[1] * h, 7, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }
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
    const lines = wrapLines(String(s.txt || ""), max);
    const widths = lines.map((l) => measure.measureText(l).width);
    const m = measure.measureText("Hg");
    const asc = m.fontBoundingBoxAscent ?? fs * 0.8, desc = m.fontBoundingBoxDescent ?? fs * 0.2;
    const lh = fs * LH;
    return { lines, widths, fs, font, lh, boxW: s.bw ? s.bw * w : Math.max(0, ...widths),
             boxH: lines.length * lh, pad: s.bg || s.bd ? Math.round(fs * 0.35) : 0,
             // baseline inside a line box, exactly where CSS puts it in the editing box
             base: (lh - (asc + desc)) / 2 + asc };
  }

  /** Word-wrap with the font already set on `measure`. */
  function wrapLines(txt, max) {
    const lines = [];
    for (const para of txt.split("\n")) {
      if (max === Infinity) { lines.push(para); continue; }
      let line = "";
      for (const word of para.split(/(?<=\s)/)) {
        if (line && measure.measureText((line + word).trimEnd()).width > max) { lines.push(line.trimEnd()); line = word; }
        else line += word;
      }
      lines.push(line);
    }
    return lines;
  }

  const fillColour = (bg) => (bg === "paper" ? (dark() ? "#0e0e0e" : "#ffffff") : ink(bg));
  /** Sticky-note paper: the pastel shade of an ink token (or a light tint of a hex colour). */
  const noteFill = (bg) => {
    bg ||= "@yellow";
    const tok = bg[0] === "@" ? PAL[bg.slice(1)] : null;
    const hex = tok ? tok.d : /^#[0-9a-f]{6}/i.test(bg) ? bg.slice(0, 7) : "#fde68a";
    if (dark()) return mixHex(hex, "#262b38", 0.55);
    return tok ? mixHex(hex, "#ffffff", 0.35) : mixHex(hex, "#ffffff", 0.7);
  };

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

  /** Sticky note: a square of coloured paper with handwriting on it. */
  function noteLayout(s, w, h) {
    const x = Math.min(s.a[0], s.b[0]) * w, y = Math.min(s.a[1], s.b[1]) * h;
    const bw = Math.abs(s.b[0] - s.a[0]) * w, bh = Math.abs(s.b[1] - s.a[1]) * h;
    const fs = Math.max(6, (s.fs || 0.075) * Math.min(bw, bh * 1.2));
    const pad = Math.max(4, bw * 0.08);
    return { x, y, bw, bh, fs, pad, font: `400 ${fs}px ${FONTS.hand[1]}` };
  }
  function drawNote(ctx, s, w, h) {
    const L = noteLayout(s, w, h);
    const fold = Math.min(L.bw, L.bh) * 0.14;
    ctx.save();
    ctx.shadowColor = "rgba(20, 20, 40, .18)";
    ctx.shadowBlur = Math.max(2, L.bw * 0.04);
    ctx.shadowOffsetY = Math.max(1, L.bw * 0.015);
    ctx.fillStyle = noteFill(s.bg);
    ctx.beginPath();
    ctx.moveTo(L.x, L.y); ctx.lineTo(L.x + L.bw, L.y); ctx.lineTo(L.x + L.bw, L.y + L.bh - fold);
    ctx.lineTo(L.x + L.bw - fold, L.y + L.bh); ctx.lineTo(L.x, L.y + L.bh); ctx.closePath();
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = "rgba(0, 0, 0, .12)";
    ctx.beginPath();
    ctx.moveTo(L.x + L.bw, L.y + L.bh - fold); ctx.lineTo(L.x + L.bw - fold, L.y + L.bh - fold);
    ctx.lineTo(L.x + L.bw - fold, L.y + L.bh); ctx.closePath(); ctx.fill();
    if (!s.txt) return;
    ctx.fillStyle = dark() ? "#f3f4f6" : "#1f2937";
    ctx.font = L.font;
    measure.font = L.font;
    ctx.textBaseline = "top";
    const lines = wrapLines(s.txt, L.bw - 2 * L.pad);
    const lh = L.fs * 1.3;
    ctx.save();
    ctx.beginPath(); ctx.rect(L.x, L.y, L.bw, L.bh); ctx.clip();
    lines.forEach((ln, i) => ctx.fillText(ln, L.x + L.pad, L.y + L.pad + i * lh));
    ctx.restore();
  }

  // images (pasted / uploaded) - one decoded <img> per src, repaint when it arrives
  const IMGS = new Map();
  function imageFor(src) {
    let im = IMGS.get(src);
    if (!im) {
      im = new Image();
      im.decoding = "async";
      im.onload = () => { for (const p of A.pages.values()) if (p.strokes?.some((s) => s.src === src)) schedule(p, true); };
      im.src = src;
      IMGS.set(src, im);
    }
    return im.complete && im.naturalWidth ? im : null;
  }
  const repaintAll = () => { for (const p of A.pages.values()) schedule(p, true); };

  /** The object at picker size i: strokes and shapes get that width. */
  function resized(o, i) {
    if (WHOLE.has(o.t)) return o;
    return o.w != null ? { ...o, w: SIZES[i] } : o;
  }

  /** Smooth path through freehand points (quadratic curves through the midpoints). */
  function smooth(ctx, pts, w, h) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0] * w, pts[0][1] * h);
    for (let i = 1; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      ctx.quadraticCurveTo(a[0] * w, a[1] * h, (a[0] + b[0]) / 2 * w, (a[1] + b[1]) / 2 * h);
    }
    const z = pts[pts.length - 1];
    ctx.lineTo(z[0] * w, z[1] * h);
  }

  function arrowHead(ctx, x0, y0, x1, y1, lw) {
    const ang = Math.atan2(y1 - y0, x1 - x0), L = Math.max(10, lw * 4);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x1 - L * Math.cos(ang - 0.45), y1 - L * Math.sin(ang - 0.45));
    ctx.lineTo(x1 - L * Math.cos(ang + 0.45), y1 - L * Math.sin(ang + 0.45));
    ctx.closePath();
    ctx.fill();
  }

  /** Fill (a light tint) then stroke the current path. */
  function finish(ctx, s) {
    if (s.fl) {
      ctx.save();
      ctx.setLineDash([]);
      ctx.globalAlpha = dark() ? 0.3 : 0.22;
      ctx.fillStyle = ink(s.fl);
      ctx.fill();
      ctx.restore();
    }
    ctx.stroke();
  }

  function draw(ctx, s, w, h) {
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = ink(s.c);
    ctx.fillStyle = ink(s.c);
    const lw = Math.max(1, (s.w || SIZES[2]) * w);
    if (s.d || s.k === "dash") ctx.setLineDash([lw * 2.6 + 2, lw * 2 + 3]);
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
      } else if (pts.length > 1 && (s.k === "fine" || s.k === "dash")) {
        ctx.lineWidth = lw;
        smooth(ctx, pts, w, h);
        ctx.stroke();
      } else if (pts.length > 1 && s.k === "pencil") {
        // graphite: a soft core plus a fainter, slightly offset second pass
        ctx.globalAlpha = 0.78;
        ctx.lineWidth = lw * 0.85;
        smooth(ctx, pts, w, h);
        ctx.stroke();
        ctx.globalAlpha = 0.22;
        ctx.lineWidth = lw * 1.5;
        ctx.translate(lw * 0.18, lw * 0.12);
        smooth(ctx, pts, w, h);
        ctx.stroke();
      } else {
        // Quadratic curves through the midpoints: smooth, and each segment's
        // width follows the pen pressure (or, for the fountain pen, the angle).
        for (let i = 1; i < pts.length; i++) {
          const a = pts[i - 1], b = pts[i];
          const prev = pts[i - 2] || a;
          const m0 = [(prev[0] + a[0]) / 2 * w, (prev[1] + a[1]) / 2 * h];
          const m1 = [(a[0] + b[0]) / 2 * w, (a[1] + b[1]) / 2 * h];
          ctx.beginPath();
          if (s.k === "fountain") {
            const th = Math.atan2((b[1] - a[1]) * h, (b[0] - a[0]) * w);
            ctx.lineWidth = lw * (0.35 + 1.4 * Math.abs(Math.sin(th - Math.PI / 4)));
          } else ctx.lineWidth = lw * (0.55 + 0.9 * (a[2] ?? 0.5));
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
        ctx.setLineDash([]);
        arrowHead(ctx, x0, y0, x1, y1, lw);
        if (s.two) arrowHead(ctx, x1, y1, x0, y0, lw);
      }
    } else if (s.t === "rect" || s.t === "ellipse") {
      const x = Math.min(s.a[0], s.b[0]) * w, y = Math.min(s.a[1], s.b[1]) * h;
      const rw = Math.abs(s.b[0] - s.a[0]) * w, rh = Math.abs(s.b[1] - s.a[1]) * h;
      ctx.lineWidth = lw;
      ctx.beginPath();
      if (s.t === "rect" && s.rr && ctx.roundRect) ctx.roundRect(x, y, rw, rh, Math.min(rw, rh) * 0.2);
      else if (s.t === "rect") ctx.rect(x, y, rw, rh);
      else ctx.ellipse(x + rw / 2, y + rh / 2, rw / 2, rh / 2, 0, 0, Math.PI * 2);
      finish(ctx, s);
    } else if (s.t === "poly") {
      const c = polyCorners(s);
      ctx.lineWidth = lw;
      ctx.beginPath();
      c.forEach((q, i) => (i ? ctx.lineTo(q[0] * w, q[1] * h) : ctx.moveTo(q[0] * w, q[1] * h)));
      ctx.closePath();
      finish(ctx, s);
    } else if (s.t === "arc") {
      ctx.lineWidth = lw;
      ctx.beginPath();
      const full = Math.abs(s.sw) >= Math.PI * 2 - 1e-3;
      ctx.arc(s.o[0] * w, s.o[1] * h, s.r * w, full ? 0 : s.a0, full ? Math.PI * 2 : s.a0 + s.sw, !full && s.sw < 0);
      ctx.stroke();
    } else if (s.t === "text") {
      drawText(ctx, s, w, h);
    } else if (s.t === "note") {
      drawNote(ctx, s, w, h);
    } else if (s.t === "img" || s.t === "stk") {
      const x = Math.min(s.a[0], s.b[0]) * w, y = Math.min(s.a[1], s.b[1]) * h;
      const rw = Math.abs(s.b[0] - s.a[0]) * w, rh = Math.abs(s.b[1] - s.a[1]) * h;
      const im = s.t === "img" ? imageFor(s.src) : stickerImage(s.k, repaintAll);
      if (im) ctx.drawImage(im, x, y, rw, rh);
      else {
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "rgba(124, 92, 240, .5)";
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, rw, rh);
      }
    }
    ctx.restore();
  }

  function drawLaser(ctx, p, w, h) {
    const now = performance.now();
    p.laser = p.laser.filter((q) => now - q[2] < 700);
    if (!p.laser.length) return;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let i = 1; i < p.laser.length; i++) {
      const a = p.laser[i - 1], b = p.laser[i], t = 1 - (now - b[2]) / 700;
      ctx.strokeStyle = `rgba(239, 68, 68, ${0.85 * t})`;
      ctx.shadowColor = "rgba(239, 68, 68, .9)";
      ctx.shadowBlur = 10;
      ctx.lineWidth = 2 + 4 * t;
      ctx.beginPath(); ctx.moveTo(a[0] * w, a[1] * h); ctx.lineTo(b[0] * w, b[1] * h); ctx.stroke();
    }
    const z = p.laser[p.laser.length - 1];
    ctx.fillStyle = "#ef4444";
    ctx.beginPath(); ctx.arc(z[0] * w, z[1] * h, 4.5, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    requestAnimationFrame(() => blit(p));
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
    if (s.t === "img" || s.t === "stk" || s.t === "note") {
      return [Math.min(s.a[0], s.b[0]), Math.min(s.a[1], s.b[1]), Math.max(s.a[0], s.b[0]), Math.max(s.a[1], s.b[1])];
    }
    const P = s.t === "arc" ? arcPoints(s, w, h) : s.t === "poly" ? polyCorners(s) : s.pts || [s.a, s.b];
    const xs = P.map((q) => q[0]), ys = P.map((q) => q[1]);
    const pad = (s.t === "marker" ? s.w * 1.6 : (s.w || 0) / 2);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad * (w / h), Math.max(...xs) + pad, Math.max(...ys) + pad * (w / h)];
  }

  const HANDLE = 10;                                   // px, the square resize handles
  const CURSOR = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize",
                   n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", a: "move", b: "move" };
  /** The selected object's handles in page px: text = 4 corners (scale) + the
   *  two sides (wrap width); boxes = 8 (stickers: 4 corners, they keep their
   *  shape); lines / arrows = ends. */
  function handles(s, w, h) {
    if (s.t === "line" || s.t === "arrow") return [["a", s.a[0] * w, s.a[1] * h], ["b", s.b[0] * w, s.b[1] * h]];
    if (s.t !== "text" && !isBox(s)) return [];
    const [x0, y0, x1, y1] = bbox(s, w, h);
    const X0 = x0 * w - 5, Y0 = y0 * h - 5, X1 = x1 * w + 5, Y1 = y1 * h + 5, XM = (X0 + X1) / 2, YM = (Y0 + Y1) / 2;
    const corners = [["nw", X0, Y0], ["ne", X1, Y0], ["sw", X0, Y1], ["se", X1, Y1]];
    if (s.t === "stk") return corners;
    const out = [...corners, ["w", X0, YM], ["e", X1, YM]];
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

  function unionBox(p, idx, w, h) {
    let b = null;
    for (const i of idx) {
      const s = p.strokes[i];
      if (!s) continue;
      const q = bbox(s, w, h);
      b = b ? [Math.min(b[0], q[0]), Math.min(b[1], q[1]), Math.max(b[2], q[2]), Math.max(b[3], q[3])] : q;
    }
    return b;
  }
  function drawMulti(ctx, p, w, h) {
    ctx.save();
    ctx.strokeStyle = "rgba(124, 92, 240, .55)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    for (const i of A.msel.idx) {
      const s = p.strokes[i];
      if (!s) continue;
      const [x0, y0, x1, y1] = bbox(s, w, h);
      ctx.strokeRect(x0 * w - 2, y0 * h - 2, (x1 - x0) * w + 4, (y1 - y0) * h + 4);
    }
    const u = unionBox(p, A.msel.idx, w, h);
    if (u) {
      ctx.strokeStyle = "#7c5cf0";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(u[0] * w - 7, u[1] * h - 7, (u[2] - u[0]) * w + 14, (u[3] - u[1]) * h + 14);
    }
    ctx.restore();
  }

  function segDist(q, a, b, aspect = 1) {
    const dx = b[0] - a[0], dy = (b[1] - a[1]) * aspect;
    const qy = (q[1] - a[1]) * aspect, qx = q[0] - a[0];
    const t = Math.max(0, Math.min(1, (qx * dx + qy * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(qx - t * dx, qy - t * dy);
  }

  const inBox = (q, b, m = 0) => q[0] > b[0] - m && q[0] < b[2] + m && q[1] > b[1] - m && q[1] < b[3] + m;

  /** Does point q (page fractions) touch object s, within radius r (fraction of width)? */
  function hit(s, q, r, w, h) {
    const k = h / w;                                  // compare distances in width units
    if (s.pts) return s.pts.some((a, i) => segDist(q, a, s.pts[i + 1] || a, k) < r + (s.w || 0) * (s.t === "marker" ? 1.6 : 0.5));
    if (s.t === "text" || s.t === "img" || s.t === "stk" || s.t === "note") {
      const [x0, y0, x1, y1] = bbox(s, w, h);
      return q[0] > x0 - r && q[0] < x1 + r && q[1] > y0 - r / k && q[1] < y1 + r / k;
    }
    if (s.t === "rect" || s.t === "ellipse" || s.t === "poly" || s.t === "arc") {
      return outline(s, 48, w, h).some((a, i, L) => i && segDist(q, L[i - 1], a, k) < r + s.w);
    }
    return segDist(q, s.a, s.b, k) < r + s.w;
  }

  /** For "select": anywhere inside a shape or text counts, not just its outline. */
  function grabs(s, q, w, h) {
    if (s.t === "text" || isBox(s) || (s.t === "poly")) return inBox(q, bbox(s, w, h), 0.008);
    return hit(s, q, 0.01, w, h);
  }

  /** A shape as points along its outline (for the partial eraser and hit tests). */
  function outline(s, n = 64, w = 1, h = 1) {
    const dense = (c) => {
      const out = [];
      for (let i = 1; i < c.length; i++) {
        const L = Math.max(2, Math.ceil(Math.hypot(c[i][0] - c[i - 1][0], c[i][1] - c[i - 1][1]) / 0.004));
        for (let j = i === 1 ? 0 : 1; j <= L; j++) {
          out.push([c[i - 1][0] + (c[i][0] - c[i - 1][0]) * j / L, c[i - 1][1] + (c[i][1] - c[i - 1][1]) * j / L, 0.5]);
        }
      }
      return out;
    };
    if (s.t === "line" || s.t === "arrow") return dense([s.a, s.b]);
    if (s.t === "arc") return arcPoints(s, w, h, 0.02);
    if (s.t === "poly") return dense(polyCorners(s));
    const x0 = Math.min(s.a[0], s.b[0]), x1 = Math.max(s.a[0], s.b[0]);
    const y0 = Math.min(s.a[1], s.b[1]), y1 = Math.max(s.a[1], s.b[1]);
    if (s.t === "rect") return dense([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]);
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = (x1 - x0) / 2, ry = (y1 - y0) / 2;
    return Array.from({ length: n + 1 }, (_, i) =>
      [cx + rx * Math.cos((i / n) * Math.PI * 2), cy + ry * Math.sin((i / n) * Math.PI * 2), 0.5]);
  }

  /** Move an object; normal pages keep it on the page, whole-page / camera layers don't. */
  function translate(s, dx, dy, p) {
    const fx = p?.cam ? (v) => v : clamp;
    const fy = p?.cam ? (v) => v : p?.view ? (v) => Math.max(0, v) : clamp;
    const mv = (q) => [fx(q[0] + dx), fy(q[1] + dy), ...q.slice(2)];
    if (s.pts) return { ...s, pts: s.pts.map(mv) };
    if (s.t === "text") return { ...s, x: fx(s.x + dx), y: fy(s.y + dy) };
    if (s.t === "arc") return { ...s, o: [s.o[0] + dx, s.o[1] + dy] };
    return { ...s, a: mv(s.a), b: mv(s.b) };
  }

  function pt(p, e) {
    const r = p.canvas.getBoundingClientRect();
    const pressure = e.pointerType === "pen" && e.pressure > 0 ? e.pressure : 0.5;
    if (p.cam) {
      const { w, ox, oy } = size(p);
      return [(e.clientX - r.left + ox) / w, (e.clientY - r.top + oy) / w, +pressure.toFixed(2)];
    }
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

  /** A live shape from the current shape tool, between a and b (Shift = square / 15°). */
  function liveShape(a, b, shift, w, h) {
    const base = { id: uid(), c: A.color, w: SIZES[A.size], ...(A.dash ? { d: 1 } : {}) };
    const k = A.shape;
    if (k === "line" || k === "arrow" || k === "arrow2") {
      if (shift) {
        const dx = (b[0] - a[0]) * w, dy = (b[1] - a[1]) * h;
        const ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 12)) * (Math.PI / 12), L = Math.hypot(dx, dy);
        b = [a[0] + (L * Math.cos(ang)) / w, a[1] + (L * Math.sin(ang)) / h];
      }
      return { ...base, t: k === "line" ? "line" : "arrow", ...(k === "arrow2" ? { two: 1 } : {}), a: a.slice(0, 2), b: b.slice(0, 2) };
    }
    if (shift || k === "circle") {                     // a square box in px
      const dx = (b[0] - a[0]) * w, dy = (b[1] - a[1]) * h, m = Math.max(Math.abs(dx), Math.abs(dy));
      b = [a[0] + (Math.sign(dx || 1) * m) / w, a[1] + (Math.sign(dy || 1) * m) / h];
    }
    const fill = A.fill ? { fl: A.color } : {};
    if (k === "rect" || k === "rrect") return { ...base, ...fill, t: "rect", ...(k === "rrect" ? { rr: 1 } : {}), a: a.slice(0, 2), b: b.slice(0, 2) };
    if (k === "ellipse" || k === "circle") return { ...base, ...fill, t: "ellipse", a: a.slice(0, 2), b: b.slice(0, 2) };
    return { ...base, ...fill, t: "poly", k, a: a.slice(0, 2), b: b.slice(0, 2) };
  }

  /** A box of the given px width at q, with the aspect ratio ar (= height / width). */
  function boxAt(q, wpx, ar, w, h, centre = true) {
    const bw = wpx / w, bh = (wpx * ar) / h;
    const x0 = centre ? q[0] - bw / 2 : q[0], y0 = centre ? q[1] - bh / 2 : q[1];
    return { a: [+x0.toFixed(4), +y0.toFixed(4)], b: [+(x0 + bw).toFixed(4), +(y0 + bh).toFixed(4)] };
  }
  const stickerAR = (k) => { const s = stickerLib()[k]; return s ? s.h / s.w : 1; };

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
      if (A.tool === "lasso") {
        if (A.msel?.key === p.key && inBox(q, unionBox(p, A.msel.idx, w, h) || [0, 0, 0, 0], 7 / w)) return startMultiDrag(p, q);
        clearSel();
        p.lasso = [q];
        return schedule(p);
      }
      if (A.tool === "laser") { p.laser = [[q[0], q[1], performance.now()]]; p.lasering = true; return schedule(p); }
      if (A.tool === "note") {
        const i = topmost(p, q, w, h, (x) => x.t === "note");
        if (i >= 0) {
          A.sel = { key: p.key, i };
          p.drag = { start: q, orig: p.strokes[i], before: p.strokes.slice(), moved: false, noteOnClick: true };
          return paintBar();
        }
        p.live = { id: uid(), t: "note", bg: A.noteColor || "@yellow", txt: "", a: q.slice(0, 2), b: q.slice(0, 2) };
        return schedule(p);
      }
      if (A.tool === "sticker") {
        p.live = { id: uid(), t: "stk", k: A.sticker, a: q.slice(0, 2), b: q.slice(0, 2) };
        return schedule(p);
      }
      const sw = SIZES[A.size];
      if (A.tool === "eraser") { p.erasing = { before: null }; p.eraserAt = q; eraseAt(p, q, w, h); }
      else if (A.tool === "pen" || A.tool === "marker") {
        const snap = edgeSnap(p, e);
        p.live = { id: uid(), t: A.tool, c: A.color, w: sw, pts: [snap ? snap.project(q) : q],
                   ...(A.tool === "pen" && A.pen ? { k: A.pen } : {}) };
        p.snap = snap;
        p.straight = A.tool === "marker" && (A.straight || e.shiftKey);
      }
      else if (A.tool === "shape") { p.shapeFrom = q; p.live = liveShape(q, q, e.shiftKey, w, h); }
      schedule(p);
    });
    c.addEventListener("pointermove", (e) => {
      if (p.pan && e.pointerId === p.pan.id) {
        if (p.cam && A.camPan) A.camPan(p, e.clientX - p.pan.x, e.clientY - p.pan.y);   // whiteboard camera
        else {
          p.pan.el.scrollTop -= e.clientY - p.pan.y;
          p.pan.el.scrollLeft -= e.clientX - p.pan.x;
        }
        p.pan.x = e.clientX; p.pan.y = e.clientY;
        return;
      }
      if (A.tool === "eraser" && DRAWS.has(A.tool) && !p.erasing) {   // show the eraser ring on hover
        p.eraserAt = pt(p, e);
        return schedule(p);
      }
      if (p.lasering) {
        const q = pt(p, e);
        p.laser.push([q[0], q[1], performance.now()]);
        return schedule(p);
      }
      if (!p.live && !p.erasing && !p.drag && !p.lasso) {
        if ((A.tool === "select" || A.tool === "text" || A.tool === "lasso") && p.strokes) {   // resize / move cursors
          const cur = A.sel?.key === p.key ? p.strokes[A.sel.i] : null;
          const { w, h } = size(p);
          const q = pt(p, e);
          const hd = cur && onHandle(cur, q, w, h);
          const inMulti = A.msel?.key === p.key && inBox(q, unionBox(p, A.msel.idx, w, h) || [0, 0, 0, 0], 7 / w);
          c.style.cursor = hd ? CURSOR[hd] : inMulti ? "move"
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
        else if (p.drag) moveSelect(p, q, ev);
        else if (p.lasso) p.lasso.push(q);
        else if (p.liveLocked) { /* snapped to a shape: wait for the pen to lift */ }
        else if (p.live.t === "stk" || p.live.t === "note") p.live.b = q.slice(0, 2);
        else if (p.live.pts) {
          if (p.straight) { p.live.pts = [p.live.pts[0], q]; continue; }
          const last = p.live.pts[p.live.pts.length - 1];
          const qq = p.snap ? p.snap.project(q) : q;
          if (Math.hypot(qq[0] - last[0], qq[1] - last[1]) > 0.0008) p.live.pts.push(qq);
        } else if (p.shapeFrom) p.live = { ...liveShape(p.shapeFrom, q, ev.shiftKey, w, h), id: p.live.id };
      }
      // shape snap: hold still at the end of a pen stroke
      if (p.live?.t === "pen" && A.recog && !p.snap && !p.liveLocked) {
        clearTimeout(p.holdT);
        p.holdT = setTimeout(() => {
          if (p.live?.t !== "pen" || p.liveLocked) return;
          const sz = size(p);
          const r = recognise(p.live, sz.w, sz.h);
          if (r) {
            p.live = { ...r, id: p.live.id, ...(A.dash ? { d: 1 } : {}) };
            p.liveLocked = true;
            flash("Shape snapped");
            schedule(p);
          }
        }, 550);
      }
      schedule(p, !!(p.erasing || p.drag));
    });
    c.addEventListener("pointerleave", () => { if (!p.erasing) { p.eraserAt = null; schedule(p); } });
    const end = (e) => {
      if (p.pan && e.pointerId === p.pan.id) { p.pan = null; return; }
      clearTimeout(p.holdT);
      if (p.lasering) { p.lasering = false; return schedule(p); }
      if (p.lasso) {
        const L = p.lasso;
        p.lasso = null;
        finishLasso(p, L);
      } else if (p.erasing) {
        if (p.erasing.before) commit(p, p.erasing.before);
        p.erasing = null;
      } else if (p.drag) {
        const d = p.drag;
        p.drag = null;
        if (d.moved) commit(p, d.before);
        else if (d.editOnClick && A.sel?.key === p.key) { paintLayer(p); return openEditor(p, A.sel.i); }
        else if (d.noteOnClick && A.sel?.key === p.key) { paintLayer(p); return openNote(p, A.sel.i); }
      } else if (p.live) {
        let s = p.live;
        const { w, h } = size(p);
        p.live = null;
        p.snap = null;
        p.liveLocked = false;
        p.shapeFrom = null;
        if (s.t === "stk" || s.t === "note") {
          const dx = Math.abs(s.b[0] - s.a[0]) * w;
          const ar = s.t === "stk" ? stickerAR(s.k) : 1;
          const wpx = dx < 12 ? (s.t === "stk" ? Math.min(w * 0.12, 140) * (ar < 0.6 ? 1.7 : 1) : Math.min(w * 0.2, 220)) : dx;
          const left = Math.min(s.a[0], s.b[0]), top = Math.min(s.a[1], s.b[1]);
          s = { ...s, ...boxAt(dx < 12 ? s.a : [left, top], wpx, ar, w, h, dx < 12) };
          const before = p.strokes.slice();
          p.strokes.push(s);
          A.sel = { key: p.key, i: p.strokes.length - 1 };
          commit(p, before);
          paintLayer(p);
          if (s.t === "note") openNote(p, p.strokes.length - 1);
          return;
        }
        const tiny = s.a && !s.pts && Math.hypot((s.b[0] - s.a[0]) * w, (s.b[1] - s.a[1]) * h) < 4;
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
      if (!["select", "text", "note", "lasso"].includes(A.tool)) return;
      const q = pt(p, e);
      const { w, h } = size(p);
      const i = topmost(p, q, w, h, (s) => s.t === "text" || s.t === "note");
      if (i < 0) return;
      if (p.strokes[i].t === "note") openNote(p, i); else openEditor(p, i);
    });
    // drop image files straight onto a page
    p.el.addEventListener("dragover", (e) => {
      if (A.visible === false || ![...(e.dataTransfer?.items || [])].some((it) => it.type.startsWith("image/"))) return;
      e.preventDefault();
    });
    p.el.addEventListener("drop", (e) => {
      const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("image/"));
      if (!f || A.visible === false) return;
      e.preventDefault();
      insertImage(f, p, pt(p, e));
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
  function clearSel() {
    const keys = [A.sel?.key, A.msel?.key].filter(Boolean);
    A.sel = null; A.msel = null;
    keys.forEach((k) => { const o = A.pages.get(k); if (o) blit(o); });
    paintBar();
  }
  /** Indices selected on the selection's page (one or several). */
  function selection() {
    if (A.msel) return { p: A.pages.get(A.msel.key), idx: A.msel.idx.slice() };
    if (A.sel) return { p: A.pages.get(A.sel.key), idx: [A.sel.i] };
    return null;
  }
  /** Change every selected object with fn (one undo step; live = repaint only). */
  function applyToSelection(fn, live = false) {
    const S = selection();
    if (!S?.p) return;
    const before = S.p.strokes.slice();
    let changed = false;
    for (const i of S.idx) {
      const o = S.p.strokes[i];
      if (!o) continue;
      const n = fn(o);
      if (n !== o) { S.p.strokes[i] = n; changed = true; }
    }
    if (!changed) return;
    if (live) { S.p.liveBefore ||= before; schedule(S.p, true); return; }
    commit(S.p, S.p.liveBefore || before);
    S.p.liveBefore = null;
    paintLayer(S.p);
  }

  function startSelect(p, q, w, h, e) {
    if (A.msel?.key === p.key && !e?.shiftKey && inBox(q, unionBox(p, A.msel.idx, w, h) || [0, 0, 0, 0], 7 / w)) {
      return startMultiDrag(p, q);
    }
    const cur = A.sel?.key === p.key ? p.strokes[A.sel.i] : null;
    const hd = cur && onHandle(cur, q, w, h);
    if (hd) {
      const b = bbox(cur, w, h);
      p.drag = { start: q, orig: cur, before: p.strokes.slice(), moved: false, handle: hd, w, h,
                 px: [b[0] * w, b[1] * h, b[2] * w, b[3] * h] };
      return;
    }
    const i = topmost(p, q, w, h);
    if (e?.shiftKey && i >= 0) {                        // Shift-click: add / remove from the selection
      const set = new Set(A.msel?.key === p.key ? A.msel.idx : A.sel?.key === p.key ? [A.sel.i] : []);
      if (set.has(i)) set.delete(i); else set.add(i);
      A.sel = null;
      A.msel = set.size > 1 ? { key: p.key, idx: [...set] } : null;
      if (set.size === 1) A.sel = { key: p.key, i: [...set][0] };
      paintBar();
      return;
    }
    const again = cur && i === A.sel.i;                 // a second press on the same object
    const prevKey = A.sel?.key || A.msel?.key;
    A.msel = null;
    A.sel = i >= 0 ? { key: p.key, i } : null;
    if (prevKey && prevKey !== p.key) { const o = A.pages.get(prevKey); if (o) blit(o); }
    if (i >= 0) {
      const s = p.strokes[i];
      // pressing an already selected text box / note and letting go = edit it
      p.drag = { start: q, orig: s, before: p.strokes.slice(), moved: false,
                 editOnClick: again && s.t === "text", noteOnClick: again && s.t === "note" };
      if (s.c) { A.color = LEGACY[s.c.toLowerCase()] || s.c; }
    }
    paintBar();
  }

  function startMultiDrag(p, q) {
    p.drag = { start: q, multi: true, origs: A.msel.idx.map((i) => [i, p.strokes[i]]), before: p.strokes.slice(), moved: false };
  }

  function moveSelect(p, q, ev) {
    const d = p.drag;
    const dx = q[0] - d.start[0], dy = q[1] - d.start[1];
    if (!d.moved && Math.hypot(dx, dy) < 0.003) return;
    d.moved = true;
    if (d.multi) { for (const [i, o] of d.origs) p.strokes[i] = translate(o, dx, dy, p); return; }
    p.strokes[A.sel.i] = d.handle ? resizeTo(d, q, ev) : translate(d.orig, dx, dy, p);
    placeTextBar();
  }

  /** Dragging a handle. Text: the corners scale the text about the opposite
   *  corner, the sides set the wrap width. Boxes: the grabbed edges move
   *  (images and stickers keep their shape from a corner unless Shift).
   *  Lines / arrows: the grabbed end moves. */
  function resizeTo(d, q, ev) {
    const o = d.orig, H = d.handle, { w, h } = d;
    const qx = q[0] * w, qy = q[1] * h;
    if (o.t === "line" || o.t === "arrow") return { ...o, [H]: [q[0], q[1]] };
    if (o.t === "text") {
      const L = textLayout(o, w);
      const minW = Math.max(L.fs * 2, 24);
      if (H === "e") return { ...o, bw: +(Math.max(minW, qx - L.pad - o.x * w) / w).toFixed(4) };
      if (H === "w") {
        const right = o.x * w + L.boxW;
        const nx = Math.min(right - minW, qx + L.pad);
        return { ...o, x: nx / w, bw: +((right - nx) / w).toFixed(4) };
      }
      const [bx0, by0, bx1, by1] = d.px;
      const ax = H.includes("w") ? bx1 : bx0, ay = H.includes("n") ? by1 : by0;
      const k = Math.max(Math.abs(qx - ax) / Math.max(4, bx1 - bx0), Math.abs(qy - ay) / Math.max(4, by1 - by0));
      const fsz = Math.min(0.16, Math.max(0.006, o.s * Math.max(0.15, Math.min(12, k))));
      const kk = fsz / o.s;
      const W2 = (bx1 - bx0) * kk, H2 = (by1 - by0) * kk, pad2 = L.pad * kk;
      const nx0 = H.includes("w") ? ax - W2 : ax, ny0 = H.includes("n") ? ay - H2 : ay;
      return { ...o, s: +fsz.toFixed(5), x: (nx0 + pad2) / w, y: Math.max(0, (ny0 + pad2) / h),
               ...(o.bw ? { bw: +(o.bw * kk).toFixed(4) } : {}) };
    }
    let x0 = Math.min(o.a[0], o.b[0]), y0 = Math.min(o.a[1], o.b[1]);
    let x1 = Math.max(o.a[0], o.b[0]), y1 = Math.max(o.a[1], o.b[1]);
    const keep = (o.t === "stk" || o.t === "img") && H.length === 2 && !(o.t === "img" && ev?.shiftKey);
    if (keep) {
      const ar = ((y1 - y0) * h) / Math.max(1e-6, (x1 - x0) * w);
      const ax = H.includes("w") ? x1 : x0, ay = H.includes("n") ? y1 : y0;
      const nw = Math.max(16, Math.abs(qx - ax * w), Math.abs(qy - ay * h) / ar);
      const bw = nw / w, bh = (nw * ar) / h;
      x0 = H.includes("w") ? ax - bw : ax; x1 = x0 + bw;
      y0 = H.includes("n") ? ay - bh : ay; y1 = y0 + bh;
      return { ...o, a: [x0, y0], b: [x1, y1] };
    }
    const keepDir = o.t === "poly" && POLY[o.k];
    if (H.includes("w")) x0 = Math.min(q[0], x1 - 0.005);
    if (H.includes("e")) x1 = Math.max(q[0], x0 + 0.005);
    if (H.includes("n")) y0 = Math.min(q[1], y1 - 0.005);
    if (H.includes("s")) y1 = Math.max(q[1], y0 + 0.005);
    if (keepDir) {                                     // keep a flipped polygon flipped
      const fx = o.b[0] < o.a[0], fy = o.b[1] < o.a[1];
      return { ...o, a: [fx ? x1 : x0, fy ? y1 : y0], b: [fx ? x0 : x1, fy ? y0 : y1] };
    }
    return { ...o, a: [x0, y0], b: [x1, y1] };
  }

  function finishLasso(p, L) {
    const { w, h } = size(p);
    if (L.length < 3) return paintLayer(p);
    const inside = (q) => {                             // ray casting, in px
      let c = false;
      for (let i = 0, j = L.length - 1; i < L.length; j = i++) {
        const a = L[i], b = L[j];
        if ((a[1] > q[1]) !== (b[1] > q[1]) && q[0] < ((b[0] - a[0]) * (q[1] - a[1])) / (b[1] - a[1]) + a[0]) c = !c;
      }
      return c;
    };
    const idx = [];
    p.strokes.forEach((s, i) => {
      const pts = s.pts ? s.pts : null;
      if (pts && pts.length > 2) {
        const n = pts.filter(inside).length;
        if (n / pts.length >= 0.6) idx.push(i);
        return;
      }
      const b = bbox(s, w, h);
      if (inside([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2])) idx.push(i);
    });
    A.sel = null; A.msel = null;
    if (idx.length === 1) A.sel = { key: p.key, i: idx[0] };
    else if (idx.length > 1) A.msel = { key: p.key, idx };
    paintLayer(p);
    paintBar();
  }

  function deleteSelected() {
    const S = selection();
    if (!S?.p) { A.sel = null; A.msel = null; return paintBar(); }
    const before = S.p.strokes.slice();
    const drop = new Set(S.idx);
    S.p.strokes = S.p.strokes.filter((_, i) => !drop.has(i));
    A.sel = null; A.msel = null;
    commit(S.p, before);
    paintLayer(S.p);
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
      if (A.eraseMode === "stroke" || WHOLE.has(s.t)) continue;        // whole object goes
      // Partial: drop the points under the eraser and split what is left into
      // separate strokes. Shapes become freehand strokes along their outline.
      const pts = s.t === "pen" || s.t === "marker" ? s.pts : outline(s, 64, w, h);
      const kind = s.t === "pen" || s.t === "marker" ? s.t : "pen";
      const extra = kind === "pen" ? (s.k ? { k: s.k } : s.t !== "pen" ? { k: s.d ? "dash" : "fine" } : {}) : {};
      let run = [];
      const flush = () => { if (run.length > 1) out.push({ id: uid(), t: kind, c: s.c, w: s.w, ...extra, pts: run }); run = []; };
      for (const a of pts) {
        if (Math.hypot(a[0] - q[0], (a[1] - q[1]) * k) < r) flush();
        else run.push(a);
      }
      flush();
      if (s.t === "arrow" && !s.two) {
        // keep the head if the tip wasn't erased
        if (Math.hypot(s.b[0] - q[0], (s.b[1] - q[1]) * k) >= r) {
          const tail = out[out.length - 1];
          if (tail && tail.pts?.at(-1) === pts.at(-1)) {
            const a0 = tail.pts[0];
            out[out.length - 1] = { id: tail.id, t: "arrow", c: s.c, w: s.w, a: [a0[0], a0[1]], b: s.b };
          }
        }
      }
    }
    if (changed) {
      if (!p.erasing.before) p.erasing.before = p.strokes.slice();
      p.strokes = out;
    }
  }

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
    const out = { id: o.id || uid(), t: "text", x: +(+o.x).toFixed(4), y: +(+o.y).toFixed(4), s: +(+o.s).toFixed(5), c: o.c, txt: o.txt || "" };
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
      A.msel = null;
      if (prevKey && prevKey !== p.key) { const o = A.pages.get(prevKey); if (o) blit(o); }
      p.drag = { start: q, orig: p.strokes[i], before: p.strokes.slice(), moved: false, editOnClick: true };
      paintBar();
      return;
    }
    if (A.sel || A.msel) clearSel();
    const d = A.textStyle;
    // camera pages: keep the same printed size on screen whatever the zoom
    const s0 = (d.pt / PT_PER_W) * (p.cam ? 1 / p.cam.z : 1);
    openEditor(p, null, { t: "text", x: q[0], y: q[1], c: A.color, s: s0, f: d.f,
                          b: d.b, i: d.i, u: d.u, al: d.al, bg: d.bg, bd: d.bd, txt: "" });
  }

  function openEditor(p, index, fresh) {
    closeEditor(true);
    closeNote(true);
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
    local(p).host.appendChild(wrap);
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
    ed.box.addEventListener("paste", (ev) => ev.stopPropagation());
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
    const { w: W, h: H, dx, dy } = local(p);
    let L = textLayout({ ...s, txt: box.value || " " }, W);
    if (!p.cam) {
      const room = Math.max(40, W - s.x * W - L.pad - 4);      // up to the page's right edge
      if (!s.bw && L.boxW > room) { s.bw = room / W; L = textLayout({ ...s, txt: box.value || " " }, W); }
    }
    measure.font = L.font;
    const empty = box.value ? 0 : measure.measureText("Type here").width;
    const contentW = s.bw ? s.bw * W : Math.max(L.boxW, empty) + 2;
    wrap.style.left = `${s.x * W - L.pad - dx}px`;
    wrap.style.top = `${s.y * H - L.pad - dy}px`;
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
    const W = local(p).w;
    const L = textLayout({ ...s, txt: ed.box.value || " " }, W);
    const start = ev.clientX, x0 = s.x * W, bw0 = s.bw ? s.bw * W : L.boxW, right = x0 + bw0;
    const minW = Math.max(L.fs * 2, 24);
    const maxR = p.cam ? Infinity : W;
    const move = (e) => {
      const dx = e.clientX - start;
      if (side === "e") s.bw = Math.min(maxR - x0, Math.max(minW, bw0 + dx)) / W;
      else {
        const nx = Math.max(p.cam ? -Infinity : 0, Math.min(right - minW, x0 + dx));
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
    if (ed && !ed.wrap.contains(e.target) && !tb.contains(e.target) && !fly.contains(e.target) && !bar.contains(e.target)) {
      closeEditor(true);
      if (e.target.classList?.contains("an-layer")) A.swallow = true;
    }
    const ne = NOTE.ed;
    if (ne && !ne.box.contains(e.target) && !fly.contains(e.target) && !bar.contains(e.target)) {
      closeNote(true);
      if (e.target.classList?.contains("an-layer")) A.swallow = true;
    }
  }, true);
  window.addEventListener("resize", () => { styleBox(); placeTextBar(); styleNote(); });

  // ── sticky notes ───────────────────────────────────────────────────────────
  const NOTE = { ed: null };
  function openNote(p, index) {
    closeEditor(true);
    closeNote(true);
    const orig = p.strokes[index];
    if (orig?.t !== "note") return;
    const box = document.createElement("textarea");
    box.className = "an-note-ed";
    box.placeholder = "Write a note…";
    box.setAttribute("aria-label", "Sticky note text");
    box.value = orig.txt || "";
    local(p).host.appendChild(box);
    NOTE.ed = { p, index, orig, s: { ...orig }, box };
    p.hideIndex = index;
    A.sel = { key: p.key, i: index };
    paintLayer(p);
    styleNote();
    box.focus({ preventScroll: true });
    box.setSelectionRange(box.value.length, box.value.length);
    box.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Escape" || ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter")) { ev.preventDefault(); closeNote(true); }
    });
    box.addEventListener("paste", (ev) => ev.stopPropagation());
    box.addEventListener("input", () => { NOTE.ed.s.txt = box.value; });
    paintBar();
  }
  function styleNote() {
    const ed = NOTE.ed;
    if (!ed) return;
    const { w, h, dx, dy } = local(ed.p);
    const L = noteLayout(ed.s, w, h);
    Object.assign(ed.box.style, { left: `${L.x - dx}px`, top: `${L.y - dy}px`, width: `${L.bw}px`, height: `${L.bh}px`,
      padding: `${L.pad}px`, font: L.font, lineHeight: `${L.fs * 1.3}px`, background: noteFill(ed.s.bg),
      color: dark() ? "#f3f4f6" : "#1f2937" });
  }
  function closeNote(save = true) {
    const ed = NOTE.ed;
    if (!ed) return;
    NOTE.ed = null;
    ed.box.remove();
    const p = ed.p;
    p.hideIndex = null;
    const at = p.strokes[ed.index] === ed.orig ? ed.index : null;
    const obj = { ...ed.s, txt: ed.box.value.replace(/\s+$/, "").slice(0, 2000) };
    if (save && at != null && JSON.stringify(obj) !== JSON.stringify(ed.orig)) {
      const before = p.strokes.slice();
      p.strokes[at] = obj;
      commit(p, before);
    }
    paintLayer(p);
    paintBar();
  }

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
      if (o?.t !== "text" || !p?.el.isConnected || !A.open || !(A.tool === "select" || A.tool === "text")) {
        closeTbPops();
        tb.remove();
        return;
      }
      s = o;
      const { w: W0, h: H0, dy } = local(p);
      const b = bbox(s, W0, H0);
      top0 = b[1] * H0 - 5 - dy;
      bottom0 = b[3] * H0 + 5 - dy;
    }
    const { w: W, h: H, dx, host } = local(p);
    if (tb.parentNode !== host) host.appendChild(tb);
    paintTextBar(s);
    const pad = textLayout(s, W).pad;
    const bw = tb.offsetWidth, bh = tb.offsetHeight;
    const elW = p.el.clientWidth, elH = p.view ? Infinity : p.el.clientHeight;
    const maxLeft = Math.max(0, (p.view ? document.documentElement.clientWidth + window.scrollX : elW) - bw - 4);
    const left = Math.min(Math.max(p.view ? window.scrollX + 4 : 0, s.x * W - pad - 6 - dx), maxLeft);
    let top = top0 - bh - 10;
    // no room above (top of the page, or above the visible area): put it below
    const onScreen = p.view ? top - window.scrollY : p.el.getBoundingClientRect().top + top;
    if (top < 0 || onScreen < 8) top = bottom0 + 10;
    tb.style.left = `${left}px`;
    tb.style.top = `${Math.min(top, Math.max(0, (p.cam ? elH : p.view ? Infinity : H) - bh))}px`;
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
    const { w: W, h: H } = local(p);
    const sx = e.clientX, sy = e.clientY, x0 = o.x, y0 = o.y;
    const before = p.strokes.slice(), orig = o, i = A.sel?.i;
    const move = (ev) => {
      let nx = x0 + (ev.clientX - sx) / W, ny = y0 + (ev.clientY - sy) / H;
      if (!p.cam) { nx = clamp(nx); ny = p.view ? Math.max(0, ny) : clamp(ny); }
      if (ed) { ed.s.x = nx; ed.s.y = ny; styleBox(); }
      else { p.strokes[i] = { ...orig, x: nx, y: ny }; schedule(p, true); }
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
    const S = selection();
    if (!S?.p) return;
    const { w, h } = size(S.p);
    const before = S.p.strokes.slice();
    const start = S.p.strokes.length;
    for (const i of S.idx) S.p.strokes.push({ ...translate(S.p.strokes[i], 14 / w, 14 / h, S.p), id: uid() });
    const added = S.idx.map((_, k) => start + k);
    if (added.length === 1) { A.sel = { key: S.p.key, i: added[0] }; A.msel = null; }
    else { A.msel = { key: S.p.key, idx: added }; A.sel = null; }
    commit(S.p, before);
    paintLayer(S.p);
  }

  // ── clipboard ──────────────────────────────────────────────────────────────
  // Copy: our own clipboard + the system one (as "pwt-ink:<json>", so ink can
  // go between tabs, papers and whiteboards). Paste: an image becomes an image
  // object, copied ink comes back as ink, plain text becomes a text box (when
  // the host asked for that, e.g. the whiteboard).
  const CLIP = "pwt-ink:";
  function copySelection(cut) {
    const S = selection();
    if (!S?.p) return false;
    const objs = S.idx.map((i) => S.p.strokes[i]).filter(Boolean);
    A.clip = { objs: JSON.parse(JSON.stringify(objs)), from: S.p.key, n: 0 };
    try { navigator.clipboard?.writeText(CLIP + JSON.stringify(objs)).catch(() => {}); } catch { /* ignore */ }
    if (cut) deleteSelected(); else flash(objs.length > 1 ? `Copied ${objs.length}` : "Copied");
    return true;
  }

  function pasteObjs(objs, p) {
    p ||= (A.sel && A.pages.get(A.sel.key)) || (A.msel && A.pages.get(A.msel.key)) || nearestPage();
    if (!p?.strokes || !objs.length) return;
    const { w, h } = size(p);
    const same = A.clip && A.clip.from === p.key;
    const off = same ? 14 * (++A.clip.n) : 0;
    let list = objs.map((o) => ({ ...translate(o, off / w, off / h, p), id: uid() }));
    if (!same) {                                       // another page: put it in the middle of what is visible
      const vis = visibleCentre(p);
      const u = list.reduce((b, s) => { const q = bbox(s, w, h); return b ? [Math.min(b[0], q[0]), Math.min(b[1], q[1]), Math.max(b[2], q[2]), Math.max(b[3], q[3])] : q; }, null);
      if (u && vis) {
        const dx = vis[0] - (u[0] + u[2]) / 2, dy = vis[1] - (u[1] + u[3]) / 2;
        list = list.map((o) => translate(o, dx, dy, p));
      }
    }
    const before = p.strokes.slice();
    const start = p.strokes.length;
    p.strokes.push(...list);
    if (list.length === 1) { A.sel = { key: p.key, i: start }; A.msel = null; }
    else { A.msel = { key: p.key, idx: list.map((_, k) => start + k) }; A.sel = null; }
    if (A.tool !== "select" && A.tool !== "lasso") A.tool = "select";
    commit(p, before);
    paintLayer(p);
  }

  /** The middle of the visible part of page p, in page fractions. */
  function visibleCentre(p) {
    const r = p.el.getBoundingClientRect();
    const top = Math.max(r.top, 0), bottom = Math.min(r.bottom, window.innerHeight);
    const left = Math.max(r.left, 0), right = Math.min(r.right, window.innerWidth);
    if (bottom <= top || right <= left) return null;
    const { w, h, ox, oy } = size(p);
    const x = (left + right) / 2 - r.left, y = (top + bottom) / 2 - r.top;
    if (p.view) return [(x + window.scrollX) / w, (y + window.scrollY) / w];
    return [(x + (p.cam ? ox : 0)) / w, (y + (p.cam ? oy : 0)) / h];
  }

  document.addEventListener("paste", (e) => {
    if (A.visible === false) return;
    if (e.target.matches?.("input, textarea, select, [contenteditable]") || TX.ed || NOTE.ed) return;
    const dt = e.clipboardData;
    if (!dt) return;
    const file = [...dt.items].find((it) => it.kind === "file" && it.type.startsWith("image/"))?.getAsFile();
    const txt = dt.getData("text/plain") || "";
    if (file && (A.open || pasteText)) { e.preventDefault(); insertImage(file); return; }
    if (txt.startsWith(CLIP)) {
      try { e.preventDefault(); pasteObjs(JSON.parse(txt.slice(CLIP.length))); } catch { /* not ours */ }
      return;
    }
    if (A.clip && A.open && (!txt || txt === A.clip.text)) { e.preventDefault(); pasteObjs(A.clip.objs); return; }
    if (txt && pasteText) {
      e.preventDefault();
      const p = nearestPage();
      const at = p && visibleCentre(p);
      if (!p || !at) return;
      const d = A.textStyle;
      const s0 = (d.pt / PT_PER_W) * (p.cam ? 1 / p.cam.z : 1);
      const { w } = size(p);
      const before = p.strokes.slice();
      p.strokes.push(cleanText({ x: at[0] - 0.2 * (p.cam ? 1 / p.cam.z : 1), y: at[1], c: A.color, s: s0, f: d.f,
                                 bw: Math.min(0.5, 480 / w), txt: txt.slice(0, 5000) }));
      A.sel = { key: p.key, i: p.strokes.length - 1 };
      A.tool = "select";
      commit(p, before);
      paintLayer(p);
    }
  });

  /** Keys for the selection: arrows nudge (Shift = 10 px), Ctrl+C / X / D,
   *  Ctrl+A (whole page), Enter or F2 types in a selected text box / note. */
  function objectKeys(e) {
    const mod = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
    if (mod && key === "a" && (A.tool === "select" || A.tool === "lasso")) {
      const p = (A.sel && A.pages.get(A.sel.key)) || nearestPage();
      if (p?.strokes?.length) {
        e.preventDefault();
        A.sel = null;
        A.msel = { key: p.key, idx: p.strokes.map((_, i) => i) };
        paintBar();
        return true;
      }
    }
    const S = selection();
    if (!S?.p) return false;
    if (mod && (key === "c" || key === "x")) { e.preventDefault(); return copySelection(key === "x"); }
    if (mod && key === "d") { e.preventDefault(); duplicateSelected(); return true; }
    if (!mod && !e.altKey && e.key.startsWith("Arrow")) {
      e.preventDefault();
      const { w, h } = size(S.p);
      const st = e.shiftKey ? 10 : 1;
      const dx = e.key === "ArrowLeft" ? -st : e.key === "ArrowRight" ? st : 0;
      const dy = e.key === "ArrowUp" ? -st : e.key === "ArrowDown" ? st : 0;
      applyToSelection((o) => translate(o, dx / w, dy / h, S.p));
      placeTextBar();
      return true;
    }
    const o = selected();
    if (o && (e.key === "Enter" || e.key === "F2")) {
      if (o.t === "text") { e.preventDefault(); openEditor(S.p, A.sel.i); return true; }
      if (o.t === "note") { e.preventDefault(); openNote(S.p, A.sel.i); return true; }
    }
    return false;
  }

  // ── images ─────────────────────────────────────────────────────────────────
  /** Downscale to <= 2400 px, upload, and drop it on page p at q (default: the
   *  middle of what is visible), selected. */
  async function insertImage(file, p, q) {
    p ||= (A.sel && A.pages.get(A.sel.key)) || nearestPage();
    if (!p?.strokes) return flash("Open a page first");
    if (!/^image\//.test(file.type)) return flash("That isn't an image");
    flash("Adding image…");
    let blob = file, iw, ih;
    try {
      const bmp = await createImageBitmap(file);
      iw = bmp.width; ih = bmp.height;
      const k = Math.min(1, 2400 / Math.max(iw, ih));
      if (k < 1 || file.size > 1.5e6 || !/png|jpe?g|webp|gif/.test(file.type)) {
        const cv = document.createElement("canvas");
        cv.width = Math.round(iw * k); cv.height = Math.round(ih * k);
        cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
        blob = await new Promise((res) => cv.toBlob(res, "image/webp", 0.88)) ||
               await new Promise((res) => cv.toBlob(res, "image/png"));
        iw = cv.width; ih = cv.height;
      }
      bmp.close?.();
    } catch { return flash("Couldn't read that image"); }
    let src;
    try { src = await uploader(blob); } catch (err) { return flash(err.message || "Image not saved"); }
    const { w, h } = size(p);
    const at = q || visibleCentre(p) || [0.5, 0.3];
    const vis = p.el.getBoundingClientRect();
    const maxW = Math.min(vis.width, window.innerWidth) * 0.6, maxH = Math.min(vis.height, window.innerHeight) * 0.6;
    const k = Math.min(1, maxW / iw, maxH / ih);
    const box = boxAt(at, iw * k, ih / iw, w, h, true);
    const before = p.strokes.slice();
    p.strokes.push({ id: uid(), t: "img", src, ...box });
    A.sel = { key: p.key, i: p.strokes.length - 1 };
    A.msel = null;
    A.tool = "select";
    if (!A.open) setOpen(true);
    commit(p, before);
    paintLayer(p);
    flash("Image added");
  }

  // ── history + saving ───────────────────────────────────────────────────────
  function commit(p, before) {
    A.undo.push({ key: p.key, before, after: p.strokes.slice() });
    if (A.undo.length > 200) A.undo.shift();
    A.redo = [];
    save(p);
    paintBar();
    A.onChange?.(p);
  }

  function apply(key, strokes) {
    const p = A.pages.get(key);
    if (!p) return false;
    p.strokes = strokes.slice();
    if (A.sel?.key === key && !p.strokes[A.sel.i]) A.sel = null;
    if (A.msel?.key === key) A.msel = null;
    paintLayer(p);
    save(p);
    A.onChange?.(p);
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
    if (best.strokes.length > 20 && !confirm("Clear everything on this page? (Undo brings it back.)")) return;
    const before = best.strokes.slice();
    best.strokes = [];
    A.sel = null; A.msel = null;
    commit(best, before);
    paintLayer(best);
  }

  const saved = bar.querySelector(".an-saved");
  function flash(msg) {
    saved.textContent = msg;
    clearTimeout(saved._t);
    saved._t = setTimeout(() => { saved.textContent = ""; }, 2200);
  }

  const notify = (state) => A.saveState.forEach((fn) => fn(state, A.pending));
  function save(p) {
    if (!saveInk) {
      if (!A.warned) { A.warned = true; flash(unsaved); }
      return;
    }
    if (!A.saveTimers.has(p.key)) { A.pending++; notify("saving"); }
    clearTimeout(A.saveTimers.get(p.key));
    A.saveTimers.set(p.key, setTimeout(() => flushPage(p), 700));
  }
  async function flushPage(p) {
    clearTimeout(A.saveTimers.get(p.key));
    if (!A.saveTimers.has(p.key)) return;
    A.saveTimers.delete(p.key);
    const strokes = p.strokes.slice();
    try {
      await store.save(p.doc, p.page, strokes);
      const cached = await load(p.doc);
      cached[String(p.page)] = strokes;
      A.pending = Math.max(0, A.pending - 1);
      if (!A.quietSaves) flash("Saved");
      notify(A.pending ? "saving" : "saved");
    } catch (err) {
      A.pending = Math.max(0, A.pending - 1);
      flash("Not saved — check your connection");
      notify("error", err);
    }
  }
  async function flush() {
    await Promise.all([...A.pages.values()].filter((p) => A.saveTimers.has(p.key)).map(flushPage));
  }

  window.addEventListener("resize", () => { for (const p of A.pages.values()) paintLayer(p); });

  function setVisible(v) {
    A.visible = v;
    layout();
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

  // ── instruments: ruler + protractor + compass (on screen only, never saved) ─
  const INST = { ruler: null, protractor: null, setsquare: null, compass: null };
  let INST_Z = 7;                                                    // the one touched last is on top

  /** Pixels per millimetre on this page, at the paper's real size. */
  function pxPerMm(p) {
    if (p.cam) return size(p).w / 210;                        // whiteboard: 1 unit = an A4 width
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
    if (kind === "compass") return openCompass(p);
    const r = p.el.getBoundingClientRect();
    const vis = { top: Math.max(r.top, 0), bottom: Math.min(r.bottom, window.innerHeight) };
    const k = pxPerMm(p);
    const it = { kind, p, deg: 0, len: 150, flip: false, variant: "45", scale: instScale(kind),
                 x: p.el.clientWidth / 2 - (kind === "setsquare" ? 50 * k : 0),
                 y: (vis.top + vis.bottom) / 2 - r.top + (kind === "protractor" ? 30 * k : kind === "setsquare" ? 40 * k : 0) };
    // instruments already open on this page: start this one clear of them
    const open = Object.values(INST).filter((o) => o && o.p === p && o.kind !== "compass").length;
    it.x += open * 36; it.y += open * 70 * Math.min(1, k / 3);
    it.el = document.createElement("div");
    it.el.className = `an-inst an-inst-${kind}`;
    it.el.style.zIndex = String(++INST_Z);
    p.el.appendChild(it.el);
    INST[kind] = it;
    renderInst(it);
    bindInstrument(it);
    paintInstButtons();
  }

  function paintInstButtons() {
    bar.querySelectorAll("[data-inst]").forEach((b) =>
      b.setAttribute("aria-pressed", String(!!INST[b.dataset.inst])));
  }

  const f1 = (v) => +v.toFixed(1);
  // Instrument size: 1 = true size. Angles stay right at any size (protractor,
  // set square); a resized ruler's centimetres no longer match the page, so it
  // says "not to scale". Remembered per instrument.
  const SCALES = [0.5, 0.64, 0.8, 1, 1.25, 1.56, 1.95, 2.5];
  function instScale(kind) {
    try { const v = +JSON.parse(localStorage.getItem("pwt-inst-scale") || "{}")[kind]; return SCALES.includes(v) ? v : 1; }
    catch { return 1; }
  }
  function keepScale(kind, v) {
    try {
      const all = JSON.parse(localStorage.getItem("pwt-inst-scale") || "{}");
      all[kind] = v;
      localStorage.setItem("pwt-inst-scale", JSON.stringify(all));
    } catch { /* ignore */ }
  }
  function stepScale(it, dir) {
    const i = SCALES.indexOf(it.scale);
    const next = dir === 0 ? 1 : SCALES[Math.max(0, Math.min(SCALES.length - 1, (i < 0 ? 3 : i) + dir))];
    if (next === it.scale) return;
    it.scale = next;
    keepScale(it.kind, next);
    renderInst(it);
  }
  /**
   * An instrument's drawing in its own frame (px, origin = the point it turns
   * about; y down), its bounding box, its straight edges (pens snap to them)
   * and where its handles sit. Real size: k px per mm.
   */
  function instGeo(it, k) {
    const t = [], lab = [];
    if (it.kind === "ruler") {
      const L = it.len * k, W = 30 * k, pad = 5 * k, x0 = -L / 2, y0 = -W / 2;
      for (let mm = 0; mm <= it.len; mm++) {
        const x = x0 + mm * k, len = mm % 10 === 0 ? 6.5 * k : mm % 5 === 0 ? 4.5 * k : 2.6 * k;
        t.push(`<line class="${mm % 10 === 0 ? "is-major" : ""}" x1="${f1(x)}" y1="${f1(y0)}" x2="${f1(x)}" y2="${f1(y0 + len)}"/>`);
        if (mm % 10 === 0) lab.push(`<text x="${f1(x)}" y="${f1(y0 + len + 4.6 * k)}">${mm / 10}</text>`);
      }
      const body = `<rect class="an-inst-body" x="${f1(x0 - pad)}" y="${f1(y0)}" width="${f1(L + 2 * pad)}" height="${f1(W)}" rx="${f1(1.6 * k)}"/>
        <text class="an-inst-unit${it.scale !== 1 ? " is-warn" : ""}" x="${f1(x0 + L / 2)}" y="${f1(W / 2 - 3 * k)}">${it.scale !== 1 ? "Not to scale" : `${it.len / 10} cm`}</text>`;
      return { body, ticks: t.join(""), labels: lab.join(""), font: Math.max(12, 3.4 * k),
               box: [x0 - pad, y0, L + 2 * pad, W],
               edges: [[[x0 - pad, y0], [x0 + L + pad, y0]], [[x0 - pad, -y0], [x0 + L + pad, -y0]]],
               rot: [x0 + L + pad + 22, 0], close: [x0 - pad - 22, 0], deg: [-40, W / 2 + 18], opt: [40, W / 2 + 18],
               optLabel: it.len === 150 ? "30 cm" : "15 cm", optTitle: "Longer / shorter ruler" };
    }
    if (it.kind === "protractor") {
      const R = 60 * k, sg = it.flip ? 1 : -1;                    // sg = the side the arc is on
      for (let d = 0; d <= 180; d++) {
        const a = Math.PI - (d * Math.PI) / 180, len = d % 10 === 0 ? 7 * k : d % 5 === 0 ? 4.6 * k : 2.6 * k;
        const c = Math.cos(a), sn = Math.sin(a) * sg;
        t.push(`<line class="${d % 10 === 0 ? "is-major" : ""}" x1="${f1(R * c)}" y1="${f1(R * sn)}" x2="${f1((R - len) * c)}" y2="${f1((R - len) * sn)}"/>`);
        if (d % 10 === 0) {
          const ro = R - 11.5 * k, ri = R - 17.5 * k, dy = 1.3 * k;
          lab.push(`<text x="${f1(ro * c)}" y="${f1(ro * sn + dy)}">${d}</text>`);
          lab.push(`<text class="an-inst-inner" x="${f1(ri * c)}" y="${f1(ri * sn + dy)}">${180 - d}</text>`);
        }
      }
      const Ro = R + 3 * k;
      const body = `<path class="an-inst-body" d="M${f1(-Ro)} 0 A${f1(Ro)} ${f1(Ro)} 0 0 ${it.flip ? 0 : 1} ${f1(Ro)} 0 Z"/>
        <line class="an-inst-base" x1="${f1(-Ro)}" y1="0" x2="${f1(Ro)}" y2="0"/>
        <line class="an-inst-base" x1="0" y1="${f1(4 * k)}" x2="0" y2="${f1(-4 * k)}"/>
        <circle class="an-inst-centre" cx="0" cy="0" r="${f1(Math.max(3, 0.9 * k))}"/>`;
      return { body, ticks: t.join(""), labels: lab.join(""), font: Math.max(11, 3 * k),
               box: [-Ro, it.flip ? 0 : -Ro, 2 * Ro, Ro],
               edges: [[[-Ro, 0], [Ro, 0]]],
               rot: [Ro + 22, 0], close: [-Ro - 22, 0], deg: [0, sg * R * 0.36],
               opt: [0, -sg * 18], optLabel: "Flip", optTitle: "Turn the arc to the other side of the base" };
    }
    // set square: right angle at the origin, base along +x, upright along -y
    const B = (it.variant === "45" ? 100 : 120) * k;
    const H = it.variant === "45" ? B : B * Math.tan(Math.PI / 6);
    for (let mm = 0; mm * k <= B - 8 * k; mm++) {
      const x = mm * k, len = mm % 10 === 0 ? 5 * k : mm % 5 === 0 ? 3.4 * k : 2 * k;
      t.push(`<line class="${mm % 10 === 0 ? "is-major" : ""}" x1="${f1(x)}" y1="0" x2="${f1(x)}" y2="${f1(-len)}"/>`);
      if (mm % 10 === 0 && mm) lab.push(`<text x="${f1(x)}" y="${f1(-len - 1.6 * k)}">${mm / 10}</text>`);
    }
    for (let mm = 1; mm * k <= H - 8 * k; mm++) {
      const y = -mm * k, len = mm % 10 === 0 ? 5 * k : mm % 5 === 0 ? 3.4 * k : 2 * k;
      t.push(`<line class="${mm % 10 === 0 ? "is-major" : ""}" x1="0" y1="${f1(y)}" x2="${f1(len)}" y2="${f1(y)}"/>`);
      if (mm % 10 === 0) lab.push(`<text x="${f1(len + 3 * k)}" y="${f1(y + 1.2 * k)}">${mm / 10}</text>`);
    }
    // the see-through cut-out of a real set square: the same triangle, shrunk about its incentre
    const P = B + H + Math.hypot(B, H);                            // incentre of the right triangle
    const icx = (H * B) / P, icy = -(B * H) / P;
    const sc = 0.42, sh = (x, y) => `${f1(icx + (x - icx) * sc)} ${f1(icy + (y - icy) * sc)}`;
    const body = `<path class="an-inst-body" fill-rule="evenodd" d="M0 0 L${f1(B)} 0 L0 ${f1(-H)} Z M${sh(0, 0)} L${sh(B, 0)} L${sh(0, -H)} Z"/>
      <path class="an-inst-corner" d="M${f1(7 * k)} 0 V${f1(-7 * k)} H0"/>
      <text class="an-inst-unit" x="${f1(B * 0.6)}" y="${f1(-H * 0.12)}">${it.variant === "45" ? "45°" : "30° · 60°"}</text>`;
    return { body, ticks: t.join(""), labels: lab.join(""), font: Math.max(11, 3 * k),
             box: [0, -H, B, H],
             edges: [[[0, 0], [B, 0]], [[0, 0], [0, -H]], [[B, 0], [0, -H]]],
             rot: [B + 22, 0], close: [-22, 14], deg: [B * 0.3, 20], opt: [B * 0.3 + 70, 20],
             optLabel: it.variant === "45" ? "30°/60°" : "45°", optTitle: "Switch set square" };
  }

  /** (Re)draw an instrument at the page's current scale, keeping where it is. */
  function renderInst(it) {
    const k = pxPerMm(it.p) * (it.scale || 1);
    const g = instGeo(it, k);
    it.geo = g;
    const [bx, by, bw, bh] = g.box, m = 44;                     // room for the handles outside the body
    it.box = { x: bx - m, y: by - m, w: bw + 2 * m, h: bh + 2 * m };
    const pos = (q) => `left:${f1(q[0] - it.box.x)}px;top:${f1(q[1] - it.box.y)}px`;
    it.el.innerHTML = `<svg class="an-inst-svg" width="${f1(it.box.w)}" height="${f1(it.box.h)}"
        viewBox="${f1(it.box.x)} ${f1(it.box.y)} ${f1(it.box.w)} ${f1(it.box.h)}">
        <g class="an-inst-shape">${g.body}</g>
        <g class="an-inst-ticks">${g.ticks}</g>
        <g class="an-inst-labels" style="font-size:${f1(g.font)}px">${g.labels}</g></svg>
      <button type="button" class="an-inst-rot" style="${pos(g.rot)}" aria-label="Rotate the ${it.kind}" title="Drag to rotate (Shift: 15° steps)"></button>
      <button type="button" class="an-inst-x" style="${pos(g.close)}" aria-label="Put the ${it.kind} away" title="Put away">×</button>
      <span class="an-inst-deg" style="${pos(g.deg)}">0°</span>
      <button type="button" class="an-inst-opt" style="${pos(g.opt)}" title="${g.optTitle}">${g.optLabel}</button>
      <span class="an-inst-size" style="${pos([g.opt[0] + (it.kind === "setsquare" ? 92 : 96), g.opt[1]])}" role="group" aria-label="Size of the ${it.kind}">
        <button type="button" data-isz="-1" aria-label="Smaller" title="Smaller (Ctrl + scroll)">−</button>
        <button type="button" data-isz="0" class="${it.scale !== 1 ? "is-off" : ""}" title="${it.scale !== 1 ? "Back to true size" : "True size"}">${Math.round((it.scale || 1) * 100)}%</button>
        <button type="button" data-isz="1" aria-label="Bigger" title="Bigger (Ctrl + scroll)">+</button>
      </span>`;
    it.el.style.width = `${f1(it.box.w)}px`;
    it.el.style.height = `${f1(it.box.h)}px`;
    placeInstrument(it);
  }

  function placeInstrument(it) {
    const ox = -it.box.x, oy = -it.box.y;                          // the turning point inside the element
    Object.assign(it.el.style, { left: `${it.x - ox}px`, top: `${it.y - oy}px`,
                                 transformOrigin: `${ox}px ${oy}px`, transform: `rotate(${-it.deg}deg)` });
    const d = ((Math.round(it.deg) % 360) + 360) % 360;
    it.el.querySelector(".an-inst-deg").textContent = `${d > 180 ? d - 360 : d}°`;
  }

  function bindInstrument(it) {
    const el = it.el;
    el.addEventListener("wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey) || !e.target.closest(".an-inst-shape, .an-inst-ticks, .an-inst-labels")) return;
      e.preventDefault();
      e.stopPropagation();
      stepScale(it, e.deltaY < 0 ? 1 : -1);
    }, { passive: false });
    el.addEventListener("click", (e) => {
      if (e.target.closest(".an-inst-x")) return toggleInstrument(it.kind);
      const sz = e.target.closest("[data-isz]");
      if (sz) return stepScale(it, +sz.dataset.isz);
      if (!e.target.closest(".an-inst-opt")) return;
      if (it.kind === "ruler") it.len = it.len === 150 ? 300 : 150;
      if (it.kind === "protractor") it.flip = !it.flip;
      if (it.kind === "setsquare") it.variant = it.variant === "45" ? "3060" : "45";
      renderInst(it);
    });
    el.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".an-inst-shape, .an-inst-ticks, .an-inst-labels, .an-inst-rot, .an-inst-size, .an-inst-opt")) {
        el.style.zIndex = String(++INST_Z);                          // bring it to the front
      }
      if (e.target.closest(".an-inst-x, .an-inst-opt, .an-inst-size")) return;
      // the empty margin around the shape (it only holds the handles) lets presses through
      if (!e.target.closest(".an-inst-rot, .an-inst-shape, .an-inst-ticks, .an-inst-labels")) return;
      // Pen/highlighter pressed on an EDGE draws along it (hand the press to
      // the page underneath); anywhere else on the body drags the instrument.
      if ((A.tool === "pen" || A.tool === "marker") && !e.target.closest(".an-inst-rot") && edgeSnap(it.p, e, it)) {
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
      const ang = (ev) => Math.atan2(ev.clientY - host.top - it.y, ev.clientX - host.left - it.x) * 180 / Math.PI;
      const grab = ang(e) + it.deg;                                  // turning is relative to where you grabbed
      const move = (ev) => {
        if (rot) {
          let deg = grab - ang(ev);
          deg = ev.shiftKey ? Math.round(deg / 15) * 15 : Math.round(deg);
          it.deg = ((deg + 540) % 360) - 180;
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

  /** If a stroke starts on (or just off) a straight edge of the ruler, set
   *  square or protractor base on this page, a projector that pins every
   *  point onto that line. only = look at that one instrument. */
  function edgeSnap(p, e, only = null) {
    const host = p.el.getBoundingClientRect();
    const x = e.clientX - host.left, y = e.clientY - host.top;
    let best = null;
    for (const it of [INST.ruler, INST.setsquare, INST.protractor]) {
      if (!it || it.p !== p || (only && it !== only) || !it.geo) continue;
      const a = (-it.deg * Math.PI) / 180, c = Math.cos(a), sn = Math.sin(a);
      const dx = x - it.x, dy = y - it.y;
      const lx = dx * c + dy * sn, ly = -dx * sn + dy * c;           // the press in the instrument's frame
      for (const [[x1, y1], [x2, y2]] of it.geo.edges) {
        const ex = x2 - x1, ey = y2 - y1, L2 = ex * ex + ey * ey;
        const tt = ((lx - x1) * ex + (ly - y1) * ey) / L2;
        if (tt < -0.03 || tt > 1.03) continue;
        const d = Math.hypot(lx - (x1 + tt * ex), ly - (y1 + tt * ey));
        if (d <= 14 && (!best || d < best.d)) {
          const L = Math.sqrt(L2);
          // the edge in page px: a point on it and its direction
          best = { d, px: it.x + x1 * c - y1 * sn, py: it.y + x1 * sn + y1 * c,
                   ux: (ex / L) * c - (ey / L) * sn, uy: (ex / L) * sn + (ey / L) * c };
        }
      }
    }
    if (!best) return null;
    const { w, h, ox, oy } = size(p);
    return {
      project(q) {
        // page fractions -> element px (whole-page and camera layers are scrolled)
        const px = q[0] * w - ox, py = q[1] * h - oy;
        const t2 = (px - best.px) * best.ux + (py - best.py) * best.uy;
        return [(best.px + t2 * best.ux + ox) / w, (best.py + t2 * best.uy + oy) / h, q[2]];
      },
    };
  }

  // ── compass ────────────────────────────────────────────────────────────────
  // Needle at C, pencil at P = C + r·(cos θ, sin θ), hinge above the middle.
  // Drag the needle = move it (snaps to line ends, corners, arc centres and
  // intersections); drag the pencil = set the radius (snaps too) without
  // drawing; turn the hinge = draw an arc. Lock keeps the radius.
  function openCompass(p) {
    const r0 = 40 * pxPerMm(p);                                   // starts at 4 cm
    const rr = p.el.getBoundingClientRect();
    const vis = { top: Math.max(rr.top, 0), bottom: Math.min(rr.bottom, window.innerHeight) };
    const it = { kind: "compass", p, cx: p.el.clientWidth / 2 - r0 / 2, cy: (vis.top + vis.bottom) / 2 - rr.top + 40,
                 r: r0, ang: 0, lock: false };
    it.el = document.createElement("div");
    it.el.className = "an-inst an-compass";
    it.el.innerHTML = `<svg class="an-cmp-svg"><g class="an-cmp-g">
        <line class="an-cmp-leg" data-k="leg1"/><line class="an-cmp-leg an-cmp-leg2" data-k="leg2"/>
        <line class="an-cmp-lead" data-k="lead"/>
        <path class="an-cmp-guide" data-k="guide"/>
        <circle class="an-cmp-needle" data-k="needle" r="8"/><circle class="an-cmp-tip" data-k="tipC" r="2.4"/>
        <circle class="an-cmp-pencil" data-k="pencil" r="9"/><circle class="an-cmp-tip2" data-k="tipP" r="3"/>
        <circle class="an-cmp-hinge" data-k="hinge" r="13"/><path class="an-cmp-turn" data-k="turn"/>
      </g></svg>
      <span class="an-cmp-r"></span>
      <button type="button" class="an-cmp-lock" aria-pressed="false" title="Lock the radius" aria-label="Lock the radius">${svg("unlock")}</button>
      <button type="button" class="an-inst-x" aria-label="Put the compass away" title="Put away">×</button>`;
    p.el.appendChild(it.el);
    INST.compass = it;
    placeCompass(it);
    bindCompass(it);
    paintInstButtons();
    flash("Drag the needle, set the radius with the pencil, turn the top to draw");
  }

  function compassGeo(it) {
    const C = [it.cx, it.cy], P = [it.cx + it.r * Math.cos(it.ang), it.cy + it.r * Math.sin(it.ang)];
    const M = [(C[0] + P[0]) / 2, (C[1] + P[1]) / 2];
    let n = [Math.sin(it.ang), -Math.cos(it.ang)];
    if (n[1] > 0) n = [-n[0], -n[1]];                 // the hinge sits above the legs
    const L = Math.max(it.r / 2 + 34, 120);
    const hgt = Math.sqrt(Math.max(L * L - (it.r / 2) ** 2, 38 * 38));
    return { C, P, H: [M[0] + n[0] * hgt, M[1] + n[1] * hgt] };
  }

  function placeCompass(it) {
    const { C, P, H } = compassGeo(it);
    const q = (k) => it.el.querySelector(`[data-k="${k}"]`);
    const ln = (k, a, b) => { const e = q(k); e.setAttribute("x1", a[0]); e.setAttribute("y1", a[1]); e.setAttribute("x2", b[0]); e.setAttribute("y2", b[1]); };
    ln("leg1", H, C);
    ln("leg2", H, P);
    const lead = [P[0] + (H[0] - P[0]) * 0.22, P[1] + (H[1] - P[1]) * 0.22];
    ln("lead", lead, P);
    q("lead").style.stroke = ink(A.color);
    q("tipP").style.fill = ink(A.color);
    for (const [k, pnt] of [["needle", C], ["tipC", C], ["pencil", P], ["tipP", P], ["hinge", H]]) {
      q(k).setAttribute("cx", pnt[0]); q(k).setAttribute("cy", pnt[1]);
    }
    q("turn").setAttribute("d", `M${H[0] - 9} ${H[1] - 18} A 12 12 0 0 1 ${H[0] + 9} ${H[1] - 18}`);
    // faint guide circle while the radius is being set
    q("guide").setAttribute("d", it.showGuide
      ? `M${C[0] + it.r} ${C[1]} A ${it.r} ${it.r} 0 1 1 ${C[0] - it.r} ${C[1]} A ${it.r} ${it.r} 0 1 1 ${C[0] + it.r} ${C[1]}` : "");
    const lab = it.el.querySelector(".an-cmp-r");
    lab.textContent = `${(it.r / pxPerMm(it.p) / 10).toFixed(1)} cm`;
    Object.assign(lab.style, { left: `${(C[0] + P[0]) / 2}px`, top: `${(C[1] + P[1]) / 2 + 14}px` });
    const lock = it.el.querySelector(".an-cmp-lock"), x = it.el.querySelector(".an-inst-x");
    Object.assign(lock.style, { left: `${H[0] + 18}px`, top: `${H[1] - 12}px` });
    Object.assign(x.style, { left: `${H[0] - 40}px`, top: `${H[1] - 12}px` });
    lock.setAttribute("aria-pressed", String(it.lock));
    lock.innerHTML = svg(it.lock ? "lock" : "unlock");
    lock.title = it.lock ? "Radius locked — click to unlock" : "Lock the radius";
  }

  /** Points the compass can snap to, in element px: ends, corners, centres, intersections. */
  function snapPoints(p) {
    const { w, h, ox, oy } = size(p);
    const px = (q) => [q[0] * w - ox, q[1] * h - oy];
    const pts = [], segs = [], circles = [];
    for (const s of p.strokes || []) {
      if (s.t === "line" || s.t === "arrow") { const a = px(s.a), b = px(s.b); pts.push(a, b); segs.push([a, b]); }
      else if (s.t === "rect" || s.t === "poly") {
        const c = s.t === "rect" ? [[s.a[0], s.a[1]], [s.b[0], s.a[1]], [s.b[0], s.b[1]], [s.a[0], s.b[1]], [s.a[0], s.a[1]]] : polyCorners(s);
        const P = c.map(px);
        P.slice(0, -1).forEach((q) => pts.push(q));
        for (let i = 1; i < P.length; i++) segs.push([P[i - 1], P[i]]);
      } else if (s.t === "arc") {
        const o = px(s.o), R = s.r * w;
        pts.push(o, [o[0] + R * Math.cos(s.a0), o[1] + R * Math.sin(s.a0)],
                 [o[0] + R * Math.cos(s.a0 + s.sw), o[1] + R * Math.sin(s.a0 + s.sw)]);
        circles.push({ o, R, a0: s.a0, sw: s.sw });
      } else if ((s.t === "pen") && s.pts?.length > 1) {
        pts.push(px(s.pts[0]), px(s.pts[s.pts.length - 1]));
      }
    }
    const onArc = (c, ang) => {
      if (Math.abs(c.sw) >= Math.PI * 2 - 1e-3) return true;
      let d = (ang - c.a0) * Math.sign(c.sw);
      d = ((d % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
      return d <= Math.abs(c.sw) + 0.02;
    };
    const S = segs.slice(0, 160);
    for (let i = 0; i < S.length; i++) for (let j = i + 1; j < S.length; j++) {
      const [a, b] = S[i], [c, d] = S[j];
      const den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0]);
      if (Math.abs(den) < 1e-9) continue;
      const t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den;
      const u = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / den;
      if (t >= -0.01 && t <= 1.01 && u >= -0.01 && u <= 1.01) pts.push([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]);
    }
    const CI = circles.slice(0, 60);
    for (let i = 0; i < CI.length; i++) {
      for (let j = i + 1; j < CI.length; j++) {             // arc ∩ arc (bisectors, equilateral triangles)
        const A1 = CI[i], B1 = CI[j];
        const d = Math.hypot(B1.o[0] - A1.o[0], B1.o[1] - A1.o[1]);
        if (d < 1e-6 || d > A1.R + B1.R || d < Math.abs(A1.R - B1.R)) continue;
        const a = (A1.R * A1.R - B1.R * B1.R + d * d) / (2 * d), hh = Math.sqrt(Math.max(0, A1.R * A1.R - a * a));
        const mx = A1.o[0] + (a * (B1.o[0] - A1.o[0])) / d, my = A1.o[1] + (a * (B1.o[1] - A1.o[1])) / d;
        for (const sg of [1, -1]) {
          const X = [mx + (sg * hh * (B1.o[1] - A1.o[1])) / d, my - (sg * hh * (B1.o[0] - A1.o[0])) / d];
          if (onArc(A1, Math.atan2(X[1] - A1.o[1], X[0] - A1.o[0])) && onArc(B1, Math.atan2(X[1] - B1.o[1], X[0] - B1.o[0]))) pts.push(X);
        }
      }
      for (const [a, b] of S.slice(0, 80)) {                // arc ∩ line
        const c = CI[i], dx = b[0] - a[0], dy = b[1] - a[1];
        const fx = a[0] - c.o[0], fy = a[1] - c.o[1];
        const qa = dx * dx + dy * dy, qb = 2 * (fx * dx + fy * dy), qc = fx * fx + fy * fy - c.R * c.R;
        const disc = qb * qb - 4 * qa * qc;
        if (disc < 0 || qa < 1e-9) continue;
        for (const sg of [1, -1]) {
          const t = (-qb + sg * Math.sqrt(disc)) / (2 * qa);
          if (t < -0.01 || t > 1.01) continue;
          const X = [a[0] + t * dx, a[1] + t * dy];
          if (onArc(c, Math.atan2(X[1] - c.o[1], X[0] - c.o[0]))) pts.push(X);
        }
      }
    }
    return pts;
  }
  function snapTo(pts, x, y, r = 12) {
    let best = null, bd = r;
    for (const q of pts) { const d = Math.hypot(q[0] - x, q[1] - y); if (d < bd) { bd = d; best = q; } }
    return best;
  }

  function bindCompass(it) {
    const el = it.el;
    el.querySelector(".an-inst-x").addEventListener("click", () => toggleInstrument("compass"));
    el.querySelector(".an-cmp-lock").addEventListener("click", () => { it.lock = !it.lock; placeCompass(it); });
    el.addEventListener("pointerdown", (e) => {
      const k = e.target.closest("[data-k]")?.dataset.k;
      if (!k || !["needle", "tipC", "pencil", "tipP", "hinge", "turn", "leg1", "leg2", "lead"].includes(k)) return;
      e.preventDefault();
      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      const p = it.p;
      const host = () => p.el.getBoundingClientRect();
      const mode = k === "needle" || k === "tipC" || k === "leg1" ? "move"
        : k === "pencil" || k === "tipP" || k === "lead" || k === "leg2" ? (it.lock ? "turnFree" : "radius") : "draw";
      const pts = mode === "move" || mode === "radius" ? snapPoints(p) : null;
      const start = { x: e.clientX, y: e.clientY, cx: it.cx, cy: it.cy };
      const h0 = host();
      // turning: the pencil moves by however far the hand turns about the needle
      let sweep = 0, prev = Math.atan2(e.clientY - h0.top - it.cy, e.clientX - h0.left - it.cx);
      const startAng = it.ang;
      const toFrac = (x, y) => { const { w, h, ox, oy } = size(p); return [(x + ox) / w, (y + oy) / h]; };
      it.showGuide = mode === "radius";
      const move = (ev) => {
        const hr = host();
        const x = ev.clientX - hr.left, y = ev.clientY - hr.top;
        p.snapAt = null;
        if (mode === "move") {
          let nx = start.cx + ev.clientX - start.x, ny = start.cy + ev.clientY - start.y;
          const s = snapTo(pts, nx, ny);
          if (s) { [nx, ny] = s; p.snapAt = toFrac(nx, ny); }
          it.cx = nx; it.cy = ny;
        } else if (mode === "radius") {
          let px = x, py = y;
          const s = snapTo(pts, px, py);
          if (s) { [px, py] = s; p.snapAt = toFrac(px, py); }
          it.r = Math.max(6, Math.hypot(px - it.cx, py - it.cy));
          it.ang = Math.atan2(py - it.cy, px - it.cx);
        } else {
          const a = Math.atan2(y - it.cy, x - it.cx);
          let d = a - prev;
          if (d > Math.PI) d -= Math.PI * 2;
          if (d < -Math.PI) d += Math.PI * 2;
          prev = a;
          it.ang += d;
          if (mode === "draw") {
            sweep = Math.max(-Math.PI * 2, Math.min(Math.PI * 2, sweep + d));
            const { w } = size(p);
            const o = toFrac(it.cx, it.cy);
            p.live = { id: p.live?.id || uid(), t: "arc", c: A.color, w: SIZES[A.size], o: [+o[0].toFixed(5), +o[1].toFixed(5)],
                       r: +(it.r / w).toFixed(5), a0: +startAng.toFixed(4), sw: +sweep.toFixed(4), ...(A.dash ? { d: 1 } : {}) };
          }
        }
        placeCompass(it);
        schedule(p);
      };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
        p.snapAt = null;
        it.showGuide = false;
        placeCompass(it);
        if (mode === "draw" && p.live?.t === "arc") {
          const s = p.live;
          p.live = null;
          if (Math.abs(s.sw) > 0.03) {
            const before = p.strokes.slice();
            p.strokes.push(s);
            commit(p, before);
          }
        }
        paintLayer(p);
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    });
  }

  // ── camera (infinite whiteboard) ───────────────────────────────────────────
  function setCamera(p, cam) {
    if (!p?.cam) return;
    Object.assign(p.cam, cam);
    paintLayer(p);
    styleBox(); placeTextBar(); styleNote();
  }

  /** Draw a list of objects onto any 2D context at page width w (exports, thumbnails). */
  function render(ctx, strokes, w, h) {
    for (const s of strokes) draw(ctx, s, w, h);
  }

  paintBar();
  layout();

  const api = {
    attach, attachViewport, detachWithin, setVisible,
    repaint: () => { for (const p of A.pages.values()) if (p.el.isConnected) paintLayer(p); },
    setTool, get tool() { return A.tool; },
    onTool: (fn) => A.listeners.add(fn),
    onSave: (fn) => A.saveState.add(fn),
    onChange: (fn) => { A.onChange = fn; },
    onPan: (fn) => { A.camPan = fn; },
    setHotkeys: (on) => { A.hotkeys = on; },
    setOpen, flush, insertImage, setCamera, render, bbox: (s, w, h) => bbox(s, w, h),
    get pending() { return A.pending; },
    page: (doc, page) => A.pages.get(`${doc}|${page}`),
    quiet: (v) => { A.quietSaves = v; },
    el: bar,
  };
  // The newest annotator on the page answers Alt+P / Alt+H / Alt+X (shortcuts.js).
  window.pwtInk = api;
  return api;
}
