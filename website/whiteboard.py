"""PrepWithTee Board - the whiteboard, and image storage for every ink layer.

Pages
    GET  /whiteboard                      dashboard (boards, folders, starred, trash);
                                          guests get the product page
    GET  /whiteboard/new?template=&q=     make a board and open it (q = drop that
                                          past-paper question on it)
    GET  /whiteboard/{id}                 the editor (owner; an assigned teacher read-only)
    GET  /whiteboard/s/{token}            a share link (read-only, optional "make a copy")

API (signed in unless a share token is given)
    GET    /api/wb/me                         plan limits + usage
    GET    /api/wb/boards                     my boards (the dashboard filters them)
    POST   /api/wb/boards                     new board {title, kind, template, folder_id}
    GET    /api/wb/boards/{id}                board + pages in order
    PATCH  /api/wb/boards/{id}                title, starred, folder, settings, thumb, shared_with_teacher
    DELETE /api/wb/boards/{id}[?purge=1]      to the trash (or gone)
    POST   /api/wb/boards/{id}/restore        out of the trash
    POST   /api/wb/boards/{id}/duplicate
    POST   /api/wb/boards/{id}/pages          add {after, duplicate, settings}
    PUT    /api/wb/boards/{id}/pages/{pid}    save ink {objects, version} -> 409 + server copy if stale
    PATCH  /api/wb/boards/{id}/pages/{pid}    page settings (paper, pattern, size, background)
    DELETE /api/wb/boards/{id}/pages/{pid}
    PUT    /api/wb/boards/{id}/order          page order
    POST   /api/wb/boards/{id}/import-pdf     PDF pages -> new pages with the PDF as background (paid)
    GET    /api/wb/boards/{id}/export.pdf     the board as a PDF (?s=token on share links)
    GET|POST /api/wb/boards/{id}/shares       share links; DELETE /api/wb/shares/{token}
    GET    /api/wb/shared/{token}             a shared board; POST .../copy into my boards
    GET|POST /api/wb/folders, PATCH|DELETE /api/wb/folders/{id}
    GET    /api/wb/students                   (teachers) boards their students sent them
    POST   /api/ink/assets                    upload an image (any ink layer) -> {id, url}
    GET    /api/ink/assets/{id}               the image (owner, their teacher, a share link, admin)

Free accounts keep FREE_BOARDS boards (the trash doesn't count) and
FREE_BYTES of images; any paid plan (and teachers / admins) is unlimited and
can import PDFs. Realtime co-editing is a later phase: every object already
carries an id and pages save with an optimistic version, which is what it needs.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, field_validator

import access as _access
import annot_pdf
import auth as _auth
import teach_store as _ts
import teaching as _teaching
import users_db as _udb
import wb_store as S

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = Path(os.environ.get("INK_ASSET_DIR") or ROOT / "data" / "ink_assets")
WB_V = "20261009t"                       # bump with static/board/* and annotate.*
FREE_BOARDS = 3
FREE_BYTES = 50 * 1024 * 1024
PAID_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMAGE = 8 * 1024 * 1024
MAX_PDF = 25 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_PAGES = 200
_ID = re.compile(r"^[A-Za-z0-9_-]{6,24}$")
_ASSET_URL = re.compile(r"^/api/ink/assets/([A-Za-z0-9_-]{6,24})(?:\?.*)?$")
_e = lambda s: _html.escape(str(s), quote=True)        # noqa: E731
KINDS = ("pages", "infinite")
SIZES = tuple(annot_pdf.PAGE_SIZES)
PAPERS = tuple(annot_pdf.PAPERS)
PATTERNS = annot_pdf.PATTERNS
IMAGE_SIGS = {"png": (b"\x89PNG\r\n\x1a\n",), "jpg": (b"\xff\xd8\xff",), "gif": (b"GIF87a", b"GIF89a"),
              "webp": (b"RIFF",)}
MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


# ── who may do what ──────────────────────────────────────────────────────────
def _staff(user: dict | None) -> bool:
    return bool(user) and user.get("role") in ("teacher", "admin")


def _paid(user: dict) -> bool:
    return _access._plan_active(user) != "free"


def _limits(user: dict) -> dict:
    paid = _paid(user)
    return {"paid": paid, "boards": None if paid else FREE_BOARDS,
            "bytes": PAID_BYTES if paid else FREE_BYTES, "pdf_import": paid}


def _teaches(teacher: dict | None, student_id: str) -> bool:
    return _teaching.teaches(teacher, student_id)


def _id_or_404(v: str) -> str:
    if not _ID.match(v or ""):
        raise HTTPException(404, "Not found")
    return v


def _board_for(user: dict | None, board_id: str, write: bool | str = False) -> dict:
    """The board, if this user may see it. 404 for everyone else, so ids can't
    be probed.
      read:          owner; a member (wb_members); their teacher if the student
                     shared it; an admin
      write="draw":  owner, or a member with the edit role (pages + ink)
      write=True:    owner only (rename, trash, share links)"""
    b = S.get_board(_id_or_404(board_id))
    if not b or not user:
        raise HTTPException(404, "Board not found")
    if b["owner_id"] == user["id"]:
        return b
    role = _ts.board_role(b["id"], user["id"])
    if write == "draw" and role == "edit":
        return b
    if not write and (role or (_teaches(user, b["owner_id"])
                               and (b.get("shared_with_teacher") or user.get("role") == "admin"))):
        return b
    raise HTTPException(404, "Board not found")


def _can_draw(user: dict, b: dict) -> bool:
    return b["owner_id"] == user["id"] or _ts.board_role(b["id"], user["id"]) == "edit"


def _share_or_404(token: str) -> tuple[dict, dict]:
    sh = S.get_share(token) if _ID.match(token or "") else None
    if not sh or sh.get("revoked_at"):
        raise HTTPException(404, "This link has been switched off")
    if sh.get("expires_at") and sh["expires_at"] < S.now():
        raise HTTPException(404, "This link has expired")
    b = S.get_board(sh["board_id"])
    if not b or b.get("deleted_at"):
        raise HTTPException(404, "This board is no longer available")
    return sh, b


def _live_count(owner_id: str) -> int:
    """Boards counted against the free limit - a board a teacher made for the
    student (a member the student didn't add) is the teacher's, not counted."""
    live = [b for b in S.list_boards(owner_id) if not b.get("deleted_at")]
    try:
        theirs = {b["id"] for b in live for m in _ts.board_members(b["id"]) if m.get("added_by") not in (None, owner_id)}
    except Exception:
        theirs = set()
    return sum(1 for b in live if b["id"] not in theirs)


def _room_for_board(user: dict) -> None:
    lim = _limits(user)
    if lim["boards"] is not None and _live_count(user["id"]) >= lim["boards"]:
        raise HTTPException(403, {"code": "wb_limit",
                                  "message": f"Free accounts can keep {FREE_BOARDS} boards. Delete one (empty the "
                                             f"trash too) or upgrade for unlimited boards."})


# ── settings + objects ───────────────────────────────────────────────────────
def clean_settings(v: dict | None) -> dict:
    v = v or {}
    out = {}
    if v.get("size") in SIZES:
        out["size"] = v["size"]
    p = v.get("paper")
    if p in PAPERS or (isinstance(p, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", p)):
        out["paper"] = p
    if v.get("pattern") in PATTERNS:
        out["pattern"] = v["pattern"]
    ax = annot_pdf.clean_axes(v.get("ax"))
    if ax:
        out["ax"] = ax
    bg = v.get("bg")
    if isinstance(bg, str) and _ASSET_URL.match(bg):
        out["bg"] = bg.split("?")[0]
    return out


def _check_objects(objs: list, infinite: bool) -> list:
    if not isinstance(objs, list) or len(objs) > 5000:
        raise HTTPException(413, "Too much on one page - add a new page")
    if len(json.dumps(objs, separators=(",", ":"))) > (3_000_000 if infinite else 1_500_000):
        raise HTTPException(413, "Too much on one page - add a new page")
    for o in objs:
        if not isinstance(o, dict) or not isinstance(o.get("t"), str):
            raise HTTPException(400, "Bad object")
    return objs


def _new_id(n: int = 9) -> str:
    return secrets.token_urlsafe(n)[:12].replace("-", "x").replace("_", "y")


TEMPLATES = {
    "blank": ("Blank pages", "pages", {"pattern": "plain", "paper": "white"}),
    "lined": ("Lined notebook", "pages", {"pattern": "lined", "paper": "white"}),
    "squared": ("Maths squared", "pages", {"pattern": "squared", "paper": "white"}),
    "graph": ("Graph paper", "pages", {"pattern": "graph", "paper": "white"}),
    "axes": ("Graph with axes", "pages", {"pattern": "axes", "paper": "white", "ax": dict(annot_pdf.AXES_DEFAULT)}),
    "dotted": ("Dotted journal", "pages", {"pattern": "dotted", "paper": "cream"}),
    "isometric": ("Isometric", "pages", {"pattern": "isometric", "paper": "white"}),
    "cornell": ("Cornell notes", "pages", {"pattern": "cornell", "paper": "white"}),
    "construction": ("Construction sheet", "pages", {"pattern": "plain", "paper": "white"}),
    "lesson": ("Lesson plan", "pages", {"pattern": "lined", "paper": "white"}),
    "planner": ("Weekly planner", "pages", {"pattern": "plain", "paper": "cream", "size": "a4l"}),
    "infinite": ("Infinite canvas", "infinite", {"pattern": "dotted", "paper": "white"}),
    "chalk": ("Chalkboard", "infinite", {"pattern": "plain", "paper": "chalk"}),
}


def _oid() -> str:
    return secrets.token_hex(4)


def _txt(x, y, txt, pt=12, **kw) -> dict:
    return {"id": _oid(), "t": "text", "x": x, "y": y, "s": round(pt / 595, 5), "c": kw.pop("c", "@ink"),
            "txt": txt, "f": kw.pop("f", "sans"), **kw}


def starter_objects(template: str) -> list:
    """A template's first page: headings, boxes, a hint - plain objects the
    student can move or delete like their own."""
    if template == "lesson":
        return [_txt(0.08, 0.035, "Lesson plan", 22, b=1, c="@purple"),
                _txt(0.08, 0.085, "Topic:", 12, b=1), _txt(0.55, 0.085, "Date:", 12, b=1),
                _txt(0.08, 0.16, "Learning objectives", 13, b=1, c="@blue"),
                _txt(0.08, 0.37, "Key ideas & worked examples", 13, b=1, c="@blue"),
                _txt(0.08, 0.68, "Practice questions", 13, b=1, c="@blue"),
                _txt(0.08, 0.86, "Homework / next steps", 13, b=1, c="@blue")]
    if template == "planner":
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        out = [_txt(0.04, 0.035, "Weekly planner", 20, b=1, c="@purple"), _txt(0.62, 0.045, "Week of:", 12, b=1)]
        for i, d in enumerate(days):
            col, row = i % 4, i // 4
            x0, y0 = 0.04 + col * 0.235, 0.13 + row * 0.43
            out.append({"id": _oid(), "t": "rect", "rr": 1, "c": "@grey", "w": 0.0015,
                        "a": [x0, y0], "b": [x0 + 0.215, y0 + 0.4]})
            out.append(_txt(x0 + 0.012, y0 + 0.015, d, 12, b=1, c="@blue"))
        out.append({"id": _oid(), "t": "note", "bg": "@yellow", "txt": "Goals this week:",
                    "a": [0.745, 0.56], "b": [0.94, 0.9]})
        return out
    if template == "construction":
        return [_txt(0.08, 0.04, "Constructions", 18, b=1, c="@purple"),
                {"id": _oid(), "t": "note", "bg": "@sky", "a": [0.62, 0.03], "b": [0.94, 0.17],
                 "txt": "Open the compass in the tools on the left. Drag the needle onto a point - it snaps to "
                        "ends and crossings."}]
    return []


def _make_board(user: dict, title: str, template: str, folder_id: str | None = None) -> dict:
    name, kind, settings = TEMPLATES.get(template, TEMPLATES["blank"])
    bid, pid = _new_id(), _new_id(6)
    t = S.now()
    b = S.create_board({"id": bid, "owner_id": user["id"], "title": (title or name)[:120], "kind": kind,
                        "folder_id": folder_id, "settings": settings, "page_order": [pid], "starred": False,
                        "shared_with_teacher": False, "created_at": t, "updated_at": t, "opened_at": t})
    S.insert_page(bid, pid, {}, starter_objects(template))
    return b


def _summary(b: dict) -> dict:
    return {k: b.get(k) for k in ("id", "title", "kind", "folder_id", "settings", "starred", "shared_with_teacher",
                                  "thumb", "created_at", "updated_at", "opened_at", "deleted_at")} | \
        {"pages": len(b.get("page_order") or [])}


def _full(b: dict, tokenise: str | None = None) -> dict:
    """Board + its pages in order (missing / stray pages repaired)."""
    rows = {p["page_id"]: p for p in S.get_pages(b["id"])}
    order = [pid for pid in (b.get("page_order") or []) if pid in rows]
    order += [pid for pid in rows if pid not in order]
    pages = [{"id": pid, "settings": rows[pid].get("settings") or {}, "objects": rows[pid].get("objects") or [],
              "version": rows[pid].get("version") or 1} for pid in order]
    if tokenise:                                        # share links: images carry the token
        for p in pages:
            for o in p["objects"]:
                if o.get("t") == "img" and isinstance(o.get("src"), str) and _ASSET_URL.match(o["src"]):
                    o["src"] = f"{o['src'].split('?')[0]}?s={tokenise}"
            if p["settings"].get("bg"):
                p["settings"]["bg"] = f"{p['settings']['bg']}?s={tokenise}"
        if b["settings"].get("bg"):
            b["settings"]["bg"] = f"{b['settings']['bg']}?s={tokenise}"
    return {**_summary(b), "owner_id": b["owner_id"], "pages": pages}


# ── API: me + boards ─────────────────────────────────────────────────────────
@router.get("/api/wb/me")
def wb_me(user: dict = Depends(_auth.get_current_user)):
    st = S.owner_stats(user["id"])
    return {**st, "limits": _limits(user), "role": user.get("role") or "student",
            "has_teacher": bool(_udb.get_student_teachers(user["id"])) if user.get("role", "student") == "student" else False}


@router.get("/api/wb/boards")
def wb_list(user: dict = Depends(_auth.get_current_user)):
    return {"boards": [_summary(b) for b in S.list_boards(user["id"])],
            "folders": S.list_folders(user["id"])}


class NewBoard(BaseModel):
    title: str = ""
    template: str = "blank"
    folder_id: str | None = None

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return (v or "").strip()[:120]


@router.post("/api/wb/boards")
def wb_create(req: NewBoard, user: dict = Depends(_auth.get_current_user)):
    _room_for_board(user)
    folder = req.folder_id if req.folder_id and (S.get_folder(req.folder_id) or {}).get("owner_id") == user["id"] else None
    return _summary(_make_board(user, req.title, req.template if req.template in TEMPLATES else "blank", folder))


@router.get("/api/wb/boards/{board_id}")
def wb_get(board_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id)
    mine = b["owner_id"] == user["id"]
    if mine:
        S.update_board(b["id"], {"opened_at": S.now()})
        _ts.student_event(("board",), b["id"])         # a board in their folder: now in progress
    others = _people(b, user)
    return {**_full(b), "readonly": not _can_draw(user, b) or bool(b.get("deleted_at")),
            "me": user["id"], "people": others,
            "collab": len(others) > 1 or bool(b.get("shared_with_teacher")),
            "teacher_edit": any(p["role"] == "edit" and p["id"] != b["owner_id"] for p in others)}


def _people(b: dict, user: dict) -> list[dict]:
    """Everyone else who can open this board: owner + members (+ the owner's
    teachers when the board is shared with them). For names on presence dots."""
    try:
        rows = _ts.board_members(b["id"])
    except Exception:
        rows = []
    ids = {b["owner_id"]: "edit", **{r["user_id"]: r["role"] for r in rows}}
    out = []
    for uid, role in ids.items():
        u = _udb.get_user(uid) or {}
        out.append({"id": uid, "name": u.get("name") or "Someone", "role": role,
                    "teacher": u.get("role") in ("teacher", "admin"), "owner": uid == b["owner_id"]})
    return out


@router.get("/api/wb/boards/{board_id}/poll")
def wb_poll(board_id: str, since: str | None = None, page: str | None = None,
            user: dict = Depends(_auth.get_current_user)):
    """What changed since `since` (the `now` of the previous poll): pages
    (objects + version), the page order, and who else has the board open.
    The editor calls this every 1-6 s while open."""
    b = _board_for(user, board_id)
    doc = f"wb:{b['id']}"
    try:
        _ts.touch_presence(doc, user["id"], (page or "")[:40] or None)
        here = [r for r in _ts.present(doc) if r["user_id"] != user["id"]]
    except Exception:
        here = []
    t = _ts.now()
    pages = []
    if since:
        # 2 s of overlap: a save that landed while the last poll ran is not missed
        from datetime import datetime, timedelta
        try:
            cut = (datetime.fromisoformat(since) - timedelta(seconds=2)).isoformat()
        except ValueError:
            cut = None
        rows = _ts._select("wb_pages", {"board_id": b["id"]}, gt=("updated_at", cut)) if cut else []
        pages = [{"id": r["page_id"], "objects": r.get("objects") or [], "version": r.get("version") or 1,
                  "settings": r.get("settings") or {}} for r in rows]
    names = {}
    for r in here:
        u = _udb.get_user(r["user_id"]) or {}
        names[r["user_id"]] = {"id": r["user_id"], "name": u.get("name") or "Someone", "page": r.get("page"),
                               "teacher": u.get("role") in ("teacher", "admin")}
    return {"now": t, "pages": pages, "order": b.get("page_order") or [], "title": b.get("title"),
            "here": list(names.values())}


class BoardPatch(BaseModel):
    title: str | None = None
    starred: bool | None = None
    folder_id: str | None = None
    settings: dict | None = None
    thumb: str | None = None
    shared_with_teacher: bool | None = None
    teacher_edit: bool | None = None                      # my teachers may draw on it too
    move: bool = False                                    # folder_id given (None = out of any folder)


def _drop_cover(old: str | None, new: str | None, owner_id: str, board_id: str) -> None:
    """A replaced cover image is only that board's cover: delete it (unless two
    identical covers - two blank boards - share the one deduplicated file)."""
    m = _ASSET_URL.match(old or "")
    if not m or old == new:
        return
    if any(o.get("thumb") == old for o in S.list_boards(owner_id) if o["id"] != board_id):
        return
    a = S.get_asset(m.group(1))
    if not a or a["owner_id"] != owner_id:
        return
    p = asset_path(a["id"])
    S.delete_asset(a["id"])
    try:
        if p:
            p.unlink()
    except OSError:
        pass


@router.patch("/api/wb/boards/{board_id}")
def wb_patch(board_id: str, req: BoardPatch, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write=True)
    f = {}
    if req.title is not None:
        f["title"] = req.title.strip()[:120] or "Untitled board"
    if req.starred is not None:
        f["starred"] = req.starred
    if req.move:
        if req.folder_id and (S.get_folder(req.folder_id) or {}).get("owner_id") != user["id"]:
            raise HTTPException(404, "Folder not found")
        f["folder_id"] = req.folder_id
    if req.settings is not None:
        f["settings"] = clean_settings(req.settings)
    if req.thumb is not None:
        m = _ASSET_URL.match(req.thumb)
        a = S.get_asset(m.group(1)) if m else None
        f["thumb"] = req.thumb.split("?")[0] if a and a["owner_id"] == user["id"] else None
        _drop_cover(b.get("thumb"), f["thumb"], user["id"], b["id"])
    if req.shared_with_teacher is not None:
        f["shared_with_teacher"] = req.shared_with_teacher
    if req.teacher_edit is not None:
        for t in _teaching.teachers_of(user["id"]):
            _ts.set_board_member(b["id"], t["id"], "edit" if req.teacher_edit else None, user["id"])
        if req.teacher_edit:
            f["shared_with_teacher"] = True
    if f:
        if set(f) - {"thumb", "starred"}:
            f["updated_at"] = S.now()
        S.update_board(b["id"], f)
    return _summary(S.get_board(b["id"]))


@router.delete("/api/wb/boards/{board_id}")
def wb_delete(board_id: str, purge: int = 0, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write=True)
    if purge:
        S.delete_board(b["id"])
    else:
        S.update_board(b["id"], {"deleted_at": S.now()})
    return {"ok": True}


@router.post("/api/wb/boards/{board_id}/restore")
def wb_restore(board_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write=True)
    if b.get("deleted_at"):
        _room_for_board(user)
        S.update_board(b["id"], {"deleted_at": None, "updated_at": S.now()})
    return _summary(S.get_board(b["id"]))


def _copy_board(src: dict, user: dict, title: str) -> dict:
    """A copy owned by `user`. Images owned by someone else are copied too,
    so the new board never depends on the old owner's files."""
    full = _full(src)
    bid, t = _new_id(), S.now()
    remap: dict[str, str] = {}

    def own(url: str | None) -> str | None:
        m = _ASSET_URL.match(url or "")
        if not m:
            return url
        a = S.get_asset(m.group(1))
        if not a:
            return None
        if a["owner_id"] == user["id"]:
            return f"/api/ink/assets/{a['id']}"
        if a["id"] not in remap:
            mine = S.find_asset(user["id"], a["sha256"])
            if not mine:
                nid = _new_id()
                srcp = ASSET_DIR / a["owner_id"] / f"{a['id']}.{a['ext']}"
                dst = ASSET_DIR / user["id"] / f"{nid}.{a['ext']}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                if srcp.exists():
                    dst.write_bytes(srcp.read_bytes())
                S.add_asset({**{k: a[k] for k in ("sha256", "mime", "ext", "bytes", "w", "h")},
                             "id": nid, "owner_id": user["id"], "created_at": t})
                mine = {"id": nid}
            remap[a["id"]] = mine["id"]
        return f"/api/ink/assets/{remap[a['id']]}"

    order = []
    settings = dict(full.get("settings") or {})
    if settings.get("bg"):
        settings["bg"] = own(settings["bg"])
    S.create_board({"id": bid, "owner_id": user["id"], "title": title[:120], "kind": full["kind"],
                    "folder_id": None, "settings": settings, "page_order": [], "starred": False,
                    "shared_with_teacher": False, "created_at": t, "updated_at": t, "opened_at": t})
    for p in full["pages"]:
        pid = _new_id(6)
        objs = []
        for o in p["objects"]:
            if o.get("t") == "img":
                src2 = own(o.get("src"))
                if not src2:
                    continue
                o = {**o, "src": src2}
            objs.append(o)
        ps = dict(p["settings"])
        if ps.get("bg"):
            ps["bg"] = own(ps["bg"])
        S.insert_page(bid, pid, ps, objs)
        order.append(pid)
    S.update_board(bid, {"page_order": order})
    return S.get_board(bid)


