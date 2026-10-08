"""PrepWithTee social posts - template engine.

Every series folder (study-tips/, memes/, ...) holds a posts.json. Each post is a
list of slides; each slide names a LAYOUT (hook, tip, qa, bigtype, ...) plus its
words. This script turns them into <series>/preview.html and renders every slide
to a PNG at 2x with Playwright:

    .venv\\Scripts\\python marketing\\posts\\build.py                 # everything
    .venv\\Scripts\\python marketing\\posts\\build.py --series memes  # one series
    .venv\\Scripts\\python marketing\\posts\\build.py --only mm-03    # one post
    .venv\\Scripts\\python marketing\\posts\\build.py --html-only     # no PNGs

Output: <series>/png/<post-id>.png (single) or <series>/png/<post-id>/01.png ...
(carousel), <series>/CAPTIONS.md, and gallery.html (contact sheet of everything).

Inline markup in any text field (see README.md):
  **bold**  *italic*  ((marker circle))  __scribble underline__  ==highlighter==
  [[swap colour]]  {{handwriting}}  ~~strike~~  and a newline for a line break.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
UP = "../../../"          # from <series>/preview.html back to the repo root
FONTS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800"
         "&family=Inter:ital,wght@0,400..800;1,400..800&family=Caveat:wght@500..700"
         "&family=Noto+Color+Emoji&family=Space+Mono:wght@400;700"
         "&family=STIX+Two+Text:ital,wght@0,500;1,500&display=block")
OWL = UP + "brand-kit/claude-design/logos/owl-icon-colour.png"
OWL_WHITE = UP + "brand-kit/claude-design/logos/owl-icon-white.png"
SHOTS = UP + "website/static/demos/hero/"
SITE = "prepwithtee.com"
WHATSAPP = "0320 488 4375"
SHOT_W, SHOT_H = 1280, 800     # size of the site screenshots in SHOTS

# ---------------------------------------------------------------- svg bits
CIRCLE = ('<svg viewBox="0 0 200 100" preserveAspectRatio="none"><path d="M30 18C80 2 170 4 192 40'
          'C206 70 150 96 92 95C36 94 4 76 8 50C12 26 50 10 120 8"/></svg>')
SCRIB = ('<svg viewBox="0 0 200 20" preserveAspectRatio="none"><path d="M2 12C40 4 80 18 120 9'
         'S180 6 198 11"/></svg>')
CHECK = '<svg viewBox="0 0 60 60"><path d="M8 32L24 48L54 10"/></svg>'
CROSS = '<svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M14 14L86 88M88 12L12 86"/></svg>'
NEXT = '<svg viewBox="0 0 40 40"><path d="M12 6L28 20L12 34"/></svg>'
SWIPE = ('<svg viewBox="0 0 64 20"><path d="M2 10H60M50 2L61 10L50 18" fill="none" stroke="currentColor"'
         ' stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')
WA = ('<svg viewBox="0 0 32 32" fill="currentColor"><path d="M16 3a13 13 0 0 0-11.2 19.6L3 29l6.6-1.7A13 13 0 1 0 16 3zm0 '
      '23.6c-2 0-3.9-.5-5.6-1.5l-.4-.2-3.9 1 1-3.8-.3-.4A10.6 10.6 0 1 1 16 26.6zm5.8-7.9c-.3-.2-1.9-.9-2.2-1-.3-.1-.5-.2-.7.2l-1 '
      '1.2c-.2.2-.4.2-.7.1a8.7 8.7 0 0 1-4.3-3.8c-.3-.6.3-.5 1-1.7.1-.2 0-.4 0-.5l-1-2.4c-.3-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 '
      '1-1 2.5s1.1 2.9 1.2 3.1c.2.2 2.1 3.2 5.1 4.5 1.9.8 2.6.9 3.6.7.6-.1 1.9-.8 2.1-1.5.3-.7.3-1.4.2-1.5-.1-.1-.3-.2-.6-.3z"/></svg>')

# hand-drawn doodles: name -> (viewBox, inner svg). Placed with "doodles": [[name, x, y, w, rot, colour]]
DOODLES = {
    "arrow-curl": ("0 0 200 170", '<path d="M10 20C60 0 120 10 130 60C135 95 110 110 95 95C80 80 110 60 140 80'
                   'C160 95 165 120 160 150"/><path d="M144 136L160 152L174 132"/>'),
    "arrow-down": ("0 0 180 160", '<path d="M40 10C120 10 150 60 120 140"/><path d="M100 126L120 144L138 120"/>'),
    "arrow-right": ("0 0 200 60", '<path d="M5 30C60 22 120 36 190 28"/><path d="M170 12L192 28L170 46"/>'),
    "arrow-loop": ("0 0 200 140", '<path d="M190 20C150 10 110 30 120 60C128 85 160 80 150 58C140 36 90 50 60 80'
                   'C45 95 30 110 20 120"/><path d="M16 96L18 122L44 120"/>'),
    "arrow-up": ("0 0 120 180", '<path d="M30 170C10 120 40 60 90 20"/><path d="M62 18L92 16L88 46"/>'),
    "sparkle": ("0 0 100 100", '<path class="fill" d="M50 0C54 36 64 46 100 50C64 54 54 64 50 100C46 64 36 54 0 50'
                'C36 46 46 36 50 0Z"/>'),
    "sparkle-o": ("0 0 100 100", '<path d="M50 4C54 36 64 46 96 50C64 54 54 64 50 96C46 64 36 54 4 50C36 46 46 36 50 4Z"/>'),
    "burst": ("0 0 70 70", '<path d="M8 60L34 50M18 22L42 34M52 4L56 30"/>'),
    "squiggle": ("0 0 160 60", '<path d="M5 30C25 0 35 60 55 30S85 0 105 30S135 60 155 30"/>'),
    "swirl": ("0 0 140 100", '<path d="M20 80C0 40 60 0 80 40C95 70 55 85 50 60C45 35 90 20 130 50"/>'),
    "heart": ("0 0 100 100", '<path d="M50 85C10 60 0 30 25 18C40 10 50 25 50 30C50 25 60 10 75 18C100 30 90 60 50 85Z"/>'),
    "star": ("0 0 100 100", '<path d="M50 6L62 38L96 38L68 58L79 92L50 72L21 92L32 58L4 38L38 38Z"/>'),
    "crown": ("0 0 120 80", '<path d="M10 70L20 20L45 50L60 10L75 50L100 20L110 70Z"/>'),
    "underline": ("0 0 200 20", '<path d="M2 12C40 4 80 18 120 9S180 6 198 11"/>'),
    "circle": ("0 0 200 100", '<path d="M30 18C80 2 170 4 192 40C206 70 150 96 92 95C36 94 4 76 8 50C12 26 50 10 120 8"/>'),
    "zigzag": ("0 0 160 40", '<path d="M4 30L24 10L44 30L64 10L84 30L104 10L124 30L144 10"/>'),
    "lamp": ("0 0 300 420", '<path d="M70 410H210M140 410V350L70 230L165 110"/><path d="M165 110L268 55L292 150Z"/>'
             '<path d="M70 230m-12 0a12 12 0 1 0 24 0a12 12 0 1 0 -24 0"/>'),
}
COLOURS = {"ink": "var(--ink)", "white": "#fff", "lime": "var(--lime)", "sun": "var(--sun)", "coral": "var(--coral)",
           "lilac": "var(--lilac)", "sky": "var(--sky)", "bubble": "var(--bubble)", "mint": "var(--mint)",
           "tang": "var(--tang)", "gold": "var(--gold)", "navy": "var(--navy)", "purple": "var(--purple)"}
INKS = {"lime": "var(--lime-ink)", "lilac": "var(--lilac-ink)", "sky": "var(--sky-ink)", "sun": "var(--sun-ink)",
        "tang": "var(--tang-ink)", "bubble": "var(--bubble-ink)", "mint": "var(--mint-ink)", "coral": "var(--coral-ink)"}
DARK_BGS = {"navy", "mood", "desk", "wall", "wall2", "spot", "black", "retro"}


def col(name: str | None, default: str = "var(--ink)") -> str:
    if not name:
        return default
    return COLOURS.get(name, name)


# ---------------------------------------------------------------- markup
def md(text: str | None) -> str:
    if not text:
        return ""
    s = html.escape(text, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"==(.+?)==", r'<span class="hl">\1</span>', s)
    s = re.sub(r"\[\[(.+?)\]\]", r'<span class="swap">\1</span>', s)
    s = re.sub(r"\{\{(.+?)\}\}", r'<span class="hand">\1</span>', s)
    s = re.sub(r"\(\((.+?)\)\)", lambda m: f'<span class="circ">{m[1]}{CIRCLE}</span>', s)
    s = re.sub(r"__(.+?)__", lambda m: f'<span class="scrib">{m[1]}{SCRIB}</span>', s)
    return s.replace("\n", "<br>")


def style(**kv) -> str:
    parts = [f"{k.replace('_', '-')}:{v}" for k, v in kv.items() if v is not None]
    return f' style="{";".join(parts)}"' if parts else ""


def doodles(items) -> str:
    out = []
    for d in items or []:
        name, x, y, w = d[0], d[1], d[2], d[3]
        rot = d[4] if len(d) > 4 else 0
        c = col(d[5]) if len(d) > 5 else None
        vb, inner = DOODLES[name]
        out.append(f'<div class="doodle"{style(left=f"{x}px", top=f"{y}px", width=f"{w}px", transform=f"rotate({rot}deg)", color=c)}>'
                   f'<svg viewBox="{vb}">{inner}</svg></div>')
    return "".join(out)


def torn_clip(seed: str, jag_bottom=True, jag_top=False) -> str:
    """A clip-path polygon with a ripped edge (deterministic per slide)."""
    rnd = random.Random(seed)
    top = [(0, 0), (100, 0)]
    if jag_top:
        top = [(x, rnd.uniform(0, 2.2)) for x in range(0, 101, 4)]
    bottom = [(100, 100), (0, 100)]
    if jag_bottom:
        bottom = [(x, 100 - rnd.uniform(0, 3.2)) for x in range(100, -1, -4)]
    pts = top + bottom
    return "polygon(" + ",".join(f"{x:.1f}% {y:.1f}%" for x, y in pts) + ")"


# ---------------------------------------------------------------- layouts
# Each returns the inner HTML for one slide. `s` = slide dict, `ctx` = post-level info.

def L_hook(s, ctx):
    pos = s.get("align", "")
    h = f'<h1 class="h-{s.get("size", "xl")}">{md(s["title"])}</h1>'
    eb = f'<div class="eyebrow"{style(color=col(s.get("eyebrow_c")))}>{md(s["eyebrow"])}</div>' if s.get("eyebrow") else ""
    k = f'<div class="kicker">{md(s["kicker"])}</div>' if s.get("kicker") else ""
    sub = f'<p class="sub">{md(s["sub"])}</p>' if s.get("sub") else ""
    note = ""
    if s.get("note"):
        note = (f'<div class="torn {s.get("note_style", "lime")}"{style(clip_path=torn_clip(ctx["sid"]), transform="rotate(-3deg)", margin_top="10px", max_width="760px", align_self="flex-end" if s.get("note_right") else None)}>'
                f'<p>{md(s["note"])}</p></div>')
    return f'<div class="hook {pos}">{eb}{h}{k}{sub}{note}</div>'


def L_tip(s, ctx):
    n = s.get("num", "")
    body = f'<p>{md(s["body"])}</p>' if s.get("body") else ""
    tr = f'<div class="try">{md(s["try"])}</div>' if s.get("try") else ""
    return (f'<div class="tip"><div class="num"><span class="circ">{html.escape(n)}{CIRCLE}</span></div>'
            f'<h2>{md(s["title"])}</h2>{body}{tr}</div>')


def L_qa(s, ctx):
    label = (f'<div class="qa-label"{style(color=col(s.get("label_ink")))}><span{style(color=col(s.get("label_c"), "#fff"))}>'
             f'{md(s["subject"])}</span><br>{md(s.get("label", "QUESTION:"))}</div>')
    lines = "".join(f"<p>{md(p)}</p>" for p in s["answer"])
    if s.get("mistake"):
        lines += f'<p class="small"><b>Common mistake:</b> {md(s["mistake"])}</p>'
    rot = s.get("rot", -2.5)
    note = (f'<div class="torn holes"{style(clip_path=torn_clip(ctx["sid"], True, True), transform=f"rotate({rot}deg)", __hole=None)}>'
            f'{lines}</div>')
    owl = ""
    if s.get("owl", True):
        ox, oy, orot = s.get("owl_at", [770, 300, 10])
        owl = f'<img class="owl-peek" src="{OWL}"{style(left=f"{ox}px", top=f"{oy}px", transform=f"rotate({orot}deg)")}>'
        if s.get("owl_says"):
            owl += f'<div class="bubble-say"{style(left=f"{ox - 70}px", top=f"{oy - 105}px", transform="rotate(-4deg)")}>{md(s["owl_says"])}</div>'
    return f'<div class="qa">{label}<h2 class="qa-q">{md(s["question"])}</h2>{note}</div>', owl


def L_steps(s, ctx):
    head = f'<div class="list-head"><h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2>' \
           f'{"<p class=sub>" + md(s["sub"]) + "</p>" if s.get("sub") else ""}</div>'
    items = "".join(f'<li><span class="n"><span class="circ">{i + 1:02d}{CIRCLE}</span></span>'
                    f'<div><b>{md(it[0])}</b><span>{md(it[1])}</span></div></li>' for i, it in enumerate(s["items"]))
    return f'{head}<ol class="steps">{items}</ol>'


def L_checklist(s, ctx):
    head = f'<div class="list-head"><h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2>' \
           f'{"<p class=sub>" + md(s["sub"]) + "</p>" if s.get("sub") else ""}</div>'
    boxed = s.get("boxed")
    items = []
    for it in s["items"]:
        t, small = (it, "") if isinstance(it, str) else (it[0], it[1])
        mark = f'<span class="box">{CHECK}</span>' if boxed else CHECK
        items.append(f'<li>{mark}<div>{md(t)}{"<small>" + md(small) + "</small>" if small else ""}</div></li>')
    tail = f'<p class="foot-hand" style="text-align:left">{md(s["tail"])}</p>' if s.get("tail") else ""
    return f'<div class="listwrap">{head}<ul class="checks{" boxed" if boxed else ""}">{"".join(items)}</ul>{tail}</div>'


def L_defs(s, ctx):
    head = f'<div class="list-head"><h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2>' \
           f'{"<p class=sub>" + md(s["sub"]) + "</p>" if s.get("sub") else ""}</div>'
    cs = s.get("colours", ["lime", "lilac", "sky", "sun", "bubble", "mint", "tang"])
    rows = "".join(f'<div class="row"><dt><span{style(__c=col(cs[i % len(cs)]))}>{md(t)}</span></dt><dd>{md(d)}</dd></div>'
                   for i, (t, d) in enumerate(s["items"]))
    tail = f'<p class="foot-hand" style="text-align:left;margin-top:44px">{md(s["tail"])}</p>' if s.get("tail") else ""
    return f'{head}<dl class="defs">{rows}</dl>{tail}'


def L_bigtype(s, ctx):
    lines = "".join(f'<span class="line">{md(t)}</span>' for t in s["lines"])
    after = f'<p class="after">{md(s["after"])}</p>' if s.get("after") else ""
    return f'<div class="bigtype"{style(__bt=f"{s.get("px", 150)}px")}><h1>{lines}</h1>{after}</div>'


def L_quote(s, ctx):
    tail = ""
    if s.get("tail"):
        tail = f'<div class="tail">{md(s["tail"])}{"<small>" + md(s["tail_sub"]) + "</small>" if s.get("tail_sub") else ""}</div>'
    return (f'<div class="quote"><div class="q66">&ldquo;</div><blockquote>{md(s["quote"])}</blockquote>'
            f'<cite>{md(s["name"])}<span>{md(s.get("role", ""))}</span></cite></div>{tail}')


def L_cards(s, ctx):
    pos = [(60, 400, -4), (540, 520, 4), (70, 890, -2)]
    cs = s.get("colours", ["#A35CD6", "#5E6BE0", "#2C6699"])
    out = [f'<div class="cards-head"><h2 class="h-l">{md(s["title"])}</h2></div>']
    for i, c in enumerate(s["cards"][:3]):
        x, y, r = pos[i]
        out.append(f'<div class="tcard"{style(left=f"{x}px", top=f"{y}px", transform=f"rotate({r}deg)", background=col(cs[i]))}>'
                   f'<div class="stars">★★★★★</div><p>{md(c["text"])}</p>'
                   f'<div class="who"><span class="emo">{c.get("emoji", "🙂")}</span><div><b>{md(c["name"])}</b>'
                   f'<span>{md(c["role"])}</span></div></div></div>')
    return "".join(out[:1]), "".join(out[1:])


def L_rows(s, ctx):
    blocks = []
    for r in s["rows"]:
        cells = "".join(f'<div><span class="sticker">{c[0]}</span><p>{md(c[1])}</p></div>' for c in r["items"])
        blocks.append(f'<div><h2>{md(r["title"])}</h2><div class="trio">{cells}</div></div>')
    return f'<div class="rows">{"".join(blocks)}</div>'


def L_grid4(s, ctx):
    cs = s.get("colours", ["lilac", "sun", "mint", "bubble"])
    tiles = "".join(f'<div class="t"{style(background=col(cs[i % len(cs)]))}><span class="sticker">{t[0]}</span>'
                    f'<b>{md(t[1])}</b><span>{md(t[2])}</span></div>' for i, t in enumerate(s["tiles"]))
    foot = f'<p class="foot-hand">{md(s["foot"])}</p>' if s.get("foot") else ""
    return f'<h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2><div class="g4">{tiles}</div>{foot}'


def L_bingo(s, ctx):
    cells = list(s["cells"])
    cells.insert(12, None)
    hits = set(s.get("hits", []))
    out = []
    for i, c in enumerate(cells):
        if c is None:
            out.append(f'<div class="free"><img src="{OWL}"></div>')
        else:
            out.append(f'<div class="hit">{CIRCLE}<span>{md(c)}</span></div>' if i in hits else f'<div><span>{md(c)}</span></div>')
    sub = f'<p class="hand" style="font-size:46px">{md(s["sub"])}</p>' if s.get("sub") else ""
    return (f'<div class="bingo-title"><h2 class="h-l">{md(s["title"])}</h2>{sub}</div>'
            f'<div class="bingo">{"".join(out)}</div>')


def L_versus(s, ctx):
    halves = []
    for h in s["halves"]:
        stickers = "".join(f'<span class="sticker">{e}</span>' for e in h["emoji"])
        halves.append(f'<div class="half"{style(background=col(h.get("bg", "lilac")))}><span class="tag">{md(h["tag"])}</span>'
                      f'<p class="say">{md(h["say"])}</p><div class="collage">{stickers}</div></div>')
    return f'<h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2><div class="vs">{"".join(halves)}</div>'


def L_journal(s, ctx):
    """A grid notebook on a desk with taped notes, a sticky note and polaroids."""
    back = '<div class="journal"></div>'
    head = f'<div class="j-in"><div class="j-title">{md(s["title"])}</div><div class="j-sub">{md(s.get("sub", ""))}</div></div>'
    bits = []
    n = s.get("note")
    if n:
        bits.append(f'<div class="paper-note"{style(left="200px", top="640px", width="560px", transform="rotate(-2deg)", clip_path=torn_clip(ctx["sid"]))}>'
                    f'<p>{md(n["text"])}</p><div class="meta">{md(n.get("meta", ""))}</div></div>'
                    f'<div class="tape"{style(left="380px", top="616px", transform="rotate(-3deg)")}></div>')
    st = s.get("sticky")
    if st:
        bits.append(f'<div class="sticky"{style(left="600px", top="900px", width="350px", transform="rotate(3deg)")}>{md(st)}</div>')
    for i, p in enumerate(s.get("polaroids", [])[:2]):
        x, y, r = [(790, 560, 6), (130, 880, -7)][i]
        bits.append(f'<figure class="polaroid"{style(left=f"{x}px", top=f"{y}px", transform=f"rotate({r}deg)")}>'
                    f'<div class="ph"{style(__c=col(p[2] if len(p) > 2 else "lilac"))}><span class="sticker">{p[0]}</span></div>'
                    f'<figcaption>{md(p[1])}</figcaption></figure>'
                    f'<div class="tape"{style(left=f"{x + 60}px", top=f"{y - 24}px", transform=f"rotate({r - 4}deg)", width="150px")}></div>')
    if s.get("button"):
        bits.append(f'<div class="tape-btn"{style(left="150px", bottom="52px")}>{md(s["button"])}</div>')
    return "", back + head + "".join(bits)


def L_mood(s, ctx):
    sub = f'<p class="sub" style="font-size:48px;line-height:1.3;color:rgba(255,255,255,.9);font-weight:600">{md(s["sub"])}</p>' if s.get("sub") else ""
    return (f'<div class="hook" style="gap:56px"><h1 class="h-{s.get("size", "m")}" style="font-weight:700;letter-spacing:-.03em;line-height:1.08">'
            f'{md(s["title"])}</h1>{sub}</div>')


def shot_style(img, crop, w):
    x, y, cw, ch = crop
    k = w / cw
    return dict(width=f"{w}px", height=f"{round(ch * k)}px", background_image=f"url('{SHOTS}{img}')",
                background_size=f"{round(SHOT_W * k)}px {round(SHOT_H * k)}px",
                background_position=f"{-round(x * k)}px {-round(y * k)}px")


def L_device(s, ctx):
    head = (f'<div class="dev-head"><div class="eyebrow" style="margin-bottom:22px">{md(s.get("eyebrow", ""))}</div>'
            f'<h2 class="h-{s.get("size", "m")}">{md(s["title"])}</h2>'
            f'{"<p class=sub style=margin-top:24px>" + md(s["sub"]) + "</p>" if s.get("sub") else ""}</div>')
    over = []
    lx, ly, lw = s.get("laptop_at", [120, 640, 900])
    scr_h = round(lw * SHOT_H / SHOT_W)
    over.append(f'<div class="laptop"{style(left=f"{lx}px", top=f"{ly}px", width=f"{lw}px")}>'
                f'<div class="scr"{style(height=f"{scr_h}px")}><div{style(background_image=f"url({SHOTS}{s["shot"]})")}></div></div>'
                f'<div class="base"></div></div>')
    for z in s.get("zooms", []):
        st = shot_style(z.get("shot", s["shot"]), z["crop"], z["w"])
        st.update(left=f'{z["at"][0]}px', top=f'{z["at"][1]}px', transform=f'rotate({z.get("rot", 0)}deg)')
        over.append(f'<div class="zoom"{style(**st)}></div>')
    for c in s.get("callouts", []):
        over.append(f'<div class="callout"{style(left=f"{c[1]}px", top=f"{c[2]}px", transform=f"rotate({c[3] if len(c) > 3 else -3}deg)", background=col(c[4]) if len(c) > 4 else None)}>{md(c[0])}</div>')
    return head, "".join(over)


def L_cta(s, ctx):
    btns = []
    if s.get("button"):
        btns.append(f'<span class="btn">{md(s["button"])} <svg viewBox="0 0 40 40"><path d="M8 20H32M22 10L32 20L22 30" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>')
    if s.get("whatsapp"):
        btns.append(f'<span class="btn wa">{WA} {WHATSAPP}</span>')
    sub = f'<p class="sub">{md(s["sub"])}</p>' if s.get("sub") else ""
    return f'<div class="cta"><h1 class="h-{s.get("size", "l")}">{md(s["title"])}</h1>{sub}<div class="btns">{"".join(btns)}</div></div>'


def L_promo(s, ctx):
    eb = f'<div class="eyebrow" style="margin-bottom:26px">{md(s.get("eyebrow", ""))}</div>'
    h = f'<h1 class="h-{s.get("size", "xl")}">{md(s["title"])}</h1>'
    sub = f'<p class="sub" style="margin-top:30px;color:var(--ink)">{md(s["sub"])}</p>' if s.get("sub") else ""
    chips = "".join(f'<span class="chip">{md(c)}</span>' for c in s.get("chips", []))
    over = []
    if s.get("badge"):
        b = s["badge"]
        over.append(f'<div class="badge"{style(right="84px", top="66px", background=col(b[1]), transform="rotate(4deg)")}>{md(b[0])}</div>')
    if s.get("burst"):
        b = s["burst"]
        x, y, w = b.get("at", [640, 560, 360])
        pts = []
        for i in range(32):
            import math
            r = 50 if i % 2 == 0 else 43
            a = math.pi * i / 16
            pts.append(f"{50 + r * math.cos(a):.1f},{50 + r * math.sin(a):.1f}")
        over.append(f'<div class="burst"{style(left=f"{x}px", top=f"{y}px", width=f"{w}px", height=f"{w}px", transform=f"rotate({b.get("rot", 8)}deg)")}>'
                    f'<svg viewBox="0 0 100 100"><polygon points="{" ".join(pts)}" fill="{col(b.get("bg", "lime"))}" stroke="#15131C" stroke-width="1.2"/></svg>'
                    f'<div class="bt">{md(b["top"])}<big>{md(b["big"])}</big>{md(b["bottom"])}</div></div>')
    if s.get("bar", True):
        over.append(f'<div class="bar"><div><b>{md(s.get("bar_title", "Book a free demo"))}</b><span>{SITE} · online or in Lahore</span></div>'
                    f'<span class="wa">{WA} {WHATSAPP}</span></div>')
    return f'{eb}{h}{sub}<div class="chiprow" style="margin-top:44px">{chips}</div>', "".join(over)


# ---------------------------------------------------------------- internet-format layouts
# (styles in assets/formats.css)

def _title(s, size="m", cls=""):
    if not s.get("title"):
        return ""
    return f'<h2 class="h-{s.get("size", size)} {cls}">{md(s["title"])}</h2>'


def _vc(inner):
    """Centre a layout's block vertically in the content box (no dead band at the bottom)."""
    return f'<div class="vc">{inner}</div>'


