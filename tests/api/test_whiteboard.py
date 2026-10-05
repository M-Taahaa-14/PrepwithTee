"""PrepWithTee Board API: boards, pages (optimistic version), quota, images, sharing, export."""
import io

import fitz


def _png():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 10), 0)
    pix.clear_with(200)
    return pix.tobytes("png")


def test_board_lifecycle_quota_and_export(client, new_student):
    new_student()
    ids = [client.post("/api/wb/boards", json={"template": t}).json()["id"] for t in ("squared", "infinite", "lesson")]
    r = client.post("/api/wb/boards", json={"template": "blank"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "wb_limit"      # free = 3 boards
    b = client.get(f"/api/wb/boards/{ids[0]}").json()
    pid = b["pages"][0]["id"]
    ok = client.put(f"/api/wb/boards/{ids[0]}/pages/{pid}", json={"objects": [{"id": "a", "t": "pen", "c": "@blue", "w": .003, "pts": [[.1, .1, .5], [.2, .2, .5]]}], "version": 1})
    assert ok.json()["version"] == 2
    stale = client.put(f"/api/wb/boards/{ids[0]}/pages/{pid}", json={"objects": [], "version": 1})
    assert stale.status_code == 409 and stale.json()["objects"][0]["id"] == "a"
    client.post(f"/api/wb/boards/{ids[0]}/pages", json={"after": pid})
    pdf = client.get(f"/api/wb/boards/{ids[0]}/export.pdf")
    assert pdf.status_code == 200 and fitz.open("pdf", pdf.content).page_count == 2
    client.delete(f"/api/wb/boards/{ids[2]}")                 # trash frees a slot
    assert client.post("/api/wb/boards", json={"template": "blank"}).status_code == 200
    assert client.post(f"/api/wb/boards/{ids[2]}/restore").status_code == 403


def test_images_are_private_and_shares_work(client, new_student):
    new_student()
    bid = client.post("/api/wb/boards", json={"template": "blank"}).json()["id"]
    up = client.post("/api/ink/assets", files={"file": ("x.png", io.BytesIO(_png()), "image/png")}).json()
    assert client.get(up["url"]).status_code == 200
    assert client.post("/api/ink/assets", files={"file": ("x.png", io.BytesIO(b"not an image"), "image/png")}).status_code == 415
    tok = client.post(f"/api/wb/boards/{bid}/shares", json={"role": "view"}).json()["token"]
    client.cookies.clear()
    assert client.get(up["url"]).status_code == 404                      # a stranger
    assert client.get(f"{up['url']}?s={tok}").status_code == 200          # the share link
    assert client.get(f"/api/wb/shared/{tok}").json()["readonly"] is True
    new_student()
    assert client.get(f"/api/wb/boards/{bid}").status_code == 404        # another student
    assert client.post(f"/api/wb/shared/{tok}/copy").status_code == 403  # view-only link


def test_public_pages_are_seo_ready(client):
    r = client.get("/whiteboard")
    assert r.status_code == 200 and '"SoftwareApplication"' in r.text and '"FAQPage"' in r.text
    assert 'rel="canonical" href="https://prepwithtee.com/whiteboard"' in r.text and "noindex" not in r.text
    f = client.get("/features")
    assert f.status_code == 200 and 'href="/whiteboard"' in f.text and '"FAQPage"' in f.text
    sm = client.get("/sitemap.xml").text
    assert "/whiteboard</loc>" in sm and "/features</loc>" in sm


def test_teacher_sees_only_boards_sent_to_them(client, new_student):
    import users_db as udb
    stu = new_student()
    bid = client.post("/api/wb/boards", json={"template": "blank"}).json()["id"]
    teacher = new_student()
    udb.update_profile(teacher["id"], {"role": "teacher"})
    udb.create_allocation(teacher["id"], stu["id"], "5054")
    client.post("/auth/login", json={"email": teacher["email"], "password": teacher["password"]})
    assert client.get(f"/api/wb/boards/{bid}").status_code == 404            # not sent yet
    client.post("/auth/login", json={"email": stu["email"], "password": stu["password"]})
    client.patch(f"/api/wb/boards/{bid}", json={"shared_with_teacher": True})
    client.post("/auth/login", json={"email": teacher["email"], "password": teacher["password"]})
    b = client.get(f"/api/wb/boards/{bid}").json()
    assert b["readonly"] is True
    assert [x["id"] for x in client.get("/api/wb/students").json()["boards"]] == [bid]
    pid = b["pages"][0]["id"]
    assert client.put(f"/api/wb/boards/{bid}/pages/{pid}", json={"objects": [], "version": 1}).status_code == 404
