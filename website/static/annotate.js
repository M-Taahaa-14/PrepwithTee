/* annotate.js — the floating annotation bar + a drawing layer on every page.
 *
 *   const ann = createAnnotator({ mount: document.body });
 *   ann.attach(pageEl, "paper:123", 4);   // any positioned element = one "page"
 *
 * Tools: pointer (scroll/click), select (move · edit text · delete · recolour),
 * pen, highlighter, eraser (partial - cuts through strokes and shapes - or
 * whole objects), line, arrow, rectangle, ellipse, text; 6 colours, 3 sizes;
 * undo/redo; clear page. Strokes are stored as fractions of the page (so zoom
 * never matters) and saved per page to /api/annotations, debounced.
 *
 * Pens (Wacom, Surface, Apple Pencil): the layer is touch-action:none whenever a
 * drawing tool is on, so the browser never turns a pen stroke into a scroll
 * (it used to, after a short stroke, with pan-y allowed). Once a stylus has been
 * seen, a finger or palm does not draw: it scrolls the page, done here by hand.
 * Drawing is frame-throttled over a cached image of the finished strokes, so a
 * long stroke on a busy page stays smooth.
 * Keys: V pointer · S select · P pen · H highlighter · E eraser · T text ·
 *       Delete remove selection · Ctrl+Z / Ctrl+Y.
 */
const COLORS = ["#1d4ed8", "#111827", "#dc2626", "#16a34a", "#f59e0b", "#9333ea"];
const SIZES = [0.0022, 0.0042, 0.0085];            // fraction of page width
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
  grip: '<circle cx="9" cy="7" r="1.2"/><circle cx="15" cy="7" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="17" r="1.2"/><circle cx="15" cy="17" r="1.2"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const TOOLS = [["pointer", "Pointer — scroll and click (V)"], ["select", "Select — move, edit, delete (S)"],
  ["pen", "Pen (P)"], ["marker", "Highlighter (H)"], ["eraser", "Eraser (E) — tap again for options"]];
const SHAPES = [["line", "Line"], ["arrow", "Arrow"], ["rect", "Rectangle"],
  ["ellipse", "Ellipse"], ["text", "Text (T)"]];
const DRAWS = new Set(["select", "pen", "marker", "eraser", "line", "arrow", "rect", "ellipse", "text"]);
const clamp = (v) => Math.min(1, Math.max(0, v));

async function req(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`annotations ${r.status}`);
  return r.json();
}