@router.post("/api/wb/boards/{board_id}/duplicate")
def wb_duplicate(board_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id)
    _room_for_board(user)
    return _summary(_copy_board(b, user, f"{b['title']} (copy)"))


# ── API: pages ───────────────────────────────────────────────────────────────
class NewPage(BaseModel):
    after: str | None = None
    duplicate: str | None = None
    settings: dict | None = None


@router.post("/api/wb/boards/{board_id}/pages")
def wb_add_page(board_id: str, req: NewPage, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write="draw")
    if b["kind"] != "pages":
        raise HTTPException(400, "An infinite board has one canvas")
    order = list(b.get("page_order") or [])
    if len(order) >= MAX_PAGES:
        raise HTTPException(413, f"A board can have up to {MAX_PAGES} pages")
    pid = _new_id(6)
    settings, objects = clean_settings(req.settings), []
    if req.duplicate:
        src = S.get_page(b["id"], req.duplicate)
        if src:
            settings, objects = src.get("settings") or {}, [{**o, "id": _oid()} for o in src.get("objects") or []]
    S.insert_page(b["id"], pid, settings, objects)
    anchor = req.after or req.duplicate
    at = order.index(anchor) + 1 if anchor in order else len(order)
    order.insert(at, pid)
    S.update_board(b["id"], {"page_order": order, "updated_at": S.now()})
    return {"id": pid, "settings": settings, "objects": objects, "version": 1, "order": order}


