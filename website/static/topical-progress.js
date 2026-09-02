/* Topical Progress — syllabus tracker + AI-marked practice.
 *
 * Extracted from revise.js. Handles the chapter-by-chapter view:
 * progress status, past-paper practice per chapter, quiz panel,
 * and the new progress rings summary.
 *
 * Progress is keyed on (syllabus, topic, subtopic). A chapter row writes a row
 * with subtopic = null; each subtopic writes its own. The chapter's own status
 * is what the dashboard rings count, so setting a chapter also clears nothing
 * underneath it — the two levels are tracked independently on purpose.
 */

import { requireProfile } from "/auth.js";
import { lockElement, setPlan, setRole } from "/upgrade-modal.js";
import {
  BOARD_OF_GRADE, STATUSES, PAPER_STEPS,
  api, teeLoader, esc, key,
  subjectFor, mySubjects, renderSubjectStrip, highlightSubjectPill,
  renderProgressRing,
} from "/progress-shared.js";

const state = {
  meta: null,
  enrolled: [],
  board: null,
  syllabus: null,
  progress: new Map(),
  topicPapers: new Map(),
  quiz: null,
};

/* ---- Boot ---------------------------------------------------------------- */

const dataPromise = Promise.all([api("/api/meta"), api("/api/enrollments")]);
dataPromise.catch(() => {});

const deepLink = new URLSearchParams(location.search).get("syllabus");
const progressPrefetch = new Map();
if (deepLink) {
  const p = api(`/api/progress?syllabus=${encodeURIComponent(deepLink)}`);
  p.catch(() => {});
  progressPrefetch.set(deepLink, p);
}

const user = await requireProfile();
if (user) init();

async function init() {
  state.board = BOARD_OF_GRADE[user.grade] || null;
  setRole(user.role);
  const isPrivileged = user.role === "teacher" || user.role === "admin";
  setPlan(isPrivileged ? "all" : (user.plan || "free"));
  try {
    const [meta, enr] = await dataPromise;
    state.meta = meta;
    state.enrolled = enr.enrollments.map(e => e.syllabus);
  } catch (err) {
    document.getElementById("topic-list").innerHTML =
      `<p class="revise-loading">Couldn't load your subjects: ${esc(err.message)}</p>`;
    return;
  }

  renderSubjects();

  const wanted = deepLink;
  const visible = mySubjects(state.meta, state.board, state.enrolled);
  const first = (wanted && visible.some(s => s.syllabus === wanted)) ? wanted
              : state.enrolled[0]
              || visible[0]?.syllabus;
  if (first) selectSubject(first);
  wireQuizPanel();
}

/* ---- Subject pills ------------------------------------------------------- */

function renderSubjects() {
  const box = document.getElementById("revise-subjects");
  const subs = mySubjects(state.meta, state.board, state.enrolled);
  renderSubjectStrip(box, subs, state.enrolled, selectSubject);

  const note = document.getElementById("revise-board-note");
  if (note && state.board) {
    note.querySelector(".revise-board-name").textContent = state.board;
    note.hidden = false;
  }

  // No enrolled subjects yet — show a clear CTA to add them.
  const enrollNote = document.getElementById("revise-enroll-note");
  if (enrollNote) enrollNote.hidden = state.enrolled.length > 0;
}

