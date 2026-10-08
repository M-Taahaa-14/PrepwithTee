/* board/boards.js — the PrepWithTee Board dashboard (/whiteboard).
 *
 * Left: New board · Home · Recent · Starred · From my students (teachers) ·
 * Trash · Folders · usage (free: n of 3 boards). Main: a template strip
 * (blank, lined, squared, graph, dotted, isometric, Cornell, construction,
 * lesson plan, planner, infinite canvas, chalkboard), then the boards as cards
 * (cover, name, pages, last edit, star, ⋯ menu: open, rename, duplicate,
 * move to folder, share, download PDF, trash / restore / delete forever).
 * Search, sort (recent / name / created), grid or list.
 */
import { PAPERS, drawPattern, paperHex, AXES_DEFAULT } from "/board/paper.js?v=20261008b";

const ST = JSON.parse(document.getElementById("wbd-state").textContent);
const root = document.getElementById("wbd");
const V = { view: "home", folder: null, q: "", sort: "recent", layout: "grid", boards: [], folders: [], me: null, students: [] };
try { Object.assign(V, JSON.parse(localStorage.getItem("wbd-prefs") || "{}")); } catch { /* ignore */ }
V.view = "home"; V.folder = null; V.q = "";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const TPL = [
  ["blank", "Blank", { pattern: "plain", paper: "white" }], ["lined", "Lined", { pattern: "lined", paper: "white" }],
  ["squared", "Maths squared", { pattern: "squared", paper: "white" }], ["graph", "Graph paper", { pattern: "graph", paper: "white" }],
  ["axes", "Graph with axes", { pattern: "axes", paper: "white", ax: AXES_DEFAULT }],
  ["dotted", "Dotted", { pattern: "dotted", paper: "cream" }], ["isometric", "Isometric", { pattern: "isometric", paper: "white" }],
  ["cornell", "Cornell notes", { pattern: "cornell", paper: "white" }], ["construction", "Constructions", { pattern: "plain", paper: "white" }],
  ["lesson", "Lesson plan", { pattern: "lined", paper: "white" }], ["planner", "Weekly planner", { pattern: "plain", paper: "cream", size: "a4l" }],
  ["infinite", "Infinite canvas", { pattern: "dotted", paper: "white" }, true], ["chalk", "Chalkboard", { pattern: "plain", paper: "chalk" }, true],
];
const I = {
  plus: '<path d="M12 5v14M5 12h14"/>', home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  trash: '<path d="M4 7h16"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>', folder: '<path d="M3 6h6l2 2h10v11H3z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><path d="M16 4.5a3.5 3.5 0 010 7M21.5 20a6.5 6.5 0 00-4-6"/>',
  dots: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>', inf: '<path d="M7 9a3 3 0 100 6c2 0 3-1.5 5-3s3-3 5-3a3 3 0 110 6c-2 0-3-1.5-5-3S9 9 7 9z"/>',
  pages: '<path d="M7 3h9l4 4v12H7z"/><path d="M4 7v14h12"/>',
};
const ic = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${I[k]}</svg>`;

async function api(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await r.json(); } catch { /* none */ }
  if (!r.ok) {
    const d = data?.detail;
    const e = new Error(typeof d === "string" ? d : d?.message || `Something went wrong (${r.status})`);
    e.code = d?.code; e.status = r.status;
    throw e;
  }
  return data;
}

function toast(msg, bad = false) {
  let t = document.querySelector(".wbd-toast");
  if (!t) { t = document.createElement("div"); t.className = "wbd-toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg;
  t.classList.toggle("is-bad", bad);
  t.classList.add("is-on");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("is-on"), 2800);
}

const ago = (iso) => {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const keep = () => { try { localStorage.setItem("wbd-prefs", JSON.stringify({ sort: V.sort, layout: V.layout })); } catch { /* ignore */ } };

async function load() {
  try {
    const [b, me] = await Promise.all([api("GET", "/api/wb/boards"), api("GET", "/api/wb/me")]);
    V.boards = b.boards; V.folders = b.folders; V.me = me;
    if (me.role === "teacher") V.students = (await api("GET", "/api/wb/students").catch(() => ({ boards: [] }))).boards;
  } catch (e) {
    root.innerHTML = `<p class="wbd-loading">${esc(e.message)} — <a href="/whiteboard">try again</a></p>`;
    return;
  }
  const qs = new URLSearchParams(location.search);
  if (qs.get("full")) setTimeout(() => limitDialog(`Free accounts can keep ${V.me.limits.boards} boards.`), 50);
  if (qs.get("missing")) toast("That board isn't available any more", true);
  if (qs.toString()) history.replaceState(null, "", "/whiteboard");
  render();
}

// ── render ───────────────────────────────────────────────────────────────────
function visible() {
  let list = V.view === "students" ? V.students : V.boards;
  if (V.view === "trash") list = list.filter((b) => b.deleted_at);
  else if (V.view !== "students") list = list.filter((b) => !b.deleted_at);
  if (V.view === "starred") list = list.filter((b) => b.starred);
  if (V.view === "folder") list = list.filter((b) => b.folder_id === V.folder);
  if (V.view === "recent") list = [...list].sort((a, b) => (b.opened_at || "").localeCompare(a.opened_at || "")).slice(0, 12);
  if (V.q) { const q = V.q.toLowerCase(); list = list.filter((b) => (b.title || "").toLowerCase().includes(q) || (b.student || "").toLowerCase().includes(q)); }
  if (V.view !== "recent") {
    const by = { recent: (a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""),
                 name: (a, b) => (a.title || "").localeCompare(b.title || ""),
                 created: (a, b) => (b.created_at || "").localeCompare(a.created_at || "") }[V.sort];
    list = [...list].sort(by);
  }
  return list;
}

function heading() {
  if (V.view === "folder") return V.folders.find((f) => f.id === V.folder)?.name || "Folder";
  return { home: "My boards", recent: "Recently opened", starred: "Starred", trash: "Trash", students: "From my students" }[V.view];
}

function render() {
  const live = V.boards.filter((b) => !b.deleted_at).length, trash = V.boards.length - live;
  const lim = V.me.limits;
  const pct = lim.boards ? Math.min(100, (live / lim.boards) * 100) : 0;
  const mb = (V.me.bytes / 1048576).toFixed(1), cap = lim.bytes >= 1073741824 ? `${lim.bytes / 1073741824} GB` : `${lim.bytes / 1048576} MB`;
  const nav = (view, icon, label, count = "", extra = "") =>
    `<button type="button" class="wbd-nav-it${V.view === view && !extra ? " is-on" : ""}" data-view="${view}" ${extra}>${ic(icon)}<span>${label}</span>${count !== "" ? `<em>${count}</em>` : ""}</button>`;
  const list = visible();
  root.dataset.state = "ready";
  root.innerHTML = `
    <aside class="wbd-side">
      <button type="button" class="wbd-new" data-new>${ic("plus")} New board</button>
      <nav class="wbd-nav" aria-label="Boards">
        ${nav("home", "home", "All boards", live)}
        ${nav("recent", "clock", "Recent")}
        ${nav("starred", "star", "Starred", V.boards.filter((b) => b.starred && !b.deleted_at).length || "")}
        ${V.me.role === "teacher" ? nav("students", "users", "From my students", V.students.length || "") : ""}
        ${nav("trash", "trash", "Trash", trash || "")}
      </nav>
      <div class="wbd-folders">
        <div class="wbd-fold-head"><span>Folders</span><button type="button" class="wbd-mini" data-newfolder aria-label="New folder" title="New folder">${ic("plus")}</button></div>
        ${V.folders.map((f) => `<button type="button" class="wbd-nav-it wbd-folder${V.view === "folder" && V.folder === f.id ? " is-on" : ""}" data-folder="${f.id}" data-tone="${esc(f.color || "violet")}">
          ${ic("folder")}<span>${esc(f.name)}</span><em>${V.boards.filter((b) => b.folder_id === f.id && !b.deleted_at).length || ""}</em></button>`).join("") ||
          '<p class="wbd-hint">Group boards by subject or topic.</p>'}
      </div>
      <div class="wbd-usage">
        ${lim.boards ? `<div class="wbd-usage-row"><b>${live} of ${lim.boards} boards</b><span>Free plan</span></div>
          <div class="wbd-bar"><i style="width:${pct}%"></i></div>` : `<div class="wbd-usage-row"><b>Unlimited boards</b><span>${lim.paid ? "Your plan" : ""}</span></div>`}
        <p class="wbd-hint">${mb} MB of ${cap} images used</p>
        ${lim.paid ? "" : '<a class="wbd-up" href="/pricing.html">Upgrade for unlimited →</a>'}
      </div>
    </aside>
    <section class="wbd-main">
      <header class="wbd-head">
        <div><p class="wbd-eyebrow">PrepWithTee Board</p><h1>${esc(heading())}</h1></div>
        <div class="wbd-tools">
          <label class="wbd-search">${ic("search")}<input type="search" placeholder="Search boards" value="${esc(V.q)}" aria-label="Search boards"></label>
          <select class="wbd-sort" aria-label="Sort"><option value="recent">Last edited</option><option value="name">Name</option><option value="created">Date created</option></select>
          <div class="wbd-layout" role="group" aria-label="Layout">
            <button type="button" data-layout="grid" aria-pressed="${V.layout === "grid"}" aria-label="Grid">${ic("grid")}</button>
            <button type="button" data-layout="list" aria-pressed="${V.layout === "list"}" aria-label="List">${ic("list")}</button>
          </div>
        </div>
      </header>
      ${V.view === "home" || V.view === "folder" ? `<div class="wbd-tpl-head"><h2>Start something new</h2></div>
        <div class="wbd-tpls">${TPL.map(([k, n, s, inf]) => `<button type="button" class="wbd-tpl" data-tpl="${k}">
          <canvas width="132" height="92" data-tplprev="${k}"></canvas>${inf ? `<i class="wbd-tpl-inf" title="Infinite canvas">${ic("inf")}</i>` : ""}<span>${n}</span></button>`).join("")}</div>` : ""}
      ${V.view === "trash" && list.length ? '<div class="wbd-trashbar"><span>Boards in the trash are deleted for good after 30 days.</span><button type="button" class="wbd-btn wbd-btn-danger" data-empty>Empty trash</button></div>' : ""}
      ${list.length ? `<div class="wbd-boards is-${V.layout}">${list.map(card).join("")}</div>` : empty()}
    </section>`;
  root.querySelector(".wbd-sort").value = V.sort;
  root.querySelectorAll("[data-tplprev]").forEach((cv) => {
    const t = TPL.find((x) => x[0] === cv.dataset.tplprev);
    drawPattern(cv.getContext("2d"), 132, 92, t[2], 132 / 90);
    if (t[0] === "lesson" || t[0] === "planner" || t[0] === "construction") decorate(cv.getContext("2d"), t[0]);
  });
  root.querySelectorAll("[data-cover]").forEach((cv) => {
    const b = V.boards.find((x) => x.id === cv.dataset.cover) || V.students.find((x) => x.id === cv.dataset.cover);
    drawPattern(cv.getContext("2d"), cv.width, cv.height, b?.settings || {}, cv.width / 120);
  });
}

function decorate(ctx, k) {
  ctx.fillStyle = "#7e22ce";
  if (k === "lesson") { ctx.fillRect(14, 10, 50, 5); ctx.fillStyle = "#1d4ed8"; [28, 48, 68].forEach((y) => ctx.fillRect(14, y, 34, 3)); }
  if (k === "planner") {
    ctx.strokeStyle = "#94a3b8"; ctx.lineWidth = 1;
    for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) ctx.strokeRect(8 + i * 30, 14 + j * 38, 26, 34);
    ctx.fillRect(8, 5, 40, 4);
  }
  if (k === "construction") {
    ctx.strokeStyle = "#1d4ed8"; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(30, 66); ctx.lineTo(100, 66); ctx.stroke();
    ctx.beginPath(); ctx.arc(30, 66, 45, -1.25, -0.6); ctx.stroke();
    ctx.beginPath(); ctx.arc(100, 66, 45, -2.55, -1.9); ctx.stroke();
  }
}

function card(b) {
  const trash = !!b.deleted_at, stu = V.view === "students";
  return `<article class="wbd-card" data-id="${b.id}">
    <a class="wbd-cover" href="/whiteboard/${b.id}" ${trash ? 'data-trashopen' : ""} aria-label="Open ${esc(b.title)}">
      ${b.thumb ? `<img src="${esc(b.thumb)}" alt="" loading="lazy">` : `<canvas width="240" height="150" data-cover="${b.id}"></canvas>`}
      <span class="wbd-kind" title="${b.kind === "infinite" ? "Infinite canvas" : `${b.pages} page${b.pages === 1 ? "" : "s"}`}">${ic(b.kind === "infinite" ? "inf" : "pages")}${b.kind === "infinite" ? "" : b.pages}</span>
    </a>
    <div class="wbd-card-body">
      <div class="wbd-card-txt">
        <h3 title="${esc(b.title)}">${esc(b.title)}</h3>
        <p>${stu ? `${esc(b.student)} · ` : ""}${trash ? `Deleted ${ago(b.deleted_at)}` : `Edited ${ago(b.updated_at)}`}</p>
      </div>
      ${stu || trash ? "" : `<button type="button" class="wbd-star${b.starred ? " is-on" : ""}" data-star aria-pressed="${!!b.starred}" aria-label="${b.starred ? "Unstar" : "Star"}" title="${b.starred ? "Unstar" : "Star"}">${ic("star")}</button>`}
      ${stu ? "" : `<button type="button" class="wbd-more" data-more aria-haspopup="true" aria-label="More for ${esc(b.title)}">${ic("dots")}</button>`}
    </div>
  </article>`;
}

function empty() {
  const msg = { home: ["No boards yet", "Pick a template above to start your first board."],
    recent: ["Nothing opened yet", "Boards you open show up here."],
    starred: ["No starred boards", "Star the boards you use most to keep them here."],
    trash: ["The trash is empty", "Deleted boards wait here for 30 days."],
    folder: ["This folder is empty", "Make a board here with a template above, or move one in from its ⋯ menu."],
    students: ["Nothing from your students yet", "When a student uses “Send to my teacher” on a board, it appears here."] }[V.view];
  return `<div class="wbd-empty">${V.q ? `<h2>No boards match “${esc(V.q)}”</h2>` : `<h2>${msg[0]}</h2><p>${msg[1]}</p>`}</div>`;
}

// ── actions ──────────────────────────────────────────────────────────────────
root.addEventListener("click", async (e) => {
  const t = e.target;
  const v = t.closest("[data-view]");
  if (v) { V.view = v.dataset.view; V.folder = null; return render(); }
  const f = t.closest("[data-folder]");
  if (f) { V.view = "folder"; V.folder = f.dataset.folder; return render(); }
  const ly = t.closest("[data-layout]");
  if (ly) { V.layout = ly.dataset.layout; keep(); return render(); }
  if (t.closest("[data-new]")) return newDialog();
  if (t.closest("[data-newfolder]")) return folderDialog();
  const tpl = t.closest("[data-tpl]");
  if (tpl) return create(tpl.dataset.tpl);
  if (t.closest("[data-empty]")) return emptyTrash();
  const cardEl = t.closest(".wbd-card");
  if (!cardEl) return;
  const b = V.boards.find((x) => x.id === cardEl.dataset.id) || V.students.find((x) => x.id === cardEl.dataset.id);
  if (t.closest("[data-trashopen]")) { e.preventDefault(); return toast("Restore it from its ⋯ menu to open it"); }
  if (t.closest("[data-star]")) {
    b.starred = !b.starred;
    render();
    api("PATCH", `/api/wb/boards/${b.id}`, { starred: b.starred }).catch((err) => toast(err.message, true));
    return;
  }
  const more = t.closest("[data-more]");
  if (more) return menu(more, b.deleted_at ? trashItems(b) : boardItems(b));
});
root.addEventListener("input", (e) => {
  if (!e.target.matches(".wbd-search input")) return;
  V.q = e.target.value;
  const pos = e.target.selectionStart;
  render();
  const i = root.querySelector(".wbd-search input");
  i.focus(); i.setSelectionRange(pos, pos);
});
root.addEventListener("change", (e) => { if (e.target.matches(".wbd-sort")) { V.sort = e.target.value; keep(); render(); } });
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !e.target.matches("input, textarea, select")) { e.preventDefault(); root.querySelector(".wbd-search input")?.focus(); }
});

async function create(template, title = "") {
  try {
    const b = await api("POST", "/api/wb/boards", { template, title, folder_id: V.view === "folder" ? V.folder : null });
    location.href = `/whiteboard/${b.id}`;
  } catch (e) {
    if (e.code === "wb_limit") limitDialog(e.message); else toast(e.message, true);
  }
}

function boardItems(b) {
  return [
    { label: "Open", run: () => { location.href = `/whiteboard/${b.id}`; } },
    { label: "Rename", run: () => renameDialog(b) },
    { label: "Duplicate", run: async () => {
      try { const c = await api("POST", `/api/wb/boards/${b.id}/duplicate`); V.boards.unshift(c); render(); toast("Copy made"); }
      catch (e) { if (e.code === "wb_limit") limitDialog(e.message); else toast(e.message, true); } } },
    { label: "Move to folder…", run: () => moveDialog(b) },
    { label: "Share…", run: () => { location.href = `/whiteboard/${b.id}?share=1`; } },
    { label: "Download PDF", run: () => { location.href = `/api/wb/boards/${b.id}/export.pdf`; } },
    "-",
    { label: "Move to trash", danger: true, run: async () => {
      try { await api("DELETE", `/api/wb/boards/${b.id}`); b.deleted_at = new Date().toISOString(); render(); toast("Moved to the trash"); }
      catch (e) { toast(e.message, true); } } },
  ];
}
function trashItems(b) {
  return [
    { label: "Restore", run: async () => {
      try { const r = await api("POST", `/api/wb/boards/${b.id}/restore`); Object.assign(b, r); render(); toast("Restored"); }
      catch (e) { if (e.code === "wb_limit") limitDialog(e.message); else toast(e.message, true); } } },
    { label: "Delete forever", danger: true, run: async () => {
      if (!confirm(`Delete “${b.title}” for good? This can't be undone.`)) return;
      try { await api("DELETE", `/api/wb/boards/${b.id}?purge=1`); V.boards = V.boards.filter((x) => x !== b); render(); }
      catch (e) { toast(e.message, true); } } },
  ];
}
async function emptyTrash() {
  const t = V.boards.filter((b) => b.deleted_at);
  if (!confirm(`Delete ${t.length} board${t.length === 1 ? "" : "s"} for good? This can't be undone.`)) return;
  for (const b of t) { try { await api("DELETE", `/api/wb/boards/${b.id}?purge=1`); V.boards = V.boards.filter((x) => x !== b); } catch { /* keep going */ } }
  render();
  toast("Trash emptied");
}