def _foot(s, cls):
    return f'<div class="{cls}">{md(s["foot"])}</div>' if s.get("foot") else ""


def L_chat(s, ctx):
    msgs = []
    for who, t in s["msgs"]:
        if who in ("time", "read"):
            msgs.append(f'<div class="msg-{who}">{md(t)}</div>')
        else:
            msgs.append(f'<div class="msg {who}">{md(t)}</div>')
    return (f'{_title(s, "s", "chat-title")}<div class="chat"><div class="chat-head">'
            f'<div class="av"{style(background=col(s.get("av_bg", "lilac")))}>{s.get("avatar", "🙂")}</div>'
            f'<div><b>{md(s["contact"])}</b><span>{md(s.get("status", "online"))}</span></div></div>'
            f'<div class="chat-body">{"".join(msgs)}</div></div>')


TIER_COLOURS = {"S": "#FF7F7F", "A": "#FFBF7F", "B": "#FFDF7F", "C": "#FFFF7F", "D": "#BFFF7F", "F": "#7FBFFF"}


def L_tier(s, ctx):
    rows = []
    for lab, items in s["rows"]:
        its = "".join(f'<span class="it"><span class="emo">{e}</span>{md(t)}</span>' for e, t in items)
        rows.append(f'<div class="row"><div class="lab" style="background:{TIER_COLOURS.get(lab, "#ddd")}">{html.escape(lab)}</div>'
                    f'<div class="items">{its}</div></div>')
    return _vc(f'{_title(s)}<div class="tier">{"".join(rows)}</div>{_foot(s, "tier-foot")}')


