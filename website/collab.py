"""Shared ink on a collaborative booklet: the teacher and the student draw on
ONE layer per page and see each other's changes within a second or two.

    GET  /api/collab?doc=booklet:<id>[:ms]               every page + who is here
    PUT  /api/collab        {doc, page, objects, version} 409 {objects, version} if stale
    GET  /api/collab/poll?doc=&since=&page=              pages changed since `since`

No WebSockets: the browser polls (static/collab.js) - 1.5 s while someone else
is here, slower otherwise. Saves are optimistic (`version`); on a 409 the
browser merges by object id and saves again, so neither side loses work.
Each object carries its author in `by` (set here, never trusted from the client
for new objects).

Whiteboards use the same idea on their own tables (whiteboard.py wb_poll).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

import auth as _auth
import booklets as _booklets
import teach_store as _ts
import users_db as _udb

router = APIRouter()

_DOC = re.compile(r"^booklet:([A-Za-z0-9_-]{6,16})(:ms)?$")
MAX_OBJECTS = 3000
MAX_BYTES = 600_000


def _doc_access(doc: str, user: dict) -> dict:
    """The booklet behind a collaborative doc key, if this user may ink on it:
    its owner or their teacher (or an admin), and only once it is shared."""
    m = _DOC.match(doc or "")
    if not m:
        raise HTTPException(400, "Unknown document")
    b = _booklets._owned(m.group(1), user, shared=False)
    if not _booklets.is_collab(b):
        raise HTTPException(409, {"code": "not_collab", "message": "This paper isn't shared with a teacher."})
    if m.group(2) and not _booklets.ms_allowed(b, user):
        raise HTTPException(403, "The mark scheme isn't open yet.")
    return b


def _names(ids: list[str]) -> dict[str, dict]:
    out = {}
    for uid in ids:
        u = _udb.get_user(uid) or {}
        out[uid] = {"id": uid, "name": u.get("name") or "Someone",
                    "teacher": u.get("role") in ("teacher", "admin")}
    return out


def _here(doc: str, user: dict, page: str | None) -> list[dict]:
    try:
        _ts.touch_presence(doc, user["id"], (page or "")[:40] or None)
        rows = [r for r in _ts.present(doc) if r["user_id"] != user["id"]]
    except Exception as exc:
        print(f"[collab] presence: {exc}", flush=True)
        return []
    names = _names([r["user_id"] for r in rows])
    return [{**names[r["user_id"]], "page": r.get("page")} for r in rows]


@router.get("/api/collab")
def collab_get(doc: str, user: dict = Depends(_auth.get_current_user)):
    b = _doc_access(doc, user)
    people = _names([b["user_id"]] + [t["id"] for t in _teachers(b["user_id"])])
    return {"doc": doc, "now": _ts.now(), "me": user["id"],
            "pages": {str(r["page"]): {"objects": r.get("objects") or [], "version": r.get("version") or 1}
                      for r in _ts.ink_pages(doc)},
            "here": _here(doc, user, None), "people": list(people.values())}


def _teachers(student_id: str) -> list[dict]:
    import teaching
    return teaching.teachers_of(student_id)


class InkSave(BaseModel):
    doc: str
    page: int
    objects: list[dict]
    version: int = 0

    @field_validator("page")
    @classmethod
    def _page(cls, v):
        if not 0 <= v < 1000:
            raise ValueError("page out of range")
        return v

    @field_validator("objects")
    @classmethod
    def _objects(cls, v):
        if len(v) > MAX_OBJECTS or len(json.dumps(v)) > MAX_BYTES:
            raise ValueError("too much ink on one page")
        if any(not isinstance(o.get("t"), str) or not o.get("id") for o in v):
            raise ValueError("every object needs a type and an id")
        return v


@router.put("/api/collab")
def collab_put(req: InkSave, user: dict = Depends(_auth.get_current_user)):
    _doc_access(req.doc, user)
    cur = _ts.ink_page(req.doc, req.page)
    # authorship: objects already on the page keep theirs; new ones are mine
    known = {o.get("id"): o.get("by") for o in (cur or {}).get("objects") or []}
    objects = [{**o, "by": known.get(o["id"]) or user["id"]} for o in req.objects]
    v = _ts.save_ink(req.doc, req.page, objects, req.version, user["id"])
    if v is None:
        cur = _ts.ink_page(req.doc, req.page) or {}
        return Response(json.dumps({"code": "stale", "objects": cur.get("objects") or [],
                                    "version": cur.get("version") or 0}),
                        status_code=409, media_type="application/json")
    return {"version": v, "objects": objects}


@router.get("/api/collab/poll")
def collab_poll(doc: str, since: str | None = None, page: str | None = None,
                user: dict = Depends(_auth.get_current_user)):
    _doc_access(doc, user)
    t = _ts.now()
    pages = []
    if since:
        try:
            cut = (datetime.fromisoformat(since) - timedelta(seconds=2)).isoformat()
        except ValueError:
            cut = None
        if cut:
            pages = [{"page": r["page"], "objects": r.get("objects") or [], "version": r.get("version") or 1}
                     for r in _ts.ink_pages(doc, cut)]
    return {"now": t, "pages": pages, "here": _here(doc, user, page)}
