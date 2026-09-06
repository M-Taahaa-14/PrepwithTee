/* PrepWithTee admin dashboard.
 *
 * Sidebar shell: one page, one data load, sections swap in place. The admin
 * key lives in sessionStorage and travels as X-Admin-Key, never in the URL.
 */

import * as StudentConsole from "/admin-student.js?v=20260831c";

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
  applications: [], teachers: [], courses: [], calendly: null,
  groups: [], payments: [], allocations: [], contacts: [], newsletter: [],
  teacherProfiles: [],
  subjectOptions: [], loaded: false,
  homework: null, hwStudent: null, hwFilter: "all",
  blog: [],
};

const PAGES = {
  overview:     ["Overview", "Everything happening across PrepWithTee."],
  leads:        ["Demo Requests", "Parents and students asking for a trial lesson."],
  calendly:     ["Calendly Meetings", "Sessions booked through your Calendly link."],
  requests:     ["Subject Requests", "Syllabuses students want you to add."],
  students:     ["Students", "Everyone registered — click a row for their full log."],
  homework:     ["Homework", "Work you've set, and what students have handed in."],
  applications: ["Teacher Applications", "Review, approve or reject applicants."],
  teachers:     ["Teachers", "Who appears on the public Teachers page."],
  blog:         ["Blog", "Write, publish and manage blog posts for SEO."],
  courses:      ["Courses", "Course catalog — manage SEO landing pages."],
  groups:       ["Groups", "Small-group tutoring sessions created by teachers."],
  payments:     ["Payment Proofs", "Screenshots uploaded by students — approve to upgrade their plan."],
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

/** Multipart sibling of api(). No Content-Type header — the browser has to set
 *  it itself so the multipart boundary is included. */
async function upload(path, formData) {
  const res = await fetch(path, {
    method: "POST", headers: { "X-Admin-Key": adminKey }, body: formData,
  });
  if (res.status === 401) { lock(); throw new Error("Session locked — re-enter your key."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status})`);
  return data;
}

/**
 * Upload with a progress callback.
 *
 * fetch() gives no upload progress — the request body is opaque once handed
 * over — so this is XMLHttpRequest, which is the only browser API that fires
 * `upload.onprogress`. Worth the older shape: a 20 MB worksheet on a slow
 * connection otherwise looks like a frozen button.
 *
 * onProgress({loaded, total, done}); `done` flips true once the bytes are sent
 * and the server is still working, so the UI can stop showing a byte count.
 */
function uploadWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader("X-Admin-Key", adminKey);

    xhr.upload.addEventListener("progress", e => {
      if (e.lengthComputable) {
        onProgress?.({ loaded: e.loaded, total: e.total, done: e.loaded >= e.total });
      }
    });
    xhr.upload.addEventListener("load", () =>
      onProgress?.({ loaded: 1, total: 1, done: true }));

    xhr.addEventListener("load", () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* empty body */ }
      if (xhr.status === 401) { lock(); return reject(new Error("Session locked — re-enter your key.")); }
      if (xhr.status < 200 || xhr.status >= 300) {
        return reject(new Error(data.detail || `Upload failed (${xhr.status})`));
      }
      resolve(data);
    });
    xhr.addEventListener("error", () =>
      reject(new Error("Connection lost during upload.")));
    xhr.addEventListener("abort", () =>
      reject(new Error("Upload cancelled.")));
    xhr.addEventListener("timeout", () =>
      reject(new Error("Upload timed out.")));

    xhr.timeout = 10 * 60 * 1000;
    xhr.send(formData);
  });
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
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const diff = Date.now() - d.getTime();
  const mins  = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days  = Math.floor(diff / 86400000);
  if (mins  <  2)  return "just now";
  if (mins  < 60)  return `${mins}m ago`;
  if (hours <  2)  return "1 hour ago";
  if (hours < 24)  return `${hours} hours ago`;
  if (days  === 1) return "yesterday";
  if (days  <  7)  return `${days} days ago`;
  if (days  < 14)  return "1 week ago";
  if (days  < 30)  return `${Math.floor(days / 7)} weeks ago`;
  const months = Math.floor(days / 30);
  return months === 1 ? "1 month ago" : `${months} months ago`;
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
  if (tab === "homework") loadHomework();
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
    const safe = p => p.catch(() => ({}));
    const [ov, leads, fb, sr, students, apps, teachers, courses, groups, payments] = await Promise.all([
      api("/api/admin/overview"),
      api("/api/admin/leads"),
      api("/api/admin/feedback"),
      api("/api/admin/subject-requests"),
      api("/api/admin/students"),
      api("/api/admin/teacher-applications"),
      api("/api/admin/teachers"),
      safe(api("/api/admin/courses")),
      safe(api("/api/admin/groups")),
      safe(api("/api/admin/payment-proofs")),
    ]);
    const [allocations, contacts, newsletter, teacherProfiles, blog] = await Promise.all([
      safe(api("/api/admin/allocations")),
      safe(api("/api/admin/contacts")),
      safe(api("/api/admin/newsletter")),
      safe(api("/api/admin/teacher-profiles")),
      safe(api("/api/admin/blog")),
    ]);
    state.subjectOptions = ov.subject_options || [];
    state.leads = leads.leads || [];
    state.feedback = fb.feedback || [];
    state.requests = sr.subject_requests || [];
    state.students = students.students || [];
    state.applications = apps.applications || [];
    state.teachers = teachers.teachers || [];
    state.teacherProfiles = teacherProfiles.teachers || []; // profiles with role=teacher
    state.courses = courses.courses || [];
    state.groups = groups.groups || [];
    state.payments = payments.proofs || [];
    state.allocations = allocations.allocations || [];
    state.contacts = contacts.contacts || [];
    state.newsletter = newsletter.subscribers || [];
    state.blog = blog.posts || [];
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
  renderBlog();
  renderCourses();
  renderGroups();
  renderPayments();
  renderAllocations();
  renderContacts();
  renderNewsletter();

  setCount("leads", state.leads.length);
  setCount("students", state.students.length);
  setCount("applications", state.applications.length);
  setCount("teachers", state.teachers.filter(t => t.active).length);
  setCount("blog", state.blog.length);
  setCount("courses", state.courses.length);
  setCount("groups", state.groups.length);
  setCount("payments", (state.payments || []).filter(p => p.status === "pending").length);
  setCount("feedback", state.feedback.length);
  setCount("requests", state.requests.length);
  setCount("allocations", (state.allocations || []).length);
  setCount("contacts", (state.contacts || []).length);
  setCount("newsletter", (state.newsletter || []).length);
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
        <div class="tile"><div class="tile-top"><span class="tile-ic lav">📄</span>
          <span class="tile-lbl">Papers done</span></div><b>${st.papers_done ?? 0}</b>
          <small>full past papers</small></div>
        <div class="tile"><div class="tile-top"><span class="tile-ic grn">📅</span>
          <span class="tile-lbl">Classes held</span></div><b>${st.classes_held ?? 0}</b>
          <small>${st.last_class ? "last " + esc(st.last_class) : "none logged"}</small></div>
        <div class="tile ${st.open_homework ? "tile-hot" : ""}">
          <div class="tile-top"><span class="tile-ic org">📝</span>
          <span class="tile-lbl">Open homework</span></div><b>${st.open_homework ?? 0}</b>
          <small>${st.open_homework ? "awaiting the student" : "all caught up"}</small></div>
        <div class="tile"><div class="tile-top"><span class="tile-ic lav">📚</span>
          <span class="tile-lbl">Subjects</span></div><b>${active.length}</b>
          <small>${esc(active.map(e => e.name).join(", ") || "none enrolled")}</small></div>
      </div>`;

    const subjects = d.by_syllabus.length ? d.by_syllabus.map(s => {
      // Denominator is the whole syllabus, and only CHAPTERS count — the
      // server now sends both, so nothing is recomputed from touched rows here.
      const total = s.chapters_total || 1;
      const pct = s.pct ?? Math.round(s.confident / total * 100);
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
            <span class="prog-of">of <b>${total}</b> chapters</span>
          </div>
          ${s.subtopics?.length ? `<div class="prog-sub">
            <b>${s.sub_confident}</b> of ${s.subtopics.length} subtopics confident</div>` : ""}
          <div class="topic-list">${s.topics.map(t => `
            <span class="topic-chip ${esc(t.status || "not_started")}">${esc(t.topic)}</span>`).join("")}</div>
        </div>`;
    }).join("") : empty("📗", "No topics tracked yet.",
                        "Progress appears once they mark topics in their dashboard.");

    const quizzes = d.quizzes.length
      ? quizGroups(d.quizzes)
      : empty("✍️", "No quizzes attempted yet.");

    const PLAN_LABELS  = { free: "Free", solo: "Solo", three: "3 Subjects", all: "All Subjects" };
    const PLAN_PRICES  = { free: "No charge", solo: "PKR 1,000/mo", three: "PKR 2,000/mo", all: "PKR 3,000/mo" };
    const PLAN_DESC    = {
      free:  "Preview only — minimal quotas",
      solo:  "1 subject, unlimited practice tools",
      three: "Up to 3 subjects, unlimited access",
      all:   "All subjects, full platform access",
    };
    const PLAN_COLORS  = { free: "", solo: "badge-lav", three: "badge-ok", all: "badge-issue" };
    const currentPlan  = p.plan || "free";
    const isTrial      = !!p.plan_trial;
    const planBadge    = `<span class="badge ${PLAN_COLORS[currentPlan] || ""}">${PLAN_LABELS[currentPlan] || currentPlan}${isTrial ? " · trial" : ""}</span>`;

    const fmtIso = iso => iso ? iso.slice(0,10) : "—";
    const planMeta = currentPlan !== "free"
      ? `<span style="font-size:11px;color:var(--grey);display:block;margin-top:2px;">
           Started ${fmtIso(p.plan_started_at)} · Expires ${fmtIso(p.plan_expires_at)}
         </span>`
      : "";

    // Plan picker cards
    const planCards = ["free","solo","three","all"].map(pl => `
      <label class="plan-card${pl === currentPlan ? " selected" : ""}" style="cursor:pointer;">
        <input type="radio" name="plan-pick-${esc(p.id)}" value="${pl}"${pl === currentPlan ? " checked" : ""}
               style="position:absolute;opacity:0;pointer-events:none">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px;">
          <b style="font-size:.82rem;">${PLAN_LABELS[pl]}</b>
          <span style="font-size:.75rem;color:var(--grey);white-space:nowrap;">${PLAN_PRICES[pl]}</span>
        </div>
        <span style="font-size:.72rem;color:var(--grey);display:block;margin-top:2px;">${PLAN_DESC[pl]}</span>
      </label>`).join("");

    const planControl = `
      <div class="detail-row plan-row" id="plan-row-${esc(p.id)}">
        <span class="k">Plan</span>
        <span class="v" style="flex-direction:column;align-items:flex-start;gap:8px;">
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            ${planBadge}${planMeta}
          </div>
          <div class="plan-cards" id="plan-cards-${esc(p.id)}" style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;width:100%;">
            ${planCards}
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <button class="btn btn-xs" id="plan-save-${esc(p.id)}">Grant 30 days</button>
            <button class="btn btn-xs btn-ghost" id="plan-trial-${esc(p.id)}">Grant 7-day trial</button>
            <span style="font-size:.72rem;color:var(--grey);">Expiry auto-set · no date entry needed</span>
          </div>
        </span>
      </div>`;

    const profile = [
      ["Email", p.email], ["Phone", p.phone], ["Grade", p.grade],
      ["Gender", p.gender], ["Birthday", p.birthday],
      ["Joined", fmtDate(p.created_at)],
      ["Profile complete", p.profile_complete ? "Yes" : "No"],
      ["Enrolled", active.map(e => e.name).join(", ") || "—"],
    ].map(([k, v]) => `<div class="detail-row"><span class="k">${esc(k)}</span>
        <span class="v">${esc(v || "—")}</span></div>`).join("") + planControl;

    $("view-student").innerHTML = `
      <button class="back-link" data-goto="students">← Back to students</button>
      ${hero}${tiles}
      ${StudentConsole.tabsHtml()}
      <details class="stu-more">
        <summary>Snapshot, profile and quiz log</summary>
        <div class="grid-2">
          <div>${panel("Subject progress", `<div class="panel-body">${subjects}</div>`)}</div>
          <div>${panel("Profile", `<div class="panel-body">${profile}</div>`)}</div>
        </div>
        ${panel(`Quiz log (${d.quizzes.length})`, `<div class="panel-body">${quizzes}</div>`)}
      </details>`;

    wireGoto($("view-student"));
    StudentConsole.mount(d, $("view-student"));
    StudentConsole.wireTabs($("view-student"));

    // Highlight selected plan card on click
    $(`plan-cards-${p.id}`)?.querySelectorAll("label.plan-card").forEach(card => {
      card.addEventListener("click", () => {
        $(`plan-cards-${p.id}`).querySelectorAll("label.plan-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
      });
    });

    // Wire plan buttons — plan_started_at and plan_expires_at auto-set server-side from now
    const _doPlanSave = async (trial) => {
      const checked = $(`plan-cards-${p.id}`)?.querySelector("input[type=radio]:checked");
      const newPlan = checked ? checked.value : "free";
      const saveBtn = $(`plan-save-${p.id}`);
      const trialBtn = $(`plan-trial-${p.id}`);
      const activeBtn = trial ? trialBtn : saveBtn;
      if (activeBtn) { activeBtn.disabled = true; activeBtn.textContent = "Saving…"; }
      try {
        await api(`/api/admin/students/${encodeURIComponent(p.id)}/plan`, {
          method: "PATCH",
          body: { plan: newPlan, trial },
        });
        const label = trial ? `${PLAN_LABELS[newPlan] || newPlan} · trial` : (PLAN_LABELS[newPlan] || newPlan);
        toast(`Plan set to ${label} — started from now`);
        const badge = $(`plan-row-${p.id}`)?.querySelector(".badge");
        if (badge) badge.textContent = label;
      } catch (ex) {
        toast(ex.message, "error");
      } finally {
        if (activeBtn) { activeBtn.disabled = false; activeBtn.textContent = trial ? "Grant 7-day trial" : "Grant 30 days"; }
      }
    };
    $(`plan-save-${p.id}`)?.addEventListener("click", () => _doPlanSave(false));
    $(`plan-trial-${p.id}`)?.addEventListener("click", () => _doPlanSave(true));
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
      if (result.temp_password) {
        // Show the temp password so the admin can share it manually if email failed
        const emailNote = result.email_sent
          ? "✅ Welcome email sent."
          : `⚠️ Email not sent${result.email_error ? ": " + result.email_error : ""}. Share the password below manually.`;
        openDrawer(`
          <h2>Teacher approved ✓</h2>
          <p>${emailNote}</p>
          <div class="dr-block">
            <h3>Login credentials</h3>
            <div class="detail-row"><span class="k">Email</span>
              <span class="v">${esc(result.application?.email || "")}</span></div>
            <div class="detail-row"><span class="k">Temp password</span>
              <span class="v"><code id="tmp-pwd">${esc(result.temp_password)}</code>
                <button class="btn btn-xs" onclick="navigator.clipboard.writeText('${esc(result.temp_password)}');this.textContent='Copied!'">Copy</button>
              </span></div>
          </div>
          <p class="sub">The teacher will be prompted to change this on first login.</p>
          <div class="btn-row"><button class="btn btn-primary" id="ap-done">Done</button></div>`);
        $("ap-done").addEventListener("click", closeDrawer);
      } else if (result.profile_id) {
        // Existing account promoted — no temp password
        toast("Approved — existing account promoted to teacher.");
      } else {
        toast("Approved — they're live on the Teachers page.");
      }
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
        <button class="btn" data-students="${t.id}" data-tname="${esc(t.name || "")}">Students</button>
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
  $("view-teachers").querySelectorAll("[data-students]").forEach(b =>
    b.addEventListener("click", () => openTeacherStudents(Number(b.dataset.students), b.dataset.tname)));
}

async function openTeacherStudents(teacherId, teacherName) {
  openDrawer(`<h2>Students — ${esc(teacherName)}</h2><p class="sub">Loading…</p>`);
  let assignments = [];
  try {
    const r = await api(`/api/admin/teachers/${teacherId}/students`);
    assignments = r.assignments || [];
  } catch (ex) {
    $("drawer-body").innerHTML = `<h2>Students — ${esc(teacherName)}</h2>
      ${empty("⚠️", "Couldn't load student links.", ex.message)}`;
    return;
  }

  function renderStudentRows() {
    if (!assignments.length) return `<p class="sub">No students assigned yet.</p>`;
    return `<div class="tbl-wrap"><table>
      <thead><tr><th>Student</th><th>Syllabus</th><th></th></tr></thead>
      <tbody>${assignments.map(a => `
        <tr>
          <td><strong>${esc(a.name || a.student_id || "—")}</strong>
            <div class="ts">${esc(a.email || "")}</div></td>
          <td><span class="pill">${esc(SUBJECT_LABELS[a.syllabus] || a.syllabus)}</span></td>
          <td><button class="btn btn-danger btn-xs"
                data-unassign="${esc(a.student_id)}"
                data-syl="${esc(a.syllabus)}">Remove</button></td>
        </tr>`).join("")}</tbody></table></div>`;
  }

  function rebuildDrawer() {
    $("drawer-body").innerHTML = `
      <h2>Students — ${esc(teacherName)}</h2>
      <p class="sub">Students this teacher is linked to per syllabus.</p>
      <div id="ts-list">${renderStudentRows()}</div>
      <div class="dr-block">
        <h3>Assign a student</h3>
        <div class="f-grid">
          <div class="f-field"><label>Student</label>
            <select id="ts-student">
              <option value="">— pick a student —</option>
              ${state.students.map(s => `<option value="${esc(s.id)}">${esc(s.name || s.email)}</option>`).join("")}
            </select></div>
          <div class="f-field"><label>Syllabus</label>
            <select id="ts-syllabus">
              <option value="">— pick a syllabus —</option>
              ${state.subjectOptions.map(o => `<option value="${esc(o.code)}">${esc(o.name)}</option>`).join("")}
            </select></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="ts-assign">Assign</button>
        </div>
      </div>`;

    $("drawer-body").querySelectorAll("[data-unassign]").forEach(b => {
      b.addEventListener("click", async () => {
        const sid = b.dataset.unassign, syl = b.dataset.syl;
        b.disabled = true;
        try {
          await api(`/api/admin/teachers/${teacherId}/students/${encodeURIComponent(sid)}?syllabus=${encodeURIComponent(syl)}`,
            { method: "DELETE" });
          assignments = assignments.filter(a => !(a.student_id === sid && a.syllabus === syl));
          rebuildDrawer();
          toast("Student removed.");
        } catch (ex) { toast(ex.message, true); b.disabled = false; }
      });
    });

    $("ts-assign").addEventListener("click", async () => {
      const sid = $("ts-student").value;
      const syl = $("ts-syllabus").value;
      if (!sid || !syl) return toast("Pick a student and a syllabus first.", true);
      const btn = $("ts-assign");
      btn.disabled = true;
      btn.textContent = "Assigning…";
      try {
        await api(`/api/admin/teachers/${teacherId}/students`,
          { method: "POST", body: { student_id: sid, syllabus: syl } });
        const student = state.students.find(s => s.id === sid);
        // Only add if not already listed (prevent duplicates in local state)
        if (!assignments.some(a => a.student_id === sid && a.syllabus === syl)) {
          assignments.push({
            student_id: sid, syllabus: syl,
            name: student?.name || "", email: student?.email || "",
          });
        }
        rebuildDrawer();
        toast("Student assigned.");
      } catch (ex) { toast(ex.message, true); }
      finally { if ($("ts-assign")) { $("ts-assign").disabled = false; $("ts-assign").textContent = "Assign"; } }
    });
  }

  rebuildDrawer();
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

/* ---- Blog ---------------------------------------------------------------- */

function toSlug(s) {
  return s.toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-");
}

function renderBlog() {
  const rows = state.blog.map(p => `
    <tr>
      <td>
        <strong>${esc(p.title || "—")}</strong>
        <div class="ts">/blog/${esc(p.slug || "")}</div>
      </td>
      <td><span class="badge ${p.published ? "badge-ok" : "badge-neutral"}">
        ${p.published ? "Live" : "Draft"}</span>
      </td>
      <td class="ts">${esc((p.published_at || p.updated_at || p.created_at || "").slice(0, 10))}</td>
      <td><div class="btn-row">
        <button class="btn" data-blog-edit="${p.id}">Edit</button>
        <button class="btn" data-blog-toggle="${p.id}"
          data-pub="${p.published ? "1" : "0"}">
          ${p.published ? "Unpublish" : "Publish"}
        </button>
        ${p.published
          ? `<a class="btn" href="/blog/${encodeURIComponent(p.slug || "")}"
               target="_blank" rel="noopener">View ↗</a>`
          : ""}
        <button class="btn btn-danger" data-blog-del="${p.id}">Delete</button>
      </div></td>
    </tr>`).join("");

  $("view-blog").innerHTML = panel(
    `${state.blog.length} post${state.blog.length === 1 ? "" : "s"}`,
    state.blog.length
      ? `<div style="overflow-x:auto"><table class="data-table"><thead><tr>
          <th>Title / URL</th><th>Status</th><th>Date</th><th></th>
         </tr></thead><tbody>${rows}</tbody></table></div>`
      : empty("✍️", "No posts yet.", "Add a post to start building your SEO blog."),
    `<button class="btn btn-primary" id="add-blog">+ New post</button>`);

  $("add-blog").addEventListener("click", () => openBlogEditor(null));

  $("view-blog").querySelectorAll("[data-blog-edit]").forEach(b =>
    b.addEventListener("click", () => openBlogEditor(Number(b.dataset.blogEdit))));

  $("view-blog").querySelectorAll("[data-blog-del]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm("Delete this post permanently?")) return;
      try {
        await api(`/api/admin/blog/${b.dataset.blogDel}`, { method: "DELETE" });
        toast("Post deleted.");
        const res = await api("/api/admin/blog");
        state.blog = res.posts || [];
        renderBlog();
        setCount("blog", state.blog.length);
      } catch (ex) { toast(ex.message, true); }
    }));

  $("view-blog").querySelectorAll("[data-blog-toggle]").forEach(b =>
    b.addEventListener("click", async () => {
      const id  = Number(b.dataset.blogToggle);
      const pub = b.dataset.pub === "1";
      b.disabled = true;
      try {
        await api(`/api/admin/blog/${id}`, {
          method: "PATCH", body: { published: !pub },
        });
        toast(pub ? "Post unpublished." : "Post is now live.");
        const res = await api("/api/admin/blog");
        state.blog = res.posts || [];
        renderBlog();
        setCount("blog", state.blog.length);
      } catch (ex) {
        toast(ex.message, true);
        b.disabled = false;
      }
    }));
}

/* Compact Markdown → HTML for the live preview. Mirrors the subset the server
   (blog.py) renders: headings, bold/italic/code, links, images, lists,
   blockquotes, fenced code, rules and paragraphs. It's a preview aid — the
   published page is rendered server-side. */
function mdToHtml(src) {
  if (!src || !src.trim())
    return '<p class="be-pv-empty">Your formatted post will appear here as you write.</p>';
  const e = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = t => e(t)
    .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1">')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let out = "", i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf = []; i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(e(lines[i])); i++; }
      i++; out += `<pre><code>${buf.join("\n")}</code></pre>`; continue;
    }
    if (/^###\s+/.test(line)) { out += `<h3>${inline(line.replace(/^###\s+/, ""))}</h3>`; i++; continue; }
    if (/^##\s+/.test(line))  { out += `<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`;  i++; continue; }
    if (/^#\s+/.test(line))   { out += `<h2>${inline(line.replace(/^#\s+/, ""))}</h2>`;   i++; continue; }
    if (/^(---|\*\*\*)\s*$/.test(line)) { out += "<hr>"; i++; continue; }
    if (/^>\s?/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(inline(lines[i].replace(/^>\s?/, ""))); i++; }
      out += `<blockquote>${buf.join("<br>")}</blockquote>`; continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { buf.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`); i++; }
      out += `<ul>${buf.join("")}</ul>`; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { buf.push(`<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`); i++; }
      out += `<ol>${buf.join("")}</ol>`; continue;
    }
    if (!line.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() &&
           !/^(#{1,3}\s|>|\s*[-*]\s|\s*\d+\.\s|```|---|\*\*\*)/.test(lines[i])) {
      buf.push(inline(lines[i])); i++;
    }
    out += `<p>${buf.join("<br>")}</p>`;
  }
  return out;
}

let _beEl = null;   // the mounted editor overlay, if any

function closeBlogEditor(force) {
  if (!_beEl) return;
  if (!force && _beEl.dataset.dirty === "1" &&
      !confirm("Discard your unsaved changes?")) return;
  _beEl.remove();
  _beEl = null;
  document.body.style.overflow = "";
}

/* Full-screen writing studio: toolbar + live preview + drag-drop image upload.
   Metadata (slug, excerpt, SEO) is auto-derived and tucked behind “Advanced”,
   so posting is just: title, write, publish. */
function openBlogEditor(postId) {
  const p = postId ? state.blog.find(x => x.id === postId) : null;
  closeBlogEditor(true);

  const el = document.createElement("div");
  el.className = "be-backdrop";
  el.dataset.dirty = "0";
  el.innerHTML = `
    <div class="be-modal" role="dialog" aria-label="${p ? "Edit post" : "New post"}">
      <header class="be-top">
        <div class="be-top-left">
          <span class="be-badge">✍️ ${p ? "Editing" : "New post"}</span>
          <span class="be-status" id="be-status"></span>
        </div>
        <div class="be-top-actions">
          <button class="btn" id="be-cancel" type="button">Cancel</button>
          <button class="btn" id="be-save" type="button">Save draft</button>
          <button class="btn btn-gold" id="be-publish" type="button">
            ${p?.published ? "Save &amp; keep live" : "Publish"}
          </button>
        </div>
      </header>

      <div class="be-cols">
        <div class="be-edit">
          <input id="be-title" class="be-title-input" value="${esc(p?.title || "")}"
                 placeholder="Post title…">

          <div class="be-cover" id="be-cover">
            <input type="file" id="be-cover-file" accept="image/*" hidden>
            <div class="be-cover-empty" id="be-cover-empty">
              <span class="be-cover-ico">🖼️</span>
              <div>
                <b>Add a cover image</b>
                <span class="ts">Drag &amp; drop, or click to upload — shown on the card and at the top of the post.</span>
              </div>
              <button class="btn" type="button" id="be-cover-pick">Choose image</button>
            </div>
            <div class="be-cover-set" id="be-cover-set" hidden>
              <img id="be-cover-img" alt="cover preview">
              <div class="be-cover-actions">
                <button class="btn" type="button" id="be-cover-replace">Replace</button>
                <button class="btn btn-danger" type="button" id="be-cover-remove">Remove</button>
              </div>
            </div>
          </div>

          <div class="be-toolbar" id="be-toolbar">
            <button type="button" data-wrap="**" title="Bold"><b>B</b></button>
            <button type="button" data-wrap="*" title="Italic"><i>I</i></button>
            <span class="be-tb-sep"></span>
            <button type="button" data-line="## " title="Heading">H2</button>
            <button type="button" data-line="### " title="Sub-heading">H3</button>
            <button type="button" data-line="- " title="Bullet list">• List</button>
            <button type="button" data-line="1. " title="Numbered list">1. List</button>
            <button type="button" data-line="> " title="Quote">❝ Quote</button>
            <span class="be-tb-sep"></span>
            <button type="button" id="be-tb-link" title="Link">🔗 Link</button>
            <button type="button" id="be-tb-img" title="Insert image">🖼 Image</button>
            <button type="button" data-wrap="\`" title="Inline code">&lt;/&gt;</button>
          </div>

          <textarea id="be-md" class="be-md"
            placeholder="Write your post here. Use the toolbar above — no need to know Markdown.">${esc(p?.body_markdown || "")}</textarea>
          <input type="file" id="be-body-file" accept="image/*" hidden>

          <div class="be-editfoot">
            <span class="ts" id="be-wc"></span>
            <button class="be-adv-toggle" id="be-adv-toggle" type="button">⚙ Advanced (URL &amp; SEO)</button>
          </div>

          <div class="be-adv" id="be-adv" hidden>
            <div class="f-field">
              <label>URL slug <span class="ts">auto-filled from the title</span></label>
              <input id="be-slug" value="${esc(p?.slug || "")}"
                     placeholder="how-to-ace-o-level-physics" style="font-family:monospace;font-size:.82rem">
            </div>
            <div class="f-field">
              <label>Excerpt <span class="ts">the summary shown on the blog card</span></label>
              <textarea id="be-excerpt" rows="2"
                placeholder="A one-line summary. Leave blank to auto-generate from the post.">${esc(p?.excerpt || "")}</textarea>
            </div>
            <div class="f-grid">
              <div class="f-field">
                <label>Author</label>
                <input id="be-author" value="${esc(p?.author || "Muhammad Taahaa")}">
              </div>
              <div class="f-field">
                <label>SEO title <span class="ts">optional</span></label>
                <input id="be-meta-title" value="${esc(p?.meta_title || "")}"
                       placeholder="Defaults to the post title">
              </div>
            </div>
            <div class="f-field">
              <label>SEO description <span class="ts">optional</span></label>
              <textarea id="be-meta-desc" rows="2"
                placeholder="Defaults to the excerpt.">${esc(p?.meta_desc || "")}</textarea>
            </div>
          </div>
        </div>

        <div class="be-preview-wrap">
          <div class="be-preview-lbl">Live preview</div>
          <article class="be-preview" id="be-preview"></article>
        </div>
      </div>
    </div>`;

  document.body.appendChild(el);
  document.body.style.overflow = "hidden";
  _beEl = el;

  const $$ = sel => el.querySelector(sel);
  const titleEl = $$("#be-title");
  const mdEl    = $$("#be-md");
  const slugEl  = $$("#be-slug");
  const excerptEl = $$("#be-excerpt");
  const previewEl = $$("#be-preview");
  const wcEl    = $$("#be-wc");
  const statusEl = $$("#be-status");
  let slugEdited = !!p?.slug;
  let coverUrl   = p?.cover_url || "";

  const markDirty = () => { el.dataset.dirty = "1"; };

  const renderPreview = () => {
    const cover = coverUrl
      ? `<img class="be-pv-cover" src="${esc(coverUrl)}" alt="">` : "";
    const title = titleEl.value.trim()
      ? `<h1 class="be-pv-title">${esc(titleEl.value.trim())}</h1>` : "";
    previewEl.innerHTML =
      `${cover}${title}<div class="pbody-preview">${mdToHtml(mdEl.value)}</div>`;
  };

  const updateWC = () => {
    const words = mdEl.value.trim().split(/\s+/).filter(Boolean).length;
    wcEl.textContent = `${words} word${words === 1 ? "" : "s"} · ~${Math.max(1, Math.ceil(words / 200))} min read`;
  };

  const setCover = (url, dirty = true) => {
    coverUrl = url || "";
    const hasCover = !!coverUrl;
    $$("#be-cover-empty").hidden = hasCover;
    $$("#be-cover-set").hidden = !hasCover;
    if (hasCover) $$("#be-cover-img").src = coverUrl;
    if (dirty) markDirty();
    renderPreview();
  };

  titleEl.addEventListener("input", () => {
    if (!slugEdited) slugEl.value = toSlug(titleEl.value);
    markDirty(); renderPreview();
  });
  slugEl.addEventListener("input", () => { slugEdited = true; markDirty(); });
  excerptEl.addEventListener("input", markDirty);
  mdEl.addEventListener("input", () => { markDirty(); updateWC(); renderPreview(); });

  // ── Toolbar: wrap selection / prefix lines / insert link ──────────────────
  const applyWrap = (token) => {
    const s = mdEl.selectionStart, e2 = mdEl.selectionEnd;
    const sel = mdEl.value.slice(s, e2) || "text";
    mdEl.setRangeText(token + sel + token, s, e2, "select");
    mdEl.focus(); markDirty(); updateWC(); renderPreview();
  };
  const applyLinePrefix = (prefix) => {
    const s = mdEl.selectionStart, e2 = mdEl.selectionEnd;
    const val = mdEl.value;
    const from = val.lastIndexOf("\n", s - 1) + 1;
    const block = val.slice(from, e2);
    const next = block.split("\n").map(l => prefix + l).join("\n");
    mdEl.setRangeText(next, from, e2, "select");
    mdEl.focus(); markDirty(); updateWC(); renderPreview();
  };
  const insertText = (text) => {
    const s = mdEl.selectionStart, e2 = mdEl.selectionEnd;
    mdEl.setRangeText(text, s, e2, "end");
    mdEl.focus(); markDirty(); updateWC(); renderPreview();
  };

  el.querySelectorAll("[data-wrap]").forEach(b =>
    b.addEventListener("click", () => applyWrap(b.dataset.wrap)));
  el.querySelectorAll("[data-line]").forEach(b =>
    b.addEventListener("click", () => applyLinePrefix(b.dataset.line)));
  $$("#be-tb-link").addEventListener("click", () => {
    const url = prompt("Link URL (https://…)");
    if (!url) return;
    const s = mdEl.selectionStart, e2 = mdEl.selectionEnd;
    const sel = mdEl.value.slice(s, e2) || "link text";
    mdEl.setRangeText(`[${sel}](${url})`, s, e2, "end");
    mdEl.focus(); markDirty(); updateWC(); renderPreview();
  });

  // ── Image upload (cover + inline) ─────────────────────────────────────────
  const doUpload = async (file, onDone) => {
    if (!file) return;
    if (!/^image\//.test(file.type)) { toast("That's not an image file.", true); return; }
    statusEl.textContent = "Uploading image…";
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await upload("/api/admin/blog/upload", fd);
      onDone(res.url);
      statusEl.textContent = "";
    } catch (ex) { statusEl.textContent = ""; toast(ex.message, true); }
  };

  const coverFile = $$("#be-cover-file");
  $$("#be-cover-pick").addEventListener("click", () => coverFile.click());
  $$("#be-cover-replace").addEventListener("click", () => coverFile.click());
  $$("#be-cover-remove").addEventListener("click", () => setCover(""));
  coverFile.addEventListener("change", () =>
    doUpload(coverFile.files[0], (url) => setCover(url)));

  const coverBox = $$("#be-cover");
  ["dragover", "dragenter"].forEach(ev => coverBox.addEventListener(ev, e => {
    e.preventDefault(); coverBox.classList.add("be-drag");
  }));
  ["dragleave", "drop"].forEach(ev => coverBox.addEventListener(ev, e => {
    e.preventDefault(); coverBox.classList.remove("be-drag");
  }));
  coverBox.addEventListener("drop", e =>
    doUpload(e.dataTransfer.files[0], (url) => setCover(url)));

  const bodyFile = $$("#be-body-file");
  $$("#be-tb-img").addEventListener("click", () => bodyFile.click());
  bodyFile.addEventListener("change", () =>
    doUpload(bodyFile.files[0], (url) => insertText(`\n![](${url})\n`)));

  // ── Advanced toggle ───────────────────────────────────────────────────────
  $$("#be-adv-toggle").addEventListener("click", () => {
    const adv = $$("#be-adv");
    adv.hidden = !adv.hidden;
    $$("#be-adv-toggle").classList.toggle("open", !adv.hidden);
  });

  // ── Save / publish ────────────────────────────────────────────────────────
  const collect = (publish) => ({
    title:         titleEl.value.trim(),
    slug:          slugEl.value.trim() || toSlug(titleEl.value),
    excerpt:       excerptEl.value.trim() || null,
    body_markdown: mdEl.value,
    cover_url:     coverUrl || null,
    author:        $$("#be-author").value.trim() || "Muhammad Taahaa",
    meta_title:    $$("#be-meta-title").value.trim() || null,
    meta_desc:     $$("#be-meta-desc").value.trim() || null,
    ...(publish !== null ? { published: publish } : {}),
  });

  const save = async (publish, btn) => {
    const data = collect(publish);
    if (!data.title) { toast("Give your post a title first.", true); titleEl.focus(); return; }
    if (!data.slug)  { toast("A URL slug is required (open Advanced).", true); return; }
    btn.disabled = true;
    statusEl.textContent = "Saving…";
    try {
      if (p) await api(`/api/admin/blog/${p.id}`, { method: "PATCH", body: data });
      else   await api("/api/admin/blog", { method: "POST", body: data });
      el.dataset.dirty = "0";
      toast(publish ? "Post published ✓" : "Draft saved ✓");
      closeBlogEditor(true);
      const res  = await api("/api/admin/blog");
      state.blog = res.posts || [];
      renderBlog();
      setCount("blog", state.blog.length);
    } catch (ex) {
      statusEl.textContent = "";
      btn.disabled = false;
      toast(ex.message, true);
    }
  };

  $$("#be-save").addEventListener("click", (e) => save(p ? null : false, e.currentTarget));
  $$("#be-publish").addEventListener("click", (e) => save(true, e.currentTarget));
  $$("#be-cancel").addEventListener("click", () => closeBlogEditor(false));
  el.addEventListener("mousedown", (e) => { if (e.target === el) closeBlogEditor(false); });

  // Initial paint
  if (coverUrl) setCover(coverUrl, false);
  updateWC();
  renderPreview();
  titleEl.focus();
}

/* ---- Courses ------------------------------------------------------------- */

function renderCourses() {
  const rows = state.courses.map(c => `
    <tr>
      <td>
        <strong>${esc(c.title || "—")}</strong>
        <div class="ts">${esc(c.slug || "")}</div>
      </td>
      <td><span class="pill">${esc(c.level || "")}</span></td>
      <td><span class="pill">${esc(c.syllabus_code || "")}</span></td>
      <td><span class="badge ${c.published ? "badge-ok" : "badge-neutral"}">
        ${c.published ? "Live" : "Draft"}</span></td>
      <td><div class="btn-row">
        <button class="btn" data-course-edit="${c.id}">Edit</button>
        <button class="btn" data-course-toggle="${c.id}" data-pub="${c.published ? "1" : "0"}">
          ${c.published ? "Unpublish" : "Publish"}
        </button>
        <a class="btn" href="/course.html?slug=${encodeURIComponent(c.slug || "")}"
           target="_blank" rel="noopener">View ↗</a>
        <button class="btn btn-danger" data-course-del="${c.id}">Delete</button>
      </div></td>
    </tr>`).join("");

  $("view-courses").innerHTML = panel(
    `${state.courses.length} course${state.courses.length === 1 ? "" : "s"}`,
    state.courses.length
      ? table(["Title / slug", "Level", "Syllabus", "Status", ""], rows)
      : empty("📖", "No courses yet.", "Add a course to create a public SEO landing page."),
    `<button class="btn btn-primary" id="add-course">+ Add course</button>`);

  $("add-course").addEventListener("click", () => openCourseForm(null));

  $("view-courses").querySelectorAll("[data-course-edit]").forEach(b =>
    b.addEventListener("click", () => openCourseForm(Number(b.dataset.courseEdit))));

  $("view-courses").querySelectorAll("[data-course-del]").forEach(b =>
    b.addEventListener("click", () => deleteCourse(Number(b.dataset.courseDel))));

  $("view-courses").querySelectorAll("[data-course-toggle]").forEach(b =>
    b.addEventListener("click", async () => {
      const id = Number(b.dataset.courseToggle);
      const pub = b.dataset.pub === "1";
      b.disabled = true;
      try {
        await api(`/api/admin/courses/${id}`, {
          method: "PATCH", body: { published: !pub },
        });
        toast(pub ? "Course unpublished." : "Course published — live now.");
        loadAll();
      } catch (ex) {
        toast(ex.message, true);
        b.disabled = false;
      }
    }));
}

function openCourseForm(courseId) {
  const c = courseId ? state.courses.find(x => x.id === courseId) : null;

  let what = [];
  try { what = JSON.parse(c?.what_you_get_json || "[]"); } catch (e) {}

  const SUBJECT_PRESETS = [
    { label: "Physics", codes: { "O Level": "5054", "IGCSE": "0625", "A Level": "9702" } },
    { label: "Mathematics", codes: { "O Level": "4024", "IGCSE": "0580" } },
    { label: "Computer Science", codes: { "O Level": "2210", "IGCSE": "0478" } },
  ];

  openDrawer(`
    <h2>${c ? "Edit course" : "New course"}</h2>
    <p class="sub">Fields marked * are required.</p>

    <div class="dr-block">
      <h3>Identity</h3>
      <div class="f-grid">
        <div class="f-field"><label>Title *</label>
          <input id="cr-title" value="${esc(c?.title || "")}"
                 placeholder="e.g. O Level Physics 5054"></div>
        <div class="f-field"><label>Slug * <span class="ts">auto-generated from title</span></label>
          <input id="cr-slug" value="${esc(c?.slug || "")}"
                 placeholder="o-level-physics-5054" style="font-family:monospace;font-size:.82rem"></div>
      </div>

      <div class="f-field" style="margin-bottom:6px"><label>Subject *</label>
        <div class="cr-preset-row" id="cr-presets">
          ${SUBJECT_PRESETS.map(s =>
            `<button type="button" class="btn btn-xs cr-preset${c?.subject === s.label ? " active" : ""}"
               data-subj="${s.label}" data-codes='${JSON.stringify(s.codes)}'>${s.label}</button>`
          ).join("")}
        </div>
        <input id="cr-subject" value="${esc(c?.subject || "")}" placeholder="or type manually" style="margin-top:6px">
      </div>

      <div class="f-grid">
        <div class="f-field"><label>Level *</label>
          <select id="cr-level">
            ${["O Level","IGCSE","A Level"].map(l =>
              `<option${c?.level === l ? " selected" : ""}>${l}</option>`).join("")}
          </select></div>
        <div class="f-field"><label>Syllabus code *</label>
          <input id="cr-code" value="${esc(c?.syllabus_code || "")}"
                 placeholder="e.g. 5054" style="font-family:monospace"></div>
      </div>

      <div class="f-grid">
        <div class="f-field"><label>Tagline <span class="ts">shown on course card</span></label>
          <input id="cr-tagline" value="${esc(c?.tagline || "")}"
                 placeholder="Master structured questions from 6 years of past papers"></div>
        <div class="f-field"><label>Display order</label>
          <input id="cr-order" type="number" value="${c?.sort_order ?? 0}" style="max-width:90px"></div>
      </div>
    </div>

    <div class="dr-block">
      <h3>What students get <span class="ts">one outcome per line — shown as ✓ bullets</span></h3>
      <textarea id="cr-what" rows="6" style="font-size:.82rem;line-height:1.6"
        placeholder="Master every topic in the Cambridge syllabus&#10;Tackle exam questions with full model answers&#10;Predict likely exam themes from 6 years of past papers&#10;Build exam technique through weekly timed practice&#10;Get WhatsApp support between sessions">${
        what.map(l => esc(l)).join("\n")}</textarea>
      <div class="cr-counter" id="cr-what-count">0 bullets</div>
    </div>

    <div class="dr-block">
      <h3>Overview <span class="ts">optional — "About this course" section on the landing page</span></h3>
      <p class="ts" style="margin:0 0 8px">Plain text or simple HTML (&lt;p&gt;, &lt;strong&gt;, &lt;ul&gt;). Keep it 2–4 sentences.</p>
      <textarea id="cr-overview" rows="4" placeholder="This course covers the full Cambridge O Level Physics syllabus (5054), taught through real past-paper questions from 2019–2025. Every session builds exam technique alongside subject knowledge.">${esc(c?.overview_html || "")}</textarea>
    </div>

    <div class="dr-block">
      <h3>How we teach <span class="ts">optional — "Approach" section</span></h3>
      <p class="ts" style="margin:0 0 8px">Describe your teaching style: pacing, feedback, homework, etc.</p>
      <textarea id="cr-approach" rows="4" placeholder="We start every lesson by reviewing the previous week's marked paper, then introduce one new topic through worked examples before students attempt a timed section independently.">${esc(c?.approach_html || "")}</textarea>
    </div>

    <details class="dr-block" style="cursor:default">
      <summary style="cursor:pointer;list-style:none;display:flex;align-items:center;justify-content:space-between">
        <h3 style="margin:0;display:inline">SEO overrides <span class="ts" style="font-weight:400">(optional — auto-generated if blank)</span></h3>
        <span class="ts">▸ expand</span>
      </summary>
      <div style="margin-top:14px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <span class="ts">Override the auto-generated title &amp; description for custom Google phrasing.</span>
        <button type="button" class="btn btn-xs" id="cr-seo-autofill">✦ Auto-fill</button>
      </div>

      <div class="f-field">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <label>Meta title</label>
          <span id="cr-mtitle-count" class="cr-seo-count">0 / 60</span>
        </div>
        <input id="cr-mtitle" value="${esc(c?.meta_title || "")}"
               placeholder="e.g. O Level Physics 5054 — PrepWithTee Cambridge Tutoring">
        <div class="cr-seo-hint">Ideal: 50–60 characters. Appears as the blue link in Google results.</div>
      </div>

      <div class="f-field" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <label>Meta description</label>
          <span id="cr-mdesc-count" class="cr-seo-count">0 / 160</span>
        </div>
        <textarea id="cr-mdesc" rows="3"
          placeholder="Expert O Level Physics tutoring in Lahore. Past papers, mark schemes and weekly 1-on-1 sessions — tailored to Cambridge 5054. Book a free demo.">${esc(c?.meta_description || "")}</textarea>
        <div class="cr-seo-hint">Ideal: 140–160 characters. The snippet shown under the title in Google.</div>
      </div>

      <div class="cr-google-preview" id="cr-gpreview">
        <div class="cgp-label">Google preview</div>
        <div class="cgp-url">prepwithtee.com › course</div>
        <div class="cgp-title" id="cgp-title">—</div>
        <div class="cgp-desc" id="cgp-desc">—</div>
      </div>
      <p class="ts" style="margin-top:10px">
        Leave both blank and the page auto-generates them from title, level, and tagline.
        Only fill in if you want a custom phrasing for Google.
      </p>
    </div>
    </details>

    <div class="dr-block">
      <div class="f-field"><label>Visibility</label>
        <select id="cr-pub">
          <option value="0"${!c?.published ? " selected" : ""}>Draft — not shown publicly</option>
          <option value="1"${c?.published ? " selected" : ""}>Published — live on site</option>
        </select></div>
    </div>

    <div class="btn-row" style="margin-top:8px">
      <button class="btn btn-primary" id="cr-save">${c ? "Save changes" : "Create course"}</button>
      <button class="btn" id="cr-cancel">Cancel</button>
    </div>`);

  $("cr-cancel").addEventListener("click", closeDrawer);

  // Subject preset chips
  $("cr-presets").querySelectorAll(".cr-preset").forEach(btn => {
    btn.addEventListener("click", () => {
      $("cr-presets").querySelectorAll(".cr-preset").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      $("cr-subject").value = btn.dataset.subj;
      const codes = JSON.parse(btn.dataset.codes);
      const level = $("cr-level").value;
      if (codes[level]) $("cr-code").value = codes[level];
      updateSlug();
    });
  });
  $("cr-level").addEventListener("change", () => {
    const active = $("cr-presets").querySelector(".cr-preset.active");
    if (active) {
      const codes = JSON.parse(active.dataset.codes);
      const level = $("cr-level").value;
      if (codes[level]) $("cr-code").value = codes[level];
    }
    updateSlug();
  });

  // Auto-generate slug from title when creating
  function updateSlug() {
    if ($("cr-slug").dataset.touched) return;
    const subj = $("cr-subject").value.trim().toLowerCase().replace(/\s+/g,"-");
    const code = $("cr-code").value.trim();
    const lvl  = $("cr-level").value.toLowerCase().replace(/\s+/g,"-");
    if (subj && code) $("cr-slug").value = `${lvl}-${subj}-${code}`;
    else if ($("cr-title").value.trim()) {
      $("cr-slug").value = $("cr-title").value.toLowerCase().trim()
        .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    }
  }
  $("cr-title").addEventListener("input", () => { if (!$("cr-slug").dataset.touched) updateSlug(); });
  $("cr-code").addEventListener("input", () => { if (!$("cr-slug").dataset.touched) updateSlug(); });
  $("cr-subject").addEventListener("input", () => { if (!$("cr-slug").dataset.touched) updateSlug(); });
  $("cr-slug").addEventListener("input", () => { $("cr-slug").dataset.touched = "1"; });

  // What bullets counter
  function updateWhatCount() {
    const n = $("cr-what").value.split("\n").map(l => l.trim()).filter(Boolean).length;
    $("cr-what-count").textContent = `${n} bullet${n === 1 ? "" : "s"}`;
    $("cr-what-count").style.color = n >= 3 && n <= 6 ? "var(--green,#2a7a4b)" : n > 6 ? "#b45309" : "var(--grey)";
  }
  $("cr-what").addEventListener("input", updateWhatCount);
  updateWhatCount();

  // SEO counters + Google preview
  function seoCount(el, countEl, ideal) {
    const n = el.value.length;
    const [lo, hi] = ideal;
    countEl.textContent = `${n} / ${hi}`;
    countEl.style.color = n >= lo && n <= hi ? "var(--green,#2a7a4b)" : n > hi ? "#dc2626" : n > 0 ? "#b45309" : "var(--grey)";
  }
  function updatePreview() {
    const title = $("cr-mtitle").value.trim() ||
      `${$("cr-title").value.trim()} — PrepWithTee`;
    const desc  = $("cr-mdesc").value.trim() ||
      $("cr-tagline").value.trim() || "Cambridge past-paper tutoring with PrepWithTee.";
    $("cgp-title").textContent = title.slice(0, 70);
    $("cgp-desc").textContent  = desc.slice(0, 160);
  }
  [$("cr-mtitle"), $("cr-mdesc"), $("cr-title"), $("cr-tagline")].forEach(el => {
    if (el) el.addEventListener("input", () => {
      if ($("cr-mtitle")) seoCount($("cr-mtitle"), $("cr-mtitle-count"), [50, 60]);
      if ($("cr-mdesc"))  seoCount($("cr-mdesc"),  $("cr-mdesc-count"),  [140, 160]);
      updatePreview();
    });
  });
  // Init counters
  if ($("cr-mtitle")) { seoCount($("cr-mtitle"), $("cr-mtitle-count"), [50, 60]); updatePreview(); }
  if ($("cr-mdesc"))  seoCount($("cr-mdesc"), $("cr-mdesc-count"), [140, 160]);

  // Auto-fill SEO from title + tagline
  const seoBtn = $("cr-seo-autofill");
  if (seoBtn) seoBtn.addEventListener("click", () => {
    const t = $("cr-title").value.trim();
    const lvl = $("cr-level").value;
    const code = $("cr-code").value.trim();
    const tag = $("cr-tagline").value.trim();
    if (t) $("cr-mtitle").value = `${t} — PrepWithTee Cambridge ${lvl} Tutoring`.slice(0, 60);
    if (tag) $("cr-mdesc").value = (`${tag} Past papers, mark schemes and 1-on-1 sessions with expert Cambridge tutors. Book a free demo lesson.`).slice(0, 160);
    seoCount($("cr-mtitle"), $("cr-mtitle-count"), [50, 60]);
    seoCount($("cr-mdesc"),  $("cr-mdesc-count"),  [140, 160]);
    updatePreview();
  });

  $("cr-save").addEventListener("click", async () => {
    const btn = $("cr-save");
    const title = $("cr-title").value.trim();
    const slug  = $("cr-slug").value.trim();
    const level = $("cr-level").value;
    const subject = $("cr-subject").value.trim();
    const syllabus_code = $("cr-code").value.trim();
    if (!title)  return toast("Title is required.", true);
    if (!slug)   return toast("Slug is required.", true);
    if (!subject) return toast("Subject is required.", true);
    if (!syllabus_code) return toast("Syllabus code is required.", true);

    const whatLines = $("cr-what").value.split("\n")
      .map(l => l.trim()).filter(Boolean);

    btn.disabled = true;
    btn.textContent = "Saving…";
    const body = {
      title, slug, level, subject, syllabus_code,
      tagline:          $("cr-tagline").value.trim() || null,
      overview_html:    $("cr-overview").value.trim() || null,
      approach_html:    $("cr-approach").value.trim() || null,
      what_you_get_json: JSON.stringify(whatLines),
      meta_title:       $("cr-mtitle").value.trim() || null,
      meta_description: $("cr-mdesc").value.trim() || null,
      sort_order:       Number($("cr-order").value || 0),
      published:        $("cr-pub").value === "1",
    };
    try {
      if (c) await api(`/api/admin/courses/${c.id}`, { method: "PUT", body });
      else   await api("/api/admin/courses", { method: "POST", body });
      closeDrawer();
      toast(c ? "Course updated." : "Course created.");
      loadAll();
    } catch (ex) {
      toast(ex.message, true);
      btn.disabled = false;
      btn.textContent = c ? "Save changes" : "Create course";
    }
  });
}

async function deleteCourse(courseId) {
  const c = state.courses.find(x => x.id === courseId);
  if (!confirm(`Delete "${c?.title || "this course"}" permanently?`)) return;
  try {
    await api(`/api/admin/courses/${courseId}`, { method: "DELETE" });
    toast("Course deleted.");
    loadAll();
  } catch (ex) { toast(ex.message, true); }
}

/* ---- Groups -------------------------------------------------------------- */

const GROUP_STATUS_LABELS = { draft: "Draft", active: "Active", closed: "Closed" };
const GROUP_STATUS_COLORS = { draft: "", active: "badge-ok", closed: "badge-issue" };

function renderGroups() {
  const box = $("view-groups");
  if (!box) return;
  const rows = (state.groups || []).map(g => `
    <tr>
      <td>${esc(g.name)}</td>
      <td>${esc(g.syllabus || "—")}</td>
      <td>${g.member_count ?? 0} / ${g.max_students}</td>
      <td><span class="badge ${GROUP_STATUS_COLORS[g.status] || ""}">${GROUP_STATUS_LABELS[g.status] || g.status}</span></td>
      <td style="white-space:nowrap">
        ${g.status !== "active"
          ? `<button class="btn btn-xs" onclick="setGroupStatus(${g.id},'active')">Publish</button> ` : ""}
        ${g.status === "active"
          ? `<button class="btn btn-xs" onclick="setGroupStatus(${g.id},'closed')">Close</button> ` : ""}
        ${g.status !== "draft"
          ? `<button class="btn btn-xs" onclick="setGroupStatus(${g.id},'draft')">Draft</button>` : ""}
      </td>
    </tr>`).join("");

  box.innerHTML = panel("Groups", `<div class="panel-body">
    ${rows ? `<table class="data-table"><thead><tr>
      <th>Name</th><th>Syllabus</th><th>Members</th><th>Status</th><th>Actions</th>
    </tr></thead><tbody>${rows}</tbody></table>`
    : empty("👥", "No groups yet.", "Teachers create groups from their dashboard.")}
  </div>`);
}

async function setGroupStatus(groupId, status) {
  try {
    await api(`/api/admin/groups/${groupId}/status`, { method: "PATCH", body: { status } });
    toast(`Group ${status}`);
    const g = state.groups.find(x => x.id === groupId);
    if (g) g.status = status;
    renderGroups();
    setCount("groups", (state.groups || []).length);
  } catch (ex) { toast(ex.message, true); }
}

/* ---- Payments ------------------------------------------------------------- */

const PROOF_PLAN_LABELS = { free: "Free", solo: "1-on-1", three: "Group of 3", all: "All Access" };
const PROOF_STATUS_COLORS = { pending: "badge-lav", approved: "badge-ok", rejected: "badge-issue" };

function renderPayments() {
  const box = $("view-payments");
  if (!box) return;
  const proofs = state.payments || [];
  const rows = proofs.map(p => `
    <tr>
      <td>${esc(p.name || p.email || "—")}</td>
      <td>${esc(PROOF_PLAN_LABELS[p.plan] || p.plan)}</td>
      <td>${p.amount_pkr ? `PKR ${p.amount_pkr.toLocaleString()}` : "—"}</td>
      <td>${esc(p.method || "—")}</td>
      <td>${esc(p.transaction_id || "—")}</td>
      <td>${p.screenshot_url
        ? `<a href="${esc(p.screenshot_url)}" target="_blank" rel="noopener">View</a>` : "—"}</td>
      <td><span class="badge ${PROOF_STATUS_COLORS[p.status] || ""}">${esc(p.status)}</span></td>
      <td style="white-space:nowrap">${p.status === "pending" ? `
        <button class="btn btn-xs" onclick="reviewProof(${p.id},'approved')">✓ Approve</button>
        <button class="btn btn-xs btn-danger" onclick="reviewProof(${p.id},'rejected')">✗ Reject</button>
      ` : "—"}</td>
    </tr>`).join("");

  box.innerHTML = panel("Payment Proofs",
    `<p style="font-size:13px;color:var(--muted);margin-bottom:12px">
      Approving a proof instantly upgrades the student's plan.
    </p>
    <div class="panel-body">
    ${rows ? `<div style="overflow-x:auto"><table class="data-table"><thead><tr>
      <th>Student</th><th>Plan</th><th>Amount</th><th>Method</th>
      <th>Txn ID</th><th>Screenshot</th><th>Status</th><th>Action</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`
    : empty("💳", "No payment proofs yet.", "Students submit proofs from the pricing page.")}
    </div>`);
}

async function reviewProof(proofId, status) {
  if (!confirm(`${status === "approved" ? "Approve" : "Reject"} this payment?`)) return;
  try {
    await api(`/api/admin/payment-proofs/${proofId}/review`, {
      method: "POST", body: { status },
    });
    toast(status === "approved" ? "Plan upgraded ✓" : "Proof rejected");
    const p = state.payments.find(x => x.id === proofId);
    if (p) p.status = status;
    renderPayments();
    setCount("payments", (state.payments || []).filter(x => x.status === "pending").length);
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
  if (e.key !== "Escape") return;
  if (_beEl) { closeBlogEditor(false); return; }
  if (!$("drawer-backdrop").hidden) closeDrawer();
});

/* ---- Homework -------------------------------------------------------------
 *
 * One page answering "who is waiting on me?". The student list is ordered by
 * that question — anything handed in and still open first, then overdue, then
 * merely open — and picking a student shows their work with every file they
 * have submitted, downloadable in one click.
 */

async function loadHomework(force = false) {
  const box = $("view-homework");
  if (state.homework && !force) { renderHomeworkPage(); return; }
  box.innerHTML = panel("Homework", `<div class="panel-body">${
    empty("⏳", "Loading homework…")}</div>`);
  try {
    state.homework = await api("/api/admin/homework");
    setCount("homework", state.homework.totals.awaiting_review);
    renderHomeworkPage();
  } catch (ex) {
    box.innerHTML = panel("Homework", `<div class="panel-body">${
      empty("⚠️", "Couldn't load homework.", ex.message)}</div>`);
  }
}

function hwStudents() {
  const all = state.homework?.students || [];
  if (state.hwFilter === "awaiting") return all.filter(s => s.awaiting_review > 0);
  if (state.hwFilter === "overdue") return all.filter(s => s.overdue > 0);
  return all;
}

function renderHomeworkPage() {
  const data = state.homework;
  const box = $("view-homework");
  if (!data) return;
  const t = data.totals;
  const list = hwStudents();

  // Keep the selection if it survives the filter, else take the top student —
  // the detail pane should never sit empty while the list has rows.
  if (!list.some(s => s.user_id === state.hwStudent)) {
    state.hwStudent = list[0]?.user_id || null;
  }

  const stat = (n, label, cls = "") =>
    `<div class="hw-stat ${cls}"><b>${n}</b><span>${esc(label)}</span></div>`;
  const filterBtn = (key, label, n) =>
    `<button class="hw-fbtn${state.hwFilter === key ? " on" : ""}" data-hwfilter="${key}">
       ${esc(label)}<i>${n}</i></button>`;

  box.innerHTML = `
    <div class="hw-stats">
      ${stat(t.students, "students with work")}
      ${stat(t.open, "open")}
      ${stat(t.overdue, "overdue", t.overdue ? "is-late" : "")}
      ${stat(t.awaiting_review, "handed in", t.awaiting_review ? "is-wait" : "")}
      ${stat(t.submissions, "files submitted")}
    </div>
    <div class="hw-page">
      <aside class="hw-side">
        <div class="hw-filters">
          ${filterBtn("all", "All", data.students.length)}
          ${filterBtn("awaiting", "Handed in", t.awaiting_review)}
          ${filterBtn("overdue", "Overdue", t.overdue)}
        </div>
        <input type="search" class="hw-search" id="hw-search" placeholder="Search students…">
        <div class="hw-students" id="hw-students"></div>
      </aside>
      <div class="hw-detail" id="hw-detail"></div>
    </div>`;

  box.querySelectorAll("[data-hwfilter]").forEach(b => b.onclick = () => {
    state.hwFilter = b.dataset.hwfilter;
    renderHomeworkPage();
  });
  $("hw-search").oninput = e => renderHwStudentList(e.target.value);

  renderHwStudentList("");
  renderHwDetail();
}

function renderHwStudentList(query) {
  const q = (query || "").trim().toLowerCase();
  const list = hwStudents().filter(s =>
    !q || s.name.toLowerCase().includes(q) || (s.email || "").toLowerCase().includes(q));
  const box = $("hw-students");
  if (!list.length) {
    box.innerHTML = `<p class="hw-side-empty">No students match.</p>`;
    return;
  }
  box.innerHTML = list.map(s => `
    <button class="hw-srow${s.user_id === state.hwStudent ? " on" : ""}"
            data-hwstudent="${esc(s.user_id)}">
      <span class="hw-savatar">${s.picture_url
        ? `<img src="${esc(s.picture_url)}" alt="">`
        : esc((s.name || "?").trim()[0].toUpperCase())}</span>
      <span class="hw-sinfo">
        <b>${esc(s.name)}</b>
        <em>${s.open} open · ${s.total} set</em>
      </span>
      <span class="hw-stags">
        ${s.awaiting_review ? `<i class="hw-tag wait" title="Handed in, not marked done">${s.awaiting_review}</i>` : ""}
        ${s.overdue ? `<i class="hw-tag late" title="Overdue">${s.overdue}</i>` : ""}
      </span>
    </button>`).join("");
  box.querySelectorAll("[data-hwstudent]").forEach(b => b.onclick = () => {
    state.hwStudent = b.dataset.hwstudent;
    box.querySelectorAll(".hw-srow").forEach(r => r.classList.toggle("on", r === b));
    renderHwDetail();
  });
}

function renderHwDetail() {
  const box = $("hw-detail");
  const s = (state.homework?.students || []).find(x => x.user_id === state.hwStudent);
  if (!s) {
    box.innerHTML = empty("📒", "No homework set yet.",
      "Assign work from a student's page and it shows up here.");
    return;
  }
  const open = s.assignments.filter(a => a.status !== "done");
  const done = s.assignments.filter(a => a.status === "done");

  box.innerHTML = `
    <div class="hw-dhead">
      <div>
        <h3>${esc(s.name)}</h3>
        <p>${esc(s.email || "")}</p>
      </div>
      <button class="btn btn-ghost" data-hwopen="${esc(s.user_id)}">Open full student log →</button>
    </div>
    ${open.length ? `<h4 class="hw-dsub">Open (${open.length})</h4>
      <div class="hw-dlist">${open.map(hwDetailCard).join("")}</div>` : ""}
    ${done.length ? `<h4 class="hw-dsub">Completed (${done.length})</h4>
      <div class="hw-dlist">${done.map(hwDetailCard).join("")}</div>` : ""}
    ${!s.assignments.length ? empty("📗", "Nothing set for this student yet.") : ""}`;

  box.querySelector("[data-hwopen]")?.addEventListener("click", () => {
    go("student");
    openStudent(s.user_id);
  });
}

function hwDetailCard(a) {
  const today = new Date().toISOString().slice(0, 10);
  const late = a.status !== "done" && a.due_date && a.due_date < today;
  const subs = a.submissions || [];
  const isTest = (a.kind || "") === "test";
  return `
    <div class="hw-dcard${a.status === "done" ? " is-done" : ""}${late ? " is-late" : ""}">
      <div class="hw-dtop">
        <span class="badge badge-kind${isTest ? " badge-test" : ""}">${esc(a.kind || "homework")}</span>
        ${a.subject_name ? `<span class="badge badge-lav">${esc(a.subject_name)}</span>` : ""}
        ${a.due_date ? `<span class="hw-ddue${late ? " late" : ""}">
          ${isTest ? "On" : "Due"} ${esc(a.due_date)}</span>` : ""}
        <span class="sp"></span>
        ${a.status === "done" ? `<span class="badge badge-ok">done</span>`
          : subs.length ? `<span class="badge badge-pending">handed in</span>`
          : a.seen_at ? `<span class="badge badge-pending">seen</span>`
                      : `<span class="badge badge-issue">unread</span>`}
      </div>
      <h5>${esc(a.title)}</h5>
      ${a.instructions ? `<p class="hw-dinstr">${esc(a.instructions)}</p>` : ""}

      ${a.attachments?.length ? `
        <div class="hw-dfiles">
          <p class="hw-dfiles-lbl">You attached</p>
          ${a.attachments.map(t => `<span class="hw-dfile">
            ${t.type === "upload" ? "📎" : t.type === "resource" ? "📄" : "📚"}
            ${esc(t.name || t.rel || "attachment")}</span>`).join("")}
        </div>` : ""}

      ${subs.length ? `
        <div class="hw-dfiles hw-dsubs">
          <p class="hw-dfiles-lbl">Student submitted (${subs.length})</p>
          ${subs.map(sub => `
            <a class="hw-dsub-file" target="_blank" rel="noopener"
               href="/api/admin/assignments/${a.id}/submission/${sub.idx}">
              <span class="hw-dsub-ic">📥</span>
              <span><b>${esc(sub.name || "Submission")}</b>
                <em>${sub.submitted_at ? "Handed in " + esc(String(sub.submitted_at).slice(0, 10)) : "Download"}${
                  sub.size ? " · " + fmtSize(sub.size) : ""}</em></span>
            </a>`).join("")}
        </div>`
      : `<p class="hw-dnone">Nothing handed in yet.</p>`}

      ${a.student_note ? `<p class="hw-dnote"><strong>Student note:</strong> ${esc(a.student_note)}</p>` : ""}
    </div>`;
}

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/* ---- Allocations ---------------------------------------------------------- */

const SUBJECT_LABELS_ALLOC = {
  "4024":"Maths OL","0580":"Maths IGCSE","5054":"Physics OL","0625":"Physics IGCSE",
  "2210":"CS OL","0478":"CS IGCSE","9702":"Physics AL","9709":"Maths AL","9618":"CS AL",
  "5070":"Chemistry OL","0620":"Chemistry IGCSE",
};

function renderAllocations() {
  const box = $("view-allocations");
  if (!box) return;
  const allocs = state.allocations || [];
  // Use teacher-role profiles (have valid profiles.id) not the marketing teachers table
  const teacherProfiles = state.teacherProfiles || [];
  const students = state.students || [];
  const teacherOpts = teacherProfiles.map(t =>
    `<option value="${esc(t.id)}">${esc(t.name || t.email)}</option>`).join("");
  const studentOpts = students.map(s =>
    `<option value="${esc(s.id)}">${esc(s.name)} (${esc(s.email)})</option>`).join("");
  const sylOpts = Object.entries(SUBJECT_LABELS_ALLOC).map(([k,v]) =>
    `<option value="${k}">${v} (${k})</option>`).join("");
  const rows = allocs.map(a => `<tr>
    <td>${esc(a.teacher_name || a.teacher_id)}</td>
    <td>${esc(a.student_name || a.student_id)}<br><small>${esc(a.student_email||"")}</small></td>
    <td>${esc(SUBJECT_LABELS_ALLOC[a.syllabus] || a.syllabus)}</td>
    <td>${esc(a.status || "active")}</td>
    <td><button class="btn btn-xs btn-danger" onclick="removeAllocation(${a.id})">Remove</button></td>
  </tr>`).join("");

  box.innerHTML = panel("Teacher ↔ Student Allocations",
    `<p style="font-size:13px;color:var(--muted);margin-bottom:12px">
      Admin assigns a teacher to a student per syllabus. Students become "tutored" once linked.
    </p>
    <div class="panel-body">
    <form id="alloc-form" style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:16px">
      <div style="flex:1;min-width:160px">
        <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:3px">Teacher</label>
        <select id="alloc-teacher" style="width:100%">${teacherOpts || "<option>No teachers yet</option>"}</select>
      </div>
      <div style="flex:1;min-width:160px">
        <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:3px">Student</label>
        <select id="alloc-student" style="width:100%">${studentOpts || "<option>No students yet</option>"}</select>
      </div>
      <div style="flex:1;min-width:130px">
        <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:3px">Syllabus</label>
        <select id="alloc-syllabus" style="width:100%">${sylOpts}</select>
      </div>
      <button type="submit" class="btn btn-gold" style="white-space:nowrap">+ Assign</button>
    </form>
    ${rows ? `<div style="overflow-x:auto"><table class="data-table"><thead><tr>
      <th>Teacher</th><th>Student</th><th>Subject</th><th>Status</th><th>Action</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`
    : empty("🔗", "No allocations yet.", "Use the form above to assign a teacher to a student.")}
    </div>`);

  document.getElementById("alloc-form")?.addEventListener("submit", async e => {
    e.preventDefault();
    const tid = document.getElementById("alloc-teacher").value;
    const sid = document.getElementById("alloc-student").value;
    const syl = document.getElementById("alloc-syllabus").value;
    if (!tid || !sid) return toast("Select both teacher and student", true);
    try {
      await api("/api/admin/allocations", { method: "POST",
        body: { teacher_id: tid, student_id: sid, syllabus: syl }});
      toast("Allocated ✓");
      const res = await api("/api/admin/allocations");
      state.allocations = res.allocations || [];
      renderAllocations();
      setCount("allocations", state.allocations.length);
    } catch (ex) { toast(ex.message, true); }
  });
}

async function removeAllocation(id) {
  if (!confirm("Remove this allocation?")) return;
  try {
    await api(`/api/admin/allocations/${id}`, { method: "DELETE" });
    state.allocations = state.allocations.filter(a => a.id !== id);
    renderAllocations();
    setCount("allocations", state.allocations.length);
    toast("Removed");
  } catch (ex) { toast(ex.message, true); }
}

/* ---- Contacts ------------------------------------------------------------- */

function renderContacts() {
  const box = $("view-contacts");
  if (!box) return;
  const items = state.contacts || [];
  const rows = items.map(c => `<tr>
    <td>${esc(c.name || "—")}</td>
    <td><a href="mailto:${esc(c.email)}">${esc(c.email)}</a></td>
    <td>${esc(c.subject || "—")}</td>
    <td style="max-width:300px;white-space:pre-wrap">${esc(c.message)}</td>
    <td style="white-space:nowrap">${esc((c.created_at || "").slice(0,10))}</td>
  </tr>`).join("");
  box.innerHTML = panel("Contact Submissions",
    `<div class="panel-body">${rows
      ? `<div style="overflow-x:auto"><table class="data-table"><thead><tr>
           <th>Name</th><th>Email</th><th>Subject</th><th>Message</th><th>Date</th>
         </tr></thead><tbody>${rows}</tbody></table></div>`
      : empty("✉️", "No contact messages yet.", "Messages from the contact form appear here.")
    }</div>`);
}

/* ---- Newsletter ----------------------------------------------------------- */

function renderNewsletter() {
  const box = $("view-newsletter");
  if (!box) return;
  const subs = state.newsletter || [];
  const csvData = ["Email,Subscribed"].concat(
    subs.map(s => `${s.email},${(s.subscribed_at||"").slice(0,10)}`)).join("\n");

  const rows = subs.map(s => `<tr>
    <td>${esc(s.email)}</td>
    <td>${esc((s.subscribed_at || "").slice(0,10))}</td>
  </tr>`).join("");

  box.innerHTML = panel("Newsletter Subscribers",
    `<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
      <span style="font-size:13px;color:var(--muted)">${subs.length} subscriber${subs.length !== 1 ? "s" : ""} total</span>
      <button class="btn btn-xs" id="nl-broadcast-btn" style="margin-left:auto">📢 Broadcast email</button>
      ${subs.length ? `<button class="btn btn-xs btn-ghost" id="nl-csv-btn">⬇ Export CSV</button>` : ""}
    </div>
    <div id="nl-compose" style="display:none;background:var(--bg-muted,#f8f7ff);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px">
      <p style="font-size:12px;font-weight:700;color:var(--muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:.07em">Compose broadcast</p>
      <input id="nl-subj" type="text" placeholder="Subject line…" style="width:100%;padding:7px 10px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--text);font-size:13px;margin-bottom:8px">
      <textarea id="nl-body" rows="5" placeholder="Email body (plain text)…"
                style="width:100%;padding:7px 10px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--text);font-size:13px;resize:vertical;margin-bottom:8px"></textarea>
      <div style="display:flex;gap:8px">
        <button class="btn btn-xs" id="nl-send-btn">Send to ${subs.length} subscriber${subs.length !== 1?"s":""}</button>
        <button class="btn btn-xs btn-ghost" id="nl-cancel-btn">Cancel</button>
      </div>
      <p id="nl-send-status" style="font-size:12px;margin-top:8px;color:var(--muted)"></p>
    </div>
    <div class="panel-body">${rows
      ? `<div style="overflow-x:auto"><table class="data-table"><thead><tr>
           <th>Email</th><th>Subscribed</th>
         </tr></thead><tbody>${rows}</tbody></table></div>`
      : empty("📬", "No subscribers yet.", "Newsletter signups from the homepage footer appear here.")
    }</div>`,
    "", "newsletter-panel");

  $("nl-broadcast-btn")?.addEventListener("click", () => {
    const comp = $("nl-compose");
    if (comp) comp.style.display = comp.style.display === "none" ? "block" : "none";
  });
  $("nl-cancel-btn")?.addEventListener("click", () => { if ($("nl-compose")) $("nl-compose").style.display = "none"; });
  $("nl-csv-btn")?.addEventListener("click", () => {
    const blob = new Blob([csvData], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `newsletter_subscribers_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
  $("nl-send-btn")?.addEventListener("click", async () => {
    const subj = $("nl-subj")?.value.trim();
    const body = $("nl-body")?.value.trim();
    const status = $("nl-send-status");
    if (!subj || !body) { if (status) status.textContent = "Subject and body are required."; return; }
    const btn = $("nl-send-btn");
    btn.disabled = true; btn.textContent = "Sending…";
    if (status) status.textContent = "";
    try {
      const res = await api("/api/admin/newsletter/broadcast", {
        method: "POST",
        body: { subject: subj, body },
      });
      if (status) status.textContent = `✓ Sent to ${res.sent || subs.length} subscribers.`;
      $("nl-subj").value = ""; $("nl-body").value = "";
    } catch (ex) {
      if (status) status.textContent = `Error: ${ex.message}`;
    } finally {
      btn.disabled = false; btn.textContent = `Send to ${subs.length} subscriber${subs.length!==1?"s":""}`;
    }
  });
}

/* ---- Boot ---------------------------------------------------------------- */

// The student console gets this page's helpers rather than importing its own,
// so there is one API client, one toast and one drawer in the document.
StudentConsole.init({
  api, upload, uploadWithProgress, esc, panel, table, empty, toast,
  openDrawer, closeDrawer,
  subjectName: code => SUBJECT_LABELS[code] || code,
});

(function initTheme() {
  const toggleBtn = $("theme-toggle");
  if (!toggleBtn) return;
  const updateBtn = () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    toggleBtn.innerHTML = isDark ? "☀️ Light Mode" : "🌙 Night Mode";
  };
  updateBtn();
  toggleBtn.addEventListener("click", () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
    updateBtn();
  });
})();

(async function boot() {
  // A ?key= in the URL is honoured once, then scrubbed from history so the
  // secret does not sit in the address bar or get bookmarked.
  const urlKey = new URLSearchParams(location.search).get("key");
  if (urlKey) {
    adminKey = urlKey;
    history.replaceState({}, "", location.pathname);
  }

  // JWT session check: if user is logged in as admin, skip the key gate
  if (!adminKey) {
    try {
      setLoaderStatus("Checking your session…");
      const me = await fetch("/auth/me", { credentials: "same-origin" });
      if (me.ok) {
        const u = await me.json();
        if (u && u.role === "admin") {
          // Session cookie will authenticate all API calls (same-origin)
          adminKey = "";
          $("gate").hidden = true;
          $("app").hidden = false;
          await loadAll();
          return;
        }
        if (u) {
          // Logged in but not admin — redirect to their own dashboard
          const dash = u.role === "teacher" ? "/teacher-dashboard.html"
                     : u.role === "parent"  ? "/parent-dashboard.html"
                     : "/dashboard.html";
          location.replace(dash);
          return;
        }
      }
    } catch {}
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
