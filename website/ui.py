"""Shared building blocks for the server-rendered section pages.

Every section (past papers, yearly, MCQ, mock tests, notes, resources) is its
own page, but a student moves between them per SUBJECT - "Physics 5054:
topical -> by year -> notes". So each subject-level page carries the same
subject tabs (subject_tabs), a back link to its parent (back_link), and the
hubs share the guide blocks (steps, mode cards, FAQ with FAQPage JSON-LD).

Nothing here imports the section modules at import time (they import this),
so the URL helpers are looked up lazily.
"""

import html as _html
import json

_e = lambda s: _html.escape(str(s), quote=True)        # noqa: E731


# ── Icons (inline SVG, currentColor) ─────────────────────────────────────────
_ICONS = {
    "topical": '<path d="M4 5h16M4 10h10M4 15h16M4 20h8"/>',
    "yearly": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "mcq": '<circle cx="6.5" cy="7" r="2"/><circle cx="6.5" cy="17" r="2"/><path d="M11 7h9M11 17h9"/><path d="M5.6 7l.8.8 1.5-1.6"/>',
    "test": '<path d="M9 3h6l1 3H8z"/><rect x="5" y="5.5" width="14" height="15.5" rx="2"/><path d="M9 12l2 2 4-4"/>',
    "notes": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
    "resources": '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
    "progress": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "history": '<path d="M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.8L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
    "tools": '<path d="M14.7 6.3a4 4 0 015 5L11 20l-5 1 1-5z"/>',
    "ai": '<path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z"/>',
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "download": '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    "book": '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z"/><path d="M4 19V5M19 17v4H6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
    "map": '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
}


def icon(name: str, cls: str = "ui-ic") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICONS.get(name, "")}</svg>')


# ── Navigation ───────────────────────────────────────────────────────────────

def back_link(href: str, label: str) -> str:
    """'← Back to X' - the explicit way up, next to the breadcrumbs."""
    return f'<a class="ui-back" href="{_e(href)}">{icon("back")}<span>{_e(label)}</span></a>'


def subject_links(code: str) -> list[tuple[str, str, str, str]]:
    """[(key, label, url, icon)] for every section this subject has."""
    import catalog, notes, resources, yearly            # the section modules import this one
    out = [("topical", "Topical", catalog.subject_url(code), "topical")]
    if yearly.subject_years(code):
        out.append(("yearly", "By year", yearly.yearly_url(code), "yearly"))
    if code in yearly.mcq_codes():
        out.append(("mcq", "MCQ", yearly.mcq_url(code), "mcq"))
    out.append(("test", "Mock test", f"{catalog.subject_url(code)}?mode=test#builder", "test"))
    out.append(("notes", "Notes", notes.notes_url(code), "notes"))
    if resources.has_subject(code):
        out.append(("resources", "Resources", resources.subject_url(code), "resources"))
    return out


def subject_tabs(code: str, active: str) -> str:
    """The row of section tabs shown on every subject-level page."""
    import catalog
    s = catalog.SUBJECTS[code]
    cur = ' aria-current="page"'
    tabs = "".join(
        f'<a class="ui-stab{" is-on" if k == active else ""}" href="{_e(url)}"'
        f'{cur if k == active else ""}>{icon(ic)}<span>{_e(label)}</span></a>'
        for k, label, url, ic in subject_links(code))
    return (f'<nav class="ui-stabs cat-tone-{s["tone"]}" aria-label="{_e(s["plain"])} {code} sections">'
            f'<span class="ui-stabs-name"><b>{_e(s["plain"])}</b> {code}</span>{tabs}</nav>')


# ── Guide blocks ─────────────────────────────────────────────────────────────

def steps(items: list[tuple[str, str]], title: str = "", cls: str = "") -> str:
    """Numbered how-to steps: [(heading, text)]."""
    lis = "".join(f'<li><b>{_e(h)}</b><span>{t}</span></li>' for h, t in items)
    head = f'<h2 class="ui-h2">{_e(title)}</h2>' if title else ""
    return f'<section class="ui-steps-wrap {cls}">{head}<ol class="ui-steps">{lis}</ol></section>'


def mode_card(*, key: str, title: str, url: str, blurb: str, best: str, cta: str,
              tone: str = "lav", meta: str = "", icon_name: str | None = None) -> str:
    return f"""
      <a class="ui-mode cat-tone-{tone}" href="{_e(url)}" data-mode="{key}">
        <span class="ui-mode-ic">{icon(icon_name or key)}</span>
        <span class="ui-mode-body">
          <b class="ui-mode-title">{_e(title)}</b>
          <span class="ui-mode-blurb">{blurb}</span>
          <span class="ui-mode-best"><i>Best for</i> {best}</span>
          {f'<span class="ui-mode-meta">{meta}</span>' if meta else ''}
        </span>
        <span class="ui-mode-cta">{_e(cta)} {icon("arrow")}</span>
      </a>"""


def faq(items: list[tuple[str, str]], title: str = "Questions students ask") -> tuple[str, dict]:
    """(html, FAQPage JSON-LD). Answers may contain simple inline HTML."""
    import re
    body = "".join(f'<details class="ui-faq-item"><summary>{_e(q)}</summary><div>{a}</div></details>'
                   for q, a in items)
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q,
                          "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}}
                         for q, a in items]}
    return f'<section class="ui-faq"><h2 class="ui-h2">{_e(title)}</h2>{body}</section>', ld


def callout(text: str, tone: str = "gold", icon_name: str = "ai") -> str:
    return f'<aside class="ui-callout ui-callout-{tone}">{icon(icon_name)}<div>{text}</div></aside>'


def json_ld(block: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(block, ensure_ascii=False)}</script>'
