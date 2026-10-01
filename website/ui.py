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
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
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
        f'<a class="ui-stab{" is-on" if k == active else ""}" data-sec="{k}" href="{_e(url)}"'
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


# ── Board + subject picker ───────────────────────────────────────────────────
# ONE picker for every section (topical, mock tests, yearly, MCQ, notes,
# resources) so a student learns it once: board tabs + search on top, each
# board a coloured band, and every subject an equal-sized tile with the same
# parts in the same places - icon + status flag, name, code, a stats row, and
# at most two buttons. (Tutor, 2026-09-27: the old grids felt "scrambled".)

BOARD_THEME = {                  # board -> (monogram, long name)
    "o-level": ("O", "Cambridge O Level"),
    "igcse": ("IG", "Cambridge IGCSE"),
    "a-level": ("A", "Cambridge International A Level"),
}

# Subject glyphs by family (the tone catalog._FAMILY gives each family).
_SUBJECT_ICONS = {
    "lav": '<path d="M5 6h14M9 6v12M15 6v9a3 3 0 003 3"/>',                              # maths: pi
    "green": ('<circle cx="12" cy="12" r="1.6"/><ellipse cx="12" cy="12" rx="9" ry="3.6"/>'
              '<ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)"/>'
              '<ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(120 12 12)"/>'),  # physics: atom
    "orange": ('<path d="M9 3h6M10 3v6l-5.5 9.5A1.7 1.7 0 006 21h12a1.7 1.7 0 001.5-2.5L14 9V3"/>'
               '<path d="M7.5 15h9"/>'),                                                 # chemistry: flask
    "pink": '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',                        # computing: </>
    "teal": ('<path d="M15.5 4.5a8 8 0 100 15 6.5 6.5 0 010-15z"/>'
             '<path d="M17.5 9.5l.6 1.4 1.5.1-1.1 1 .3 1.5-1.3-.8-1.3.8.3-1.5-1.1-1 1.5-.1z"/>'),  # islamiyat
    "yellow": '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',                                     # pakistan studies
    "blue": '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z"/>',
}


def subject_icon(tone: str, cls: str = "pk-glyph") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'{_SUBJECT_ICONS.get(tone, _SUBJECT_ICONS["blue"])}</svg>')


_FLAGS = {"on": "Enrolled", "lock": "Not enrolled", "soon": "Coming soon"}


def tile(*, code: str, url: str, stats: list[tuple[str, str]], flag: str = "",
         actions: list[tuple] = (), soon: bool = False, years: str = "",
         more: list[tuple[str, str]] = ()) -> str:
    """One subject tile. stats = [(value, label)] (max 2 - they must never
    truncate); years = "2010–2025" shown beside the code; flag = on|lock|soon|"";
    actions = [(label, href or None, kind "primary"|"ghost"|"gold", extra attrs)] (max 2).
    more = [(label, href)]: a slim "Also" row of the subject's other sections, so
    nothing that used to be one click away (MCQ, notes) is lost to the 2-button cap.
    The name is a stretched link, so the whole tile opens `url`."""
    import catalog
    s = catalog.SUBJECTS[code]
    board = catalog.BOARD_SHORT[s["board_slug"]]
    st = "".join(f'<div><dt>{_e(k)}</dt><dd>{_e(v)}</dd></div>' for v, k in stats[:2])
    acts = []
    for a in list(actions)[:2]:
        label, href, kind, attrs = (list(a) + ["", ""])[:4]
        cls = f'pk-btn pk-btn-{kind or "primary"}'
        if href:
            acts.append(f'<a class="{cls}" href="{_e(href)}" {attrs}>{_e(label)}</a>')
        else:
            acts.append(f'<button class="{cls}" type="button" {attrs}>{_e(label)}</button>')
    mark = icon("check") if flag == "on" else icon("lock") if flag == "lock" else ""
    flag_html = f'<span class="pk-flag pk-flag-{flag}">{mark}{_FLAGS.get(flag, flag)}</span>' if flag else ""
    q = f'{s["plain"]} {s["name"]} {code} {board}'.lower()
    cls = "pk-tile cat-tone-" + s["tone"] + (" is-mine" if flag == "on" else "") + (" is-soon" if soon else "")
    return (f'<article class="{cls}" data-q="{_e(q)}">'
            f'<div class="pk-top"><span class="pk-ic">{subject_icon(s["tone"])}</span>{flag_html}</div>'
            f'<h3><a class="pk-link" href="{_e(url)}">{_e(s["plain"])}</a></h3>'
            f'<p class="pk-sub"><span class="pk-code">{code}</span>{_e(board)}'
            + (f'<span class="pk-years">{_e(years)}</span>' if years else "") + '</p>'
            + (f'<dl class="pk-stats">{st}</dl>' if st else "")
            + (f'<nav class="pk-more" aria-label="More for {_e(s["plain"])} {code}"><span>Also</span>'
               + "".join(f'<a href="{_e(h)}">{_e(lab)}</a>' for lab, h in more) + '</nav>' if more else "")
            + (f'<div class="pk-acts">{"".join(acts)}</div>' if acts else "")
            + '</article>')


