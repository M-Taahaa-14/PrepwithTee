// Teaching console shell (/teach): sign-in check, sidebar, hash router, Ctrl K.
// Built from the admin console's parts (core.js, datatable.js, the student
// manage card, homework) pointed at /api/teach - the teacher's own students only.

import { $, $$, api, esc, icon, avatar, toast, setApiBase } from "/admin/core.js";

setApiBase("/api/teach");

const SECTIONS = {
  today:    () => import("./sections/today.js"),
  students: () => import("./sections/students.js"),
  student:  () => import("./sections/student.js"),
  homework: () => import("./sections/homework.js"),
  groups:   () => import("./sections/groups.js"),
  messages: () => import("./sections/messages.js"),
  settings: () => import("./sections/settings.js"),
};

const NAV = [
  { items: [{ id: "today", label: "Today", icon: "sun", badge: "to_mark" }] },
  { group: "Teaching", items: [
    { id: "students", label: "My students", icon: "school" },
    { id: "homework", label: "Homework", icon: "notebook", badge: "overdue" },
    { id: "groups", label: "Groups", icon: "users-group" },
  ] },
  { group: "You", items: [
    { id: "messages", label: "Messages", icon: "message-circle", badge: "unread" },
    { id: "settings", label: "Settings", icon: "settings" },
  ] },
];

const ctx = { me: null, badges: {}, students: [], refresh: () => refreshBadges() };
const view = $("#view");

async function boot() {
  try {
    ctx.me = (await api("/api/teach/me")).teacher;
  } catch (ex) {
    $("#boot").hidden = true;
    $("#gate").hidden = false;
    if (ex.status === 403) {
      $("#gate-note").hidden = false;
      $("#gate-note").textContent = "This account isn't a teacher account. Ask the PrepWithTee admin to add you as a teacher.";
    } else if (ex.status !== 401) {
      $("#gate-note").hidden = false;
      $("#gate-note").textContent = ex.message;
    }
    return;
  }
  $("#boot").hidden = true;
  $("#app").hidden = false;
  $("#me").innerHTML = `${avatar(ctx.me)}<span>${esc(ctx.me.name || ctx.me.email || "Teacher")}</span>`;
  drawNav();
  wireChrome();
  addEventListener("hashchange", route);
  route();
  refreshBadges();
  setInterval(refreshBadges, 2 * 60 * 1000);
}

document.addEventListener("admin:signed-out", () => {
  if (!$("#app").hidden) { toast("Your session ended. Sign in again.", true); setTimeout(() => location.reload(), 1500); }
});

function drawNav() {
  $("#nav").innerHTML = NAV.map(g => `
    ${g.group ? `<div class="nav-group">${esc(g.group)}</div>` : ""}
    ${g.items.map(it => {
      const n = it.badge && ctx.badges[it.badge];
      return `<a class="nav-item" href="#/${it.id}" data-nav="${it.id}">${icon(it.icon)}${esc(it.label)}${n ? `<span class="badge">${n}</span>` : ""}</a>`;
    }).join("")}`).join("");
  markNav();
}

function markNav() {
  const cur = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || "today";
  const active = { student: "students" }[cur] || cur;
  $$("[data-nav]").forEach(a => {
    const on = a.dataset.nav === active;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

async function refreshBadges() {
  try {
    const [o, m] = await Promise.all([api("/api/teach/overview"), api("/api/messages").catch(() => ({}))]);
    ctx.students = o.students;
    ctx.badges = { to_mark: o.totals.to_mark, overdue: o.totals.overdue, unread: m.unread || 0 };
    drawNav();
  } catch { /* badges are a nicety */ }
}

export function parseHash() {
  const h = location.hash.replace(/^#\/?/, "") || "today";
  const [path, query = ""] = h.split("?");
  const [section, ...rest] = path.split("/");
  return { section, rest, params: Object.fromEntries(new URLSearchParams(query)) };
}

export function setParams(params) {
  const { section, rest } = parseHash();
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== "" && v != null) q.set(k, v); });
  const s = q.toString();
  history.replaceState(null, "", `#/${[section, ...rest].join("/")}${s ? `?${s}` : ""}`);
}

let routeSeq = 0;
async function route() {
  const seq = ++routeSeq;
  const { section, rest, params } = parseHash();
  markNav();
  $("#app").classList.remove("nav-open");
  const load = SECTIONS[section];
  if (!load) { location.hash = "#/today"; return; }
  try {
    const mod = await load();
    if (seq !== routeSeq) return;
    document.title = `${mod.title || section} · Teach · PrepWithTee`;
    view.innerHTML = "";
    await mod.render(view, { rest, params, ctx, setParams });
    view.focus({ preventScroll: true });
  } catch (ex) {
    view.innerHTML = `<div class="card">${esc(ex.message)}</div>`;
  }
}

function wireChrome() {
  const btn = $("#theme-btn");
  const paint = () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    btn.innerHTML = `${icon(dark ? "sun" : "moon")}<span>${dark ? "Light mode" : "Dark mode"}</span>`;
  };
  paint();
  btn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch { /* ok */ }
    paint();
  });
  $("#burger").addEventListener("click", () => $("#app").classList.toggle("nav-open"));
  $("#signout-btn").addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
    location.href = "/";
  });
  $("#search-btn").addEventListener("click", openPalette);
  addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
    else if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]")) { e.preventDefault(); openPalette(); }
  });
}

function openPalette() {
  if ($(".scrim .palette")) return;
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.innerHTML = `<div class="modal palette" role="dialog" aria-modal="true" aria-label="Search">
      <label class="sr-only" for="pal-q">Search</label>
      <input class="input" id="pal-q" autocomplete="off" placeholder="Type a student's name or a section">
      <div class="palette-list" role="listbox" id="pal-list"></div></div>`;
  document.body.append(scrim);
  const input = $("#pal-q"), list = $("#pal-list");
  let items = [], on = 0;
  const close = () => scrim.remove();
  const all = () => [
    ...ctx.students.map(s => ({ group: "Students", icon: "user", label: s.name || s.email, hint: s.subjects.join(", "),
                                go: () => { location.hash = `#/student/${s.id}`; } })),
    ...NAV.flatMap(g => g.items).map(it => ({ group: "Go to", icon: it.icon, label: it.label,
                                              go: () => { location.hash = `#/${it.id}`; } })),
  ];
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    items = all().filter(i => !q || `${i.label} ${i.hint || ""}`.toLowerCase().includes(q)).slice(0, 30);
    on = Math.min(on, Math.max(0, items.length - 1));
    let last = null;
    list.innerHTML = items.length ? items.map((it, i) => {
      const head = it.group !== last ? `<div class="palette-group">${esc(it.group)}</div>` : "";
      last = it.group;
      return `${head}<div class="palette-item${i === on ? " on" : ""}" role="option" aria-selected="${i === on}" data-i="${i}">
        ${icon(it.icon)}<span>${esc(it.label)}</span>${it.hint ? `<span class="k">${esc(it.hint)}</span>` : ""}</div>`;
    }).join("") : `<div class="empty small">No matches</div>`;
  };
  const pick = i => { const it = items[i]; if (it) { close(); it.go(); } };
  input.addEventListener("input", () => { on = 0; draw(); });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); on = Math.min(items.length - 1, on + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); on = Math.max(0, on - 1); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); pick(on); }
    else if (e.key === "Escape") close();
  });
  list.addEventListener("click", e => { const el = e.target.closest("[data-i]"); if (el) pick(+el.dataset.i); });
  scrim.addEventListener("mousedown", e => { if (e.target === scrim) close(); });
  draw();
  input.focus();
}

boot();
