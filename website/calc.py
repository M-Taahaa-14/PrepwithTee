"""The scientific calculator's memory and history, saved per account (P2-c).

    GET    /api/calc               {mem, ans, vars, deg, history}
    POST   /api/calc/history       add one calculation {q, a}   -> {history}
    DELETE /api/calc/history       clear the history
    PUT    /api/calc/state         memory / Ans / variables / DEG-RAD (partial update)
    POST   /api/calc/merge         a guest's localStorage copy, merged in at sign-in

History is newest first, capped at 200. Entries are appended one at a time on
the server, so two open devices never overwrite each other's calculations.
Guests use the same shape in localStorage (tools-calculator.js).
"""

import math
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

import auth as _auth
import users_db as _udb

router = APIRouter()

MAX = _udb.CALC_HISTORY_MAX
VAR_NAMES = ("A", "B", "C", "D", "E", "F")


def _num(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


class Entry(BaseModel):
    q: str
    a: str
    t: float | None = None           # ms since epoch (client clock)

    @field_validator("q", "a")
    @classmethod
    def _short(cls, v):
        v = v.strip()
        if not v or len(v) > 300:
            raise ValueError("1-300 characters")
        return v


class StateReq(BaseModel):
    mem: float | None = None
    ans: float | None = None
    deg: bool | None = None
    vars: dict[str, float] | None = None


class MergeReq(StateReq):
    history: list[Entry] = []


def _vars(v: dict | None) -> dict:
    return {k: _num(x) for k, x in (v or {}).items() if k in VAR_NAMES}


def _entry(e: Entry) -> dict:
    return {"q": e.q, "a": e.a, "t": e.t or time.time() * 1000}


@router.get("/api/calc")
def get_calc(user: dict = Depends(_auth.get_current_user)):
    return _udb.get_calc(user["id"])


@router.post("/api/calc/history")
def add_history(e: Entry, user: dict = Depends(_auth.get_current_user)):
    st = _udb.get_calc(user["id"])
    st["history"] = [_entry(e)] + st["history"]
    return {"history": _udb.set_calc(user["id"], st)["history"]}


@router.delete("/api/calc/history")
def clear_history(user: dict = Depends(_auth.get_current_user)):
    st = _udb.get_calc(user["id"])
    st["history"] = []
    _udb.set_calc(user["id"], st)
    return {"history": []}


@router.put("/api/calc/state")
def put_state(req: StateReq, user: dict = Depends(_auth.get_current_user)):
    st = _udb.get_calc(user["id"])
    if req.mem is not None:
        st["mem"] = _num(req.mem)
    if req.ans is not None:
        st["ans"] = _num(req.ans)
    if req.deg is not None:
        st["deg"] = req.deg
    if req.vars is not None:
        st["vars"] = _vars(req.vars)
    row = _udb.set_calc(user["id"], st)
    return {k: row[k] for k in ("mem", "ans", "vars", "deg")}


@router.post("/api/calc/merge")
def merge(req: MergeReq, user: dict = Depends(_auth.get_current_user)):
    """Fold a guest's calculator into the account: history interleaved by time
    (duplicates dropped), memory/variables only where the account has none."""
    st = _udb.get_calc(user["id"])
    seen = {(h.get("q"), h.get("a"), h.get("t")) for h in st["history"]}
    extra = [_entry(e) for e in req.history[:MAX] if (e.q, e.a, e.t) not in seen]
    st["history"] = sorted(st["history"] + extra, key=lambda h: -(h.get("t") or 0))[:MAX]
    if req.mem and not st["mem"]:
        st["mem"] = _num(req.mem)
    if req.ans and not st["ans"]:
        st["ans"] = _num(req.ans)
    st["vars"] = {**_vars(req.vars), **st["vars"]}
    return _udb.set_calc(user["id"], st)
