"""House rules for the consoles' front ends (static/admin/ and static/teach/,
which reuses the admin modules).

- Every colour is a token: raw colours only inside the token blocks of admin.css.
- No inline style="" strings or onclick="" handlers in markup the JS builds.
- Every ES module is in index.html's import map at the one shared version
  (Caddy serves static JS immutable for a year, so an unversioned import
  would never update for anyone who already has it).
"""

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "website" / "static"
ADMIN = STATIC / "admin"
TEACH = STATIC / "teach"
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")


def _js_files():
    return sorted(ADMIN.rglob("*.js")) + sorted(TEACH.rglob("*.js"))


def test_colours_only_in_tokens():
    css = (ADMIN / "admin.css").read_text(encoding="utf-8")
    assert "/* end tokens */" in css
    body = css.split("/* end tokens */", 1)[1]
    assert not COLOUR.findall(body), "raw colour outside the token blocks of admin.css"
    body_t = (TEACH / "teach.css").read_text(encoding="utf-8")
    assert not COLOUR.findall(body_t), "raw colour in teach.css - use the admin.css tokens"
    for f in _js_files() + [ADMIN / "index.html", TEACH / "index.html"]:
        src = f.read_text(encoding="utf-8")
        if f.name == "index.html":
            src = re.sub(r"<script>try\{.*?</script>", "", src, flags=re.S)
        hits = [m for m in COLOUR.findall(src) if not re.fullmatch(r"#\w+", m) or not _is_anchor(src, m)]
        assert not hits, f"raw colour in {f.relative_to(STATIC)}: {hits[:3]}"


def _is_anchor(src: str, m: str) -> bool:
    """'#/students' style hash routes are not colours."""
    return bool(re.search(re.escape(m) + r"[/\w-]", src)) and not re.search(re.escape(m) + r"[;\s\"')]", src)


def test_no_inline_styles_or_handlers():
    for f in _js_files() + [ADMIN / "index.html", TEACH / "index.html"]:
        src = f.read_text(encoding="utf-8")
        assert 'style="' not in src, f"inline style in {f.relative_to(STATIC)}"
        assert not re.search(r"\son[a-z]+=\"", src), f"inline event handler in {f.relative_to(STATIC)}"


def test_every_module_is_versioned_in_the_import_map():
    html = (ADMIN / "index.html").read_text(encoding="utf-8")
    imap = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    app_v = re.search(r'/admin/app\.js\?v=(\w+)', html).group(1)
    css_v = re.search(r'/admin/admin\.css\?v=(\w+)', html).group(1)
    assert app_v == css_v
    for f in sorted(ADMIN.rglob("*.js")):
        rel = "/admin/" + f.relative_to(ADMIN).as_posix()
        if rel == "/admin/app.js":
            continue
        assert imap.get(rel) == f"{rel}?v={app_v}", f"{rel} missing from the import map or on another version"
    for src in imap:
        assert (ADMIN / src.removeprefix("/admin/")).is_file(), f"import map lists a missing file {src}"


def test_teach_console_map_covers_its_modules_and_the_admin_ones():
    html = (TEACH / "index.html").read_text(encoding="utf-8")
    imap = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    v = re.search(r'/teach/app\.js\?v=(\w+)', html).group(1)
    assert re.search(rf'/teach/teach\.css\?v={v}', html) and re.search(rf'/admin/admin\.css\?v={v}', html)
    admin_v = re.search(r'/admin/app\.js\?v=(\w+)', (ADMIN / "index.html").read_text(encoding="utf-8")).group(1)
    assert v == admin_v, "the two consoles share one version - run scripts/bump_admin_assets.py"
    for root, prefix in ((TEACH, "teach"), (ADMIN, "admin")):
        for f in sorted(root.rglob("*.js")):
            rel = f"/{prefix}/" + f.relative_to(root).as_posix()
            if f.name == "app.js":
                continue
            assert imap.get(rel) == f"{rel}?v={v}", f"{rel} missing from /teach's import map or on another version"
