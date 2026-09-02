/**
 * MCQ Live Solver — full session engine.
 *
 * Mode 1 (topic):  pick topics from a subject, random question pool
 * Mode 2 (paper):  pick a specific past paper, all Qs in order
 *
 * Auto-check: when ms_entries.answer is stored, the answer locks in on click
 * and inline green/red feedback appears.  There is NO auto-advance — the
 * student reads the feedback (and optionally the AI explanation) and presses
 * Next.  When no answer is stored, the MS crop overlay appears for self-check.
 *
 * Navigator: fixed bottom-left grid showing status of every question —
 * click any dot to jump to that question (already-answered questions are shown
 * in review mode; unanswered ones resume normally).
 *
 * Session state is mirrored to localStorage so a refresh can offer a resume.
 * The saved record stores the *request* (state.lastBody, seed included), not
 * the question array — the backend's selection is seeded and deterministic,
 * so re-POSTing reproduces the identical list for a fraction of the bytes.
 */

import { api, getUser, showAuthRequiredModal } from "/auth.js";

// MCQ papers by syllabus-paper combo
const MCQ_PAPERS = new Set([
  "9702-1","5054-1","0625-1","0625-2","5070-1","0620-1","0620-2",
]);
function isMCQPaper(syl, paper) { return MCQ_PAPERS.has(`${syl}-${paper}`); }
function mcqPapersFor(syl, sub) {
  return (sub?.components || [])
    .filter(c => isMCQPaper(syl, c.paper))
    .map(c => c.paper);
}

const SESSION_LABELS = { s: "May/Jun", w: "Oct/Nov", m: "Feb/Mar" };
// Cambridge sits Feb/March first, then May/June, then Oct/Nov. Sorting the
// session codes alphabetically happens to give m,s,w — but only by accident,
// so the order is written down rather than relied on.
const SESSION_ORDER = { m: 0, s: 1, w: 2 };
const $ = id => document.getElementById(id);
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtTime(secs) {
  return `${Math.floor(secs/60)}:${String(secs%60).padStart(2,"0")}`;
}
function showPanel(id) {
  ["setup-panel","session-panel","results-panel"].forEach(pid => {
    const el = document.getElementById(pid);
    if (el) el.hidden = pid !== id;
  });
}

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  meta: null, syllabus: null, papers: [], board: null,
  mode: "topic",       // "topic" | "paper"
  fpSel: null,         // {paper_id, label, q_count, paper} for full-paper mode
  fpAllPapers: [],     // cached list from /api/mcq/papers
  fpYear: null,        // selected year in tabbed FP picker
  fpSession: null,     // selected session in tabbed FP picker
  fpComp: null,        // selected paper component (1, 2, …) in FP picker
  timeSecs: 90,
  countSel: 40,        // 0=all, -1=custom, else N
  questions: [], qIndex: 0,
  results: [],         // indexed array: results[i] = entry | null (unanswered)
  flags: [],           // indexed array of booleans, parallel to results
  streak: 0, bestStreak: 0,
  paused: false, pauseStart: 0,
  qStartTime: 0, sessionStartTime: 0,
  overallTimer: null, qTimer: null, qElapsed: 0,
  paperTimer: null, paperTimerEnd: null,
  answered: false, lastBody: null,
  navOpen: false,
  isGuest: false,
};

// ── Session persistence ───────────────────────────────────────────────────────
// Declared above the boot block on purpose: readSaved() runs during boot, and a
// `const` declared further down would still be in its temporal dead zone.
//
// We persist the REQUEST, not the response. state.lastBody carries the seed,
// and the backend's selection is seeded + deterministically ordered, so
// re-POSTing reproduces the identical question list. Storing the question
// array instead would cost ~3 MB for a 9999-question "All" session.
const SAVE_KEY = "pwt_mcq_session";
const SAVE_MAX_AGE_MS = 24 * 60 * 60 * 1000;
let saveTimer = null;
let saveDisabled = false;   // set if the browser refuses writes (quota/private mode)

function snapshot() {
  return {
    v: 1,
    savedAt: Date.now(),
    mode: state.mode,
    syllabus: state.syllabus,
    subjectLabel: $("mcq-session-subject-label").textContent,
    body: state.lastBody,
    total: state.questions.length,
    qIndex: state.qIndex,
    timeSecs: state.timeSecs,
    elapsedMs: Date.now() - state.sessionStartTime,
    paperRemainMs: state.paperTimerEnd ? Math.max(0, state.paperTimerEnd - Date.now()) : null,
    results: state.results,
    flags: state.flags,
    streak: state.streak,
    bestStreak: state.bestStreak,
  };
}

// Debounced: the overall timer ticks twice a second and must never drive a write.
function saveSession() {
  if (saveDisabled || !state.questions.length || !state.lastBody) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, 400);
}
function flushSave() {
  clearTimeout(saveTimer);
  if (saveDisabled || !state.questions.length || !state.lastBody) return;
  try { localStorage.setItem(SAVE_KEY, JSON.stringify(snapshot())); }
  catch (e) { saveDisabled = true; }   // degrade silently, never break the session
}
function clearSaved() {
  saveDisabled = false;
  clearTimeout(saveTimer);
  try { localStorage.removeItem(SAVE_KEY); } catch (e) {}
}
// Closing the tab mid-question should not lose the last few answers.
addEventListener("pagehide", () => {
  const p = $("session-panel");
  if (p && !p.hidden) flushSave();
});

function readSaved() {
  let rec;
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (!raw) return null;
    rec = JSON.parse(raw);
  } catch (e) { return null; }
  const ok = rec && rec.v === 1 && rec.body && rec.total > 0
    && Number.isInteger(rec.qIndex) && rec.qIndex < rec.total
    && Date.now() - (rec.savedAt || 0) < SAVE_MAX_AGE_MS;
  if (!ok) { clearSaved(); return null; }
  return rec;
}

function agoText(ms) {
  const m = Math.round(ms / 60000);
  if (m < 1) return "just now";
  if (m === 1) return "a minute ago";
  if (m < 60) return `${m} minutes ago`;
  const h = Math.round(m / 60);
  return h === 1 ? "an hour ago" : `${h} hours ago`;
}

function showResumePrompt(rec) {
  const answered = (rec.results || []).filter(Boolean).length;
  $("mcq-resume-info").textContent =
    `${rec.subjectLabel || rec.syllabus} — ${answered} of ${rec.total} answered, `
    + `saved ${agoText(Date.now() - rec.savedAt)}. `
    + `Your question timer starts fresh.`;
  $("mcq-resume-modal").hidden = false;
  $("mcq-resume-yes").onclick = () => resumeSession(rec);
  $("mcq-resume-no").onclick = () => { clearSaved(); $("mcq-resume-modal").hidden = true; };
}

function failResumePrompt(msg) {
  const yes = $("mcq-resume-yes"), err = $("mcq-resume-err");
  if (yes) { yes.disabled = true; yes.textContent = "Resume"; }
  if (err) { err.textContent = msg; err.hidden = false; }
}