def picker(tiles_by_board: dict[str, list[str]], *, state: dict | None = None,
           board_links: str | None = None, active: str = "", anchor: str = "boards",
           subtitle=None, search: bool = True, empty: str = "") -> str:
    """Board tabs + search + one coloured band of tiles per board.

    tiles_by_board: {board_slug: [tile html]} in display order (empty boards skipped).
    board_links: when set (e.g. "/yearly/{board}"), the tabs are links to the
      per-board pages (and `active` marks the current one); otherwise the tabs
      filter the bands in place (picker.js) and "All boards" shows every one.
    subtitle: fn(board, n_tiles) -> html under each board's name."""
    import catalog
    boards = [b for b, t in tiles_by_board.items() if t]
    if not boards:
        return empty
    mine = set((state or {}).get("boards") or [])
    yours = '<em>yours</em>'
    tabs = []
    if board_links:
        for b in board_order(state):
            on = b == active
            cur = ' aria-current="page"' if on else ""
            tabs.append(f'<a class="pk-tab pk-b-{b}{" is-on" if on else ""}" href="{_e(board_links.format(board=b))}"'
                        f'{cur}><i></i>{catalog.BOARD_SHORT[b]}{yours if b in mine else ""}</a>')
    else:
        total = sum(len(tiles_by_board[b]) for b in boards)
        tabs.append('<button class="pk-tab is-on" type="button" data-pk-board="" aria-pressed="true">'
                    f'All boards <b>{total}</b></button>')
        for b in boards:
            tabs.append(f'<button class="pk-tab pk-b-{b}" type="button" data-pk-board="{b}" aria-pressed="false">'
                        f'<i></i>{catalog.BOARD_SHORT[b]} <b>{len(tiles_by_board[b])}</b>'
                        f'{yours if b in mine else ""}</button>')
    srch = ""
    if search:
        srch = (f'<label class="pk-search">{icon("search")}<span class="sr-only">Search subjects</span>'
                '<input type="search" data-pk-q placeholder="Search a subject or code, e.g. Physics or 5054" '
                'autocomplete="off"><kbd>/</kbd></label>')
    bands = []
    for b in boards:
        mono, long = BOARD_THEME[b]
        n = len(tiles_by_board[b])
        sub = subtitle(b, n) if subtitle else f"{n} subject{'s' if n != 1 else ''}"
        badge = '<span class="pk-yours">Your board</span>' if b in mine else ""
        bands.append(f'<section class="pk-board pk-b-{b}" data-pk-board="{b}" id="{b}">'
                     f'<header class="pk-bhead"><span class="pk-bmark">{mono}</span>'
                     f'<div><h2>{_e(long)}</h2><p>{sub}</p></div>{badge}</header>'
                     f'<div class="pk-grid">{"".join(tiles_by_board[b])}</div></section>')
    return (f'<div class="pk" id="{_e(anchor)}" data-pk>'
            f'<div class="pk-bar"><nav class="pk-tabs" aria-label="Boards">{"".join(tabs)}</nav>{srch}</div>'
            + "".join(bands)
            + '<p class="pk-none" hidden>No subject matches <b data-pk-echo></b>. '
              'Try the subject name or its 4-digit code.</p></div>')


