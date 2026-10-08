"""The student's side of teaching: "My classroom".

    /classroom                   every subject they have a teacher for
    /classroom/{syllabus}        that subject: teacher, what's next, the shared folder
                                 (to do / in progress / done / marked) with the
                                 teacher's marks + comments, classes held
    POST /api/classroom/items/{id}/open   the student opened it (in progress)
    POST /api/classroom/items/{id}/done   "I've done this" (or undo with ?undo=1)
    GET  /api/classroom                   counts for the dashboard / nav badge

The folder is the same one the teacher sees in /teach (teach.folder_for), minus
the teacher's private notes. Server-rendered; a little JS for the buttons.
"""
from __future__ import annotations

import html as _html
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import auth as _auth
import catalog as _catalog
import teach_store as _ts
import teaching as _teaching
import users_db as _udb

router = APIRouter()
CLASSROOM_V = "20261009b"
_e = _html.escape

KIND = {"booklet": ("📑", "Topical booklet"), "test": ("🧪", "Mock test"), "board": ("🖊️", "Whiteboard"),
        "homework": ("📝", "Homework"), "class": ("🎓", "Class"), "report": ("📊", "Report"),
        "file": ("📎", "File"), "note": ("💬", "Note from your teacher"), "link": ("🔗", "Link")}
COLS = [("todo", "To do"), ("in_progress", "In progress"), ("done", "Done - waiting for your teacher"),
        ("marked", "Marked")]
STUDENT_DONE_KINDS = {"booklet", "board", "note", "link", "file"}     # tests finish themselves; homework on its page


def _subjects(user: dict) -> dict[str, list[dict]]:
    """{syllabus: [teacher, ...]} for the student's linked teachers."""
    try:
        if _udb._USE_SUPABASE:
            rows = _udb.fetch_all("teacher_students", "teacher_id,syllabus,status", eq={"student_id": user["id"]})
        else:
            with _udb._local() as c:
                rows = [dict(r) for r in c.execute(
                    "SELECT teacher_id, syllabus, status FROM teacher_students WHERE student_id=?", (user["id"],))]
    except Exception as exc:
        print(f"[classroom] {exc}", flush=True)
        rows = []
    out: dict[str, list[dict]] = {}
    people: dict[str, dict] = {}
    for r in rows:
        if r.get("status") not in (None, "active") or not r.get("syllabus"):
            continue
        t = people.get(r["teacher_id"]) or _udb.get_user(r["teacher_id"]) or {}
        people[r["teacher_id"]] = t
        out.setdefault(r["syllabus"], []).append({"id": r["teacher_id"], "name": t.get("name") or "Your teacher",
                                                 "picture_url": t.get("picture_url")})
    # subjects that have folder items even if the link was removed later stay visible
    for i in _items(user["id"]):
        out.setdefault(i["syllabus"], [])
    return out


def _items(sid: str, syllabus: str | None = None) -> list[dict]:
    import teach
    try:
        return teach.folder_for(sid, syllabus, private=False)
    except Exception as exc:
        print(f"[classroom] folder: {exc}", flush=True)
        return []


