"""Burn annotations (annotate.js objects) into PDFs.

burn()          "Download with my annotations" (My papers, booklet viewer): a
                copy of the paper with every page's ink on top.
render_board()  a whiteboard as a PDF: blank pages in the board's paper colour
                and pattern (lined, squared, graph, dotted...), then the ink.

Objects are stored as fractions of the page as displayed, exactly as
annotate.js draws them; colours are palette tokens ("@blue") resolved with the
LIGHT palette (a download is white paper) or hex (8 digits = see-through).
Keep PALETTE, POLY and the object fields in step with annotate.js and
static/ink/shapes.js; stickers come from static/ink/stickers.json, the same
file the browser draws.
"""

import json
import math
import re
from pathlib import Path

import fitz  # PyMuPDF

# token -> (light, dark). annotate.js has the same table.
PALETTE = {
    "blue": ("#1d4ed8", "#93c5fd"), "ink": ("#111827", "#f3f4f6"), "red": ("#dc2626", "#fca5a5"),
    "green": ("#15803d", "#86efac"), "orange": ("#ea580c", "#fdba74"), "purple": ("#7e22ce", "#d8b4fe"),
    "pink": ("#db2777", "#f9a8d4"), "teal": ("#0f766e", "#5eead4"), "yellow": ("#ca8a04", "#fde68a"),
    "brown": ("#92400e", "#e7c9a9"), "grey": ("#4b5563", "#cbd5e1"), "sky": ("#0284c7", "#7dd3fc"),
}


def _rgb(c: str | None) -> tuple[float, float, float]:
    c = c or "@blue"
    if c.startswith("@"):
        c = PALETTE.get(c[1:], PALETTE["blue"])[0]
    c = c.lstrip("#")
    if len(c) in (3, 4):
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.11, 0.3, 0.85)


def _alpha(c: str | None) -> float:
    """Opacity of a colour: 8-digit (or 4-digit) hex carries it, tokens are solid."""
    c = (c or "").lstrip("#")
    if len(c) == 4:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 8:
        try:
            return max(0.05, int(c[6:8], 16) / 255)
        except ValueError:
            return 1.0
    return 1.0


def _mix(rgb, other, t):
    return tuple(a + (b - a) * t for a, b in zip(rgb, other))


# Box-defined polygons (unit box) - static/ink/shapes.js POLY.
def _regular(n):
    return [(0.5 + 0.5 * math.cos(-math.pi / 2 + i * 2 * math.pi / n),
             0.5 + 0.5 * math.sin(-math.pi / 2 + i * 2 * math.pi / n)) for i in range(n)]


def _star(n, inner):
    return [(0.5 + (inner * 0.5 if i % 2 else 0.5) * math.cos(-math.pi / 2 + i * math.pi / n),
             0.5 + (inner * 0.5 if i % 2 else 0.5) * math.sin(-math.pi / 2 + i * math.pi / n))
            for i in range(n * 2)]


POLY = {
    "tri": [(0.5, 0), (1, 1), (0, 1)], "rtri": [(0, 0), (1, 1), (0, 1)],
    "diamond": [(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)], "para": [(0.25, 0), (1, 0), (0.75, 1), (0, 1)],
    "trap": [(0.25, 0), (0.75, 0), (1, 1), (0, 1)], "pent": _regular(5), "hex": _regular(6),
    "oct": _regular(8), "star": _star(5, 0.4),
}


def poly_corners(s: dict) -> list[tuple[float, float]]:
    """A polygon's corners in page fractions (closed)."""
    if s.get("pts"):
        return [(q[0], q[1]) for q in s["pts"]]
    a, b = s["a"], s["b"]
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
    fx, fy = b[0] < a[0], b[1] < a[1]
    k = s.get("k")
    out = [(x0 + ((1 - u) if fx and k == "rtri" else u) * w, y0 + ((1 - v) if fy else v) * h)
           for u, v in POLY.get(k, POLY["tri"])]
    return out + out[:1]


_STICKERS = None
_STICKER_PDF: dict = {}