def L_tot(s, ctx):
    pairs = "".join(f'<div class="pair"><div class="opt"><span class="emo">{a}</span>{md(b)}</div><div class="or">or</div>'
                    f'<div class="opt"><span class="emo">{c}</span>{md(d)}</div></div>' for a, b, c, d in s["pairs"])
    return _vc(f'{_title(s)}<div class="tot">{pairs}</div>{_foot(s, "tier-foot")}')


def L_quiz(s, ctx):
    tags = "".join(f'<span class="qtag"{style(background=col(c))}>{md(t)}</span>' for t, c in s.get("tags", []))
    reveal, ans = s.get("reveal"), s.get("answer")
    opts = []
    for i, o in enumerate(s["options"]):
        cls = "qo" + ((" right" if i == ans else " wrong") if reveal else "")
        opts.append(f'<div class="{cls}"><span class="l">{"ABCD"[i]}</span><span>{md(o)}</span></div>')
    why = f'<div class="why">{md(s["why"])}</div>' if reveal and s.get("why") else ""
    cta = f'<div class="qcta">{md(s["cta"])}</div>' if not reveal and s.get("cta") else ""
    return f'<div class="quiz"><div class="qmeta">{tags}</div><div class="qtext">{md(s["q"])}</div><div class="qos">{"".join(opts)}</div>{why}{cta}</div>'