class PageSave(BaseModel):
    objects: list
    version: int


@router.put("/api/wb/boards/{board_id}/pages/{page_id}")
def wb_save_page(board_id: str, page_id: str, req: PageSave, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write="draw")
    if b.get("deleted_at"):
        raise HTTPException(409, {"code": "trashed", "message": "This board is in the trash - restore it to edit"})
    objs = _check_objects(req.objects, b["kind"] == "infinite")
    known = {o.get("id"): o.get("by") for o in (S.get_page(b["id"], _id_or_404(page_id)) or {}).get("objects") or []}
    objs = [{**o, "by": known.get(o.get("id")) or o.get("by") or user["id"]} for o in objs]    # authorship
    v = S.save_page(b["id"], page_id, objs, req.version)
    if v is None:
        cur = S.get_page(b["id"], page_id)
        if not cur:
            raise HTTPException(404, "Page not found")
        return Response(json.dumps({"code": "stale", "objects": cur.get("objects") or [],
                                    "version": cur.get("version") or 1}),
                        status_code=409, media_type="application/json")
    S.update_board(b["id"], {"updated_at": S.now()})
    return {"version": v}


class PagePatch(BaseModel):
    settings: dict


@router.patch("/api/wb/boards/{board_id}/pages/{page_id}")
def wb_page_settings(board_id: str, page_id: str, req: PagePatch, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write="draw")
    if not S.get_page(b["id"], _id_or_404(page_id)):
        raise HTTPException(404, "Page not found")
    s = clean_settings(req.settings)
    S.set_page_settings(b["id"], page_id, s)
    return {"settings": s}