async function resumeSession(rec) {
  const yes = $("mcq-resume-yes");
  yes.disabled = true; yes.textContent = "Loading…";
  $("mcq-resume-err").hidden = true;

  let data;
  try { data = await api("/api/mcq/questions", { method: "POST", body: rec.body }); }
  catch (e) { return failResumePrompt("Couldn't reload those questions: " + e.message); }

  if (!data.questions?.length || data.questions.length !== rec.total) {
    clearSaved();
    return failResumePrompt("That session can't be restored — the question set changed. Start fresh.");
  }

  state.mode = rec.mode; state.syllabus = rec.syllabus;
  state.lastBody = rec.body; state.timeSecs = rec.timeSecs;
  state.questions = data.questions;
  state.results = rec.results || new Array(rec.total).fill(null);
  state.flags = rec.flags?.length === rec.total ? rec.flags : new Array(rec.total).fill(false);
  state.streak = rec.streak || 0;
  state.bestStreak = rec.bestStreak || 0;
  state.sessionStartTime = Date.now() - (rec.elapsedMs || 0);

  $("mcq-resume-modal").hidden = true;
  enterSession(rec.qIndex, rec.subjectLabel,
    rec.paperRemainMs != null ? Date.now() + rec.paperRemainMs : null);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
// Check auth without redirecting — unauthenticated users see the setup UI in
// a locked state with an inline sign-in prompt on click, never an auto-redirect.
const currentUser = await getUser();
state.isGuest = !currentUser;

// Guests skip the API calls entirely — show auth wall on the setup panel now.
if (state.isGuest) {
  showPanel("setup-panel");
  showGuestWall();
} else {
  // Read + render the resume prompt BEFORE the await, so a refresh shows it
  // instantly. The Resume button stays disabled until meta actually arrives.
  const savedSession = readSaved();
  if (savedSession) showResumePrompt(savedSession);

  let meta;
  try {
    const [metaRes, enrollRes] = await Promise.all([
      api("/api/meta"),
      api("/api/enrollments").catch(() => null)
    ]);
    meta = metaRes;
    if (enrollRes && enrollRes.enrollments) {
      state.enrolledSyllabuses = enrollRes.enrollments.map(e => e.syllabus);
    } else {
      state.enrolledSyllabuses = [];
    }
  }
  catch(e) {
    $("mcq-setup-status").textContent = "Couldn't load subjects: " + e.message;
    if (savedSession) failResumePrompt("Couldn't reach the server — try refreshing.");
  }
  state.meta = meta;
  initSetupUI();
  if (savedSession && state.meta) $("mcq-resume-yes").disabled = false;
}

// ── Setup UI ──────────────────────────────────────────────────────────────────
function initSetupUI() {
  if (!state.meta) return;

  // Mode toggle
  document.querySelectorAll("#mcq-mode-seg .pill").forEach(btn => {
    btn.onclick = () => {
      if (btn.dataset.mode === state.mode) return;
      state.mode = btn.dataset.mode;
      document.querySelectorAll("#mcq-mode-seg .pill").forEach(b =>
        b.classList.toggle("active", b === btn));
      $("mcq-mode-topic").hidden = state.mode !== "topic";
      $("mcq-mode-paper").hidden = state.mode !== "paper";
      if (state.mode === "paper" && state.syllabus) {
        if (state.fpAllPapers.length) {
          renderFPUI(state.syllabus); // already pre-loaded, just render the UI
        } else {
          const sub = state.meta.subjects.find(s => s.syllabus === state.syllabus);
          initFullPaperMode(state.syllabus, sub);
        }
      }
      updateSetupSummary();
    };
  });

  // Board toggle + subject buttons
  const row = $("mcq-subjects"); row.innerHTML = "";
  const enrolled = state.enrolledSyllabuses || [];
  const subjectsToRender = enrolled.length > 0
    ? state.meta.subjects.filter(s => enrolled.includes(s.syllabus))
    : state.meta.subjects;

  const byBoard = {};
  for (const s of subjectsToRender) (byBoard[s.board] ||= []).push(s);
  const order = state.meta.board_order || [];
  const boards = [...order.filter(b => byBoard[b]), ...Object.keys(byBoard).filter(b => !order.includes(b))];

  const switcher = document.createElement("div");
  switcher.className = "seg-large"; switcher.id = "mcq-board-toggle";
  for (const board of boards) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.board = board.toLowerCase().replace(/\s+/g, "-");
    btn.textContent = board.replace(/^Cambridge\s+/, "");
    btn.onclick = () => switchBoard(board);
    switcher.appendChild(btn);
  }
  row.appendChild(switcher);

  for (const board of boards) {
    const group = document.createElement("div");
    group.className = "subject-group";
    group.dataset.board = board.toLowerCase().replace(/\s+/g, "-");
    const pr = document.createElement("div"); pr.className = "pill-row";
    for (const s of byBoard[board]) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "pill subject"; b.dataset.syllabus = s.syllabus;
      const hasMCQ = (s.components || []).some(c => isMCQPaper(s.syllabus, c.paper));
      if (!hasMCQ) { b.classList.add("mcq-subject-disabled"); b.title = "No MCQ paper available"; }
      b.innerHTML = `${s.short || s.subject} <small>${s.syllabus}</small>`;
      b.onclick = () => { if (!hasMCQ) return; pickSubject(s.syllabus); };
      pr.appendChild(b);
    }
    group.appendChild(pr); row.appendChild(group);
  }

  // Pre-select from URL params
  const params = new URLSearchParams(location.search);
  const wantSyl = params.get("syllabus");
  const wantTopics = (params.get("topics") || "").split(",").filter(Boolean);
  const first = state.meta.subjects.find(s => s.syllabus === wantSyl) ||
    state.meta.subjects.find(s => (s.components || []).some(c => isMCQPaper(s.syllabus, c.paper)));
  if (first) { switchBoard(first.board); pickSubject(first.syllabus, wantTopics); }
  else if (boards.length) switchBoard(boards[0]);

  setYearRange(state.meta.year_min, state.meta.year_max);

  // Time pills
  document.querySelectorAll("#mcq-time-pills .pill").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll("#mcq-time-pills .pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.timeSecs = +btn.dataset.secs;
      $("mcq-ring-wrap").style.display = state.timeSecs === 0 ? "none" : "";
    };
  });

  // Topic all/clear
  $("mcq-all").onclick = () => {
    document.querySelectorAll("#mcq-topics .topic-cb").forEach(i => {
      if (i.closest(".topic-wrapper").style.display !== "none") {
        i.checked = true; i.closest(".topic").classList.add("on");
      }
    });
    updateSetupSummary();
  };
  $("mcq-none").onclick = () => {
    document.querySelectorAll("#mcq-topics .topic-cb").forEach(i => {
      i.checked = false; i.closest(".topic").classList.remove("on");
    });
    updateSetupSummary();
  };
  $("mcq-topic-search").oninput = e => filterTopics(e.target.value);
  $("mcq-yfrom").onchange = updateSetupSummary;
  $("mcq-yto").onchange = updateSetupSummary;
  document.querySelectorAll("#mcq-count-pills [data-cnt]").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll("#mcq-count-pills [data-cnt]")
        .forEach(b => b.classList.toggle("active", b === btn));
      state.countSel = +btn.dataset.cnt;
      const cw = $("mcq-custom-wrap");
      if (cw) cw.hidden = state.countSel !== -1;
      updateSetupSummary();
    };
  });
  $("mcq-custom-n")?.addEventListener("input", updateSetupSummary);
  $("fp-latest")?.addEventListener("click", () => fpJumpToLatest(state.syllabus));
  $("mcq-start").onclick = () => state.isGuest ? showGuestWall() : startSession();
}

function switchBoard(board) {
  state.board = board;
  const bk = board.toLowerCase().replace(/\s+/g, "-");
  document.querySelectorAll("#mcq-board-toggle button").forEach(b =>
    b.classList.toggle("active", b.dataset.board === bk));
  document.querySelectorAll("#mcq-subjects .subject-group").forEach(g => {
    g.style.display = g.dataset.board === bk ? "" : "none";
  });
}

function pickSubject(syl, preselect = []) {
  state.syllabus = syl; state.papers = []; state.fpSel = null; state.fpAllPapers = [];
  state.fpYear = null; state.fpSession = null; state.fpComp = null;
  document.querySelectorAll(".subject").forEach(b =>
    b.classList.toggle("active", b.dataset.syllabus === syl));
  const sub = state.meta.subjects.find(s => s.syllabus === syl);
  if (sub && sub.board !== state.board) switchBoard(sub.board);

  const compField = $("mcq-component-field");
  const compRow = $("mcq-components");
  compRow.innerHTML = "";
  const mcqComps = (sub?.components || []).filter(c => isMCQPaper(syl, c.paper));

  if (mcqComps.length > 1) {
    compField.classList.remove("hidden");
    const mk = (paper, label, count) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "pill component";
      b.dataset.paper = paper === null ? "" : paper;
      b.innerHTML = `${label} <small>${count}</small>`;
      b.onclick = () => toggleComponent(paper);
      compRow.appendChild(b);
    };
    mk(null, "All MCQ papers", mcqComps.reduce((s, c) => s + c.count, 0));
    for (const c of mcqComps) mk(c.paper, c.label, c.count);
    syncComponentPills();
    $("mcq-topics-step").textContent = "4 · Topics";
    $("mcq-years-label").textContent = "5 · Years";
  } else {
    compField.classList.add("hidden");
    if (mcqComps.length === 1) state.papers = [mcqComps[0].paper];
    $("mcq-topics-step").textContent = "3 · Topics";
    $("mcq-years-label").textContent = "4 · Years";
  }

  const yearMin = sub?.year_min || state.meta.year_min;
  const yearMax = sub?.year_max || state.meta.year_max;
  setYearRange(yearMin, yearMax);
  renderTopics(sub, preselect);
  // Always pre-load papers list (renders the UI if mode is already "paper")
  initFullPaperMode(syl, sub);
}

function toggleComponent(paper) {
  if (paper === null) state.papers = [];
  else if (state.papers.includes(paper)) state.papers = state.papers.filter(p => p !== paper);
  else state.papers = [...state.papers, paper];
  syncComponentPills();
  renderTopics(state.meta.subjects.find(s => s.syllabus === state.syllabus));
  updateSetupSummary();
}
function syncComponentPills() {
  const allActive = state.papers.length === 0;
  document.querySelectorAll("#mcq-components .pill.component").forEach(b => {
    if (b.dataset.paper === "") b.classList.toggle("active", allActive);
    else b.classList.toggle("active", state.papers.includes(+b.dataset.paper));
  });
}

function setYearRange(yearMin, yearMax) {
  const fromSel = $("mcq-yfrom"), toSel = $("mcq-yto");
  const pf = +fromSel.value, pt = +toSel.value;
  fromSel.innerHTML = ""; toSel.innerHTML = "";
  for (let y = yearMin; y <= yearMax; y++) {
    for (const sel of [fromSel, toSel]) {
      const o = document.createElement("option"); o.value = o.textContent = y; sel.appendChild(o);
    }
  }
  fromSel.value = (pf >= yearMin && pf <= yearMax) ? pf : yearMin;
  toSel.value = (pt >= yearMin && pt <= yearMax) ? pt : yearMax;
  if (fromSel._sdInstance) fromSel._sdInstance.refresh();
  if (toSel._sdInstance) toSel._sdInstance.refresh();
}