def L_notif(s, ctx):
    ns = "".join(f'<div class="notif"><div class="ic">{n[0]}</div><div class="tx"><div class="top"><span>{md(n[1])}</span>'
                 f'<span>{md(n[4] if len(n) > 4 else "now")}</span></div><b>{md(n[2])}</b><p>{md(n[3])}</p></div></div>'
                 for n in s["notifs"])
    cap = f'<div class="cap">{md(s["cap"])}</div>' if s.get("cap") else ""
    return "", f'<div class="lock"><div class="date">{md(s.get("date", ""))}</div><div class="clock">{md(s["clock"])}</div><div class="notifs">{ns}</div>{cap}</div>'


def L_tweet(s, ctx):
    after = f'<div class="after">{md(s["after"])}</div>' if s.get("after") else ""
    return (f'<div class="tweet"><div class="tw"><div class="tw-head"><img src="{OWL}"><div><b>PrepWithTee</b><span>{SITE}</span></div></div>'
            f'<div class="tw-text">{md(s["text"])}</div><div class="tw-foot">{md(s.get("when", "2:47 AM · exam season"))}</div></div>{after}</div>')


def L_myth(s, ctx):
    rows = "".join(f'<div class="myth"><div class="m"><small>myth</small><p>{md(m)}</p></div><div class="f"><small>fact</small><p>{md(f)}</p></div></div>'
                   for m, f in s["items"])
    return _vc(f'{_title(s)}<div class="myths">{rows}</div>{_foot(s, "tier-foot")}')


