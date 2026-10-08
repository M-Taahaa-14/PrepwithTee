/* board/paper.js — paper for PrepWithTee Board: sizes, colours and the
 * background patterns (lined, squared, graph, dotted, isometric, Cornell).
 * website/annot_pdf.py draws the same patterns into exported PDFs - keep the
 * spacings and colours in step (PAGE_SIZES, PAPERS, _pattern).
 */
export const SIZES = {
  a4: { name: "A4 portrait", w: 595, h: 842, mm: 210 },
  a4l: { name: "A4 landscape", w: 842, h: 595, mm: 297 },
  letter: { name: "Letter", w: 612, h: 792, mm: 215.9 },
  wide: { name: "Slide 16:9", w: 842, h: 474, mm: 297 },
};
export const PAPERS = {
  white: ["White", "#ffffff"], cream: ["Cream", "#fbf6ea"], mint: ["Mint", "#eef8f1"], sky: ["Sky", "#eef5fd"],
  lilac: ["Lilac", "#f4f0fd"], grey: ["Grey", "#f1f2f4"], chalk: ["Chalkboard", "#1e2a26"], night: ["Night", "#171a21"],
};
export const DARK = new Set(["chalk", "night"]);
export const PATTERNS = {
  plain: "Plain", lined: "Lined", narrow: "Narrow lined", squared: "Squared 5 mm", graph: "Graph (2 mm / 1 cm)",
  axes: "Graph with axes", dotted: "Dotted", isometric: "Isometric", cornell: "Cornell notes",
};

/* "Graph with axes": the student picks the ranges and what one big square is
 * worth. settings.ax = {x0, x1, y0, y1, dx, dy, sub, eq, lab}; whiteboard.py
 * clean_axes() and annot_pdf._axes() hold the same rules and the same layout. */
export const AXES_DEFAULT = { x0: -5, x1: 5, y0: -5, y1: 5, dx: 1, dy: 1, sub: 5, eq: true, lab: true };
export const AXES_SUBS = [1, 2, 4, 5, 10];
export const AXES_MAX_CELLS = 60;

/** Settings as given, or null with a reason when they can't make a grid. */
export function checkAxes(a) {
  const v = { ...AXES_DEFAULT, ...(a || {}) };
  for (const k of ["x0", "x1", "y0", "y1", "dx", "dy"]) {
    v[k] = Number(v[k]);
    if (!Number.isFinite(v[k]) || Math.abs(v[k]) > 1e6) return { error: "Use numbers between -1,000,000 and 1,000,000." };
  }
  if (v.x1 <= v.x0) return { error: "The x range must go from smaller to bigger." };
  if (v.y1 <= v.y0) return { error: "The y range must go from smaller to bigger." };
  if (v.dx <= 0 || v.dy <= 0) return { error: "Each big square must be worth more than 0." };
  const nx = (v.x1 - v.x0) / v.dx, ny = (v.y1 - v.y0) / v.dy;
  if (nx > AXES_MAX_CELLS || ny > AXES_MAX_CELLS) return { error: `That's more than ${AXES_MAX_CELLS} big squares across - make each square worth more.` };
  if (nx < 1 || ny < 1) return { error: "The range must be at least one big square." };
  v.sub = AXES_SUBS.includes(Number(v.sub)) ? Number(v.sub) : 5;
  v.eq = v.eq !== false;
  v.lab = v.lab !== false;
  return { ax: v };
}

/** Where the grid sits on a w x h page (mm = px per millimetre). */
export function axesLayout(w, h, mm, a) {
  const v = checkAxes(a).ax || AXES_DEFAULT;
  const nx = Math.ceil((v.x1 - v.x0) / v.dx - 1e-9), ny = Math.ceil((v.y1 - v.y0) / v.dy - 1e-9);
  const m = Math.min(14 * mm, 0.08 * Math.min(w, h));       // room for the numbers
  let cw = (w - 2 * m) / nx, ch = (h - 2 * m) / ny;
  if (v.eq) cw = ch = Math.min(cw, ch);
  const left = (w - nx * cw) / 2, top = (h - ny * ch) / 2;
  return { v, nx, ny, cw, ch, left, top, right: left + nx * cw, bottom: top + ny * ch };
}

/** A tidy label: no float noise, no "-0". */
export const fmtNum = (n) => {
  const r = Math.round(n * 1e6) / 1e6;
  return Object.is(r, -0) ? "0" : String(r);
};