async function selectSubject(code) {
  state.syllabus = code;
  highlightSubjectPill(code);

  const list = document.getElementById("topic-list");
  list.innerHTML = teeLoader("subjects", 5);

  state.progress = new Map();
  state.topicPapers = new Map();
  try {
    const pending = progressPrefetch.get(code)
      || api(`/api/progress?syllabus=${encodeURIComponent(code)}`);
    progressPrefetch.delete(code);
    const { progress } = await pending;
    for (const row of progress) {
      state.progress.set(key(row.topic, row.subtopic), row.status);
      state.topicPapers.set(key(row.topic, row.subtopic),
                            row.papers_status || "not_started");
    }
  } catch { /* an empty tracker is a valid starting point */ }

  renderTopics();

  // Free users can only track progress on their first enrolled subject.
  const firstEnrolled = state.enrolled[0];
  const isPrivilegedUser = user.role === "teacher" || user.role === "admin";
  const isLocked = !isPrivilegedUser && user.plan === "free" && firstEnrolled && code !== firstEnrolled;
  const topicList = document.getElementById("topic-list");
  if (topicList) {
    topicList.classList.remove("pwt-locked");
    topicList.querySelectorAll(".pwt-lock-chip").forEach(c => c.remove());
    if (isLocked) {
      lockElement(topicList, {
        minPlan: "pro",
        label: "Upgrade to track all subjects",
        message: "Free plan lets you track progress in one subject. Upgrade to Pro to unlock all subjects.",
      });
    }
  }
}

/* ---- Status helpers ------------------------------------------------------ */

function statusOf(topic, subtopic) {
  return state.progress.get(key(topic, subtopic)) || "not_started";
}

function papersOf(topic, subtopic) {
  return state.topicPapers.get(key(topic, subtopic)) || "not_started";
}

function isReady(topic, subtopic) {
  return statusOf(topic, subtopic) === "confident"
      && papersOf(topic, subtopic) === "confident";
}

/* ---- Topic accordion ----------------------------------------------------- */

function segment(topic, subtopic, current) {
  const sub = subtopic == null ? "" : esc(subtopic);
  return `<div class="status-seg" data-topic="${esc(topic)}" data-subtopic="${sub}">
    ${STATUSES.map(([v, label]) => `
      <button type="button" class="status-btn status-${v}${current === v ? " on" : ""}"
              data-status="${v}" aria-pressed="${current === v}">${label}</button>`).join("")}
  </div>`;
}

function paperSegment(topic, subtopic, current) {
  const sub = subtopic == null ? "" : esc(subtopic);
  return `<div class="pp-seg-topic" data-topic="${esc(topic)}" data-subtopic="${sub}"
               role="group" aria-label="Past-paper practice for ${esc(topic)}">
    <span class="pp-seg-label">Past papers</span>
    ${PAPER_STEPS.map(([v, label, hint]) => `
      <button type="button" class="pp-topic-btn pp-topic-${v}${current === v ? " on" : ""}"
              data-papers="${v}" title="${esc(hint)}"
              aria-pressed="${current === v}">${label}</button>`).join("")}
  </div>`;
}

function renderTopics() {
  const subject = subjectFor(state.meta, state.syllabus);
  const list = document.getElementById("topic-list");
  if (!subject) { list.innerHTML = `<p class="revise-loading">Subject not found.</p>`; return; }

  renderSummary(subject);

  if (subject.split_by_paper && subject.paper_groups?.length) {
    const byName = new Map(subject.topics.map(t => [t.name, t]));
    list.innerHTML = subject.paper_groups.map(g => {
      const topics = g.topics.map(n => byName.get(n)).filter(Boolean);
      const done = topics.filter(t => statusOf(t.name, null) === "confident").length;
      const ready = topics.filter(t => isReady(t.name, null)).length;
      return `
        <section class="paper-group">
          <header class="paper-group-head">
            <h2>${esc(g.label)}</h2>
            <span class="paper-group-meta">
              ${topics.length} chapter${topics.length === 1 ? "" : "s"} ·
              <strong>${done}</strong> confident${ready ? ` · ★ ${ready} exam-ready` : ""}
            </span>
          </header>
          ${topics.map((t, i) => topicRow(t, i)).join("")}
        </section>`;
    }).join("");
    wireTopicList();
    return;
  }

  list.innerHTML = subject.topics.map((t, i) => topicRow(t, i)).join("");
  wireTopicList();
}