function renderTopics(sub, preselect = []) {
  if (!sub) return;
  const keep = new Set([...document.querySelectorAll("#mcq-topics .topic-cb:checked")].map(i => i.value));
  const box = $("mcq-topics"); box.innerHTML = "";
  const ps = new Set(preselect.map(t => t.toLowerCase()));
  let shown = 0;
  for (const t of sub.topics) {
    const count = state.papers.length === 0
      ? t.count
      : state.papers.reduce((s, p) => s + (t.papers[String(p)] || 0), 0);
    if (!count) continue; shown++;
    const wrapper = document.createElement("div"); wrapper.className = "topic-wrapper";
    const label = document.createElement("label"); label.className = "topic";
    label.dataset.count = count; label.dataset.topicName = t.name;
    label.innerHTML = `<input type="checkbox" class="topic-cb" value="${t.name}"><span>${esc(t.display || t.name)}</span><span class="n">${count}</span>`;
    const input = label.querySelector(".topic-cb");
    const shouldCheck = keep.has(t.name) || ps.has(t.name.toLowerCase());
    if (shouldCheck) { input.checked = true; label.classList.add("on"); }
    input.onchange = e => { label.classList.toggle("on", e.target.checked); updateSetupSummary(); };
    wrapper.appendChild(label); box.appendChild(wrapper);
  }
  const search = $("mcq-topic-search");
  search.style.display = shown > 8 ? "" : "none"; search.value = "";
  filterTopics("");
  $("mcq-topic-note").textContent = `${shown} topics`;
  updateSetupSummary();
}

function filterTopics(q) {
  q = q.trim().toLowerCase();
  document.querySelectorAll("#mcq-topics .topic-wrapper").forEach(w => {
    const name = w.querySelector(".topic span").textContent.toLowerCase();
    w.style.display = !q || name.includes(q) ? "" : "none";
  });
}

function showGuestWall() {
  showAuthRequiredModal({
    heading: "Sign in to use MCQ Solver",
    text: "You need a free PrepWithTee account to practise past paper MCQs.",
    nextUrl: location.pathname + location.search,
    container: document.getElementById("setup-panel"),
  });
}

function updateSetupSummary() {
  const startBtn = $("mcq-start");
  if (state.isGuest) {
    startBtn.disabled = false;
    startBtn.title = "Sign in required";
    startBtn.style.opacity = "0.55";
    $("mcq-summary").innerHTML = `<span class="muted">Sign in to start practising.</span>`;
    return;
  }
  startBtn.title = "";
  startBtn.style.opacity = "";
  if (state.mode === "paper") {
    if (state.fpSel) {
      const mins = paperExamMins(state.syllabus, state.fpSel.paper);
      $("mcq-summary").innerHTML =
        `<b>${esc(state.fpSel.label)}</b> &middot; ${state.fpSel.q_count} questions &middot; ${mins} min`;
      startBtn.disabled = false;
    } else {
      $("mcq-summary").innerHTML = `<span class="muted">Pick a paper to start.</span>`;
      startBtn.disabled = true;
    }
    return;
  }
  const checked = [...document.querySelectorAll("#mcq-topics .topic-cb:checked")];
  const nTopics = checked.length;
  const nQ = checked.reduce((s, i) => s + (+i.closest(".topic").dataset.count || 0), 0);
  const sub = state.meta.subjects.find(s => s.syllabus === state.syllabus);
  if (!nTopics) {
    $("mcq-summary").innerHTML = `<span class="muted">Pick at least one topic to start.</span>`;
    startBtn.disabled = true; return;
  }
  startBtn.disabled = false;
  const sylLabel = sub ? (sub.short || sub.subject) : state.syllabus;
  const yf = $("mcq-yfrom").value, yt = $("mcq-yto").value;
  const count = getCount();
  const countLbl = state.countSel === 0 ? "All" : count;
  const hint = $("mcq-custom-hint");
  if (hint) hint.textContent = state.countSel === -1 && nQ > 0 ? `pool: ${nQ}` : "";
  const timeLbl = state.timeSecs === 0 ? "no limit" : `${state.timeSecs}s/Q`;
  $("mcq-summary").innerHTML = `<b>${esc(sylLabel)}</b> &middot; <b>${nTopics}</b> topic${nTopics > 1 ? "s" : ""} <span class="muted">(~${nQ} in pool)</span> &middot; ${yf}&ndash;${yt} &middot; ${countLbl} Qs &middot; ${timeLbl}`;
}

// ── Full Past Paper mode ───────────────────────────────────────────────────────
async function initFullPaperMode(syl, sub) {
  if (state.mode === "paper") {
    $("fp-year-tabs").innerHTML = `<span class="muted">Loading…</span>`;
    $("fp-step-sess").hidden = true;
    $("fp-step-comp").hidden = true;
    $("fp-step-var").hidden = true;
    $("mcq-fp-info").innerHTML = "";
  }
  let data;
  try { data = await api(`/api/mcq/papers?syllabus=${encodeURIComponent(syl)}`); }
  catch(e) {
    if (state.mode === "paper") $("fp-year-tabs").innerHTML = `<span class="error-text">${esc(e.message)}</span>`;
    return;
  }
  state.fpAllPapers = (data.papers || []).filter(p => isMCQPaper(syl, p.paper));
  if (state.mode === "paper") renderFPUI(syl);
}

// Label a component the way the student's syllabus does ("P2 · MCQ Extended"),
// falling back to a plain paper number for subjects /api/meta has no label for.
function fpCompLabel(paper) {
  const sub = state.meta?.subjects?.find(s => s.syllabus === state.syllabus);
  const c = (sub?.components || []).find(c => c.paper === paper);
  return c?.label || `Paper ${paper}`;
}

// Narrow the cached paper list one step at a time. Each step reads the
// selections above it, so the four rows can never disagree about what is shown.
function fpPapersAt({ year, session, comp } = {}) {
  return state.fpAllPapers.filter(p =>
    (year == null || p.year === year) &&
    (session == null || p.session === session) &&
    (comp == null || p.paper === comp));
}

/* Tabbed picker: year → session → paper component → variant.
 *
 * Every step clamps its own selection to what is actually available and then
 * auto-selects the first option, so there is always a valid paper chosen —
 * the old build could leave `fpSel` null after a year change and silently
 * disable Start with no explanation on screen. */
function renderFPUI(syl) {
  const yearTabsEl = $("fp-year-tabs");
  if (!yearTabsEl) return;
  const sessStep = $("fp-step-sess"), sessTabsEl = $("fp-sess-tabs");
  const compStep = $("fp-step-comp"), compRowEl = $("fp-comp-row");
  const varStep  = $("fp-step-var"),  varRowEl  = $("fp-var-row");

  const years = [...new Set(state.fpAllPapers.map(p => p.year))].sort((a, b) => b - a);
  if (!years.length) {
    yearTabsEl.innerHTML = `<span class="muted">No MCQ papers for this subject.</span>`;
    sessStep.hidden = compStep.hidden = varStep.hidden = true;
    state.fpSel = null;
    $("mcq-fp-info").innerHTML = "";
    updateSetupSummary();
    return;
  }

  // ── Year ──
  if (!years.includes(state.fpYear)) state.fpYear = years[0];
  yearTabsEl.innerHTML = years.map(y =>
    `<button type="button" class="fp-tab${y === state.fpYear ? " active" : ""}" data-fpyear="${y}">${y}</button>`
  ).join("");

  // ── Session ──
  const sessions = [...new Set(fpPapersAt({ year: state.fpYear }).map(p => p.session))]
    .sort((a, b) => (SESSION_ORDER[a] ?? 9) - (SESSION_ORDER[b] ?? 9));
  if (!sessions.includes(state.fpSession)) state.fpSession = sessions[0] || null;
  sessStep.hidden = false;
  sessTabsEl.innerHTML = sessions.map(s =>
    `<button type="button" class="fp-sess-btn${s === state.fpSession ? " active" : ""}" data-fpses="${s}">${SESSION_LABELS[s] || s.toUpperCase()}</button>`
  ).join("");

  // ── Paper component ──
  // Hidden when the subject only examines one MCQ component: a single "P1"
  // button is a step the student has to click through for nothing.
  const comps = [...new Set(fpPapersAt({ year: state.fpYear, session: state.fpSession })
    .map(p => p.paper))].sort((a, b) => a - b);
  const allComps = [...new Set(state.fpAllPapers.map(p => p.paper))];
  if (!comps.includes(state.fpComp)) state.fpComp = comps[0] ?? null;
  compStep.hidden = allComps.length < 2;
  compRowEl.innerHTML = comps.map(c => {
    const n = fpPapersAt({ year: state.fpYear, session: state.fpSession, comp: c }).length;
    return `<button type="button" class="fp-comp-btn${c === state.fpComp ? " active" : ""}" data-fpcomp="${c}">`
         + `${esc(fpCompLabel(c))}<small>${n} variant${n === 1 ? "" : "s"}</small></button>`;
  }).join("");

  // ── Variant ──
  const papers = fpPapersAt({ year: state.fpYear, session: state.fpSession, comp: state.fpComp })
    .sort((a, b) => String(a.variant).localeCompare(String(b.variant), undefined, { numeric: true }));
  if (!papers.some(p => p.id === state.fpSel?.paper_id)) {
    if (papers.length) selectFPPaper(papers[0], syl);
    else state.fpSel = null;
  }
  varStep.hidden = false;
  varRowEl.innerHTML = papers.length
    ? papers.map(p =>
        `<button type="button" class="fp-var-btn${state.fpSel?.paper_id === p.id ? " active" : ""}" data-fpvar="${p.id}">`
        + `<b>Variant ${esc(p.variant)}</b><small>${p.q_count} question${p.q_count === 1 ? "" : "s"}</small></button>`
      ).join("")
    : `<span class="muted">No papers for this session.</span>`;

  renderFPInfo();
  updateSetupSummary();

  // ── Event listeners ──
  // Clearing the step below on each click is what lets the clamps above pick a
  // sensible default rather than keeping a variant from a different paper.
  yearTabsEl.querySelectorAll("[data-fpyear]").forEach(b => b.onclick = () => {
    state.fpYear = +b.dataset.fpyear;
    state.fpSession = null; state.fpSel = null;
    renderFPUI(syl);
  });
  sessTabsEl.querySelectorAll("[data-fpses]").forEach(b => b.onclick = () => {
    state.fpSession = b.dataset.fpses; state.fpSel = null;
    renderFPUI(syl);
  });
  compRowEl.querySelectorAll("[data-fpcomp]").forEach(b => b.onclick = () => {
    state.fpComp = +b.dataset.fpcomp; state.fpSel = null;
    renderFPUI(syl);
  });
  varRowEl.querySelectorAll("[data-fpvar]").forEach(b => b.onclick = () => {
    const paper = state.fpAllPapers.find(p => p.id === +b.dataset.fpvar);
    if (!paper) return;
    selectFPPaper(paper, syl);
    varRowEl.querySelectorAll(".fp-var-btn").forEach(x =>
      x.classList.toggle("active", x === b));
    renderFPInfo();
    updateSetupSummary();
  });
}