def L_receipt(s, ctx):
    lines = "".join(f'<div class="ln"><span>{md(a)}</span><span>{md(b)}</span></div>' for a, b in s["items"])
    tot = "".join(f'<div class="ln tot"><span>{md(a)}</span><span>{md(b)}</span></div>' for a, b in s["total"])
    clip = torn_clip(ctx["sid"], True, True)
    over = (f'<div class="receipt"{style(clip_path=clip, transform=f"rotate({s.get("rot", -1.5)}deg)")}><h3>{md(s["store"])}</h3>'
            f'<div class="meta">{md(s.get("meta", ""))}</div><div class="dash"></div>{lines}<div class="dash"></div>{tot}'
            f'<div class="bc"></div><div class="ft">{md(s.get("footer", ""))}</div></div>')
    if s.get("note"):
        x, y = s.get("note_at", [90, 1130])
        over += f'<div class="rc-note"{style(left=f"{x}px", top=f"{y}px", color=col(s.get("note_c")) if s.get("note_c") else None)}>{md(s["note"])}</div>'
    return "", over


MAG = ('<svg viewBox="0 0 24 24" width="36" height="36"><circle cx="10" cy="10" r="7" fill="none" stroke="#9aa0a6" stroke-width="2.4"/>'
       '<path d="M15.5 15.5L21 21" stroke="#9aa0a6" stroke-width="2.4" stroke-linecap="round"/></svg>')


def L_search(s, ctx):
    q = html.escape(s["query"])
    sugs = "".join(f'<div class="sug">{MAG}<span>{q}<b>{md(x)}</b></span></div>' for x in s["suggestions"])
    return _vc(f'{_title(s)}<div class="search"><div class="sq">{MAG}<span>{q}</span><span class="caret"></span></div>{sugs}</div>{_foot(s, "search-foot")}')


def L_playlist(s, ctx):
    now = s.get("now", 0)
    tr = "".join(f'<div class="trk{" now" if i == now else ""}"><i>{"▶" if i == now else i + 1}</i><div><b>{md(t[0])}</b>'
                 f'<span>{md(t[1])}</span></div><em>{html.escape(t[2])}</em></div>' for i, t in enumerate(s["tracks"]))
    cover = (f'<div class="pl-cover"{style(background=s.get("cover_bg", "linear-gradient(135deg,#CBF266,#9BD7FF)"))}>'
             f'<span class="sticker">{s.get("cover_emoji", "🎧")}</span><div class="ct">{md(s.get("cover_text", ""))}</div></div>')
    return (f'<div class="pl"><div class="pl-top">{cover}<div class="pl-meta"><small>{md(s.get("kind", "playlist"))}</small>'
            f'<h2>{md(s["title"])}</h2><p>{md(s.get("by", "PrepWithTee"))}</p></div></div><div class="tracks">{tr}</div></div>')


def L_wrapped(s, ctx):
    blks = []
    for b in s["blocks"]:
        blks.append(f'<div class="blk{" list" if b.get("list") else ""}"{style(background=col(b.get("bg", "lime")), __r=f"{b.get("rot", 0)}deg")}>'
                    f'<small>{md(b["label"])}</small><big>{md(b["big"])}</big><span>{md(b.get("sub", ""))}</span></div>')
    eb = f'<div class="eyebrow">{md(s["eyebrow"])}</div>' if s.get("eyebrow") else ""
    return f'<div class="wr">{eb}{_title(s)}{"".join(blks)}</div>'


def L_error(s, ctx):
    bs = s["buttons"]
    btns = "".join(f'<span class="{"pri" if i == len(bs) - 1 else ""}">{md(b)}</span>' for i, b in enumerate(bs))
    over = (f'<div class="win"{style(top=f"{s.get("top", 440)}px")}><div class="win-bar"><span>{md(s.get("app", "System"))}</span><span class="x">✕</span></div>'
            f'<div class="win-body"><div class="ic">{s.get("icon", "⚠️")}</div><div><h3>{md(s["msg"])}</h3><p>{md(s.get("detail", ""))}</p></div></div>'
            f'<div class="win-btns">{btns}</div></div>')
    return _title(s, "l"), over


def L_ticket(s, ctx):
    t = s["ticket"]
    grid = "".join(f'<div><small>{md(a)}</small><b>{md(b)}</b></div>' for a, b in t["fields"])
    over = (f'<div class="ticket"><div class="tk-main"><div class="tk-air"><span>{md(t.get("airline", "PrepWithTee Air"))}</span>'
            f'<span>{md(t.get("cls", "boarding pass"))}</span></div>'
            f'<div class="tk-route"><div><small>{md(t["from_l"])}</small><b>{md(t["from"])}</b></div><div class="plane">✈️</div>'
            f'<div style="text-align:right"><small>{md(t["to_l"])}</small><b>{md(t["to"])}</b></div></div>'
            f'<div class="tk-grid">{grid}</div></div><div class="tk-stub"><div><small>passenger</small><b>{md(t.get("name", "YOU"))}</b></div>'
            f'<div class="bc"></div><div><small>{md(t.get("stub_l", "seat"))}</small><b>{md(t.get("stub", ""))}</b></div></div></div>')
    if s.get("bar", True):
        over += (f'<div class="bar"><div><b>{md(s.get("bar_title", "Book a free demo"))}</b><span>{SITE} · online or in Lahore</span></div>'
                 f'<span class="wa">{WA} {WHATSAPP}</span></div>')
    eb = f'<div class="eyebrow" style="margin-bottom:20px">{md(s["eyebrow"])}</div>' if s.get("eyebrow") else ""
    return eb + _title(s, "l"), over


def L_starter(s, ctx):
    tilt = [-2, 1.5, -1, 2, -1.5, 1]
    cells = "".join(f'<div{style(transform=f"rotate({tilt[i % 6]}deg)")}><span class="sticker">{e}</span><p>{md(t)}</p></div>'
                    for i, (e, t) in enumerate(s["items"]))
    return _vc(f'{_title(s)}<div class="sp">{cells}</div>{_foot(s, "tier-foot")}')


