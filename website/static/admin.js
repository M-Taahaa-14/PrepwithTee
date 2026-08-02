/* PrepWithTee admin dashboard.
 *
 * Sidebar shell: one page, one data load, sections swap in place. The admin
 * key lives in sessionStorage and travels as X-Admin-Key, never in the URL.
 */

const KEY_STORE = "pwt_admin_key";
let adminKey = sessionStorage.getItem(KEY_STORE) || "";

/* The branded loader is data-gated, not timed: it lifts as soon as the first
   load finishes, but never flashes by faster than this. Raise it if you want
   the splash to linger. */
const LOADER_MIN_MS = 1400;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  leads: [], feedback: [], requests: [], students: [],
  applications: [], teachers: [], calendly: null,
  subjectOptions: [], loaded: false,
};

const PAGES = {
  overview:     ["Overview", "Everything happening across PrepWithTee."],
  leads:        ["Demo Requests", "Parents and students asking for a trial lesson."],
  calendly:     ["Calendly Meetings", "Sessions booked through your Calendly link."],
  requests:     ["Subject Requests", "Syllabuses students want you to add."],
  students:     ["Students", "Everyone registered — click a row for their full log."],
  applications: ["Teacher Applications", "Review, approve or reject applicants."],
  teachers:     ["Teachers", "Who appears on the public Teachers page."],
  feedback:     ["Feedback & Issues", "Ratings, comments and reported problems."],
  student:      ["Student", "Full progress log."],
};