def _sticker(k: str):
    """The sticker as a one-page PDF (vector), from static/ink/stickers.json."""
    global _STICKERS
    if _STICKERS is None:
        try:
            _STICKERS = json.loads((Path(__file__).parent / "static" / "ink" / "stickers.json")
                                   .read_text("utf-8"))
        except (OSError, ValueError):
            _STICKERS = {}
    if k not in _STICKER_PDF:
        s = _STICKERS.get(k)
        if not s:
            return None
        svg = fitz.open("svg", s["svg"].encode("utf-8"))
        _STICKER_PDF[k] = fitz.open("pdf", svg.convert_to_pdf())
    return _STICKER_PDF[k]


# Text box fonts (annotate.js FONTS) -> base-14 PDF fonts: (regular, bold, italic, bold italic).
# Handwriting has no base-14 twin; Helvetica oblique is the nearest in spirit.
_FONTS = {"sans": ("helv", "hebo", "heit", "hebi"), "serif": ("tiro", "tibo", "tiit", "tibi"),
          "mono": ("cour", "cobo", "coit", "cobi"), "hand": ("heit", "hebi", "heit", "hebi")}
LH = 1.25                                        # line height, as on screen


def _wrap(txt: str, fs: float, width: float, font: str = "helv") -> list[str]:
    """A text box's lines: its own line breaks, then word-wrapped to its box
    width (annotate.js textLayout does the same on screen). width 0 = no wrap."""
    if width <= 0:
        return txt.split("\n")
    out = []
    for para in txt.split("\n"):
        line = ""
        for word in re.split(r"(?<=\s)", para):
            if line and fitz.get_text_length((line + word).rstrip(), font, fs) > width:
                out.append(line.rstrip())
                line = word
            else:
                line += word
        out.append(line)
    return out


def _draw_text(page: fitz.Page, s: dict, col, P) -> None:
    """A text box: fill, border, then the lines - aligned, underlined - with
    the same box geometry annotate.js drawText uses."""
    W, H = page.rect.width, page.rect.height
    fs = max(3.0, float(s.get("s") or 0.02) * W)
    regular, bold, italic, both = _FONTS.get(s.get("f") or "sans", _FONTS["sans"])
    font = both if s.get("b") and s.get("i") else bold if s.get("b") else italic if s.get("i") else regular
    lines = _wrap(str(s["txt"]), fs, float(s.get("bw") or 0) * W, font)
    widths = [fitz.get_text_length(line, font, fs) for line in lines]
    box_w = float(s.get("bw") or 0) * W or max(widths or [0])
    lh = fs * LH
    x, y = float(s.get("x") or 0) * W, float(s.get("y") or 0) * H
    pad = round(fs * 0.35) if (s.get("bg") or s.get("bd")) else 0
    rect = fitz.Rect(P((x - pad) / W, (y - pad) / H), P((x + box_w + pad) / W, (y + len(lines) * lh + pad) / H))
    if s.get("bg") or s.get("bd"):
        shape = page.new_shape()
        shape.draw_rect(rect.normalize())
        bg = s.get("bg")
        shape.finish(color=col if s.get("bd") else None, width=max(0.6, fs * 0.07) if s.get("bd") else 0,
                     fill=(1, 1, 1) if bg == "paper" else _rgb(bg) if bg else None,
                     fill_opacity=1 if bg == "paper" else 0.26)
        shape.commit(overlay=True)
    f = fitz.Font(font)
    base = (lh - (f.ascender - f.descender) * fs) / 2 + f.ascender * fs      # baseline in a line box
    m = page.derotation_matrix
    for i, (line, lw_) in enumerate(zip(lines, widths)):
        off = (box_w - lw_) / 2 if s.get("al") == "c" else (box_w - lw_) if s.get("al") == "r" else 0
        by = y + i * lh + base
        if line:
            page.insert_text(fitz.Point(x + off, by) * m, line, fontsize=fs, fontname=font,
                             color=col, rotate=page.rotation)
        if s.get("u") and lw_:
            shape = page.new_shape()
            shape.draw_line(P((x + off) / W, (by + fs * 0.12) / H), P((x + off + lw_) / W, (by + fs * 0.12) / H))
            shape.finish(color=col, width=max(0.5, fs * 0.07))
            shape.commit(overlay=True)