@router.delete("/api/wb/boards/{board_id}/pages/{page_id}")
def wb_delete_page(board_id: str, page_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write="draw")
    order = [p for p in (b.get("page_order") or []) if p != page_id]
    if not order:
        raise HTTPException(400, "A board needs at least one page")
    S.delete_page(b["id"], _id_or_404(page_id))
    S.update_board(b["id"], {"page_order": order, "updated_at": S.now()})
    return {"order": order}


class Order(BaseModel):
    order: list[str]


@router.put("/api/wb/boards/{board_id}/order")
def wb_order(board_id: str, req: Order, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write="draw")
    if sorted(req.order) != sorted(b.get("page_order") or []):
        raise HTTPException(400, "The order must list every page once")
    S.update_board(b["id"], {"page_order": req.order, "updated_at": S.now()})
    return {"order": req.order}


# ── API: images ──────────────────────────────────────────────────────────────
def _sniff(data: bytes) -> str | None:
    for ext, sigs in IMAGE_SIGS.items():
        if any(data.startswith(s) for s in sigs):
            if ext == "webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return None


def store_image(user: dict, data: bytes) -> dict:
    """Keep an image for this user (deduplicated); the asset row."""
    ext = _sniff(data)
    if not ext:
        raise HTTPException(415, "That file isn't a PNG, JPEG, GIF or WebP image")
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "Images can be up to 8 MB")
    sha = hashlib.sha256(data).hexdigest()
    have = S.find_asset(user["id"], sha)
    if have:
        return have
    if S.owner_bytes(user["id"]) + len(data) > _limits(user)["bytes"]:
        raise HTTPException(403, {"code": "wb_storage",
                                  "message": "Your image storage is full. Delete some boards or upgrade for 2 GB."})
    w = h = None
    try:
        import fitz
        pix = fitz.Pixmap(data)
        w, h = pix.width, pix.height
    except Exception:
        pass
    aid = _new_id()
    path = ASSET_DIR / user["id"] / f"{aid}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    row = {"id": aid, "owner_id": user["id"], "sha256": sha, "mime": MIME[ext], "ext": ext,
           "bytes": len(data), "w": w, "h": h, "created_at": S.now()}
    S.add_asset(row)
    return row