def L_flags(s, ctx):
    g = "".join(f'<li><span class="emo">🟢</span><span>{md(t)}</span></li>' for t in s["green"])
    r = "".join(f'<li><span class="emo">🚩</span><span>{md(t)}</span></li>' for t in s["red"])
    return _vc(f'{_title(s)}<div class="flags"><div class="col g"><h3>green flags</h3><ul>{g}</ul></div>'
            f'<div class="col r"><h3>red flags</h3><ul>{r}</ul></div></div>{_foot(s, "tier-foot")}')


def L_notes(s, ctx):
    items = []
    for it in s["items"]:
        text, done = (it[0], it[1]) if isinstance(it, list) else (it, False)
        items.append(f'<li class="{"done" if done else ""}"><span class="c"></span><span>{md(text)}</span></li>')
    return (f'<div class="nt"><div class="nt-bar"><span>‹ Notes</span><span>Done</span></div><h2>{md(s["title"])}</h2>'
            f'<div class="d">{md(s.get("date", ""))}</div><ul>{"".join(items)}</ul></div>')


def fx(t: str) -> str:
    """Formula markup: ^{sup} _{sub} {numerator // denominator}; plain letters are italic (serif)."""
    s = md(t)
    s = re.sub(r"\^\{([^{}]+)\}", r"<sup>\1</sup>", s)
    s = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", s)
    s = re.sub(r"\{(.+?) // (.+?)\}", r'<span class="fr"><span>\1</span><span>\2</span></span>', s)
    s = re.sub(r"\b(sin|cos|tan|NOT|AND|OR|XOR|NAND|NOR)\b", r'<span class="up">\1</span>', s)   # operators stay upright
    return s


def L_formula(s, ctx):
    cells = []
    for c in s["cells"]:
        note = f'<span class="k">{md(c["note"])}</span>' if c.get("note") else ""
        cls = "f" + (" wide" if c.get("wide") else "") + (" words" if c.get("words") else "")
        cells.append(f'<div class="{cls}"{style(background=col(c["bg"]) if c.get("bg") else None)}>'
                     f'<small>{md(c["name"])}</small><b>{fx(c["f"])}</b>{note}</div>')
    return (f'<div class="fsw{" dense" if s.get("dense") else ""}"><div class="eyebrow">{md(s.get("eyebrow", "save this 📌"))}</div>'
            f'<h2 class="h-{s.get("size", "m")}" style="margin-top:14px">{md(s["title"])}</h2><div class="fs">{"".join(cells)}</div>{_foot(s, "fs-foot")}</div>')


def L_spot(s, ctx):
    tags = "".join(f'<span class="qtag"{style(background=col(c))}>{md(t)}</span>' for t, c in s.get("tags", []))
    reveal = s.get("reveal")
    ls = []
    for i, line in enumerate(s["lines"]):
        txt = html.escape(line) if s.get("mono") else md(line)
        if reveal and i == s.get("bad"):
            txt = f'<span class="circ red">{txt}{CIRCLE}</span>'
        ls.append(f'<div class="ln{" mono" if s.get("mono") else ""}"><i>{i + 1}</i>{txt}</div>')
    tail = (f'<div class="spot-fix">{md(s["fix"])}</div>' if reveal else
            f'<div class="qcta" style="margin-top:34px">{md(s.get("ask", "spot the mistake 👀 answer on the next slide"))}</div>')
    return (f'<div class="spotwrap"><div class="qmeta">{tags}</div><h2 class="h-{s.get("size", "m")}" style="margin-top:26px">{md(s["title"])}</h2>'
            f'<div class="spot">{"".join(ls)}</div>{tail}</div>')


def wordle_row(guess: str, ans: str) -> list[str]:
    res, pool = ["x"] * 5, list(ans)
    for i, c in enumerate(guess):
        if c == ans[i]:
            res[i] = "g"
            pool.remove(c)
    for i, c in enumerate(guess):
        if res[i] != "g" and c in pool:
            res[i] = "y"
            pool.remove(c)
    return res


def L_wordle(s, ctx):
    ans = s["answer"].upper()
    guesses = [g.upper() for g in s["guesses"]] + ([ans] if s.get("reveal") else [])
    cells = []
    for r in range(6):
        if r < len(guesses):
            cells += [f'<div class="{c}">{ch}</div>' for ch, c in zip(guesses[r], wordle_row(guesses[r], ans))]
        else:
            cells += ['<div class="e"></div>'] * 5
    return f'{_title(s)}<div class="wd">{"".join(cells)}</div>{_foot(s, "wd-foot")}'


def L_meters(s, ctx):
    cs = s.get("colours", ["lime", "sun", "tang", "coral", "bubble", "lilac", "sky", "mint"])
    rows = []
    for i, r in enumerate(s["rows"]):
        c = col(r[2] if len(r) > 2 else cs[i % len(cs)])
        rows.append(f'<div class="meter"><b>{md(r[0])}</b><div class="track"><div class="fill"{style(width=f"{max(r[1], 0)}%", background=c, border_right="0" if r[1] == 0 else None)}></div></div>'
                    f'<em>{r[1]}%</em></div>')
    sub = f'<p class="sub" style="margin-top:18px">{md(s["sub"])}</p>' if s.get("sub") else ""
    return _vc(f'{_title(s)}{sub}<div class="meters">{"".join(rows)}</div>{_foot(s, "meters-foot")}')


LAYOUTS = {k[2:]: v for k, v in globals().items() if k.startswith("L_")}


# ---------------------------------------------------------------- page
def slide_html(post: dict, i: int, s: dict, series: str) -> str:
    n = len(post["slides"])
    sid = post["id"] if n == 1 else f'{post["id"]}--{i + 1:02d}'
    ctx = {"sid": sid, "i": i, "n": n}
    bg = s.get("bg", post.get("bg", "paper"))
    size = post.get("size", "feed")
    cls = ["slide", f"bg-{bg}", size]
    if s.get("grain", bg in ("paper", "grid", "mood", "desk") or post.get("grain")):
        cls.append("grain")
    if bg in DARK_BGS or s.get("dark"):
        cls.append("on-dark")
    if s.get("margin"):
        cls.append("margin")
    extra = ""
    if bg == "mood":
        cls.append("mood-" + s.get("light", "lamp-right"))
        extra += '<div class="mood-light"></div>'
        if s.get("photo"):   # optional real photo (path relative to the repo), darkened under the text
            extra += f'<div class="mood-photo"{style(background_image=f"url({UP}{s["photo"]})")}></div>'
        extra += '<div class="vignette"></div>'
        for b in s.get("bokeh", []):
            extra += f'<div class="bokeh"{style(left=f"{b[0]}px", top=f"{b[1]}px", width=f"{b[2]}px", height=f"{b[2]}px", background=b[3] if len(b) > 3 else "rgba(255,190,110,.35)")}></div>'
    pop = col(s.get("pop", post.get("pop", "lime")))
    swap = col(s.get("swap", post.get("swap", "white")))
    popink = INKS.get(s.get("pop", post.get("pop", "lime")), "var(--ink)")
    inner = LAYOUTS[s["layout"]](s, ctx)
    flow, over = inner if isinstance(inner, tuple) else (inner, "")
    # chrome
    dark = bg in DARK_BGS or s.get("dark")
    logo_src = OWL_WHITE if dark and s.get("white_owl", True) else OWL
    logo_cls = "logo" + (" right" if s.get("logo") == "right" else "") + (" mark-only" if s.get("logo_mark_only") else "")
    chrome = "" if s.get("logo") == "none" else f'<div class="{logo_cls}"><img src="{logo_src}"><span>PrepWithTee</span></div>'
    if n > 1 and i < n - 1 and not s.get("no_swipe"):
        chrome += f'<div class="next">{NEXT}</div>' if s.get("next_pill") else f'<div class="swipe">swipe {SWIPE}</div>'
    if s.get("url", post.get("url", True)) and s["layout"] not in ("promo",):
        chrome += f'<div class="url">{SITE}</div>'
    in_style = style(inset=s["inset"]) if s.get("inset") else ""
    return (f'<section class="{" ".join(cls)}" id="{sid}"{style(__pop=pop, __swapc=swap, __popink=popink, color=col(s.get("ink")) if s.get("ink") else None)}>'
            f'{extra}<div class="in"{in_style}>{flow}</div>{over}{doodles(s.get("doodles"))}{chrome}</section>')