export function createAnnotator({ mount = document.body, position = "bottom" } = {}) {
  const A = {
    tool: "pointer", color: COLORS[0], size: 1, collapsed: false, eraseMode: "partial",
    docs: new Map(),      // doc -> Promise<{page: strokes[]}>
    pages: new Map(),     // `${doc}|${page}` -> { el, canvas, strokes, doc, page }
    undo: [], redo: [], saveTimers: new Map(), penSeen: false, listeners: new Set(),
    sel: null,            // { key, i } - the selected object
  };
  try {
    const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
    if (COLORS.includes(s.color)) A.color = s.color;
    if (s.size >= 0 && s.size < SIZES.length) A.size = s.size;
    if (s.pos === "top" || s.pos === "bottom") position = s.pos;
    if (s.erase === "stroke" || s.erase === "partial") A.eraseMode = s.erase;
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
    <div class="an-group">${TOOLS.map(([k, t]) => k === "eraser" ? `
      <div class="an-pop-wrap">
        <button type="button" data-tool="eraser" title="${t}" aria-label="${t}" aria-pressed="false">${svg("eraser")}<b class="an-mode"></b></button>
        <div class="an-pop an-pop-list" data-pop="eraser" hidden>
          <button type="button" data-erase="partial"><b>Partial eraser</b><span>Rub out just the part you touch</span></button>
          <button type="button" data-erase="stroke"><b>Object eraser</b><span>Remove a whole stroke or shape</span></button>
        </div>
      </div>` : `
      <button type="button" data-tool="${k}" title="${t}" aria-label="${t}" aria-pressed="false">${svg(k)}</button>`).join("")}
    </div>
    <span class="an-sep" aria-hidden="true"></span>
    <div class="an-group an-shapes">${SHAPES.map(([k, t]) => `
      <button type="button" data-tool="${k}" title="${t}" aria-label="${t}" aria-pressed="false">${svg(k)}</button>`).join("")}
    </div>
    <span class="an-sep" aria-hidden="true"></span>
    <div class="an-pop-wrap">
      <button type="button" class="an-swatch" data-an="colors" title="Colour" aria-label="Colour"
              aria-haspopup="true" aria-expanded="false"><i></i></button>
      <div class="an-pop" data-pop="colors" hidden>${COLORS.map((c) => `
        <button type="button" data-color="${c}" style="--c:${c}" aria-label="Colour ${c}"></button>`).join("")}</div>
    </div>
    <div class="an-pop-wrap">
      <button type="button" class="an-size" data-an="sizes" title="Thickness" aria-label="Thickness"
              aria-haspopup="true" aria-expanded="false"><i></i></button>
      <div class="an-pop" data-pop="sizes" hidden>${SIZES.map((_, i) => `
        <button type="button" data-size="${i}" aria-label="Size ${i + 1}"><i style="--d:${4 + i * 4}px"></i></button>`).join("")}</div>
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
      localStorage.setItem("pwt-annot", JSON.stringify({ ...s, color: A.color, size: A.size,
                                                         pos: bar.dataset.pos, erase: A.eraseMode }));
    } catch { /* ignore */ }
  }

  function paintBar() {
    bar.querySelectorAll("[data-tool]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.tool === A.tool)));
    bar.querySelector(".an-swatch i").style.background = selected()?.c || A.color;
    bar.querySelector(".an-size i").style.setProperty("--d", `${4 + A.size * 4}px`);
    bar.querySelectorAll("[data-color]").forEach((b) => b.classList.toggle("is-on", b.dataset.color === A.color));
    bar.querySelectorAll("[data-size]").forEach((b) => b.classList.toggle("is-on", +b.dataset.size === A.size));
    bar.querySelectorAll("[data-erase]").forEach((b) => b.classList.toggle("is-on", b.dataset.erase === A.eraseMode));
    bar.querySelector(".an-mode").textContent = A.eraseMode === "partial" ? "" : "•";
    bar.querySelector('[data-tool="eraser"]').title =
      `${A.eraseMode === "partial" ? "Partial" : "Object"} eraser (E) — tap again for options`;
    bar.querySelector('[data-an="undo"]').disabled = !A.undo.length;
    bar.querySelector('[data-an="redo"]').disabled = !A.redo.length;
    bar.querySelector('[data-an="delete"]').hidden = !A.sel;
    const drawing = DRAWS.has(A.tool);
    document.documentElement.classList.toggle("an-drawing", drawing);
    document.documentElement.dataset.anTool = A.tool;
    for (const p of A.pages.values()) paintLayer(p);
    A.listeners.forEach((fn) => fn(A.tool));
  }

  function setTool(t) {
    if (t !== "select") A.sel = null;
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

  bar.addEventListener("click", (e) => {
    const er = e.target.closest("[data-erase]");
    if (er) { A.eraseMode = er.dataset.erase; persist(); closePops(); A.tool = "eraser"; return paintBar(); }
    const t = e.target.closest("[data-tool]");
    if (t) {
      const k = t.dataset.tool;
      if (k === "eraser" && A.tool === "eraser") {            // second tap: eraser options
        const pop = bar.querySelector('[data-pop="eraser"]');
        const open = pop.hidden;
        closePops();
        pop.hidden = !open;
        return;
      }
      return setTool(A.tool === k && k !== "pointer" ? "pointer" : k);
    }
    const c = e.target.closest("[data-color]");
    if (c) {
      A.color = c.dataset.color; persist(); closePops();
      const s = selected();
      if (s) { mutate(A.sel.key, (list) => { list[A.sel.i] = { ...s, c: A.color }; }); return paintBar(); }
      if (!DRAWS.has(A.tool) || A.tool === "eraser" || A.tool === "select") A.tool = "pen";
      return paintBar();
    }
    const s = e.target.closest("[data-size]");
    if (s) { A.size = +s.dataset.size; persist(); closePops(); return paintBar(); }
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
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      if (A.undo.length) { e.preventDefault(); doUndo(); }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) {
      if (A.redo.length) { e.preventDefault(); doRedo(); }
      return;
    }
    if (A.sel && (e.key === "Delete" || e.key === "Backspace")) { e.preventDefault(); deleteSelected(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey || A.collapsed) return;
    const k = { v: "pointer", s: "select", p: "pen", h: "marker", e: "eraser", t: "text" }[e.key.toLowerCase()];
    if (k && A.hotkeys !== false) { setTool(k); }
    if (e.key === "Escape") { if (A.sel) { A.sel = null; paintBar(); } else if (A.tool !== "pointer") setTool("pointer"); }
  });

  // ── pages ──────────────────────────────────────────────────────────────────
  function load(doc) {
    if (!A.docs.has(doc)) {
      A.docs.set(doc, req("GET", `/api/annotations?doc=${encodeURIComponent(doc)}`)
        .then((d) => d.pages || {}).catch(() => ({})));
    }
    return A.docs.get(doc);
  }

  async function attach(el, doc, page) {
    const key = `${doc}|${page}`;
    const prev = A.pages.get(key);
    const canvas = document.createElement("canvas");
    canvas.className = "an-layer";
    el.appendChild(canvas);
    const p = { el, canvas, doc, page, key, strokes: prev ? prev.strokes : null };
    A.pages.set(key, p);
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
    for (const [k, p] of A.pages) if (root.contains(p.el) || !p.el.isConnected) A.pages.delete(k);
  }

  function size(p) {
    const w = p.el.clientWidth, h = p.el.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    let changed = false;
    if (p.canvas.width !== Math.round(w * dpr) || p.canvas.height !== Math.round(h * dpr)) {
      p.canvas.width = Math.round(w * dpr);
      p.canvas.height = Math.round(h * dpr);
      changed = true;
    }
    return { w, h, dpr, changed };
  }

  /** Full repaint: rebuild the cached image of the finished strokes, then show it. */
  function paintLayer(p) {
    if (!p.strokes) return;
    const { w, h, dpr } = size(p);
    if (!p.base) p.base = document.createElement("canvas");
    p.base.width = p.canvas.width;
    p.base.height = p.canvas.height;
    const b = p.base.getContext("2d");
    b.setTransform(dpr, 0, 0, dpr, 0, 0);
    b.clearRect(0, 0, w, h);
    for (const s of p.strokes) draw(b, s, w, h);
    blit(p);
    p.canvas.classList.toggle("is-active", DRAWS.has(A.tool));
    p.canvas.dataset.tool = A.tool === "eraser" ? `eraser-${A.eraseMode}` : A.tool;
  }

  /** Cheap per-frame paint: cached strokes + the stroke being drawn + selection. */
  function blit(p) {
    const { w, h, dpr, changed } = size(p);
    if (changed || !p.base) return paintLayer(p);
    const ctx = p.canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);
    ctx.drawImage(p.base, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (p.live) draw(ctx, p.live, w, h);
    if (A.sel?.key === p.key && p.strokes[A.sel.i]) drawSelection(ctx, p.strokes[A.sel.i], w, h);
    if (p.eraserAt && A.tool === "eraser") {
      ctx.beginPath();
      ctx.arc(p.eraserAt[0] * w, p.eraserAt[1] * h, ERASER_R[A.size] * w, 0, Math.PI * 2);
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
    const fs = Math.max(10, s.s * w);
    return { fs, font: `600 ${fs}px "Hanken Grotesk", system-ui, sans-serif` };
  }

  function draw(ctx, s, w, h) {
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = s.c;
    ctx.fillStyle = s.c;
    const lw = Math.max(1, s.w * w);
    if (s.t === "marker") {
      ctx.globalAlpha = 0.32;
      ctx.globalCompositeOperation = "multiply";
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
      const { fs, font } = textFont(s, w);
      ctx.font = font;
      ctx.textBaseline = "top";
      String(s.txt || "").split("\n").forEach((line, i) => ctx.fillText(line, s.x * w, s.y * h + i * fs * 1.25));
    }
    ctx.restore();
  }

  // ── geometry ───────────────────────────────────────────────────────────────
  const measure = document.createElement("canvas").getContext("2d");

  /** Bounding box of an object, in page fractions. */
  function bbox(s, w, h) {
    if (s.t === "text") {
      const { fs, font } = textFont(s, w);
      measure.font = font;
      const lines = String(s.txt || "").split("\n");
      const tw = Math.max(...lines.map((l) => measure.measureText(l).width));
      return [s.x, s.y, s.x + tw / w, s.y + (lines.length * fs * 1.25) / h];
    }
    const xs = s.pts ? s.pts.map((q) => q[0]) : [s.a[0], s.b[0]];
    const ys = s.pts ? s.pts.map((q) => q[1]) : [s.a[1], s.b[1]];
    const pad = (s.t === "marker" ? s.w * 1.6 : s.w / 2);
    return [Math.min(...xs) - pad, Math.min(...ys) - pad * (w / h), Math.max(...xs) + pad, Math.max(...ys) + pad * (w / h)];
  }

  function drawSelection(ctx, s, w, h) {
    const [x0, y0, x1, y1] = bbox(s, w, h);
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = "#7c5cf0";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x0 * w - 5, y0 * h - 5, (x1 - x0) * w + 10, (y1 - y0) * h + 10);
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

  function translate(s, dx, dy) {
    const mv = (q) => [clamp(q[0] + dx), clamp(q[1] + dy), ...q.slice(2)];
    if (s.pts) return { ...s, pts: s.pts.map(mv) };
    if (s.t === "text") return { ...s, x: clamp(s.x + dx), y: clamp(s.y + dy) };
    return { ...s, a: mv(s.a), b: mv(s.b) };
  }

  function pt(p, e) {
    const r = p.canvas.getBoundingClientRect();
    const pressure = e.pointerType === "pen" && e.pressure > 0 ? e.pressure : 0.5;
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
      else if (A.tool === "pen" || A.tool === "marker") p.live = { t: A.tool, c: A.color, w: sw, pts: [q] };
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
      if (!p.live && !p.erasing && !p.drag) return;
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
          if (Math.hypot(q[0] - last[0], q[1] - last[1]) > 0.0008) p.live.pts.push(q);
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
        if (p.drag.moved) commit(p, p.drag.before);
        p.drag = null;
      } else if (p.live) {
        const s = p.live;
        p.live = null;
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
      if (i >= 0) editText(p, i);
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
    const i = topmost(p, q, w, h);
    const prevKey = A.sel?.key;
    A.sel = i >= 0 ? { key: p.key, i } : null;
    if (prevKey && prevKey !== p.key) { const o = A.pages.get(prevKey); if (o) blit(o); }
    if (i >= 0) {
      const s = p.strokes[i];
      p.drag = { start: q, orig: s, before: p.strokes.slice(), moved: false };
      if (s.c) { A.color = s.c; }
    }
    paintBar();
  }

  function moveSelect(p, q) {
    const d = p.drag;
    const dx = q[0] - d.start[0], dy = q[1] - d.start[1];
    if (!d.moved && Math.hypot(dx, dy) < 0.002) return;
    d.moved = true;
    p.strokes[A.sel.i] = translate(d.orig, dx, dy);
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
    const r = ERASER_R[A.size];
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
  function startText(p, e, q) {
    const { w, h } = size(p);
    const i = topmost(p, q, w, h, (s) => s.t === "text");
    if (i >= 0) return editText(p, i);                 // clicking existing text edits it
    textBox(p, { x: q[0], y: q[1], c: A.color, s: SIZES[A.size] * 5, txt: "" }, null);
  }

  function editText(p, i) {
    const s = p.strokes[i];
    textBox(p, s, i);
  }

  function textBox(p, s, index) {
    const box = document.createElement("textarea");
    box.className = "an-text";
    box.rows = Math.max(1, String(s.txt || "").split("\n").length);
    box.placeholder = "Type · Enter to finish · Shift+Enter new line";
    box.value = s.txt || "";
    const fs = Math.max(12, s.s * p.el.clientWidth);
    Object.assign(box.style, { left: `${s.x * 100}%`, top: `${s.y * 100}%`, color: s.c, fontSize: `${fs}px` });
    // hide the canvas copy while it is being edited
    let hidden = null;
    if (index != null) {
      hidden = p.strokes[index];
      p.strokes = p.strokes.map((x, j) => (j === index ? { ...x, txt: "" } : x));
      paintLayer(p);
      p.strokes = p.strokes.map((x, j) => (j === index ? hidden : x));
    }
    p.el.appendChild(box);
    // focus now, not on a timer: the first key typed must not reach the tool hotkeys
    box.focus({ preventScroll: true });
    box.select();
    setTimeout(() => { if (document.activeElement !== box) box.focus({ preventScroll: true }); });
    let finished = false;
    const done = (save) => {
      if (finished) return;
      finished = true;
      const txt = box.value.replace(/\s+$/, "");
      box.remove();
      const before = p.strokes.slice();
      if (index == null) {
        if (save && txt) { p.strokes.push({ t: "text", c: s.c, s: s.s, x: s.x, y: s.y, txt: txt.slice(0, 500) }); commit(p, before); }
      } else if (save && txt !== hidden.txt) {
        if (txt) p.strokes[index] = { ...hidden, txt: txt.slice(0, 500) };
        else { p.strokes.splice(index, 1); A.sel = null; }
        commit(p, before);
      }
      paintLayer(p);
    };
    box.addEventListener("input", () => { box.rows = Math.max(1, box.value.split("\n").length); });
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); done(true); }
      if (ev.key === "Escape") done(false);
      ev.stopPropagation();
    });
    box.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    box.addEventListener("blur", () => done(true));
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
  if (window.innerWidth < 700 && remembered !== true) setCollapsed(true);
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

  return {
    attach, detachWithin, setVisible,
    repaint: () => { for (const p of A.pages.values()) if (p.el.isConnected) paintLayer(p); },
    setTool, get tool() { return A.tool; },
    onTool: (fn) => A.listeners.add(fn),
    setHotkeys: (on) => { A.hotkeys = on; },
    el: bar,
  };
}
