/* Student dashboard — progress rings, recent practice, enrolment. */

import { requireProfile, api, teeLoader, UpgradeRequiredError } from "/auth.js";
import { showUpgradeModal, setPlan, setRole, initUsageMeter } from "/upgrade-modal.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TINTS = ["lav", "green", "blue", "pink", "orange", "teal"];

/* The profile stores the qualification the student is sitting ("IGCSE");
   /api/meta labels each subject with its board ("Cambridge IGCSE"). This is
   the only bridge between the two, so keep the keys in step with the radio
   values in profile.html and with BOARDS in app.py. */
const BOARD_OF_GRADE = {
  "O Level": "Cambridge O Level",
  "IGCSE": "Cambridge IGCSE",
  "A Level": "Cambridge A Level",
};

let meta = null;
let dash = null;
let board = null;          // the student's board, or null if we can't map it

/* Kick the data fetches off immediately, in parallel with the auth check.
   Both endpoints require the session cookie and 401 on their own, so there is
   nothing to gain by waiting for /auth/me first — and waiting cost a full
   round-trip (~0.6 s to Supabase's region) before the page even started
   loading. The rejection is swallowed here and re-read inside init(). */
const dataPromise = Promise.all([api("/api/dashboard"), api("/api/meta")]);
dataPromise.catch(() => {});

const user = await requireProfile();
if (user) init();

