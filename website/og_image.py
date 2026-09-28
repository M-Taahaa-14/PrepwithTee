"""Social share images (og:image) for the server-rendered sections.

    GET /og/{section}.png                      e.g. /og/papers.png
    GET /og/{section}/{board}.png              e.g. /og/yearly/igcse.png
    GET /og/{section}/{board}/{subject}.png    e.g. /og/notes/igcse/physics-0625.png

The URL mirrors the page it belongs to, and only real sections / boards /
subjects are accepted - no free text, so nobody can make the server draw
arbitrary words. 1200x630 PNG drawn with PyMuPDF (already a dependency, no
Pillow on the server), cached on disk; `og_url(path)` is what catalog._shell
puts in <meta property="og:image">.
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

import catalog as _cat

ROOT = Path(__file__).resolve().parent.parent
OG_DIR = Path(os.environ.get("OG_DIR") or ROOT / "data" / "og")
LOGO = Path(__file__).parent / "static" / "prepwithtee-logo.png"
VERSION = "1"                     # bump to redraw every cached image

W, H = 1200, 630
CREAM = (0.984, 0.953, 0.851)     # the logo PNG's own background
NAVY = (0.161, 0.208, 0.329)
GOLD = (0.957, 0.651, 0.196)
GREY = (0.40, 0.42, 0.48)

SECTIONS = {
    "papers": ("Topical past papers", "Every question sorted by chapter, with the official mark schemes"),
    "yearly": ("Yearly past papers", "Every sitting - question papers, mark schemes and inserts"),
    "mcq": ("MCQ practice", "Timed multiple-choice papers with instant marking"),
    "notes": ("Revision notes", "Chapter-by-chapter notes built on the official syllabus"),
    "resources": ("Resources", "Books, worksheets and study material"),
    "explore": ("Explore PrepWithTee", "Every page, tool and section in one place"),
}

router = APIRouter()


def _resolve(parts: list[str]) -> tuple[str, str, str] | None:
    """(label, title, subtitle) for a path, or None if it isn't a real page."""
    if not parts or parts[0] not in SECTIONS:
        return None
    label, lede = SECTIONS[parts[0]]
    if len(parts) == 1:
        return "PrepWithTee", label, lede
    board = parts[1]
    if board not in _cat.BOARD_SHORT:
        return None
    if len(parts) == 2:
        return label, f"Cambridge {_cat.BOARD_SHORT[board]}", lede
    s = _cat.find_subject(board, parts[2])
    if not s or len(parts) > 3:
        return None
    return label, s["plain"], f"Cambridge {_cat.BOARD_SHORT[board]} · {s['code']}"


def og_url(path: str) -> str:
    """The share image for a page path; falls back to the logo."""
    parts = [p for p in path.split("?")[0].strip("/").split("/") if p][:3]
    while parts and _resolve(parts) is None:
        parts.pop()              # chapter / year pages use their subject's image
    if not parts:
        return f"{_cat.SITE_ORIGIN}/logo.png"
    return f"{_cat.SITE_ORIGIN}/og/{'/'.join(parts)}.png?v={VERSION}"


def _fit(page, rect, text, *, font, size, min_size, color, align=0) -> float:
    """Largest font size (down to min_size) that fits the box; returns the y
    where the text ends."""
    while size > min_size and fitz.get_text_length(text, fontname=font, fontsize=size) > rect.width * 2:
        size -= 2
    while True:
        rc = page.insert_textbox(rect, text, fontname=font, fontsize=size, color=color,
                                 align=align, lineheight=1.1)
        if rc >= 0 or size <= min_size:
            return rect.y1 - max(rc, 0)
        size -= 2


def render(label: str, title: str, subtitle: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.draw_rect(page.rect, color=None, fill=CREAM)
    # Logo on the left (its cream background blends into the page).
    page.insert_image(fitz.Rect(40, 60, 510, 530), filename=str(LOGO))
    # Text column.
    x0, x1 = 560, W - 60
    page.draw_rect(fitz.Rect(x0, 150, x0 + 90, 156), color=None, fill=GOLD)
    page.insert_textbox(fitz.Rect(x0, 100, x1, 145), label.upper(), fontname="hebo",
                        fontsize=24, color=GOLD)
    y = _fit(page, fitz.Rect(x0, 175, x1, 405), title, font="hebo", size=72, min_size=40, color=NAVY)
    _fit(page, fitz.Rect(x0, y + 18, x1, 540), subtitle, font="helv", size=30, min_size=22, color=GREY)
    # Footer band.
    page.draw_rect(fitz.Rect(0, H - 64, W, H), color=None, fill=NAVY)
    page.insert_textbox(fitz.Rect(60, H - 48, W - 60, H - 10),
                        "prepwithtee.com  ·  Expert Cambridge tutoring, Lahore",
                        fontname="hebo", fontsize=22, color=CREAM)
    png = page.get_pixmap(alpha=False).tobytes("png")
    doc.close()
    return png


@router.get("/og/{path:path}", include_in_schema=False)
def og_image(path: str):
    if not path.endswith(".png"):
        raise HTTPException(404)
    parts = [p for p in path[:-4].split("/") if p]
    spec = _resolve(parts)
    if spec is None:
        raise HTTPException(404)
    out = OG_DIR / f"v{VERSION}" / ("_".join(parts) + ".png")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".tmp-{os.getpid()}.png")
        tmp.write_bytes(render(*spec))
        os.replace(tmp, out)
    return FileResponse(out, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=604800"})