/* ---- API ----------------------------------------------------------------- */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "GET",
    headers: {
      "X-Admin-Key": adminKey,
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { lock(); throw new Error("Session locked — re-enter your key."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/* ---- Helpers ------------------------------------------------------------- */

const today = new Date().toISOString().slice(0, 10);
const isToday = v => String(v ?? "").startsWith(today);

function tsCell(value) {
  const v = String(value ?? "");
  if (!v) return `<td class="ts">—</td>`;
  const t = isToday(v);
  return `<td class="ts">${esc(t ? v.slice(11, 16) : v.slice(0, 10))}${
    t ? '<span class="today-pill">Today</span>' : ""}</td>`;
}

function waHref(contact) {
  let d = String(contact ?? "").replace(/\D/g, "");
  if (d.length < 7 || d.length > 15) return null;
  if (d.startsWith("0")) d = "92" + d.slice(1);
  else if (!d.startsWith("92") && d.length <= 11) d = "92" + d;
  return `https://wa.me/${d}`;
}

function contactCell(value) {
  const v = String(value ?? "") || "—";
  const wa = waHref(v);
  const btn = wa ? `<a class="wa-btn" href="${wa}" target="_blank" rel="noopener">WhatsApp ↗</a>`
    : v.includes("@") ? `<a class="mail-btn" href="mailto:${esc(v)}">Email ↗</a>` : "";
  return `<td>${esc(v)}${btn}</td>`;
}

const initials = name => (name || "?").trim().split(/\s+/).slice(0, 2)
  .map(w => w[0]).join("").toUpperCase();

function avatar(person, cls = "") {
  return person.picture_url
    ? `<img class="avatar ${cls}" src="${esc(person.picture_url)}" alt="">`
    : `<div class="avatar ${cls}">${esc(initials(person.name))}</div>`;
}

function empty(icon, msg, hint = "") {
  return `<div class="empty-state"><span>${icon}</span><p>${esc(msg)}</p>
    ${hint ? `<small>${esc(hint)}</small>` : ""}</div>`;
}

function table(headers, rowsHtml) {
  return `<div class="tbl-wrap"><table>
    <thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rowsHtml}</tbody></table></div>`;
}

function panel(title, bodyHtml, tools = "") {
  return `<div class="panel">
    <div class="panel-head"><h2>${esc(title)}</h2><div class="sp"></div>${tools}</div>
    ${bodyHtml}</div>`;
}

function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " err" : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 3400);
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 16);
  return d.toLocaleString(undefined,
    { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function relative(iso) {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (isNaN(diff)) return "—";
  const days = Math.floor(diff / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? "a month ago" : `${months} months ago`;
}

/* ---- Loader / gate ------------------------------------------------------- */

const bootedAt = Date.now();

function setLoaderStatus(text) {
  const el = $("loader-status");
  if (el) el.textContent = text;
}

async function hideLoader() {
  const wait = Math.max(0, LOADER_MIN_MS - (Date.now() - bootedAt));
  await new Promise(r => setTimeout(r, wait));
  const el = $("loader");
  el.classList.add("done");
  setTimeout(() => { el.hidden = true; }, 500);
}

function lock() {
  adminKey = "";
  sessionStorage.removeItem(KEY_STORE);
  $("app").hidden = true;
  $("gate").hidden = false;
  $("loader").hidden = true;
}

$("gate-form").addEventListener("submit", async e => {
  e.preventDefault();
  adminKey = $("gate-key").value.trim();
  const err = $("gate-error");
  err.hidden = true;
  try {
    await api("/api/admin/overview");
    sessionStorage.setItem(KEY_STORE, adminKey);
    $("gate").hidden = true;
    $("app").hidden = false;
    await loadAll();
  } catch (ex) {
    adminKey = "";
    err.textContent = ex.message;
    err.hidden = false;
  }
});

$("lock-btn").addEventListener("click", lock);
$("refresh-btn").addEventListener("click", async () => {
  toast("Refreshing…");
  await loadAll(true);
  toast("Up to date.");
});

/* ---- Navigation ---------------------------------------------------------- */

function go(tab) {
  document.querySelectorAll(".nav-item").forEach(n =>
    n.classList.toggle("active", n.dataset.tab === tab));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $("view-" + tab).classList.add("active");

  const [title, sub] = PAGES[tab] || ["", ""];
  $("page-title").textContent = title;
  $("page-sub").textContent = sub;
  $("topbar-tools").innerHTML = "";

  if (tab === "students") mountStudentSearch();
  if (tab === "calendly" && !state.calendly) loadCalendly();
  closeSidebar();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("nav").addEventListener("click", e => {
  const item = e.target.closest(".nav-item");
  if (item) go(item.dataset.tab);
});

const closeSidebar = () => {
  document.querySelector(".sidebar").classList.remove("open");
  $("scrim").hidden = true;
};
$("burger").addEventListener("click", () => {
  document.querySelector(".sidebar").classList.add("open");
  $("scrim").hidden = false;
});
$("scrim").addEventListener("click", closeSidebar);

function setCount(name, n) {
  const el = document.querySelector(`[data-count="${name}"]`);
  if (el) el.textContent = n;
}

/* ---- Load ---------------------------------------------------------------- */

async function loadAll(isRefresh = false) {
  try {
    setLoaderStatus("Loading submissions…");
    const [ov, leads, fb, sr, students, apps, teachers] = await Promise.all([
      api("/api/admin/overview"),
      api("/api/admin/leads"),
      api("/api/admin/feedback"),
      api("/api/admin/subject-requests"),
      api("/api/admin/students"),
      api("/api/admin/teacher-applications"),
      api("/api/admin/teachers"),
    ]);
    state.subjectOptions = ov.subject_options || [];
    state.leads = leads.leads || [];
    state.feedback = fb.feedback || [];
    state.requests = sr.subject_requests || [];
    state.students = students.students || [];
    state.applications = apps.applications || [];
    state.teachers = teachers.teachers || [];
    state.loaded = true;

    setLoaderStatus("Building your dashboard…");
    renderAll();
    if (isRefresh && state.calendly) loadCalendly(true);
  } catch (ex) {
    setLoaderStatus("Couldn't load data.");
    toast(ex.message, true);
  } finally {
    if (!$("loader").hidden) hideLoader();
  }
}

function renderAll() {
  renderOverview();
  renderLeads();
  renderFeedback();
  renderRequests();
  renderStudents();
  renderApplications();
  renderTeachers();

  setCount("leads", state.leads.length);
  setCount("students", state.students.length);
  setCount("applications", state.applications.length);
  setCount("teachers", state.teachers.filter(t => t.active).length);
  setCount("feedback", state.feedback.length);
  setCount("requests", state.requests.length);
}

/* ---- Overview ------------------------------------------------------------ */

function renderOverview() {
  const rated = state.feedback.map(f => f.rating).filter(Boolean);
  const avg = rated.length
    ? (rated.reduce((a, b) => a + b, 0) / rated.length).toFixed(1) : null;
  const pending = state.applications.filter(a => (a.status || "pending") === "pending").length;
  const issues = state.feedback.filter(f => (f.type || "feedback") === "issue").length;
  const newLeads = state.leads.filter(l => isToday(l.timestamp)).length;
  const activeStudents = state.students.filter(s => s.quiz_count > 0).length;

  const tiles = [
    ["leads", "lav", "📋", state.leads.length, "Demo Requests",
      newLeads ? `${newLeads} new today` : "no new today", !!newLeads],
    ["students", "grn", "🎓", state.students.length, "Students",
      `${activeStudents} have practised`, false],
    ["applications", "org", "📨", pending, "Pending Applications",
      pending ? "needs your review" : "all reviewed", !!pending],
    ["teachers", "lav", "👥", state.teachers.filter(t => t.active).length, "Live Teachers",
      `${state.teachers.length} total`, false],
    ["feedback", "grn", "💬", state.feedback.length, "Feedback",
      avg ? `${avg}★ average` : "no ratings yet", false],
    ["feedback", "pnk", "🔧", issues, "Open Issues",
      issues ? "reported problems" : "nothing broken", !!issues],
    ["requests", "org", "📚", state.requests.length, "Subject Requests",
      "syllabus wishlist", false],
  ];

  const tilesHtml = tiles.map(([tab, tint, ic, n, label, note, hot]) => `
    <div class="tile" data-goto="${tab}">
      <div class="tile-top"><span class="tile-ic ${tint}">${ic}</span>
        <span class="tile-lbl">${esc(label)}</span></div>
      <b>${n ?? 0}</b><small class="${hot ? "hot" : ""}">${esc(note)}</small>
    </div>`).join("");

  // Most recently active students, so the tutor sees who is actually working.
  const recent = [...state.students]
    .filter(s => s.last_active)
    .sort((a, b) => String(b.last_active).localeCompare(String(a.last_active)))
    .slice(0, 5);

  const recentHtml = recent.length ? table(
    ["Student", "Subjects", "Quizzes", "Avg", "Last active"],
    recent.map(s => `
      <tr class="clickable" data-student="${esc(s.id)}">
        <td><div class="who">${avatar(s)}<div><strong>${esc(s.name || "—")}</strong>
          <div class="ts">${esc(s.grade || "")}</div></div></div></td>
        <td><div class="pill-row">${(s.subject_names || [])
          .map(n => `<span class="pill">${esc(n)}</span>`).join("") || "—"}</div></td>
        <td>${s.quiz_count || 0}</td>
        <td>${s.avg_score ?? "—"}</td>
        <td class="ts">${esc(relative(s.last_active))}</td>
      </tr>`).join(""))
    : empty("🎓", "No student activity yet.",
            "Once students start practising, they'll show up here.");

  const pendingApps = state.applications.filter(a => (a.status || "pending") === "pending");
  const appsHtml = pendingApps.length ? table(
    ["Applicant", "Subjects", "Experience", ""],
    pendingApps.slice(0, 5).map(a => `
      <tr>
        <td><strong>${esc(a.name || "—")}</strong><div class="ts">${esc(a.email || "")}</div></td>
        <td>${esc(a.subjects || "—")}</td>
        <td>${esc(a.experience || "—")}</td>
        <td><button class="btn btn-ok" data-approve="${a.id}">Review</button></td>
      </tr>`).join(""))
    : empty("✅", "No applications waiting.", "New applicants will appear here for review.");

  $("view-overview").innerHTML = `
    <div class="tiles">${tilesHtml}</div>
    <div class="grid-2">
      ${panel("Recently active students", recentHtml,
              `<button class="btn" data-goto="students">View all</button>`)}
      ${panel("Awaiting your review", appsHtml,
              `<button class="btn" data-goto="applications">View all</button>`)}
    </div>`;

  wireGoto($("view-overview"));
  wireStudentRows($("view-overview"));
  $("view-overview").querySelectorAll("[data-approve]").forEach(b =>
    b.addEventListener("click", () => openApproval(Number(b.dataset.approve))));
}

function wireGoto(scope) {
  scope.querySelectorAll("[data-goto]").forEach(el =>
    el.addEventListener("click", () => go(el.dataset.goto)));
}

function wireStudentRows(scope) {
  scope.querySelectorAll("[data-student]").forEach(tr =>
    tr.addEventListener("click", () => openStudent(tr.dataset.student)));
}

/* ---- Demo requests ------------------------------------------------------- */

function renderLeads() {
  const rows = state.leads.map(l => `
    <tr class="${isToday(l.timestamp) ? "row-today" : ""}">
      ${tsCell(l.timestamp)}
      <td>${esc(l.parent_name || "—")}</td>
      <td><strong>${esc(l.student_name || "—")}</strong></td>
      ${contactCell(l.contact)}
      <td>${esc(l.grade || "—")}</td>
      <td><div class="pill-row">${(l.subjects || "").split(",").filter(Boolean)
        .map(s => `<span class="pill">${esc(s.trim())}</span>`).join("") || "—"}</div></td>
      <td>${esc(l.message || "—")}</td>
    </tr>`).join("");

  $("view-leads").innerHTML = state.leads.length
    ? panel(`${state.leads.length} demo requests`,
        table(["Time", "Parent", "Student", "Contact", "Grade", "Subjects", "Note"], rows))
    : panel("Demo requests",
        empty("📭", "No demo requests yet.",
              "They appear the moment a parent books from the site."));
}

/* ---- Feedback ------------------------------------------------------------ */

function renderFeedback() {
  const rows = state.feedback.map(f => {
    const type = f.type || "feedback";
    const isIssue = type === "issue";
    const r = f.rating;
    const stars = r ? "★".repeat(r) + "☆".repeat(5 - r) : "—";
    return `
      <tr class="${isToday(f.ts) ? "row-today" : ""}">
        ${tsCell(f.ts)}
        <td><span class="badge ${isIssue ? "badge-issue" : "badge-ok"}">
          ${isIssue ? "🔧" : "💬"} ${esc(type)}</span></td>
        <td class="${r >= 4 ? "stars-hi" : r ? "stars-lo" : ""}">${stars}</td>
        <td>${esc(f.name || "—")}</td>
        <td>${esc(f.page || "—")}</td>
        <td>${esc(f.message || "—")}</td>
      </tr>`;
  }).join("");

  $("view-feedback").innerHTML = state.feedback.length
    ? panel(`${state.feedback.length} submissions`,
        table(["Time", "Type", "Stars", "Name", "Page", "Message"], rows))
    : panel("Feedback & issues", empty("💬", "Nothing submitted yet."));
}

/* ---- Subject requests ---------------------------------------------------- */

function renderRequests() {
  const rows = state.requests.map(r => `
    <tr class="${isToday(r.ts) ? "row-today" : ""}">
      ${tsCell(r.ts)}
      <td><strong>${esc(r.subject || "—")}</strong></td>
      <td>${esc(r.board || "—")}</td>
      <td>${esc(r.message || "—")}</td>
    </tr>`).join("");

  $("view-requests").innerHTML = state.requests.length
    ? panel(`${state.requests.length} requested subjects`,
        table(["Time", "Subject", "Board", "Message"], rows))
    : panel("Subject requests",
        empty("📚", "No subject requests yet.",
              "Students use these to ask for syllabuses you don't cover."));
}

/* ---- Students ------------------------------------------------------------ */

let studentFilter = "";

function mountStudentSearch() {
  $("topbar-tools").innerHTML =
    `<input class="search-box" id="student-search" placeholder="Search name, email or grade…"
       value="${esc(studentFilter)}">`;
  const box = $("student-search");
  box.addEventListener("input", e => {
    studentFilter = e.target.value;
    renderStudents();
  });
}

function renderStudents() {
  const q = studentFilter.trim().toLowerCase();
  const list = q
    ? state.students.filter(s =>
        `${s.name} ${s.email} ${s.grade || ""}`.toLowerCase().includes(q))
    : state.students;

  const rows = list.map(s => {
    const pct = s.topics_tracked
      ? Math.round(s.topics_confident / s.topics_tracked * 100) : 0;
    return `
      <tr class="clickable" data-student="${esc(s.id)}">
        <td><div class="who">${avatar(s)}<div><strong>${esc(s.name || "—")}</strong>
          <div class="ts">${esc(s.email || "")}</div></div></div></td>
        <td>${esc(s.grade || "—")}</td>
        <td><div class="pill-row">${(s.subject_names || [])
          .map(n => `<span class="pill">${esc(n)}</span>`).join("") || "—"}</div></td>
        <td><strong>${pct}%</strong><div class="ts">${s.topics_confident}/${s.topics_tracked} topics</div></td>
        <td>${s.quiz_count || 0}</td>
        <td>${s.avg_score ?? "—"}</td>
        <td class="ts">${esc(relative(s.last_active))}</td>
      </tr>`;
  }).join("");

  $("view-students").innerHTML = list.length
    ? panel(`${list.length} student${list.length === 1 ? "" : "s"}`,
        table(["Student", "Grade", "Subjects", "Confident", "Quizzes", "Avg", "Last active"], rows))
    : panel("Students", empty("🎓",
        q ? "No student matches that search." : "No students registered yet."));

  wireStudentRows($("view-students"));
}

async function openStudent(userId) {
  go("student");
  $("view-student").innerHTML =
    `<button class="back-link" data-goto="students">← Back to students</button>
     ${panel("Loading", empty("⏳", "Fetching this student's record…"))}`;
  wireGoto($("view-student"));

  try {
    const d = await api(`/api/admin/students/${encodeURIComponent(userId)}`);
    const p = d.profile, st = d.stats;
    const active = d.enrollments.filter(e => e.status === "active");
    const wa = waHref(p.phone);

    $("page-title").textContent = p.name || "Student";
    $("page-sub").textContent = "Full progress log.";

    const hero = `
      <div class="stu-hero">
        ${avatar(p)}
        <div>
          <h2>${esc(p.name || "Student")}</h2>
          <div class="em">${esc(p.email || "")}</div>
          <div class="meta">
            ${p.grade ? `<span>${esc(p.grade)}</span>` : ""}
            ${p.phone ? `<span>${esc(p.phone)}</span>` : ""}
            <span>Joined ${esc(fmtDate(p.created_at).split(",")[0])}</span>
            <span>Active ${esc(relative(st.last_active))}</span>
          </div>
        </div>
        <div class="hero-cta">
          ${wa ? `<a class="hero-btn" href="${wa}" target="_blank" rel="noopener">WhatsApp</a>` : ""}
          ${p.email ? `<a class="hero-btn" href="mailto:${esc(p.email)}">Email</a>` : ""}
        </div>
      </div>`;

    const confident = d.by_syllabus.reduce((n, s) => n + s.confident, 0);
    const tiles = `
      <div class="tiles">
        <div class="tile"><div class="tile-top"><span class="tile-ic lav">📗</span>
          <span class="tile-lbl">Topics tracked</span></div><b>${st.topics_tracked}</b>
          <small>${confident} marked confident</small></div>
        <div class="tile"><div class="tile-top"><span class="tile-ic grn">✍️</span>
          <span class="tile-lbl">Quizzes done</span></div><b>${st.quiz_count}</b>
          <small>${esc(relative(st.last_active))}</small></div>
        <div class="tile"><div class="tile-top"><span class="tile-ic org">🎯</span>
          <span class="tile-lbl">Average score</span></div><b>${st.avg_score ?? "—"}</b>
          <small>marks per question</small></div>
        <div class="tile"><div class="tile-top"><span class="tile-ic lav">📚</span>
          <span class="tile-lbl">Subjects</span></div><b>${active.length}</b>
          <small>${esc(active.map(e => e.name).join(", ") || "none enrolled")}</small></div>
      </div>`;

    const subjects = d.by_syllabus.length ? d.by_syllabus.map(s => {
      const total = s.topics.length || 1;
      const pct = Math.round(s.confident / total * 100);
      return `
        <div class="subj-card">
          <div class="subj-top">
            <h4>${esc(s.name)}</h4>
            <span class="badge badge-lav">${esc(s.syllabus)}</span>
            <span class="subj-pct">${pct}%</span>
          </div>
          <div class="prog-bar">
            <i class="cf" style="width:${(s.confident / total * 100).toFixed(1)}%"></i>
            <i class="ln" style="width:${(s.learning / total * 100).toFixed(1)}%"></i>
          </div>
          <div class="prog-legend">
            <span><i class="cf"></i><b>${s.confident}</b> confident</span>
            <span><i class="ln"></i><b>${s.learning}</b> learning</span>
            <span><i class="ns"></i><b>${s.not_started}</b> not started</span>
          </div>
          <div class="topic-list">${s.topics.map(t => `
            <span class="topic-chip ${esc(t.status || "not_started")}">${esc(t.topic)}${
              t.subtopic ? " · " + esc(t.subtopic) : ""}</span>`).join("")}</div>
        </div>`;
    }).join("") : empty("📗", "No topics tracked yet.",
                        "Progress appears once they mark topics in their dashboard.");

    const quizzes = d.quizzes.length
      ? quizGroups(d.quizzes)
      : empty("✍️", "No quizzes attempted yet.");

    const profile = [
      ["Email", p.email], ["Phone", p.phone], ["Grade", p.grade],
      ["Gender", p.gender], ["Birthday", p.birthday],
      ["Joined", fmtDate(p.created_at)],
      ["Profile complete", p.profile_complete ? "Yes" : "No"],
      ["Enrolled", active.map(e => e.name).join(", ") || "—"],
    ].map(([k, v]) => `<div class="detail-row"><span class="k">${esc(k)}</span>
        <span class="v">${esc(v || "—")}</span></div>`).join("");

    $("view-student").innerHTML = `
      <button class="back-link" data-goto="students">← Back to students</button>
      ${hero}${tiles}
      <div class="grid-2">
        <div>${panel("Subject progress", `<div class="panel-body">${subjects}</div>`)}</div>
        <div>${panel("Profile", `<div class="panel-body">${profile}</div>`)}</div>
      </div>
      ${panel(`Quiz log (${d.quizzes.length})`, `<div class="panel-body">${quizzes}</div>`)}`;

    wireGoto($("view-student"));
  } catch (ex) {
    $("view-student").innerHTML =
      `<button class="back-link" data-goto="students">← Back to students</button>
       ${panel("Error", empty("⚠️", "Couldn't load this student.", ex.message))}`;
    wireGoto($("view-student"));
  }
}

/* Quiz log: grouped by subject, one collapsed row per attempt showing only the
   score. Details live in the row's <details> body so nothing is fetched twice. */
function quizGroups(quizzes) {
  const groups = new Map();
  for (const q of quizzes) {
    const key = q.syllabus || "—";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(q);
  }

  return [...groups.entries()].map(([syllabus, list]) => {
    const scored = list.filter(q => q.score != null);
    const got = scored.reduce((n, q) => n + q.score, 0);
    const outOf = scored.reduce((n, q) => n + (q.max_marks || 0), 0);
    const name = SUBJECT_LABELS[syllabus] || syllabus;

    const rows = list.map(q => `
      <details class="qz">
        <summary>
          <span class="qz-topic">${esc(q.topic || "—")}${
            q.subtopic ? ` <span class="qz-sub">· ${esc(q.subtopic)}</span>` : ""}</span>
          <span class="qz-score ${scoreTone(q)}">${
            q.score != null ? esc(q.score) : "—"}<i>/${q.max_marks ?? "?"}</i></span>
          <span class="qz-date ts">${esc(String(q.created_at || "").slice(0, 10))}</span>
          <span class="qz-caret">▾</span>
        </summary>
        <div class="qz-body">
          <div class="quiz-q">${esc(q.question_text || "")}</div>
          ${q.student_answer ? `<div class="quiz-a"><em>Their answer</em>${esc(q.student_answer)}</div>` : ""}
          ${q.feedback ? `<div class="quiz-fb"><strong>Examiner feedback:</strong> ${esc(q.feedback)}</div>` : ""}
          ${q.ideal_answer ? `<div class="quiz-fb"><strong>Full-mark answer:</strong> ${esc(q.ideal_answer)}</div>` : ""}
          <div class="ts" style="margin-top:8px">${esc(fmtDate(q.created_at))}</div>
        </div>
      </details>`).join("");

    return `
      <div class="qz-group">
        <div class="qz-group-head">
          <h4>${esc(name)}</h4>
          <span class="badge badge-lav">${esc(syllabus)}</span>
          <span class="qz-group-tot">${list.length} attempt${list.length === 1 ? "" : "s"}
            ${outOf ? `· <b>${got}/${outOf}</b> marks` : ""}</span>
        </div>
        ${rows}
      </div>`;
  }).join("");
}

/* Green when they scored most of the marks, amber mid, grey when unscored. */
function scoreTone(q) {
  if (q.score == null || !q.max_marks) return "";
  const ratio = q.score / q.max_marks;
  return ratio >= 0.7 ? "hi" : ratio >= 0.4 ? "mid" : "lo";
}

const SUBJECT_LABELS = {
  "4024": "O Level Mathematics D", "0580": "IGCSE Mathematics",
  "5054": "O Level Physics", "0625": "IGCSE Physics",
  "2210": "O Level Computer Science", "0478": "IGCSE Computer Science",
  "5070": "O Level Chemistry", "0620": "IGCSE Chemistry",
  "9709": "A Level Mathematics", "9702": "A Level Physics",
  "9618": "A Level Computer Science",
};

/* ---- Teacher applications ------------------------------------------------ */

function renderApplications() {
  const rows = state.applications.map(a => {
    const status = a.status || "pending";
    const badge = status === "approved" ? "badge-ok"
      : status === "rejected" ? "badge-issue" : "badge-pending";
    const actions = status === "pending"
      ? `<div class="btn-row">
           <button class="btn btn-ok" data-approve="${a.id}">Approve</button>
           <button class="btn btn-danger" data-reject="${a.id}">Reject</button>
         </div>`
      : `<span class="ts">${esc(String(a.reviewed_at || "").slice(0, 10) || "—")}</span>`;
    return `
      <tr class="${isToday(a.created_at) ? "row-today" : ""}">
        ${tsCell(a.created_at)}
        <td><strong>${esc(a.name || "—")}</strong><div class="ts">${esc(a.phone || "")}</div></td>
        ${contactCell(a.email)}
        <td>${esc(a.subjects || "—")}</td>
        <td>${esc(a.qualifications || "—")}</td>
        <td>${esc(a.experience || "—")}</td>
        <td><span class="badge ${badge}">${esc(status)}</span></td>
        <td>${actions}</td>
      </tr>`;
  }).join("");

  const pending = state.applications.filter(a => (a.status || "pending") === "pending").length;
  $("view-applications").innerHTML = state.applications.length
    ? panel(`${state.applications.length} applications · ${pending} pending`,
        table(["Time", "Name", "Email", "Subjects", "Qualifications",
               "Experience", "Status", "Action"], rows))
    : panel("Teacher applications",
        empty("📨", "No applications yet.",
              "Submissions from the Teach With Us form land here."));

  $("view-applications").querySelectorAll("[data-approve]").forEach(b =>
    b.addEventListener("click", () => openApproval(Number(b.dataset.approve))));
  $("view-applications").querySelectorAll("[data-reject]").forEach(b =>
    b.addEventListener("click", () => rejectApplication(Number(b.dataset.reject))));
}

function subjectCheckboxes(selected = []) {
  return state.subjectOptions.map(o => `
    <label class="subj-check">
      <input type="checkbox" name="subj" value="${esc(o.code)}"
        ${selected.includes(o.code) ? "checked" : ""}>
      <span>${esc(o.name)}</span>
    </label>`).join("");
}

function openApproval(appId) {
  const a = state.applications.find(x => x.id === appId);
  if (!a) return;
  const preset = String(a.subject_codes || "").split(",").map(s => s.trim()).filter(Boolean);

  openDrawer(`
    <h2>Approve ${esc(a.name || "applicant")}</h2>
    <p class="sub">Set how they'll appear on the public Teachers page.</p>

    <div class="dr-block">
      <h3>What they submitted</h3>
      ${[["Email", a.email], ["Phone", a.phone], ["Subjects", a.subjects],
         ["Qualifications", a.qualifications], ["Experience", a.experience],
         ["Message", a.message]]
        .map(([k, v]) => `<div class="detail-row"><span class="k">${esc(k)}</span>
            <span class="v">${esc(v || "—")}</span></div>`).join("")}
    </div>

    <div class="dr-block">
      <h3>Public profile</h3>
      <div class="f-grid">
        <div class="f-field"><label>Display name</label>
          <input id="ap-name" value="${esc(a.name || "")}"></div>
        <div class="f-field"><label>Role / title</label>
          <input id="ap-role" placeholder="e.g. Physics Teacher" value="Teacher"></div>
      </div>
      <div class="f-field"><label>Bio</label>
        <textarea id="ap-bio" placeholder="A short paragraph for their card…"></textarea></div>
      <div class="f-grid">
        <div class="f-field"><label>Qualifications</label>
          <input id="ap-quals" value="${esc(a.qualifications || "")}"></div>
        <div class="f-field"><label>Years of experience</label>
          <input id="ap-years" type="number" min="0" max="60"
            value="${esc(String(a.experience || "").replace(/\D/g, ""))}"></div>
      </div>
      <div class="f-grid">
        <div class="f-field"><label>Photo URL</label>
          <input id="ap-photo" placeholder="https://…"></div>
        <div class="f-field"><label>Display order</label>
          <input id="ap-order" type="number" value="0"></div>
      </div>
    </div>

    <div class="dr-block">
      <h3>Subjects they teach</h3>
      <div class="subj-grid" id="ap-subjects">${subjectCheckboxes(preset)}</div>
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" id="ap-submit">Approve &amp; publish</button>
      <button class="btn" id="ap-cancel">Cancel</button>
    </div>`);

  $("ap-cancel").addEventListener("click", closeDrawer);
  $("ap-submit").addEventListener("click", async () => {
    const btn = $("ap-submit");
    btn.disabled = true;
    btn.textContent = "Publishing…";
    const years = $("ap-years").value.trim();
    const order = $("ap-order").value.trim();
    try {
      await api(`/api/admin/teacher-applications/${appId}/approve`, {
        method: "POST",
        body: {
          name: $("ap-name").value.trim() || null,
          role: $("ap-role").value.trim() || null,
          bio: $("ap-bio").value.trim() || null,
          qualifications: $("ap-quals").value.trim() || null,
          experience_years: years ? Number(years) : null,
          picture_url: $("ap-photo").value.trim() || null,
          display_order: order ? Number(order) : 0,
          subjects: [...document.querySelectorAll('#ap-subjects input[name="subj"]:checked')]
            .map(i => i.value),
        },
      });
      closeDrawer();
      toast("Approved — they're live on the Teachers page.");
      loadAll();
    } catch (ex) {
      toast(ex.message, true);
      btn.disabled = false;
      btn.textContent = "Approve & publish";
    }
  });
}

async function rejectApplication(appId) {
  const note = prompt("Reason for rejecting (optional, kept internal):");
  if (note === null) return;
  try {
    await api(`/api/admin/teacher-applications/${appId}/reject`, {
      method: "POST", body: { admin_note: note || null },
    });
    toast("Application rejected.");
    loadAll();
  } catch (ex) { toast(ex.message, true); }
}

/* ---- Teachers ------------------------------------------------------------ */

function renderTeachers() {
  const rows = state.teachers.map(t => `
    <tr>
      <td><div class="who">${avatar(t)}<div><strong>${esc(t.name || "—")}</strong>
        <div class="ts">${esc(t.email || "")}</div></div></div></td>
      <td>${esc(t.role || "—")}</td>
      <td><div class="pill-row">${(t.subject_names || [])
        .map(n => `<span class="pill">${esc(n)}</span>`).join("")
        || '<span class="ts">No subjects assigned</span>'}</div></td>
      <td>${t.experience_years != null ? esc(t.experience_years) + " yrs" : "—"}</td>
      <td><span class="badge ${t.active ? "badge-ok" : "badge-neutral"}">
        ${t.active ? "Live" : "Hidden"}</span></td>
      <td><div class="btn-row">
        <button class="btn" data-edit="${t.id}">Edit</button>
        <button class="btn btn-danger" data-del="${t.id}">Delete</button>
      </div></td>
    </tr>`).join("");

  $("view-teachers").innerHTML = panel(
    `${state.teachers.length} teacher${state.teachers.length === 1 ? "" : "s"}`,
    state.teachers.length
      ? table(["Name", "Role", "Subjects", "Experience", "Status", ""], rows)
      : empty("👥", "No teachers published yet.",
              "Approve an application, or add one manually."),
    `<button class="btn btn-primary" id="add-teacher">+ Add teacher</button>`);

  $("add-teacher").addEventListener("click", () => openTeacherForm(null));
  $("view-teachers").querySelectorAll("[data-edit]").forEach(b =>
    b.addEventListener("click", () => openTeacherForm(Number(b.dataset.edit))));
  $("view-teachers").querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () => deleteTeacher(Number(b.dataset.del))));
}

function openTeacherForm(teacherId) {
  const t = teacherId ? state.teachers.find(x => x.id === teacherId) : null;

  openDrawer(`
    <h2>${t ? "Edit " + esc(t.name) : "Add a teacher"}</h2>
    <p class="sub">These fields drive their card on the public Teachers page.</p>

    <div class="dr-block">
      <div class="f-grid">
        <div class="f-field"><label>Name</label>
          <input id="t-name" value="${esc(t?.name || "")}"></div>
        <div class="f-field"><label>Role / title</label>
          <input id="t-role" value="${esc(t?.role || "Teacher")}"></div>
      </div>
      <div class="f-field"><label>Bio</label>
        <textarea id="t-bio">${esc(t?.bio || "")}</textarea></div>
      <div class="f-grid">
        <div class="f-field"><label>Qualifications</label>
          <input id="t-quals" value="${esc(t?.qualifications || "")}"></div>
        <div class="f-field"><label>Years of experience</label>
          <input id="t-years" type="number" min="0" max="60"
            value="${t?.experience_years ?? ""}"></div>
      </div>
      <div class="f-grid">
        <div class="f-field"><label>Email</label>
          <input id="t-email" value="${esc(t?.email || "")}"></div>
        <div class="f-field"><label>Phone</label>
          <input id="t-phone" value="${esc(t?.phone || "")}"></div>
      </div>
      <div class="f-grid">
        <div class="f-field"><label>Photo URL</label>
          <input id="t-photo" value="${esc(t?.picture_url || "")}"></div>
        <div class="f-field"><label>Display order</label>
          <input id="t-order" type="number" value="${t?.display_order ?? 0}"></div>
      </div>
      <div class="f-field"><label>Show on the public site</label>
        <select id="t-active">
          <option value="1" ${t && !t.active ? "" : "selected"}>Live — visible to everyone</option>
          <option value="0" ${t && !t.active ? "selected" : ""}>Hidden — not shown</option>
        </select></div>
    </div>

    <div class="dr-block">
      <h3>Subjects they teach</h3>
      <div class="subj-grid" id="t-subjects">${subjectCheckboxes(t?.subjects || [])}</div>
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" id="t-save">${t ? "Save changes" : "Add teacher"}</button>
      <button class="btn" id="t-cancel">Cancel</button>
    </div>`);

  $("t-cancel").addEventListener("click", closeDrawer);
  $("t-save").addEventListener("click", async () => {
    const btn = $("t-save");
    const name = $("t-name").value.trim();
    if (!name) return toast("Name is required.", true);
    btn.disabled = true;
    btn.textContent = "Saving…";
    const years = $("t-years").value.trim();
    const body = {
      name,
      role: $("t-role").value.trim() || null,
      bio: $("t-bio").value.trim() || null,
      qualifications: $("t-quals").value.trim() || null,
      experience_years: years ? Number(years) : null,
      email: $("t-email").value.trim() || null,
      phone: $("t-phone").value.trim() || null,
      picture_url: $("t-photo").value.trim() || null,
      display_order: Number($("t-order").value.trim() || 0),
      active: $("t-active").value === "1",
      subjects: [...document.querySelectorAll('#t-subjects input[name="subj"]:checked')]
        .map(i => i.value),
    };
    try {
      if (t) await api(`/api/admin/teachers/${t.id}`, { method: "PATCH", body });
      else    await api("/api/admin/teachers", { method: "POST", body });
      closeDrawer();
      toast(t ? "Teacher updated." : "Teacher added.");
      loadAll();
    } catch (ex) {
      toast(ex.message, true);
      btn.disabled = false;
      btn.textContent = t ? "Save changes" : "Add teacher";
    }
  });
}

async function deleteTeacher(teacherId) {
  const t = state.teachers.find(x => x.id === teacherId);
  if (!confirm(`Remove ${t?.name || "this teacher"} from the site permanently?`)) return;
  try {
    await api(`/api/admin/teachers/${teacherId}`, { method: "DELETE" });
    toast("Teacher removed.");
    loadAll();
  } catch (ex) { toast(ex.message, true); }
}

/* ---- Calendly ------------------------------------------------------------ */

async function loadCalendly(force = false) {
  if (!state.calendly) {
    $("view-calendly").innerHTML =
      panel("Calendly meetings", empty("📅", "Loading your meetings…"));
  }
  try {
    state.calendly = await api("/api/admin/calendly" + (force ? "?refresh=true" : ""));
    renderCalendly();
  } catch (ex) {
    $("view-calendly").innerHTML =
      panel("Calendly meetings", empty("⚠️", "Couldn't reach Calendly.", ex.message));
  }
}

function renderCalendly() {
  const d = state.calendly;
  if (!d.configured) {
    $("view-calendly").innerHTML = panel("Calendly meetings",
      empty("🔑", "Calendly isn't connected yet.", d.message || ""));
    setCount("calendly", 0);
    return;
  }

  const now = Date.now();
  const events = d.events || [];
  setCount("calendly", events.length);

  const upcoming = events.filter(e =>
    e.status !== "canceled" && new Date(e.start_time).getTime() >= now).length;

  const cards = events.map(ev => {
    const start = ev.start_time ? new Date(ev.start_time) : null;
    const past = start && start.getTime() < now;
    const canceled = ev.status === "canceled";
    const inv = ev.invitees || [];
    return `
      <div class="cal-card ${canceled ? "canceled" : past ? "past" : ""}">
        <div class="cal-when">
          <div class="d">${start ? start.getDate() : "—"}</div>
          <div class="m">${start ? start.toLocaleString(undefined, { month: "short" }) : ""}</div>
          <div class="t">${start ? start.toLocaleTimeString(undefined,
            { hour: "2-digit", minute: "2-digit" }) : ""}</div>
        </div>
        <div class="cal-body">
          <h4>${esc(ev.name || "Meeting")}
            <span class="badge ${canceled ? "badge-issue" : past ? "badge-neutral" : "badge-ok"}">
              ${canceled ? "canceled" : past ? "done" : "upcoming"}</span></h4>
          ${inv.map(i => `
            <div class="cal-inv"><strong>${esc(i.name || "—")}</strong>
              ${i.email ? ` · <a class="mail-btn" href="mailto:${esc(i.email)}">${esc(i.email)}</a>` : ""}
              ${i.timezone ? `<span class="ts"> · ${esc(i.timezone)}</span>` : ""}
              ${(i.questions || []).filter(q => q.answer).map(q => `
                <div class="cal-qa"><strong>${esc(q.question)}</strong><br>${esc(q.answer)}</div>`).join("")}
            </div>`).join("") || `<div class="cal-inv ts">No invitee details.</div>`}
          ${ev.join_url ? `<a class="cal-link" href="${esc(ev.join_url)}"
            target="_blank" rel="noopener">Join link ↗</a>` : ""}
          ${ev.location && !ev.join_url ? `<div class="ts">${esc(ev.location)}</div>` : ""}
        </div>
      </div>`;
  }).join("");

  $("view-calendly").innerHTML = panel(
    `${events.length} meetings · ${upcoming} upcoming`,
    events.length ? `<div class="panel-body"><div class="cal-list">${cards}</div></div>`
                  : empty("📅", "No meetings scheduled yet."),
    `${d.scheduling_url ? `<a class="btn" href="${esc(d.scheduling_url)}"
       target="_blank" rel="noopener">Booking page ↗</a>` : ""}
     <button class="btn" id="cal-refresh">↻ Sync</button>`);

  const btn = $("cal-refresh");
  if (btn) btn.addEventListener("click", () => loadCalendly(true));
}

/* ---- Drawer -------------------------------------------------------------- */

function openDrawer(html) {
  $("drawer-body").innerHTML = html;
  $("drawer-backdrop").hidden = false;
  $("drawer").scrollTop = 0;
  document.body.style.overflow = "hidden";
}

function closeDrawer() {
  $("drawer-backdrop").hidden = true;
  document.body.style.overflow = "";
}

$("drawer-close").addEventListener("click", closeDrawer);
$("drawer-backdrop").addEventListener("click", e => {
  if (e.target === $("drawer-backdrop")) closeDrawer();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("drawer-backdrop").hidden) closeDrawer();
});

/* ---- Boot ---------------------------------------------------------------- */

(async function boot() {
  // A ?key= in the URL is honoured once, then scrubbed from history so the
  // secret does not sit in the address bar or get bookmarked.
  const urlKey = new URLSearchParams(location.search).get("key");
  if (urlKey) {
    adminKey = urlKey;
    history.replaceState({}, "", location.pathname);
  }
  if (!adminKey) { lock(); return; }
  try {
    setLoaderStatus("Checking your key…");
    await api("/api/admin/overview");
    sessionStorage.setItem(KEY_STORE, adminKey);
    $("gate").hidden = true;
    $("app").hidden = false;
    await loadAll();
  } catch {
    lock();
  }
})();