def _draw(page: fitz.Page, s: dict, resolve=None) -> None:
    W, H = page.rect.width, page.rect.height
    m = page.derotation_matrix                    # displayed -> unrotated page space

    def P(x, y):
        return fitz.Point(float(x) * W, float(y) * H) * m

    def box():
        return fitz.Rect(P(*s["a"][:2]), P(*s["b"][:2])).normalize()

    col = _rgb(s.get("c"))
    op = _alpha(s.get("c"))
    lw = max(0.6, float(s.get("w") or 0.004) * W)
    t = s.get("t")
    dashes = f"[{lw * 2.6 + 1.5:.1f} {lw * 2 + 2.2:.1f}] 0" if (s.get("d") or s.get("k") == "dash") else None
    fill = _rgb(s["fl"]) if s.get("fl") else None
    shape = page.new_shape()
    if t in ("pen", "marker"):
        pts = [P(q[0], q[1]) for q in s.get("pts") or [] if len(q) >= 2]
        if not pts:
            return
        if len(pts) == 1:
            shape.draw_circle(pts[0], lw / 2)
            shape.finish(color=col, fill=col, width=0, fill_opacity=op)
        else:
            shape.draw_polyline(pts)
            if t == "marker":
                shape.finish(color=col, width=lw * 3.2, stroke_opacity=0.32 * op, lineCap=0, lineJoin=1,
                             closePath=False)
            else:
                k = s.get("k")
                if k in ("fine", "dash"):
                    width = lw
                elif k == "fountain":
                    width = lw * 1.05
                elif k == "pencil":
                    width = lw * 0.85
                else:
                    pr = [q[2] for q in s["pts"] if len(q) > 2]
                    width = lw * (0.55 + 0.9 * (sum(pr) / len(pr) if pr else 0.5))
                shape.finish(color=col, width=width, lineCap=1, lineJoin=1, closePath=False, dashes=dashes,
                             stroke_opacity=op * (0.8 if k == "pencil" else 1))
    elif t in ("line", "arrow") and s.get("a") and s.get("b"):
        a, b = P(*s["a"][:2]), P(*s["b"][:2])
        shape.draw_line(a, b)
        shape.finish(color=col, width=lw, lineCap=1, dashes=dashes, stroke_opacity=op)
        if t == "arrow":
            L = max(7.5, lw * 4)
            for tip_at, frm in (((b, a), (a, b)) if s.get("two") else ((b, a),)):
                ang = math.atan2(tip_at.y - frm.y, tip_at.x - frm.x)
                tip = [tip_at,
                       fitz.Point(tip_at.x - L * math.cos(ang - 0.45), tip_at.y - L * math.sin(ang - 0.45)),
                       fitz.Point(tip_at.x - L * math.cos(ang + 0.45), tip_at.y - L * math.sin(ang + 0.45))]
                shape.draw_polyline(tip + [tip_at])
                shape.finish(color=col, fill=col, width=0.5, closePath=True, stroke_opacity=op, fill_opacity=op)
    elif t in ("rect", "ellipse") and s.get("a") and s.get("b"):
        r = box()
        if t == "rect" and s.get("rr"):
            shape.draw_rect(r, radius=0.2)
        elif t == "rect":
            shape.draw_rect(r)
        else:
            shape.draw_oval(r)
        shape.finish(color=col, width=lw, dashes=dashes, fill=fill, fill_opacity=0.22 if fill else 1,
                     stroke_opacity=op)
    elif t == "poly" and (s.get("pts") or (s.get("a") and s.get("b"))):
        pts = [P(x, y) for x, y in poly_corners(s)]
        shape.draw_polyline(pts)
        shape.finish(color=col, width=lw, closePath=True, lineJoin=1, dashes=dashes, fill=fill,
                     fill_opacity=0.22 if fill else 1, stroke_opacity=op)
    elif t == "arc" and s.get("o") is not None and s.get("r"):
        cx, cy, R = float(s["o"][0]) * W, float(s["o"][1]) * H, float(s["r"]) * W
        a0, sw = float(s.get("a0") or 0), float(s.get("sw") or 0)
        n = max(8, int(abs(sw) / 0.03))
        pts = [fitz.Point(cx + R * math.cos(a0 + sw * i / n), cy + R * math.sin(a0 + sw * i / n)) * m
               for i in range(n + 1)]
        shape.draw_polyline(pts)
        shape.finish(color=col, width=lw, lineCap=1, closePath=False, dashes=dashes, stroke_opacity=op)
    elif t == "text" and s.get("txt"):
        _draw_text(page, s, col, P)
        return
    elif t == "stk" and s.get("a") and s.get("b"):
        src = _sticker(s.get("k") or "")
        if src is not None:
            page.show_pdf_page(box(), src, 0, rotate=page.rotation, keep_proportion=False)
        return
    elif t == "img" and s.get("a") and s.get("b"):
        path = resolve(s.get("src") or "") if resolve else None
        if path:
            page.insert_image(box(), filename=str(path), rotate=page.rotation, keep_proportion=False)
        return
    elif t == "note" and s.get("a") and s.get("b"):
        r = box()
        bg = s.get("bg") or "@yellow"
        if bg.startswith("@"):                       # the pastel (dark-paper) shade, lightened
            fill_rgb = _mix(_rgb(PALETTE.get(bg[1:], PALETTE["yellow"])[1]), (1, 1, 1), 0.35)
        else:
            fill_rgb = _mix(_rgb(bg), (1, 1, 1), 0.7)
        shape.draw_rect(r)
        shape.finish(color=None, width=0, fill=fill_rgb)
        shape.commit(overlay=True)
        if s.get("txt"):
            x0, y0 = min(s["a"][0], s["b"][0]) * W, min(s["a"][1], s["b"][1]) * H
            bw = abs(s["b"][0] - s["a"][0]) * W
            bh = abs(s["b"][1] - s["a"][1]) * H
            fs = max(4.0, float(s.get("fs") or 0.075) * min(bw, bh * 1.2))
            pad = max(3.0, bw * 0.08)
            for i, line in enumerate(_wrap(str(s["txt"]), fs, bw - 2 * pad, "heit")):
                y = y0 + pad + i * fs * 1.3 + fs * 0.85
                if y > y0 + bh - pad * 0.3:
                    break
                if line:
                    page.insert_text(fitz.Point(x0 + pad, y) * m, line, fontsize=fs, fontname="heit",
                                     color=(0.12, 0.16, 0.22), rotate=page.rotation)
        return
    else:
        return
    shape.commit(overlay=True)


