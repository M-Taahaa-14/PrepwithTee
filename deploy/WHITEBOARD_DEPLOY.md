# Deploying the ink rail + PrepWithTee Board (2026-10-05)

1. **Supabase first:** run `website/migrations/026_whiteboard.sql` (wb_boards, wb_pages,
   wb_folders, wb_shares, ink_assets). Without it every /api/wb and /api/ink call 500s.
2. **Image folder on the server:** `sudo mkdir -p /srv/prepwithtee/data/ink_assets &&
   sudo chown prepwithtee: /srv/prepwithtee/data/ink_assets` (or set `INK_ASSET_DIR`).
   Include it in backups - it holds students' pasted images and board covers.
3. **Code:** the usual code-only tar of `website/` (+ `scripts/build_stickers.py`) via
   /tmp/stage; `python -m compileall website` with the server's Python 3.10 first.
   `website/static/ink/stickers.json` is generated - it is committed, ship it.
4. **Check after restart:** /whiteboard (guest page, has SoftwareApplication JSON-LD),
   /features, /sitemap.xml lists both, create a board, draw, paste an image, export PDF,
   open a share link in a private window; on a yearly paper the left rail + compass work
   and "Download with my annotations" includes stickers/arcs.

Versions bumped in this change (all `20261005a`): annotate.js/css + ink/*, auth.js, main.js,
scratch-pen.js, styles.css (catalog.STYLES_V), catalog.css (CSS_V), tools-core/tools.css
(ui.TOOLS_V), pdf-pane.js, VIEWER_V (booklets + yearly), SESSION_V, RES_V, WB_V.