@router.post("/api/ink/assets")
async def ink_upload(file: UploadFile = File(...), user: dict = Depends(_auth.get_current_user)):
    data = await file.read(MAX_IMAGE + 1)
    a = store_image(user, data)
    return {"id": a["id"], "url": f"/api/ink/assets/{a['id']}", "w": a.get("w"), "h": a.get("h")}


def asset_path(asset_id: str) -> Path | None:
    a = S.get_asset(asset_id)
    if not a:
        return None
    p = ASSET_DIR / a["owner_id"] / f"{a['id']}.{a['ext']}"
    return p if p.exists() else None


def resolver(owner_id: str):
    """For annot_pdf: an image src -> its file, only for this owner's images."""
    def resolve(src: str):
        m = _ASSET_URL.match(src or "")
        if not m:
            return None
        a = S.get_asset(m.group(1))
        if not a or a["owner_id"] != owner_id:
            return None
        return asset_path(a["id"])
    return resolve


@router.get("/api/ink/assets/{asset_id}")
def ink_asset(asset_id: str, s: str | None = None, user: dict | None = Depends(_auth.maybe_user)):
    a = S.get_asset(_id_or_404(asset_id))
    if not a:
        raise HTTPException(404, "Not found")
    ok = bool(user) and (a["owner_id"] == user["id"] or user.get("role") == "admin" or _teaches(user, a["owner_id"])
                         or _teaching._teaches_id(a["owner_id"], user["id"]))
    if not ok and s:
        try:
            _, b = _share_or_404(s)
            ok = b["owner_id"] == a["owner_id"]
        except HTTPException:
            ok = False
    if not ok:
        raise HTTPException(404, "Not found")
    p = asset_path(a["id"])
    if not p:
        raise HTTPException(404, "Not found")
    return FileResponse(p, media_type=a["mime"], headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/api/wb/boards/{board_id}/import-pdf")
async def wb_import_pdf(board_id: str, file: UploadFile = File(...), user: dict = Depends(_auth.get_current_user)):
    """Each page of a PDF becomes a new board page with that page as its background."""
    b = _board_for(user, board_id, write="draw")
    if not _limits(user)["pdf_import"]:
        raise HTTPException(403, {"code": "wb_paid", "message": "Importing PDFs comes with a paid plan."})
    if b["kind"] != "pages":
        raise HTTPException(400, "PDFs go into a pages board")
    data = await file.read(MAX_PDF + 1)
    if not data.startswith(b"%PDF") or len(data) > MAX_PDF:
        raise HTTPException(415, "Choose a PDF up to 25 MB")
    import fitz
    try:
        doc = fitz.open("pdf", data)
    except Exception:
        raise HTTPException(415, "That PDF couldn't be opened")
    order = list(b.get("page_order") or [])
    n = min(doc.page_count, MAX_PDF_PAGES, MAX_PAGES - len(order))
    skipped = doc.page_count - n
    added = []
    for i in range(n):
        pg = doc[i]
        land = pg.rect.width > pg.rect.height
        png = pg.get_pixmap(dpi=130).tobytes("png")
        a = store_image(user, png)
        pid = _new_id(6)
        settings = {"bg": f"/api/ink/assets/{a['id']}", "size": "a4l" if land else "a4", "pattern": "plain",
                    "paper": "white"}
        S.insert_page(b["id"], pid, settings, [])
        order.append(pid)
        added.append({"id": pid, "settings": settings, "objects": [], "version": 1})
    doc.close()
    # a fresh board whose only page is still empty: the PDF replaces it
    if len(order) == n + 1 and added:
        first = S.get_page(b["id"], order[0])
        if first and not first.get("objects") and not (first.get("settings") or {}).get("bg"):
            S.delete_page(b["id"], order[0])
            order = order[1:]
    S.update_board(b["id"], {"page_order": order, "updated_at": S.now()})
    return {"pages": added, "order": order, "skipped": skipped}


# ── API: export ──────────────────────────────────────────────────────────────
@router.get("/api/wb/boards/{board_id}/export.pdf")
def wb_export(board_id: str, s: str | None = None, pages: str | None = None,
              user: dict | None = Depends(_auth.maybe_user)):
    if s:
        _, b = _share_or_404(s)
        if b["id"] != board_id:
            raise HTTPException(404, "Not found")
    else:
        b = _board_for(user, board_id)
    full = _full(b)
    pl = full["pages"]
    if pages:
        want = set(pages.split(","))
        pl = [p for p in pl if p["id"] in want] or pl
    pdf = annot_pdf.render_board(full, pl, resolver(b["owner_id"]))
    name = re.sub(r"[^A-Za-z0-9]+", "-", b["title"] or "board").strip("-")[:80] or "board"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"',
                             "Cache-Control": "private, no-store"})


