/* Student dashboard — progress rings, recent practice, enrolment. */

import { requireProfile, api } from "/auth.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TINTS = ["lav", "green", "blue", "pink", "orange", "teal"];

let meta = null;
let dash = null;

const user = await requireProfile();
if (user) init();

async function init() {
  greet(user);
  try {
    [dash, meta] = await Promise.all([api("/api/dashboard"), api("/api/meta")]);
  } catch (err) {
    document.getElementById("ring-row").innerHTML =
      `<p class="dash-loading">Couldn't load your dashboard: ${esc(err.message)}</p>`;
    return;
  }
  renderStreak();
  renderRings();
  renderQuizzes();
  renderEnrol();
}

function greet(u) {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const first = (u.name || "").split(" ")[0] || "there";
  document.getElementById("dash-hello").textContent = `${part}, ${first}`;
  document.getElementById("dash-date").textContent =
    new Date().toLocaleDateString(undefined,
      { weekday: "long", day: "numeric", month: "long" });
}

function renderStreak() {
  if (!dash.streak) return;
  const box = document.getElementById("dash-streak");
  box.hidden = false;
  box.querySelector(".dash-streak-num").textContent = dash.streak;
  box.querySelector(".dash-streak-label").textContent =
    dash.streak === 1 ? "day streak" : "day streak";
}

/* ---- Progress rings ------------------------------------------------------ */

function ring(pct, tint) {
  const r = 34, c = 2 * Math.PI * r;
  return `
    <svg class="progress-ring" viewBox="0 0 80 80" width="80" height="80" aria-hidden="true">
      <circle class="ring-track" cx="40" cy="40" r="${r}"></circle>
      <circle class="ring-fill ring-${tint}" cx="40" cy="40" r="${r}"
              stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - pct / 100)}"></circle>
    </svg>
    <span class="ring-pct">${pct}<em>%</em></span>`;
}

function renderRings() {
  const box = document.getElementById("ring-row");

  if (!dash.enrollments.length) {
    box.innerHTML = `
      <div class="dash-empty">
        <p><strong>No subjects yet.</strong> Add one below and your progress,
        papers and practice all unlock straight away.</p>
      </div>`;
    return;
  }

  box.innerHTML = dash.enrollments.map((e, i) => {
    const subject = meta.subjects.find(s => s.syllabus === e.syllabus);
    const chapters = subject?.topics.length || 0;
    const sum = dash.progress_summary[e.syllabus];
    // The summary only counts chapters the student has touched; the ring is a
    // share of the whole syllabus, so divide by the syllabus, not by the rows.
    const confident = sum?.confident || 0;
    const learning = sum?.learning || 0;
    const pct = chapters ? Math.round((confident / chapters) * 100) : 0;
    const tint = TINTS[i % TINTS.length];

    return `
      <a class="ring-card" href="revise.html?syllabus=${encodeURIComponent(e.syllabus)}">
        <div class="ring-wrap">${ring(pct, tint)}</div>
        <div class="ring-meta">
          <h3>${esc(subject?.short || e.name)}</h3>
          <p class="ring-board">${esc(subject?.board || e.syllabus)}</p>
          <p class="ring-stats">
            <span class="dot-confident">${confident} confident</span>
            <span class="dot-learning">${learning} learning</span>
          </p>
          <p class="ring-total">${chapters} chapter${chapters === 1 ? "" : "s"} in this syllabus</p>
        </div>
      </a>`;
  }).join("");
}

/* ---- Recent practice ----------------------------------------------------- */

function relative(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (isNaN(then)) return "";
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr${hrs === 1 ? "" : "s"} ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function renderQuizzes() {
  const box = document.getElementById("quiz-history");
  const rows = dash.recent_quizzes || [];

  if (!rows.length) {
    box.innerHTML = `
      <div class="dash-empty dash-empty-sm">
        <p>No practice yet. Open a chapter in revision mode and hit
        <strong>Quiz me</strong> — you'll get an exam-style question marked
        straight back.</p>
        <a class="btn btn-outline" href="revise.html">Start practising</a>
      </div>`;
    return;
  }

  box.innerHTML = `<ul class="quiz-list">${rows.map(q => {
    const subject = meta.subjects.find(s => s.syllabus === q.syllabus);
    const band = q.score == null ? "none" : q.score >= 4 ? "good" : q.score >= 2 ? "mid" : "low";
    return `
      <li class="quiz-item">
        <span class="quiz-item-score quiz-item-${band}">${q.score ?? "—"}</span>
        <span class="quiz-item-meta">
          <strong>${esc(q.topic)}</strong>
          <em>${esc(subject?.short || q.syllabus)} · ${esc(relative(q.created_at))}</em>
        </span>
      </li>`;
  }).join("")}</ul>`;
}

/* ---- Enrolment ----------------------------------------------------------- */

function renderEnrol() {
  const box = document.getElementById("enrol-grid");
  const enrolled = new Set(dash.enrollments.map(e => e.syllabus));

  box.innerHTML = meta.subjects.map(s => {
    const on = enrolled.has(s.syllabus);
    const questions = s.topics.reduce((n, t) => n + t.count, 0);
    return `
      <div class="enrol-card${on ? " on" : ""}">
        <div class="enrol-card-body">
          <h3>${esc(s.short)}</h3>
          <p class="enrol-board">${esc(s.board)} · ${esc(s.syllabus)}</p>
          <p class="enrol-count">${questions.toLocaleString()} questions ·
             ${s.topics.length} chapters</p>
        </div>
        <button type="button" class="btn ${on ? "btn-outline" : "btn-gold"} enrol-btn"
                data-syllabus="${esc(s.syllabus)}" data-on="${on}">
          ${on ? "Enrolled" : "Add subject"}
        </button>
      </div>`;
  }).join("");

  box.querySelectorAll(".enrol-btn").forEach(btn =>
    btn.addEventListener("click", () => toggleEnrol(btn)));
}

async function toggleEnrol(btn) {
  const syllabus = btn.dataset.syllabus;
  const on = btn.dataset.on === "true";
  btn.disabled = true;
  btn.textContent = on ? "Removing…" : "Adding…";

  try {
    if (on) {
      await api(`/api/enrollments/${encodeURIComponent(syllabus)}`, { method: "DELETE" });
    } else {
      await api("/api/enrollments", { method: "POST", body: { syllabus } });
    }
    // Refetch rather than patch — the rings depend on the same data.
    dash = await api("/api/dashboard");
    renderRings();
    renderEnrol();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = on ? "Enrolled" : "Add subject";
    alert(err.message);
  }
}