def _feedback(items: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for i in items:
        if i["status"] == "marked" and not (i.get("meta") or {}).get("virtual"):
            try:
                out[i["id"]] = _ts.feedback(i["id"])
            except Exception:
                out[i["id"]] = []
    return out


def _name(code: str) -> str:
    s = _catalog.SUBJECTS.get(code) or {}
    return s.get("name") or s.get("plain") or code


def _num(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _initials(n: str) -> str:
    return "".join(w[0] for w in (n or "?").split()[:2]).upper()


def _avatar(p: dict) -> str:
    if p.get("picture_url"):
        return f'<img class="cr-av" src="{_e(p["picture_url"])}" alt="" referrerpolicy="no-referrer">'
    return f'<span class="cr-av" aria-hidden="true">{_e(_initials(p.get("name")))}</span>'


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%d %b")
    except ValueError:
        return str(iso)[:10]


# ── pages ────────────────────────────────────────────────────────────────────

def _page(user: dict, title: str, path: str, body: str, crumbs: list) -> HTMLResponse:
    import ui
    state = _catalog._student_state(user)
    html = _catalog._shell(title=f"{title} - PrepWithTee", desc="Your classes, papers and boards with your teacher.",
                           path=path, body=ui.dash_tabs("/classroom") + body, state=state, noindex=True,
                           crumbs=crumbs, styles=(f"/classroom.css?v={CLASSROOM_V}",),
                           scripts=(f"/classroom.js?v={CLASSROOM_V}",))
    return HTMLResponse(html, headers={"Cache-Control": "private, no-store"})


@router.get("/classroom", include_in_schema=False)
def classroom_home(user: dict | None = Depends(_auth.maybe_user)):
    if user is None:
        return RedirectResponse("/login.html?next=/classroom", 302)
    subjects = _subjects(user)
    if len(subjects) == 1:
        return RedirectResponse(f"/classroom/{next(iter(subjects))}", 302)
    crumbs = [("Home", "/"), ("Dashboard", "/dashboard.html"), ("My classroom", "/classroom")]
    if not subjects:
        body = """<header class="cat-hero cat-hero-sm"><p class="cat-eyebrow">My classroom</p>
          <h1>Learn with a PrepWithTee teacher</h1>
          <p class="cat-lede">When you join a class, your teacher's papers, whiteboards, notes and marks all live
            here - one folder per subject, so you always know what to do next.</p>
          <div class="cat-actions"><a class="cat-btn" href="/maths-classes.html">Maths classes</a>
            <a class="cat-btn cat-btn-ghost" href="/physics-classes.html">Physics classes</a>
            <a class="cat-btn cat-btn-ghost" href="/cs-classes.html">Computer Science classes</a></div></header>"""
        return _page(user, "My classroom", "/classroom", body, crumbs)
    cards = []
    for code, teachers in sorted(subjects.items()):
        items = _items(user["id"], code)
        todo = sum(1 for i in items if i["status"] in ("todo", "in_progress"))
        marked = sum(1 for i in items if i["status"] == "marked")
        cards.append(f"""<a class="cr-subj" href="/classroom/{_e(code)}">
          <span class="cr-subj-code">{_e(code)}</span><b>{_e(_name(code))}</b>
          <span class="cr-teachers">{''.join(_avatar(t) for t in teachers)}
            <span>{_e(", ".join(t["name"] for t in teachers) or "No teacher right now")}</span></span>
          <span class="cr-subj-stats"><span><b>{todo}</b> to do</span><span><b>{marked}</b> marked</span>
            <span><b>{len(items)}</b> in the folder</span></span></a>""")
    body = f"""<header class="cat-hero cat-hero-sm"><p class="cat-eyebrow">My classroom</p>
      <h1>Your subjects with a teacher</h1>
      <p class="cat-lede">Everything your teacher set you, and everything you've done, in one place per subject.</p>
      </header><div class="cr-subjects">{''.join(cards)}</div>"""
    return _page(user, "My classroom", "/classroom", body, crumbs)


def _item_card(i: dict, fb: list[dict]) -> str:
    ic, label = KIND.get(i["kind"], ("📄", i["kind"]))
    due = ""
    if i.get("due_at") and i["status"] not in ("done", "marked"):
        late = str(i["due_at"])[:10] < date.today().isoformat()
        due = f'<span class="cr-due{" is-late" if late else ""}">{"was due" if late else "due"} {_e(_date(i["due_at"]))}</span>'
    url = i.get("url")
    body = (i.get("meta") or {}).get("body")
    overall = next((f for f in fb if f.get("question_id") is None), None)
    per_q = [f for f in fb if f.get("question_id") is not None]
    marks = ""
    if overall or per_q:
        got = overall.get("marks") if overall and overall.get("marks") is not None else (
            sum(f.get("marks") or 0 for f in per_q) if per_q else None)
        out_of = overall.get("max_marks") if overall and overall.get("max_marks") else (
            sum(f.get("max_marks") or 0 for f in per_q) if per_q else None)
        parts = []
        if got is not None:
            score = _num(got) + (f" / {_num(out_of)}" if out_of else "")
            parts.append(f'<b class="cr-mark">{_e(score)}</b>')
        if overall and overall.get("comment"):
            parts.append(f'<p>{_e(overall["comment"])}</p>')
        parts += [f'<p class="cr-fbq">{_e(f["comment"])}</p>' for f in per_q if f.get("comment")]
        marks = f'<div class="cr-fb"><span class="cr-fb-h">Your teacher:</span>{"".join(parts)}</div>'
    can_done = i["kind"] in STUDENT_DONE_KINDS and not (i.get("meta") or {}).get("virtual")
    btns = []
    if url:
        btns.append(f'<a class="cat-btn cr-open" href="{_e(url)}" data-open="{_e(i["id"])}"'
                    f'{" target=_blank rel=noopener" if i["kind"] == "link" else ""}>Open</a>')
    if can_done and i["status"] in ("todo", "in_progress"):
        btns.append(f'<button type="button" class="cat-btn cat-btn-ghost" data-done="{_e(i["id"])}">I\'ve done this</button>')
    elif can_done and i["status"] == "done":
        btns.append(f'<button type="button" class="cr-undo" data-undo="{_e(i["id"])}">Not done yet</button>')
    chips = "".join(f'<span class="cr-chip">{_e(c)}</span>' for c in (i.get("chapters") or []))
    return f"""<article class="cr-item cr-{_e(i['kind'])}" data-kind="{_e(i['kind'])}">
      <div class="cr-item-top"><span class="cr-kind">{ic} {_e(label)}</span>{due}</div>
      <h3>{_e(i['title'])}</h3>
      {f'<p class="cr-body">{_e(body)}</p>' if body else ''}
      {f'<div class="cr-chips">{chips}</div>' if chips else ''}
      {marks}
      {f'<div class="cr-actions">{"".join(btns)}</div>' if btns else ''}
    </article>"""


@router.get("/classroom/{syllabus}", include_in_schema=False)
def classroom_subject(syllabus: str, user: dict | None = Depends(_auth.maybe_user)):
    if user is None:
        return RedirectResponse(f"/login.html?next=/classroom/{syllabus}", 302)
    subjects = _subjects(user)
    if syllabus not in subjects:
        return RedirectResponse("/classroom", 302)
    teachers = subjects[syllabus]
    items = [i for i in _items(user["id"], syllabus) if i["kind"] != "class"]
    fb = _feedback(items)
    classes = [c for c in _safe(lambda: _udb.get_class_log(user["id"]), []) if c.get("syllabus") == syllabus]
    classes.sort(key=lambda c: (c.get("class_date") or "", c.get("start_time") or ""), reverse=True)
    today = date.today().isoformat()
    upcoming = sorted([c for c in classes if (c.get("class_date") or "") >= today and c.get("status") != "cancelled"],
                      key=lambda c: (c.get("class_date"), c.get("start_time") or ""))
    held = [c for c in classes if (c.get("status") or "held") == "held" and (c.get("class_date") or "") <= today]
    open_n = sum(1 for i in items if i["status"] in ("todo", "in_progress"))
    due_soon = sorted((i for i in items if i["status"] in ("todo", "in_progress") and i.get("due_at")),
                      key=lambda i: str(i["due_at"]))
    nxt = due_soon[0] if due_soon else next((i for i in items if i["status"] == "todo"), None)

    if nxt:
        what = KIND.get(nxt["kind"], ("", nxt["kind"]))[1]
        due_txt = f" · due {_date(nxt['due_at'])}" if nxt.get("due_at") else ""
        start = (f'<a class="cat-btn" href="{_e(nxt["url"])}" data-open="{_e(nxt["id"])}">Start</a>'
                 if nxt.get("url") else "")
        next_html = (f'<p class="cr-eyebrow">Next up</p><h2>{_e(nxt["title"])}</h2>'
                     f'<p>{_e(what + due_txt)}</p>{start}')
    else:
        next_html = ('<p class="cr-eyebrow">Next up</p><h2>You&rsquo;re all caught up</h2>'
                     '<p>Nothing waiting from your teacher.</p>')
    class_next = ""
    if upcoming:
        u = upcoming[0]
        at = f" at {_e(u['start_time'])}" if u.get("start_time") else ""
        class_next = f'<p class="cr-class-next">Next class: <b>{_e(_date(u.get("class_date")))}</b>{at}</p>'
    cols = []
    for key, label in COLS:
        lst = [i for i in items if i["status"] == key]
        cols.append(f"""<section class="cr-col" data-col="{key}"><h2>{_e(label)} <span>{len(lst)}</span></h2>
          {''.join(_item_card(i, fb.get(i['id'], [])) for i in lst) or '<p class="cr-empty">Nothing here.</p>'}</section>""")
    teacher_html = "".join(f"""<div class="cr-teacher">{_avatar(t)}<div><b>{_e(t['name'])}</b>
        <span>Your {_e(_name(syllabus))} teacher</span></div>
        <a class="cat-btn cat-btn-ghost" href="/messages.html">Message</a></div>""" for t in teachers) or \
        '<p class="cr-empty">No teacher on this subject right now - your folder is kept.</p>'
    class_html = "".join(f"""<li><b>{_e(_date(c.get('class_date')))}</b>{f" · {_e(c['start_time'])}" if c.get('start_time') else ''}
        <span>{_e(c.get('topic') or 'Class')}</span>{f'<em>{_e(c["note"])}</em>' if c.get('note') else ''}</li>"""
                         for c in held[:12]) or '<li class="cr-empty">No classes logged yet.</li>'
    body = f"""
    <header class="cat-hero cat-hero-sm cr-hero">
      <p class="cat-eyebrow">My classroom · {_e(syllabus)}</p>
      <h1>{_e(_name(syllabus))}</h1>
      <dl class="cat-stats"><div><dt>To do</dt><dd>{open_n}</dd></div>
        <div><dt>Marked</dt><dd>{sum(1 for i in items if i['status'] == 'marked')}</dd></div>
        <div><dt>Classes</dt><dd>{len(held)}</dd></div></dl>
    </header>
    <div class="cr-top">
      <div class="cr-card cr-next">{next_html}{class_next}</div>
      <div class="cr-card">{teacher_html}</div>
    </div>
    <div class="cr-bar" role="toolbar" aria-label="Show">
      <button type="button" class="yr-chip" data-show="" aria-pressed="true">Everything</button>
      {''.join(f'<button type="button" class="yr-chip" data-show="{k}" aria-pressed="false">{v[0]} {_e(v[1].split(" from")[0])}</button>'
               for k, v in KIND.items() if any(i["kind"] == k for i in items))}
    </div>
    <div class="cr-cols">{''.join(cols)}</div>
    <section class="cr-card cr-classes"><h2>Classes</h2><ol>{class_html}</ol></section>"""
    crumbs = [("Home", "/"), ("Dashboard", "/dashboard.html"), ("My classroom", "/classroom"),
              (_name(syllabus), f"/classroom/{syllabus}")]
    return _page(user, f"{_name(syllabus)} classroom", f"/classroom/{syllabus}", body, crumbs)


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:
        print(f"[classroom] {exc}", flush=True)
        return default


# ── API ──────────────────────────────────────────────────────────────────────

def _my_item(item_id: str, user: dict) -> dict:
    it = _ts.get_item(item_id)
    if not it or it["student_id"] != user["id"] or it["kind"] == "tnote" or (it.get("meta_json") or {}).get("private"):
        raise HTTPException(404, "Not found")
    return it


@router.post("/api/classroom/items/{item_id}/open")
def item_open(item_id: str, user: dict = Depends(_auth.get_current_user)):
    it = _my_item(item_id, user)
    f = {}
    if not it.get("student_opened_at"):
        f["student_opened_at"] = _ts.now()
    if it["status"] == "todo" and it["kind"] in STUDENT_DONE_KINDS | {"test"}:
        f["status"] = "in_progress"
    if it["kind"] in ("note", "link") and it["status"] == "todo":
        f["status"] = "in_progress"
    if f:
        _ts.update_item(it["id"], f)
    return {"ok": True}


@router.post("/api/classroom/items/{item_id}/done")
def item_done(item_id: str, undo: bool = False, user: dict = Depends(_auth.get_current_user)):
    it = _my_item(item_id, user)
    if it["kind"] not in STUDENT_DONE_KINDS:
        raise HTTPException(409, "This one is finished on its own page.")
    if it["status"] == "marked":
        raise HTTPException(409, "Your teacher has already marked this.")
    if undo:
        _ts.update_item(it["id"], {"status": "in_progress", "student_done_at": None})
    else:
        _ts.update_item(it["id"], {"status": "done", "student_done_at": _ts.now(),
                                   **({} if it.get("student_opened_at") else {"student_opened_at": _ts.now()})})
    return {"ok": True, "status": "in_progress" if undo else "done"}


@router.get("/api/classroom")
def classroom_summary(user: dict = Depends(_auth.get_current_user)):
    subjects = _subjects(user)
    out = []
    for code, teachers in subjects.items():
        items = _items(user["id"], code)
        out.append({"syllabus": code, "name": _name(code), "teachers": teachers, "url": f"/classroom/{code}",
                    "todo": sum(1 for i in items if i["status"] in ("todo", "in_progress")),
                    "marked": sum(1 for i in items if i["status"] == "marked")})
    return {"subjects": out, "todo": sum(s["todo"] for s in out)}


def notifications(user: dict) -> list[dict]:
    """Folder events for the bell (users.list_notifications): new things from the
    teacher, and things they've marked. Items created as homework already have
    their own homework notification, so they're skipped here."""
    notes = []
    for i in _items(user["id"]):
        if (i.get("meta") or {}).get("virtual") or i["kind"] in ("homework", "class"):
            continue
        href = f"/classroom/{i['syllabus']}"
        ic, label = KIND.get(i["kind"], ("📄", "Item"))
        notes.append({"id": f"cr-new-{i['id']}", "kind": "classroom", "icon": ic,
                      "title": f"From your teacher: {i['title']}", "body": f"{label} · {_name(i['syllabus'])}",
                      "at": i.get("created_at"), "href": href, "done": i["status"] in ("done", "marked")})
        if i["status"] == "marked" and i.get("marked_at"):
            notes.append({"id": f"cr-marked-{i['id']}", "kind": "marked", "icon": "✅",
                          "title": f"Marked: {i['title']}", "body": f"Your teacher marked it · {_name(i['syllabus'])}",
                          "at": i["marked_at"], "href": href, "done": False})
    return notes