// What the student is about to sit, in words: paper name, question count and
// the real Cambridge time allowance for that component.
function renderFPInfo() {
  const el = $("mcq-fp-info");
  if (!el) return;
  const sel = state.fpSel;
  if (!sel) { el.innerHTML = ""; return; }
  const mins = paperExamMins(state.syllabus, sel.paper);
  el.innerHTML =
    `<span class="fp-info-chip">&#x1F4C4; ${esc(sel.label)}</span>`
    + `<span class="fp-info-chip">&#x2753; ${sel.q_count} questions</span>`
    + `<span class="fp-info-chip">&#x23F1; ${mins} min booklet time</span>`;
}

// "Jump to latest": the newest year, its latest session, and the first
// variant of the component already being looked at.
function fpJumpToLatest(syl) {
  if (!state.fpAllPapers.length) return;
  const latest = state.fpAllPapers
    .slice()
    .sort((a, b) => b.year - a.year
      || (SESSION_ORDER[b.session] ?? 9) - (SESSION_ORDER[a.session] ?? 9))[0];
  state.fpYear = latest.year;
  state.fpSession = latest.session;
  state.fpSel = null;
  renderFPUI(syl);
}

function selectFPPaper(paper, syl) {
  const sa = SESSION_LABELS[paper.session] || paper.session.toUpperCase();
  state.fpComp = paper.paper;
  state.fpSel = {
    paper_id: paper.id,
    label: `${syl} ${sa} ${paper.year} · P${paper.paper} variant ${paper.variant}`,
    q_count: paper.q_count,
    paper: paper.paper,
    year: paper.year,
    session: paper.session,
    variant: paper.variant,
  };
}

// ── Start session ──────────────────────────────────────────────────────────────
async function startSession() {
  const startBtn = $("mcq-start"); startBtn.disabled = true;
  $("mcq-setup-status").textContent = "Loading questions…";

  let body;
  if (state.mode === "paper") {
    if (!state.fpSel) { $("mcq-setup-status").textContent = "Pick a paper first."; startBtn.disabled = false; return; }
    body = { syllabus: state.syllabus, paper_id: state.fpSel.paper_id, topics: [] };
  } else {
    const topics = [...document.querySelectorAll("#mcq-topics .topic-cb:checked")].map(i => i.value);
    if (!topics.length) { startBtn.disabled = false; return; }

    // Always restrict to MCQ-only papers (fixes theory questions mixing in)
    let papersToSend = [...state.papers];
    if (!papersToSend.length) {
      const sub = state.meta.subjects.find(s => s.syllabus === state.syllabus);
      papersToSend = mcqPapersFor(state.syllabus, sub);
    }

    body = {
      syllabus: state.syllabus, topics,
      year_from: +$("mcq-yfrom").value, year_to: +$("mcq-yto").value,
      count: getCount(),
      seed: Math.floor(Math.random() * 99999),
    };
    if (papersToSend.length) body.papers = papersToSend;
  }
  state.lastBody = body;

  try {
    const data = await api("/api/mcq/questions", { method: "POST", body });
    if (!data.questions.length) throw new Error("No questions match these filters.");
    state.questions = data.questions;
  } catch(err) {
    if (err.message === "Not authenticated" || err.status === 401) {
      $("mcq-setup-status").textContent = "";
      startBtn.disabled = false;
      showGuestWall();
      return;
    }
    $("mcq-setup-status").textContent = err.message; startBtn.disabled = false; return;
  }

  state.results = new Array(state.questions.length).fill(null); // indexed, not push
  state.flags   = new Array(state.questions.length).fill(false);
  state.streak = 0; state.bestStreak = 0;
  state.sessionStartTime = Date.now();
  const sub = state.meta.subjects.find(s => s.syllabus === state.syllabus);
  const label = sub ? (sub.short || sub.subject) : state.syllabus;
  const ms = bookletMs();
  clearSaved();
  enterSession(0, label, ms ? Date.now() + ms : null);
}

// Total time allowed for the whole booklet.
// Full-paper mode uses the real exam duration; topic mode is simply the
// per-question allowance multiplied by however many questions were drawn.
// "No limit" (timeSecs 0) means no booklet countdown at all.
function bookletMs() {
  if (state.mode === "paper" && state.fpSel?.paper) {
    return paperExamMins(state.syllabus, state.fpSel.paper) * 60_000;
  }
  if (state.timeSecs > 0) return state.timeSecs * state.questions.length * 1000;
  return 0;
}

// Everything from "we have a question list" to "the student is looking at one".
// Shared by startSession and resumeSession so the two can never drift.
function enterSession(startIndex, subjectLabel, paperEndAt) {
  state.qIndex = startIndex;
  state.paused = false; state.answered = false;
  $("mcq-setup-status").textContent = "";
  $("mcq-session-subject-label").textContent = subjectLabel || "";
  const pFill = $("mcq-progress-fill");
  if (pFill) pFill.style.width = "0%";
  document.body.classList.add("mcq-in-session");
  showPanel("session-panel");
  startOverallTimer();
  // Two timers, not three: when a booklet countdown is running it IS the
  // headline figure, so the elapsed stopwatch steps aside. With "No limit"
  // there is no countdown, so the stopwatch takes over.
  if (paperEndAt) { startPaperTimer(paperEndAt); $("mcq-overall-timer").hidden = true; }
  else {
    const ptEl = $("mcq-paper-time"); if (ptEl) ptEl.hidden = true;
    $("mcq-overall-timer").hidden = false;
  }
  buildNav();
  state.navOpen = false; // ensure toggleNav opens it
  toggleNav();           // open navigator by default
  syncThemeBtn();
  renderStreak();
  loadQuestion(startIndex);
  document.addEventListener("keydown", onKeyDown);
}

