"""/features - everything a student can do on PrepWithTee, with how to find it.

Most students only ever use topical past papers (tutor, 2026-10-05); this page
is where the rest is introduced: what each feature is for, the one tip that
makes it useful, and a link straight to it. What's new sits at the top, and
static/whats-new.js points signed-in students here once per announcement.
FEATURES is also the source for that spotlight's wording - keep NEW in step
with whats-new.js ANNOUNCEMENTS.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

import auth as _auth
import catalog as _catalog

router = APIRouter()
_e = _catalog._e

# (emoji, title, what it is, the tip, url, cta, tone)
NEW = [
    ("🖊️", "PrepWithTee Board - your own whiteboard",
     "Notebooks (lined, squared, graph, dotted, Cornell) or an infinite canvas, saved to your account.",
     "Open a question in a topical paper and press <b>🖊️ Whiteboard</b> - it lands on a fresh board ready for your "
     "working. Export any board as a PDF.", "/whiteboard", "Open the whiteboard", "lav"),
    ("✏️", "New pen tools on every paper",
     "The toolbar now sits on the left: pens, highlighter, shapes that snap neat, text, sticky notes, stickers and "
     "pasted images.", "Hold any tool (or tap it twice) for its options. Pin the bar to keep it open.",
     "/papers/topical", "Try it on a paper", "pink"),
    ("🧭", "A real compass, ruler and protractor",
     "At true scale on the page - for constructions, bearings, loci-style drawing and transformations.",
     "Drag the needle onto a point (it snaps to line ends and crossings), set the radius with the pencil, then turn "
     "the top to draw the arc. The lock keeps the radius for the second arc.", "/whiteboard/new?template=construction",
     "Practise a construction", "teal"),
]

GROUPS = [
    ("Practise", "lav", [
        ("📚", "Topical past papers", "Pick chapters and subtopics - get real Cambridge questions with the mark scheme after each one.",
         "Mix up to 4 chapters; the newest papers come first.", "/papers/topical"),
        ("⏱️", "Mock tests", "A timed exam-style paper from your chapters. The mark scheme unlocks when you press Finish.",
         "Time is one minute per mark, like the real thing.", "/papers/mock-tests"),
        ("📅", "Papers by year", "Every sitting's question paper, mark scheme and insert, side by side. No account needed.",
         "On a wide screen the mark scheme follows the question you are reading.", "/yearly"),
        ("🔘", "MCQ practice", "Full multiple-choice papers or topical sets, marked instantly against the official key.",
         "Turn on live check to see each answer as you go.", "/mcq"),
        ("🗂️", "My papers", "Every booklet and mock test you have built, with your ink saved on them.",
         "Download any paper with your annotations burnt in.", "/my-papers"),
    ]),
    ("Understand", "green", [
        ("✦", "Explain and Guide me", "On every question in a topical paper: a full worked explanation, or hints one step at a time.",
         "Try Guide me first - you remember what you work out yourself.", "/papers/topical"),
        ("🤖", "AI Tutor", "Ask about any concept and get a patient, step-by-step answer.",
         "Ask it to quiz you on a chapter when you think you know it.", "/tutor.html"),
        ("📸", "Photo Solver", "Snap a question to get a solution - or snap your own working to have it checked.",
         "“Check my working” gives an estimated mark and shows which step went wrong.", "/solver"),
        ("📝", "Revision notes", "Chapter-by-chapter notes written for the current syllabus, linked to practice questions.",
         "Each chapter ends with a button that builds a paper on it.", "/notes"),
        ("📦", "Resources", "Well-known teachers' notes, books, worksheets, official syllabuses and planners.",
         "Search inside a folder to find a file deep in it.", "/resources"),
    ]),
    ("Remember", "orange", [
        ("🃏", "Flashcards", "Spaced-repetition decks - the cards you find hard come back more often.",
         "Five minutes a day beats an hour the night before.", "/flashcards.html"),
        ("🗒️", "My notes", "Your own jottings and sticky notes, kept in one place.",
         "Highlight text on a notes page to save it straight here.", "/notes.html"),
        ("🎯", "Study session", "Everything due today - flashcards, weak topics - in one sitting.",
         "Keeps your streak going on busy days.", "/study.html"),
    ]),
    ("Track", "blue", [
        ("📊", "Dashboard", "Your streak, time spent, papers done and what to revise next.",
         "Any activity keeps the streak - even ten minutes.", "/dashboard.html"),
        ("📈", "Topical and yearly progress", "Mark papers as done, record your marks and see grades against the real thresholds.",
         "Progress tracking is free for every subject.", "/topical-progress.html"),
        ("🧮", "Grade calculator", "Predict your grade from your paper marks with the official thresholds.",
         "Use it after a mock to see where the marks matter most.", "/grade-calculator.html"),
    ]),
    ("Tools", "pink", [
        ("🔢", "Calculator", "An fx-991ES-style calculator: fractions, roots, SOLVE, equations, statistics.",
         "Inside any paper press <b>Alt + T</b> - it opens beside the question.", "/calculator.html"),
        ("📉", "Graph plotter", "Plot any function or relation and read values off it.",
         "Type it the way you would write it: 2x^2 - 3x + 1.", "/graph.html"),
        ("📐", "Formula sheets", "169 formulas, each marked “given in the exam” or “must memorise”.",
         "Physics IGCSE gives you nothing in the exam - check what to learn.", "/formulas.html"),
        ("🧪", "Periodic table", "With the exact values Cambridge uses.", "", "/periodic-table.html"),
        ("💻", "Pseudocode runner", "Write and run Cambridge pseudocode in the browser.",
         "Paste a past-paper algorithm and trace it.", "/pseudocode.html"),
        ("🔎", "Search everything", "Every page, subject, chapter and note from one box.",
         "Press <b>Ctrl K</b> (or /) anywhere on the site.", "/explore"),
    ]),
]

FAQ = [
    ("Is PrepWithTee Board free?",
     "Yes - every account gets 3 boards free, with all the pens, shapes, compass, stickers and PDF export. Any paid "
     "plan makes boards unlimited and adds PDF import."),
    ("Can I write on past papers with a stylus?",
     "Yes. The tools on every paper support Apple Pencil, Surface and Wacom pens with pressure, and once a pen is "
     "used your finger scrolls instead of drawing."),
    ("Where are my annotations saved?",
     "In your account, page by page, so they are there on any device. From My papers you can download a paper with "
     "your ink on it."),
    ("How do I use the compass for constructions?",
     "Open the compass from the tools on the left. Drag the red needle onto a point - it snaps to line ends and "
     "crossings - drag the pencil to set the radius, then turn the top to draw an arc. Lock the radius to draw the "
     "matching arc from the other point."),
]


def _card(ic, title, what, tip, url, cta=None, tone=None, new=False) -> str:
    return (f'<a class="ft-card{" is-new" if new else ""}{f" cat-tone-{tone}" if tone else ""}" href="{_e(url)}">'
            f'<span class="ft-ic" aria-hidden="true">{ic}</span>'
            f'<span class="ft-body"><b>{_e(title)}{" <em>New</em>" if new else ""}</b><span>{_e(what)}</span>'
            + (f'<small><i>Tip</i> {tip}</small>' if tip else "")
            + (f'<span class="ft-cta">{_e(cta)} →</span>' if cta else "")
            + "</span></a>")


@router.get("/features", response_class=HTMLResponse)
def features(user: dict | None = Depends(_auth.maybe_user)):
    import ui
    state = _catalog._student_state(user)
    new = "".join(_card(ic, t, w, tip, url, cta, tone, new=True) for ic, t, w, tip, url, cta, tone in NEW)
    groups = "".join(
        f'<section class="ft-group cat-tone-{tone}" id="{_e(head.lower())}"><h2 class="ui-h2">{_e(head)}</h2>'
        f'<div class="ft-grid">{"".join(_card(ic, t, w, tip, url) for ic, t, w, tip, url in items)}</div></section>'
        for head, tone, items in GROUPS)
    jump = "".join(f'<a href="#{_e(h.lower())}">{_e(h)}</a>' for h, _t, _i in GROUPS)
    faq_html, faq_ld = ui.faq(FAQ)
    week = ui.steps([
        ("Learn a chapter", "Read the <a href=\"/notes\">notes</a>, then ask the <a href=\"/tutor.html\">AI Tutor</a> about anything unclear."),
        ("Practise it", "Build a <a href=\"/papers/topical\">topical paper</a> on it. Stuck? <b>Guide me</b> before <b>Explain</b>."),
        ("Work it out properly", "Send a hard question to the <a href=\"/whiteboard\">whiteboard</a> and solve it step by step."),
        ("Test yourself", "A <a href=\"/papers/mock-tests\">mock test</a> on the chapters you have done - timed, marked from the scheme."),
        ("Keep it", "Add what you got wrong to <a href=\"/flashcards.html\">flashcards</a> and track it on your <a href=\"/dashboard.html\">dashboard</a>."),
    ], title="A good week with PrepWithTee")
    n = len(NEW) + sum(len(i) for _h, _t, i in GROUPS)
    body = f"""
    <header class="cat-hero cat-hero-sm ft-hero">
      <p class="cat-eyebrow">Features</p>
      <h1>More than past papers</h1>
      <p class="cat-lede">PrepWithTee has {n} things built to help you learn, practise and remember - most students
        only find the topical papers. Here is all of it, with the one tip that makes each one useful.</p>
      <nav class="ft-jump" aria-label="Jump to">{''.join([f'<a href="#new">What’s new</a>', jump])}</nav>
    </header>
    <section class="ft-new" id="new"><h2 class="ui-h2">What's new</h2><div class="ft-grid ft-grid-new">{new}</div></section>
    {groups}
    {week}
    {faq_html}"""
    return _catalog._respond(_catalog._shell(
        title="PrepWithTee Features - Past Papers, Whiteboard, AI Tutor & Study Tools", path="/features", body=body,
        state=state, ld=[faq_ld],
        desc="Everything on PrepWithTee for O Level, IGCSE and A Level: topical and yearly past papers, mock tests, "
             "MCQ practice, an online whiteboard with compass and protractor, AI explanations, notes, flashcards "
             "and an exam calculator.",
        crumbs=[("Home", "/"), ("Features", "/features")]), bool(user))
