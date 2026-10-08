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

import db as _db

router = APIRouter()

_SITE_ORIGIN = os.environ.get("SITE_ORIGIN", "https://prepwithtee.com").rstrip("/")
_CSS_V = "20260930b"  # keep in sync with styles.css version pin


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
        # Admin console v2 (migration 025): scheduling, FAQ, keywords, revisions.
        if _db.USE_PG:
            for stmt in ("ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS publish_at TEXT",
                         "ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS faq_json TEXT",
                         "ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS keywords TEXT",
                         """CREATE TABLE IF NOT EXISTS blog_revisions (
                                id BIGSERIAL PRIMARY KEY, post_id BIGINT NOT NULL,
                                title TEXT, body_markdown TEXT, excerpt TEXT, meta_title TEXT,
                                meta_desc TEXT, source TEXT, created_by TEXT,
                                created_at TEXT NOT NULL DEFAULT (now()::text))"""):
                con.execute(stmt)
        else:
            for stmt in ("ALTER TABLE blog_posts ADD COLUMN publish_at TEXT",
                         "ALTER TABLE blog_posts ADD COLUMN faq_json TEXT",
                         "ALTER TABLE blog_posts ADD COLUMN keywords TEXT"):
                try:
                    con.execute(stmt)
                except Exception:
                    pass                          # already there
            con.execute("""CREATE TABLE IF NOT EXISTS blog_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL,
                title TEXT, body_markdown TEXT, excerpt TEXT, meta_title TEXT,
                meta_desc TEXT, source TEXT, created_by TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        con.commit()
        _TABLE_ENSURED = True
    finally:
        con.close()


def publish_due(now: str | None = None) -> int:
    """Publish scheduled posts whose time has come. Returns how many."""
    ensure_table()
    now = now or _now_iso()
    con = _con()
    try:
        rows = con.execute("SELECT id, publish_at FROM blog_posts WHERE NOT published "
                           "AND publish_at IS NOT NULL AND publish_at <= ?", (now,)).fetchall()
        for r in rows:
            con.execute("UPDATE blog_posts SET published = ?, published_at = ?, publish_at = NULL, "
                        "updated_at = ? WHERE id = ?",
                        (True if _db.USE_PG else 1, dict(r)["publish_at"], now, dict(r)["id"]))
        con.commit()
        return len(rows)
    finally:
        con.close()


def _publisher() -> None:
    import time as _time
    while True:
        _time.sleep(60)
        try:
            n = publish_due()
            if n:
                print(f"[blog] published {n} scheduled post(s)", flush=True)
        except Exception as exc:                 # never let the loop die
            print(f"[blog] scheduled publishing failed: {exc}", flush=True)


if os.environ.get("APP_ENV") != "test":
    import threading as _threading
    _threading.Thread(target=_publisher, name="blog-publisher", daemon=True).start()


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
                      published, published_at, publish_at, meta_title, meta_desc,
                      body_markdown, faq_json, keywords, created_at, updated_at
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


# The site navbar is a single shared partial (website/partials/nav.html), stamped
# into every static page by sync_nav.py. Blog pages are server-rendered, so we read
# the same partial here — one source of truth for the whole site. Page-relative
# links/images are rewritten to absolute so they still resolve under /blog/<slug>.
_NAV_PARTIAL = Path(__file__).resolve().parent / "partials" / "nav.html"
_NAV_HTML: str | None = None

_NAV_FALLBACK = """<header class="site-header">
  <div class="container header-row">
    <a class="brand" href="/">
      <img src="/logo.png" alt="PrepWithTee owl logo">
      <span>PrepWithTee</span>
    </a>
    <nav class="header-nav" style="gap:.5rem">
      <a href="/blog" class="nav-link" style="font-weight:600">Blog</a>
      <a href="/papers" class="nav-link">Past Papers</a>
      <a href="/resources" class="nav-link">Notes</a>
      <a href="/pricing.html" class="nav-link">Pricing</a>
      <a href="/#contact" class="btn btn-dark"
         style="padding:.45rem .9rem;font-size:.875rem">Book a demo</a>
    </nav>
  </div>
</header>"""


def _nav() -> str:
    global _NAV_HTML
    if _NAV_HTML is None:
        try:
            raw = _NAV_PARTIAL.read_text(encoding="utf-8-sig")
            # href/src that are page-relative (not absolute, protocol, #, mailto,
            # tel or data) → absolute, so they work on /blog and /blog/<slug>.
            _NAV_HTML = re.sub(
                r'(href|src)="(?!https?:|//|/|#|mailto:|tel:|data:)',
                r'\1="/', raw)
        except OSError:
            _NAV_HTML = _NAV_FALLBACK
    return _NAV_HTML


_FOOT_PARTIAL = Path(__file__).resolve().parent / "partials" / "footer.html"
_FOOT_HTML: str | None = None


def _foot() -> str:
    """The shared site footer (partials/footer.html - links are absolute)."""
    global _FOOT_HTML
    if _FOOT_HTML is None:
        try:
            _FOOT_HTML = _FOOT_PARTIAL.read_text(encoding="utf-8-sig")
        except OSError:
            _FOOT_HTML = ('<footer class="site-footer"><div class="container footer-bottom">'
                          '<span>&copy; 2026 PrepWithTee</span></div></footer>')
    return _FOOT_HTML


_BLOG_CSS = """
/* Theme-aware tokens (styles.css defines --gold, not these) so the blog matches
   the site in both light and dark. */
:root{--bl-head:#1a1a2e;--bl-muted:#6b6b7b;--bl-border:#e7e0d2;--bl-surface:#ffffff;
      --bl-code:#f3f0e8;--bl-shadow:rgba(46,27,74,.12);--bl-goldwash:rgba(232,145,58,.12)}
html[data-theme="dark"]{--bl-head:#ece7f5;--bl-muted:#a49dba;--bl-border:#2b3240;
      --bl-surface:#1b1733;--bl-code:#241f38;--bl-shadow:rgba(0,0,0,.45);
      --bl-goldwash:rgba(245,158,11,.14)}

.bwrap{max-width:780px;margin:0 auto;padding:2.5rem 1.25rem 5rem}
.bwrap-wide{max-width:1140px}

/* hero */
.bhero{text-align:center;max-width:660px;margin:0 auto 1rem}
.beyebrow{display:inline-flex;align-items:center;gap:.4rem;font-size:.72rem;font-weight:700;
          text-transform:uppercase;letter-spacing:.09em;color:var(--gold,#E8913A);
          background:var(--bl-goldwash);padding:.42rem .85rem;border-radius:999px;margin:0 0 1.1rem}
.bhtitle{font-family:'Playfair Display',Georgia,serif;font-size:clamp(2rem,5vw,3rem);
         font-weight:800;line-height:1.12;margin:0 0 .85rem;color:var(--bl-head)}
.bhsub{color:var(--bl-muted);font-size:1.05rem;line-height:1.65;margin:0 auto;max-width:560px}
.bhrule{width:56px;height:3px;background:var(--gold,#E8913A);border:none;border-radius:2px;
        margin:1.6rem auto 0}

/* cards grid */
.blist{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
       gap:1.6rem;margin-top:2.75rem}
.bcard{border:1px solid var(--bl-border);border-radius:16px;overflow:hidden;
       transition:transform .16s ease,box-shadow .16s ease;text-decoration:none;color:inherit;
       display:flex;flex-direction:column;background:var(--bl-surface)}
.bcard:hover{transform:translateY(-4px);box-shadow:0 14px 34px var(--bl-shadow)}
.bcard-cover{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}
.bcard-ph{width:100%;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;
          background:linear-gradient(135deg,#2E1B4A 0%,#4A2E8F 100%);font-size:2.6rem}
.bcbd{padding:1.35rem 1.4rem 1.5rem;display:flex;flex-direction:column;flex:1}
.bcmeta{font-size:.72rem;color:var(--bl-muted);margin:0 0 .5rem;
        text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.bctitle{font-size:1.18rem;font-weight:700;line-height:1.32;margin:0 0 .55rem;color:var(--bl-head)}
.bcex{color:var(--bl-muted);font-size:.9rem;line-height:1.6;margin:0 0 1.1rem}
.bclink{margin-top:auto;font-weight:700;font-size:.82rem;color:var(--gold,#E8913A)}

/* empty state */
.bempty{max-width:580px;margin:1rem auto 0;text-align:center;
        border:1px solid var(--bl-border);border-radius:22px;padding:3.2rem 2rem;
        background:var(--bl-surface);box-shadow:0 10px 40px var(--bl-shadow)}
.bempty-ico{font-size:3rem;line-height:1;margin-bottom:.7rem}
.bempty h2{font-size:1.45rem;font-weight:800;margin:0 0 .7rem;color:var(--bl-head)}
.bempty p{color:var(--bl-muted);line-height:1.65;margin:0 auto 1.7rem;max-width:440px}
.bempty-links{display:flex;flex-wrap:wrap;gap:.7rem;justify-content:center}
.bempty-links a{text-decoration:none;font-weight:600;font-size:.875rem;padding:.62rem 1.15rem;
                border-radius:11px;border:1px solid var(--bl-border);color:var(--bl-head);
                transition:background .15s,border-color .15s,transform .15s}
.bempty-links a:hover{border-color:var(--gold,#E8913A);background:var(--bl-goldwash);transform:translateY(-2px)}
.bempty-links a.primary{background:#2E1B4A;color:#fff;border-color:#2E1B4A}
.bempty-links a.primary:hover{background:#3D2560;border-color:#3D2560}

/* single post */
.phd{margin-bottom:2.25rem;border-bottom:1px solid var(--bl-border);padding-bottom:1.5rem}
.peye{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:var(--bl-muted);margin:0 0 .6rem}
.ptitle{font-family:'Playfair Display',Georgia,serif;font-size:clamp(1.9rem,4.5vw,2.6rem);
        font-weight:800;line-height:1.16;margin:0 0 .9rem;color:var(--bl-head)}
.pmeta{font-size:.82rem;color:var(--bl-muted);margin:0}
.pcover{width:100%;border-radius:12px;margin-bottom:2rem}
.pbody{line-height:1.85;font-size:1.05rem}
.pbody h2{font-size:1.5rem;font-weight:700;margin:2.25rem 0 .65rem;color:var(--bl-head)}
.pbody h3{font-size:1.18rem;font-weight:700;margin:1.75rem 0 .45rem;color:var(--bl-head)}
.pbody p{margin:0 0 1.2rem}
.pbody ul,.pbody ol{margin:0 0 1.2rem;padding-left:1.5rem}
.pbody li{margin-bottom:.35rem}
.pbody blockquote{border-left:3px solid var(--gold,#E8913A);padding:.5rem 1rem;
                  margin:1.5rem 0;color:var(--bl-muted);font-style:italic}
.pbody code{background:var(--bl-code);padding:.15em .35em;
            border-radius:4px;font-size:.87em;font-family:ui-monospace,Menlo,monospace}
.pbody pre{background:var(--bl-code);padding:1rem 1.25rem;
           border-radius:8px;overflow-x:auto;margin:0 0 1.2rem}
.pbody pre code{background:none;padding:0}
.pbody img{max-width:100%;border-radius:8px;margin:.4rem 0}
.pbody a{color:var(--gold,#E8913A);text-decoration:underline}
.pback{display:inline-flex;align-items:center;gap:.3rem;font-size:.875rem;
       font-weight:600;color:var(--bl-muted);text-decoration:none;margin-bottom:2rem}
.pback:hover{color:var(--gold,#E8913A)}
@media(max-width:640px){.blist{gap:1.1rem}.bcbd{padding:1rem}}
"""


def _page(*, title: str, desc: str, path: str, body: str,
          og_image: str = "", og_type: str = "website",
          ld_json: dict | None = None, main_class: str = "bwrap") -> str:
    canonical = f"{_SITE_ORIGIN}{path}"
    og_img    = og_image or f"{_SITE_ORIGIN}/logo.png"
    ld = (f'<script type="application/ld+json">{json.dumps(ld_json, ensure_ascii=False)}</script>'
          if ld_json else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script>try{{var t=localStorage.getItem("theme")||"dark";document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
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
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800;900&family=Hanken+Grotesk:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;0,900;1,600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles.css?v={_CSS_V}">
  <style>{_BLOG_CSS}</style>
</head>
<body>
{_nav()}
<main class="{main_class}">{body}</main>
{_foot()}
<script src="/main.js?v=20261009a"></script>
<script src="/tools-core.js?v=20261005a"></script>
<script src="/tools-nav.js?v=20260811d"></script>
<script type="module" src="/auth.js?v=20261009a"></script>
</body>
</html>"""


# ── Public routes ─────────────────────────────────────────────────────────────

_HERO = (
    '<section class="bhero">'
    '<p class="beyebrow">✍️ PrepWithTee Blog</p>'
    '<h1 class="bhtitle">Cambridge Exam Tips &amp; Study Guides</h1>'
    '<p class="bhsub">Study techniques, topic breakdowns and real exam insights '
    'from PrepWithTee tutors — for Cambridge O&nbsp;Level, IGCSE &amp; A&nbsp;Level.</p>'
    '<hr class="bhrule">'
    '</section>'
)


@router.get("/blog", response_class=HTMLResponse)
def blog_list():
    posts = get_published_posts()
    if posts:
        cards = []
        for p in posts:
            if p.get("cover_url"):
                cover = (f'<img class="bcard-cover" src="{_html.escape(p["cover_url"])}" '
                         f'alt="{_html.escape(p["title"])}" loading="lazy">')
            else:
                cover = ('<div class="bcard-ph">'
                         '<img src="/logo.png" alt="" style="height:56px;opacity:.92"></div>')
            date = _fmt_date(p.get("published_at") or p.get("created_at"))
            author = _html.escape(p.get("author") or "Muhammad Taahaa")
            ex   = _html.escape(p.get("excerpt") or "")
            ex_p = f'<p class="bcex">{ex}</p>' if ex else ""
            cards.append(
                f'<a class="bcard" href="/blog/{_html.escape(p["slug"])}">'
                f'{cover}'
                f'<div class="bcbd">'
                f'<p class="bcmeta">{date} &middot; {author}</p>'
                f'<p class="bctitle">{_html.escape(p["title"])}</p>'
                f'{ex_p}'
                f'<span class="bclink">Read more →</span>'
                f'</div></a>'
            )
        body = _HERO + f'<div class="blist">{"".join(cards)}</div>'
    else:
        body = (
            _HERO +
            '<div class="bempty">'
            '<div class="bempty-ico">🦉</div>'
            '<h2>New posts are on the way</h2>'
            "<p>We're busy writing study guides, exam tips and topic breakdowns. "
            'In the meantime, dive straight into the good stuff:</p>'
            '<div class="bempty-links">'
            '<a class="primary" href="/papers">Topical Past Papers →</a>'
            '<a href="/resources">Revision Notes →</a>'
            '<a href="/#contact">Book a free demo →</a>'
            '</div></div>'
        )

    return _page(
        title="Cambridge Exam Tips & Study Guides | PrepWithTee Blog",
        desc=("Study techniques, topic breakdowns and Cambridge O Level, IGCSE "
              "& A Level exam tips from PrepWithTee tutors."),
        path="/blog",
        body=body,
        main_class="bwrap bwrap-wide",
    )


def _faq_html(faq: list[dict]) -> str:
    if not faq:
        return ""
    items = "".join(f"<details><summary>{_html.escape(f['q'])}</summary><p>{_html.escape(f['a'])}</p></details>"
                    for f in faq)
    return f'<h2>Frequently asked questions</h2><div class="pfaq">{items}</div>'


@router.get("/blog/{slug}", response_class=HTMLResponse)
def blog_post(slug: str):
    if not re.match(r"^[a-z0-9-]{1,120}$", slug):
        raise HTTPException(404, "post not found")
    post = get_post_by_slug(slug)
    if post is None:
        raise HTTPException(404, "post not found")

    content_html = _md(post.get("body_markdown") or "")
    try:
        faq = [f for f in json.loads(post.get("faq_json") or "[]") if f.get("q") and f.get("a")]
    except (TypeError, ValueError, AttributeError):
        faq = []
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
        f'<div class="pbody">{content_html}{_faq_html(faq)}</div>'
    )

    if faq:
        ld = [ld, {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]}]

    return _page(
        title=post.get("meta_title") or f"{post['title']} | PrepWithTee",
        desc=post.get("meta_desc") or post.get("excerpt") or post["title"],
        path=f"/blog/{slug}",
        og_type="article",
        og_image=post.get("cover_url") or "",
        ld_json=ld,
        body=body,
    )