// ── Overall timer ──────────────────────────────────────────────────────────────
function startOverallTimer() {
  if (state.overallTimer) clearInterval(state.overallTimer);
  state.overallTimer = setInterval(() => {
    if (state.paused) return;
    const e = Math.floor((Date.now() - state.sessionStartTime) / 1000);
    $("mcq-overall-timer").textContent = fmtTime(e);
  }, 500);
}
function stopOverallTimer() {
  if (state.overallTimer) { clearInterval(state.overallTimer); state.overallTimer = null; }
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function getCount() {
  if (state.countSel === 0)  return 9999;  // "All"
  if (state.countSel === -1) return Math.max(1, parseInt($("mcq-custom-n")?.value) || 40);
  return state.countSel;
}

// ── Exam paper countdown ───────────────────────────────────────────────────────
// Official Cambridge durations per MCQ component, so full-paper mode runs to
// the real clock. Anything unlisted falls back to the IGCSE 45 minutes.
const EXAM_MINS = {
  "9702-1": 75,                 // A Level Physics P1 — 1 h 15
  "5054-1": 60, "5070-1": 60,   // O Level Physics / Chemistry P1 — 1 h
  "0625-1": 45, "0625-2": 45,   // IGCSE Physics MCQ Core / Extended
  "0620-1": 45, "0620-2": 45,   // IGCSE Chemistry MCQ Core / Extended
};
function paperExamMins(syl, paper) { return EXAM_MINS[`${syl}-${paper}`] ?? 45; }

function startPaperTimer(endAt) {
  stopPaperTimer();
  const el = $("mcq-paper-time");
  if (!el) return;
  el.hidden = false;
  el.classList.remove("is-warn", "is-danger");
  state.paperTimerEnd = endAt;
  updatePaperTimer();
  state.paperTimer = setInterval(() => { if (!state.paused) updatePaperTimer(); }, 1000);
}
function updatePaperTimer() {
  const el = $("mcq-paper-time");
  if (!el || !state.paperTimerEnd) return;
  const rem = Math.max(0, Math.round((state.paperTimerEnd - Date.now()) / 1000));
  const h = Math.floor(rem / 3600);
  const m = Math.floor((rem % 3600) / 60);
  const s = rem % 60;
  const pad = n => String(n).padStart(2, "0");
  el.textContent = h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  // Classes, not inline colours — the palette differs per theme.
  el.classList.toggle("is-danger", rem === 0);
  el.classList.toggle("is-warn", rem > 0 && rem <= 300);
  if (rem === 0) {
    stopPaperTimer();
    // Booklet time is up — end it like a real paper would.
    if (!$("session-panel").hidden) {
      stopQTimer(); stopOverallTimer();
      document.removeEventListener("keydown", onKeyDown);
      endSession();
    }
  }
}
function stopPaperTimer() {
  if (state.paperTimer) { clearInterval(state.paperTimer); state.paperTimer = null; }
}

// ── Per-question ring timer ────────────────────────────────────────────────────
const CIRC = 326.7;
function startQTimer() {
  stopQTimer();
  state.qElapsed = 0; state.qStartTime = Date.now();
  $("mcq-ring-wrap").classList.remove("is-warn", "is-danger");
  if (state.timeSecs === 0) { $("mcq-ring-wrap").style.display = "none"; return; }
  $("mcq-ring-wrap").style.display = "";
  updateRing(state.timeSecs, state.timeSecs);
  state.qTimer = setInterval(() => {
    if (state.paused) return;
    state.qElapsed = Math.floor((Date.now() - state.qStartTime) / 1000);
    const rem = Math.max(0, state.timeSecs - state.qElapsed);
    updateRing(rem, state.timeSecs);
    $("mcq-ring-num").textContent = rem;
    const wrap = $("mcq-ring-wrap");
    wrap.classList.toggle("is-danger", rem <= 5);
    wrap.classList.toggle("is-warn", rem > 5 && rem <= Math.ceil(state.timeSecs * 0.3));
    if (rem === 0) { stopQTimer(); recordTimeout(); }
  }, 500);
}
function stopQTimer() {
  if (state.qTimer) { clearInterval(state.qTimer); state.qTimer = null; }
}
function updateRing(rem, total) {
  const pct = total > 0 ? rem / total : 1;
  $("mcq-ring-fill").style.strokeDashoffset = CIRC * (1 - pct);
}

// ── Load question ──────────────────────────────────────────────────────────────
function loadQuestion(index) {
  if (index >= state.questions.length) { endSession(); return; }
  state.qIndex = index;
  const q = state.questions[index];

  $("mcq-q-counter").textContent = `Q ${index + 1} / ${state.questions.length}`;
  const pFill = document.getElementById("mcq-progress-fill");
  if (pFill) pFill.style.width = `${((index + 1) / state.questions.length) * 100}%`;
  $("mcq-q-ref").textContent = q.ref;
  $("mcq-q-topic").textContent = q.topic + (q.subtopic ? ` · ${q.subtopic}` : "");

  // Reset button styles
  document.querySelectorAll(".mcq-ans-btn").forEach(b => { b.className = "mcq-ans-btn"; b.disabled = false; });

  // Load question image
  const img = $("mcq-q-img"), spinner = $("mcq-q-img-spinner"), errEl = $("mcq-q-img-error");
  img.style.display = "none"; spinner.style.display = ""; errEl.hidden = true;
  img.onload = () => { spinner.style.display = "none"; img.style.display = ""; };
  img.onerror = () => {
    spinner.style.display = "none"; errEl.hidden = false;
    $("mcq-q-text-fallback").textContent = q.text_snippet || "";
  };
  img.src = `/api/question/${q.id}/preview`;

  // Reset feedback UIs
  $("mcq-feedback-overlay").hidden = true;
  $("mcq-inline-feedback").hidden = true;
  $("mcq-explanation-panel").hidden = true;

  // Animate question card entrance
  const qCard = $("mcq-question-card");
  qCard.classList.remove("mcq-card-enter");
  void qCard.offsetWidth; // force reflow
  qCard.classList.add("mcq-card-enter");

  updateNav();
  syncFlagBtn();

  const existing = state.results[index];
  if (existing && existing.result !== "skipped") {
    // Already answered — show in review mode
    state.answered = true;
    restoreAnsweredState(existing, q);
  } else {
    // Unanswered or previously skipped — allow (re-)answering
    if (existing?.result === "skipped") state.results[index] = null;
    state.answered = false;
    startQTimer();
  }
  updateScoreLive();
  saveSession();
}

// Restore visual state for an already-answered question (review / jump-to)
function restoreAnsweredState(r, q) {
  stopQTimer();
  document.querySelectorAll(".mcq-ans-btn").forEach(b => {
    const l = b.dataset.letter; b.disabled = true;
    if (r.result !== "skipped") {
      if (q.has_answer) {
        if (l === q.answer) b.classList.add("mcq-ans-correct");
        if (l === r.yourAnswer && l !== q.answer) b.classList.add("mcq-ans-wrong");
      } else {
        if (l === r.yourAnswer) b.classList.add("mcq-ans-selected");
      }
    }
  });
  if (r.result === "skipped") return;
  if (q.has_answer) {
    showInlineFeedback(r.yourAnswer, q, r.result);
  } else {
    showMSOverlay(r.yourAnswer, q);
  }
}

function updateScoreLive() {
  const answered = state.results.filter(Boolean);
  const correct = answered.filter(r => r.result === "correct").length;
  const attempted = answered.filter(r => r.result !== "skipped").length;
  $("mcq-score-live").textContent = `${correct} / ${attempted}`;
}

// ── Answer submission ─────────────────────────────────────────────────────────
function submitAnswer(letter) {
  if (state.answered) return;
  state.answered = true; stopQTimer();
  const q = state.questions[state.qIndex];
  const timeTaken = Math.round((Date.now() - state.qStartTime) / 1000);
  let result;
  if (q.has_answer) result = letter === q.answer ? "correct" : "wrong";
  else result = "no-key";
  state.results[state.qIndex] = {
    qid: q.id, ref: q.ref, topic: q.topic,
    yourAnswer: letter, correctAnswer: q.answer, timeSecs: timeTaken, result,
  };
  // "no-key" (self-check) deliberately leaves the streak alone — we cannot
  // know yet whether the student was right.
  if (result === "correct") {
    state.streak++;
    if (state.streak > state.bestStreak) state.bestStreak = state.streak;
  } else if (result === "wrong") {
    state.streak = 0;
  }
  showAnswerFeedback(letter, q, result);
  updateScoreLive();
  updateNav();
  renderStreak();
  saveSession();
}

// The per-question ring hit zero. Not "auto-advance" — that was removed;
// this is the timeout path, which still records a skip and moves on.
function recordTimeout() {
  if (state.answered) return;
  state.answered = true;
  const q = state.questions[state.qIndex];
  const timeTaken = state.timeSecs || Math.round((Date.now() - state.qStartTime) / 1000);
  state.results[state.qIndex] = {
    qid: q.id, ref: q.ref, topic: q.topic,
    yourAnswer: null, correctAnswer: q.answer, timeSecs: timeTaken, result: "skipped",
  };
  state.streak = 0;   // running out of time breaks the run
  updateScoreLive();
  updateNav();
  renderStreak();
  saveSession();
  nextQuestion();
}

function showAnswerFeedback(letter, q, result) {
  // Colour the answer buttons
  document.querySelectorAll(".mcq-ans-btn").forEach(b => {
    const l = b.dataset.letter; b.disabled = true;
    if (q.has_answer) {
      if (l === q.answer) b.classList.add("mcq-ans-correct");
      if (l === letter && l !== q.answer) b.classList.add("mcq-ans-wrong");
    } else {
      if (l === letter) b.classList.add("mcq-ans-selected");
    }
  });

  if (q.has_answer) {
    // Inline feedback. No auto-advance: the student reads it (and optionally
    // the explanation) and presses Next when ready.
    showInlineFeedback(letter, q, result);
    // A wrong answer is exactly the moment the explanation is worth reading,
    // so don't make them ask for it.
    if (result === "wrong") openExplanation(true);
  } else {
    // No stored answer — show MS crop for self-check
    showMSOverlay(letter, q);
  }
}

function showInlineFeedback(letter, q, result) {
  const correct = result === "correct";
  const icon = correct ? "✓" : "✗";
  const colorCls = correct ? "mcq-fb-correct" : "mcq-fb-wrong";
  const resultText = correct ? "Correct!" : "Incorrect";
  let lettersHtml = letter ? `Your answer: <b>${letter}</b>` : "";
  if (q.has_answer && !correct && letter) {
    lettersHtml += ` &nbsp;&middot;&nbsp; Correct: <b class="mcq-letter-correct">${q.answer}</b>`;
  }
  $("mcq-fb-icon").textContent = icon;
  $("mcq-fb-result").textContent = resultText;
  $("mcq-fb-letters").innerHTML = lettersHtml;
  const fb = $("mcq-inline-feedback");
  fb.className = `mcq-inline-feedback ${colorCls}`;
  fb.hidden = false;
  // Next is the ONLY way forward now, so it is always shown. Hiding it here
  // (as the old auto-advance build did) would soft-lock the session.
  const nextBtn = $("mcq-fb-next-btn");
  const explainBtn = $("mcq-explain-btn");
  if (nextBtn) nextBtn.style.display = "";
  if (explainBtn) explainBtn.style.display = "";
}

function showMSOverlay(letter, q) {
  $("mcq-feedback-result").innerHTML = `<span class="mcq-result-nokey">&#x2139; Check mark scheme</span>`;
  $("mcq-feedback-letters").innerHTML = `Your answer: <strong>${letter}</strong> &nbsp;&middot;&nbsp; <em>No key stored — see MS crop below</em>`;
  const msImg = $("mcq-feedback-ms-img"), msSpin = $("mcq-feedback-ms-spinner"), msErr = $("mcq-feedback-ms-error");
  msImg.style.display = "none"; msSpin.style.display = ""; msErr.hidden = true;
  msImg.onload = () => { msSpin.style.display = "none"; msImg.style.display = ""; };
  msImg.onerror = () => { msSpin.style.display = "none"; msErr.hidden = false; };
  msImg.src = `/api/question/${q.id}/ms-preview`;
  $("mcq-feedback-overlay").hidden = false;
}

function nextQuestion() {
  $("mcq-feedback-overlay").hidden = true;
  $("mcq-inline-feedback").hidden = true;
  $("mcq-explanation-panel").hidden = true;
  loadQuestion(state.qIndex + 1);
}

// ── Question navigator ─────────────────────────────────────────────────────────
function buildNav() {
  const nav = $("mcq-q-nav");
  if (!nav) return;
  nav.innerHTML = `
    <div class="mcq-nav-tab" id="mcq-nav-tab" role="button" tabindex="0" aria-label="Question navigator">
      <span class="mcq-nav-tab-label" id="mcq-nav-tab-num">Q1</span>
      <span class="mcq-nav-tab-icon">&#9783;</span>
    </div>
    <div class="mcq-nav-panel" id="mcq-nav-panel" hidden>
      <div class="mcq-nav-legend">
        <span class="mcq-lg"><i class="mcq-nd mcq-nd-correct">&#10003;</i>Correct</span>
        <span class="mcq-lg"><i class="mcq-nd mcq-nd-wrong">&#10007;</i>Wrong</span>
        <span class="mcq-lg"><i class="mcq-nd mcq-nd-skipped">&ndash;</i>Skipped</span>
        <span class="mcq-lg"><i class="mcq-nd mcq-nd-now">&bull;</i>Now</span>
        <span class="mcq-lg"><i class="mcq-nd mcq-nd-blank mcq-nd-flagged">&#x2691;</i>Flagged</span>
      </div>
      <div class="mcq-nav-dots" id="mcq-nav-dots"></div>
    </div>`;
  const tab = $("mcq-nav-tab");
  tab.onclick = toggleNav;
  tab.onkeydown = e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleNav(); }
  };
  updateNav();
}

