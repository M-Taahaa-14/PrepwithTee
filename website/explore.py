"""/explore - every page on the site, grouped, plus every subject's sections.

A human site map: a student who cannot find something lands here from the
footer ("All pages") and sees each page with one line on what it is for.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

import auth as _auth
import catalog as _catalog

router = APIRouter()
_e = _catalog._e

# (heading, icon, [(label, url, what it is for, needs_account)])
SECTIONS = [
    ("Practise past papers", "topical", [
        ("Past papers hub", "/papers", "Every way to practise, and which to use when", False),
        ("Topical papers", "/papers/topical", "Pick chapters, get a booklet with the mark scheme", False),
        ("Papers by year", "/yearly", "Every sitting: question paper, mark scheme, insert", False),
        ("MCQ practice", "/mcq", "Multiple choice, marked instantly", False),
        ("Mock tests", "/papers/mock-tests", "Timed tests, mark scheme unlocks at the end", False),
        ("My papers", "/my-papers", "Everything you have built, with your annotations", True),
        ("Topical progress", "/topical-progress.html", "How far through each chapter you are", True),
        ("Yearly progress", "/yearly-progress.html", "Scores and grades on full papers", True),
    ]),
    ("Learn", "notes", [
        ("Revision notes", "/notes", "PrepWithTee's own notes, chapter by chapter", False),
        ("Resources", "/resources", "Teachers' PDF notes, books, worksheets, syllabuses", False),
        ("Formula sheets", "/formulas.html", "Every exam formula", False),
        ("Definitions", "/definitions.html", "Key terms and their exact meanings", False),
        ("Command words", "/command-words.html", "What State, Describe, Explain... want", False),
        ("Graph guide", "/graphs-guide.html", "Graph shapes and sketching", False),
        ("Islamiyat references", "/islamiat-references.html", "Verses, Hadith and battles", False),
        ("Flashcards", "/flashcards.html", "Spaced repetition decks", True),
        ("Study session", "/study.html", "Review what is due today", True),
        ("My notes", "/notes.html", "Your own jottings and stickies", True),
    ]),
    ("AI help", "ai", [
        ("AI Tutor", "/tutor.html", "Ask about any concept, step by step", True),
        ("Photo Solver", "/solver", "Photograph a question - solve it or check your working", True),
    ]),
    ("Tools", "tools", [
        ("All tools", "/tools.html", "Everything below in one place", False),
        ("Whiteboard", "/whiteboard", "Notebooks and an infinite canvas: pens, compass, stickers, PDF export", False),
        ("Calculator", "/calculator.html", "Scientific calculator with memory", False),
        ("Graph plotter", "/graph.html", "Plot any function or relation", False),
        ("Grade calculator", "/grade-calculator.html", "Predict your grade from paper marks", False),
        ("Grade trends", "/grade-trends.html", "Grade threshold history", False),
        ("Number bases & logic", "/bases-logic.html", "Binary, hex and truth tables", False),
        ("Pseudocode runner", "/pseudocode.html", "Write and run Cambridge pseudocode", False),
        ("Periodic table", "/periodic-table.html", "Cambridge data values", False),
    ]),
    ("Your account", "user", [
        ("Dashboard", "/dashboard.html", "Your overview", True),
        ("Study hub", "/study-hub.html", "All learning tools", True),
        ("Calendar", "/calendar.html", "Planner and tasks", True),
        ("Analytics", "/analytics.html", "Stats, XP and streaks", True),
        ("Achievements", "/achievements.html", "Badges you have earned", True),
        ("Homework", "/homework.html", "Assignments from your teacher", True),
        ("Messages", "/messages.html", "Talk to your teacher", True),
        ("Profile", "/profile.html", "Settings and subjects", True),
    ]),
    ("About PrepWithTee", "map", [
        ("Subjects", "/subjects.html", "Every course we cover", False),
        ("Pricing", "/pricing.html", "Plans and what they include", False),
        ("Our teachers", "/teachers.html", "Meet the tutors", False),
        ("Teach with us", "/teacher-apply.html", "Join the team", False),
        ("Blog", "/blog", "Study tips and exam advice", False),
        ("Guide", "/guide.html", "How to use the site", False),
        ("Contact", "/contact.html", "Get in touch", False),
        ("Terms", "/terms.html", "Terms of use", False),
        ("Privacy", "/privacy.html", "Privacy policy", False),
    ]),
]


_GROUP_TONES = {"Practise past papers": "lav", "Learn": "green", "AI help": "pink", "Tools": "orange",
                "Your account": "blue", "About PrepWithTee": "teal"}

# The four doors most students want first.
_START = [
    ("ai", "What can I do here?", "/features", "Every feature, with the tip that makes it useful", "orange"),
    ("topical", "Topical past papers", "/papers/topical", "Pick chapters, get real questions + mark scheme", "lav"),
    ("yearly", "Papers by year", "/yearly", "Every sitting, no account needed", "blue"),
    ("notes", "Revision notes", "/notes", "Chapter-by-chapter, linked to questions", "green"),
    ("ai", "AI Tutor & Photo Solver", "/tutor.html", "Stuck? Ask, or snap a photo of the question", "pink"),
]


@router.get("/explore", response_class=HTMLResponse)
def explore(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    state = _catalog._student_state(user)
    n_pages = sum(len(items) for _h, _i, items in SECTIONS)
    n_ch = sum(len(_catalog.chapters(c)) for c in _catalog.SUBJECTS)
    n_q = sum(_catalog.subject_stats(c)["questions"] for c in _catalog.SUBJECTS)
    start = "".join(
        f'<a class="ex-start cat-tone-{tone}" href="{_e(url)}"><span class="ex-start-ic">{ui.icon(ic)}</span>'
        f'<b>{_e(t)}</b><span>{_e(d)}</span><i>{ui.icon("arrow")}</i></a>'
        for ic, t, url, d, tone in _START)
    groups = []
    for head, ic, items in SECTIONS:
        tone = _GROUP_TONES.get(head, "lav")
        lis = "".join(
            f'<li data-q="{_e((label + " " + what + " " + head).lower())}"><a href="{_e(url)}"><b>{_e(label)}</b><span>{_e(what)}</span>'
            + ('<i class="ui-acct" title="Needs a free account">Account</i>' if acct and not user else "")
            + "</a></li>" for label, url, what, acct in items)
        groups.append(f'<section class="ex-group cat-tone-{tone}"><h2><span class="ex-gic">{ui.icon(ic)}</span>'
                      f'{_e(head)}<small>{len(items)}</small></h2><ul>{lis}</ul></section>')
    bands = []
    for board, subs in _catalog.BOARDS:
        b = _catalog.BOARD_SLUGS[board]
        mono, long = ui.BOARD_THEME[b]
        cards = []
        for c, _n in subs:
            s = _catalog.SUBJECTS[c]
            links = "".join(f'<a class="sec-{k}" href="{_e(url)}">{ui.icon(ic)}{_e(label)}</a>'
                            for k, label, url, ic in ui.subject_links(c))
            cards.append(f'<article class="ex-subj cat-tone-{s["tone"]}" data-q="{_e((s["name"] + " " + c + " " + long).lower())}">'
                         f'<header><span class="pk-ic">{ui.subject_icon(s["tone"])}</span>'
                         f'<div><b>{_e(s["plain"])}</b><small><span class="pk-code">{c}</span></small></div></header>'
                         f'<nav>{links}</nav></article>')
        bands.append(f'<section class="pk-board pk-b-{b}"><header class="pk-bhead"><span class="pk-bmark">{mono}</span>'
                     f'<div><h2>{_e(long)}</h2><p>{len(subs)} subjects</p></div></header>'
                     f'<div class="ex-subjs">{"".join(cards)}</div></section>')
    body = f"""
    <header class="cat-hero cat-hero-sm ex-hero">
      <p class="cat-eyebrow">Explore</p>
      <h1>Everything on PrepWithTee, in one place</h1>
      <p class="cat-lede">Every page with one line on what it is for, and every subject's sections side by side.
        Pages marked <i class="ui-acct">Account</i> need a free account.</p>
      <button class="ex-bigsearch" type="button" data-site-search>{ui.icon("search")}
        <span>Search subjects, chapters, notes and tools…</span><kbd>Ctrl K</kbd></button>
      <dl class="ui-hero-stats ex-stats">
        <div class="cat-tone-lav"><dt>Pages</dt><dd>{n_pages}</dd></div>
        <div class="cat-tone-blue"><dt>Subjects</dt><dd>{len(_catalog.SUBJECTS)}</dd></div>
        <div class="cat-tone-green"><dt>Chapters</dt><dd>{n_ch}</dd></div>
        <div class="cat-tone-orange"><dt>Questions</dt><dd>{n_q:,}</dd></div>
      </dl>
    </header>
    <section><h2 class="ui-h2">Start here</h2><div class="ex-starts">{start}</div></section>
    {ui.page_search("Filter this page, e.g. calculator, flashcards, physics", ".ex-group li, .ex-subj", ".ex-group, .pk-board")}
    <div class="ex-groups">{''.join(groups)}</div>
    <section class="ex-map"><h2 class="ui-h2">Every subject, every section</h2>{''.join(bands)}</section>"""
    return _catalog._respond(_catalog._shell(
        title="Explore PrepWithTee - Every Page and Subject", path="/explore", body=body, state=state,
        desc="Every PrepWithTee page in one place: past papers by topic and year, MCQ practice, mock tests, "
             "revision notes, teachers' resources, AI help and study tools.",
        crumbs=[("Home", "/"), ("Explore", "/explore")]), bool(user))