function topicRow(t, i) {
  const st = statusOf(t.name, null);
  const pp = papersOf(t.name, null);
  const ready = isReady(t.name, null);
  const subs = t.subtopics || [];
  return `
      <section class="topic-row status-is-${st}${ready ? " is-ready" : ""}"
               data-topic="${esc(t.name)}">
        <div class="topic-main">
          <button type="button" class="topic-toggle" aria-expanded="false"
                  ${subs.length ? "" : "disabled"}>
            <span class="topic-index">${String(i + 1).padStart(2, "0")}</span>
            <span class="topic-name">${esc(t.display || t.name)}
              ${ready ? `<span class="ready-badge" title="Learned and drilled">★ Exam-ready</span>` : ""}</span>
            <span class="topic-count">${t.count} question${t.count === 1 ? "" : "s"}</span>
            ${subs.length ? `<svg class="topic-chev" viewBox="0 0 12 8" width="12" height="8"
                 aria-hidden="true"><path d="M1 1.5 6 6.5 11 1.5" fill="none"
                 stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
                 stroke-linejoin="round"/></svg>` : ""}
          </button>
          <div class="topic-actions">
            ${segment(t.name, null, st)}
            ${paperSegment(t.name, null, pp)}
            <button type="button" class="btn-quiz" data-quiz-topic="${esc(t.name)}">
              Quiz me
            </button>
          </div>
        </div>
        ${subs.length ? `
          <div class="subtopic-list" hidden>
            ${subs.map(s => {
              const ss = statusOf(t.name, s.name);
              const sp = papersOf(t.name, s.name);
              return `<div class="subtopic-row${isReady(t.name, s.name) ? " is-ready" : ""}">
                <span class="subtopic-name"${s.detail ? ` title="${esc(s.detail)}"` : ""}>${esc(s.name)}</span>
                ${s.count ? `<span class="subtopic-count">${s.count}</span>` : ""}
                ${segment(t.name, s.name, ss)}
                ${paperSegment(t.name, s.name, sp)}
                <button type="button" class="btn-quiz btn-quiz-sm"
                        data-quiz-topic="${esc(t.name)}"
                        data-quiz-subtopic="${esc(s.name)}">Quiz</button>
              </div>`;
            }).join("")}
          </div>` : ""}
      </section>`;
}

/* ---- Progress rings summary ---------------------------------------------- */

function renderSummary(subject) {
  const total = subject.topics.length;
  let confident = 0, learning = 0, papersDone = 0, ready = 0;
  for (const t of subject.topics) {
    const s = statusOf(t.name, null);
    if (s === "confident") confident++;
    else if (s === "learning") learning++;
    if (papersOf(t.name, null) === "confident") papersDone++;
    if (isReady(t.name, null)) ready++;
  }
  const confPct = total ? Math.round((confident / total) * 100) : 0;
  const learnPct = total ? Math.round((learning / total) * 100) : 0;
  const paperPct = total ? Math.round((papersDone / total) * 100) : 0;
  const readyPct = total ? Math.round((ready / total) * 100) : 0;

  const box = document.getElementById("revise-summary");
  box.hidden = false;
  box.innerHTML = `
    <div class="progress-rings-row">
      ${renderProgressRing({
        pct: confPct, color: "green", label: "Confident",
        tooltip: `${confident} of ${total} chapters confident`
      })}
      ${renderProgressRing({
        pct: learnPct, color: "lav", label: "Learning",
        tooltip: `${learning} of ${total} chapters in progress`
      })}
      ${renderProgressRing({
        pct: paperPct, color: "orange", label: "PP Drilled",
        tooltip: `${papersDone} of ${total} chapters past-paper drilled`
      })}
      ${renderProgressRing({
        pct: readyPct, color: "gold", label: "Exam-Ready",
        tooltip: `${ready} of ${total} chapters both confident and drilled`
      })}
    </div>`;
}

/* ---- Wire events --------------------------------------------------------- */