function menu(anchor, items) {
  document.querySelector(".wbd-menu")?.remove();
  const m = document.createElement("div");
  m.className = "wbd-menu";
  m.setAttribute("role", "menu");
  m.innerHTML = items.map((it) => it === "-" ? "<hr>" : `<button type="button" role="menuitem" class="${it.danger ? "is-danger" : ""}">${esc(it.label)}</button>`).join("");
  document.body.appendChild(m);
  const r = anchor.getBoundingClientRect();
  m.style.top = `${Math.min(window.innerHeight - m.offsetHeight - 8, r.bottom + 4)}px`;
  m.style.left = `${Math.max(8, Math.min(window.innerWidth - m.offsetWidth - 8, r.right - m.offsetWidth))}px`;
  const acts = items.filter((x) => x !== "-");
  const btns = [...m.querySelectorAll("button")];
  btns.forEach((b, i) => b.addEventListener("click", () => { m.remove(); acts[i].run(); }));
  btns[0]?.focus();
  m.addEventListener("keydown", (e) => {
    const i = btns.indexOf(document.activeElement);
    if (e.key === "Escape") { m.remove(); anchor.focus(); }
    if (e.key === "ArrowDown") { e.preventDefault(); btns[(i + 1) % btns.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); btns[(i - 1 + btns.length) % btns.length].focus(); }
  });
  const close = (e) => { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("pointerdown", close, true); } };
  setTimeout(() => document.addEventListener("pointerdown", close, true));
}

