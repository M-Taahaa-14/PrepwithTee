/* board/app.js — the PrepWithTee Board editor (/whiteboard/{id}, /whiteboard/s/{token}).
 *
 * One board = a notebook of pages (A4 / landscape / Letter / 16:9, each with a
 * paper colour and pattern) or one infinite canvas (pan, zoom, minimap). The
 * ink engine is annotate.js - the same rail, pens, shapes, compass, stickers,
 * text and images as on past papers - given:
 *   store   pages load from the board, save with an optimistic version (a stale
 *           save is merged by object id and saved again), offline saves retry
 *           and are kept as a local draft until the server has them;
 *   camera  attach(..., { camera: true }) for the infinite canvas.
 * Around it: title, save status, zoom, page thumbnails (drag to reorder), page
 * settings, insert (image / camera / sticky note / sticker / PDF pages),
 * present (fullscreen + laser), share links, export (PDF / PNG / print).
 */
import { createAnnotator } from "/annotate.js?v=20261005c";
import { SIZES, PAPERS, PATTERNS, paperHex, isDark, sizeOf, drawPattern, AXES_DEFAULT, AXES_SUBS, checkAxes } from "/board/paper.js?v=20261008b";

const ST = JSON.parse(document.getElementById("wb-state").textContent);
const root = document.getElementById("wb");
const DOC = `wb:${ST.board}`;
const BASE = 1000;                                   // infinite canvas: px per world unit at 100 %
const B = { board: null, pages: [], versions: new Map(), seen: new Map(), els: new Map(), ps: new Map(),
            readonly: false, zoom: 1, cur: 0, p: null, dirtyThumb: false, me: null };