function wireTopicList() {
  const list = document.getElementById("topic-list");

  list.querySelectorAll(".topic-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const panel = btn.closest(".topic-row").querySelector(".subtopic-list");
      if (!panel) return;
      const open = panel.hidden;
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      btn.classList.toggle("open", open);
    });
  });

  list.querySelectorAll(".status-btn").forEach(btn => {
    btn.addEventListener("click", () => setStatus(btn));
  });

  list.querySelectorAll(".pp-topic-btn").forEach(btn => {
    btn.addEventListener("click", () => setTopicPapers(btn));
  });

  list.querySelectorAll("[data-quiz-topic]").forEach(btn => {
    btn.addEventListener("click", () =>
      openQuiz(btn.dataset.quizTopic, btn.dataset.quizSubtopic || null));
  });
}

async function setStatus(btn) {
  const seg      = btn.closest(".status-seg");
  const topic    = seg.dataset.topic;
  const subtopic = seg.dataset.subtopic || null;
  const status   = btn.dataset.status;

  seg.querySelectorAll(".status-btn").forEach(b => {
    b.classList.toggle("on", b === btn);
    b.setAttribute("aria-pressed", String(b === btn));
  });
  state.progress.set(key(topic, subtopic), status);
  refreshReady(seg, topic, subtopic, status);
  renderSummary(subjectFor(state.meta, state.syllabus));

  try {
    await api("/api/progress", {
      method: "POST",
      body: { syllabus: state.syllabus, topic, subtopic, status },
    });
  } catch (err) {
    console.warn("Progress not saved:", err.message);
  }
}

async function setTopicPapers(btn) {
  const seg      = btn.closest(".pp-seg-topic");
  const topic    = seg.dataset.topic;
  const subtopic = seg.dataset.subtopic || null;
  const status   = btn.dataset.papers;

  seg.querySelectorAll(".pp-topic-btn").forEach(b => {
    b.classList.toggle("on", b === btn);
    b.setAttribute("aria-pressed", String(b === btn));
  });
  state.topicPapers.set(key(topic, subtopic), status);
  refreshReady(seg, topic, subtopic, null);
  renderSummary(subjectFor(state.meta, state.syllabus));

  try {
    await api("/api/progress", {
      method: "POST",
      body: { syllabus: state.syllabus, topic, subtopic, papers_status: status },
    });
  } catch (err) {
    console.warn("Past-paper practice not saved:", err.message);
  }
}

function refreshReady(seg, topic, subtopic, newStatus) {
  const ready = isReady(topic, subtopic);
  if (subtopic) {
    seg.closest(".subtopic-row")?.classList.toggle("is-ready", ready);
    return;
  }
  const row = seg.closest(".topic-row");
  if (!row) return;
  const st = newStatus || statusOf(topic, null);
  row.className = `topic-row status-is-${st}${ready ? " is-ready" : ""}`;
  const name = row.querySelector(".topic-name");
  const badge = name.querySelector(".ready-badge");
  if (ready && !badge) {
    name.insertAdjacentHTML("beforeend",
      ` <span class="ready-badge" title="Learned and drilled">★ Exam-ready</span>`);
  } else if (!ready && badge) {
    badge.remove();
  }
}

/* ---- Quiz panel ---------------------------------------------------------- */

function wireQuizPanel() {
  const overlay = document.getElementById("quiz-overlay");
  overlay.querySelectorAll("[data-close]").forEach(el =>
    el.addEventListener("click", closeQuiz));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !overlay.hidden) closeQuiz();
  });
}

function closeQuiz() {
  document.getElementById("quiz-overlay").hidden = true;
  document.body.style.overflow = "";
  state.quiz = null;
}

async function openQuiz(topic, subtopic) {
  const overlay = document.getElementById("quiz-overlay");
  const subject = subjectFor(state.meta, state.syllabus);

  overlay.hidden = false;
  document.body.style.overflow = "hidden";
  document.getElementById("quiz-subject").textContent =
    `${subject.short} · ${subject.board}`;
  document.getElementById("quiz-topic").textContent =
    subtopic ? `${topic} — ${subtopic}` : topic;

  state.quiz = { topic, subtopic };
  await generate();
}

