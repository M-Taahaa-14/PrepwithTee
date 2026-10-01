"""Burn a student's annotations (annotate.js strokes) into a copy of a PDF.

Used by "Download with my annotations" (My papers, booklet viewer). Strokes are
stored per 1-based page as fractions of the page as displayed, exactly as
annotate.js draws them; colours are palette tokens ("@blue") resolved with the
LIGHT palette, because a downloaded PDF is white paper. Keep PALETTE in step
with annotate.js.
"""

import re

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
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.11, 0.3, 0.85)


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


def _draw(page: fitz.Page, s: dict) -> None:
    W, H = page.rect.width, page.rect.height
    m = page.derotation_matrix                    # displayed -> unrotated page space

    def P(x, y):
        return fitz.Point(float(x) * W, float(y) * H) * m

    col = _rgb(s.get("c"))
    lw = max(0.6, float(s.get("w") or 0.004) * W)
    t = s.get("t")
    shape = page.new_shape()
    if t in ("pen", "marker"):
        pts = [P(q[0], q[1]) for q in s.get("pts") or [] if len(q) >= 2]
        if not pts:
            return
        if len(pts) == 1:
            shape.draw_circle(pts[0], lw / 2)
            shape.finish(color=col, fill=col, width=0)
        else:
            shape.draw_polyline(pts)
            if t == "marker":
                shape.finish(color=col, width=lw * 3.2, stroke_opacity=0.32, lineCap=0, lineJoin=1,
                             closePath=False)
            else:
                pr = [q[2] for q in s["pts"] if len(q) > 2]
                k = 0.55 + 0.9 * (sum(pr) / len(pr) if pr else 0.5)
                shape.finish(color=col, width=lw * k, lineCap=1, lineJoin=1, closePath=False)
    elif t in ("line", "arrow") and s.get("a") and s.get("b"):
        a, b = P(*s["a"][:2]), P(*s["b"][:2])
        shape.draw_line(a, b)
        shape.finish(color=col, width=lw, lineCap=1)
        if t == "arrow":
            import math
            ang = math.atan2(b.y - a.y, b.x - a.x)
            L = max(7.5, lw * 4)
            tip = [b, fitz.Point(b.x - L * math.cos(ang - 0.45), b.y - L * math.sin(ang - 0.45)),
                   fitz.Point(b.x - L * math.cos(ang + 0.45), b.y - L * math.sin(ang + 0.45))]
            shape.draw_polyline(tip + [b])
            shape.finish(color=col, fill=col, width=0.5, closePath=True)
    elif t in ("rect", "ellipse") and s.get("a") and s.get("b"):
        r = fitz.Rect(P(*s["a"][:2]), P(*s["b"][:2])).normalize()
        (shape.draw_rect if t == "rect" else shape.draw_oval)(r)
        shape.finish(color=col, width=lw)
    elif t == "text" and s.get("txt"):
        _draw_text(page, s, col, P)
        return
    else:
        return
    shape.commit(overlay=True)


def burn(pdf_path, pages: dict[int, list]) -> bytes:
    """A copy of the PDF with every page's strokes drawn on top."""
    doc = fitz.open(pdf_path)
    try:
        for n, strokes in pages.items():
            if not strokes or not 1 <= int(n) <= doc.page_count:
                continue
            page = doc[int(n) - 1]
            for s in strokes:
                try:
                    _draw(page, s)
                except Exception:
                    continue                     # one odd stroke never loses the rest
        return doc.tobytes(garbage=1, deflate=True)
    finally:
        doc.close()