def burn(pdf_path, pages: dict[int, list], resolve=None) -> bytes:
    """A copy of the PDF with every page's strokes drawn on top. resolve(src)
    turns an image object's src into a local file path (or None to skip it)."""
    doc = fitz.open(pdf_path)
    try:
        for n, strokes in pages.items():
            if not strokes or not 1 <= int(n) <= doc.page_count:
                continue
            page = doc[int(n) - 1]
            for s in strokes:
                try:
                    _draw(page, s, resolve)
                except Exception:
                    continue                     # one odd stroke never loses the rest
        return doc.tobytes(garbage=1, deflate=True)
    finally:
        doc.close()


# ── whiteboards ──────────────────────────────────────────────────────────────
# Page sizes (points) and paper colours - static/board/paper.js has the same.
PAGE_SIZES = {"a4": (595, 842), "a4l": (842, 595), "letter": (612, 792), "wide": (842, 474)}
PAPERS = {"white": "#ffffff", "cream": "#fbf6ea", "mint": "#eef8f1", "sky": "#eef5fd", "lilac": "#f4f0fd",
          "grey": "#f1f2f4", "chalk": "#1e2a26", "night": "#171a21"}
DARK_PAPERS = {"chalk", "night"}
PATTERNS = ("plain", "lined", "narrow", "squared", "graph", "axes", "dotted", "isometric", "cornell")

# "Graph with axes" (static/board/paper.js checkAxes / axesLayout hold the same rules)
AXES_DEFAULT = {"x0": -5, "x1": 5, "y0": -5, "y1": 5, "dx": 1, "dy": 1, "sub": 5, "eq": True, "lab": True}
AXES_SUBS = (1, 2, 4, 5, 10)
AXES_MAX_CELLS = 60


def clean_axes(a) -> dict | None:
    """The ranges / box values a student typed, or None when they can't make a grid."""
    if not isinstance(a, dict):
        return None
    v = {**AXES_DEFAULT, **a}
    try:
        for k in ("x0", "x1", "y0", "y1", "dx", "dy"):
            v[k] = float(v[k])
            if not math.isfinite(v[k]) or abs(v[k]) > 1e6:
                return None
    except (TypeError, ValueError):
        return None
    if v["x1"] <= v["x0"] or v["y1"] <= v["y0"] or v["dx"] <= 0 or v["dy"] <= 0:
        return None
    nx, ny = (v["x1"] - v["x0"]) / v["dx"], (v["y1"] - v["y0"]) / v["dy"]
    if not (1 <= nx <= AXES_MAX_CELLS and 1 <= ny <= AXES_MAX_CELLS):
        return None
    for k in ("x0", "x1", "y0", "y1", "dx", "dy"):         # 2.0 -> 2 keeps the JSON tidy
        if v[k] == int(v[k]):
            v[k] = int(v[k])
    try:
        v["sub"] = int(v["sub"]) if int(v["sub"]) in AXES_SUBS else 5
    except (TypeError, ValueError):
        v["sub"] = 5
    v["eq"] = v.get("eq") is not False
    v["lab"] = v.get("lab") is not False
    return {k: v[k] for k in AXES_DEFAULT}


