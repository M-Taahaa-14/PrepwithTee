"""Blog — server-rendered public pages and shared DB helpers.

Public routes (registered in app.py):
  GET /blog         — published posts list (full HTML, SEO-ready)
  GET /blog/{slug}  — single post (full HTML, SEO-ready)

Admin CRUD lives in admin.py and calls the helpers defined here.
"""

import html as _html
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from . import db as _db

router = APIRouter()

_SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://prepwithtee.com").rstrip("/")
_CSS_V = "20260822a"  # keep in sync with styles.css version pin


# ── Markdown ──────────────────────────────────────────────────────────────────

try:
    import markdown as _md_lib
    def _md(text: str) -> str:
        return _md_lib.markdown(text, extensions=["extra", "toc", "sane_lists"])
except ImportError:
    def _md(text: str) -> str:
        """Minimal fallback when the markdown package is not installed."""
        t = _html.escape(text)
        t = re.sub(r"^### (.+)$", r"<h3>\1</h3>", t, flags=re.M)
        t = re.sub(r"^## (.+)$",  r"<h2>\1</h2>", t, flags=re.M)
        t = re.sub(r"^# (.+)$",   r"<h1>\1</h1>", t, flags=re.M)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         t)
        t = re.sub(r"\n\n+", "</p><p>", t)
        return f"<p>{t}</p>"


# ── DB helpers ────────────────────────────────────────────────────────────────

_TABLE_ENSURED = False


def _con():
    return _db.plain_connect()


