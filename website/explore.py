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


@router.get("/explore", response_class=HTMLResponse)
def explore(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    state = _catalog._student_state(user)
    groups = []
    for head, ic, items in SECTIONS:
        lis = "".join(
            f'<li><a href="{_e(url)}"><b>{_e(label)}</b><span>{_e(what)}</span>'
            + ('<i class="ui-acct" title="Needs a free account">Account</i>' if acct and not user else "")
            + "</a></li>" for label, url, what, acct in items)
        groups.append(f'<section class="ex-group"><h2>{ui.icon(ic)}{_e(head)}</h2><ul>{lis}</ul></section>')
    rows = []
    for board, subs in _catalog.BOARDS:
        b = _catalog.BOARD_SLUGS[board]
        trs = "".join(
            f'<tr><th scope="row"><span class="cat-code">{c}</span> {_e(_catalog.SUBJECTS[c]["plain"])}</th><td>'
            + " ".join(f'<a href="{_e(url)}">{_e(label)}</a>' for _k, label, url, _i in ui.subject_links(c))
            + "</td></tr>" for c, _n in subs)
        rows.append(f'<h3 class="cat-group">{_catalog.BOARD_SHORT[b]}</h3>'
                    f'<table class="ex-subjects"><tbody>{trs}</tbody></table>')
    body = f"""
    <header class="cat-hero cat-hero-sm">
      <p class="cat-eyebrow">Explore</p>
      <h1>Everything on PrepWithTee</h1>
      <p class="cat-lede">Every page, with one line on what it is for. Pages marked <i class="ui-acct">Account</i>
        need a free account.</p>
    </header>
    <div class="ex-groups">{''.join(groups)}</div>
    <section><h2 class="ui-h2">Every subject, every section</h2>{''.join(rows)}</section>"""
    return _catalog._respond(_catalog._shell(
        title="Explore PrepWithTee - Every Page and Subject", path="/explore", body=body, state=state,
        desc="Every PrepWithTee page in one place: past papers by topic and year, MCQ practice, mock tests, "
             "revision notes, teachers' resources, AI help and study tools.",
        crumbs=[("Home", "/"), ("Explore", "/explore")]), bool(user))