async function generate(mode = "auto") {
  const body = document.getElementById("quiz-body");
  body.innerHTML = `
    <div class="quiz-loading">
      <span class="quiz-spinner" aria-hidden="true"></span>
      <p>${mode === "past_paper" ? "Finding a past-paper question…" : "Writing you a question…"}</p>
    </div>`;

  try {
    const q = await api("/api/quiz/generate", {
      method: "POST",
      body: {
        syllabus: state.syllabus,
        topic: state.quiz.topic,
        subtopic: state.quiz.subtopic,
        mode,
      },
    });
    Object.assign(state.quiz, {
      mode: q.mode, stem: q.stem, parts: q.parts,
      question: q.question, marks: q.marks, mark_scheme: q.mark_scheme,
      question_id: q.question_id, ref: q.ref,
      image_url: q.image_url, ms_url: q.ms_url,
    });
    renderQuestion();
  } catch (err) {
    body.innerHTML = `
      <div class="quiz-error">
        <p>${esc(err.message)}</p>
        <button type="button" class="btn btn-outline" id="quiz-retry">Try again</button>
      </div>`;
    document.getElementById("quiz-retry").addEventListener("click", () => generate(mode));
  }
}

function paperBody(q) {
  if (q.mode === "past_paper") {
    return `
      <figure class="paper-figure">
        <img src="${esc(q.image_url)}" alt="Past paper question ${esc(q.ref)}" loading="eager">
        <figcaption>${esc(q.ref)}${q.marks ? ` · ${q.marks} mark${q.marks === 1 ? "" : "s"}` : ""}</figcaption>
      </figure>`;
  }
  if (!q.parts?.length) {
    return `<div class="paper-part"><p>${esc(q.question).replace(/\n/g, "<br>")}</p></div>`;
  }
  return `
    ${q.stem ? `<p class="paper-stem">${esc(q.stem)}</p>` : ""}
    ${q.parts.map(p => `
      <div class="paper-part">
        <span class="paper-label">${esc(p.label)}</span>
        <div class="paper-text">
          <p>${esc(p.text)}</p>
          <div class="paper-rules">
            ${Array.from({ length: Math.min((p.marks || 1) + 1, 5) },
                         () => `<span class="paper-rule"></span>`).join("")}
          </div>
        </div>
        <span class="paper-marks">[${p.marks ?? ""}]</span>
      </div>`).join("")}`;
}

function renderQuestion() {
  const q = state.quiz;
  const isPP = q.mode === "past_paper";
  document.getElementById("quiz-body").innerHTML = `
    <div class="paper-sheet">
      <div class="paper-head">
        <span class="paper-qno">1</span>
        <span class="paper-source">${isPP
          ? `Cambridge past paper · ${esc(q.ref)}`
          : "Exam-style practice question"}</span>
        ${q.marks ? `<span class="paper-total">${q.marks} mark${q.marks === 1 ? "" : "s"}</span>` : ""}
      </div>
      ${paperBody(q)}
    </div>
    <label class="auth-field quiz-answer-field">
      <span>Your answer</span>
      <textarea id="quiz-answer" rows="8"
        placeholder="Answer as you would in the exam — label each part (a), (b) and show your working."></textarea>
    </label>
    <div class="quiz-actions">
      <button type="button" class="btn btn-gold" id="quiz-submit">Submit for marking</button>
      <button type="button" class="btn btn-outline" id="quiz-skip">Different question</button>
    </div>
    <div class="quiz-mode-switch">
      <button type="button" class="quiz-mode-btn" data-mode="${isPP ? "ai" : "past_paper"}">
        <span class="qm-icon" aria-hidden="true">${isPP ? "✎" : "📄"}</span>
        <span class="qm-text">
          <strong>${isPP ? "Try a fresh practice question" : "Switch to a real past-paper question"}</strong>
          <em>${isPP
            ? "Newly written on this chapter, unlimited attempts"
            : "The original Cambridge question, with its diagram and official mark scheme"}</em>
        </span>
        <span class="qm-arrow" aria-hidden="true">→</span>
      </button>
    </div>`;

  document.getElementById("quiz-submit").addEventListener("click", evaluate);
  document.getElementById("quiz-skip").addEventListener("click", () => generate(q.mode));
  const swap = document.querySelector(".quiz-mode-btn");
  if (swap) swap.addEventListener("click", () => generate(swap.dataset.mode));
  document.getElementById("quiz-answer").focus();
}