def axes_layout(W: float, H: float, mm: float, a) -> dict:
    v = clean_axes(a) or dict(AXES_DEFAULT)
    nx = math.ceil((v["x1"] - v["x0"]) / v["dx"] - 1e-9)
    ny = math.ceil((v["y1"] - v["y0"]) / v["dy"] - 1e-9)
    m = min(14 * mm, 0.08 * min(W, H))
    cw, ch = (W - 2 * m) / nx, (H - 2 * m) / ny
    if v["eq"]:
        cw = ch = min(cw, ch)
    left, top = (W - nx * cw) / 2, (H - ny * ch) / 2
    return {"v": v, "nx": nx, "ny": ny, "cw": cw, "ch": ch, "left": left, "top": top,
            "right": left + nx * cw, "bottom": top + ny * ch}


def fmt_num(n: float) -> str:
    r = round(n, 6)
    if r == 0:
        return "0"
    return str(int(r)) if r == int(r) else f"{r:g}"


def _axes(page, sh, W, H, mm, settings, line, op, dark) -> None:
    L = axes_layout(W, H, mm, settings.get("ax"))
    v, nx, ny, cw, ch = L["v"], L["nx"], L["ny"], L["cw"], L["ch"]
    left, top, right, bottom = L["left"], L["top"], L["right"], L["bottom"]
    if v["sub"] > 1:
        for i in range(nx * v["sub"] + 1):
            x = left + i * cw / v["sub"]
            sh.draw_line((x, top), (x, bottom))
        for j in range(ny * v["sub"] + 1):
            y = top + j * ch / v["sub"]
            sh.draw_line((left, y), (right, y))
        sh.finish(color=line, width=0.25, stroke_opacity=op * 0.7)
    for i in range(nx + 1):
        sh.draw_line((left + i * cw, top), (left + i * cw, bottom))
    for j in range(ny + 1):
        sh.draw_line((left, top + j * ch), (right, top + j * ch))
    sh.finish(color=line, width=0.6, stroke_opacity=op)

    def X(x):
        return left + (x - v["x0"]) / v["dx"] * cw

    def Y(y):
        return bottom - (y - v["y0"]) / v["dy"] * ch

    ink = (1, 1, 1) if dark else (0.2, 0.26, 0.35)
    ay = Y(0) if v["y0"] <= 0 <= v["y1"] else bottom
    ax = X(0) if v["x0"] <= 0 <= v["x1"] else left
    x_end, y_end = X(v["x1"]), Y(v["y1"])
    fs = max(5.0, min(3.3 * mm, min(cw, ch) * 0.55))
    ah = max(4.0, min(cw, ch) * 0.28, 2 * mm)
    off = fs * 1.3                                         # arrowheads past the last numbers
    sh.draw_line((left, ay), (x_end + off, ay))
    sh.draw_line((ax, bottom), (ax, y_end - off))
    sh.finish(color=ink, width=1.1, stroke_opacity=0.75 if dark else 1)
    sh.draw_polyline([(x_end + off + ah, ay), (x_end + off, ay - ah * 0.5), (x_end + off, ay + ah * 0.5), (x_end + off + ah, ay)])
    sh.draw_polyline([(ax, y_end - off - ah), (ax - ah * 0.5, y_end - off), (ax + ah * 0.5, y_end - off), (ax, y_end - off - ah)])
    sh.finish(color=None, fill=ink, width=0, fill_opacity=0.75 if dark else 1)
    sh.commit(overlay=True)

    font = "helv"

    def text(x, y, s, align="left", valign="base"):
        tw = fitz.get_text_length(s, fontname=font, fontsize=fs)
        dx = {"left": 0, "center": -tw / 2, "right": -tw}[align]
        dy = {"base": 0, "top": fs * 0.8, "middle": fs * 0.35}[valign]
        page.insert_text(fitz.Point(x + dx, y + dy), s, fontsize=fs, fontname=font, color=ink)

    text(x_end + off + ah * 1.2, ay - fs * 0.35, "x")
    text(ax, y_end - off - ah * 1.3, "y", "center")
    if v["lab"]:
        kx = max(1, math.ceil(fs * 2.4 / cw))
        ky = max(1, math.ceil(fs * 1.5 / ch))
        for i in range(nx + 1):
            val = v["x0"] + i * v["dx"]
            if i % kx or (abs(val) < 1e-9 and ax != left):
                continue
            text(left + i * cw, ay + fs * 0.35, fmt_num(val), "center", "top")
        for j in range(ny + 1):
            val = v["y0"] + j * v["dy"]
            if j % ky or (abs(val) < 1e-9 and ay != bottom):
                continue
            text(ax - fs * 0.4, bottom - j * ch, fmt_num(val), "right", "middle")
        if ax != left and ay != bottom:
            text(ax - fs * 0.3, ay + fs * 0.3, "0", "right", "top")
