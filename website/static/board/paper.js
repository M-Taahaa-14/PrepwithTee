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
  dotted: "Dotted", isometric: "Isometric", cornell: "Cornell notes",
};

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
  const pat = s?.pattern || "plain";
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
