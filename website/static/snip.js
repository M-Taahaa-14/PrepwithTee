/* snip.js — "snip part of the page" for feedback and issue reports.
 *
 *   const { snip, fileToSnip } = await import("/snip.js?v=...");
 *   const dataUrl = await snip({ hide: [feedbackPanel] });   // null if cancelled
 *
 * 1. Renders what is on screen right now with modern-screenshot (jsDelivr). It
 *    draws through the browser's own SVG renderer, so color-mix() and the other
 *    modern CSS on this site survive (classic html2canvas throws on them), and
 *    scrolled panes (paper viewers) keep their scroll position.
 *    If that fails, the browser's "share this tab" capture is the fallback.
 * 2. Full-screen overlay: drag a box (mouse, pen or finger), or "Whole screen".
 * 3. Optional red pen to circle the problem, then "Attach". Esc cancels.
 * Output: a JPEG data: URL, at most MAX_W px wide (the server takes <= 3 MB).
 */
const LIB = "https://cdn.jsdelivr.net/npm/modern-screenshot@4.7.0/dist/index.mjs";
const MAX_W = 1600;
const QUALITY = 0.86;

let lib = null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Text that sits on one line on screen: the SVG renderer measures text a
 *  hair wider, so without this buttons and pills wrap in the picture. */
function markOneLine(h) {
  const marked = [];
  for (const el of document.body.querySelectorAll("*")) {
    let text = false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) { text = true; break; }
    if (!text) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || r.bottom < 0 || r.top > h) continue;
    const cs = getComputedStyle(el);
    if (cs.whiteSpace !== "normal") continue;
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.25;
    const inner = r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
      - parseFloat(cs.borderTopWidth) - parseFloat(cs.borderBottomWidth);
    if (inner < lh * 1.6) { el.setAttribute("data-snip-1line", ""); marked.push(el); }
  }
  return () => marked.forEach((el) => el.removeAttribute("data-snip-1line"));
}

async function shootDom() {
  lib = lib || await import(LIB);
  const w = window.innerWidth, h = window.innerHeight;
  const root = document.documentElement;
  const unmark = markOneLine(h);
  try {
    return await render(root, w, h);
  } finally {
    unmark();
  }
}

/** The colour behind the page: body's, else html's, else white (never transparent). */
function pageBg() {
  for (const el of [document.body, document.documentElement]) {
    const c = getComputedStyle(el).backgroundColor;
    if (c && c !== "transparent" && !/rgba\(.*,\s*0\)$/.test(c)) return c;
  }
  return "#ffffff";
}

async function render(root, w, h) {
  const canvas = await lib.domToCanvas(root, {
    onCloneEachNode: (n) => {
      if (n.nodeType === 1 && n.hasAttribute("data-snip-1line")) {
        n.style.whiteSpace = "nowrap";
        n.removeAttribute("data-snip-1line");
      }
    },
    width: w, height: h,
    scale: Math.min(window.devicePixelRatio || 1, 2),
    backgroundColor: pageBg(),
    // Show the viewport, not the top of the document.
    style: { transform: `translate(${-window.scrollX}px, ${-window.scrollY}px)`, transformOrigin: "0 0" },
    filter: (n) => !(n.classList && (n.classList.contains("snip-ui") || n.hasAttribute?.("data-snip-hide"))),
    timeout: 12000,
  });
  return canvas;
}

async function shootScreen() {
  // Asks the browser for this tab ("Share this tab?"): exact pixels, one click.
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: { displaySurface: "browser" }, audio: false, preferCurrentTab: true, selfBrowserSurface: "include",
  });
  try {
    const v = document.createElement("video");
    v.srcObject = stream;
    v.muted = true;
    await v.play();
    await sleep(250);
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    return c;
  } finally {
    stream.getTracks().forEach((t) => t.stop());
  }
}

function busy(text) {
  const el = document.createElement("div");
  el.className = "snip-ui snip-busy";
  el.setAttribute("role", "status");
  el.innerHTML = `<span class="snip-spin" aria-hidden="true"></span>${text}`;
  document.body.appendChild(el);
  return el;
}

function toJpeg(canvas, sx, sy, sw, sh, ink) {
  const k = Math.min(1, MAX_W / sw);
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(sw * k));
  out.height = Math.max(1, Math.round(sh * k));
  const g = out.getContext("2d");
  g.fillStyle = "#fff";
  g.fillRect(0, 0, out.width, out.height);
  g.drawImage(canvas, sx, sy, sw, sh, 0, 0, out.width, out.height);
  if (ink) g.drawImage(ink, 0, 0, out.width, out.height);
  return out.toDataURL("image/jpeg", QUALITY);
}