function updateNav() {
  const dotsEl = $("mcq-nav-dots");
  const tabNum = $("mcq-nav-tab-num");
  if (!dotsEl) return;
  if (tabNum) tabNum.textContent = `Q${state.qIndex + 1}`;
  dotsEl.innerHTML = "";
  state.questions.forEach((q, i) => {
    const r = state.results[i];
    let cls = "mcq-nd";
    if (i === state.qIndex) cls += " mcq-nd-now";
    else if (!r) cls += " mcq-nd-blank";
    else if (r.result === "correct") cls += " mcq-nd-correct";
    else if (r.result === "wrong") cls += " mcq-nd-wrong";
    else cls += " mcq-nd-skipped";
    if (state.flags[i]) cls += " mcq-nd-flagged";
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = cls; btn.textContent = i + 1;
    btn.title = `Q${i + 1}: ${q.ref}` + (state.flags[i] ? " (flagged)" : "");
    btn.onclick = () => jumpToQuestion(i);
    dotsEl.appendChild(btn);
  });
}

function toggleNav() {
  state.navOpen = !state.navOpen;
  const panel = $("mcq-nav-panel");
  if (panel) panel.hidden = !state.navOpen;
  const nav = $("mcq-q-nav");
  if (nav) nav.classList.toggle("mcq-nav-open", state.navOpen);
}

function jumpToQuestion(index) {
  if (index < 0 || index >= state.questions.length) return;
  loadQuestion(index);
}

// ── Flag for review ───────────────────────────────────────────────────────────
function toggleFlag(i = state.qIndex) {
  if (i < 0 || i >= state.questions.length) return;
  state.flags[i] = !state.flags[i];
  syncFlagBtn(); updateNav(); saveSession();
}
function syncFlagBtn() {
  const b = $("mcq-flag-btn");
  if (!b) return;
  const on = !!state.flags[state.qIndex];
  b.classList.toggle("is-flagged", on);
  b.setAttribute("aria-pressed", String(on));
  b.title = on ? "Unflag (F)" : "Flag for review (F)";
}

// ── Streak ────────────────────────────────────────────────────────────────────
function renderStreak() {
  const el = $("mcq-streak");
  if (!el) return;
  const n = state.streak;
  el.hidden = n < 2;            // don't nag at 0 or 1
  if (n < 2) return;
  $("mcq-streak-n").textContent = n;
  el.classList.toggle("is-hot", n >= 5);
  el.classList.remove("is-pop"); void el.offsetWidth; el.classList.add("is-pop");
}

// ── Theme ─────────────────────────────────────────────────────────────────────
// The head script already resolved the initial value onto <html>; this only
// reflects it onto the button and handles the toggle. Theme is a device
// preference, so it deliberately does NOT go into the session snapshot.
const THEME_KEY = "pwt_mcq_theme";
function currentTheme() {
  return document.documentElement.getAttribute("data-mcq-theme") === "light" ? "light" : "dark";
}
function setTheme(t) {
  document.documentElement.setAttribute("data-mcq-theme", t);
  try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
  syncThemeBtn();
}
function syncThemeBtn() {
  const b = $("mcq-theme-toggle");
  if (!b) return;
  const light = currentTheme() === "light";
  b.setAttribute("aria-pressed", String(light));
  b.title = light ? "Switch to dark (T)" : "Switch to light (T)";
}
function toggleTheme() { setTheme(currentTheme() === "light" ? "dark" : "light"); }

// ── Controls ──────────────────────────────────────────────────────────────────
$("mcq-skip-btn").onclick = () => {
  if (state.answered) { nextQuestion(); return; }
  recordTimeout();
};
$("mcq-next-btn").onclick = nextQuestion;
$("mcq-fb-next-btn").onclick = nextQuestion;
$("mcq-flag-btn").onclick = () => toggleFlag();
$("mcq-theme-toggle").onclick = toggleTheme;
syncThemeBtn();
document.querySelectorAll(".mcq-ans-btn").forEach(btn => {
  btn.onclick = () => { if (state.answered || state.paused) return; submitAnswer(btn.dataset.letter); };
});

// ── AI Explanation ────────────────────────────────────────────────────────────
const explanationCache = new Map();

async function fetchExplanation(qid, yourAnswer, correctAnswer, topic) {
  if (explanationCache.has(qid)) return explanationCache.get(qid);
  const body = {
    question_id: qid,
    your_answer: yourAnswer || null,
    correct_answer: correctAnswer || null,
    syllabus: state.syllabus || null,
    topic: topic || null,
  };
  const data = await api("/api/mcq/explain", { method: "POST", body });
  // Never cache a cut-short worked solution — caching it would make "Explain"
  // replay the same broken answer forever.
  if (!data.truncated) explanationCache.set(qid, data.html);
  return data.html;
}

async function openExplanation(auto = false) {
  const q = state.questions[state.qIndex];
  if (!q) return;
  const r = state.results[state.qIndex];
  const panel = $("mcq-explanation-panel");
  const loading = $("mcq-explanation-loading");
  const content = $("mcq-explanation-content");
  const badge = $("mcq-explanation-auto");

  if (badge) badge.hidden = !auto;
  panel.hidden = false;
  loading.style.display = "";
  content.innerHTML = "";

  // Explanations now fire on their own for wrong answers, and the arrow keys
  // make it easy to move on before one lands. Pin the request to the question
  // that asked for it so a late reply can't paint over a different question.
  const forQ = state.qIndex;
  try {
    const html = await fetchExplanation(q.id, r?.yourAnswer, q.answer, q.topic);
    if (state.qIndex !== forQ) return;
    content.innerHTML = html;
  } catch (err) {
    if (state.qIndex !== forQ) return;
    content.innerHTML = `<p class="mcq-explain-err">Could not load explanation: ${esc(err.message)}</p>`;
  } finally {
    if (state.qIndex === forQ) loading.style.display = "none";
  }
}

$("mcq-explain-btn").onclick = () => {
  const panel = $("mcq-explanation-panel");
  if (!panel.hidden) { panel.hidden = true; return; }   // toggle off
  openExplanation(false);
};
$("mcq-explanation-close").onclick = () => {
  $("mcq-explanation-panel").hidden = true;
};

function onKeyDown(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (document.getElementById("session-panel").hidden) return;
  if (state.paused && e.key !== " ") return;   // paused = nothing but resume
  switch(e.key.toUpperCase()) {
    case "A": case "B": case "C": case "D":
      if (!state.answered) submitAnswer(e.key.toUpperCase()); break;
    // Right = "move on", whatever that means here: Next if the question is
    // answered, Skip if it isn't. Left = back a question.
    case "ARROWRIGHT": case "ENTER":
      e.preventDefault();
      if (state.answered) nextQuestion(); else recordTimeout();
      break;
    case "ARROWLEFT":
      e.preventDefault(); prevQuestion(); break;
    case "F": e.preventDefault(); toggleFlag(); break;
    case "T": e.preventDefault(); toggleTheme(); break;
    case " ": e.preventDefault(); togglePause(); break;
  }
}

function prevQuestion() {
  if (state.qIndex > 0) jumpToQuestion(state.qIndex - 1);
}

