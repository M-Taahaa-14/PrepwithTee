// Admin console shell: sign-in check, sidebar, hash router, Ctrl K palette.
//
// Routes are #/<section>?<params>. Sections not rebuilt yet open in the
// classic page (/admin.html?tab=...), marked "classic" in the sidebar.

import { $, $$, api, esc, icon, avatar, debounce, toast } from "./core.js";

// Versions come from the import map in index.html.
const SECTIONS = {
  overview:   () => import("./sections/overview.js"),
  students:   () => import("./sections/students.js"),
  student:    () => import("./sections/student.js"),
  teachers:   () => import("./sections/teachers.js"),
  inbox:      () => import("./sections/inbox.js"),
  calendly:   () => import("./sections/calendly.js"),
  payments:   () => import("./sections/payments.js"),
  courses:    () => import("./sections/courses.js"),
  groups:     () => import("./sections/groups.js"),
  homework:   () => import("./sections/homework.js"),
  newsletter: () => import("./sections/newsletter.js"),
  emails:     () => import("./sections/emails.js"),
  blog:       () => import("./sections/blog.js"),
  post:       () => import("./sections/post.js"),
  audit:      () => import("./sections/audit.js"),
};

const NAV = [
  { items: [{ id: "overview", label: "Overview", icon: "layout-dashboard" }] },
  { items: [{ id: "inbox", label: "Inbox", icon: "inbox", badge: "inbox_new" }] },
  { group: "People", items: [
    { id: "students", label: "Students", icon: "school" },
    { id: "teachers", label: "Teachers", icon: "users", badge: "applications" },
  ] },
  { group: "Learning", items: [
    { id: "homework", label: "Homework", icon: "notebook" },
    { id: "groups", label: "Groups", icon: "users-group" },
    { id: "courses", label: "Courses", icon: "book" },
  ] },
  { group: "Money", items: [
    { id: "payments", label: "Payments", icon: "receipt", badge: "pending_proofs" },
  ] },
  { group: "Content and reach", items: [
    { id: "blog", label: "Blog studio", icon: "pencil" },
    { id: "newsletter", label: "Newsletter", icon: "mail" },
    { id: "emails", label: "Emails", icon: "send" },
  ] },
  { group: "System", items: [{ id: "audit", label: "Audit log", icon: "history" }] },
];

const ctx = { me: null, badges: {}, refreshBadges: () => refreshBadges() };
const view = $("#view");

/* ── boot ─────────────────────────────────────────────────────────────── */
async function boot() {
  try {
    ctx.me = (await api("/api/admin/me")).admin;
  } catch (ex) {
    $("#boot").hidden = true;
    $("#gate").hidden = false;
    if (ex.status !== 401) {
      $("#gate-note").hidden = false;
      $("#gate-note").textContent = ex.message;
    } else {
      // Signed in as a non-admin? Say so instead of looping on the sign-in page.
      try {
        const me = await fetch("/auth/me", { credentials: "same-origin" });
        if (me.ok) {
          const u = await me.json();
          $("#gate-note").hidden = false;
          $("#gate-note").textContent = `You're signed in as ${u.email}, which isn't an admin account.`;
        }
      } catch { /* not signed in */ }
    }
    return;
  }
  $("#boot").hidden = true;
  $("#app").hidden = false;
  $("#me").innerHTML = `${avatar(ctx.me)}<span>${esc(ctx.me.name || ctx.me.email || "Admin")}</span>`;
  drawNav();
  wireChrome();
  addEventListener("hashchange", route);
  route();
  refreshBadges();
  setInterval(refreshBadges, 5 * 60 * 1000);
}

document.addEventListener("admin:signed-out", () => {
  if (!$("#app").hidden) { toast("Your session ended. Sign in again.", true); setTimeout(() => location.reload(), 1500); }
});

/* ── nav ──────────────────────────────────────────────────────────────── */
function drawNav() {
  $("#nav").innerHTML = NAV.map(g => `
    ${g.group ? `<div class="nav-group">${esc(g.group)}</div>` : ""}
    ${g.items.map(it => {
      const badge = it.badge && ctx.badges[it.badge] ? `<span class="badge">${ctx.badges[it.badge]}</span>` : "";
      if (it.classic) {
        return `<a class="nav-item" href="/admin.html?tab=${it.classic}">${icon(it.icon)}${esc(it.label)}${badge || `<span class="classic">classic</span>`}</a>`;
      }
      return `<a class="nav-item" href="#/${it.id}" data-nav="${it.id}">${icon(it.icon)}${esc(it.label)}${badge}</a>`;
    }).join("")}`).join("");
  markNav();
}