# ── API: sharing ─────────────────────────────────────────────────────────────
class NewShare(BaseModel):
    role: str = "view"
    days: int | None = None


@router.get("/api/wb/boards/{board_id}/shares")
def wb_shares(board_id: str, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write=True)
    return {"shares": [{k: x.get(k) for k in ("token", "role", "created_at", "expires_at")} for x in S.list_shares(b["id"])]}


@router.post("/api/wb/boards/{board_id}/shares")
def wb_share(board_id: str, req: NewShare, user: dict = Depends(_auth.get_current_user)):
    b = _board_for(user, board_id, write=True)
    role = req.role if req.role in ("view", "copy") else "view"
    expires = None
    if req.days:
        from datetime import datetime, timedelta, timezone
        expires = (datetime.now(timezone.utc) + timedelta(days=max(1, min(365, req.days)))).isoformat()
    tok = secrets.token_urlsafe(12)[:16]
    S.create_share({"token": tok, "board_id": b["id"], "role": role, "created_by": user["id"],
                    "created_at": S.now(), "expires_at": expires})
    return {"token": tok, "role": role, "expires_at": expires, "url": f"/whiteboard/s/{tok}"}


@router.delete("/api/wb/shares/{token}")
def wb_unshare(token: str, user: dict = Depends(_auth.get_current_user)):
    sh = S.get_share(_id_or_404(token))
    if not sh:
        raise HTTPException(404, "Not found")
    _board_for(user, sh["board_id"], write=True)
    S.revoke_share(token)
    return {"ok": True}


@router.get("/api/wb/shared/{token}")
def wb_shared(token: str):
    sh, b = _share_or_404(token)
    return {**_full(b, tokenise=token), "owner_id": None, "readonly": True, "role": sh["role"]}


@router.post("/api/wb/shared/{token}/copy")
def wb_shared_copy(token: str, user: dict = Depends(_auth.get_current_user)):
    sh, b = _share_or_404(token)
    if sh["role"] != "copy" and b["owner_id"] != user["id"]:
        raise HTTPException(403, "This link is view-only")
    _room_for_board(user)
    return _summary(_copy_board(b, user, b["title"]))


# ── API: folders ─────────────────────────────────────────────────────────────
class FolderReq(BaseModel):
    name: str
    color: str | None = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        v = (v or "").strip()[:60]
        if not v:
            raise ValueError("Give the folder a name")
        return v


@router.get("/api/wb/folders")
def wb_folders(user: dict = Depends(_auth.get_current_user)):
    return {"folders": S.list_folders(user["id"])}


@router.post("/api/wb/folders")
def wb_new_folder(req: FolderReq, user: dict = Depends(_auth.get_current_user)):
    if len(S.list_folders(user["id"])) >= 100:
        raise HTTPException(413, "That's a lot of folders - tidy a few up first")
    fid = _new_id()
    S.create_folder({"id": fid, "owner_id": user["id"], "name": req.name,
                     "color": req.color if req.color in ("violet", "sky", "teal", "amber", "rose", "grey") else "violet",
                     "created_at": S.now()})
    return S.get_folder(fid)