// What the student actually wants to know while paused: how far in they are,
// how they're doing, and how much booklet time is left.
function renderPauseStats() {
  const total = state.questions.length;
  const answered = state.results.filter(Boolean);
  const done = answered.length;
  const correct = answered.filter(r => r.result === "correct").length;
  const elapsed = Math.floor((Date.now() - state.sessionStartTime) / 1000);

  $("mcq-pause-done").textContent = `${done}/${total}`;
  $("mcq-pause-correct").textContent = correct;
  $("mcq-pause-elapsed").textContent = fmtTime(elapsed);
  $("mcq-pause-left").textContent = state.paperTimerEnd
    ? fmtTime(Math.max(0, Math.round((state.paperTimerEnd - Date.now()) / 1000)))
    : "∞";   // no limit

  const pct = total ? Math.round(done / total * 100) : 0;
  $("mcq-pause-bar-fill").style.width = `${pct}%`;
  $("mcq-pause-progress").textContent = done === total
    ? "Every question answered — finish up when you're ready."
    : `${done} of ${total} answered · ${total - done} to go`;
}

$("mcq-pause-btn").onclick = $("mcq-resume-btn").onclick = togglePause;
function togglePause() {
  state.paused = !state.paused;
  $("mcq-pause-overlay").hidden = !state.paused;
  if (state.paused) { state.pauseStart = Date.now(); renderPauseStats(); }
  else {
    const d = Date.now() - state.pauseStart;
    state.sessionStartTime += d; state.qStartTime += d;
    if (state.paperTimerEnd) state.paperTimerEnd += d;
  }
  saveSession();
}

$("mcq-quit-btn").onclick = () => {
  if (confirm("End this session and see your results?")) {
    stopQTimer(); stopOverallTimer();
    document.removeEventListener("keydown", onKeyDown);
    endSession();
  }
};

// ── End session → Results ──────────────────────────────────────────────────────
function endSession() {
  stopQTimer(); stopOverallTimer(); stopPaperTimer();
  document.removeEventListener("keydown", onKeyDown);
  document.body.classList.remove("mcq-in-session");
  clearSaved();   // the session is over — nothing left to resume
  const ptEl = $("mcq-paper-time");
  if (ptEl) {
    ptEl.hidden = true; ptEl.textContent = "";
    ptEl.classList.remove("is-warn", "is-danger");
  }
  const totalSecs = Math.round((Date.now() - state.sessionStartTime) / 1000);
  const answered = state.results.filter(Boolean);
  const correct  = answered.filter(r => r.result === "correct").length;
  const wrong    = answered.filter(r => r.result === "wrong").length;
  const skipped  = answered.filter(r => r.result === "skipped").length;
  const attempted = answered.filter(r => r.result !== "skipped").length;
  const pct = attempted > 0 ? Math.round(correct / attempted * 100) : 0;
  const avgTime = answered.length > 0
    ? Math.round(answered.reduce((s, r) => s + r.timeSecs, 0) / answered.length) : 0;

  $("res-score").textContent = correct;
  $("res-total").textContent = attempted || answered.length;
  $("res-correct").textContent = correct;
  $("res-wrong").textContent = wrong;
  $("res-skipped").textContent = skipped;
  $("res-time").textContent = fmtTime(totalSecs);
  $("res-avg-time").textContent = `${avgTime} s`;
  $("res-pct").textContent = `${pct}%`;

  const msg = pct >= 90 ? "🏆 Outstanding! Cambridge-exam ready."
    : pct >= 75 ? "🎉 Great score! A few more sessions and you'll ace it."
    : pct >= 60 ? "📈 Solid effort. Revisit the topics you struggled on."
    : pct >= 40 ? "💪 Keep going — every session builds your speed and confidence."
    : "📚 Review those chapters carefully and try again!";
  $("res-message").textContent = msg;
  $("res-headline").textContent = answered.length === 0 ? "Session ended" : "Session complete!";

  // Animate score ring
  const fill = $("mcq-results-ring"), circ = 427.3;
  setTimeout(() => {
    fill.style.transition = "stroke-dashoffset 1.2s cubic-bezier(.22,.61,.36,1)";
    fill.style.stroke = pct >= 75 ? "var(--green-ink,#16704A)" : pct >= 50 ? "#E8913A" : "var(--pink-ink,#B0326E)";
    fill.style.strokeDashoffset = circ * (1 - pct / 100);
  }, 200);

  renderResultsGrid();
  renderResultsTable("all");
  document.querySelectorAll("[data-res-filter]").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll("[data-res-filter]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      renderResultsTable(btn.dataset.resFilter);
    };
  });

  $("res-retry-btn").onclick = () => {
    state.results = []; state.flags = [];
    state.streak = 0; state.bestStreak = 0;
    clearSaved();
    showPanel("setup-panel");
    document.removeEventListener("keydown", onKeyDown);
  };
  if (state.lastBody && state.mode === "topic" && state.lastBody.topics?.length) {
    const p = new URLSearchParams({ syllabus: state.lastBody.syllabus, topics: state.lastBody.topics.join(",") });
    $("res-pdf-btn").href = `papers.html?${p}`;
  }
  showPanel("results-panel");

  // Offer to save score if the student just finished a full past paper.
  if (state.mode === "paper" && state.fpSel) {
    openSaveModal(correct, attempted || answered.length);
  }
}

// ── Save score dialog ─────────────────────────────────────────────────────────
function openSaveModal(correct, total) {
  const sel = state.fpSel;
  if (!sel) return;
  const pct = total > 0 ? Math.round(correct / total * 100) : 0;
  $("mcq-save-desc").textContent = sel.label;
  $("mcq-save-score").textContent = `${correct} / ${total}`;
  $("mcq-save-pct").textContent = `${pct}% correct`;
  $("mcq-save-status").textContent = "";
  $("mcq-save-yes").disabled = false;
  $("mcq-save-yes").textContent = "Save & mark done";
  $("mcq-save-modal").hidden = false;

  $("mcq-save-no").onclick = () => { $("mcq-save-modal").hidden = true; };
  $("mcq-save-yes").onclick = async () => {
    const enrolled = state.enrolledSyllabuses || [];
    if (state.meta && enrolled.length > 0 && !enrolled.includes(state.syllabus)) {
      openEnrollGatingModal(state.syllabus, () => {
        // Enrolled successfully! Add to locally checked active list
        state.enrolledSyllabuses = [...enrolled, state.syllabus];
        // Trigger the save action again!
        $("mcq-save-yes").click();
      });
      return;
    }

    $("mcq-save-yes").disabled = true;
    $("mcq-save-yes").textContent = "Saving…";
    $("mcq-save-status").textContent = "";
    try {
      await api("/api/paper-progress", {
        method: "POST",
        body: {
          syllabus: state.syllabus,
          year: sel.year,
          session: sel.session,
          paper: sel.paper,
          variant: String(sel.variant),
          status: "confident",
          score: correct,
          max_score: total,
        },
      });
      $("mcq-save-yes").textContent = "Saved ✓";
      $("mcq-save-status").textContent = "Marked as done on your dashboard.";
    } catch (err) {
      $("mcq-save-yes").disabled = false;
      $("mcq-save-yes").textContent = "Save & mark done";
      $("mcq-save-status").textContent = "Could not save: " + err.message;
    }
  };
}

// ── Review PDF download ───────────────────────────────────────────────────────
//
// Every question in the session goes into the booklet, whether it was answered
// or not: an unanswered question is still one the student wants the worked
// solution for. The backend re-reads the reference, topic and mark-scheme
// answer from the database, so all we send is which question and what they
// picked.
//
// Filling in the missing explanations is a run of AI calls, far too slow to
// hold a request open for, so this drives a job: POST once, poll, download.
const dlState = { jobId: null, timer: null, url: null };

function dlItems() {
  return state.questions.map((q, i) => ({
    question_id: q.id,
    your_answer: state.results[i]?.yourAnswer || null,
    time_secs: state.results[i]?.timeSecs ?? null,
  }));
}

function dlSessionTitle() {
  const sub = state.meta?.subjects?.find(s => s.syllabus === state.syllabus);
  const name = sub ? (sub.short || sub.subject) : (state.syllabus || "MCQ");
  if (state.mode === "paper" && state.fpSel) return `${name} · ${state.fpSel.label}`;
  const topics = state.lastBody?.topics || [];
  if (topics.length === 1) return `${name} · ${topics[0]}`;
  if (topics.length > 1) return `${name} · ${topics.length} topics`;
  return `${name} · MCQ practice`;
}

function fmtEta(secs) {
  if (secs < 15) return "a few seconds";
  if (secs < 60) return `${Math.round(secs / 5) * 5} seconds`;
  const m = Math.round(secs / 60);
  return m === 1 ? "a minute" : `${m} minutes`;
}

function dlShowStep(step) {
  $("mcq-dl-setup").hidden = step !== "setup";
  $("mcq-dl-progress").hidden = step !== "progress";
  $("mcq-dl-done").hidden = step !== "done";
}

function dlError(msg) {
  const el = $("mcq-dl-err");
  el.textContent = msg;
  el.hidden = false;
  dlShowStep("setup");
}

// Worst case: every worked solution has to be written from scratch. Three run
// at once at ~8 s each, plus a fixed ~10 s for the queries, crops and render.
// Anything already stored comes back instantly, so the real wait is usually
// well under this — hence "up to".
const DL_SECS_EACH = 3, DL_SECS_FIXED = 10;

