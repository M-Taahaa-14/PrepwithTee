/* annotate.js — the floating annotation bar + a drawing layer on every page.
 *
 *   const ann = createAnnotator({ mount: document.body });
 *   ann.attach(pageEl, "paper:123", 4);   // any positioned element = one "page"
 *
 * Tools: pen, highlighter, eraser (whole strokes), line, arrow, rectangle,
 * ellipse, text; 6 colours, 3 sizes; undo/redo; clear page. Strokes are stored
 * as fractions of the page (so zoom never matters) and saved per page to
 * /api/annotations, debounced. A stylus draws and a finger scrolls once a pen
 * has been seen (palm rejection); a mouse or finger draws otherwise.
 * Keys: V pointer · P pen · H highlighter · E eraser · T text · Ctrl+Z / Ctrl+Y.
 */
const COLORS = ["#1d4ed8", "#111827", "#dc2626", "#16a34a", "#f59e0b", "#9333ea"];
const SIZES = [0.0022, 0.0042, 0.0085];            // fraction of page width
const ICON = {
  pointer: '<path d="M5 3l14 8-6 2-2 6z"/>',
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
  collapse: '<path d="M6 9l6 6 6-6"/>',
  grip: '<circle cx="9" cy="7" r="1.2"/><circle cx="15" cy="7" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="17" r="1.2"/><circle cx="15" cy="17" r="1.2"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;
const TOOLS = [["pointer", "Pointer — scroll and click (V)"], ["pen", "Pen (P)"],
  ["marker", "Highlighter (H)"], ["eraser", "Eraser (E)"]];
const SHAPES = [["line", "Line"], ["arrow", "Arrow"], ["rect", "Rectangle"],
  ["ellipse", "Ellipse"], ["text", "Text (T)"]];
const DRAWS = new Set(["pen", "marker", "eraser", "line", "arrow", "rect", "ellipse", "text"]);

async function req(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`annotations ${r.status}`);
  return r.json();
}