function drawAxes(ctx, w, h, s, mm, line, dark, px) {
  const L = axesLayout(w, h, mm, s.ax);
  const { v, nx, ny, cw, ch, left, top, right, bottom } = L;
  ctx.lineWidth = px * 0.5;
  // small squares: only when they don't blur into a grey wash
  if (v.sub > 1 && Math.min(cw, ch) / v.sub >= 3) {
    ctx.globalAlpha = 0.6;
    ctx.beginPath();
    for (let i = 0; i <= nx * v.sub; i++) { const x = Math.round(left + i * cw / v.sub) + 0.5; ctx.moveTo(x, top); ctx.lineTo(x, bottom); }
    for (let j = 0; j <= ny * v.sub; j++) { const y = Math.round(top + j * ch / v.sub) + 0.5; ctx.moveTo(left, y); ctx.lineTo(right, y); }
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.lineWidth = px * 1.2;
  ctx.beginPath();
  for (let i = 0; i <= nx; i++) { const x = Math.round(left + i * cw) + 0.5; ctx.moveTo(x, top); ctx.lineTo(x, bottom); }
  for (let j = 0; j <= ny; j++) { const y = Math.round(top + j * ch) + 0.5; ctx.moveTo(left, y); ctx.lineTo(right, y); }
  ctx.stroke();

  // the axes: through 0 when 0 is in range, otherwise along the edge
  const ink = dark ? "rgba(255,255,255,.75)" : "#34425a";
  const X = (x) => left + (x - v.x0) / v.dx * cw, Y = (y) => bottom - (y - v.y0) / v.dy * ch;
  const ay = v.y0 <= 0 && v.y1 >= 0 ? Y(0) : bottom;          // where the x-axis runs
  const ax = v.x0 <= 0 && v.x1 >= 0 ? X(0) : left;            // where the y-axis runs
  const xEnd = X(v.x1), yEnd = Y(v.y1);
  const fs = Math.max(6, Math.min(3.3 * mm, Math.min(cw, ch) * 0.55));
  const ah = Math.max(4, Math.min(cw, ch) * 0.28, 2 * mm);    // arrowheads at the positive ends,
  const off = fs * 1.3;                                       // past the last numbers so they never cover one
  ctx.strokeStyle = ink; ctx.fillStyle = ink;
  ctx.lineWidth = Math.max(1, px * 2.4);
  ctx.beginPath(); ctx.moveTo(left, ay); ctx.lineTo(xEnd + off, ay); ctx.moveTo(ax, bottom); ctx.lineTo(ax, yEnd - off); ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(xEnd + off + ah, ay); ctx.lineTo(xEnd + off, ay - ah * 0.5); ctx.lineTo(xEnd + off, ay + ah * 0.5); ctx.closePath();
  ctx.moveTo(ax, yEnd - off - ah); ctx.lineTo(ax - ah * 0.5, yEnd - off); ctx.lineTo(ax + ah * 0.5, yEnd - off); ctx.closePath();
  ctx.fill();

  ctx.font = `600 ${fs}px "Hanken Grotesk", system-ui, sans-serif`;
  ctx.fillText("x", xEnd + off + ah * 1.2, ay - fs * 0.35);
  ctx.textAlign = "center";
  ctx.fillText("y", ax, yEnd - off - ah * 1.3);
  if (!v.lab) { ctx.textAlign = "start"; return; }
  // numbers on every k-th line, so they never run into each other
  const kx = Math.max(1, Math.ceil(fs * 2.4 / cw)), ky = Math.max(1, Math.ceil(fs * 1.5 / ch));
  ctx.textBaseline = "top";
  for (let i = 0; i <= nx; i++) {
    const val = v.x0 + i * v.dx;
    if (i % kx || (Math.abs(val) < 1e-9 && ax !== left)) continue;
    ctx.fillText(fmtNum(val), left + i * cw, ay + fs * 0.35);
  }
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  for (let j = 0; j <= ny; j++) {
    const val = v.y0 + j * v.dy;
    if (j % ky || (Math.abs(val) < 1e-9 && ay !== bottom)) continue;
    ctx.fillText(fmtNum(val), ax - fs * 0.4, bottom - j * ch);
  }
  if (ax !== left && ay !== bottom) {                         // one 0 at the origin
    ctx.textBaseline = "top";
    ctx.fillText("0", ax - fs * 0.3, ay + fs * 0.3);
  }
  ctx.textAlign = "start"; ctx.textBaseline = "alphabetic";
}

export const paperHex = (s) => {
  const p = s?.paper || "white";
  return PAPERS[p]?.[1] || (/^#[0-9a-f]{6}$/i.test(p) ? p : "#ffffff");
};
export const isDark = (s) => DARK.has(s?.paper);
export const sizeOf = (s) => SIZES[s?.size] || SIZES.a4;

/**
 * Draw the pattern for settings s onto ctx (already scaled to CSS px), over
 * the rectangle 0..w x 0..h. mm = px per millimetre. ox / oy shift the pattern
 * (infinite canvas: the camera), so it scrolls with the ink.
 */
export function drawPattern(ctx, w, h, s, mm, ox = 0, oy = 0, { fill = true, cam = false } = {}) {
  if (fill) { ctx.fillStyle = paperHex(s); ctx.fillRect(0, 0, w, h); }
  let pat = s?.pattern || "plain";
  if (pat === "axes" && cam) pat = "graph";                    // axes belong to a page, not an endless canvas
  if (pat === "plain") return;
  const dark = isDark(s);
  const line = dark ? "rgba(255,255,255,.16)" : "rgba(140,166,204,.55)";
  const red = dark ? "rgba(219,77,89,.3)" : "rgba(219,77,89,.5)";
  const px = Math.max(0.5, mm * 0.18);                         // ~0.5 pt at 100 %
  const start = (step, off) => ((-off % step) + step) % step;
  // lines from `from` + one step on a page; on the infinite canvas a grid fixed to the world
  const hl = (step, from = 0, x0 = 0, x1 = w, cut = h) => {
    ctx.beginPath();
    for (let y = cam ? start(step, oy) : from + step; y < cut - 0.5; y += step) {
      ctx.moveTo(x0, Math.round(y) + 0.5); ctx.lineTo(x1, Math.round(y) + 0.5);
    }
    ctx.stroke();
  };
  const vl = (step) => {
    ctx.beginPath();
    for (let x = start(step, ox); x < w; x += step) { ctx.moveTo(Math.round(x) + 0.5, 0); ctx.lineTo(Math.round(x) + 0.5, h); }
    ctx.stroke();
  };
  ctx.save();
  ctx.strokeStyle = line;
  ctx.lineWidth = px;
  if (pat === "lined" || pat === "narrow") {
    const step = (pat === "lined" ? 8 : 6) * mm;
    hl(step, 18 * mm);
    if (!cam) {                                                 // the margin only on real pages
      ctx.strokeStyle = red; ctx.lineWidth = px * 1.2;
      ctx.beginPath(); ctx.moveTo(25 * mm, 0); ctx.lineTo(25 * mm, h); ctx.stroke();
    }
  } else if (pat === "squared") {
    hl(5 * mm); vl(5 * mm);
  } else if (pat === "graph") {
    ctx.lineWidth = px * 0.5;
    ctx.globalAlpha = 0.7;
    if (mm * 2 >= 3) { hl(2 * mm); vl(2 * mm); }               // minor lines only when they don't blur
    ctx.globalAlpha = 1;
    ctx.lineWidth = px * 1.2;
    hl(10 * mm); vl(10 * mm);
  } else if (pat === "axes") {
    drawAxes(ctx, w, h, s, mm, line, dark, px);
  } else if (pat === "dotted") {
    const step = 5 * mm, r = Math.max(0.7, mm * 0.2);
    ctx.fillStyle = dark ? "rgba(255,255,255,.22)" : "rgba(140,166,204,.8)";
    for (let y = start(step, oy); y < h; y += step) {
      for (let x = start(step, ox); x < w; x += step) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); }
    }
  } else if (pat === "isometric") {
    const step = 5 * mm;
    ctx.lineWidth = px * 0.7;
    hl(step * Math.sqrt(3) / 2);
    const run = h / Math.tan(Math.PI / 3);
    ctx.beginPath();
    for (let x = -run + start(step, ox); x < w + run; x += step) {
      ctx.moveTo(x, 0); ctx.lineTo(x + run, h);
      ctx.moveTo(x + run, 0); ctx.lineTo(x, h);
    }
    ctx.stroke();
  } else if (pat === "cornell") {
    const top = 30 * mm, cue = 63 * mm, summary = h - 50 * mm;
    ctx.lineWidth = px * 0.9;
    hl(8 * mm, top, cue, w, summary);
    ctx.strokeStyle = red; ctx.lineWidth = px * 1.6;
    ctx.beginPath();
    ctx.moveTo(0, top); ctx.lineTo(w, top);
    ctx.moveTo(cue, top); ctx.lineTo(cue, summary);
    ctx.moveTo(0, summary); ctx.lineTo(w, summary);
    ctx.stroke();
  }
  ctx.restore();
}
