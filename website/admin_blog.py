"""Admin console phase 4: the Blog studio, AI writing for blog / courses /
newsletter, and post ideas from the site's own data.

Posts live in blog_posts (blog.py's connection: SQLite index.db locally,
Postgres in production). State is derived, never stored twice:
    published                      -> "published"
    not published, publish_at set  -> "scheduled"  (blog.publish_due flips it)
    otherwise                      -> "draft"
Every save and every AI generation writes a blog_revisions row, so nothing an
admin (or the AI) wrote is ever lost.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import blog as _blog
import content_ai
import users_db as _udb
from admin_auth import Admin

router = APIRouter(prefix="/api/admin")

SLUG = re.compile(r"^[a-z0-9-]{1,120}$")
POST_FIELDS = ("title", "slug", "excerpt", "body_markdown", "cover_url", "author", "meta_title",
               "meta_desc", "faq_json", "keywords")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(sql: str, args: tuple = (), one: bool = False, write: bool = False):
    _blog.ensure_table()
    con = _blog._con()
    try:
        cur = con.execute(sql, args)
        if write:
            con.commit()
            return getattr(cur, "lastrowid", None)
        rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows
    finally:
        con.close()


def _state(p: dict) -> str:
    if p.get("published") in (True, 1, "1", "t", "true"):
        return "published"
    return "scheduled" if p.get("publish_at") else "draft"


def _view(p: dict) -> dict:
    p = dict(p)
    p["state"] = _state(p)
    p["published"] = p["state"] == "published"
    try:
        p["faq"] = json.loads(p.get("faq_json") or "[]")
    except (TypeError, ValueError):
        p["faq"] = []
    body = p.get("body_markdown") or ""
    p["words"] = len(re.findall(r"\w+", body))
    return p


def _post(post_id: int) -> dict:
    p = _q("SELECT * FROM blog_posts WHERE id = ?", (post_id,), one=True)
    if not p:
        raise HTTPException(404, "Post not found")
    return p


def _revision(post_id: int, p: dict, source: str, by: str | None) -> None:
    _q("INSERT INTO blog_revisions (post_id, title, body_markdown, excerpt, meta_title, meta_desc, "
       "source, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
       (post_id, p.get("title"), p.get("body_markdown"), p.get("excerpt"), p.get("meta_title"),
        p.get("meta_desc"), source, by, _now()), write=True)


# ── posts ────────────────────────────────────────────────────────────────────

@router.get("/blog/posts")
def posts(_=Admin):
    rows = _q("SELECT * FROM blog_posts ORDER BY COALESCE(updated_at, created_at) DESC")
    out = []
    for r in rows:
        v = _view(r)
        v.pop("body_markdown", None)
        out.append(v)
    return {"posts": out, "ai": content_ai.status()}


@router.get("/blog/posts/{post_id}")
def post(post_id: int, _=Admin):
    revs = _q("SELECT id, title, source, created_by, created_at, LENGTH(body_markdown) AS chars "
              "FROM blog_revisions WHERE post_id = ? ORDER BY created_at DESC, id DESC", (post_id,))
    return {"post": _view(_post(post_id)), "revisions": revs[:50], "ai": content_ai.status()}


class PostIn(BaseModel):
    title: str | None = None
    slug: str | None = None
    excerpt: str | None = None
    body_markdown: str | None = None
    cover_url: str | None = None
    author: str | None = None
    meta_title: str | None = None
    meta_desc: str | None = None
    faq: list[dict] | None = None
    keywords: str | None = None
    source: str | None = None           # 'ai:<model>' when the text came from the AI


def _fields(req: PostIn) -> dict:
    f = {k: v for k, v in req.model_dump(exclude_unset=True).items()
         if k in POST_FIELDS and v is not None}
    if req.faq is not None:
        f["faq_json"] = json.dumps([{"q": str(x.get("q", ""))[:300], "a": str(x.get("a", ""))[:1500]}
                                    for x in req.faq if x.get("q") and x.get("a")][:10])
    if "slug" in f:
        f["slug"] = f["slug"].strip().lower()
        if not SLUG.match(f["slug"]):
            raise HTTPException(400, "The address may only use lowercase letters, numbers and hyphens")
    if "title" in f and not f["title"].strip():
        raise HTTPException(400, "Give the post a title")
    return f


def _slug_free(slug: str, post_id: int | None = None) -> bool:
    row = _q("SELECT id FROM blog_posts WHERE slug = ?", (slug,), one=True)
    return row is None or row["id"] == post_id


@router.post("/blog/posts")
def create_post(req: PostIn, admin=Admin):
    f = _fields(req)
    f.setdefault("title", "Untitled post")
    base = f.get("slug") or re.sub(r"[^a-z0-9]+", "-", f["title"].lower()).strip("-")[:80] or "post"
    slug, n = base, 2
    while not _slug_free(slug):
        slug, n = f"{base}-{n}", n + 1
    f["slug"] = slug
    f.setdefault("body_markdown", "")
    f.setdefault("author", admin.get("name") if admin.get("via") == "session" else "Muhammad Taahaa")
    f["created_at"] = f["updated_at"] = _now()
    cols = list(f)
    _q(f"INSERT INTO blog_posts ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
       tuple(f[c] for c in cols), write=True)
    p = _q("SELECT * FROM blog_posts WHERE slug = ?", (slug,), one=True)
    _revision(p["id"], p, req.source or "manual", admin.get("email"))
    return {"post": _view(p)}


@router.patch("/blog/posts/{post_id}")
def update_post(post_id: int, req: PostIn, admin=Admin):
    _post(post_id)
    f = _fields(req)
    if "slug" in f and not _slug_free(f["slug"], post_id):
        raise HTTPException(409, "Another post already uses that address")
    if not f:
        return {"post": _view(_post(post_id))}
    f["updated_at"] = _now()
    _q(f"UPDATE blog_posts SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?",
       (*f.values(), post_id), write=True)
    p = _post(post_id)
    if any(k in f for k in ("title", "body_markdown", "excerpt", "meta_title", "meta_desc")):
        _revision(post_id, p, req.source or "manual", admin.get("email"))
    return {"post": _view(p)}


@router.delete("/blog/posts/{post_id}")
def delete_post(post_id: int, _=Admin):
    _post(post_id)
    _q("DELETE FROM blog_revisions WHERE post_id = ?", (post_id,), write=True)
    _q("DELETE FROM blog_posts WHERE id = ?", (post_id,), write=True)
    return {"ok": True}


class PublishIn(BaseModel):
    action: str                         # publish | schedule | unpublish
    publish_at: str | None = None       # ISO, for schedule


@router.post("/blog/posts/{post_id}/publish")
def publish(post_id: int, req: PublishIn, _=Admin):
    p = _post(post_id)
    pg = _blog._db.USE_PG
    if req.action in ("publish", "schedule"):
        if not (p.get("body_markdown") or "").strip():
            raise HTTPException(400, "Write the post before publishing it")
    if req.action == "publish":
        _q("UPDATE blog_posts SET published = ?, published_at = COALESCE(published_at, ?), publish_at = NULL, "
           "updated_at = ? WHERE id = ?", (True if pg else 1, _now(), _now(), post_id), write=True)
    elif req.action == "schedule":
        try:
            when = datetime.fromisoformat((req.publish_at or "").replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "Pick a date and time")
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when <= datetime.now(timezone.utc):
            raise HTTPException(400, "Pick a time in the future (or publish now)")
        _q("UPDATE blog_posts SET published = ?, publish_at = ?, updated_at = ? WHERE id = ?",
           (False if pg else 0, when.isoformat(), _now(), post_id), write=True)
    elif req.action == "unpublish":
        _q("UPDATE blog_posts SET published = ?, publish_at = NULL, updated_at = ? WHERE id = ?",
           (False if pg else 0, _now(), post_id), write=True)
    else:
        raise HTTPException(400, "action must be publish, schedule or unpublish")
    return {"post": _view(_post(post_id))}


@router.get("/blog/posts/{post_id}/revisions/{rev_id}")
def revision(post_id: int, rev_id: int, _=Admin):
    r = _q("SELECT * FROM blog_revisions WHERE id = ? AND post_id = ?", (rev_id, post_id), one=True)
    if not r:
        raise HTTPException(404, "Revision not found")
    return {"revision": r}


@router.post("/blog/posts/{post_id}/revisions/{rev_id}/restore")
def restore(post_id: int, rev_id: int, admin=Admin):
    r = revision(post_id, rev_id, admin)["revision"]
    fields = {k: r[k] for k in ("title", "body_markdown", "excerpt", "meta_title", "meta_desc") if r.get(k) is not None}
    fields["updated_at"] = _now()
    _q(f"UPDATE blog_posts SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
       (*fields.values(), post_id), write=True)
    p = _post(post_id)
    _revision(post_id, p, f"restore of #{rev_id}", admin.get("email"))
    return {"post": _view(p)}


# ── AI writing ───────────────────────────────────────────────────────────────

def _ai(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except content_ai.AIUnavailable as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class BriefIn(BaseModel):
    prompt: str
    audience: str | None = "students"
    subject: str | None = None
    tone: str | None = None
    length: int = 900
    keywords: str | None = None


@router.post("/blog/ai/outline")
def ai_outline(req: BriefIn, _=Admin):
    if len(req.prompt.strip()) < 5:
        raise HTTPException(400, "Describe the post in a few words")
    data, model = _ai(content_ai.blog_outline, req.prompt.strip(), req.audience, req.subject, req.tone,
                      max(300, min(req.length, 2500)), req.keywords)
    return {"outline": data, "model": model}


class DraftIn(BriefIn):
    outline: dict


@router.post("/blog/ai/draft")
def ai_draft(req: DraftIn, _=Admin):
    if not req.outline.get("sections"):
        raise HTTPException(400, "The outline has no sections")
    data, model = _ai(content_ai.blog_draft, req.outline, req.audience, req.subject, req.tone,
                      max(300, min(req.length, 2500)), req.keywords)
    data["title"] = req.outline.get("title") or ""
    return {"draft": data, "model": model}


class EditIn(BaseModel):
    action: str
    selection: str
    context: str = ""
    subject: str | None = None


@router.post("/blog/ai/edit")
def ai_edit(req: EditIn, _=Admin):
    if not req.selection.strip():
        raise HTTPException(400, "Select some text first")
    data, model = _ai(content_ai.blog_edit, req.action, req.selection[:6000], req.context, req.subject)
    return {"replacement": data["replacement"], "model": model}


# ── post ideas from the site's own data ──────────────────────────────────────

def idea_signals() -> list[dict]:
    """Facts from the site that suggest posts students need. No AI involved."""
    out = []
    reqs: dict[str, int] = {}
    for r in _udb.get_subject_requests():
        key = f"{(r.get('subject') or '').strip()} {(r.get('board') or '').strip()}".strip()
        if key:
            reqs[key] = reqs.get(key, 0) + 1
    for key, n in sorted(reqs.items(), key=lambda kv: -kv[1])[:3]:
        out.append({"kind": "request", "why": f"{n} student{'s' if n > 1 else ''} asked for {key}",
                    "title": f"Studying {key}: where to start", "subject": None})
    scores: dict[tuple, list[float]] = {}
    for q in _udb.fetch_all("quiz_sessions", "syllabus,topic,score,max_marks"):
        if q.get("score") is not None and q.get("max_marks"):
            scores.setdefault((q["syllabus"], q["topic"]), []).append(q["score"] / q["max_marks"])
    weak = sorted(((k, sum(v) / len(v), len(v)) for k, v in scores.items() if len(v) >= 3), key=lambda x: x[1])
    for (syl, topic), avg, n in weak[:4]:
        out.append({"kind": "weak", "why": f"Average AI-quiz score on {syl} {topic} is {round(avg * 100)}% over {n} attempts",
                    "title": f"{topic} ({syl}): the mistakes that cost marks", "subject": syl})
    picks: dict[tuple, int] = {}
    for b in _udb.fetch_all("booklets", "syllabus,params_json"):
        try:
            chapters = json.loads(b.get("params_json") or "{}").get("chapters") or []
        except (TypeError, ValueError):
            chapters = []
        for ch in chapters:
            name = ch if isinstance(ch, str) else (ch.get("name") or ch.get("topic") if isinstance(ch, dict) else None)
            if name:
                picks[(b["syllabus"], name)] = picks.get((b["syllabus"], name), 0) + 1
    for (syl, ch), n in sorted(picks.items(), key=lambda kv: -kv[1])[:4]:
        out.append({"kind": "popular", "why": f"{n} booklets built on {syl} {ch}",
                    "title": f"How to revise {ch} for {syl}", "subject": syl})
    return out


@router.get("/blog/ideas")
def ideas(polish: bool = Query(False), _=Admin):
    signals = idea_signals()
    model = None
    if polish and signals and content_ai.status()["configured"]:
        try:
            titles, model = content_ai.polish_ideas(signals)
            for s, t in zip(signals, titles):
                if isinstance(t, dict) and t.get("title"):
                    s["title"], s["angle"] = t["title"], t.get("angle")
        except content_ai.AIUnavailable:
            model = None                       # the plain titles still stand
    return {"ideas": signals, "model": model}


# ── course pages and newsletter ──────────────────────────────────────────────

class CourseAI(BaseModel):
    syllabus_code: str
    level: str
    title: str
    notes: str | None = None
    field: str | None = None             # regenerate one field only


@router.post("/courses/ai")
def course_ai(req: CourseAI, _=Admin):
    if req.field and req.field not in content_ai.COURSE_FIELDS:
        raise HTTPException(400, f"field must be one of {list(content_ai.COURSE_FIELDS)}")
    data, model = _ai(content_ai.course_fields, req.syllabus_code, req.level, req.title, req.notes, req.field)
    if req.field:
        data = {req.field: data[req.field]}
    return {"fields": data, "model": model}


class NewsAI(BaseModel):
    prompt: str = ""
    include_posts: bool = True


@router.post("/newsletter/ai")
def newsletter_ai(req: NewsAI, _=Admin):
    recent = _blog.get_published_posts()[:5] if req.include_posts else []
    data, model = _ai(content_ai.newsletter, req.prompt.strip(), recent)
    return {"draft": data, "model": model}


@router.get("/ai/status")
def ai_status(_=Admin):
    return content_ai.status()