MM = 72 / 25.4


def paper_rgb(settings: dict) -> tuple:
    p = settings.get("paper") or "white"
    return _rgb(PAPERS.get(p, p if str(p).startswith("#") else "#ffffff"))


def _pattern(page: fitz.Page, settings: dict, scale: float = 1.0, infinite: bool = False) -> None:
    """Lined / squared / graph / dotted / isometric / Cornell, as vector lines.
    scale = page points per real point (an infinite board fitted to one page)."""
    pat = settings.get("pattern") or "plain"
    if pat == "plain":
        return
    if pat == "axes" and infinite:                           # axes belong to a page (paper.js does the same)
        pat = "graph"
    W, H = page.rect.width, page.rect.height
    mm = MM * scale
    dark = (settings.get("paper") or "white") in DARK_PAPERS
    line = (1, 1, 1) if dark else (0.55, 0.65, 0.8)
    op = 0.16 if dark else 0.55
    sh = page.new_shape()

    def hlines(step, y0=0.0, x0=0.0, x1=None, cut=None):
        y = y0 + step
        while y < (cut if cut is not None else H) - 0.5:
            sh.draw_line((x0, y), (x1 if x1 is not None else W, y))
            y += step

    def vlines(step):
        x = step
        while x < W - 0.5:
            sh.draw_line((x, 0), (x, H))
            x += step

    if pat in ("lined", "narrow"):
        hlines((8 if pat == "lined" else 6) * mm, 18 * mm)
        sh.finish(color=line, width=0.5, stroke_opacity=op)
        sh.draw_line((25 * mm, 0), (25 * mm, H))
        sh.finish(color=(0.86, 0.3, 0.35), width=0.6, stroke_opacity=0.3 if dark else 0.5)
    elif pat == "squared":
        hlines(5 * mm)
        vlines(5 * mm)
        sh.finish(color=line, width=0.4, stroke_opacity=op)
    elif pat == "graph":
        hlines(2 * mm)
        vlines(2 * mm)
        sh.finish(color=line, width=0.25, stroke_opacity=op * 0.7)
        hlines(10 * mm)
        vlines(10 * mm)
        sh.finish(color=line, width=0.6, stroke_opacity=op)
    elif pat == "axes":
        _axes(page, sh, W, H, mm, settings, line, op, dark)
        return
    elif pat == "dotted":
        step = 5 * mm
        y = step
        while y < H:
            x = step
            while x < W:
                sh.draw_circle((x, y), 0.55)
                x += step
            y += step
        sh.finish(color=None, fill=line, width=0, fill_opacity=min(1, op * 1.4))
    elif pat == "isometric":
        step = 5 * mm
        hlines(step * math.sqrt(3) / 2)
        run = H / math.tan(math.radians(60))
        x = -run
        while x < W + run:
            sh.draw_line((x, 0), (x + run, H))
            sh.draw_line((x + run, 0), (x, H))
            x += step
        sh.finish(color=line, width=0.35, stroke_opacity=op * 0.8)
    elif pat == "cornell":
        top, cue, summary = 30 * mm, 63 * mm, H - 50 * mm
        hlines(8 * mm, top, cue, W, summary)
        sh.finish(color=line, width=0.45, stroke_opacity=op)
        sh.draw_line((0, top), (W, top))
        sh.draw_line((cue, top), (cue, summary))
        sh.draw_line((0, summary), (W, summary))
        sh.finish(color=(0.86, 0.3, 0.35), width=0.8, stroke_opacity=0.55)
    sh.commit(overlay=True)