def dash_tabs(current: str) -> str:
    """The dashboard section tabs (sync_nav.DASH_TABS) for a server-rendered
    page, e.g. /my-papers - the static pages get them stamped by sync_nav.py."""
    import sync_nav
    return sync_nav.dash_tabs_html(current).replace('class="dtabs"', 'class="dtabs dtabs-inline"', 1)


TOOLS_V = "20260930c"          # = VERSION in static/tools-core.js


def tools_dock(syllabus: str | None) -> tuple[str, str]:
    """The Tools tab (calculator, periodic table, formulas...) for a paper
    viewer: (<body> attributes, <script> tags). The dock picks the tools that
    subject's exam needs and moves the paper over on a wide screen."""
    attrs = f' data-syllabus="{_e(syllabus or "")}" data-dock="push"'
    scripts = (f'<script src="/tools-core.js?v={TOOLS_V}"></script>'
               f'<script src="/tools-dock.js?v={TOOLS_V}"></script>')
    return attrs, scripts


def page_search(placeholder: str, items: str, groups: str = "section, .nt-group",
                 deep: list[dict] | None = None, scope: str = "this page") -> str:
    """A filter box for long pages (a subject's chapters, a resources folder):
    hides every `items` element whose data-q (or text) misses a typed word, and
    any `groups` container left empty. Behaviour: catalog.js ([data-ps]).

    deep = every folder and file BELOW the current one (see deep_entry): while
    something is typed, the page's own listing is swapped for a flat list of
    matches from the whole subtree, each with the path it sits at - never
    anything outside the current folder (tutor, 2026-09-30). Wrap the normal
    listing in <div data-ps-browse> on those pages."""
    results = ""
    if deep is not None:
        rows = []
        for d in deep:
            where = f'<small>{_e(" › ".join(d["path"]))}</small>' if d["path"] else ""
            rows.append(
                f'<li data-q="{_e(d["q"])}" data-t="{_e(d["title"])}">'
                f'<a href="{_e(d["href"])}"{" download" if d.get("download") else ""}>'
                f'<i class="ps-kind ps-kind-{_e(d["kind"].lower())}" aria-hidden="true">{_e(d["kind"])}</i>'
                f'<span class="ps-hit"><b>{_e(d["title"])}</b>{where}</span></a></li>')
        rows = "".join(rows)
        results = (f'<section class="ps-results" data-ps-results hidden>'
                   f'<ol class="ps-list">{rows}</ol>'
                   f'<p class="ps-empty" hidden>Nothing called that in {_e(scope)} or the folders inside it.</p>'
                   f'</section>')
    return (f'<div class="ps" data-ps data-ps-items="{_e(items)}" data-ps-groups="{_e(groups)}"'
            f'{" data-ps-deep" if deep is not None else ""}>'
            f'<label class="pk-search ps-box">{icon("search")}<span class="sr-only">Search {_e(scope)}</span>'
            f'<input type="search" data-ps-q placeholder="{_e(placeholder)}" autocomplete="off" '
            f'spellcheck="false" enterkeyhint="search"></label>'
            f'<span class="ps-count" data-ps-count aria-live="polite"></span></div>{results}')


def deep_entry(title: str, href: str, kind: str, path: list[str], extra: str = "",
               download: bool = False) -> dict:
    """One row for page_search(deep=...). `path` = the folders between the
    current page and the item (shown under the title, and searchable)."""
    return {"title": title, "href": href, "kind": kind, "path": path, "download": download,
            "q": " ".join([title, *path, extra]).lower()}


def board_order(state: dict | None) -> list[str]:
    """The student's boards first, then the rest."""
    import catalog
    mine = list((state or {}).get("boards") or [])
    return mine + [b for b in catalog.BOARD_SHORT if b not in mine]


def codes_for(board: str, state: dict | None = None) -> list[str]:
    """A board's subjects, enrolled ones first (stable otherwise)."""
    import catalog
    enrolled = (state or {}).get("enrolled") or set()
    codes = [c for c, s in catalog.SUBJECTS.items() if s["board_slug"] == board]
    return sorted(codes, key=lambda c: c not in enrolled)