def ensure_table():
    """Create blog_posts if not present.

    In Supabase (Postgres) mode, the table is created via schema.sql;
    this call is a cheap no-op after the first run. In SQLite (local dev)
    it creates the table on demand.
    """
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    con = _con()
    try:
        if _db.USE_PG:
            con.execute("""
                CREATE TABLE IF NOT EXISTS blog_posts (
                    id            BIGSERIAL PRIMARY KEY,
                    title         TEXT NOT NULL,
                    slug          TEXT UNIQUE NOT NULL,
                    excerpt       TEXT,
                    body_markdown TEXT NOT NULL DEFAULT '',
                    cover_url     TEXT,
                    author        TEXT NOT NULL DEFAULT 'Muhammad Taahaa',
                    published     BOOLEAN NOT NULL DEFAULT FALSE,
                    published_at  TEXT,
                    meta_title    TEXT,
                    meta_desc     TEXT,
                    created_at    TEXT NOT NULL DEFAULT (now()::text),
                    updated_at    TEXT NOT NULL DEFAULT (now()::text)
                )
            """)
        else:
            con.execute("""
                CREATE TABLE IF NOT EXISTS blog_posts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    title         TEXT NOT NULL,
                    slug          TEXT UNIQUE NOT NULL,
                    excerpt       TEXT,
                    body_markdown TEXT NOT NULL DEFAULT '',
                    cover_url     TEXT,
                    author        TEXT NOT NULL DEFAULT 'Muhammad Taahaa',
                    published     INTEGER NOT NULL DEFAULT 0,
                    published_at  TEXT,
                    meta_title    TEXT,
                    meta_desc     TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
        con.commit()
        _TABLE_ENSURED = True
    finally:
        con.close()


def get_published_posts() -> list[dict]:
    ensure_table()
    con = _con()
    try:
        rows = con.execute(
            """SELECT id, title, slug, excerpt, cover_url, author,
                      published_at, created_at
               FROM blog_posts WHERE published
               ORDER BY COALESCE(published_at, created_at) DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_post_by_slug(slug: str) -> dict | None:
    ensure_table()
    con = _con()
    try:
        row = con.execute(
            "SELECT * FROM blog_posts WHERE slug = ? AND published",
            (slug,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def get_all_posts_admin() -> list[dict]:
    ensure_table()
    con = _con()
    try:
        rows = con.execute(
            """SELECT id, title, slug, excerpt, cover_url, author,
                      published, published_at, meta_title, meta_desc,
                      body_markdown, created_at, updated_at
               FROM blog_posts
               ORDER BY COALESCE(updated_at, created_at) DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_date(s) -> str:
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.strftime("%d %B %Y").lstrip("0")
    except Exception:
        return str(s)[:10]


def _nav() -> str:
    return """<header class="site-header">
  <div class="container header-row">
    <a class="brand" href="/">
      <img src="/logo.png" alt="PrepWithTee owl logo">
      <span>PrepWithTee</span>
    </a>
    <nav class="header-nav" style="gap:.5rem">
      <a href="/blog" class="nav-link" style="font-weight:600">Blog</a>
      <a href="/papers.html" class="nav-link">Past Papers</a>
      <a href="/resources.html" class="nav-link">Notes</a>
      <a href="/pricing.html" class="nav-link">Pricing</a>
      <a href="/#contact" class="btn btn-dark"
         style="padding:.45rem .9rem;font-size:.875rem">Book a demo</a>
    </nav>
  </div>
</header>"""


def _foot() -> str:
    return """<footer class="site-footer" style="margin-top:4rem">
  <div class="container footer-bottom"
       style="padding-top:1.25rem;padding-bottom:1.25rem;display:flex;
              flex-wrap:wrap;gap:.5rem 1.5rem;align-items:center;
              justify-content:space-between">
    <a class="footer-brand" href="/" style="text-decoration:none">
      <img src="/logo.png" alt=""
           style="height:26px;vertical-align:middle;margin-right:6px">
      <span style="font-weight:700;color:#fff">PrepWithTee</span>
    </a>
    <nav style="display:flex;flex-wrap:wrap;gap:.5rem 1.25rem">
      <a href="/blog"          style="color:#9ca3af;font-size:.82rem;text-decoration:none">Blog</a>
      <a href="/papers.html"   style="color:#9ca3af;font-size:.82rem;text-decoration:none">Past Papers</a>
      <a href="/subjects.html" style="color:#9ca3af;font-size:.82rem;text-decoration:none">Subjects</a>
      <a href="/pricing.html"  style="color:#9ca3af;font-size:.82rem;text-decoration:none">Pricing</a>
      <a href="/privacy.html"  style="color:#9ca3af;font-size:.82rem;text-decoration:none">Privacy</a>
      <a href="/terms.html"    style="color:#9ca3af;font-size:.82rem;text-decoration:none">Terms</a>
    </nav>
    <p style="color:#6b7280;font-size:.78rem;margin:0">&copy; 2026 PrepWithTee</p>
  </div>
</footer>"""


_BLOG_CSS = """
.bwrap{max-width:780px;margin:0 auto;padding:2.5rem 1.25rem 5rem}
.blist{display:grid;gap:1.75rem;margin-top:2.5rem}
.bcard{border:1px solid var(--border,#e5e7eb);border-radius:14px;overflow:hidden;
       transition:box-shadow .15s;text-decoration:none;color:inherit;display:block}
.bcard:hover{box-shadow:0 4px 24px rgba(0,0,0,.1)}
.bcard img{width:100%;aspect-ratio:16/7;object-fit:cover;display:block}
.bcbd{padding:1.4rem}
.bcmeta{font-size:.78rem;color:var(--muted,#6b7280);margin:0 0 .4rem}
.bctitle{font-size:1.2rem;font-weight:700;line-height:1.3;margin:0 0 .5rem;
         color:var(--heading,#111827)}
.bcex{color:var(--muted,#6b7280);font-size:.875rem;line-height:1.6;margin:0 0 .9rem}
.bclink{font-weight:600;font-size:.82rem;color:var(--gold,#c9a227)}
.phd{margin-bottom:2.25rem;border-bottom:1px solid var(--border,#e5e7eb);padding-bottom:1.5rem}
.peye{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;
      color:var(--muted,#6b7280);margin:0 0 .6rem}
.ptitle{font-size:clamp(1.7rem,4vw,2.4rem);font-weight:800;line-height:1.2;margin:0 0 .9rem}
.pmeta{font-size:.82rem;color:var(--muted,#6b7280);margin:0}
.pcover{width:100%;border-radius:12px;margin-bottom:2rem}
.pbody{line-height:1.85;font-size:1.03rem}
.pbody h2{font-size:1.45rem;font-weight:700;margin:2.25rem 0 .65rem}
.pbody h3{font-size:1.15rem;font-weight:700;margin:1.75rem 0 .45rem}
.pbody p{margin:0 0 1.2rem}
.pbody ul,.pbody ol{margin:0 0 1.2rem;padding-left:1.5rem}
.pbody li{margin-bottom:.35rem}
.pbody blockquote{border-left:3px solid var(--gold,#c9a227);padding:.5rem 1rem;
                  margin:1.5rem 0;color:var(--muted,#6b7280);font-style:italic}
.pbody code{background:var(--surface2,#f3f4f6);padding:.15em .35em;
            border-radius:4px;font-size:.87em;font-family:monospace}
.pbody pre{background:var(--surface2,#f3f4f6);padding:1rem 1.25rem;
           border-radius:8px;overflow-x:auto;margin:0 0 1.2rem}
.pbody pre code{background:none;padding:0}
.pbody a{color:var(--gold,#c9a227);text-decoration:underline}
.pback{display:inline-flex;align-items:center;gap:.3rem;font-size:.875rem;
       font-weight:600;color:var(--muted,#6b7280);text-decoration:none;margin-bottom:2rem}
.pback:hover{color:var(--gold,#c9a227)}
@media(max-width:640px){.blist{gap:1.1rem}.bcbd{padding:1rem}}
"""


def _page(*, title: str, desc: str, path: str, body: str,
          og_image: str = "", og_type: str = "website",
          ld_json: dict | None = None) -> str:
    canonical = f"{_SITE_ORIGIN}{path}"
    og_img    = og_image or f"{_SITE_ORIGIN}/logo.png"
    ld = (f'<script type="application/ld+json">{json.dumps(ld_json, ensure_ascii=False)}</script>'
          if ld_json else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_html.escape(title)}</title>
  <meta name="description" content="{_html.escape(desc)}">
  <link rel="canonical" href="{_html.escape(canonical)}">
  <meta property="og:type"        content="{og_type}">
  <meta property="og:title"       content="{_html.escape(title)}">
  <meta property="og:description" content="{_html.escape(desc)}">
  <meta property="og:image"       content="{_html.escape(og_img)}">
  <meta property="og:url"         content="{_html.escape(canonical)}">
  <meta name="twitter:card"       content="summary_large_image">
  {ld}
  <link rel="icon" href="/logo.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;0,900;1,600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_CSS_V}">
  <style>{_BLOG_CSS}</style>
</head>
<body>
{_nav()}
<main class="bwrap">{body}</main>
{_foot()}
</body>
</html>"""


# ── Public routes ─────────────────────────────────────────────────────────────

@router.get("/blog", response_class=HTMLResponse)
def blog_list():
    posts = get_published_posts()
    if posts:
        cards = []
        for p in posts:
            cover = (
                f'<img src="{_html.escape(p["cover_url"])}" '
                f'alt="{_html.escape(p["title"])}" loading="lazy">'
                if p.get("cover_url") else ""
            )
            date = _fmt_date(p.get("published_at") or p.get("created_at"))
            ex   = _html.escape(p.get("excerpt") or "")
            ex_p = f'<p class="bcex">{ex}</p>' if ex else ""
            cards.append(
                f'<a class="bcard" href="/blog/{_html.escape(p["slug"])}">'
                f'{cover}'
                f'<div class="bcbd">'
                f'<p class="bcmeta">{date}'
                f' &middot; {_html.escape(p.get("author") or "Muhammad Taahaa")}</p>'
                f'<p class="bctitle">{_html.escape(p["title"])}</p>'
                f'{ex_p}'
                f'<span class="bclink">Read more →</span>'
                f'</div></a>'
            )
        body = (
            '<h1 style="font-size:clamp(1.7rem,4vw,2.4rem);font-weight:800;margin:0 0 .4rem">'
            'Cambridge Exam Tips &amp; Study Guides</h1>'
            '<p style="color:var(--muted,#6b7280);margin:0 0 .25rem">Study techniques, '
            'topic breakdowns and exam insights from PrepWithTee.</p>'
            f'<div class="blist">{"".join(cards)}</div>'
        )
    else:
        body = (
            '<h1 style="font-size:2rem;font-weight:800;margin:0 0 1rem">Blog</h1>'
            '<p style="color:var(--muted,#6b7280)">No posts yet — check back soon.</p>'
        )

    return _page(
        title="Cambridge Exam Tips & Study Guides | PrepWithTee Blog",
        desc=("Study techniques, topic breakdowns and Cambridge O Level, IGCSE "
              "& A Level exam tips from PrepWithTee tutors."),
        path="/blog",
        body=body,
    )


@router.get("/blog/{slug}", response_class=HTMLResponse)
def blog_post(slug: str):
    if not re.match(r"^[a-z0-9-]{1,120}$", slug):
        raise HTTPException(404, "post not found")
    post = get_post_by_slug(slug)
    if post is None:
        raise HTTPException(404, "post not found")

    content_html = _md(post.get("body_markdown") or "")
    date  = _fmt_date(post.get("published_at") or post.get("created_at"))
    cover = (
        f'<img class="pcover" src="{_html.escape(post["cover_url"])}" '
        f'alt="{_html.escape(post["title"])}" loading="eager">'
        if post.get("cover_url") else ""
    )

    ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post["title"],
        "description": post.get("excerpt") or "",
        "author": {"@type": "Person",
                   "name": post.get("author") or "Muhammad Taahaa"},
        "datePublished": str(post.get("published_at") or post.get("created_at") or ""),
        "dateModified":  str(post.get("updated_at") or ""),
        "image": post.get("cover_url") or f"{_SITE_ORIGIN}/logo.png",
        "publisher": {
            "@type": "Organization", "name": "PrepWithTee",
            "logo": {"@type": "ImageObject",
                     "url": f"{_SITE_ORIGIN}/logo.png"},
        },
        "url": f"{_SITE_ORIGIN}/blog/{post['slug']}",
    }

    body = (
        '<a class="pback" href="/blog">← All posts</a>'
        '<header class="phd">'
        '<p class="peye">PrepWithTee Blog</p>'
        f'<h1 class="ptitle">{_html.escape(post["title"])}</h1>'
        f'<p class="pmeta">{date}'
        f' &middot; {_html.escape(post.get("author") or "Muhammad Taahaa")}</p>'
        '</header>'
        f'{cover}'
        f'<div class="pbody">{content_html}</div>'
    )

    return _page(
        title=post.get("meta_title") or f"{post['title']} | PrepWithTee",
        desc=post.get("meta_desc") or post.get("excerpt") or post["title"],
        path=f"/blog/{slug}",
        og_type="article",
        og_image=post.get("cover_url") or "",
        ld_json=ld,
        body=body,
    )