def page(series: str, posts: list[dict]) -> str:
    body = []
    for p in posts:
        body.append(f'<div class="post-label">{html.escape(p["id"])} · {len(p["slides"])} slide(s)</div>')
        body += [slide_html(p, i, s, series) for i, s in enumerate(p["slides"])]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{series} posts</title>'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link href="{FONTS}" rel="stylesheet">'
            f'<link rel="stylesheet" href="../assets/base.css"><link rel="stylesheet" href="../assets/formats.css"></head><body>{"".join(body)}</body></html>')


def captions(series: str, meta: dict, posts: list[dict]) -> str:
    out = [f"# {meta.get('title', series)} - captions\n", meta.get("about", ""), "",
           "Generated by build.py from posts.json - edit there, not here.\n"]
    for p in posts:
        n = len(p["slides"])
        files = f"png/{p['id']}.png" if n == 1 else f"png/{p['id']}/01.png ... {n:02d}.png"
        out += [f"## {p['id']}  ({'carousel, ' + str(n) + ' slides' if n > 1 else 'single'}{', story' if p.get('size') == 'story' else ''})",
                f"Files: `{files}`", ""]
        if p.get("note"):
            out += [f"> NOTE: {p['note']}", ""]
        out += [p.get("caption", "").strip(), ""]
        if p.get("hashtags"):
            out += [" ".join("#" + h for h in p["hashtags"]), ""]
        out.append("---\n")
    return "\n".join(out)


def gallery(series_dirs: list[Path]) -> str:
    """Contact sheet of every rendered post: series filter, search, lightbox, copy caption."""
    series, posts = [], []
    for d in series_dirs:
        meta, ps = load(d)
        series.append({"key": d.name, "title": meta.get("title", d.name), "about": meta.get("about", ""), "n": len(ps)})
        for p in ps:
            n = len(p["slides"])
            srcs = [f"{d.name}/png/{p['id']}.png"] if n == 1 else [f"{d.name}/png/{p['id']}/{i:02d}.png" for i in range(1, n + 1)]
            posts.append({"series": d.name, "id": p["id"], "slides": srcs, "story": p.get("size") == "story",
                          "caption": p.get("caption", "").strip(), "tags": " ".join("#" + h for h in p.get("hashtags", [])),
                          "note": p.get("note", "")})
    data = json.dumps({"series": series, "posts": posts}, ensure_ascii=False).replace("</", "<\\/")
    n_slides = sum(len(p["slides"]) for p in posts)
    return GALLERY_HTML.replace("__DATA__", data).replace("__STATS__", f"{len(posts)} posts · {n_slides} slides · {len(series)} series")