function dialog(title, body) {
  document.querySelector(".wbd-dlg-back")?.remove();
  const back = document.createElement("div");
  back.className = "wbd-dlg-back";
  back.innerHTML = `<form class="wbd-dlg" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h2>${esc(title)}</h2>${body}</form>`;
  document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-cancel]")) close(); });
  back.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  setTimeout(() => back.querySelector("input, select, button")?.focus());
  return { form: back.querySelector("form"), close };
}

function newDialog() {
  const d = dialog("New board", `
    <label class="wbd-field"><span>Name</span><input name="title" maxlength="120" placeholder="e.g. Circle theorems"></label>
    <span class="wbd-field-lbl">Start from</span>
    <div class="wbd-pick">${TPL.map(([k, n], i) => `<label><input type="radio" name="tpl" value="${k}" ${i === 0 ? "checked" : ""}><span>${n}</span></label>`).join("")}</div>
    <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Cancel</button><button class="wbd-btn wbd-btn-primary">Create board</button></div>`);
  d.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(d.form);
    d.close();
    create(fd.get("tpl"), String(fd.get("title") || ""));
  });
}

function renameDialog(b) {
  const d = dialog("Rename board", `<label class="wbd-field"><span>Name</span><input name="title" maxlength="120" value="${esc(b.title)}" required></label>
    <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Cancel</button><button class="wbd-btn wbd-btn-primary">Save</button></div>`);
  d.form.querySelector("input").select();
  d.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = String(new FormData(d.form).get("title") || "").trim();
    d.close();
    if (!title) return;
    try { Object.assign(b, await api("PATCH", `/api/wb/boards/${b.id}`, { title })); render(); }
    catch (err) { toast(err.message, true); }
  });
}