@router.patch("/api/wb/folders/{folder_id}")
def wb_rename_folder(folder_id: str, req: FolderReq, user: dict = Depends(_auth.get_current_user)):
    f = S.get_folder(_id_or_404(folder_id))
    if not f or f["owner_id"] != user["id"]:
        raise HTTPException(404, "Folder not found")
    fields = {"name": req.name}
    if req.color in ("violet", "sky", "teal", "amber", "rose", "grey"):
        fields["color"] = req.color
    S.update_folder(folder_id, fields)
    return S.get_folder(folder_id)


@router.delete("/api/wb/folders/{folder_id}")
def wb_delete_folder(folder_id: str, user: dict = Depends(_auth.get_current_user)):
    f = S.get_folder(_id_or_404(folder_id))
    if not f or f["owner_id"] != user["id"]:
        raise HTTPException(404, "Folder not found")
    S.delete_folder(folder_id, user["id"])
    return {"ok": True}


# ── API: teachers ────────────────────────────────────────────────────────────
@router.get("/api/wb/students")
def wb_students(user: dict = Depends(_auth.get_current_user)):
    if not _staff(user):
        raise HTTPException(403, "For teachers")
    rows = _udb.get_teacher_students(user["id"]) if user.get("role") == "teacher" else []
    names = {r["student_id"]: r.get("name") or r.get("email") or "Student" for r in rows}
    boards = S.boards_shared_with_teacher(list(names))
    have = {b["id"] for b in boards}
    try:                                   # boards built for / opened to me as a member
        for m in _ts.member_boards(user["id"]):
            b = S.get_board(m["board_id"])
            if b and not b.get("deleted_at") and b["id"] not in have and b["owner_id"] in names:
                boards.append(b)
                have.add(b["id"])
    except Exception:
        pass
    return {"boards": [{**_summary(b), "student": names.get(b["owner_id"]), "student_id": b["owner_id"]} for b in boards]}


