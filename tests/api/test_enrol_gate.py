"""Enrolling needs a finished profile: name, WhatsApp number and the subject's board."""


def test_enrol_refused_until_profile_complete(client, new_student):
    new_student(setup=False)
    st = client.get("/api/me/setup").json()
    assert not st["complete"] and "phone" in st["missing"] and "boards" in st["missing"]

    r = client.post("/api/enrollments", json={"syllabus": "5054"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "profile_incomplete"
    assert r.json()["detail"]["board"] == "o-level"
    assert client.get("/api/enrollments").json()["enrollments"] == []

    # restore is the same door
    assert client.post("/api/enrollments/5054/restore").status_code == 409


def test_setup_validates(client, new_student):
    new_student(setup=False)
    bad = [{"name": "", "phone": "+92 3001234567", "boards": ["igcse"]},
           {"name": "Ali Khan", "phone": "123", "boards": ["igcse"]},
           {"name": "Ali Khan", "phone": "+92 3001234567", "boards": []},
           {"name": "Ali Khan", "phone": "+92 3001234567", "boards": ["mars"]}]
    for body in bad:
        assert client.post("/api/me/setup", json=body).status_code == 422, body


def test_board_must_match_subject(client, new_student):
    new_student(setup=False)
    r = client.post("/api/me/setup", json={"name": "Ali Khan", "phone": "+92 300 1234567",
                                           "boards": ["igcse"]})
    assert r.status_code == 200 and r.json()["complete"]
    assert r.json()["boards"] == ["igcse"]

    assert client.post("/api/enrollments", json={"syllabus": "0625"}).status_code == 200
    r = client.post("/api/enrollments", json={"syllabus": "5054"})   # O Level subject
    assert r.status_code == 409 and r.json()["detail"]["code"] == "board_not_chosen"

    client.post("/api/me/setup", json={"name": "Ali Khan", "phone": "+92 300 1234567",
                                       "boards": ["igcse", "o-level"]})
    assert client.post("/api/enrollments", json={"syllabus": "5054"}).status_code == 200
    me = client.get("/auth/me?fresh=true").json()
    assert me["phone"] == "+92 300 1234567" and me["grade"] == "IGCSE"
    assert me["profile_complete"]


def test_guest_setup_is_quiet(client):
    r = client.get("/api/me/setup")
    assert r.status_code == 200 and r.json()["signed_in"] is False


def test_legacy_enrolled_student_is_flagged_but_keeps_subjects(client, new_student):
    import users_db
    u = new_student(setup=False)
    users_db.enroll(u["id"], "0625")                    # enrolled before the gate existed
    users_db.update_profile(u["id"], {"grade": "IGCSE"})
    st = client.get("/api/me/setup").json()
    assert not st["complete"] and st["missing"] == ["phone"]
    assert st["enrolled"] and st["boards"] == ["igcse"] and st["role"] == "student"
    client.post("/api/me/setup", json={"name": "Old Timer", "phone": "+92 3001234567",
                                       "boards": ["igcse"]})
    assert client.get("/api/me/setup").json()["complete"]
    assert [e["syllabus"] for e in client.get("/api/enrollments").json()["enrollments"]] == ["0625"]