let ann = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const I = {
  back: '<path d="M15 18l-6-6 6-6"/>', minus: '<path d="M5 12h14"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  page: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/>', insert: '<path d="M12 5v14M5 12h14"/><rect x="3" y="3" width="18" height="18" rx="4"/>',
  present: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  share: '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>',
  export: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>', side: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  dup: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
  trash: '<path d="M4 7h16"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>', gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  prev: '<path d="M15 18l-6-6 6-6"/>', next: '<path d="M9 18l6-6-6-6"/>', copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
};
const ic = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${I[k]}</svg>`;

async function api(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body && !(body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await r.json(); } catch { /* not json */ }
  if (!r.ok) {
    const d = data?.detail;
    const err = new Error(typeof d === "string" ? d : d?.message || `Something went wrong (${r.status})`);
    err.status = r.status; err.data = data; err.code = d?.code;
    throw err;
  }
  return data;
}

function toast(msg, kind = "") {
  let t = document.querySelector(".wb-toast");
  if (!t) { t = document.createElement("div"); t.className = "wb-toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg;
  t.dataset.kind = kind;
  t.classList.add("is-on");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("is-on"), 2800);
}

// ── saving ───────────────────────────────────────────────────────────────────
const draftKey = (pid) => `wb-draft:${ST.board}:${pid}`;
function draft(pid, objects) {
  try { localStorage.setItem(draftKey(pid), JSON.stringify({ v: B.versions.get(pid) || 1, objects, t: Date.now() })); }
  catch { /* full or blocked: the save still goes up */ }
}
const clearDraft = (pid) => { try { localStorage.removeItem(draftKey(pid)); } catch { /* ignore */ } };

/** Server copy + my copy, by object id: mine wins; things only the server has
 *  (added elsewhere since I loaded) are kept unless I had them and deleted them. */
function merge(pid, mine, theirs) {
  const have = new Set(mine.map((o) => o.id));
  const seen = B.seen.get(pid) || new Set();
  return [...mine, ...theirs.filter((o) => o.id && !have.has(o.id) && !seen.has(o.id))];
}

async function putPage(pid, objects, tries = 0) {
  const r = await fetch(`/api/wb/boards/${ST.board}/pages/${pid}`, { method: "PUT", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ objects, version: B.versions.get(pid) || 1 }) });
  if (r.status === 409) {
    const d = await r.json().catch(() => ({}));
    if (d.code === "stale" && tries < 4) {
      const merged = merge(pid, objects, d.objects || []);
      B.versions.set(pid, d.version);
      if (merged.length !== objects.length) {
        const p = ann.page(DOC, pid);
        if (p) { p.strokes = merged; ann.repaint(); }
        toast("Merged changes from another tab");
      }
      return putPage(pid, merged, tries + 1);
    }
    const e = new Error(d.detail?.message || "Not saved"); e.status = 409; throw e;
  }
  if (!r.ok) { const e = new Error(`Not saved (${r.status})`); e.status = r.status; throw e; }
  const d = await r.json();
  B.versions.set(pid, d.version);
  B.seen.set(pid, new Set(objects.map((o) => o.id)));
  clearDraft(pid);
  const pg = B.pages.find((x) => x.id === pid);
  if (pg) pg.objects = objects;
}

const store = {
  load: async () => Object.fromEntries(B.pages.map((p) => [p.id, p.objects])),
  async save(doc, pid, objects) {
    if (B.readonly) return;
    draft(pid, objects);
    for (let attempt = 0; ; attempt++) {
      try { await putPage(pid, objects); setStatus(ann?.pending > 1 ? "saving" : "saved"); return; }
      catch (e) {
        if (e.status && e.status < 500 && e.status !== 408 && e.status !== 429) {
          setStatus("error"); toast(e.message, "bad"); throw e;
        }
        setStatus("offline");
        await sleep(Math.min(20000, 2500 * (attempt + 1)));
      }
    }
  },
};

function setStatus(state) {
  const el = root.querySelector(".wb-status");
  if (!el) return;
  const txt = { saving: "Saving…", saved: "All changes saved", offline: "Offline — will save when you're back",
                error: "Not saved", readonly: "View only" }[state] || "";
  el.textContent = txt;
  el.dataset.state = state;
}

// ── start ────────────────────────────────────────────────────────────────────
async function start() {
  let data;
  try {
    data = ST.share ? await api("GET", `/api/wb/shared/${ST.share}`) : await api("GET", `/api/wb/boards/${ST.board}`);
  } catch (e) {
    root.innerHTML = `<div class="wb-fail"><h1>We couldn't open this board</h1><p>${esc(e.message)}</p>
      <a class="wb-btn wb-btn-primary" href="/whiteboard">Back to my boards</a></div>`;
    return;
  }
  B.board = data;
  B.readonly = !!data.readonly;
  B.pages = data.pages;
  for (const p of B.pages) {
    B.versions.set(p.id, p.version || 1);
    B.seen.set(p.id, new Set((p.objects || []).map((o) => o.id)));
    // a save that never reached the server (closed offline): put it back
    if (!B.readonly) {
      try {
        const d = JSON.parse(localStorage.getItem(draftKey(p.id)) || "null");
        if (d && d.v === p.version && Array.isArray(d.objects)) { p.objects = d.objects; p.restored = true; }
        else if (d) clearDraft(p.id);
      } catch { /* ignore */ }
    }
  }
  document.title = `${data.title} — PrepWithTee Board`;
  syncTheme();
  shell();
  ann = createAnnotator({ mount: document.body, store, pasteText: true, push: true,
                          pinned: window.innerWidth >= 900, collapsed: window.innerWidth < 700 });
  ann.quiet(true);
  ann.onSave((state) => setStatus(state === "saving" ? "saving" : state === "error" ? "offline" : "saved"));
  ann.onChange((p) => { markThumb(p.page); B.dirtyThumb = true; scheduleCover(); if (B.board.kind === "infinite") drawMini(); });
  ann.onPan((p, dx, dy) => panBy(-dx, -dy));
  if (B.readonly) { ann.setVisible(false); setStatus("readonly"); }
  if (B.board.kind === "infinite") await mountInfinite(); else await mountPages();
  for (const p of B.pages) if (p.restored) { ann.page(DOC, p.id)?.strokes && store.save(DOC, p.id, ann.page(DOC, p.id).strokes); }
  if (ST.insertq) insertQuestion(ST.insertq);
  if (new URLSearchParams(location.search).get("share") === "1") openShare();
  root.dataset.state = "ready";
}

function syncTheme() {
  // ink shades follow the board's paper: pastel inks on a chalkboard
  document.documentElement.dataset.paper = isDark(boardSettings()) ? "dark" : "light";
}
const boardSettings = () => ({ size: "a4", paper: "white", pattern: "plain", ...(B.board.settings || {}) });
const pageSettings = (pg) => ({ ...boardSettings(), ...(pg?.settings || {}) });

// ── the shell: top bar, stage, side panel ────────────────────────────────────
function shell() {
  const b = B.board, ro = B.readonly, inf = b.kind === "infinite";
  root.innerHTML = `
    <header class="wb-top">
      <a class="wb-iconbtn" href="/whiteboard" title="All my boards" aria-label="All my boards">${ic("back")}</a>
      <a class="wb-brand" href="/whiteboard" aria-label="PrepWithTee Board"><img src="/logo-nav.webp" alt="" width="28" height="28"><span>Board</span></a>
      ${ro ? `<h1 class="wb-title-ro">${esc(b.title)}</h1><span class="wb-badge">${ic("lock")} View only</span>`
           : `<input class="wb-title" value="${esc(b.title)}" maxlength="120" aria-label="Board name" spellcheck="false">`}
      <span class="wb-status" aria-live="polite"></span>
      <div class="wb-grow"></div>
      ${inf ? "" : '<span class="wb-pgind" aria-live="polite"></span>'}
      <div class="wb-zoom" role="group" aria-label="Zoom">
        <button type="button" class="wb-iconbtn" data-act="zoomout" title="Zoom out (Ctrl −)" aria-label="Zoom out">${ic("minus")}</button>
        <button type="button" class="wb-zoompct" data-act="zoomfit" title="Fit (Ctrl 0)">100%</button>
        <button type="button" class="wb-iconbtn" data-act="zoomin" title="Zoom in (Ctrl +)" aria-label="Zoom in">${ic("plus")}</button>
      </div>
      <div class="wb-acts">
        ${ro ? "" : `<button type="button" class="wb-btn" data-act="insert" aria-haspopup="true">${ic("insert")}<span>Insert</span></button>
        <button type="button" class="wb-btn" data-act="paper" aria-haspopup="true">${ic("page")}<span>Paper</span></button>`}
        <button type="button" class="wb-btn" data-act="present">${ic("present")}<span>Present</span></button>
        ${ro ? "" : `<button type="button" class="wb-btn" data-act="share">${ic("share")}<span>Share</span></button>`}
        <button type="button" class="wb-btn ${ro ? "" : "wb-btn-primary"}" data-act="export" aria-haspopup="true">${ic("export")}<span>Export</span></button>
        ${ro && ST.share ? `<button type="button" class="wb-btn wb-btn-primary" data-act="copy">${ic("copy")}<span>${ST.signedIn ? "Make a copy" : "Sign in to copy"}</span></button>` : ""}
        ${inf ? "" : `<button type="button" class="wb-iconbtn wb-sidebtn" data-act="side" title="Pages" aria-label="Show pages" aria-pressed="true">${ic("side")}</button>`}
      </div>
    </header>
    <div class="wb-main">
      <div class="wb-stage${inf ? " is-inf" : ""}" tabindex="-1"></div>
      ${inf ? "" : `<aside class="wb-side" aria-label="Pages">
        <div class="wb-side-head"><b>Pages</b>${ro ? "" : `<button type="button" class="wb-iconbtn" data-act="addpage" title="Add a page" aria-label="Add a page">${ic("plus")}</button>`}</div>
        <ol class="wb-thumbs"></ol>
        ${ro ? "" : '<button type="button" class="wb-addpage" data-act="addpage">+ New page</button>'}
      </aside>`}
    </div>`;
  if (window.innerWidth < 900) root.classList.add("side-closed");
  root.querySelector(".wb-sidebtn")?.setAttribute("aria-pressed", String(!root.classList.contains("side-closed")));
  root.addEventListener("click", onAction);
  const title = root.querySelector(".wb-title");
  if (title) {
    let t = null;
    const saveTitle = () => {
      const v = title.value.trim() || "Untitled board";
      if (v === B.board.title) return;
      B.board.title = v;
      document.title = `${v} — PrepWithTee Board`;
      api("PATCH", `/api/wb/boards/${ST.board}`, { title: v }).catch((e) => toast(e.message, "bad"));
    };
    title.addEventListener("input", () => { clearTimeout(t); t = setTimeout(saveTitle, 800); });
    title.addEventListener("change", saveTitle);
    title.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") title.blur(); });
  }
}

function onAction(e) {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const a = b.dataset.act;
  if (a === "zoomin") zoomBy(1.2);
  else if (a === "zoomout") zoomBy(1 / 1.2);
  else if (a === "zoomfit") zoomFit();
  else if (a === "insert") menu(b, insertItems());
  else if (a === "paper") openPaper(b);
  else if (a === "present") present(true);
  else if (a === "share") openShare();
  else if (a === "export") menu(b, exportItems());
  else if (a === "copy") copyBoard();
  else if (a === "addpage") addPage();
  else if (a === "side") {
    root.classList.toggle("side-closed");
    b.setAttribute("aria-pressed", String(!root.classList.contains("side-closed")));
    setTimeout(() => relayout(), 220);
  }
}

// ── pages mode ───────────────────────────────────────────────────────────────
const stage = () => root.querySelector(".wb-stage");
let wrap = null;

async function mountPages() {
  wrap = document.createElement("div");
  wrap.className = "wb-pages";
  stage().appendChild(wrap);
  for (const pg of B.pages) wrap.appendChild(pageEl(pg));
  relayout();
  await Promise.all(B.pages.map(async (pg) => {
    const p = await ann.attach(B.els.get(pg.id), DOC, pg.id);
    B.ps.set(pg.id, p);
  }));
  renderThumbs();
  stage().addEventListener("scroll", onScroll, { passive: true });
  stage().addEventListener("wheel", onWheelPages, { passive: false });
  onScroll();
}

function pageEl(pg) {
  const el = document.createElement("section");
  el.className = "wb-pg";
  el.dataset.pid = pg.id;
  el.innerHTML = `<canvas class="wb-pat" aria-hidden="true"></canvas><img class="wb-bg" alt="" hidden>`;
  B.els.set(pg.id, el);
  patObs.observe(el);
  return el;
}

const patObs = new IntersectionObserver((entries) => {
  for (const e of entries) {
    e.target.dataset.near = e.isIntersecting ? "1" : "";
    if (e.isIntersecting && e.target.dataset.drawn !== String(B.zoom)) drawPagePattern(e.target);
  }
}, { rootMargin: "600px 0px" });

function baseWidth() {
  const st = stage();
  return Math.max(300, Math.min(980, (st?.clientWidth || 900) - 66));          // room for a scrollbar
}

function relayout() {
  if (B.board.kind === "infinite") { drawInfPattern(); drawMini(); return; }
  const bw = baseWidth() * B.zoom;
  for (const pg of B.pages) {
    const el = B.els.get(pg.id);
    if (!el) continue;
    const sz = sizeOf(pageSettings(pg));
    const w = Math.round(bw * (sz.w > sz.h ? Math.min(1.25, sz.w / 595) : 1));
    el.style.width = `${w}px`;
    el.style.height = `${Math.round((w * sz.h) / sz.w)}px`;
    el.dataset.drawn = "";
    const s = pageSettings(pg);
    const img = el.querySelector(".wb-bg");
    if (s.bg) { if (img.getAttribute("src") !== s.bg) img.src = s.bg; img.hidden = false; }
    else { img.hidden = true; img.removeAttribute("src"); }
    if (el.dataset.near === "1") drawPagePattern(el);
  }
  root.querySelector(".wb-zoompct").textContent = `${Math.round(B.zoom * 100)}%`;
  ann?.repaint();
}

function drawPagePattern(el) {
  const pg = B.pages.find((x) => x.id === el.dataset.pid);
  if (!pg) return;
  const s = pageSettings(pg);
  const cv = el.querySelector(".wb-pat");
  const w = el.clientWidth, h = el.clientHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawPattern(ctx, w, h, s, w / sizeOf(s).mm);
  el.style.background = paperHex(s);
  el.dataset.drawn = String(B.zoom);
}

function onScroll() {
  const st = stage(), mid = st.scrollTop + st.clientHeight / 2;
  let best = 0, bd = Infinity;
  B.pages.forEach((pg, i) => {
    const el = B.els.get(pg.id);
    if (!el) return;
    const c = el.offsetTop + el.offsetHeight / 2, d = Math.abs(c - mid);
    if (d < bd) { bd = d; best = i; }
  });
  if (best !== B.cur || !root.querySelector(".wb-pgind")?.textContent) {
    B.cur = best;
    const ind = root.querySelector(".wb-pgind");
    if (ind) ind.textContent = `Page ${best + 1} of ${B.pages.length}`;
    root.querySelectorAll(".wb-thumb").forEach((t, i) => t.classList.toggle("is-cur", i === best));
  }
}

function zoomBy(k, cx, cy) {
  if (B.board.kind === "infinite") return zoomCam(k, cx, cy);
  const st = stage();
  const r = st.getBoundingClientRect();
  const ax = cx ?? r.left + st.clientWidth / 2, ay = cy ?? r.top + st.clientHeight / 2;
  const fx = (st.scrollLeft + ax - r.left) / Math.max(1, st.scrollWidth), fy = (st.scrollTop + ay - r.top) / Math.max(1, st.scrollHeight);
  B.zoom = Math.min(4, Math.max(0.3, B.zoom * k));
  relayout();
  st.scrollLeft = fx * st.scrollWidth - (ax - r.left);
  st.scrollTop = fy * st.scrollHeight - (ay - r.top);
}
function zoomFit() {
  if (B.board.kind === "infinite") return fitCam();
  const pg = B.pages[B.cur];
  B.zoom = 1;
  relayout();
  B.els.get(pg?.id)?.scrollIntoView({ block: "start" });
}
function onWheelPages(e) {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  zoomBy(Math.exp(-e.deltaY * 0.0022), e.clientX, e.clientY);
}

function goPage(i) {
  i = Math.max(0, Math.min(B.pages.length - 1, i));
  B.els.get(B.pages[i]?.id)?.scrollIntoView({ block: "start", behavior: "smooth" });
}

// ── thumbnails ───────────────────────────────────────────────────────────────
function renderThumbs() {
  const list = root.querySelector(".wb-thumbs");
  if (!list) return;
  list.innerHTML = B.pages.map((pg, i) => `
    <li class="wb-thumb${i === B.cur ? " is-cur" : ""}" data-pid="${pg.id}" ${B.readonly ? "" : 'draggable="true"'}>
      <button type="button" class="wb-th-open" aria-label="Go to page ${i + 1}"><canvas></canvas></button>
      <span class="wb-th-n">${i + 1}</span>
      ${B.readonly ? "" : `<span class="wb-th-acts">
        <button type="button" data-th="dup" title="Duplicate page" aria-label="Duplicate page ${i + 1}">${ic("dup")}</button>
        <button type="button" data-th="del" title="Delete page" aria-label="Delete page ${i + 1}">${ic("trash")}</button>
      </span>`}
    </li>`).join("");
  B.pages.forEach((pg) => drawThumb(pg.id));
}
const thumbTimers = new Map();
function markThumb(pid) {
  clearTimeout(thumbTimers.get(pid));
  thumbTimers.set(pid, setTimeout(() => drawThumb(pid), 500));
}
function pageStrokes(pid) {
  return ann?.page(DOC, pid)?.strokes || B.pages.find((x) => x.id === pid)?.objects || [];
}
/** Draw a page (paper, background, ink) at width w onto a fresh canvas. */
function renderPage(pg, w, dpr = 1) {
  const s = pageSettings(pg), sz = sizeOf(s);
  const h = Math.round((w * sz.h) / sz.w);
  const cv = document.createElement("canvas");
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  drawPattern(ctx, w, h, s, w / sz.mm);
  const img = B.els.get(pg.id)?.querySelector(".wb-bg");
  if (s.bg && img?.complete && img.naturalWidth) {
    const k = Math.min(w / img.naturalWidth, h / img.naturalHeight);
    ctx.drawImage(img, (w - img.naturalWidth * k) / 2, (h - img.naturalHeight * k) / 2, img.naturalWidth * k, img.naturalHeight * k);
  }
  ann.render(ctx, pageStrokes(pg.id), w, h);
  return cv;
}
function drawThumb(pid) {
  const li = root.querySelector(`.wb-thumb[data-pid="${pid}"]`);
  const pg = B.pages.find((x) => x.id === pid);
  if (!li || !pg || !ann) return;
  const src = renderPage(pg, 136, Math.min(window.devicePixelRatio || 1, 2));
  const cv = li.querySelector("canvas");
  cv.width = src.width; cv.height = src.height;
  cv.style.width = `${136}px`;
  cv.style.height = `${(src.height / src.width) * 136}px`;
  cv.getContext("2d").drawImage(src, 0, 0);
}

document.addEventListener("click", (e) => {
  const li = e.target.closest?.(".wb-thumb");
  if (!li) return;
  const i = B.pages.findIndex((x) => x.id === li.dataset.pid);
  const act = e.target.closest("[data-th]")?.dataset.th;
  if (act === "dup") return addPage(li.dataset.pid, true);
  if (act === "del") return deletePage(li.dataset.pid);
  goPage(i);
});
// drag to reorder
let dragPid = null;
document.addEventListener("dragstart", (e) => {
  const li = e.target.closest?.(".wb-thumb");
  if (!li) return;
  dragPid = li.dataset.pid;
  li.classList.add("is-drag");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", dragPid);
});
document.addEventListener("dragover", (e) => {
  const li = e.target.closest?.(".wb-thumb");
  if (!li || !dragPid) return;
  e.preventDefault();
  const r = li.getBoundingClientRect();
  root.querySelectorAll(".wb-thumb").forEach((x) => x.classList.remove("drop-before", "drop-after"));
  li.classList.add(e.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
});
document.addEventListener("dragend", () => {
  dragPid = null;
  root.querySelectorAll(".wb-thumb").forEach((x) => x.classList.remove("drop-before", "drop-after", "is-drag"));
});
document.addEventListener("drop", async (e) => {
  const li = e.target.closest?.(".wb-thumb");
  if (!li || !dragPid) return;
  e.preventDefault();
  const before = li.classList.contains("drop-before");
  const from = B.pages.findIndex((x) => x.id === dragPid);
  const moved = B.pages.splice(from, 1)[0];
  let to = B.pages.findIndex((x) => x.id === li.dataset.pid);
  if (!before) to += 1;
  B.pages.splice(to, 0, moved);
  dragPid = null;
  for (const pg of B.pages) wrap.appendChild(B.els.get(pg.id));
  renderThumbs();
  onScroll();
  try { await api("PUT", `/api/wb/boards/${ST.board}/order`, { order: B.pages.map((x) => x.id) }); }
  catch (err) { toast(err.message, "bad"); }
});

async function addPage(after = null, duplicate = false) {
  if (B.readonly) return;
  const anchor = after || B.pages[B.cur]?.id;
  const prev = B.pages.find((x) => x.id === anchor);
  try {
    const d = await api("POST", `/api/wb/boards/${ST.board}/pages`,
      duplicate ? { duplicate: anchor } : { after: anchor, settings: prev?.settings || {} });
    await ann.flush();
    const pg = { id: d.id, settings: d.settings, objects: d.objects, version: d.version };
    const at = B.pages.findIndex((x) => x.id === anchor) + 1;
    B.pages.splice(at || B.pages.length, 0, pg);
    B.versions.set(pg.id, 1);
    B.seen.set(pg.id, new Set(pg.objects.map((o) => o.id)));
    const el = pageEl(pg);
    const next = B.els.get(B.pages[at + 1]?.id);
    if (next) wrap.insertBefore(el, next); else wrap.appendChild(el);
    relayout();
    B.ps.set(pg.id, await ann.attach(el, DOC, pg.id, { strokes: pg.objects }));
    renderThumbs();
    el.scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (e) { toast(e.message, "bad"); }
}

async function deletePage(pid) {
  if (B.pages.length < 2) return toast("A board needs at least one page");
  const i = B.pages.findIndex((x) => x.id === pid);
  if (pageStrokes(pid).length && !confirm(`Delete page ${i + 1}? Everything on it goes too.`)) return;
  try {
    await api("DELETE", `/api/wb/boards/${ST.board}/pages/${pid}`);
    const el = B.els.get(pid);
    ann.detachWithin(el);
    el.remove();
    B.els.delete(pid);
    B.pages.splice(i, 1);
    clearDraft(pid);
    renderThumbs();
    onScroll();
  } catch (e) { toast(e.message, "bad"); }
}

// ── infinite canvas ──────────────────────────────────────────────────────────
let infEl = null, mini = null;
const camKey = `wb-cam:${ST.board}`;

async function mountInfinite() {
  infEl = document.createElement("div");
  infEl.className = "wb-inf";
  infEl.innerHTML = '<canvas class="wb-pat" aria-hidden="true"></canvas>';
  stage().appendChild(infEl);
  mini = document.createElement("canvas");
  mini.className = "wb-mini";
  mini.title = "Map — click to jump";
  stage().appendChild(mini);
  const pg = B.pages[0];
  B.p = await ann.attach(infEl, DOC, pg.id, { camera: true });
  B.ps.set(pg.id, B.p);
  let cam = null;
  try { cam = JSON.parse(localStorage.getItem(camKey) || "null"); } catch { /* ignore */ }
  if (cam && Number.isFinite(cam.x) && Number.isFinite(cam.z)) ann.setCamera(B.p, cam);
  else fitCam(true);
  bindCamera();
  drawInfPattern();
  drawMini();
  window.addEventListener("resize", () => { drawInfPattern(); drawMini(); });
}

function setCam(c) {
  ann.setCamera(B.p, c);
  drawInfPattern();
  drawMini();
  root.querySelector(".wb-zoompct").textContent = `${Math.round(B.p.cam.z * 100)}%`;
  clearTimeout(setCam._t);
  setCam._t = setTimeout(() => { try { localStorage.setItem(camKey, JSON.stringify(B.p.cam)); } catch { /* ignore */ } }, 400);
}
function panBy(dx, dy) {
  const w = BASE * B.p.cam.z;
  setCam({ x: B.p.cam.x + dx / w, y: B.p.cam.y + dy / w });
}
function zoomCam(k, cx, cy) {
  const r = infEl.getBoundingClientRect();
  const sx = (cx ?? r.left + r.width / 2) - r.left, sy = (cy ?? r.top + r.height / 2) - r.top;
  const c = B.p.cam, w = BASE * c.z;
  const wx = c.x + sx / w, wy = c.y + sy / w;
  const z = Math.min(8, Math.max(0.1, c.z * k)), w2 = BASE * z;
  setCam({ z, x: wx - sx / w2, y: wy - sy / w2 });
}
function contentBox() {
  const s = pageStrokes(B.pages[0].id);
  if (!s.length) return null;
  let b = null;
  for (const o of s) {
    const q = ann.bbox(o, BASE, BASE);
    b = b ? [Math.min(b[0], q[0]), Math.min(b[1], q[1]), Math.max(b[2], q[2]), Math.max(b[3], q[3])] : q;
  }
  return b;
}
function fitCam(initial = false) {
  const r = infEl.getBoundingClientRect();
  const b = contentBox();
  if (!b) return setCam({ x: -0.06, y: -0.06, z: initial ? 1 : B.p.cam.z });
  const bw = Math.max(0.2, b[2] - b[0]), bh = Math.max(0.2, b[3] - b[1]);
  const z = Math.min(2, Math.max(0.1, Math.min(r.width / (bw * BASE), r.height / (bh * BASE)) * 0.9));
  const w = BASE * z;
  setCam({ z, x: (b[0] + b[2]) / 2 - r.width / 2 / w, y: (b[1] + b[3]) / 2 - r.height / 2 / w });
}

function drawInfPattern() {
  if (!infEl || !B.p) return;
  const cv = infEl.querySelector(".wb-pat");
  const w = infEl.clientWidth, h = infEl.clientHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const s = boardSettings(), px = BASE * B.p.cam.z;
  drawPattern(ctx, w, h, s, px / 210, B.p.cam.x * px, B.p.cam.y * px, { cam: true });
  infEl.style.background = paperHex(s);
}

function drawMini() {
  if (!mini || !B.p) return;
  cancelAnimationFrame(drawMini._r);
  drawMini._r = requestAnimationFrame(() => {
    const W = 168, H = 112, dpr = Math.min(window.devicePixelRatio || 1, 2);
    mini.width = W * dpr; mini.height = H * dpr;
    const ctx = mini.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = paperHex(boardSettings());
    ctx.fillRect(0, 0, W, H);
    const r = infEl.getBoundingClientRect(), c = B.p.cam, w = BASE * c.z;
    const view = [c.x, c.y, c.x + r.width / w, c.y + r.height / w];
    const b = contentBox() || view;
    const all = [Math.min(b[0], view[0]), Math.min(b[1], view[1]), Math.max(b[2], view[2]), Math.max(b[3], view[3])];
    const k = Math.min(W / (all[2] - all[0]), H / (all[3] - all[1])) * 0.9;
    const ox = (W - (all[2] - all[0]) * k) / 2 - all[0] * k, oy = (H - (all[3] - all[1]) * k) / 2 - all[1] * k;
    mini._map = { k, ox, oy };
    ctx.save();
    ctx.translate(ox, oy);
    ann.render(ctx, pageStrokes(B.pages[0].id), k, k);
    ctx.restore();
    ctx.strokeStyle = "#7c5cf0"; ctx.lineWidth = 1.5;
    ctx.fillStyle = "rgba(124, 92, 240, .08)";
    ctx.fillRect(ox + view[0] * k, oy + view[1] * k, (view[2] - view[0]) * k, (view[3] - view[1]) * k);
    ctx.strokeRect(ox + view[0] * k, oy + view[1] * k, (view[2] - view[0]) * k, (view[3] - view[1]) * k);
  });
}

function bindCamera() {
  const pointers = new Map();
  let pan = null, pinch = null, space = false, before = null;
  const hand = () => ann.tool === "pointer" || space;
  infEl.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".an-inst, .an-textwrap, .an-note-ed, .an-tb")) return;
    if (!(hand() || e.button === 1 || e.pointerType === "touch")) return;
    if (e.pointerType === "touch" && !hand()) return;          // a finger while drawing: the engine has it
    e.preventDefault();
    infEl.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), mx: (a[0] + b[0]) / 2, my: (a[1] + b[1]) / 2 };
      pan = null;
    } else pan = { x: e.clientX, y: e.clientY };
    infEl.classList.add("is-panning");
  });
  infEl.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pinch && pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]), mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      panBy(pinch.mx - mx, pinch.my - my);
      zoomCam(d / pinch.d, mx, my);
      pinch = { d, mx, my };
    } else if (pan) {
      panBy(pan.x - e.clientX, pan.y - e.clientY);
      pan = { x: e.clientX, y: e.clientY };
    }
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) { pan = null; infEl.classList.remove("is-panning"); }
  };
  infEl.addEventListener("pointerup", up);
  infEl.addEventListener("pointercancel", up);
  stage().addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) zoomCam(Math.exp(-e.deltaY * 0.0025), e.clientX, e.clientY);
    else panBy(e.shiftKey ? e.deltaY : e.deltaX, e.shiftKey ? 0 : e.deltaY);
  }, { passive: false });
  // hold Space = hand
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || space || e.target.matches("input, textarea, select, [contenteditable]")) return;
    e.preventDefault();
    space = true;
    before = ann.tool;
    if (before !== "pointer") ann.setTool("pointer");
    infEl.classList.add("is-hand");
  });
  document.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || !space) return;
    space = false;
    infEl.classList.remove("is-hand");
    if (before && before !== "pointer") ann.setTool(before);
  });
  mini.addEventListener("pointerdown", (e) => {
    const m = mini._map;
    if (!m) return;
    const go = (ev) => {
      const r = mini.getBoundingClientRect(), R = infEl.getBoundingClientRect(), w = BASE * B.p.cam.z;
      const wx = (ev.clientX - r.left - m.ox) / m.k, wy = (ev.clientY - r.top - m.oy) / m.k;
      setCam({ x: wx - R.width / 2 / w, y: wy - R.height / 2 / w });
    };
    go(e);
    mini.setPointerCapture(e.pointerId);
    mini.onpointermove = (ev) => { if (ev.buttons) go(ev); };
  });
}

// ── keys ─────────────────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.target.matches?.("input, textarea, select, [contenteditable]")) return;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); zoomBy(1.2); }
  else if (mod && e.key === "-") { e.preventDefault(); zoomBy(1 / 1.2); }
  else if (mod && e.key === "0") { e.preventDefault(); zoomFit(); }
  else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); ann?.flush(); toast("Saved"); }
  else if (!mod && B.board?.kind === "pages" && (e.key === "]" || (root.classList.contains("is-present") && (e.key === "ArrowRight" || e.key === "PageDown" || e.key === " ")))) { e.preventDefault(); goPage(B.cur + 1); }
  else if (!mod && B.board?.kind === "pages" && (e.key === "[" || (root.classList.contains("is-present") && (e.key === "ArrowLeft" || e.key === "PageUp")))) { e.preventDefault(); goPage(B.cur - 1); }
});
window.addEventListener("beforeunload", (e) => {
  if (ann?.pending) { ann.flush(); e.preventDefault(); e.returnValue = ""; }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") { ann?.flush(); if (B.dirtyThumb) saveCover(true); }
});
window.addEventListener("resize", () => { clearTimeout(relayout._t); relayout._t = setTimeout(relayout, 120); });
window.addEventListener("online", () => toast("Back online — saving"));

// ── menus + dialogs ──────────────────────────────────────────────────────────
function menu(anchor, items) {
  document.querySelector(".wb-menu")?.remove();
  const m = document.createElement("div");
  m.className = "wb-menu";
  m.setAttribute("role", "menu");
  m.innerHTML = items.map((it) => it === "-" ? '<hr>' : `<button type="button" role="menuitem" ${it.disabled ? "disabled" : ""}>
    <span class="wb-mi-ic" aria-hidden="true">${it.icon || ""}</span><span><b>${esc(it.label)}</b>${it.hint ? `<small>${esc(it.hint)}</small>` : ""}</span>
    ${it.badge ? `<em>${esc(it.badge)}</em>` : ""}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${r.bottom + 6}px`;
  m.style.left = `${Math.max(8, Math.min(window.innerWidth - m.offsetWidth - 8, r.right - m.offsetWidth))}px`;
  const btns = [...m.querySelectorAll("button")];
  const acts = items.filter((it) => it !== "-");
  btns.forEach((b, i) => b.addEventListener("click", () => { m.remove(); acts[i].run(); }));
  btns[0]?.focus();
  const close = (e) => { if (!m.contains(e.target) && e.target !== anchor) { m.remove(); document.removeEventListener("pointerdown", close, true); } };
  setTimeout(() => document.addEventListener("pointerdown", close, true));
  m.addEventListener("keydown", (e) => {
    const i = btns.indexOf(document.activeElement);
    if (e.key === "Escape") { m.remove(); anchor.focus(); }
    if (e.key === "ArrowDown") { e.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
  });
}

function dialog(title, body, { wide = false } = {}) {
  document.querySelector(".wb-dlg-back")?.remove();
  const back = document.createElement("div");
  back.className = "wb-dlg-back";
  back.innerHTML = `<div class="wb-dlg${wide ? " is-wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <header><h2>${esc(title)}</h2><button type="button" class="wb-iconbtn" data-close aria-label="Close">${ic("x")}</button></header>
    <div class="wb-dlg-body">${body}</div></div>`;
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-close]")) close(); });
  back.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Escape") close(); });
  setTimeout(() => back.querySelector("input, button:not([data-close]), select")?.focus());
  return { el: back.querySelector(".wb-dlg"), close };
}

const pick = (accept, capture) => new Promise((res) => {
  const i = document.createElement("input");
  i.type = "file"; i.accept = accept;
  if (capture) i.capture = "environment";
  i.onchange = () => res(i.files?.[0] || null);
  i.click();
});

function curPageP() {
  return B.board.kind === "infinite" ? B.p : B.ps.get(B.pages[B.cur]?.id);
}

function insertItems() {
  const items = [
    { icon: "🖼️", label: "Image…", hint: "Or paste one with Ctrl+V, or drop it on the page", run: async () => { const f = await pick("image/*"); if (f) ann.insertImage(f, curPageP()); } },
    { icon: "📷", label: "Take a photo", hint: "Phone or tablet camera", run: async () => { const f = await pick("image/*", true); if (f) ann.insertImage(f, curPageP()); } },
    { icon: "🗒️", label: "Sticky note", run: () => { ann.setOpen(true); ann.setTool("note"); toast("Tap where the note should go"); } },
    { icon: "⭐", label: "Sticker or stamp", run: () => { ann.setOpen(true); document.querySelector('.ink-rail [data-tool="sticker"]')?.click(); } },
    { icon: "🔤", label: "Text box", run: () => { ann.setOpen(true); ann.setTool("text"); toast("Click where the text should start"); } },
    { icon: "📝", label: "Past-paper question", hint: "From a topical paper: open a question, then 'Work on whiteboard'", run: () => { location.href = "/my-papers"; } },
  ];
  if (B.board.kind === "pages") {
    items.push("-",
      { icon: "📄", label: "New page", run: () => addPage() },
      { icon: "📑", label: "Pages from a PDF…", hint: "Each PDF page becomes a page you can write on", badge: ST.pdfImport ? "" : "Paid plans",
        run: () => (ST.pdfImport ? importPdf() : upsell("Importing PDFs comes with any paid plan.")) });
  }
  return items;
}

async function importPdf() {
  const f = await pick("application/pdf");
  if (!f) return;
  toast("Adding the PDF pages…");
  const fd = new FormData();
  fd.append("file", f);
  try {
    await ann.flush();
    const d = await api("POST", `/api/wb/boards/${ST.board}/import-pdf`, fd);
    // simplest correct thing: reload the board with its new pages
    toast(`Added ${d.pages.length} page${d.pages.length === 1 ? "" : "s"}${d.skipped ? ` (${d.skipped} left out - boards hold up to 200 pages)` : ""}`);
    setTimeout(() => location.reload(), 600);
  } catch (e) { toast(e.message, "bad"); }
}

function upsell(msg) {
  dialog("Upgrade for more", `<p class="wb-dlg-p">${esc(msg)}</p>
    <p class="wb-dlg-p">Every paid plan gives you unlimited boards, 2 GB of images and PDF import.</p>
    <div class="wb-dlg-acts"><a class="wb-btn wb-btn-primary" href="/pricing.html">See plans</a></div>`);
}

async function insertQuestion(qid) {
  try {
    const r = await fetch(`/api/question/${encodeURIComponent(qid)}/preview`, { credentials: "same-origin" });
    if (!r.ok) throw new Error("That question couldn't be loaded");
    const blob = await r.blob();
    const p = B.board.kind === "infinite" ? B.p : B.ps.get(B.pages[0].id);
    await ann.insertImage(new File([blob], "question.png", { type: blob.type || "image/png" }), p,
                          B.board.kind === "infinite" ? null : [0.5, 0.22]);
    history.replaceState(null, "", location.pathname);
    ann.setTool("pen");
  } catch (e) { toast(e.message, "bad"); }
}

// ── paper (page settings) ────────────────────────────────────────────────────
function openPaper() {
  const inf = B.board.kind === "infinite";
  const pg = B.pages[B.cur];
  const s = inf ? boardSettings() : pageSettings(pg);
  const d = dialog(inf ? "Canvas" : "Paper", `
    <p class="wb-lbl">Colour</p>
    <div class="wb-papers">${Object.entries(PAPERS).map(([k, [n, hex]]) =>
      `<button type="button" data-paper="${k}" class="${s.paper === k ? "is-on" : ""}" style="--c:${hex}" title="${n}" aria-label="${n}"><span>${n}</span></button>`).join("")}</div>
    <p class="wb-lbl">Pattern</p>
    <div class="wb-patterns">${Object.entries(PATTERNS).filter(([k]) => !(inf && k === "axes")).map(([k, n]) =>
      `<button type="button" data-pattern="${k}" class="${s.pattern === k ? "is-on" : ""}"><canvas width="88" height="60" data-prev="${k}"></canvas><span>${n}</span></button>`).join("")}</div>
    ${inf ? "" : axesForm(s.ax)}
    ${inf ? "" : `<p class="wb-lbl">Size</p><div class="wb-seg">${Object.entries(SIZES).map(([k, z]) =>
      `<button type="button" data-size="${k}" class="${s.size === k ? "is-on" : ""}">${z.name}</button>`).join("")}</div>
    ${s.bg ? '<p class="wb-lbl">Background</p><button type="button" class="wb-btn" data-nobg>Remove the PDF / image background</button>' : ""}
    <p class="wb-lbl">Apply to</p>
    <div class="wb-seg" data-scope><button type="button" class="is-on" data-sc="page">This page</button><button type="button" data-sc="all">Every page</button></div>`}
    <div class="wb-dlg-acts"><button type="button" class="wb-btn wb-btn-primary" data-close>Done</button></div>`, { wide: true });
  const paintPrev = (paper) => d.el.querySelectorAll("[data-prev]").forEach((cv) => {
    const ctx = cv.getContext("2d");
    drawPattern(ctx, 88, 60, { paper, pattern: cv.dataset.prev }, 88 / 60);
  });
  paintPrev(s.paper);
  let scope = "page";
  const cur = { ...s };
  const axBox = d.el.querySelector(".wb-axes");
  const showAxes = () => { if (axBox) axBox.hidden = cur.pattern !== "axes"; };
  showAxes();
  if (axBox) {
    let t = null;
    const read = () => {
      const f = (n) => axBox.querySelector(`[name="${n}"]`);
      return { x0: f("x0").value, x1: f("x1").value, y0: f("y0").value, y1: f("y1").value, dx: f("dx").value, dy: f("dy").value,
               sub: Number(f("sub").value), eq: f("eq").checked, lab: f("lab").checked };
    };
    const commit = () => {
      const r = checkAxes(read());
      const err = axBox.querySelector(".wb-axes-err");
      err.textContent = r.error || "";
      if (r.error) return;
      cur.ax = r.ax;
      applySetting("ax", r.ax, scope);
    };
    axBox.addEventListener("input", () => { clearTimeout(t); t = setTimeout(commit, 450); });
    axBox.addEventListener("change", () => { clearTimeout(t); commit(); });
    axBox.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(t); commit(); } });
    axBox.querySelectorAll("[data-axpreset]").forEach((b) => b.addEventListener("click", () => {
      const p = AXES_PRESETS[b.dataset.axpreset];
      for (const [k, v] of Object.entries(p)) {
        const f = axBox.querySelector(`[name="${k}"]`);
        if (f) f.type === "checkbox" ? (f.checked = v) : (f.value = v);
      }
      commit();
    }));
  }
  d.el.addEventListener("click", async (e) => {
    const sc = e.target.closest("[data-sc]");
    if (sc) { scope = sc.dataset.sc; d.el.querySelectorAll("[data-sc]").forEach((x) => x.classList.toggle("is-on", x === sc)); return; }
    const t = e.target.closest("[data-paper], [data-pattern], [data-size], [data-nobg]");
    if (!t) return;
    const key = t.dataset.paper ? "paper" : t.dataset.pattern ? "pattern" : t.dataset.size ? "size" : "bg";
    const val = t.dataset.paper || t.dataset.pattern || t.dataset.size || null;
    cur[key] = val;
    if (key !== "bg") t.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("is-on", x === t));
    if (key === "paper") paintPrev(val);
    if (key === "pattern") {
      showAxes();
      if (val === "axes" && !cur.ax) { cur.ax = { ...AXES_DEFAULT }; await applySetting("ax", cur.ax, inf ? "all" : scope); }
    }
    await applySetting(key, val, inf ? "all" : scope);
    if (key === "bg") t.remove();
  });
}

// the graph-with-axes settings: ranges, what one big square is worth, small squares per big one
const AXES_PRESETS = {
  quad: { x0: -5, x1: 5, y0: -5, y1: 5, dx: 1, dy: 1, sub: 5, eq: true },
  first: { x0: 0, x1: 10, y0: 0, y1: 10, dx: 1, dy: 1, sub: 5, eq: true },
  trig: { x0: 0, x1: 360, y0: -2, y1: 2, dx: 30, dy: 0.5, sub: 5, eq: false },
  data: { x0: 0, x1: 100, y0: 0, y1: 50, dx: 10, dy: 5, sub: 5, eq: false },
};
function axesForm(a) {
  const v = { ...AXES_DEFAULT, ...(a || {}) };
  const num = (n, label) => `<label><span>${label}</span><input type="number" step="any" name="${n}" value="${esc(v[n])}" inputmode="decimal"></label>`;
  return `<fieldset class="wb-axes" hidden>
    <legend class="wb-lbl">Graph axes</legend>
    <div class="wb-axes-presets">
      <button type="button" class="wb-chip" data-axpreset="quad">−5 to 5</button>
      <button type="button" class="wb-chip" data-axpreset="first">0 to 10</button>
      <button type="button" class="wb-chip" data-axpreset="trig">Trig 0°–360°</button>
      <button type="button" class="wb-chip" data-axpreset="data">Data 0–100</button>
    </div>
    <div class="wb-axes-grid">
      <b>x</b>${num("x0", "from")}${num("x1", "to")}${num("dx", "1 big square =")}
      <b>y</b>${num("y0", "from")}${num("y1", "to")}${num("dy", "1 big square =")}
    </div>
    <div class="wb-axes-row">
      <label><span>Small squares in each big square</span>
        <select name="sub">${AXES_SUBS.map((n) => `<option value="${n}"${v.sub === n ? " selected" : ""}>${n === 1 ? "None" : `${n} × ${n}`}</option>`).join("")}</select></label>
      <label class="wb-check"><input type="checkbox" name="eq"${v.eq !== false ? " checked" : ""}> Same scale on both axes (square boxes)</label>
      <label class="wb-check"><input type="checkbox" name="lab"${v.lab !== false ? " checked" : ""}> Number the axes</label>
    </div>
    <p class="wb-axes-err" role="alert"></p>
  </fieldset>`;
}

async function applySetting(key, val, scope) {
  try {
    if (scope === "all") {
      const settings = { ...boardSettings(), [key]: val };
      if (val == null) delete settings[key];
      delete settings.bg;
      await api("PATCH", `/api/wb/boards/${ST.board}`, { settings });
      B.board.settings = settings;
      // page overrides of the same thing would hide the change: clear them
      await Promise.all(B.pages.filter((pg) => pg.settings && key in pg.settings).map(async (pg) => {
        const s2 = { ...pg.settings };
        delete s2[key];
        await api("PATCH", `/api/wb/boards/${ST.board}/pages/${pg.id}`, { settings: s2 });
        pg.settings = s2;
      }));
    } else {
      const pg = B.pages[B.cur];
      const s2 = { ...(pg.settings || {}), [key]: val };
      if (val == null) delete s2[key];
      const d = await api("PATCH", `/api/wb/boards/${ST.board}/pages/${pg.id}`, { settings: s2 });
      pg.settings = d.settings;
    }
    syncTheme();
    relayout();
    renderThumbs();
    B.dirtyThumb = true;
    scheduleCover();
  } catch (e) { toast(e.message, "bad"); }
}

// ── share ────────────────────────────────────────────────────────────────────
async function openShare() {
  if (B.readonly) return;
  const d = dialog("Share this board", '<p class="wb-dlg-p">Loading…</p>', { wide: true });
  let shares = [], me = B.me;
  try {
    [shares, me] = await Promise.all([api("GET", `/api/wb/boards/${ST.board}/shares`).then((x) => x.shares),
                                      me || api("GET", "/api/wb/me")]);
    B.me = me;
  } catch (e) { d.el.querySelector(".wb-dlg-body").innerHTML = `<p class="wb-dlg-p">${esc(e.message)}</p>`; return; }
  const body = d.el.querySelector(".wb-dlg-body");
  const paint = () => {
    body.innerHTML = `
      ${me.has_teacher ? `<label class="wb-check"><input type="checkbox" data-teacher ${B.board.shared_with_teacher ? "checked" : ""}>
        <span><b>Send to my teacher</b><small>Your teacher can open this board (they can't change it).</small></span></label>` : ""}
      <p class="wb-lbl">Make a link</p>
      <div class="wb-row">
        <select data-role aria-label="What people with the link can do"><option value="view">Anyone with the link can view</option>
          <option value="copy">… view and make their own copy</option></select>
        <select data-days aria-label="Link expiry"><option value="">Never expires</option><option value="7">Expires in 7 days</option><option value="30">Expires in 30 days</option></select>
        <button type="button" class="wb-btn wb-btn-primary" data-mk>Create link</button>
      </div>
      <p class="wb-lbl">${shares.length ? "Links that work now" : "No links yet"}</p>
      <ul class="wb-links">${shares.map((s) => `<li><code>${esc(location.origin)}/whiteboard/s/${esc(s.token)}</code>
        <span class="wb-tag">${s.role === "copy" ? "View + copy" : "View only"}${s.expires_at ? ` · until ${new Date(s.expires_at).toLocaleDateString()}` : ""}</span>
        <button type="button" class="wb-btn" data-cp="${esc(s.token)}">Copy</button>
        <button type="button" class="wb-btn wb-btn-ghost" data-off="${esc(s.token)}">Switch off</button></li>`).join("")}</ul>`;
  };
  paint();
  body.addEventListener("change", async (e) => {
    if (!e.target.matches("[data-teacher]")) return;
    try {
      await api("PATCH", `/api/wb/boards/${ST.board}`, { shared_with_teacher: e.target.checked });
      B.board.shared_with_teacher = e.target.checked;
      toast(e.target.checked ? "Your teacher can now open this board" : "No longer shared with your teacher");
    } catch (err) { toast(err.message, "bad"); }
  });
  body.addEventListener("click", async (e) => {
    const cp = e.target.closest("[data-cp]"), off = e.target.closest("[data-off]");
    try {
      if (e.target.closest("[data-mk]")) {
        const s = await api("POST", `/api/wb/boards/${ST.board}/shares`,
          { role: body.querySelector("[data-role]").value, days: +body.querySelector("[data-days]").value || null });
        shares.unshift(s);
        paint();
        await navigator.clipboard?.writeText(`${location.origin}${s.url}`).catch(() => {});
        toast("Link created and copied");
      } else if (cp) {
        await navigator.clipboard.writeText(`${location.origin}/whiteboard/s/${cp.dataset.cp}`);
        toast("Link copied");
      } else if (off) {
        await api("DELETE", `/api/wb/shares/${off.dataset.off}`);
        shares = shares.filter((s) => s.token !== off.dataset.off);
        paint();
        toast("That link no longer works");
      }
    } catch (err) { toast(err.message, "bad"); }
  });
}

async function copyBoard() {
  if (!ST.signedIn) { location.href = `/login.html?next=${encodeURIComponent(location.pathname)}`; return; }
  if (ST.role !== "copy") return toast("This link is view-only");
  try {
    const b = await api("POST", `/api/wb/shared/${ST.share}/copy`);
    location.href = `/whiteboard/${b.id}`;
  } catch (e) { if (e.code === "wb_limit") upsell(e.message); else toast(e.message, "bad"); }
}

// ── export ───────────────────────────────────────────────────────────────────
function exportUrl(pages) {
  const q = new URLSearchParams();
  if (ST.share) q.set("s", ST.share);
  if (pages) q.set("pages", pages);
  return `/api/wb/boards/${ST.board}/export.pdf${q.toString() ? `?${q}` : ""}`;
}
function exportItems() {
  const inf = B.board.kind === "infinite";
  const items = [
    { icon: "📄", label: inf ? "Download as PDF" : "Download PDF (all pages)", run: () => download(exportUrl()) },
  ];
  if (!inf) items.push({ icon: "📃", label: "This page as PDF", run: () => download(exportUrl(B.pages[B.cur].id)) });
  items.push({ icon: "🖼️", label: inf ? "What you can see, as PNG" : "This page as PNG", run: exportPng },
             { icon: "🖨️", label: "Print", run: printBoard });
  return items;
}
async function download(url) {
  toast("Preparing your PDF…");
  await ann.flush();
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
async function exportPng() {
  let cv;
  if (B.board.kind === "infinite") {
    const r = infEl.getBoundingClientRect(), dpr = 2;
    cv = document.createElement("canvas");
    cv.width = r.width * dpr; cv.height = r.height * dpr;
    const ctx = cv.getContext("2d");
    ctx.drawImage(infEl.querySelector(".wb-pat"), 0, 0, cv.width, cv.height);
    const c = B.p.cam, w = BASE * c.z;
    ctx.setTransform(dpr, 0, 0, dpr, -c.x * w * dpr, -c.y * w * dpr);
    ann.render(ctx, pageStrokes(B.pages[0].id), w, w);
  } else cv = renderPage(B.pages[B.cur], 1240, 2);
  cv.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(B.board.title || "board").replace(/[^A-Za-z0-9]+/g, "-")}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }, "image/png");
}
async function printBoard() {
  toast("Getting it ready to print…");
  await ann.flush();
  try {
    const r = await fetch(exportUrl(), { credentials: "same-origin" });
    if (!r.ok) throw new Error("Couldn't make the PDF");
    const url = URL.createObjectURL(await r.blob());
    const f = document.createElement("iframe");
    f.className = "wb-print";
    f.src = url;
    f.onload = () => { try { f.contentWindow.focus(); f.contentWindow.print(); } catch { window.open(url); } };
    document.body.appendChild(f);
  } catch (e) { toast(e.message, "bad"); }
}

// ── present ──────────────────────────────────────────────────────────────────
function present(on) {
  root.classList.toggle("is-present", on);
  let bar = document.querySelector(".wb-pres");
  if (on) {
    document.documentElement.requestFullscreen?.().catch(() => {});
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "wb-pres";
      bar.innerHTML = `${B.board.kind === "pages" ? `<button type="button" data-p="prev" aria-label="Previous page">${ic("prev")}</button>
        <span class="wb-pres-n"></span><button type="button" data-p="next" aria-label="Next page">${ic("next")}</button>` : ""}
        <button type="button" data-p="laser" aria-pressed="true">Laser</button>
        <button type="button" data-p="exit">${ic("x")} Exit</button>`;
      document.body.appendChild(bar);
      bar.addEventListener("click", (e) => {
        const k = e.target.closest("[data-p]")?.dataset.p;
        if (k === "prev") goPage(B.cur - 1);
        if (k === "next") goPage(B.cur + 1);
        if (k === "exit") present(false);
        if (k === "laser") {
          const on2 = ann.tool !== "laser";
          ann.setTool(on2 ? "laser" : "pointer");
          e.target.setAttribute("aria-pressed", String(on2));
        }
      });
    }
    present._prev = ann.tool;
    ann.setTool("laser");
    if (B.board.kind === "pages") {
      const st = stage();
      const pg = B.els.get(B.pages[B.cur].id);
      const sz = sizeOf(pageSettings(B.pages[B.cur]));
      B.zoomBefore = B.zoom;
      setTimeout(() => {
        B.zoom = Math.min(3, (st.clientHeight - 24) / ((baseWidth() * sz.h) / sz.w));
        relayout();
        pg.scrollIntoView({ block: "start" });
      }, 250);
    }
    const n = () => { const el = document.querySelector(".wb-pres-n"); if (el) el.textContent = `${B.cur + 1} / ${B.pages.length}`; };
    n();
    stage().addEventListener("scroll", n, { passive: true });
  } else {
    bar?.remove();
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    ann.setTool(present._prev && present._prev !== "laser" ? present._prev : "pointer");
    if (B.zoomBefore) { B.zoom = B.zoomBefore; B.zoomBefore = null; setTimeout(relayout, 250); }
  }
}
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && root.classList.contains("is-present")) present(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && root.classList.contains("is-present")) present(false); });

// ── dashboard cover (thumbnail) ──────────────────────────────────────────────
function scheduleCover() {
  if (B.readonly) return;
  clearTimeout(scheduleCover._t);
  scheduleCover._t = setTimeout(() => saveCover(false), 20000);
}
async function saveCover(leaving) {
  if (B.readonly || !B.dirtyThumb || !ann) return;
  B.dirtyThumb = false;
  let cv;
  if (B.board.kind === "infinite") {
    cv = document.createElement("canvas");
    cv.width = 360; cv.height = 240;
    const ctx = cv.getContext("2d");
    ctx.fillStyle = paperHex(boardSettings());
    ctx.fillRect(0, 0, 360, 240);
    const b = contentBox();
    if (b) {
      const k = Math.min(360 / (b[2] - b[0]), 240 / (b[3] - b[1])) * 0.86;
      ctx.translate((360 - (b[2] - b[0]) * k) / 2 - b[0] * k, (240 - (b[3] - b[1]) * k) / 2 - b[1] * k);
      ann.render(ctx, pageStrokes(B.pages[0].id), k, k);
    }
  } else cv = renderPage(B.pages[0], 300, 1);
  const blob = await new Promise((r) => cv.toBlob(r, "image/webp", 0.8)) || await new Promise((r) => cv.toBlob(r, "image/png"));
  if (!blob) return;
  const fd = new FormData();
  fd.append("file", blob, "cover.webp");
  try {
    const r = await fetch("/api/ink/assets", { method: "POST", body: fd, credentials: "same-origin", keepalive: leaving && blob.size < 60000 });
    if (!r.ok) return;
    const { url } = await r.json();
    await fetch(`/api/wb/boards/${ST.board}`, { method: "PATCH", credentials: "same-origin", keepalive: leaving,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ thumb: url }) });
  } catch { /* the cover is only a nicety */ }
}

start();