def _scaled(s: dict, x0: float, y0: float, bw: float, bh: float) -> dict:
    """An infinite-canvas object (world units, 1 = an A4 width) as fractions of
    a page that shows the box (x0, y0, bw, bh)."""
    o = dict(s)

    def fx(x):
        return (float(x) - x0) / bw

    def fy(y):
        return (float(y) - y0) / bh

    if s.get("pts"):
        o["pts"] = [[fx(q[0]), fy(q[1]), *q[2:]] for q in s["pts"]]
    for k in ("a", "b"):
        if s.get(k):
            o[k] = [fx(s[k][0]), fy(s[k][1])]
    if s.get("o"):
        o["o"] = [fx(s["o"][0]), fy(s["o"][1])]
    if "x" in s:
        o["x"], o["y"] = fx(s["x"]), fy(s.get("y") or 0)
    for k in ("w", "s", "bw", "r"):
        if s.get(k):
            o[k] = float(s[k]) / bw
    return o


def _bbox(s: dict):
    """Rough world-unit bounds of an object (for fitting an infinite board)."""
    pts = []
    if s.get("pts"):
        pts = [(q[0], q[1]) for q in s["pts"]]
    elif s.get("a") and s.get("b"):
        pts = [tuple(s["a"][:2]), tuple(s["b"][:2])]
    elif s.get("o") is not None and s.get("r"):
        r = float(s["r"])
        pts = [(s["o"][0] - r, s["o"][1] - r), (s["o"][0] + r, s["o"][1] + r)]
    elif "x" in s:
        fs = float(s.get("s") or 0.02)
        txt = str(s.get("txt") or "")
        w = float(s.get("bw") or 0) or max(0.05, max((len(x) for x in txt.split("\n")), default=1) * fs * 0.55)
        pts = [(s["x"], s["y"]), (s["x"] + w, s["y"] + (txt.count("\n") + 1) * fs * LH)]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def render_board(board: dict, pages: list[dict], resolve=None) -> bytes:
    """A whiteboard as a PDF. pages = [{"settings": {...}, "objects": [...]}]
    in order. Pages boards: one PDF page each, at the board's paper size.
    Infinite boards: one page fitted around everything drawn."""
    settings = board.get("settings") or {}
    doc = fitz.open()
    try:
        if board.get("kind") == "infinite":
            objs = (pages[0].get("objects") if pages else []) or []
            boxes = [b for b in (_bbox(s) for s in objs) if b]
            if boxes:
                x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
                x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
            else:
                x0, y0, x1, y1 = 0, 0, 1, 1.414
            pad = 0.04 * max(x1 - x0, y1 - y0, 0.2)
            x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
            bw, bh = max(0.05, x1 - x0), max(0.05, y1 - y0)
            k = min(595.0, 14000 / max(bw, bh))   # 1 world unit = an A4 width (595 pt); PDF max is 14400
            page = doc.new_page(width=bw * k, height=bh * k)
            page.draw_rect(page.rect, color=None, fill=paper_rgb(settings), overlay=False)
            _pattern(page, settings, k / 595.0, infinite=True)
            for s in objs:
                try:
                    _draw(page, _scaled(s, x0, y0, bw, bh), resolve)
                except Exception:
                    continue
        else:
            for pg in pages or [{}]:
                ps = {**settings, **(pg.get("settings") or {})}
                W, H = PAGE_SIZES.get(ps.get("size") or "a4", PAGE_SIZES["a4"])
                page = doc.new_page(width=W, height=H)
                page.draw_rect(page.rect, color=None, fill=paper_rgb(ps), overlay=False)
                bg = ps.get("bg")
                path = resolve(bg) if (bg and resolve) else None
                if path:
                    page.insert_image(page.rect, filename=str(path), keep_proportion=True)
                _pattern(page, ps)
                for s in pg.get("objects") or []:
                    try:
                        _draw(page, s, resolve)
                    except Exception:
                        continue
        return doc.tobytes(garbage=1, deflate=True)
    finally:
        doc.close()