/** The overlay: pick an area of `canvas` (a picture of the viewport). */
function pick(canvas) {
  return new Promise((resolve) => {
    const W = window.innerWidth, H = window.innerHeight;
    const kx = canvas.width / W, ky = canvas.height / H;
    const ui = document.createElement("div");
    ui.className = "snip-ui snip-overlay";
    ui.setAttribute("role", "dialog");
    ui.setAttribute("aria-modal", "true");
    ui.setAttribute("aria-label", "Snip part of the page");
    const shot = document.createElement("canvas");
    shot.className = "snip-shot";
    shot.width = canvas.width;
    shot.height = canvas.height;
    shot.getContext("2d").drawImage(canvas, 0, 0);
    ui.innerHTML = `
      <div class="snip-veil"></div>
      <div class="snip-dim" hidden></div><div class="snip-dim" hidden></div><div class="snip-dim" hidden></div><div class="snip-dim" hidden></div>
      <div class="snip-box" hidden><canvas class="snip-ink"></canvas><span class="snip-size"></span></div>
      <div class="snip-bar" role="toolbar" aria-label="Snip">
        <span class="snip-tip" data-tip>✂️ <b>Drag over the part you want to show us</b></span>
        <button type="button" data-act="pen" hidden aria-pressed="false" title="Draw in red to point at the problem">🖍️ Mark it</button>
        <button type="button" data-act="redo" hidden>↺ Snip again</button>
        <button type="button" data-act="all">🖥️ Whole screen</button>
        <button type="button" data-act="ok" class="is-main" hidden>✓ Attach</button>
        <button type="button" data-act="cancel">Cancel</button>
      </div>`;
    ui.prepend(shot);
    document.body.appendChild(ui);
    document.documentElement.classList.add("snip-lock");
    const box = ui.querySelector(".snip-box");
    const ink = ui.querySelector(".snip-ink");
    const size = ui.querySelector(".snip-size");
    const veil = ui.querySelector(".snip-veil");
    const tip = ui.querySelector("[data-tip]");
    const btn = (a) => ui.querySelector(`[data-act=${a}]`);
    let sel = null, start = null, pen = false, drawing = null;

    function place(r) {
      sel = r;
      box.hidden = false;
      veil.classList.add("is-cut");
      Object.assign(box.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
      // Darken everything around the selection: top, bottom, left, right.
      const d = ui.querySelectorAll(".snip-dim");
      const px = (v) => `${Math.max(0, v)}px`;
      [[0, 0, W, r.y], [0, r.y + r.h, W, H - r.y - r.h], [0, r.y, r.x, r.h], [r.x + r.w, r.y, W - r.x - r.w, r.h]]
        .forEach(([x, y, w, h], i) => {
          d[i].hidden = false;
          Object.assign(d[i].style, { left: px(x), top: px(y), width: px(w), height: px(h) });
        });
      size.textContent = `${Math.round(r.w)} × ${Math.round(r.h)}`;
    }
    function ready() {
      ink.width = Math.round(sel.w * kx);
      ink.height = Math.round(sel.h * ky);
      ["pen", "redo", "ok"].forEach((a) => { btn(a).hidden = false; });
      tip.innerHTML = "Looks right? <b>Attach</b> it, or <b>Mark it</b> to circle the problem";
      btn("ok").focus();
    }
    function reset() {
      sel = null; pen = false;
      box.hidden = true;
      veil.classList.remove("is-cut");
      ui.querySelectorAll(".snip-dim").forEach((x) => { x.hidden = true; });
      ui.classList.remove("is-pen");
      btn("pen").setAttribute("aria-pressed", "false");
      ["pen", "redo", "ok"].forEach((a) => { btn(a).hidden = true; });
      tip.innerHTML = "✂️ <b>Drag over the part you want to show us</b>";
    }
    function done(v) {
      ui.remove();
      document.documentElement.classList.remove("snip-lock");
      window.removeEventListener("keydown", onKey, true);
      resolve(v);
    }
    function finish() {
      if (!sel) return;
      done(toJpeg(canvas, sel.x * kx, sel.y * ky, sel.w * kx, sel.h * ky, ink));
    }
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); done(null); }
      else if (e.key === "Enter" && sel) { e.preventDefault(); e.stopImmediatePropagation(); finish(); }
    };
    window.addEventListener("keydown", onKey, true);

    ui.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".snip-bar")) return;
      if (pen && sel && e.target === ink) {
        const r = ink.getBoundingClientRect();
        drawing = { r };
        const g = ink.getContext("2d");
        g.strokeStyle = "#e11d48";
        g.lineWidth = Math.max(3, 4 * kx);
        g.lineCap = g.lineJoin = "round";
        g.beginPath();
        g.moveTo((e.clientX - r.left) * kx, (e.clientY - r.top) * ky);
        ink.setPointerCapture(e.pointerId);
        return;
      }
      if (sel) reset();
      start = { x: e.clientX, y: e.clientY };
      ui.setPointerCapture(e.pointerId);
    });
    ui.addEventListener("pointermove", (e) => {
      if (drawing) {
        const g = ink.getContext("2d");
        g.lineTo((e.clientX - drawing.r.left) * kx, (e.clientY - drawing.r.top) * ky);
        g.stroke();
        return;
      }
      if (!start) return;
      const x = Math.max(0, Math.min(start.x, e.clientX)), y = Math.max(0, Math.min(start.y, e.clientY));
      place({ x, y, w: Math.min(W, Math.max(start.x, e.clientX)) - x, h: Math.min(H, Math.max(start.y, e.clientY)) - y });
    });
    ui.addEventListener("pointerup", () => {
      if (drawing) { drawing = null; return; }
      if (!start) return;
      start = null;
      if (!sel || sel.w < 12 || sel.h < 12) { reset(); return; }
      ready();
    });
    ui.querySelector(".snip-bar").addEventListener("click", (e) => {
      const a = e.target.closest("[data-act]")?.dataset.act;
      if (a === "cancel") done(null);
      else if (a === "all") { place({ x: 0, y: 0, w: W, h: H }); ready(); }
      else if (a === "redo") reset();
      else if (a === "ok") finish();
      else if (a === "pen") {
        pen = !pen;
        ui.classList.toggle("is-pen", pen);
        btn("pen").setAttribute("aria-pressed", String(pen));
      }
    });
  });
}