async function evaluate() {
  const answer = document.getElementById("quiz-answer").value.trim();
  const submit = document.getElementById("quiz-submit");
  if (!answer) {
    document.getElementById("quiz-answer").focus();
    return;
  }

  submit.disabled = true;
  submit.textContent = "Marking…";
  try {
    const res = await api("/api/quiz/evaluate", {
      method: "POST",
      body: {
        syllabus: state.syllabus,
        topic: state.quiz.topic,
        subtopic: state.quiz.subtopic,
        question: state.quiz.question || "",
        mark_scheme: state.quiz.mark_scheme,
        marks: state.quiz.marks,
        question_id: state.quiz.question_id ?? null,
        answer,
      },
    });
    renderResult(res, answer);
  } catch (err) {
    submit.disabled = false;
    submit.textContent = "Submit for marking";
    alert(err.message);
  }
}

function renderResult(res, answer) {
  const max = res.max_marks ?? state.quiz.marks;
  const score = res.score;
  const pct = (score != null && max) ? Math.round((score / max) * 100) : null;
  const band = pct == null ? "" : pct >= 75 ? "good" : pct >= 40 ? "mid" : "low";

  document.getElementById("quiz-body").innerHTML = `
    ${score != null ? `
      <div class="quiz-score quiz-score-${band}">
        <span class="quiz-score-value">${score}${max ? `<em>/${max}</em>` : ""}</span>
        <span class="quiz-score-label">${pct != null ? `${pct}%` : "marked"}</span>
      </div>` : ""}

    ${res.feedback ? `
      <div class="quiz-block">
        <h3>Examiner's comment</h3>
        <p>${esc(res.feedback).replace(/\n/g, "<br>")}</p>
      </div>` : ""}

    ${res.ms_url ? `
      <div class="quiz-block">
        <h3>Official Cambridge mark scheme</h3>
        <figure class="paper-figure paper-figure-ms">
          <img src="${esc(res.ms_url)}" alt="Official mark scheme" loading="lazy">
        </figure>
      </div>` : ""}

    <div class="quiz-block quiz-block-muted">
      <h3>The question</h3>
      ${state.quiz.image_url
        ? `<figure class="paper-figure"><img src="${esc(state.quiz.image_url)}" alt="" loading="lazy"></figure>`
        : `<p>${esc(state.quiz.question).replace(/\n/g, "<br>")}</p>`}
    </div>

    <div class="quiz-block quiz-block-muted">
      <h3>Your answer</h3>
      <p>${esc(answer).replace(/\n/g, "<br>")}</p>
    </div>

    ${res.ideal_answer ? `
      <details class="quiz-ideal"${res.ms_url ? "" : " open"}>
        <summary>What a full-mark answer covers</summary>
        <p>${esc(res.ideal_answer).replace(/\n/g, "<br>")}</p>
      </details>` : ""}

    <div class="quiz-actions">
      <button type="button" class="btn btn-gold" id="quiz-again">Another question</button>
      <button type="button" class="btn btn-outline" data-close>Back to chapters</button>
    </div>`;

  document.getElementById("quiz-again")
    .addEventListener("click", () => generate(state.quiz.mode || "auto"));
  document.querySelector("#quiz-body [data-close]").addEventListener("click", closeQuiz);
}