function moveDialog(b) {
  const d = dialog("Move to folder", `<div class="wbd-pick is-col">
      <label><input type="radio" name="f" value="" ${!b.folder_id ? "checked" : ""}><span>No folder</span></label>
      ${V.folders.map((f) => `<label><input type="radio" name="f" value="${f.id}" ${b.folder_id === f.id ? "checked" : ""}><span>${esc(f.name)}</span></label>`).join("")}
    </div>
    <button type="button" class="wbd-link" data-nf>+ New folder</button>
    <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Cancel</button><button class="wbd-btn wbd-btn-primary">Move</button></div>`);
  d.form.querySelector("[data-nf]").addEventListener("click", () => { d.close(); folderDialog(b); });
  d.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fid = new FormData(d.form).get("f") || null;
    d.close();
    try { Object.assign(b, await api("PATCH", `/api/wb/boards/${b.id}`, { folder_id: fid, move: true })); render(); toast("Moved"); }
    catch (err) { toast(err.message, true); }
  });
}

function folderDialog(moveBoard = null) {
  const tones = ["violet", "sky", "teal", "amber", "rose", "grey"];
  const d = dialog("New folder", `<label class="wbd-field"><span>Name</span><input name="name" maxlength="60" required placeholder="e.g. Physics — Forces"></label>
    <span class="wbd-field-lbl">Colour</span>
    <div class="wbd-tones">${tones.map((t, i) => `<label data-tone="${t}"><input type="radio" name="color" value="${t}" ${i === 0 ? "checked" : ""}><i></i></label>`).join("")}</div>
    <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Cancel</button><button class="wbd-btn wbd-btn-primary">Create</button></div>`);
  d.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(d.form);
    d.close();
    try {
      const f = await api("POST", "/api/wb/folders", { name: fd.get("name"), color: fd.get("color") });
      V.folders.push(f);
      if (moveBoard) Object.assign(moveBoard, await api("PATCH", `/api/wb/boards/${moveBoard.id}`, { folder_id: f.id, move: true }));
      V.view = "folder"; V.folder = f.id;
      render();
    } catch (err) { toast(err.message, true); }
  });
}