let cssDone = false;
function css(v) {
  if (cssDone) return;
  cssDone = true;
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = `/snip.css?v=${v}`;
  document.head.appendChild(l);
}

/** Snip part of the screen. hide = elements to take out of the picture (the feedback panel). */
export async function snip({ hide = [], v = "1" } = {}) {
  css(v);
  const hidden = hide.filter(Boolean).map((el) => {
    const prev = el.style.visibility;
    el.style.visibility = "hidden";
    return () => { el.style.visibility = prev; };
  });
  await sleep(60);                                  // let the panel's hide paint first
  const b = busy("Taking a picture of the page…");
  let canvas = null;
  try {
    canvas = await shootDom();
  } catch (err) {
    console.warn("snip: page render failed, asking for a tab capture", err);
    b.remove();
    try { canvas = await shootScreen(); } catch { canvas = null; }
  } finally {
    b.remove();
  }
  let out = null;
  try {
    if (canvas) out = await pick(canvas);
  } finally {
    hidden.forEach((undo) => undo());
  }
  return out;
}

/** A picked image file -> the same kind of JPEG data: URL. */
export async function fileToSnip(file) {
  if (!file || !/^image\//.test(file.type)) throw new Error("Choose an image file.");
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    c.getContext("2d").drawImage(img, 0, 0);
    return toJpeg(c, 0, 0, c.width, c.height, null);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The "Screenshot" field for a form: snip button, attach-a-file button, thumbnails.
 *  host = an empty element; hide() = elements to take out of the picture.
 *  Returns { get() -> [data URLs], clear() }. */
export function snipField(host, { hide = () => [], v = "1", max = 3 } = {}) {
  css(v);
  const list = [];
  host.classList.add("fb-snips");
  host.innerHTML = `
    <div class="fb-snip-head"><label>Screenshot <small>optional - show us exactly where</small></label></div>
    <div class="fb-snip-row">
      <button type="button" class="fb-snip-btn" data-snip>✂️ Snip part of the page</button>
      <label class="fb-snip-btn is-plain fb-snip-file">🖼️ Attach image<input type="file" accept="image/*" hidden></label>
    </div>
    <div class="fb-snip-thumbs" aria-live="polite"></div>`;
  const thumbs = host.querySelector(".fb-snip-thumbs");
  const btn = host.querySelector("[data-snip]");
  const file = host.querySelector("input[type=file]");
  const fileLabel = host.querySelector(".fb-snip-file");
  function paint() {
    thumbs.innerHTML = list.map((u, i) => `<span class="fb-snip-thumb"><img src="${u}" alt="Screenshot ${i + 1}">
      <button type="button" data-drop="${i}" aria-label="Remove screenshot ${i + 1}">×</button></span>`).join("");
    const full = list.length >= max;
    btn.disabled = full;
    file.disabled = full;
    fileLabel.style.opacity = full ? ".5" : "";
    btn.textContent = full ? `${max} screenshots attached` : list.length ? "✂️ Snip another" : "✂️ Snip part of the page";
  }
  btn.addEventListener("click", async () => {
    const url = await snip({ hide: hide(), v });
    if (url && list.length < max) { list.push(url); paint(); }
    btn.focus();
  });
  file.addEventListener("change", async () => {
    const f = file.files?.[0];
    file.value = "";
    if (!f || list.length >= max) return;
    try { list.push(await fileToSnip(f)); paint(); } catch (e) { alert(e.message); }
  });
  thumbs.addEventListener("click", (e) => {
    const b = e.target.closest("[data-drop]");
    if (!b) return;
    list.splice(+b.dataset.drop, 1);
    paint();
  });
  paint();
  return { get: () => list.slice(), clear: () => { list.length = 0; paint(); } };
}