# ── pages (HTML) ─────────────────────────────────────────────────────────────
def _head(title: str, noindex: bool = True, extra: str = "") -> str:
    import catalog as _catalog
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  {'<meta name="robots" content="noindex">' if noindex else ''}
  <script>try{{var t=localStorage.getItem("theme")||"light";document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
  <title>{_e(title)}</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_catalog.STYLES_V}">
  {extra}
</head>"""


def _state(obj: dict) -> str:
    return json.dumps(obj).replace("</", "<\\/")


@router.get("/whiteboard", include_in_schema=False)
def whiteboard_home(request: Request, user: dict | None = Depends(_auth.maybe_user)):
    import blog as _blog
    if not user:
        return HTMLResponse(_landing(), headers={"Cache-Control": "public, max-age=600"})
    if request.query_params.get("about"):
        return HTMLResponse(_landing(user), headers={"Cache-Control": "private, no-store"})
    page = _head("My boards — PrepWithTee Board",
                 extra=f'<link rel="stylesheet" href="/board/boards.css?v={WB_V}">') + f"""
<body class="wbd-page" data-no-scratch>
{_blog._nav()}
<main id="wbd" class="wbd" data-state="loading"><p class="wbd-loading">Opening your boards…</p></main>
<script id="wbd-state" type="application/json">{_state({"me": {"id": user["id"], "name": user.get("name") or "", "role": user.get("role") or "student"}, "templates": {k: v[0] for k, v in TEMPLATES.items()}})}</script>
<script src="/main.js?v=20261009a"></script>
<script type="module" src="/auth.js?v=20261009a"></script>
<script type="module" src="/board/boards.js?v={WB_V}"></script>
</body>
</html>"""
    return HTMLResponse(page, headers={"Cache-Control": "private, no-store"})


WB_FAQ = [
    ("Is the PrepWithTee whiteboard free?",
     "Yes. Every free account keeps 3 boards with every tool - pens, shapes, compass, stickers, images and PDF export. "
     "Any paid plan makes boards unlimited and adds importing PDFs to write on."),
    ("Can I draw constructions with a compass?",
     "Yes. The compass works at true scale: drag the needle onto a point (it snaps to line ends and crossings), set the "
     "radius with the pencil, then turn the top to draw. Lock the radius to draw the matching arc from the other point - "
     "perpendicular bisectors, angle bisectors and triangles from three sides come out exact."),
    ("Does it work with an iPad, Apple Pencil or a drawing tablet?",
     "Yes. Pens follow pressure, and once a stylus has been used your finger scrolls instead of drawing, so your palm "
     "never leaves marks."),
    ("Can I put a past-paper question on the board?",
     "Yes. In a topical paper press the Whiteboard button beside any question and it opens on a fresh squared board. "
     "You can also paste a screenshot with Ctrl+V or drop in a photo."),
    ("How do I share a board with my teacher?",
     "Use Share on the board: turn on Send to my teacher, or make a view-only link. You can also download the board as a "
     "PDF and send that."),
]


def _landing(user: dict | None = None) -> str:
    import catalog as _catalog
    import ui
    feats = [("✏️", "Real pens", "Pen, fineliner, fountain pen, pencil and highlighter, with pressure on a stylus."),
             ("📐", "Ruler, protractor, compass", "At true scale. The compass snaps to points so constructions come out exact."),
             ("🔷", "Shapes that snap", "Draw a rough circle or triangle, hold still, and it turns neat. 16 shapes besides."),
             ("🖼️", "Paste anything", "Ctrl+V a screenshot, drop in a photo, or send a past-paper question straight to a page."),
             ("📓", "Every kind of paper", "Plain, lined, squared, graph, dotted, isometric, Cornell - light or chalkboard."),
             ("♾️", "Pages or infinite canvas", "A notebook of A4 pages, or one endless canvas you pan and zoom."),
             ("⭐", "Stickers & stamps", "Good work!, stars, ticks and crosses for marking, sticky notes for reminders."),
             ("📄", "Export to PDF", "Download any board as a clean PDF to print, revise from or hand in."),
             ("👩‍🏫", "Made for lessons", "Present mode with a laser pointer, share links, and boards students send their teacher.")]
    cards = "".join(f'<div class="wbl-card"><span class="wbl-ic" aria-hidden="true">{i}</span><h3>{_e(t)}</h3><p>{_e(d)}</p></div>'
                    for i, t, d in feats)
    uses = ui.steps([
        ("Constructions", "Bisect angles and lines, construct triangles and scale drawings with the compass and ruler."),
        ("Transformations & graphs", "Reflect, rotate and enlarge on squared or graph paper; sketch curves to scale."),
        ("Physics diagrams", "Ray diagrams, circuits and forces with straight edges, arrows and a protractor."),
        ("Algorithms & trace tables", "Draw flowcharts and trace tables for Computer Science, with neat boxes and arrows."),
        ("Revision notes", "Cornell notes, mind maps on the infinite canvas, sticky notes for what to remember."),
    ], title="What students use it for")
    faq_html, faq_ld = ui.faq(WB_FAQ, "Questions about the whiteboard")
    app_ld = {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "PrepWithTee Board",
              "applicationCategory": "EducationalApplication", "operatingSystem": "Web browser",
              "url": "https://prepwithtee.com/whiteboard",
              "description": "An online whiteboard for O Level, IGCSE and A Level students and tutors: notebooks and an "
                             "infinite canvas, pens, shapes, a true-scale compass, ruler and protractor, stickers, images "
                             "and PDF export.",
              "offers": {"@type": "Offer", "price": "0", "priceCurrency": "PKR"}}
    cta = ('<a class="wbl-btn" href="/whiteboard">Open my boards</a>' if user else
           '<a class="wbl-btn" href="/login.html?next=/whiteboard">Start free - sign in</a>')
    body = f"""
  <section class="wbl-hero">
    <p class="wbl-eyebrow">PrepWithTee Board</p>
    <h1>The online whiteboard for O Level, IGCSE &amp; A Level</h1>
    <p class="wbl-lede">Notebooks and an infinite canvas for maths, physics and computer science. Draw, construct with a
       real compass, paste questions, mark with stamps and export to PDF - saved to your account, on any device.</p>
    <div class="wbl-cta">{cta}<span>3 boards free · unlimited on any plan · works with Apple Pencil &amp; tablets</span></div>
  </section>
  <section class="wbl-grid">{cards}</section>
  {uses}
  {faq_html}"""
    return _catalog._shell(title="Online Whiteboard for Students - Compass, Graph Paper & PDF | PrepWithTee",
                           desc="A free online whiteboard for O Level, IGCSE and A Level: lined, squared and graph paper "
                                "or an infinite canvas, pens, shapes, a true-scale compass and protractor, stickers, "
                                "pasted images and PDF export.",
                           path="/whiteboard", body=body, state=_catalog._student_state(user),
                           crumbs=[("Home", "/"), ("Tools", "/tools.html"), ("Whiteboard", "/whiteboard")],
                           ld=[app_ld, faq_ld], styles=(f"/board/boards.css?v={WB_V}",))


@router.get("/whiteboard/new", include_in_schema=False)
def whiteboard_new(template: str = "blank", q: int | None = None, title: str = "",
                   user: dict | None = Depends(_auth.maybe_user)):
    if not user:
        nxt = "/whiteboard/new" + (f"?q={q}" if q else f"?template={template}")
        return RedirectResponse(f"/login.html?next={nxt}", 302)
    try:
        _room_for_board(user)
    except HTTPException:
        return RedirectResponse("/whiteboard?full=1", 302)
    if q and template == "blank":
        template = "squared"
    b = _make_board(user, title or ("Question workings" if q else ""), template if template in TEMPLATES else "blank")
    return RedirectResponse(f"/whiteboard/{b['id']}" + (f"?insertq={q}" if q else ""), 302)


def _editor(state: dict, title: str) -> HTMLResponse:
    page = _head(f"{title} — PrepWithTee Board",
                 extra=f'<link rel="stylesheet" href="/annotate.css?v={WB_V}">'
                       f'<link rel="stylesheet" href="/board/board.css?v={WB_V}">') + f"""
<body class="wb-page" data-no-scratch>
<div id="wb" class="wb" data-state="loading"><p class="wb-loading">Opening your board…</p></div>
<script id="wb-state" type="application/json">{_state(state)}</script>
<script type="module" src="/board/app.js?v={WB_V}"></script>
</body>
</html>"""
    return HTMLResponse(page, headers={"Cache-Control": "private, no-store"})


@router.get("/whiteboard/s/{token}", include_in_schema=False)
def whiteboard_shared(token: str, user: dict | None = Depends(_auth.maybe_user)):
    try:
        sh, b = _share_or_404(token)
    except HTTPException as e:
        return HTMLResponse(_head("Board not available") + f'<body class="wbd-page"><main class="wbl"><section class="wbl-hero">'
                            f'<h1>{_e(e.detail)}</h1><p class="wbl-lede">Ask the person who sent it for a new link.</p>'
                            f'<p><a class="wbl-btn" href="/whiteboard">Go to PrepWithTee Board</a></p></section></main></body></html>',
                            status_code=404)
    return _editor({"board": b["id"], "share": token, "role": sh["role"], "signedIn": bool(user),
                    "v": WB_V}, b["title"])


@router.get("/whiteboard/{board_id}", include_in_schema=False)
def whiteboard_editor(board_id: str, request: Request, user: dict | None = Depends(_auth.maybe_user)):
    if not user:
        return RedirectResponse(f"/login.html?next=/whiteboard/{board_id}", 302)
    try:
        b = _board_for(user, board_id)
    except HTTPException:
        return RedirectResponse("/whiteboard?missing=1", 302)
    lim = _limits(user)
    return _editor({"board": b["id"], "me": {"id": user["id"], "role": user.get("role") or "student"},
                    "mine": b["owner_id"] == user["id"], "pdfImport": lim["pdf_import"],
                    "insertq": request.query_params.get("insertq"), "v": WB_V}, b["title"])