function limitDialog(msg) {
  const d = dialog("You've used your free boards", `<p class="wbd-p">${esc(msg)}</p>
    <p class="wbd-p">Any paid plan gives you <b>unlimited boards</b>, 2 GB of images and PDF import - alongside everything else on PrepWithTee.</p>
    <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Not now</button><a class="wbd-btn wbd-btn-primary" href="/pricing.html">See plans</a></div>`);
  d.form.addEventListener("submit", (e) => e.preventDefault());
}

// folder rename / delete: right-click a folder
root.addEventListener("contextmenu", (e) => {
  const f = e.target.closest("[data-folder]");
  if (!f) return;
  e.preventDefault();
  const folder = V.folders.find((x) => x.id === f.dataset.folder);
  menu(f, [
    { label: "Rename folder", run: () => {
      const d = dialog("Rename folder", `<label class="wbd-field"><span>Name</span><input name="name" maxlength="60" value="${esc(folder.name)}" required></label>
        <div class="wbd-dlg-acts"><button type="button" class="wbd-btn" data-cancel>Cancel</button><button class="wbd-btn wbd-btn-primary">Save</button></div>`);
      d.form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const name = new FormData(d.form).get("name");
        d.close();
        try { Object.assign(folder, await api("PATCH", `/api/wb/folders/${folder.id}`, { name })); render(); } catch (err) { toast(err.message, true); }
      });
    } },
    { label: "Delete folder (boards stay)", danger: true, run: async () => {
      try {
        await api("DELETE", `/api/wb/folders/${folder.id}`);
        V.folders = V.folders.filter((x) => x !== folder);
        V.boards.forEach((b) => { if (b.folder_id === folder.id) b.folder_id = null; });
        if (V.folder === folder.id) { V.view = "home"; V.folder = null; }
        render();
      } catch (err) { toast(err.message, true); }
    } },
  ]);
});

load();
