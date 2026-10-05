/* ink/shapes.js — geometry for annotate.js: box-defined polygons, arcs and
 * Notability-style shape recognition. Pure functions on page fractions.
 * website/annot_pdf.py has the same polygon table (POLY_KINDS) - keep in step.
 */

/** Vertices (unit box 0..1) of each box-defined polygon kind. */
export const POLY = {
  tri: [[0.5, 0], [1, 1], [0, 1]],                                       // isosceles triangle
  rtri: [[0, 0], [1, 1], [0, 1]],                                        // right angle bottom-left
  diamond: [[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]],
  para: [[0.25, 0], [1, 0], [0.75, 1], [0, 1]],                          // parallelogram
  trap: [[0.25, 0], [0.75, 0], [1, 1], [0, 1]],                          // trapezium
  pent: regular(5), hex: regular(6), oct: regular(8),
  star: starPts(5, 0.4),
};

function regular(n) {
  return Array.from({ length: n }, (_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)];
  });
}
function starPts(n, inner) {
  return Array.from({ length: n * 2 }, (_, i) => {
    const a = -Math.PI / 2 + (i * Math.PI) / n, r = i % 2 ? inner * 0.5 : 0.5;
    return [0.5 + r * Math.cos(a), 0.5 + r * Math.sin(a)];
  });
}

/** A box polygon's corners in page fractions (closed: first point repeated). */
export function polyCorners(s) {
  if (s.pts) return s.pts;
  const x0 = Math.min(s.a[0], s.b[0]), y0 = Math.min(s.a[1], s.b[1]);
  const w = Math.abs(s.b[0] - s.a[0]), h = Math.abs(s.b[1] - s.a[1]);
  const base = POLY[s.k] || POLY.tri;
  // drawn "upside down" (dragged up / left) flips the shape, like a real drag
  const fx = s.b[0] < s.a[0], fy = s.b[1] < s.a[1];
  const out = base.map(([u, v]) => [x0 + (fx && s.k === "rtri" ? 1 - u : u) * w, y0 + (fy ? 1 - v : v) * h]);
  out.push(out[0]);
  return out;
}

/** Points along an arc {o, r, a0, sw}, page fractions (r is a fraction of the width). */
export function arcPoints(s, w, h, step = 0.04) {
  const n = Math.max(4, Math.ceil(Math.abs(s.sw) / step));
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = s.a0 + (s.sw * i) / n;
    return [s.o[0] + s.r * Math.cos(t), s.o[1] + (s.r * Math.sin(t) * w) / h, 0.5];
  });
}

// ── shape recognition ───────────────────────────────────────────────────────
function segDistPx(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

/** Ramer-Douglas-Peucker on pixel points. */
function rdp(pts, eps) {
  if (pts.length < 3) return pts.slice();
  let idx = 0, dmax = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    const d = segDistPx(pts[i], pts[0], pts[pts.length - 1]);
    if (d > dmax) { dmax = d; idx = i; }
  }
  if (dmax <= eps) return [pts[0], pts[pts.length - 1]];
  return [...rdp(pts.slice(0, idx + 1), eps).slice(0, -1), ...rdp(pts.slice(idx), eps)];
}

/**
 * A freehand pen stroke -> a clean shape (or null when it is just writing).
 * Lines, circles / ellipses, triangles, rectangles (axis-aligned -> rect,
 * tilted -> closed polygon) and other closed polygons up to 6 corners.
 */
export function recognise(stroke, w, h) {
  const P = stroke.pts.map((q) => [q[0] * w, q[1] * h]);
  if (P.length < 4) return null;
  let len = 0;
  for (let i = 1; i < P.length; i++) len += Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
  if (len < 30) return null;
  const xs = P.map((p) => p[0]), ys = P.map((p) => p[1]);
  const bx0 = Math.min(...xs), bx1 = Math.max(...xs), by0 = Math.min(...ys), by1 = Math.max(...ys);
  const diag = Math.hypot(bx1 - bx0, by1 - by0);
  const base = { c: stroke.c, w: stroke.w };
  const fr = (p) => [+(p[0] / w).toFixed(4), +(p[1] / h).toFixed(4)];
  const first = P[0], last = P[P.length - 1];
  const gap = Math.hypot(last[0] - first[0], last[1] - first[1]);

  // a line: every point close to the chord
  const chord = Math.hypot(last[0] - first[0], last[1] - first[1]);
  if (chord > 0.8 * len && Math.max(...P.map((p) => segDistPx(p, first, last))) < Math.max(6, chord * 0.05)) {
    return { ...base, t: "line", a: fr(first), b: fr(last) };
  }
  if (gap > Math.max(24, diag * 0.28)) return null;        // open curve: leave it as handwriting

  // a circle / ellipse: radius about the centre steady
  const cx = (bx0 + bx1) / 2, cy = (by0 + by1) / 2, rx = (bx1 - bx0) / 2, ry = (by1 - by0) / 2;
  if (rx > 6 && ry > 6) {
    const dev = P.map((p) => Math.abs(Math.hypot((p[0] - cx) / rx, (p[1] - cy) / ry) - 1));
    const mean = dev.reduce((a, b) => a + b, 0) / dev.length;
    const corners = rdp(P, diag * 0.06).length - 1;
    if (mean < 0.1 && corners > 5) {
      const r = Math.abs(rx - ry) / Math.max(rx, ry) < 0.14 ? (rx + ry) / 2 : null;     // nearly round = a circle
      const ex = r ?? rx, ey = r ?? ry;
      return { ...base, t: "ellipse", a: fr([cx - ex, cy - ey]), b: fr([cx + ex, cy + ey]) };
    }
  }
  // a polygon: few corners after simplifying
  let C = rdp([...P.slice(0, -1), first], diag * 0.08);
  if (C.length > 2 && Math.hypot(C[0][0] - C.at(-1)[0], C[0][1] - C.at(-1)[1]) < diag * 0.15) C = C.slice(0, -1);
  // merge corners that sit almost on a straight line
  for (let changed = true; changed && C.length > 3;) {
    changed = false;
    for (let i = 0; i < C.length; i++) {
      const a = C[(i - 1 + C.length) % C.length], b = C[i], c = C[(i + 1) % C.length];
      if (segDistPx(b, a, c) < diag * 0.06) { C.splice(i, 1); changed = true; break; }
    }
  }
  if (C.length < 3 || C.length > 6) return null;
  if (C.length === 4) {
    // axis-aligned rectangle?
    const ang = (a, b) => Math.abs(Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI) % 90;
    const straight = C.every((p, i) => { const g = ang(p, C[(i + 1) % 4]); return g < 12 || g > 78; });
    if (straight) return { ...base, t: "rect", a: fr([bx0, by0]), b: fr([bx1, by1]) };
  }
  const pts = C.map((p) => [...fr(p), 0.5]);
  pts.push(pts[0]);
  return { ...base, t: "poly", pts };
}
