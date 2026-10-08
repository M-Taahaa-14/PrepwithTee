"""Rebuild the consoles' import maps and bump their one version string.

Static JS/CSS are served immutable for a year, so every console module goes
through the import map in the console's index.html at ONE version. Two
consoles share one version:
  website/static/admin/index.html   the admin console (/admin)
  website/static/teach/index.html   the teaching console (/teach) - its own
                                    modules plus every /admin/ module (it reuses
                                    core, datatable, the student manage card...)
Run this after any change under website/static/admin/ or website/static/teach/:

    .venv\\Scripts\\python scripts\\bump_admin_assets.py
"""

import re
from datetime import datetime
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "website" / "static"
ADMIN = STATIC / "admin"
TEACH = STATIC / "teach"


def _mods(root: Path, prefix: str) -> list[str]:
    return sorted(f"/{prefix}/" + p.relative_to(root).as_posix() for p in root.rglob("*.js") if p.name != "app.js")


def _next(old: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    if old.startswith(today):
        suffix = old[len(today):] or "a"
        return today + chr(ord(suffix[-1]) + 1) if suffix[-1] < "z" else today + suffix + "a"
    return today + "a"


def _write(index: Path, mods: list[str], new: str, assets: str) -> None:
    html = index.read_text(encoding="utf-8")
    imap = ",\n".join(f'    "{m}": "{m}?v={new}"' for m in mods)
    html = re.sub(r'(<script type="importmap">\s*\{"imports": \{\n?).*?(\n?\s*\}\})',
                  lambda m: m.group(1).rstrip("\n") + "\n" + imap + "\n  }}", html, count=1, flags=re.S)
    html = re.sub(rf"({assets}\?v=)\w+", rf"\g<1>{new}", html)
    index.write_text(html, encoding="utf-8")


def main() -> None:
    a_html = (ADMIN / "index.html").read_text(encoding="utf-8")
    old = re.search(r"/admin/app\.js\?v=(\w+)", a_html).group(1)
    if (TEACH / "index.html").exists():
        t = re.search(r"/teach/app\.js\?v=(\w+)", (TEACH / "index.html").read_text(encoding="utf-8"))
        if t and t.group(1) > old:
            old = t.group(1)
    new = _next(old)
    admin_mods = _mods(ADMIN, "admin")
    _write(ADMIN / "index.html", admin_mods, new, r"/admin/(?:app\.js|admin\.css)")
    if (TEACH / "index.html").exists():
        _write(TEACH / "index.html", _mods(TEACH, "teach") + admin_mods, new,
               r"/(?:teach/app\.js|teach/teach\.css|admin/admin\.css)")
    print(f"console assets {old} -> {new} ({len(admin_mods)} admin modules)")


if __name__ == "__main__":
    main()