async function init() {
  board = BOARD_OF_GRADE[user.grade] || null;
  // Set active plan + role so modal knows current tier (teachers/admins skip all walls)
  setRole(user.role);
  const isPrivileged = user.role === "teacher" || user.role === "admin";
  setPlan(isPrivileged ? "all" : (user.plan || "free"));
  // Init usage meter — show the section only when there are quota-limited bars
  initUsageMeter("#dash-usage-meter").then(() => {
    const meter = document.getElementById("dash-usage-meter");
    if (meter && meter.children.length > 0) {
      const sec = document.getElementById("dash-usage-section");
      if (sec) sec.style.display = "";
    }
  });
  greet(user);
  try {
    [dash, meta] = await dataPromise;
  } catch (err) {
    document.getElementById("ring-row").innerHTML =
      `<p class="dash-loading">Couldn't load your dashboard: ${esc(err.message)}</p>`;
    return;
  }
  renderStreak();
  renderRings();
  renderHomework();
  renderQuizzes();
  renderEnrol();
  renderBoardSwitch();
  renderSetupBanner();
  // If coming from profile setup without subjects, scroll straight to the enrol section
  if (new URLSearchParams(location.search).has("needs-subjects")) {
    history.replaceState({}, "", location.pathname); // clean the URL
    setTimeout(() => {
      document.getElementById("enrol-grid")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 400);
  }
  showWelcomeModal();
  renderTests();
  renderMessages();
  renderArchived();
  renderClasses();
}

/* ---- First-login welcome modal ------------------------------------------- */

function showWelcomeModal() {
  const overlay = document.getElementById("welcome-overlay");
  if (!overlay) return;

  // Only show if profile is genuinely incomplete
  const hasGrade = !!user.grade;
  const hasPhone = !!user.phone;
  const hasEnrollments = (dash?.enrollments?.length ?? 0) > 0;
  if (hasGrade && hasPhone && hasEnrollments) return;

  // Gate: once seen, don't nag again this browser session
  const storageKey = "pwt_welcomed_" + (user.id || "");
  try { if (localStorage.getItem(storageKey)) return; } catch {}

  // Personalise greeting
  const nameEl = document.getElementById("wm-name");
  if (nameEl && user.name) nameEl.textContent = `Welcome, ${user.name.split(" ")[0]}! 👋`;

  overlay.style.display = "flex";
  try { localStorage.setItem(storageKey, "1"); } catch {}

  document.getElementById("wm-skip")?.addEventListener("click", () => {
    overlay.style.display = "none";
  });
  // Close on backdrop click
  overlay.addEventListener("click", e => {
    if (e.target === overlay) overlay.style.display = "none";
  });
}


/* ---- Setup onboarding banner --------------------------------------------- */

function renderSetupBanner() {
  const el = document.getElementById("setup-banner");
  if (!el) return;

  const hasGrade = !!user.grade;
  const hasPhone = !!user.phone;
  const hasEnrollments = (dash?.enrollments?.length ?? 0) > 0;

  if (hasGrade && hasPhone && hasEnrollments) {
    el.hidden = true;
    return;
  }

  // Dismiss key: once per session
  const sessionKey = "pwt_setup_dismissed_" + (user.id || "");
  if (sessionStorage.getItem(sessionKey)) { el.hidden = true; return; }

  el.hidden = false;

  const done = (num, title) => `
    <div style="display:flex;gap:12px;align-items:center;padding:10px 0;
                ${num < 4 ? "border-bottom:1px solid var(--line);" : ""}opacity:.55;">
      <div style="flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
                  font:800 .75rem/1 'Archivo',sans-serif;background:var(--green-ink,#16a34a);color:#fff;">✓</div>
      <strong style="font-size:.88rem;color:var(--ink);text-decoration:line-through;">${title}</strong>
    </div>`;

  const todo = (num, title, desc, cta, href, isScroll) => `
    <div style="display:flex;gap:12px;align-items:flex-start;padding:12px 0;
                ${num < 4 ? "border-bottom:1px solid var(--line);" : ""}">
      <div style="flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
                  font:800 .75rem/1 'Archivo',sans-serif;background:var(--gold,#d4a017);color:#fff;">${num}</div>
      <div style="flex:1;min-width:0;">
        <strong style="display:block;font-size:.88rem;color:var(--ink);">${title}</strong>
        <span style="font-size:.78rem;color:var(--grey);line-height:1.5;">${desc}</span>
      </div>
      <a href="${href}" data-scroll="${isScroll ? "1" : ""}"
         style="flex:none;font-size:.78rem;font-weight:700;padding:6px 12px;border-radius:8px;
                text-decoration:none;background:var(--gold,#d4a017);color:#fff;white-space:nowrap;">${cta}</a>
    </div>`;

  // Count pending steps for the subtitle
  const pending = [!hasGrade || !hasPhone, !hasEnrollments].filter(Boolean).length;

  el.innerHTML = `
    <div style="background:var(--page);border:1.5px solid var(--gold);border-radius:var(--radius-lg);
                padding:18px 20px;margin-bottom:16px;position:relative;">
      <button type="button" aria-label="Dismiss"
              style="position:absolute;top:10px;right:12px;background:none;border:none;
                     cursor:pointer;font-size:1.1rem;color:var(--grey);line-height:1;"
              id="setup-banner-dismiss">&times;</button>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
        <span style="font-size:1.4rem;">🦉</span>
        <div>
          <strong style="font-size:.95rem;color:var(--ink);">Complete your setup — ${pending} step${pending !== 1 ? "s" : ""} left</strong>
          <p style="margin:0;font-size:.78rem;color:var(--grey);">Finish these and your dashboard will be fully personalised.</p>
        </div>
      </div>
      ${done(1, "Create your account")}
      ${(!hasGrade || !hasPhone)
        ? todo(2, "Fill in your profile",
            "Set your qualification (O Level / IGCSE / A Level), WhatsApp number and personal details.",
            "Go to profile →", "/profile.html?setup=1&next=/dashboard.html", false)
        : done(2, "Profile complete")}
      ${!hasEnrollments
        ? todo(3, "Add your subjects",
            "Enrol in the subjects you study — topical papers, AI tutor and progress tracking unlock per subject.",
            "Enrol now ↓", "#enrol-grid", true)
        : done(3, "Subjects added")}
    </div>`;

  document.getElementById("setup-banner-dismiss")?.addEventListener("click", () => {
    sessionStorage.setItem(sessionKey, "1");
    el.hidden = true;
  });

  el.querySelectorAll("a[data-scroll='1']").forEach(a => {
    a.addEventListener("click", e => {
      e.preventDefault();
      document.getElementById("enrol-grid")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

/* ---- Scheduled tests ------------------------------------------------------
 *
 * Fetched separately and rendered last so a slow or failed call can never hold
 * up the rest of the dashboard — a missing test card is a far smaller problem
 * than a page that will not load.
 */
async function renderTests() {
  const box = document.getElementById("dash-tests");
  if (!box) return;
  let tests = [];
  try {
    ({ upcoming_tests: tests = [] } = await api("/api/notifications"));
  } catch { return; }
  if (!tests.length) return;

  box.hidden = false;
  box.innerHTML = tests.slice(0, 3).map(t => {
    const d = t.days_left;
    const when = d === null ? "Date to be confirmed"
      : d < 0 ? "Was scheduled for " + esc(t.due_date)
      : d === 0 ? "Today"
      : d === 1 ? "Tomorrow"
      : `In ${d} days`;
    // Only the genuinely imminent ones shout; a test three weeks out should
    // inform, not alarm.
    const tone = d !== null && d <= 2 ? " is-soon" : "";
    return `
      <div class="test-banner${tone}">
        <span class="test-banner-ico" aria-hidden="true">📝</span>
        <div class="test-banner-body">
          <p class="test-banner-eyebrow">Test scheduled${
            t.subject_name ? " · " + esc(t.subject_name) : ""}</p>
          <strong>${esc(t.title)}</strong>
          ${t.instructions ? `<p class="test-banner-note">${esc(t.instructions)}</p>` : ""}
        </div>
        <div class="test-banner-when">
          <b>${esc(when)}</b>
          ${t.due_date ? `<span>${esc(t.due_date)}</span>` : ""}
        </div>
        <a class="btn btn-dark test-banner-cta" href="homework.html">Details</a>
      </div>`;
  }).join("");
}

/* ---- Homework reminder --------------------------------------------------- */

function renderHomework() {
  const hw = dash.homework || { open: 0, overdue: 0, due_soon: 0, items: [] };

  /* Banner shows for ANY outstanding homework, not just late work — a student
     who only ever sees it once it is overdue has already been let down by it.
     Three tiers so urgency still reads at a glance. */
  const banner = document.getElementById("dash-hw-banner");
  const next = hw.items[0];
  const tier = hw.overdue ? ["late", "⏰",
        `${hw.overdue} piece${hw.overdue === 1 ? "" : "s"} of homework ${hw.overdue === 1 ? "is" : "are"} overdue`,
        "Catch up before your next lesson."]
    : hw.due_soon ? ["soon", "📌",
        `${hw.due_soon} due in the next couple of days`,
        "Get ahead of it now."]
    : hw.open ? ["open", "📝",
        `You have ${hw.open} thing${hw.open === 1 ? "" : "s"} to do`,
        next?.due_date ? `Next up: ${esc(next.title)} — due ${esc(next.due_date)}.`
                       : `Next up: ${esc(next?.title || "")}`]
    : null;

  if (tier) {
    const [cls, icon, head, sub] = tier;
    banner.hidden = false;
    banner.className = `hw-banner hw-banner-${cls}`;
    banner.innerHTML = `
      <span class="hw-banner-icon">${icon}</span>
      <div>
        <strong>${esc(head)}.</strong>
        <p>${sub}</p>
      </div>
      <a class="btn btn-outline" href="homework.html">Open homework</a>`;
  } else {
    banner.hidden = true;
  }

  // Title badge: visible on the browser tab even when the page is in the
  // background, which is where a student usually leaves it.
  if (hw.open) document.title = `(${hw.open}) Dashboard — PrepWithTee`;

  const box = document.getElementById("dash-homework");
  if (!hw.items.length) {
    box.innerHTML = `
      <div class="dash-empty dash-empty-sm">
        <p>Nothing set right now. Anything Tee assigns you — worksheets, notes
        to read, a practice booklet — lands here.</p>
      </div>`;
    return;
  }

  box.innerHTML = `<ul class="hw-mini">${hw.items.map(a => {
    const d = a.days_left;
    const tone = a.overdue ? "late" : (d !== null && d <= 2) ? "soon" : "";
    const when = a.due_date == null ? "no deadline"
      : a.overdue ? `${Math.abs(d)}d overdue`
      : d === 0 ? "due today"
      : d === 1 ? "due tomorrow"
      : `due in ${d}d`;
    return `
      <li class="hw-mini-item ${tone}">
        <a href="homework.html">
          <strong>${esc(a.title)}</strong>
          <em>${esc(a.subject_name || "")}${a.subject_name ? " · " : ""}${esc(when)}</em>
        </a>
      </li>`;
  }).join("")}</ul>
  <a class="btn btn-outline dash-hw-all" href="homework.html">
    ${hw.open} open ${hw.open === 1 ? "task" : "tasks"} &rarr;</a>`;
}

/** Subjects the student can see: their own board, plus anything they are
 *  already enrolled in — otherwise a subject kept from a previous board
 *  would be impossible to un-enrol from. */
function visibleSubjects(enrolled) {
  if (!board) return meta.subjects;
  return meta.subjects.filter(s => s.board === board || enrolled.has(s.syllabus));
}

function greet(u) {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const first = (u.name || "").split(" ")[0] || "there";
  document.getElementById("dash-hello").textContent = `${part}, ${first}`;
  document.getElementById("dash-date").textContent =
    new Date().toLocaleDateString(undefined,
      { weekday: "long", day: "numeric", month: "long" });

  const pill = document.getElementById("dash-board");
  if (u.grade) {
    pill.textContent = board || u.grade;
    pill.hidden = false;
    document.getElementById("dash-sub").textContent =
      `Everything below is filtered to your ${u.grade} syllabuses.`;
  }
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
        <p><strong>No subjects yet.</strong> Add one below${board
          ? ` — you'll only see ${esc(board)} subjects` : ""} and your progress,
        papers and practice all unlock straight away.</p>
      </div>`;
    return;
  }

  box.innerHTML = dash.enrollments.map((e, i) => {
    const subject = meta.subjects.find(s => s.syllabus === e.syllabus);
    const chapters = subject?.topics.length || 0;
    const sum = dash.progress_summary[e.syllabus];
    /* Confident CHAPTERS over the chapters in the syllabus — the identical
       definition progress tracker uses. The summary used to include subtopic rows
       in `confident`, so a student who ticked 14 subtopics of one chapter saw
       35% here and 3% on the revise page for the same work. */
    const confident = sum?.confident || 0;
    const learning = sum?.learning || 0;
    const subDone = sum?.sub?.confident || 0;
    const papersDrilled = sum?.papers_confident || 0;
    const pct = chapters ? Math.round((confident / chapters) * 100) : 0;
    const tint = TINTS[i % TINTS.length];

    // Past papers worked through — a second, independent measure of readiness.
    const pap = dash.paper_summary?.[e.syllabus];
    const papersDone = pap?.confident || 0;
    const papersStarted = pap?.learning || 0;

    return `
      <a class="ring-card" href="topical-progress.html?syllabus=${encodeURIComponent(e.syllabus)}">
        <div class="ring-wrap">${ring(pct, tint)}</div>
        <div class="ring-meta">
          <h3>${esc(subject?.short || e.name)}</h3>
          <p class="ring-board">${esc(subject?.board || e.syllabus)}</p>
          <p class="ring-stats">
            <span class="dot-confident">${confident} confident</span>
            <span class="dot-learning">${learning} learning</span>
            <span class="dot-none">${Math.max(0, chapters - confident - learning)} to go</span>
          </p>
          <p class="ring-total">${confident} of ${chapters} chapter${chapters === 1 ? "" : "s"} confident${
            subDone ? ` · ${subDone} subtopic${subDone === 1 ? "" : "s"} done` : ""}</p>
          ${papersDrilled ? `<p class="ring-drilled">✎ ${papersDrilled} chapter${
            papersDrilled === 1 ? "" : "s"} past-paper drilled</p>` : ""}
          ${papersDone || papersStarted ? `
            <p class="ring-papers">📄 ${papersDone} paper${papersDone === 1 ? "" : "s"} done${
              pap?.avg_score != null ? ` · avg <strong>${pap.avg_score}%</strong> (best ${pap.best_score}%)` : (papersStarted ? ` · ${papersStarted} in progress` : "")}</p>` : ""}
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
        <p>No practice yet. Open a chapter in progress tracker and hit
        <strong>Quiz me</strong> — you'll get an exam-style question marked
        straight back.</p>
        <a class="btn btn-outline" href="topical-progress.html">Start practising</a>
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
  const subjects = visibleSubjects(enrolled);

  const note = document.getElementById("enrol-note");
  if (note) {
    note.textContent = board
      ? `${board} · ${subjects.filter(s => s.board === board).length} subjects live`
      : "Free — unlocks papers, revision and tests";
  }

  if (!subjects.length) {
    box.innerHTML = `
      <div class="dash-empty">
        <p><strong>Nothing live for ${esc(board || "your board")} yet.</strong>
        More syllabuses are being added — or switch board below if that's not
        the qualification you're sitting.</p>
      </div>`;
    return;
  }

  box.innerHTML = subjects.map(s => {
    const on = enrolled.has(s.syllabus);
    const offBoard = board && s.board !== board;
    const questions = s.topics.reduce((n, t) => n + t.count, 0);
    return `
      <div class="enrol-card${on ? " on" : ""}${offBoard ? " off-board" : ""}">
        <div class="enrol-card-body">
          <h3>${esc(s.short)}</h3>
          <p class="enrol-board">${esc(s.board)} · ${esc(s.syllabus)}</p>
          <p class="enrol-count">${questions.toLocaleString()} questions ·
             ${s.topics.length} chapters</p>
          ${offBoard ? `<p class="enrol-flag">Not part of your ${esc(user.grade)}
             — kept because you're enrolled.</p>` : ""}
        </div>
        <button type="button" class="btn ${on ? "btn-outline" : "btn-gold"} enrol-btn"
                data-syllabus="${esc(s.syllabus)}" data-on="${on}" data-subject-name="${esc(s.short)}">
          ${on ? "Enrolled" : "Add subject"}
        </button>
      </div>`;
  }).join("");

  box.querySelectorAll(".enrol-btn").forEach(btn =>
    btn.addEventListener("click", () => toggleEnrol(btn)));
}

/* ---- Board switcher ------------------------------------------------------ */

function renderBoardSwitch() {
  const box = document.getElementById("board-switch");
  if (!box) return;
  box.hidden = false;
  box.querySelector(".board-switch-current").textContent =
    board || user.grade || "not set";
}

async function toggleEnrol(btn) {
  const syllabus = btn.dataset.syllabus;
  const on = btn.dataset.on === "true";

  if (on) {
    const subjectName = btn.dataset.subjectName || btn.dataset.syllabus;
    const confirmed = confirm(`Your progress, notes, and scores for [${subjectName}] will be kept and hidden from your active view. You can reactivate this subject anytime from Settings → Archived Subjects to see it again.`);
    if (!confirmed) return;
  }

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
    renderArchived();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = on ? "Enrolled" : "Add subject";
    alert(err.message);
  }
}

/* ---- Messages card ---------------------------------------------------------
 * Only shown when the student has at least one conversation.
 */
async function renderMessages() {
  const card = document.getElementById("dash-messages-card");
  const inner = document.getElementById("dash-messages-inner");
  try {
    const { conversations: convs = [], unread: totalUnread = 0 } = await api("/api/messages");
    // Badge the quick-action link regardless of conversation history
    const msgLink = document.getElementById("dash-messages-link");
    if (msgLink && totalUnread > 0) {
      const titleEl = msgLink.querySelector(".dash-action-title");
      if (titleEl) titleEl.innerHTML = `💬 Message your tutor <span style="background:#6c3bff;color:#fff;border-radius:99px;font-size:.7rem;font-weight:800;padding:1px 7px;margin-left:4px;vertical-align:middle;">${totalUnread}</span>`;
    }
    if (!card || !inner || !convs.length) return; // hide card if no conversations yet
    card.style.display = "";
    inner.innerHTML = convs.slice(0, 3).map(c => {
      const av = c.partner_pic
        ? `<img src="${esc(c.partner_pic)}" style="width:32px;height:32px;border-radius:50%;object-fit:cover;flex-shrink:0;" alt="">`
        : `<div style="width:32px;height:32px;border-radius:50%;background:var(--navy,#1a2340);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0;">${esc((c.partner_name||'?')[0].toUpperCase())}</div>`;
      const unread = c.unread ? `<span style="background:#6c3bff;color:#fff;border-radius:99px;font-size:11px;font-weight:700;padding:1px 7px;">${c.unread}</span>` : '';
      const preview = (c.last_body||'').length > 50 ? c.last_body.slice(0,50)+'…' : (c.last_body||'No messages yet');
      return `<a href="messages.html" style="display:flex;align-items:center;gap:10px;padding:.65rem 0;border-bottom:1px solid var(--border,#e5e7eb);text-decoration:none;">
        ${av}
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:700;color:var(--navy,#1a2340);">${esc(c.partner_name||'Unknown')}</div>
          <div style="font-size:12px;color:var(--muted,#6b7280);overflow:hidden;white-space:nowrap;text-overflow:ellipsis;">${esc(preview)}</div>
        </div>
        ${unread}
      </a>`;
    }).join('') + `<a href="messages.html" class="btn btn-outline" style="margin-top:.75rem;display:block;text-align:center;">Open inbox${totalUnread ? ` (${totalUnread} unread)` : ''}</a>`;
  } catch { /* silently skip */ }
}


function renderArchived() {
  const section = document.getElementById("dash-archived-section");
  const box = document.getElementById("archived-ring-row");
  if (!section || !box) return;

  const archived = dash.archived_enrollments || [];
  if (!archived.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  box.innerHTML = archived.map((e, i) => {
    const subject = meta.subjects.find(s => s.syllabus === e.syllabus);
    const chapters = subject?.topics.length || 0;
    const sum = dash.progress_summary[e.syllabus];
    const confident = sum?.confident || 0;
    const learning = sum?.learning || 0;
    const subDone = sum?.sub?.confident || 0;
    const pct = chapters ? Math.round((confident / chapters) * 100) : 0;
    const tint = TINTS[i % TINTS.length];

    const pap = dash.paper_summary?.[e.syllabus];
    const papersDone = pap?.confident || 0;
    const papersStarted = pap?.learning || 0;

    return `
      <div class="ring-card archived-card" style="text-decoration:none; cursor:default; pointer-events:auto;">
        <div class="ring-wrap">${ring(pct, tint)}</div>
        <div class="ring-meta">
          <h3>${esc(subject?.short || e.name)}</h3>
          <p class="ring-board">${esc(subject?.board || e.syllabus)}</p>
          <p class="ring-total">${confident} of ${chapters} chapters confident</p>
          ${papersDone || papersStarted ? `
            <p class="ring-papers">📄 ${papersDone} paper${papersDone === 1 ? "" : "s"} done${
              pap?.avg_score != null ? ` · avg <strong>${pap.avg_score}%</strong>` : ""}</p>` : ""}
          <button type="button" class="btn btn-outline reactivate-btn" data-syllabus="${esc(e.syllabus)}" style="margin-top:10px; width:fit-content; font-size:12px; padding:4px 10px;">
            Reactivate
          </button>
        </div>
      </div>`;
  }).join("");

  // Wire reactivate buttons
  box.querySelectorAll(".reactivate-btn").forEach(btn => {
    btn.onclick = async (evt) => {
      evt.preventDefault();
      const syllabus = btn.dataset.syllabus;
      btn.disabled = true;
      btn.textContent = "Reactivating…";
      try {
        await api("/api/enrollments", { method: "POST", body: { syllabus } });
        // Refetch and re-render
        dash = await api("/api/dashboard");
        renderRings();
        renderEnrol();
        renderArchived();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Reactivate";
        alert(err.message);
      }
    };
  });

  // Collapsible toggle wiring
  const toggleBtn = document.getElementById("dash-archived-toggle");
  const content = document.getElementById("dash-archived-content");
  const arrow = document.getElementById("dash-archived-arrow");
  if (toggleBtn && content && arrow) {
    if (!toggleBtn.dataset.wired) {
      toggleBtn.dataset.wired = "true";
      toggleBtn.onclick = (e) => {
        e.preventDefault();
        const collapsed = content.style.display === "none";
        content.style.display = collapsed ? "block" : "none";
        arrow.textContent = collapsed ? "▼" : "▶";
      };
    }
  }
}

/* ---- Recent Classes (teacher-logged) -------------------------------------- */

function renderClasses() {
  const card = document.getElementById("dash-classes-card");
  const inner = document.getElementById("dash-classes-inner");
  if (!card || !inner) return;
  const classes = (dash.classes || []).slice(0, 8);
  if (!classes.length) { card.style.display = "none"; return; }
  card.style.display = "";

  const STATUS_IC = { held: "✅", rescheduled: "🔄", cancelled: "✖", missed: "⚠️" };
  const STATUS_COLOR = { held: "#16a34a", rescheduled: "#ca8a04", cancelled: "#6b7280", missed: "#dc2626" };

  inner.innerHTML = classes.map(c => {
    const status = c.status || "held";
    const ic = STATUS_IC[status] || "📅";
    const color = STATUS_COLOR[status] || "#16a34a";
    const dateStr = c.class_date
      ? new Date(c.class_date).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
      : "—";
    const subject = c.subject_name || c.syllabus || "";
    const dur = c.duration_min ? `${c.duration_min} min` : "";
    return `
      <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
        <span style="font-size:16px;width:20px;text-align:center">${ic}</span>
        <div style="flex:1;min-width:0">
          <div style="font-size:.82rem;font-weight:600;color:var(--text)">${esc(dateStr)}${subject ? ` · ${esc(subject)}` : ""}</div>
          ${c.topic ? `<div style="font-size:.73rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.topic)}</div>` : ""}
        </div>
        ${dur ? `<span style="font-size:.7rem;color:var(--muted);white-space:nowrap">${esc(dur)}</span>` : ""}
        <span style="font-size:.68rem;font-weight:700;color:${color};white-space:nowrap;text-transform:capitalize">${status}</span>
      </div>`;
  }).join("");
}
