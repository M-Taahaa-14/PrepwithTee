"""Rebuild the admin console's import map and bump its one version string.

Static JS/CSS are served immutable for a year, so every admin module goes
through the import map in website/static/admin/index.html at ONE version.
Run this after any change under website/static/admin/:

    .venv\\Scripts\\python scripts\\bump_admin_assets.py
"""

import re
from datetime import datetime
from pathlib import Path

ADMIN = Path(__file__).resolve().parent.parent / "website" / "static" / "admin"


def main() -> None:
    index = ADMIN / "index.html"
    html = index.read_text(encoding="utf-8")
    old = re.search(r"/admin/app\.js\?v=(\w+)", html).group(1)
    today = datetime.now().strftime("%Y%m%d")
    if old.startswith(today):
        suffix = old[len(today):] or "a"
        new = today + chr(ord(suffix[-1]) + 1) if suffix[-1] < "z" else today + suffix + "a"
    else:
        new = today + "a"
    mods = sorted("/admin/" + p.relative_to(ADMIN).as_posix() for p in ADMIN.rglob("*.js")
                  if p.name != "app.js")
    imap = ",\n".join(f'    "{m}": "{m}?v={new}"' for m in mods)
    html = re.sub(r'(<script type="importmap">\s*\{"imports": \{\n).*?(\n\s*\}\})',
                  lambda m: m.group(1) + imap + m.group(2), html, flags=re.S)
    html = re.sub(r"(/admin/(?:app\.js|admin\.css)\?v=)\w+", rf"\g<1>{new}", html)
    index.write_text(html, encoding="utf-8")
    print(f"admin assets {old} -> {new} ({len(mods)} modules in the import map)")


if __name__ == "__main__":
    main()