function markNav() {
  const cur = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0] || "overview";
  const active = { student: "students", calendly: "inbox", post: "blog" }[cur] || cur;
  $$("[data-nav]").forEach(a => {
    const on = a.dataset.nav === active;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

async function refreshBadges() {
  try {
    const s = await api("/api/admin/overview/stats?days=7");
    ctx.badges = s.attention;
    drawNav();
  } catch { /* badges are a nicety */ }
}

/* ── router ───────────────────────────────────────────────────────────── */
export function parseHash() {
  const h = location.hash.replace(/^#\/?/, "") || "overview";
  const [path, query = ""] = h.split("?");
  const [section, ...rest] = path.split("/");
  return { section, rest, params: Object.fromEntries(new URLSearchParams(query)) };
}

/** Rewrite the current route's query without adding history entries. */
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
  if (!load) { location.hash = "#/overview"; return; }
  try {
    const mod = await load();
    if (seq !== routeSeq) return;
    document.title = `${mod.title || section} · Admin · PrepWithTee`;
    view.innerHTML = "";
    await mod.render(view, { rest, params, ctx, setParams });
    view.focus({ preventScroll: true });
  } catch (ex) {
    view.innerHTML = `<div class="card">${esc(ex.message)}</div>`;
  }
}

/* ── chrome: theme, burger, sign-out ──────────────────────────────────── */
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

/* ── command palette ──────────────────────────────────────────────────── */
function staticItems() {
  const items = [];
  NAV.forEach(g => g.items.forEach(it => items.push({
    group: "Go to", icon: it.icon, label: it.label + (it.classic ? " (classic)" : ""),
    go: () => { location.href = it.classic ? `/admin.html?tab=${it.classic}` : `#/${it.id}`; },
  })));
  items.push(
    { group: "Students", icon: "user-off", label: "Inactive for 7+ days", go: () => { location.hash = "#/students?active=inactive7"; } },
    { group: "Students", icon: "clock", label: "Plans expiring this week", go: () => { location.hash = "#/students?expiring=7"; } },
    { group: "Students", icon: "user-exclamation", label: "Incomplete profiles", go: () => { location.hash = "#/students?profile=incomplete"; } },
    { group: "Students", icon: "user-question", label: "Students without a teacher", go: () => { location.hash = "#/students?teacher=no"; } },
    { group: "Actions", icon: "receipt", label: "Verify payments", go: () => { location.hash = "#/payments"; } },
    { group: "Actions", icon: "notebook", label: "Set homework", go: () => { location.hash = "#/homework"; } },
    { group: "Actions", icon: "mail", label: "Write a newsletter", go: () => { location.hash = "#/newsletter"; } },
    { group: "Actions", icon: "pencil", label: "Write a blog post", go: () => { location.hash = "#/blog"; } },
    { group: "Actions", icon: "bulb", label: "Blog ideas from your students", go: () => { location.hash = "#/blog?tab=ideas"; } },
    { group: "Actions", icon: "calendar", label: "Calendly bookings", go: () => { location.hash = "#/calendly"; } },
  );
  return items;
}

function openPalette() {
  if ($(".scrim .palette")) return;
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  scrim.innerHTML = `<div class="modal palette" role="dialog" aria-modal="true" aria-label="Search">
      <label class="sr-only" for="pal-q">Search</label>
      <input class="input" id="pal-q" autocomplete="off" placeholder="Type a student's name, a section or an action">
      <div class="palette-list" role="listbox" id="pal-list"></div></div>`;
  document.body.append(scrim);
  const input = $("#pal-q"), list = $("#pal-list");
  let items = [], on = 0, students = [];
  const close = () => { scrim.remove(); };
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    const st = staticItems().filter(i => !q || i.label.toLowerCase().includes(q));
    items = [...students, ...st].slice(0, 30);
    on = Math.min(on, Math.max(0, items.length - 1));
    let last = null;
    list.innerHTML = items.length ? items.map((it, i) => {
      const head = it.group !== last ? `<div class="palette-group">${esc(it.group)}</div>` : "";
      last = it.group;
      return `${head}<div class="palette-item${i === on ? " on" : ""}" role="option" aria-selected="${i === on}" data-i="${i}">
        ${icon(it.icon)}<span>${esc(it.label)}</span>${it.hint ? `<span class="k">${esc(it.hint)}</span>` : ""}</div>`;
    }).join("") : `<div class="empty small">No matches</div>`;
  };
  const findStudents = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { students = []; draw(); return; }
    try {
      const d = await api(`/api/admin/students/table?q=${encodeURIComponent(q)}&per=6&sort=last_active`);
      students = d.rows.map(r => ({ group: "Students", icon: "user", label: r.name || r.email,
        hint: r.email, go: () => { location.hash = `#/student/${r.id}`; } }));
    } catch { students = []; }
    draw();
  }, 200);
  const pick = i => { const it = items[i]; if (it) { close(); it.go(); } };
  input.addEventListener("input", () => { on = 0; draw(); findStudents(); });
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
