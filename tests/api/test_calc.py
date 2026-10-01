"""Calculator memory + history per account (P2-c)."""


def test_needs_login(client):
    assert client.get("/api/calc").status_code == 401


def test_history_memory_and_variables_round_trip(client, new_student):
    new_student()
    assert client.get("/api/calc").json() == {"mem": 0.0, "ans": 0.0, "vars": {}, "deg": True, "history": []}
    client.post("/api/calc/history", json={"q": "2+3", "a": "5", "t": 1})
    h = client.post("/api/calc/history", json={"q": "5×4", "a": "20", "t": 2}).json()["history"]
    assert [x["a"] for x in h] == ["20", "5"]                        # newest first
    r = client.put("/api/calc/state", json={"mem": 12.5, "ans": 20, "deg": False,
                                            "vars": {"A": 3, "B": -1.5, "Z": 9}}).json()
    assert r == {"mem": 12.5, "ans": 20.0, "vars": {"A": 3.0, "B": -1.5}, "deg": False}   # Z dropped
    # a partial update keeps the rest
    client.put("/api/calc/state", json={"mem": 1})
    st = client.get("/api/calc").json()
    assert st["mem"] == 1 and st["vars"] == {"A": 3.0, "B": -1.5} and st["deg"] is False
    assert len(st["history"]) == 2
    assert client.delete("/api/calc/history").json() == {"history": []}
    assert client.get("/api/calc").json()["history"] == [] and client.get("/api/calc").json()["mem"] == 1


def test_history_is_capped_at_200(client, new_student):
    new_student()
    for i in range(205):
        client.post("/api/calc/history", json={"q": f"{i}+0", "a": str(i), "t": i})
    h = client.get("/api/calc").json()["history"]
    assert len(h) == 200 and h[0]["a"] == "204" and h[-1]["a"] == "5"


def test_guest_merge_interleaves_and_keeps_account_values(client, new_student):
    new_student()
    client.post("/api/calc/history", json={"q": "1+1", "a": "2", "t": 100})
    client.put("/api/calc/state", json={"vars": {"A": 7}})
    m = client.post("/api/calc/merge", json={
        "mem": 4, "ans": 9, "vars": {"A": 1, "C": 2},
        "history": [{"q": "3×3", "a": "9", "t": 150}, {"q": "1+1", "a": "2", "t": 100},
                    {"q": "0+0", "a": "0", "t": 50}]}).json()
    assert [x["q"] for x in m["history"]] == ["3×3", "1+1", "0+0"]    # by time, duplicate dropped
    assert m["mem"] == 4 and m["vars"] == {"A": 7.0, "C": 2.0}        # account's A wins


def test_rejects_junk(client, new_student):
    new_student()
    assert client.post("/api/calc/history", json={"q": "", "a": "1"}).status_code == 422
    assert client.post("/api/calc/history", json={"q": "x" * 301, "a": "1"}).status_code == 422


def test_x_and_y_are_kept_too(client, new_student):
    """The fx-991-style keypad stores into X and Y as well as A-F (M is the memory)."""
    new_student()
    r = client.put("/api/calc/state", json={"vars": {"X": 1.5, "Y": -2, "M": 7, "Q": 1}}).json()
    assert r["vars"] == {"X": 1.5, "Y": -2.0}