function dlEstimate(n) {
  return `up to about ${fmtEta(DL_SECS_FIXED + n * DL_SECS_EACH)}`;
}

function openDownloadModal() {
  const total = state.questions.length;
  const needed = state.results.filter(
    r => !r || (r.result !== "correct" && r.result !== "no-key")).length;
  $("mcq-dl-sub").textContent =
    `${total} question${total === 1 ? "" : "s"} · ${dlSessionTitle()}`;
  $("mcq-dl-n-wrong").textContent =
    `${needed} question${needed === 1 ? "" : "s"} — wrong, skipped or unanswered `
    + `· ${dlEstimate(needed)}`;
  $("mcq-dl-n-all").textContent =
    `all ${total} — the most complete booklet · ${dlEstimate(total)}`;
  $("mcq-dl-err").hidden = true;
  dlShowStep("setup");
  $("mcq-dl-modal").hidden = false;
}

function closeDownloadModal() {
  clearTimeout(dlState.timer);
  dlState.timer = null;
  $("mcq-dl-modal").hidden = true;
}

async function dlStart() {
  const scope = document.querySelector("input[name='mcq-dl-scope']:checked")?.value || "wrong";
  $("mcq-dl-err").hidden = true;
  dlShowStep("progress");
  $("mcq-dl-phase").textContent = "Starting…";
  $("mcq-dl-bar-fill").style.width = "4%";
  $("mcq-dl-count").textContent = "";

  let data;
  try {
    data = await api("/api/mcq/report", {
      method: "POST",
      body: {
        items: dlItems(),
        syllabus: state.syllabus,
        title: dlSessionTitle(),
        subtitle: state.mode === "paper" ? "Full past paper" : "Topic practice",
        time_label: $("res-time").textContent,
        explain: scope,
      },
      // Building the item list is cheap, but the server writes the job to disk
      // before replying; a slow disk should not read as a failure.
      timeout: 30000,
    });
  } catch (err) {
    return dlError(err.message);
  }
  dlState.jobId = data.job_id;
  dlPoll();
}

async function dlPoll() {
  if (!dlState.jobId) return;
  let st;
  try { st = await api(`/api/mcq/report/${encodeURIComponent(dlState.jobId)}`); }
  catch (err) { return dlError(err.message); }

  if (st.state === "error") return dlError(st.error || "The build failed — please try again.");

  if (st.state === "done" && st.ready) {
    dlState.url = `/api/mcq/report/${encodeURIComponent(dlState.jobId)}/pdf`;
    $("mcq-dl-bar-fill").style.width = "100%";
    $("mcq-dl-link").href = dlState.url;
    dlShowStep("done");
    // Navigating a hidden iframe rather than the tab: a Content-Disposition
    // attachment downloads either way, but an iframe cannot navigate the page
    // away from the results if anything about the response is unexpected.
    let frame = document.getElementById("mcq-dl-frame");
    if (!frame) {
      frame = document.createElement("iframe");
      frame.id = "mcq-dl-frame";
      frame.style.display = "none";
      document.body.appendChild(frame);
    }
    frame.src = dlState.url;
    return;
  }

  const PHASES = {
    starting:     ["Checking what's already written", 2],
    explanations: ["Writing worked solutions", 70],
    images:       ["Collecting question images", 12],
    pdf:          ["Building your booklet", 16],
    working:      ["Working", 2],
  };
  const [label, weight] = PHASES[st.phase] || PHASES.working;
  const total = st.total || 0, done = st.done || 0;
  $("mcq-dl-phase").textContent = label + "…";

  // Count and remaining time on one line, so the student can see it is moving
  // even while `done` sits on a slow question.
  const bits = [];
  if (total) bits.push(`${done} of ${total}`);
  if (st.eta_s > 0) bits.push(`about ${fmtEta(st.eta_s)} left`);
  $("mcq-dl-count").textContent = bits.join(" · ");

  // Each phase owns a slice of the bar sized by how long it really takes, so
  // the bar tracks elapsed time rather than jumping. Never sits at 0 — a still
  // bar reads as stuck.
  let base = 0;
  for (const key of ["starting", "explanations", "images", "pdf"]) {
    if (key === st.phase) break;
    base += PHASES[key][1];
  }
  const frac = total ? done / total : 0;
  const pct = base + weight * frac;
  $("mcq-dl-bar-fill").style.width = `${Math.max(4, Math.min(100, pct))}%`;

  dlState.timer = setTimeout(dlPoll, 1500);
}

$("res-download-btn").onclick = openDownloadModal;
$("mcq-dl-start").onclick = dlStart;
$("mcq-dl-close").onclick = closeDownloadModal;
$("mcq-dl-cancel").onclick = closeDownloadModal;
$("mcq-dl-finish").onclick = closeDownloadModal;
$("mcq-dl-abandon").onclick = () => {
  // The job keeps building server-side; this only stops us watching it.
  clearTimeout(dlState.timer);
  dlState.timer = null;
  dlShowStep("setup");
};
$("mcq-dl-modal").addEventListener("click", e => {
  if (e.target === $("mcq-dl-modal")) closeDownloadModal();
});

function renderResultsGrid() {
  const grid = $("mcq-results-q-grid");
  if (!grid) return;
  grid.innerHTML = "";
  state.results.forEach((r, i) => {
    const cls = !r ? "mcq-nd-blank"
      : r.result === "correct" ? "mcq-nd-correct"
      : r.result === "wrong"   ? "mcq-nd-wrong"
      : r.result === "no-key"  ? "mcq-nd-nokey"
      : "mcq-nd-skipped";
    const flagged = state.flags?.[i];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `mcq-nd mcq-nd-lg ${cls}${flagged ? " mcq-nd-flag" : ""}`;
    btn.textContent = i + 1;
    btn.title = (r ? `Q${i + 1}: ${r.result}` : `Q${i + 1}: not answered`)
      + (flagged ? " (flagged)" : "");
    btn.onclick = () => {
      // Jump back into session panel in review mode
      showPanel("session-panel");
      buildNav();
      jumpToQuestion(i);
    };
    grid.appendChild(btn);
  });
}

function renderResultsTable(filter) {
  const tbody = $("mcq-results-tbody"); tbody.innerHTML = "";
  state.results.forEach((r, i) => {
    if (!r) return; // never reached (unanswered)
    if (filter !== "all" && r.result !== filter) return;
    const tr = document.createElement("tr"); tr.dataset.result = r.result;
    const badge = r.result === "correct"
      ? `<span class="mcq-badge-correct">&#x2713; Correct</span>`
      : r.result === "wrong"
      ? `<span class="mcq-badge-wrong">&#x2717; Wrong</span>`
      : r.result === "no-key"
      ? `<span class="mcq-badge-nokey">&#x2139; Self-check</span>`
      : `<span class="mcq-badge-skipped">&mdash; Skipped</span>`;
    const yourAns = r.yourAnswer
      ? `<strong class="${r.result==="correct"?"mcq-letter-correct":r.result==="wrong"?"mcq-letter-wrong":""}">${r.yourAnswer}</strong>`
      : `<em>&mdash;</em>`;
    const corrAns = r.correctAnswer
      ? `<strong class="mcq-letter-correct">${r.correctAnswer}</strong>`
      : `<em>N/A</em>`;
    tr.innerHTML = `<td>${i + 1}</td><td class="mcq-td-ref">${esc(r.ref)}</td><td class="mcq-td-topic">${esc(r.topic)}</td><td class="mcq-td-ans">${yourAns}</td><td class="mcq-td-ans">${corrAns}</td><td>${r.timeSecs} s</td><td>${badge}</td>`;
    tbody.appendChild(tr);
  });
  if (!tbody.children.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="7" class="mcq-td-empty">No questions in this category.</td>`;
    tbody.appendChild(tr);
  }
}

function openEnrollGatingModal(syllabus, onEnrollSuccess) {
  const sub = state.meta?.subjects?.find(s => s.syllabus === syllabus) || { subject: syllabus, syllabus: syllabus };
  const subjectLabel = sub.short || sub.subject || syllabus;
  const displayName = `${subjectLabel} (${syllabus})`;

  $("mcq-enroll-gate-message").textContent = `You're not currently enrolled in [${displayName}], so this score can't be saved to your dashboard. Enroll in this subject to track your progress here.`;
  $("mcq-enroll-gate-status").textContent = "";
  $("mcq-enroll-gate-yes").disabled = false;
  $("mcq-enroll-gate-yes").textContent = "Enroll now";
  $("mcq-enroll-gate-modal").hidden = false;

  $("mcq-enroll-gate-no").onclick = () => {
    $("mcq-enroll-gate-modal").hidden = true;
    $("mcq-save-yes").disabled = false;
    $("mcq-save-yes").textContent = "Save & mark done";
  };

  $("mcq-enroll-gate-yes").onclick = async () => {
    $("mcq-enroll-gate-yes").disabled = true;
    $("mcq-enroll-gate-yes").textContent = "Enrolling…";
    $("mcq-enroll-gate-status").textContent = "";
    try {
      await api("/api/enrollments", {
        method: "POST",
        body: { syllabus: syllabus }
      });
      $("mcq-enroll-gate-modal").hidden = true;
      if (onEnrollSuccess) onEnrollSuccess();
    } catch (err) {
      $("mcq-enroll-gate-yes").disabled = false;
      $("mcq-enroll-gate-yes").textContent = "Enroll now";
      $("mcq-enroll-gate-status").textContent = "Could not enroll: " + err.message;
    }
  };
}