export function createAnnotator({ mount = document.body, position = "bottom" } = {}) {
  const A = {
    tool: "pointer", color: COLORS[0], size: 1, collapsed: false,
    docs: new Map(),      // doc -> Promise<{page: strokes[]}>
    pages: new Map(),     // `${doc}|${page}` -> { el, canvas, strokes, doc, page }
    undo: [], redo: [], saveTimers: new Map(), penSeen: false, listeners: new Set(),
  };
  try {
    const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
    if (COLORS.includes(s.color)) A.color = s.color;
    if (s.size >= 0 && s.size < SIZES.length) A.size = s.size;
    if (s.pos === "top" || s.pos === "bottom") position = s.pos;
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
      localStorage.setItem("pwt-annot", JSON.stringify({ ...s, color: A.color, size: A.size, pos: bar.dataset.pos }));
    } catch { /* ignore */ }
  }

  function paintBar() {
    bar.querySelectorAll("[data-tool]").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.tool === A.tool)));
    bar.querySelector(".an-swatch i").style.background = A.color;
    bar.querySelector(".an-size i").style.setProperty("--d", `${4 + A.size * 4}px`);
    bar.querySelectorAll("[data-color]").forEach((b) => b.classList.toggle("is-on", b.dataset.color === A.color));
    bar.querySelectorAll("[data-size]").forEach((b) => b.classList.toggle("is-on", +b.dataset.size === A.size));
    bar.querySelector('[data-an="undo"]').disabled = !A.undo.length;
    bar.querySelector('[data-an="redo"]').disabled = !A.redo.length;
    const drawing = DRAWS.has(A.tool);
    document.documentElement.classList.toggle("an-drawing", drawing);
    document.documentElement.dataset.anTool = A.tool;
    for (const p of A.pages.values()) paintLayer(p);
    A.listeners.forEach((fn) => fn(A.tool));
  }

  function setTool(t) {
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
    const t = e.target.closest("[data-tool]");
    if (t) return setTool(A.tool === t.dataset.tool && t.dataset.tool !== "pointer" ? "pointer" : t.dataset.tool);
    const c = e.target.closest("[data-color]");
    if (c) { A.color = c.dataset.color; persist(); closePops(); if (!DRAWS.has(A.tool) || A.tool === "eraser") A.tool = "pen"; return paintBar(); }
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
    else if (act === "collapse") {
      setCollapsed(true);
      try {
        const s = JSON.parse(localStorage.getItem("pwt-annot") || "{}");
        localStorage.setItem("pwt-annot", JSON.stringify({ ...s, open: false }));
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
    if (e.ctrlKey || e.metaKey || e.altKey || A.collapsed) return;
    const k = { v: "pointer", p: "pen", h: "marker", e: "eraser", t: "text" }[e.key.toLowerCase()];
    if (k && A.hotkeys !== false) { setTool(k); }
    if (e.key === "Escape" && A.tool !== "pointer") setTool("pointer");
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
    if (p.canvas.width !== Math.round(w * dpr) || p.canvas.height !== Math.round(h * dpr)) {
      p.canvas.width = Math.round(w * dpr);
      p.canvas.height = Math.round(h * dpr);
    }
    return { w, h, dpr };
  }

  function paintLayer(p) {
    if (!p.strokes) return;
    const { w, h, dpr } = size(p);
    const ctx = p.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    for (const s of p.strokes) draw(ctx, s, w, h);
    if (p.live) draw(ctx, p.live, w, h);
    p.canvas.classList.toggle("is-active", DRAWS.has(A.tool));
    p.canvas.dataset.tool = A.tool;
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
      // Quadratic curves through the midpoints: smooth, and each segment's
      // width follows the pen pressure recorded at that point.
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i];
        const prev = pts[i - 2] || a;
        const m0 = [(prev[0] + a[0]) / 2 * w, (prev[1] + a[1]) / 2 * h];
        const m1 = [(a[0] + b[0]) / 2 * w, (a[1] + b[1]) / 2 * h];
        ctx.beginPath();
        ctx.lineWidth = s.t === "marker" ? lw * 3.2 : lw * (0.55 + 0.9 * (a[2] ?? 0.5));
        ctx.moveTo(m0[0], m0[1]);
        ctx.quadraticCurveTo(a[0] * w, a[1] * h, m1[0], m1[1]);
        ctx.stroke();
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
      const fs = Math.max(10, s.s * w);
      ctx.font = `600 ${fs}px "Hanken Grotesk", system-ui, sans-serif`;
      ctx.textBaseline = "top";
      String(s.txt || "").split("\n").forEach((line, i) => ctx.fillText(line, s.x * w, s.y * h + i * fs * 1.25));
    }
    ctx.restore();
  }

  function pt(p, e) {
    const r = p.canvas.getBoundingClientRect();
    const pressure = e.pointerType === "pen" ? (e.pressure || 0.5) : 0.5;
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
            Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)), +pressure.toFixed(2)];
  }

  function bind(p) {
    const c = p.canvas;
    c.addEventListener("pointerdown", (e) => {
      if (!DRAWS.has(A.tool) || e.button > 0 || !p.strokes) return;
      if (e.pointerType === "pen") { A.penSeen = true; document.documentElement.classList.add("an-pen"); }
      if (A.penSeen && e.pointerType === "touch") return;      // palm / finger scrolls
      e.preventDefault();
      if (A.tool === "text") return startText(p, e);
      c.setPointerCapture(e.pointerId);
      const q = pt(p, e);
      const w = SIZES[A.size];
      if (A.tool === "eraser") { p.erasing = []; eraseAt(p, q); }
      else if (A.tool === "pen" || A.tool === "marker") p.live = { t: A.tool, c: A.color, w, pts: [q] };
      else p.live = { t: A.tool, c: A.color, w, a: q.slice(0, 2), b: q.slice(0, 2) };
      paintLayer(p);
    });
    c.addEventListener("pointermove", (e) => {
      if (!p.live && !p.erasing) return;
      const co = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
      const events = co.length ? co : [e];
      for (const ev of events) {
        const q = pt(p, ev);
        if (p.erasing) eraseAt(p, q);
        else if (p.live.pts) {
          const last = p.live.pts[p.live.pts.length - 1];
          if (Math.hypot(q[0] - last[0], q[1] - last[1]) > 0.0012) p.live.pts.push(q);
        } else p.live.b = q.slice(0, 2);
      }
      paintLayer(p);
    });
    const end = () => {
      if (p.erasing) {
        if (p.erasing.length) commit(p, p.erasing.before);
        p.erasing = null;
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
  }

  function segDist(q, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
    return Math.hypot(q[0] - (a[0] + t * dx), q[1] - (a[1] + t * dy));
  }

  function hit(s, q, r) {
    if (s.pts) return s.pts.some((a, i) => segDist(q, a, s.pts[i + 1] || a) < r + s.w);
    if (s.t === "text") return Math.abs(q[0] - s.x) < 0.2 && q[1] >= s.y - r && q[1] <= s.y + s.s * 1.6;
    if (s.t === "rect" || s.t === "ellipse") {
      const x0 = Math.min(s.a[0], s.b[0]), x1 = Math.max(s.a[0], s.b[0]);
      const y0 = Math.min(s.a[1], s.b[1]), y1 = Math.max(s.a[1], s.b[1]);
      return q[0] > x0 - r && q[0] < x1 + r && q[1] > y0 - r && q[1] < y1 + r
        && !(q[0] > x0 + r && q[0] < x1 - r && q[1] > y0 + r && q[1] < y1 - r);
    }
    return segDist(q, s.a, s.b) < r + s.w;
  }

  function eraseAt(p, q) {
    const keep = p.strokes.filter((s) => !hit(s, q, 0.012));
    if (keep.length !== p.strokes.length) {
      if (!p.erasing.before) p.erasing.before = p.strokes.slice();
      p.erasing.push(1);
      p.strokes = keep;
    }
  }

  function startText(p, e) {
    const q = pt(p, e);
    const box = document.createElement("textarea");
    box.className = "an-text";
    box.rows = 1;
    box.placeholder = "Type, then Enter";
    const fs = Math.max(12, SIZES[A.size] * 5 * p.el.clientWidth);
    Object.assign(box.style, { left: `${q[0] * 100}%`, top: `${q[1] * 100}%`, color: A.color,
                               fontSize: `${fs}px` });
    p.el.appendChild(box);
    setTimeout(() => box.focus());
    const done = (save) => {
      const txt = box.value.trim();
      box.remove();
      if (save && txt) {
        const before = p.strokes.slice();
        p.strokes.push({ t: "text", c: A.color, s: SIZES[A.size] * 5, x: q[0], y: q[1], txt: txt.slice(0, 500) });
        commit(p, before);
        paintLayer(p);
      }
    };
    box.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); done(true); }
      if (ev.key === "Escape") done(false);
      ev.stopPropagation();
    });
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
