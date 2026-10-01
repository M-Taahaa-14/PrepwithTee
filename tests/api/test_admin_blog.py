"""Phase 4: AI writing (provider fallback, JSON validation), the blog studio
(posts, revisions, scheduling, public page), course AI + server-side course
meta, newsletter drafts, post ideas. No real model is ever called."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

KEY = {"X-Admin-Key": "test-admin-key"}


class FakeAI:
    """Stands in for ai_providers.call; answers by task, records who was asked."""

    def __init__(self, replies=None, limited=()):
        self.asked, self.replies, self.limited = [], replies or {}, set(limited)

    def __call__(self, name, messages, max_tokens=None, temperature=0.2):
        from pipeline import ai_providers
        self.asked.append(name)
        if name in self.limited:
            raise ai_providers.RateLimited(30, False)
        system = messages[0]["content"]
        for key, reply in self.replies.items():
            if key in system:
                text = reply(len(self.asked)) if callable(reply) else reply
                return text, {}, f"{name}:fake", {}
        return "{}", {}, f"{name}:fake", {}


OUTLINE = json.dumps({"title": "Score an A* in Physics P2", "angle": "practical",
                      "sections": [{"h2": "Know the command words", "points": ["explain", "state"]},
                                   {"h2": "Use the mark scheme", "points": ["checklist"]}]})
DRAFT = json.dumps({"body_markdown": "## Know the command words\n\nText with [booklets](/papers/topical).",
                    "excerpt": "How to score.", "slug": "Score An A* Physics!", "meta_title": "Score an A*",
                    "meta_desc": "x" * 150, "faq": [{"q": "Is P2 hard?", "a": "Not with practice."}, {"bad": 1}]})
REPLIES = {"Plan a blog post": OUTLINE, "Write the full blog post": DRAFT,
           "You edit one part": json.dumps({"replacement": "Better sentence."}),
           "landing page for one course": json.dumps({
               "tagline": "Physics that makes sense", "what_you_get": ["a", "b", "c", "d", "e"],
               "overview_html": '<p onclick="x()">Good <script>bad()</script><a href="javascript:x">link</a></p>',
               "approach_html": "<p>Weekly classes</p>", "faq": [{"q": "When?", "a": "Weekends"}],
               "meta_title": "O Level Physics 5054", "meta_description": "y" * 150}),
           "newsletter email": json.dumps({"subject": "This week", "body_markdown": "Hi!\n\nTee",
                                           "cta_label": "Practise", "cta_url": "javascript:alert(1)"}),
           "blog post idea": json.dumps({"ideas": [{"title": "Polished", "angle": "a"}]})}


@pytest.fixture()
def ai(monkeypatch):
    import content_ai
    from pipeline import ai_providers
    fake = FakeAI(REPLIES)
    monkeypatch.setattr(content_ai, "providers", lambda: ["mistral", "nvidia"])
    monkeypatch.setattr(ai_providers, "call", fake)
    return fake


# ── the generation core ──────────────────────────────────────────────────────

def test_fallback_retry_and_failure(monkeypatch):
    import content_ai
    monkeypatch.setattr(content_ai, "providers", lambda: ["mistral", "nvidia", "gemini"])
    schema = {"replacement": ("str", True)}
    # rate-limited first provider -> next one
    fake = FakeAI({"edit": json.dumps({"replacement": "ok"})}, limited={"mistral"})
    data, model = content_ai.generate("edit", "x", schema, call=fake)
    assert data == {"replacement": "ok"} and model == "nvidia:fake" and fake.asked == ["mistral", "nvidia"]
    # bad JSON once -> retried on the same provider with the error
    fake = FakeAI({"edit": lambda n: "not json" if n == 1 else '```json\n{"replacement": "fixed"}\n```'})
    assert content_ai.generate("edit", "x", schema, call=fake)[0]["replacement"] == "fixed"
    assert fake.asked == ["mistral", "mistral"]
    # nobody can answer -> one clear error
    fake = FakeAI({}, limited={"mistral", "nvidia", "gemini"})
    with pytest.raises(content_ai.AIUnavailable):
        content_ai.generate("edit", "x", schema, call=fake)
    monkeypatch.setattr(content_ai, "providers", lambda: [])
    with pytest.raises(content_ai.AIUnavailable, match="No AI provider"):
        content_ai.generate("edit", "x", schema, call=fake)


def test_never_uses_the_photo_solver_budget(monkeypatch):
    import content_ai
    from pipeline import ai_providers
    monkeypatch.setattr(ai_providers, "configured", lambda purpose=None: ["groq", "mistral"])
    assert content_ai.providers() == ["mistral"]


def test_clean_html():
    import content_ai
    out = content_ai.clean_html('<p class="x" onclick="y()">Hi <script>evil()</script>'
                                '<a href="https://prepwithtee.com/papers" target="_blank">ok</a>'
                                '<a href="javascript:alert(1)">no</a><iframe src="x"></iframe></p>')
    assert out == '<p>Hi <a href="https://prepwithtee.com/papers">ok</a><a>no</a></p>'


def test_prompts_carry_facts_and_real_links(ai):
    import content_ai
    content_ai.blog_outline("A* tips", "students", "5054", None, 900, None, call=ai)
    # the fake saw the system prompt; check the grounding text directly
    ctx = content_ai._context("students", "5054")
    assert "PKR 1,000" in ctx and "do NOT invent" in ctx and "/papers" in ctx


# ── blog studio ──────────────────────────────────────────────────────────────

def test_ai_outline_draft_edit_routes(client, ai):
    r = client.post("/api/admin/blog/ai/outline", headers=KEY, json={"prompt": "A* tips for P2", "subject": "5054"})
    assert r.status_code == 200, r.text
    outline = r.json()["outline"]
    assert len(outline["sections"]) == 2
    r = client.post("/api/admin/blog/ai/draft", headers=KEY, json={"prompt": "x", "outline": outline})
    d = r.json()["draft"]
    assert d["slug"] == "score-an-a-physics" and d["faq"] == [{"q": "Is P2 hard?", "a": "Not with practice."}]
    assert d["title"] == "Score an A* in Physics P2"
    r = client.post("/api/admin/blog/ai/edit", headers=KEY, json={"action": "simplify", "selection": "Hard text."})
    assert r.json()["replacement"] == "Better sentence."
    assert client.post("/api/admin/blog/ai/edit", headers=KEY,
                       json={"action": "delete_site", "selection": "x"}).status_code == 400


def test_ai_unavailable_is_503(client, monkeypatch):
    import content_ai
    monkeypatch.setattr(content_ai, "providers", lambda: [])
    r = client.post("/api/admin/blog/ai/outline", headers=KEY, json={"prompt": "A* tips for P2"})
    assert r.status_code == 503 and "No AI provider" in r.json()["detail"]


def _new_post(client, **kw):
    r = client.post("/api/admin/blog/posts", headers=KEY, json={"title": "Test post", **kw})
    assert r.status_code == 200, r.text
    return r.json()["post"]


def test_posts_revisions_and_slugs(client):
    a = _new_post(client, slug=f"t-{uuid.uuid4().hex[:6]}", body_markdown="First")
    b = _new_post(client, slug=a["slug"])
    assert b["slug"] == f"{a['slug']}-2"                         # never clobbers another post
    assert client.patch(f"/api/admin/blog/posts/{b['id']}", headers=KEY, json={"slug": a["slug"]}).status_code == 409
    assert client.patch(f"/api/admin/blog/posts/{a['id']}", headers=KEY, json={"slug": "Bad Slug!"}).status_code == 400
    client.patch(f"/api/admin/blog/posts/{a['id']}", headers=KEY,
                 json={"body_markdown": "Second", "faq": [{"q": "Q?", "a": "A."}], "source": "ai:mistral:x"})
    d = client.get(f"/api/admin/blog/posts/{a['id']}", headers=KEY).json()
    assert d["post"]["body_markdown"] == "Second" and d["post"]["faq"] == [{"q": "Q?", "a": "A."}]
    sources = [r["source"] for r in d["revisions"]]
    assert sources[:2] == ["ai:mistral:x", "manual"]
    first = d["revisions"][-1]["id"]
    r = client.post(f"/api/admin/blog/posts/{a['id']}/revisions/{first}/restore", headers=KEY)
    assert r.json()["post"]["body_markdown"] == "First"
    assert client.delete(f"/api/admin/blog/posts/{b['id']}", headers=KEY).status_code == 200
    assert client.get(f"/api/admin/blog/posts/{b['id']}", headers=KEY).status_code == 404


def test_schedule_publish_and_public_page(client):
    import blog
    slug = f"sched-{uuid.uuid4().hex[:6]}"
    p = _new_post(client, slug=slug, body_markdown="## Hello\n\nBody", faq=[{"q": "Why?", "a": "Because."}])
    path = f"/api/admin/blog/posts/{p['id']}/publish"
    assert client.post(path, headers=KEY, json={"action": "schedule",
                                                "publish_at": "2001-01-01T00:00:00Z"}).status_code == 400
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    r = client.post(path, headers=KEY, json={"action": "schedule", "publish_at": soon})
    assert r.json()["post"]["state"] == "scheduled"
    assert client.get(f"/blog/{slug}").status_code == 404          # not live yet
    later = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    assert blog.publish_due(later) >= 1
    page = client.get(f"/blog/{slug}")
    assert page.status_code == 200 and "FAQPage" in page.text and "Because." in page.text
    r = client.post(path, headers=KEY, json={"action": "unpublish"})
    assert r.json()["post"]["state"] == "draft" and client.get(f"/blog/{slug}").status_code == 404
    empty = _new_post(client, slug=f"e-{uuid.uuid4().hex[:6]}")
    assert client.post(f"/api/admin/blog/posts/{empty['id']}/publish", headers=KEY,
                       json={"action": "publish"}).status_code == 400


def test_ideas_from_site_data(client, ai):
    import users_db
    for _ in range(2):
        users_db._insert("subject_requests", {"subject": "Biology", "board": "IGCSE"}, ["subject", "board"])
    d = client.get("/api/admin/blog/ideas", headers=KEY).json()
    assert any("Biology" in i["why"] for i in d["ideas"])
    d = client.get("/api/admin/blog/ideas", headers=KEY, params={"polish": True}).json()
    assert d["ideas"][0]["title"] == "Polished"


# ── courses + newsletter ─────────────────────────────────────────────────────

def test_course_ai_and_server_side_meta(client, ai):
    r = client.post("/api/admin/courses/ai", headers=KEY,
                    json={"syllabus_code": "5054", "level": "O Level", "title": "O Level Physics 5054"})
    f = r.json()["fields"]
    assert "<script" not in f["overview_html"] and "onclick" not in f["overview_html"]
    assert 'href="javascript' not in f["overview_html"]
    r = client.post("/api/admin/courses/ai", headers=KEY, json={"syllabus_code": "5054", "level": "O Level",
                                                                "title": "x", "field": "tagline"})
    assert list(r.json()["fields"]) == ["tagline"]
    assert client.post("/api/admin/courses/ai", headers=KEY, json={"syllabus_code": "5054", "level": "O Level",
                                                                   "title": "x", "field": "password"}).status_code == 400
    slug = f"o-level-physics-{uuid.uuid4().hex[:5]}"
    r = client.post("/api/admin/courses", headers=KEY, json={
        "syllabus_code": "5054", "slug": slug, "title": "O Level Physics", "level": "O Level",
        "subject": "Physics", "meta_title": "Physics </script> tuition", "meta_description": "Best </script> physics",
        "published": True, "faq_json": json.dumps([{"q": "When?", "a": "Weekends"}])})
    assert r.status_code == 200, r.text
    page = client.get(f"/course.html?slug={slug}").text
    assert "<title id=\"page-title\">Physics &lt;/script&gt; tuition</title>" in page
    assert '"@type": "Course"' in page and "FAQPage" in page and "<\\/script>" in page
    assert "canonical" in page
    plain = client.get("/course.html?slug=nope").text
    assert "Course" in plain and "FAQPage" not in plain


def test_newsletter_ai(client, ai):
    r = client.post("/api/admin/newsletter/ai", headers=KEY, json={"prompt": "exam season"})
    d = r.json()["draft"]
    assert d["subject"] == "This week" and d["cta_url"] == ""      # unsafe link dropped
