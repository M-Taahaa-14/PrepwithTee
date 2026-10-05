"""Build website/static/ink/stickers.json - the sticker + stamp library.

One source for both renderers: annotate.js draws each SVG as an image on the
page canvas, website/annot_pdf.py embeds the same SVG as vectors when a page is
downloaded. Only plain shapes, flat fills and Helvetica/Arial text are used, so
MuPDF and every browser draw them the same way.

    .venv\\Scripts\\python scripts\\build_stickers.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "website" / "static" / "ink" / "stickers.json"
FONT = 'font-family="Helvetica, Arial, sans-serif" font-weight="bold"'


def star(cx, cy, R, r, n=5, rot=-90):
    pts = []
    for i in range(n * 2):
        a = math.radians(rot + i * 180 / n)
        rad = R if i % 2 == 0 else r
        pts.append(f"{cx + rad * math.cos(a):.1f},{cy + rad * math.sin(a):.1f}")
    return " ".join(pts)


def svg(w, h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{body}</svg>'


def face(extra, mouth, eyes=None):
    eyes = eyes or '<circle cx="35" cy="42" r="6" fill="#3f2a14"/><circle cx="65" cy="42" r="6" fill="#3f2a14"/>'
    return svg(100, 100, '<circle cx="50" cy="50" r="45" fill="#fcd34d" stroke="#d97706" stroke-width="4"/>'
                         + eyes + mouth + extra)


def stamp(text, fg, bg, size=30):
    return svg(240, 84,
               f'<rect x="4" y="4" width="232" height="76" rx="18" fill="{bg}" stroke="{fg}" stroke-width="5"/>'
               f'<rect x="13" y="13" width="214" height="58" rx="12" fill="none" stroke="{fg}" '
               f'stroke-width="1.6" stroke-dasharray="5 4"/>'
               f'<text x="120" y="{42 + size * 0.36:.0f}" text-anchor="middle" font-size="{size}" '
               f'fill="{fg}" {FONT}>{text}</text>')


STICKERS = {
    # ── teacher stamps ──
    "good_work": ("stamps", "Good work!", stamp("Good work!", "#15803d", "#dcfce7")),
    "excellent": ("stamps", "Excellent!", stamp("Excellent!", "#7e22ce", "#f3e8ff")),
    "well_done": ("stamps", "Well done", stamp("Well done", "#1d4ed8", "#dbeafe")),
    "neat": ("stamps", "Neat work", stamp("Neat work", "#db2777", "#fce7f3")),
    "check_again": ("stamps", "Check again", stamp("Check again", "#b45309", "#fef3c7", 28)),
    "show_working": ("stamps", "Show working", stamp("Show working", "#0f766e", "#ccfbf1", 26)),
    "units": ("stamps", "Units?", stamp("Units?", "#c2410c", "#ffedd5")),
    "see_me": ("stamps", "See me", stamp("See me", "#b91c1c", "#fee2e2")),
    "tick": ("stamps", "Tick", svg(100, 100,
        '<circle cx="50" cy="50" r="45" fill="#16a34a"/>'
        '<polyline points="27,52 43,68 74,34" fill="none" stroke="#fff" stroke-width="11" '
        'stroke-linecap="round" stroke-linejoin="round"/>')),
    "cross": ("stamps", "Cross", svg(100, 100,
        '<circle cx="50" cy="50" r="45" fill="#dc2626"/>'
        '<path d="M32 32L68 68M68 32L32 68" stroke="#fff" stroke-width="11" stroke-linecap="round"/>')),
    "half": ("stamps", "Half mark", svg(100, 100,
        '<circle cx="50" cy="50" r="45" fill="#7c3aed"/>'
        f'<text x="50" y="66" text-anchor="middle" font-size="44" fill="#fff" {FONT}>1/2</text>')),
    "hundred": ("stamps", "100", svg(120, 100,
        f'<text x="60" y="62" text-anchor="middle" font-size="54" fill="#dc2626" {FONT}>100</text>'
        '<path d="M12 74Q60 66 108 74" fill="none" stroke="#dc2626" stroke-width="6" stroke-linecap="round"/>'
        '<path d="M18 88Q60 80 102 88" fill="none" stroke="#dc2626" stroke-width="6" stroke-linecap="round"/>')),
    # ── stickers ──
    "star_gold": ("stickers", "Gold star", svg(100, 100,
        f'<polygon points="{star(50, 53, 47, 20)}" fill="#fbbf24" stroke="#b45309" stroke-width="4" '
        'stroke-linejoin="round"/>'
        f'<polygon points="{star(44, 45, 16, 7)}" fill="#fde68a"/>')),
    "star_silver": ("stickers", "Silver star", svg(100, 100,
        f'<polygon points="{star(50, 53, 47, 20)}" fill="#d1d5db" stroke="#4b5563" stroke-width="4" '
        'stroke-linejoin="round"/>'
        f'<polygon points="{star(44, 45, 16, 7)}" fill="#f9fafb"/>')),
    "medal": ("stickers", "Medal", svg(100, 100,
        '<polygon points="30,4 46,4 58,44 42,44" fill="#2563eb"/>'
        '<polygon points="70,4 54,4 42,44 58,44" fill="#ef4444"/>'
        '<circle cx="50" cy="66" r="30" fill="#f59e0b" stroke="#b45309" stroke-width="4"/>'
        '<circle cx="50" cy="66" r="21" fill="#fcd34d"/>'
        f'<text x="50" y="77" text-anchor="middle" font-size="30" fill="#92400e" {FONT}>1</text>')),
    "trophy": ("stickers", "Trophy", svg(100, 100,
        '<path d="M28 12H72V40Q72 62 50 64Q28 62 28 40Z" fill="#fbbf24" stroke="#b45309" stroke-width="4"/>'
        '<path d="M28 20H14Q12 42 30 46M72 20H86Q88 42 70 46" fill="none" stroke="#b45309" stroke-width="5"/>'
        '<rect x="44" y="64" width="12" height="14" fill="#d97706"/>'
        '<rect x="30" y="78" width="40" height="12" rx="3" fill="#92400e"/>'
        f'<polygon points="{star(50, 34, 11, 5)}" fill="#fff7d6"/>')),
    "thumbs_up": ("stickers", "Thumbs up", svg(100, 100,
        '<circle cx="50" cy="50" r="46" fill="#dbeafe"/>'
        '<rect x="18" y="46" width="16" height="34" rx="4" fill="#2563eb"/>'
        '<path d="M36 48L50 24Q53 16 59 20Q63 24 60 34L57 44H76Q84 45 82 54L77 76Q75 82 68 82H36Z" '
        'fill="#fbbf24" stroke="#b45309" stroke-width="3.5" stroke-linejoin="round"/>')),
    "heart": ("stickers", "Heart", svg(100, 100,
        '<path d="M50 88L14 52Q2 38 12 22Q26 6 44 18L50 24L56 18Q74 6 88 22Q98 38 86 52Z" '
        'fill="#f43f5e" stroke="#be123c" stroke-width="4" stroke-linejoin="round"/>'
        '<ellipse cx="30" cy="32" rx="8" ry="5" fill="#fecdd3" transform="rotate(-35 30 32)"/>')),
    "bulb": ("stickers", "Bright idea", svg(100, 100,
        '<path d="M50 8Q76 8 78 36Q78 50 66 60V70H34V60Q22 50 22 36Q24 8 50 8Z" fill="#fde047" '
        'stroke="#ca8a04" stroke-width="4"/>'
        '<rect x="36" y="72" width="28" height="8" rx="2" fill="#6b7280"/>'
        '<rect x="39" y="82" width="22" height="8" rx="3" fill="#4b5563"/>'
        '<path d="M42 58V44L50 50L58 44V58" fill="none" stroke="#ca8a04" stroke-width="3"/>')),
    "rocket": ("stickers", "Rocket", svg(100, 100,
        '<path d="M50 6Q70 22 68 58H32Q30 22 50 6Z" fill="#e5e7eb" stroke="#4b5563" stroke-width="3.5"/>'
        '<circle cx="50" cy="34" r="9" fill="#38bdf8" stroke="#4b5563" stroke-width="3"/>'
        '<path d="M32 46L18 66L32 62ZM68 46L82 66L68 62Z" fill="#ef4444" stroke="#991b1b" stroke-width="3"/>'
        '<path d="M38 60Q50 98 62 60Z" fill="#f97316"/><path d="M44 60Q50 84 56 60Z" fill="#fde047"/>')),
    "fire": ("stickers", "On fire", svg(100, 100,
        '<path d="M50 4Q58 26 74 38Q88 52 82 70Q74 94 50 94Q26 94 18 70Q14 52 28 42Q30 56 40 58Q30 30 50 4Z" '
        'fill="#f97316" stroke="#c2410c" stroke-width="3.5" stroke-linejoin="round"/>'
        '<path d="M50 44Q58 58 64 66Q68 84 50 86Q32 84 36 68Q40 58 50 44Z" fill="#fde047"/>')),
    "sparkle": ("stickers", "Sparkle", svg(100, 100,
        f'<polygon points="{star(50, 50, 46, 10, 4, -90)}" fill="#a78bfa" stroke="#6d28d9" stroke-width="3" '
        'stroke-linejoin="round"/>'
        f'<polygon points="{star(80, 20, 14, 4, 4, -90)}" fill="#f0abfc"/>'
        f'<polygon points="{star(20, 78, 10, 3, 4, -90)}" fill="#c4b5fd"/>')),
    # ── emoji ──
    "grin": ("emoji", "Happy", face("", '<path d="M26 58Q50 86 74 58Z" fill="#7c2d12"/>'
                                    '<path d="M32 60H68Q66 66 60 68H40Q34 66 32 60Z" fill="#fff"/>')),
    "wink": ("emoji", "Wink", face("", '<path d="M30 62Q50 80 70 62" fill="none" stroke="#3f2a14" '
                                   'stroke-width="5" stroke-linecap="round"/>',
                                   '<circle cx="35" cy="42" r="6" fill="#3f2a14"/>'
                                   '<path d="M58 43Q65 36 72 43" fill="none" stroke="#3f2a14" stroke-width="5" '
                                   'stroke-linecap="round"/>')),
    "wow": ("emoji", "Wow", face("", '<ellipse cx="50" cy="68" rx="9" ry="12" fill="#7c2d12"/>',
                                 '<circle cx="35" cy="40" r="8" fill="#fff" stroke="#3f2a14" stroke-width="3"/>'
                                 '<circle cx="65" cy="40" r="8" fill="#fff" stroke="#3f2a14" stroke-width="3"/>'
                                 '<circle cx="35" cy="41" r="4" fill="#3f2a14"/>'
                                 '<circle cx="65" cy="41" r="4" fill="#3f2a14"/>')),
    "cool": ("emoji", "Cool", face("", '<path d="M32 64Q50 76 68 64" fill="none" stroke="#3f2a14" '
                                   'stroke-width="5" stroke-linecap="round"/>',
                                   '<path d="M14 36H86V42Q84 54 70 54Q58 54 56 42H44Q42 54 30 54Q16 54 14 42Z" '
                                   'fill="#1f2937"/>')),
    "think": ("emoji", "Thinking", face(
        '<path d="M56 76Q68 70 74 80Q72 90 60 88Z" fill="#fbbf24" stroke="#d97706" stroke-width="3"/>',
        '<path d="M36 66H58" stroke="#3f2a14" stroke-width="5" stroke-linecap="round"/>',
        '<circle cx="35" cy="44" r="5" fill="#3f2a14"/><circle cx="65" cy="44" r="5" fill="#3f2a14"/>'
        '<path d="M26 32L42 28M58 26L74 32" stroke="#3f2a14" stroke-width="4" stroke-linecap="round"/>')),
    "love": ("emoji", "Love it", face("", '<path d="M28 60Q50 84 72 60Z" fill="#7c2d12"/>',
                                     '<path d="M35 50L25 40Q21 34 26 30Q31 27 35 33Q39 27 44 30Q49 34 45 40Z" fill="#e11d48"/>'
                                     '<path d="M65 50L55 40Q51 34 56 30Q61 27 65 33Q69 27 74 30Q79 34 75 40Z" fill="#e11d48"/>')),
    "sad": ("emoji", "Sad", face('<path d="M30 52Q26 62 30 64Q34 62 30 52Z" fill="#60a5fa"/>',
                                '<path d="M32 72Q50 58 68 72" fill="none" stroke="#3f2a14" stroke-width="5" '
                                'stroke-linecap="round"/>')),
    "party": ("emoji", "Party", face(
        '<polygon points="50,3 37,24 63,24" fill="#a855f7" stroke="#6b21a8" stroke-width="2"/>'
        '<circle cx="50" cy="5" r="4" fill="#facc15"/>',
        '<path d="M28 58Q50 84 72 58Z" fill="#7c2d12"/>',
        '<path d="M28 44Q35 36 42 44M58 44Q65 36 72 44" fill="none" stroke="#3f2a14" stroke-width="5" '
        'stroke-linecap="round"/>')),
}


def main() -> None:
    out = {}
    for key, (cat, name, s) in STICKERS.items():
        vb = s.split('viewBox="', 1)[1].split('"', 1)[0].split()
        out[key] = {"cat": cat, "name": name, "w": float(vb[2]), "h": float(vb[3]), "svg": s}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} stickers -> {OUT}")


if __name__ == "__main__":
    main()