GALLERY_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PrepWithTee post library</title>
<style>
:root{--bg:#F4F2EC;--card:#fff;--ink:#17151F;--muted:#6B6878;--line:#E4E1D8;--accent:#4C2E72;--chip:#ECE8F6;--lime:#CBF266}
@media (prefers-color-scheme:dark){:root{--bg:#17161C;--card:#22212A;--ink:#F1EFF7;--muted:#A3A0B2;--line:#34323D;--accent:#CBB8FF;--chip:#2E2B3A}}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:16px 24px 12px}
h1{margin:0;font-size:22px;letter-spacing:-.01em}h1 small{font-weight:500;color:var(--muted);font-size:14px;margin-left:8px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
.chip{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;font:600 13px system-ui;cursor:pointer}
.chip[aria-pressed=true]{background:var(--accent);color:var(--bg);border-color:var(--accent)}
.chip span{opacity:.6;font-weight:500;margin-left:4px}
input[type=search]{flex:1;min-width:200px;max-width:340px;margin-left:auto;padding:8px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font:14px system-ui}
main{padding:20px 24px 60px}
.sec{margin:26px 0 10px}.sec h2{margin:0;font-size:18px}.sec p{margin:2px 0 0;color:var(--muted);max-width:900px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.post{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px;display:flex;flex-direction:column;gap:8px;min-width:0}
.strip{display:flex;gap:6px;overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:4px}
.strip img{height:300px;aspect-ratio:4/5;object-fit:cover;border-radius:8px;flex:none;cursor:zoom-in;scroll-snap-align:start;background:var(--line)}
.post.story .strip img{aspect-ratio:9/16}
.meta{display:flex;justify-content:space-between;align-items:center;gap:8px}
.meta b{font-size:13px;word-break:break-all}.meta em{font-style:normal;color:var(--muted);font-size:12px;white-space:nowrap}
.cap{font-size:13px;color:var(--muted);white-space:pre-line;max-height:4.4em;overflow:hidden;margin:0}
.note{font-size:12px;background:#FFF1C9;color:#5C4300;border-radius:8px;padding:6px 8px}
.acts{display:flex;gap:6px}.acts button{flex:1;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:6px;font:600 12px system-ui;cursor:pointer}
.acts button:hover{background:var(--chip)}
.empty{color:var(--muted);padding:40px 0;text-align:center}
#lb{position:fixed;inset:0;z-index:20;background:rgba(10,9,14,.92);display:none;align-items:center;justify-content:center;gap:16px;padding:20px}
#lb.on{display:flex}#lb img{max-height:92vh;max-width:min(92vw,900px);border-radius:10px}
#lb button{background:rgba(255,255,255,.12);color:#fff;border:0;border-radius:999px;width:48px;height:48px;font-size:22px;cursor:pointer;flex:none}
#lb .x{position:absolute;top:16px;right:16px}#lb .ct{position:absolute;bottom:14px;left:0;right:0;text-align:center;color:#ddd;font-size:13px}
.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 14px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .2s}
.toast.on{opacity:1}
@media (max-width:600px){header,main{padding-left:16px;padding-right:16px}.grid{grid-template-columns:1fr}.strip img{height:260px}}
</style></head><body>
<header><h1>PrepWithTee post library<small>__STATS__</small></h1>
<div class="bar" id="chips"></div></header>
<main id="main"></main>
<div id="lb" role="dialog" aria-modal="true"><button class="x" aria-label="Close">✕</button><button class="pv" aria-label="Previous">‹</button><img alt=""><button class="nx" aria-label="Next">›</button><div class="ct"></div></div>
<div class="toast" id="toast"></div>
<script>
const DATA = __DATA__;
let active = "all", q = "";
const chips = document.getElementById("chips"), main = document.getElementById("main");
function chip(key, label, n){const b=document.createElement("button");b.className="chip";b.dataset.k=key;b.innerHTML=label+`<span>${n}</span>`;
  b.onclick=()=>{active=key;render()};chips.appendChild(b)}
chip("all","All",DATA.posts.length); DATA.series.forEach(s=>chip(s.key,s.title,s.n));
const search=document.createElement("input");search.type="search";search.placeholder="Search ids and captions…";
search.oninput=()=>{q=search.value.toLowerCase();render()};chips.appendChild(search);
function esc(t){return t.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function render(){
  chips.querySelectorAll(".chip").forEach(c=>c.setAttribute("aria-pressed",c.dataset.k===active));
  main.innerHTML="";let shown=0;
  DATA.series.forEach(s=>{
    if(active!=="all"&&active!==s.key)return;
    const ps=DATA.posts.filter(p=>p.series===s.key&&(!q||(p.id+" "+p.caption+" "+p.tags).toLowerCase().includes(q)));
    if(!ps.length)return;shown+=ps.length;
    const sec=document.createElement("section");sec.innerHTML=`<div class="sec"><h2>${esc(s.title)} <small style="color:var(--muted);font-weight:500">${s.key}/</small></h2><p>${esc(s.about)}</p></div>`;
    const g=document.createElement("div");g.className="grid";
    ps.forEach(p=>{const el=document.createElement("article");el.className="post"+(p.story?" story":"");
      el.innerHTML=`<div class="strip">${p.slides.map((src,i)=>`<img loading="lazy" src="${src}" data-i="${i}" alt="${esc(p.id)} slide ${i+1}">`).join("")}</div>
        <div class="meta"><b>${esc(p.id)}</b><em>${p.slides.length>1?p.slides.length+" slides":p.story?"story":"single"}</em></div>
        ${p.note?`<div class="note">⚠ ${esc(p.note)}</div>`:""}<p class="cap">${esc(p.caption)}</p>
        <div class="acts"><button data-a="copy">Copy caption</button><button data-a="open">Open PNGs</button></div>`;
      el.querySelectorAll("img").forEach(img=>img.onclick=()=>openLb(p,+img.dataset.i));
      el.querySelector('[data-a=copy]').onclick=()=>copy(p.caption+(p.tags?"\n\n"+p.tags:""));
      el.querySelector('[data-a=open]').onclick=()=>p.slides.forEach(s=>window.open(s,"_blank"));
      g.appendChild(el)});
    sec.appendChild(g);main.appendChild(sec)});
  if(!shown)main.innerHTML='<p class="empty">No posts match.</p>';
}
const lb=document.getElementById("lb"),lbImg=lb.querySelector("img"),lbCt=lb.querySelector(".ct");let cur=null,ix=0;
function openLb(p,i){cur=p;ix=i;show();lb.classList.add("on")}
function show(){lbImg.src=cur.slides[ix];lbCt.textContent=`${cur.id} · ${ix+1} / ${cur.slides.length}`}
function step(d){if(!cur)return;ix=(ix+d+cur.slides.length)%cur.slides.length;show()}
lb.querySelector(".x").onclick=()=>lb.classList.remove("on");lb.querySelector(".pv").onclick=()=>step(-1);lb.querySelector(".nx").onclick=()=>step(1);
lb.onclick=e=>{if(e.target===lb)lb.classList.remove("on")};
document.addEventListener("keydown",e=>{if(!lb.classList.contains("on"))return;if(e.key==="Escape")lb.classList.remove("on");if(e.key==="ArrowLeft")step(-1);if(e.key==="ArrowRight")step(1)});
function copy(t){(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>toast("Caption copied"),()=>{const a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();try{document.execCommand("copy");toast("Caption copied")}catch(e){toast("Copy failed")}a.remove()})}
function toast(t){const el=document.getElementById("toast");el.textContent=t;el.classList.add("on");setTimeout(()=>el.classList.remove("on"),1400)}
render();
</script></body></html>"""


def load(d: Path):
    data = json.loads((d / "posts.json").read_text(encoding="utf-8"))
    for p in data["posts"]:   # "inherit": true = copy the previous slide, then apply this one's keys
        out = []
        for sl in p["slides"]:
            if sl.get("inherit") and out:
                sl = {**out[-1], **{k: v for k, v in sl.items() if k != "inherit"}}
            out.append(sl)
        p["slides"] = out
    return data.get("series", {}), data["posts"]


# ---------------------------------------------------------------- render
def render(d: Path, posts: list[dict], only: str, scale: float) -> None:
    from playwright.sync_api import sync_playwright
    out = d / "png"
    out.mkdir(exist_ok=True)
    failed = []
    with sync_playwright() as pw:
        exe = os.environ.get("PW_CHROMIUM")   # a preinstalled Chromium when the bundled one is missing
        browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 1200, "height": 2000}, device_scale_factor=scale)
        pg.goto((d / "preview.html").as_uri(), wait_until="networkidle")
        missing = pg.evaluate("""async () => { const bad = [];
            for (const f of ['Bricolage Grotesque', 'Inter', 'Caveat', 'Noto Color Emoji', 'Space Mono', 'STIX Two Text']) {
              const got = await document.fonts.load(`700 40px "${f}"`, 'Aa 😀');
              if (!got.length) bad.push(f); }
            await document.fonts.ready; return bad; }""")
        if missing:
            raise SystemExit(f"fonts did not load: {missing}")
        pg.wait_for_timeout(300)
        for p in posts:
            if only and only not in p["id"]:
                continue
            n = len(p["slides"])
            for i in range(n):
                sid = p["id"] if n == 1 else f'{p["id"]}--{i + 1:02d}'
                sec = pg.query_selector(f'section[id="{sid}"]')
                over = sec.evaluate("""s => { const i = s.querySelector('.in').getBoundingClientRect();
                    return [...s.querySelectorAll('.in *')].some(e => { const r = e.getBoundingClientRect();
                      return r.width && (r.bottom > i.bottom + 2 || r.right > i.right + 2); }); }""")
                if n == 1:
                    path = out / f"{p['id']}.png"
                else:
                    (out / p["id"]).mkdir(exist_ok=True)
                    path = out / p["id"] / f"{i + 1:02d}.png"
                try:
                    path.write_bytes(sec.screenshot())
                except OSError as e:   # Windows: the old PNG is open in a viewer / preview pane
                    failed.append(path)
                    print(f"  {path.relative_to(HERE)}   <-- NOT SAVED ({e.strerror}: close any app showing it)")
                    continue
                print(f"  {path.relative_to(HERE)}{'   <-- OVERFLOW' if over else ''}")
        browser.close()
    if failed:
        print(f"  {len(failed)} file(s) not saved - close them, then re-run with --series {d.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="", help="only this series folder")
    ap.add_argument("--only", default="", help="only posts whose id contains this text")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()
    dirs = sorted(p.parent for p in HERE.glob("*/posts.json"))
    for d in dirs:
        if args.series and d.name != args.series:
            continue
        meta, posts = load(d)
        (d / "preview.html").write_text(page(d.name, posts), encoding="utf-8")
        (d / "CAPTIONS.md").write_text(captions(d.name, meta, posts), encoding="utf-8")
        print(f"{d.name}: {len(posts)} posts, {sum(len(p['slides']) for p in posts)} slides")
        if not args.html_only:
            render(d, posts, args.only, args.scale)
    (HERE / "gallery.html").write_text(gallery(dirs), encoding="utf-8")


if __name__ == "__main__":
    main()
