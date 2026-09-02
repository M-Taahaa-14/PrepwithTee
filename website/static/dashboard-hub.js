/* dashboard-hub.js — PrepWithTee Student Productivity Hub
   Gamification: XP/levels, daily missions, Pomodoro focus timer,
   exam countdowns, activity heatmap, achievement badges, insights.
   All state lives in localStorage under 'pwt_*' keys.
*/

import { requireProfile, api } from "/auth.js";

// ── Quotes ───────────────────────────────────────────────────────────────────

const QUOTES = [
  "Small daily improvements lead to stunning results.",
  "Every expert was once a beginner. Keep going.",
  "The secret of getting ahead is getting started.",
  "Consistency beats perfection every single time.",
  "You don't have to be great to start, but start to be great.",
  "Study hard, stay humble, and trust the process.",
  "One chapter a day keeps exam panic away.",
  "Your future self is watching — make them proud today.",
  "The pain of studying is temporary. Regret lasts forever.",
  "Excellence is not a destination. It's a daily habit.",
  "Be the student your future self would thank.",
  "The difference between try and triumph is a little umph.",
  "Hard work beats talent when talent doesn't work hard.",
  "Every mark you earn in revision, you earn twice in the exam.",
];

// ── Levels ───────────────────────────────────────────────────────────────────

const LEVELS = [
  { n: 1,  label: "Rookie",             min: 0     },
  { n: 2,  label: "Beginner",           min: 60    },
  { n: 3,  label: "Learner",            min: 150   },
  { n: 4,  label: "Student",            min: 300   },
  { n: 5,  label: "Consistent Learner", min: 500   },
  { n: 6,  label: "Committed",          min: 750   },
  { n: 7,  label: "Scholar",            min: 1100  },
  { n: 8,  label: "Advanced Scholar",   min: 1600  },
  { n: 9,  label: "Expert",             min: 2300  },
  { n: 10, label: "Master Scholar",     min: 3200  },
  { n: 15, label: "Top Performer",      min: 6000  },
  { n: 20, label: "Elite Examiner",     min: 12000 },
];

// ── Mission pool ─────────────────────────────────────────────────────────────

const MISSION_POOL = [
  { text: "Open AI Tutor and ask one concept", sub: "Get it explained clearly", xp: 15, href: "tutor.html" },
  { text: "Complete a 25-minute focus session", sub: "Use the Focus Timer right here", xp: 40, href: null },
  { text: "Revise one chapter in progress tracker", sub: "Track your understanding", xp: 20, href: "topical-progress.html" },
  { text: "Build a topical past paper", sub: "Real Cambridge questions by chapter", xp: 35, href: "papers.html" },
  { text: "Practice 10 MCQs timed", sub: "A/B/C/D with instant feedback", xp: 25, href: "mcq-solver.html" },
  { text: "Read one set of study notes", sub: "Take your time with it", xp: 15, href: "resources.html" },
  { text: "Check your homework list", sub: "Clear whatever's pending", xp: 10, href: "homework.html" },
  { text: "Message your tutor a progress update", sub: "Stay connected", xp: 15, href: "messages.html" },
  { text: "Look up 5 key definitions", sub: "Key terms matter in exams", xp: 12, href: "definitions.html" },
  { text: "Review your formula sheet", sub: "5 minutes, huge payoff", xp: 12, href: "formulas.html" },
  { text: "Plot a graph or function", sub: "Visualise the maths", xp: 15, href: "graph.html" },
  { text: "Try the Pseudocode Runner", sub: "Write and run pseudocode", xp: 18, href: "pseudocode.html" },
];

// ── Badges ───────────────────────────────────────────────────────────────────

const BADGES = [
  { id: "first_session", ico: "🎯", name: "First Step",     desc: "Opened the hub for the first time"   },
  { id: "streak_3",      ico: "🔥", name: "3-Day Fire",     desc: "Maintained a 3-day study streak"     },
  { id: "streak_7",      ico: "⚡", name: "7-Day Spark",    desc: "Maintained a 7-day study streak"     },
  { id: "streak_30",     ico: "💎", name: "Diamond Mind",   desc: "Maintained a 30-day study streak"    },
  { id: "mission_5",     ico: "✅", name: "On A Mission",   desc: "Completed 5 daily missions"          },
  { id: "mission_20",    ico: "🏅", name: "Mission Mode",   desc: "Completed 20 daily missions"         },
  { id: "focus_3",       ico: "🍅", name: "Deep Worker",    desc: "Completed 3 Pomodoro focus sessions" },
  { id: "focus_10",      ico: "🧘", name: "Flow State",     desc: "Completed 10 focus sessions"        },
  { id: "xp_100",        ico: "🌟", name: "Rising Star",    desc: "Earned 100 XP"                       },
  { id: "xp_500",        ico: "🏆", name: "High Achiever",  desc: "Earned 500 XP"                       },
  { id: "xp_1000",       ico: "👑", name: "Champion",       desc: "Earned 1,000 XP"                     },
  { id: "level_5",       ico: "📚", name: "Scholar",        desc: "Reached Level 5"                     },
];

// ── localStorage helpers ──────────────────────────────────────────────────────

const K = {
  XP:       "pwt_xp_total",
  XP_LOG:   "pwt_xp_log",
  MISSIONS: "pwt_missions",
  FOCUS:    "pwt_focus",
  EXAMS:    "pwt_exams",
  BADGES:   "pwt_badges",
};

function ls(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
  catch { return fallback; }
}
function lsSet(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch {} }

const today = () => new Date().toISOString().slice(0, 10);

function fmt(secs) {
  return `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
}

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── State ─────────────────────────────────────────────────────────────────────

let badgesEarned = new Set();
let currentStreak = 0;

// Focus timer
const FOCUS_WORK  = 25 * 60;
const FOCUS_BREAK = 5 * 60;
let focusSecondsLeft = FOCUS_WORK;
let focusIsBreak = false;
let focusInterval = null;
let focusSessionsToday = 0;

// ── Toast ─────────────────────────────────────────────────────────────────────

let toastTimer = null;
function showToast(msg) {
  let el = document.getElementById("hub-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "hub-toast";
    el.className = "hub-toast";
    document.body.appendChild(el);
  }
  el.innerHTML = `<span>⚡</span> ${msg}`;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
}

// ── XP & Levels ──────────────────────────────────────────────────────────────

function getXP() { return ls(K.XP, 0); }

// ── Server sync (debounced) ───────────────────────────────────────────────────

let _syncTimer = null;
function _scheduleSync() {
  if (_syncTimer) clearTimeout(_syncTimer);
  _syncTimer = setTimeout(_doSync, 2500);
}
async function _doSync() {
  try {
    await api("/api/stats", {
      method: "POST",
      body: {
        xp_total:   getXP(),
        xp_log:     ls(K.XP_LOG, []),
        streak:     currentStreak,
        streak_max: JSON.parse(localStorage.getItem("pwt_streak_max") || "0"),
        badges:     [...badgesEarned],
        focus:      ls(K.FOCUS, {}),
        missions:   ls(K.MISSIONS, {}),
      },
    });
  } catch { /* non-fatal */ }
}

function addXP(amount, reason = "") {
  const xp = getXP() + amount;
  lsSet(K.XP, xp);

  const log = ls(K.XP_LOG, []);
  const t = today();
  const idx = log.findIndex(e => e.date === t);
  if (idx >= 0) log[idx].xp += amount; else log.push({ date: t, xp: amount });
  lsSet(K.XP_LOG, log.slice(-90));

  updateXPDisplay();
  checkBadges();
  showToast(`+${amount} XP${reason ? "  ·  " + reason.slice(0, 22) : ""}`);
  _scheduleSync();
}

function levelForXP(xp) {
  let lv = LEVELS[0];
  for (const l of LEVELS) { if (xp >= l.min) lv = l; else break; }
  return lv;
}
function nextLevelForXP(xp) {
  for (const l of LEVELS) { if (xp < l.min) return l; }
  return null;
}

function updateXPDisplay() {
  const xp = getXP();
  const lv  = levelForXP(xp);
  const nxt = nextLevelForXP(xp);

  const chip  = document.getElementById("hub-level-chip");
  const fill  = document.getElementById("hub-xp-fill");
  const label = document.getElementById("hub-xp-text");

  if (chip)  chip.textContent  = `Lv ${lv.n} · ${lv.label}`;
  if (fill)  fill.style.width  = nxt
    ? ((xp - lv.min) / (nxt.min - lv.min) * 100).toFixed(1) + "%"
    : "100%";
  if (label) label.textContent = nxt ? `${xp} / ${nxt.min} XP` : `${xp} XP · Max Level`;

  // XP-this-month pill
  const log = ls(K.XP_LOG, []);
  const monthPrefix = new Date().toISOString().slice(0, 7); // "YYYY-MM"
  const monthXP = log.filter(e => e.date.startsWith(monthPrefix)).reduce((s, e) => s + e.xp, 0);
  const el = document.getElementById("hub-xp-today");
  if (el) el.textContent = monthXP;
}

// ── Badges ────────────────────────────────────────────────────────────────────

function checkBadges() {
  const xp = getXP();
  const focus = ls(K.FOCUS, {});
  const totalFocus = focus.total_sessions || 0;
  const missionsData = ls(K.MISSIONS, {});
  const allDone = Object.values(missionsData).flatMap(d => d?.items || []).filter(m => m.done).length;

  const triggers = [
    { id: "first_session", cond: true            },
    { id: "streak_3",      cond: currentStreak >= 3   },
    { id: "streak_7",      cond: currentStreak >= 7   },
    { id: "streak_30",     cond: currentStreak >= 30  },
    { id: "mission_5",     cond: allDone >= 5          },
    { id: "mission_20",    cond: allDone >= 20         },
    { id: "focus_3",       cond: totalFocus >= 3       },
    { id: "focus_10",      cond: totalFocus >= 10      },
    { id: "xp_100",        cond: xp >= 100             },
    { id: "xp_500",        cond: xp >= 500             },
    { id: "xp_1000",       cond: xp >= 1000            },
    { id: "level_5",       cond: levelForXP(xp).n >= 5 },
  ];

  const newlyEarned = [];
  for (const t of triggers) {
    if (t.cond && !badgesEarned.has(t.id)) {
      badgesEarned.add(t.id); newlyEarned.push(t.id);
    }
  }
  if (newlyEarned.length) {
    lsSet(K.BADGES, [...badgesEarned]);
    _scheduleSync();
    renderBadges(newlyEarned);
    const b = BADGES.find(b => b.id === newlyEarned[0]);
    if (b) showToast(`${b.ico} Badge unlocked: ${b.name}!`);
  }
}

function renderBadges(newlyEarned = []) {
  const box = document.getElementById("hub-badges-grid");
  if (!box) return;
  box.innerHTML = BADGES.map(b => {
    const earned = badgesEarned.has(b.id);
    const isNew  = newlyEarned.includes(b.id);
    return `<div class="hub-badge${earned ? " earned" : ""}${isNew ? " just-earned" : ""}" title="${b.desc}">
      <span class="hub-badge-ico">${b.ico}</span>
      <span class="hub-badge-name">${b.name}</span>
    </div>`;
  }).join("");
}

// ── Daily Missions ────────────────────────────────────────────────────────────

function getDailyMissions() {
  const stored = ls(K.MISSIONS, {});
  const t = today();
  if (stored[t]) return stored[t].items;

  // Rotate pool by day-of-year for variety
  const day = Math.floor((Date.now() - Date.UTC(new Date().getUTCFullYear(), 0, 0)) / 86400000);
  const offset = day % MISSION_POOL.length;
  const rotated = [...MISSION_POOL.slice(offset), ...MISSION_POOL.slice(0, offset)];
  const items = rotated.slice(0, 4).map((m, i) => ({ ...m, id: i, done: false }));

  // Prune old dates; keep only this week
  const fresh = {};
  for (const [k, v] of Object.entries(stored)) {
    const age = (Date.now() - new Date(k).getTime()) / 86400000;
    if (age < 8) fresh[k] = v;
  }
  fresh[t] = { items };
  lsSet(K.MISSIONS, fresh);
  return items;
}

function saveMissions(items) {
  const stored = ls(K.MISSIONS, {});
  stored[today()] = { items };
  lsSet(K.MISSIONS, stored);
}

function renderMissions() {
  const box = document.getElementById("hub-missions");
  if (!box) return;
  const items = getDailyMissions();
  const done  = items.filter(m => m.done).length;

  box.innerHTML = items.map((m, i) => `
    <div class="hub-mission-item${m.done ? " done" : ""}" data-idx="${i}">
      <div class="hub-mission-check">${m.done ? "✓" : ""}</div>
      <div class="hub-mission-body">
        <span class="hub-mission-text">${esc(m.text)}</span>
        <span class="hub-mission-sub">${esc(m.sub)}</span>
      </div>
      <span class="hub-mission-xp">+${m.xp} XP</span>
    </div>`).join("");

  const fill  = document.getElementById("hub-mission-fill");
  const label = document.getElementById("hub-mission-label");
  if (fill)  fill.style.width  = items.length ? (done / items.length * 100) + "%" : "0%";
  if (label) label.textContent = `${done} / ${items.length} done`;

  box.querySelectorAll(".hub-mission-item").forEach(el => {
    el.addEventListener("click", () => {
      const idx = +el.dataset.idx;
      const arr = getDailyMissions();
      if (arr[idx].done) return;
      arr[idx].done = true;
      saveMissions(arr);
      addXP(arr[idx].xp, arr[idx].text.slice(0, 22));
      renderMissions();
    });
  });
}

// ── Focus Timer ───────────────────────────────────────────────────────────────

function initFocus() {
  const data = ls(K.FOCUS, {});
  const t = today();
  if (data.date !== t) {
    data.date = t; data.sessions_today = 0;
    lsSet(K.FOCUS, data);
  }
  focusSessionsToday = data.sessions_today || 0;
  // Seed hero pill immediately
  const pill = document.getElementById("hub-focus-today");
  if (pill) pill.textContent = focusSessionsToday;
  updateFocusArc();
  updateFocusMeta();

  document.getElementById("hub-focus-start")?.addEventListener("click", toggleFocus);
  document.getElementById("hub-focus-reset")?.addEventListener("click", resetFocus);
}

function toggleFocus() {
  const btn = document.getElementById("hub-focus-start");
  if (focusInterval) {
    clearInterval(focusInterval); focusInterval = null;
    if (btn) btn.textContent = "Resume";
  } else {
    focusInterval = setInterval(tickFocus, 1000);
    if (btn) btn.textContent = "Pause";
  }
}

function tickFocus() {
  focusSecondsLeft = Math.max(0, focusSecondsLeft - 1);
  updateFocusArc();
  if (focusSecondsLeft === 0) {
    clearInterval(focusInterval); focusInterval = null;
    const btn = document.getElementById("hub-focus-start");
    if (btn) btn.textContent = "Start";

    if (!focusIsBreak) {
      focusSessionsToday++;
      const data = ls(K.FOCUS, {});
      data.sessions_today  = focusSessionsToday;
      data.total_sessions  = (data.total_sessions || 0) + 1;
      lsSet(K.FOCUS, data);
      addXP(40, "Focus session done");
      checkBadges();
      showToast("🍅 Well done! Take a 5-minute break.");
      focusIsBreak = true; focusSecondsLeft = FOCUS_BREAK;
    } else {
      showToast("⚡ Break over! Let's go.");
      focusIsBreak = false; focusSecondsLeft = FOCUS_WORK;
    }
    updateFocusArc();
    updateFocusMeta();
  }
}

function resetFocus() {
  clearInterval(focusInterval); focusInterval = null;
  focusIsBreak = false; focusSecondsLeft = FOCUS_WORK;
  const btn = document.getElementById("hub-focus-start");
  if (btn) btn.textContent = "Start";
  updateFocusArc();
}

function updateFocusArc() {
  const timeEl  = document.getElementById("hub-focus-time");
  const phaseEl = document.getElementById("hub-focus-phase");
  const arc     = document.getElementById("hub-focus-arc");

  if (timeEl)  timeEl.textContent  = fmt(focusSecondsLeft);
  if (phaseEl) phaseEl.textContent = focusIsBreak ? "Break" : "Focus";

  if (arc) {
    const total = focusIsBreak ? FOCUS_BREAK : FOCUS_WORK;
    const C     = 2 * Math.PI * 52;
    arc.style.strokeDasharray  = C;
    arc.style.strokeDashoffset = C * (1 - focusSecondsLeft / total);
    arc.classList.toggle("is-break", focusIsBreak);
  }
}

function updateFocusMeta() {
  const el = document.getElementById("hub-focus-meta");
  if (!el) return;
  const data = ls(K.FOCUS, {});
  const total = data.total_sessions || 0;
  el.innerHTML = `${focusSessionsToday} session${focusSessionsToday !== 1 ? "s" : ""} today &nbsp;·&nbsp; ${total} total &nbsp;·&nbsp; ${total * 40} XP earned`;

  // Update hero pill
  const pill = document.getElementById("hub-focus-today");
  if (pill) pill.textContent = focusSessionsToday;
}

// ── Exam Countdown ────────────────────────────────────────────────────────────

function daysUntil(dateStr) {
  const then = new Date(dateStr); const now = new Date();
  now.setHours(0, 0, 0, 0); then.setHours(0, 0, 0, 0);
  return Math.round((then - now) / 86400000);
}

function renderCountdowns() {
  const box = document.getElementById("hub-countdowns");
  if (!box) return;
  const exams    = ls(K.EXAMS, []);
  const upcoming = exams.filter(e => daysUntil(e.date) >= 0)
    .sort((a, b) => daysUntil(a.date) - daysUntil(b.date));

  if (!upcoming.length) {
    box.innerHTML = `<p class="hub-countdown-empty">No exams added yet.<br>Tap + Add to set your countdown.</p>`;
    return;
  }

  const C = 2 * Math.PI * 22;
  box.innerHTML = upcoming.slice(0, 3).map(e => {
    const d    = daysUntil(e.date);
    const pct  = Math.max(0, Math.min(1, 1 - d / 180));
    const col  = d <= 7 ? "#e74c3c" : d <= 30 ? "#f39c12" : "#3cb87a";
    const when = d === 0 ? "Today!" : d === 1 ? "Tomorrow" : `${d} days left`;
    return `
      <div class="hub-countdown-item">
        <div class="hub-countdown-ring-wrap">
          <svg class="hub-countdown-svg" viewBox="0 0 54 54">
            <circle class="hub-countdown-track" cx="27" cy="27" r="22"/>
            <circle class="hub-countdown-fill" cx="27" cy="27" r="22"
              stroke="${col}" stroke-dasharray="${C}"
              stroke-dashoffset="${C * (1 - pct)}"/>
          </svg>
          <div class="hub-countdown-number">${d}</div>
        </div>
        <div class="hub-countdown-meta">
          <span class="hub-countdown-subj">${esc(e.subj)}</span>
          <span class="hub-countdown-until">${when}</span>
        </div>
        <button class="hub-countdown-del" data-id="${esc(e.id)}" title="Remove">✕</button>
      </div>`;
  }).join("");

  box.querySelectorAll(".hub-countdown-del").forEach(btn =>
    btn.addEventListener("click", () => {
      lsSet(K.EXAMS, ls(K.EXAMS, []).filter(e => e.id !== btn.dataset.id));
      renderCountdowns();
    })
  );
}

function initExamForm() {
  document.getElementById("hub-add-exam")?.addEventListener("click", () => {
    let form = document.getElementById("hub-exam-form");
    if (form) { form.remove(); return; }
    form = document.createElement("div");
    form.id = "hub-exam-form";
    form.className = "hub-exam-form";
    form.innerHTML = `
      <input id="hub-exam-subj" placeholder="Subject (e.g. Mathematics)" maxlength="40"/>
      <input id="hub-exam-date" type="date" min="${today()}"/>
      <div class="hub-exam-form-btns">
        <button class="btn btn-gold hub-exam-save">Add Exam</button>
        <button class="btn btn-outline hub-exam-cancel">Cancel</button>
      </div>`;
    document.getElementById("hub-countdowns")?.insertAdjacentElement("afterend", form);

    form.querySelector(".hub-exam-cancel").addEventListener("click", () => form.remove());
    form.querySelector(".hub-exam-save").addEventListener("click", () => {
      const subj = document.getElementById("hub-exam-subj")?.value.trim();
      const date = document.getElementById("hub-exam-date")?.value;
      if (!subj || !date) { alert("Please fill in both the subject and date."); return; }
      const exams = ls(K.EXAMS, []);
      exams.push({ id: Date.now().toString(), subj, date });
      lsSet(K.EXAMS, exams);
      form.remove();
      renderCountdowns();
    });
  });
}

// ── Activity Heatmap ──────────────────────────────────────────────────────────

function renderHeatmap() {
  const box = document.getElementById("hub-heatmap-grid");
  if (!box) return;

  const log = ls(K.XP_LOG, []);
  const map = {};
  for (const e of log) map[e.date] = e.xp;

  // 91 days ending today
  const days = [];
  for (let i = 90; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }

  // Pad so first column starts on Sunday
  const firstDow = new Date(days[0]).getDay();
  const padded = Array(firstDow).fill(null).concat(days);

  const weeks = [];
  for (let i = 0; i < padded.length; i += 7) weeks.push(padded.slice(i, i + 7));

  box.innerHTML = weeks.map(week => `
    <div class="hub-heatmap-col">
      ${week.map(d => {
        if (!d) return `<div class="hub-heatmap-cell" style="opacity:0"></div>`;
        const xp = map[d] || 0;
        const level = xp === 0 ? 0 : xp < 20 ? 1 : xp < 50 ? 2 : xp < 100 ? 3 : 4;
        const label = new Date(d + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
        return `<div class="hub-heatmap-cell" data-level="${level}" title="${label}: ${xp} XP"></div>`;
      }).join("")}
    </div>`).join("");

  const weekXP = days.slice(-7).reduce((s, d) => s + (map[d] || 0), 0);
  const totalEl = document.getElementById("hub-heatmap-total");
  if (totalEl) totalEl.textContent = `${weekXP} XP this week`;
}

// ── Insights ──────────────────────────────────────────────────────────────────

function renderInsights() {
  const box = document.getElementById("hub-insights-list");
  if (!box) return;

  const log  = ls(K.XP_LOG, []);
  const xp   = getXP();
  const focus = ls(K.FOCUS, {});
  const map  = {};
  for (const e of log) map[e.date] = e.xp;

  const days7     = Array.from({ length: 7  }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - i);     return d.toISOString().slice(0, 10); }).reverse();
  const prevDays7 = Array.from({ length: 7  }, (_, i) => { const d = new Date(); d.setDate(d.getDate() - i - 7); return d.toISOString().slice(0, 10); });
  const thisWeek  = days7.reduce((s, d)     => s + (map[d] || 0), 0);
  const lastWeek  = prevDays7.reduce((s, d) => s + (map[d] || 0), 0);

  const insights = [];

  if (currentStreak >= 3)
    insights.push({ ico: "🔥", text: `${currentStreak}-day streak! Your consistency is compounding. Don't break the chain.` });

  if (lastWeek > 0 && thisWeek > lastWeek) {
    const pct = Math.round((thisWeek - lastWeek) / lastWeek * 100);
    insights.push({ ico: "📈", text: `You're ${pct}% more active this week than last. Momentum is building.` });
  }

  if (xp >= 500)
    insights.push({ ico: "⚡", text: `${xp.toLocaleString()} XP earned. Every point proves you showed up and did the work.` });

  const totalFocus = focus.total_sessions || 0;
  if (totalFocus >= 3)
    insights.push({ ico: "🧠", text: `${totalFocus} deep focus sessions completed. You're training your concentration muscle.` });

  if (!insights.length) {
    insights.push({ ico: "💡", text: "Complete missions and focus sessions to unlock personalized insights about your study habits." });
    insights.push({ ico: "🎯", text: "Add your exam dates above to see a countdown and urgency ring for each subject." });
  }

  box.innerHTML = insights.slice(0, 3).map(i =>
    `<div class="hub-insight"><span class="hub-insight-ico">${i.ico}</span><span>${i.text}</span></div>`
  ).join("");
}

// ── Quick Actions ─────────────────────────────────────────────────────────────

const QUICK_ACTIONS = [
  { ico: "🗂️", label: "Flashcards",      href: "flashcards.html",  tint: "#7c4dff" },
  { ico: "⚡",  label: "Practice Quiz",   href: "mcq-solver.html",  tint: "#e74c3c" },
  { ico: "🤖", label: "AI Tutor",         href: "tutor.html",       tint: "#E8913A" },
  { ico: "📚", label: "Study Notes",      href: "resources.html",   tint: "#00b8a9" },
  { ico: "📖", label: "Progress",         href: "topical-progress.html", tint: "#43a047" },
  { ico: "📑", label: "Past Papers",      href: "papers.html",      tint: "#2196f3" },
  { ico: "📝", label: "Homework",         href: "homework.html",    tint: "#f39c12" },
  { ico: "💬", label: "Messages",         href: "messages.html",    tint: "#3cb87a", id: "dash-messages-link" },
];

function renderQuickActions() {
  const box = document.getElementById("hub-quick-list");
  if (!box) return;
  box.innerHTML = QUICK_ACTIONS.map(a => `
    <a class="hub-action-card" href="${a.href}"${a.id ? ` id="${a.id}"` : ""}
       style="--qa-tint:${a.tint || '#E8913A'}">
      <span class="hub-action-ico">${a.ico}</span>
      <span class="hub-action-label dash-action-title">${a.label}</span>
    </a>`).join("");
}

// ── Continue Learning ─────────────────────────────────────────────────────────

function renderContinueLearning(enrollments = [], metaSubjects = []) {
  const box = document.getElementById("hub-continue-list");
  if (!box || !enrollments.length) {
    if (box) box.innerHTML = `<p class="dash-loading">Enrol in a subject below to see your resume links.</p>`;
    return;
  }
  box.innerHTML = enrollments.slice(0, 3).map(e => {
    const s = metaSubjects.find(s => s.syllabus === e.syllabus);
    const name = s?.short || e.name || e.syllabus;
    const ico  = /math/i.test(name) ? "📐" : /phys/i.test(name) ? "⚗️" : /comp/i.test(name) ? "💻" : "📚";
    return `
      <a class="hub-continue-item" href="topical-progress.html?syllabus=${encodeURIComponent(e.syllabus)}">
        <span class="hub-continue-ico">${ico}</span>
        <span class="hub-continue-meta">
          <span class="hub-continue-subj">${esc(name)}</span>
          <span class="hub-continue-chapter">Continue where you left off →</span>
        </span>
        <span class="hub-continue-arrow">→</span>
      </a>`;
  }).join("");
}

// ── Greeting ──────────────────────────────────────────────────────────────────

function renderGreeting(name) {
  const h = new Date().getHours();
  const part = h < 5 ? "Night Owl 🦉" : h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : h < 21 ? "Good Evening" : "Night Owl 🦉";
  const first = (name || "").split(" ")[0] || "there";

  const timeEl = document.getElementById("hub-greeting-time");
  const nameEl = document.getElementById("hub-greeting-name");
  if (timeEl) timeEl.textContent = part + ",";
  if (nameEl) nameEl.innerHTML = `Welcome back, <em>${esc(first)}.</em>`;

  const dayOfYear = Math.floor((Date.now() - new Date(new Date().getFullYear(), 0, 0)) / 86400000);
  const quoteEl = document.getElementById("hub-quote");
  if (quoteEl) quoteEl.textContent = `"${QUOTES[dayOfYear % QUOTES.length]}"`;

  // Mission date label
  const dateEl = document.getElementById("hub-mission-date");
  if (dateEl) dateEl.textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

// ── Streak display ────────────────────────────────────────────────────────────

function setStreak(n) {
  currentStreak = n;
  const el = document.getElementById("hub-streak-num");
  if (el) el.textContent = n;
  try {
    localStorage.setItem("pwt_streak", JSON.stringify(n));
    const prev = JSON.parse(localStorage.getItem("pwt_streak_max") || "0");
    if (n > prev) localStorage.setItem("pwt_streak_max", JSON.stringify(n));
  } catch {}
  _scheduleSync();
}

// Watch for dashboard.js writing the streak value
function watchStreak() {
  const src = document.querySelector("#dash-streak .dash-streak-num");
  if (!src) return;
  const obs = new MutationObserver(() => {
    const n = parseInt(src.textContent, 10);
    if (!isNaN(n)) setStreak(n);
  });
  obs.observe(src, { childList: true, characterData: true, subtree: true });
}

// ── Daily visit XP ────────────────────────────────────────────────────────────

function awardVisitXP() {
  const log = ls(K.XP_LOG, []);
  const t   = today();
  if (!log.find(e => e.date === t)) {
    // First visit today — silent 5 XP
    const xp = getXP() + 5;
    lsSet(K.XP, xp);
    log.push({ date: t, xp: 5 });
    lsSet(K.XP_LOG, log.slice(-90));
  }
}

// ── Calendar + Tasks ──────────────────────────────────────────────────────────

const TASK_COLORS = 5;   // 0..4 → css classes tdot-N / pill-task-N
const TASK_KEY = "pwt_tasks";

// Seed sample tasks shown on first load
function _seedTasks() {
  const today = new Date();
  const fmt = d => d.toISOString().slice(0, 10);
  const d0 = fmt(today);
  const d1 = fmt(new Date(today.getTime() + 86400000));
  const d2 = fmt(new Date(today.getTime() + 2 * 86400000));
  const d3 = fmt(new Date(today.getTime() + 3 * 86400000));
  return [
    { id: "s1", title: "Let's start acing", date: d0, startTime: "16:00", endTime: "17:00", color: 0, done: false, sample: true },
    { id: "s2", title: "Read a topic in Notes", date: d0, startTime: "18:00", endTime: "19:00", color: 1, done: false, sample: true },
    { id: "s3", title: "Revise one weak subtopic", date: d1, startTime: "17:00", endTime: "18:00", color: 2, done: false, sample: true },
    { id: "s4", title: "Try a past paper question", date: d2, startTime: "17:00", endTime: "18:00", color: 3, done: false, sample: true },
    { id: "s5", title: "Check homework list", date: d3, startTime: "15:00", endTime: "16:00", color: 4, done: false, sample: true },
  ];
}

function _loadTasks() {
  try {
    const raw = JSON.parse(localStorage.getItem(TASK_KEY) || "null");
    if (Array.isArray(raw) && raw.length) return raw;
  } catch {}
  const seed = _seedTasks();
  _saveTasks(seed);
  return seed;
}

function _saveTasks(tasks) {
  try { localStorage.setItem(TASK_KEY, JSON.stringify(tasks)); } catch {}
}

function _fmtTime(hhmm) {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  const ampm = h < 12 ? "AM" : "PM";
  const h12 = h % 12 || 12;
  return m === 0 ? `${h12} ${ampm}` : `${h12}:${String(m).padStart(2,"0")} ${ampm}`;
}

function _fmtDateLabel(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

let _calHwItems = [];
let _calYear, _calMonth, _calListenersSet = false;
let _tasks = null;
let _addFormOpen = false;

function renderCalendar(hwItems) {
  _calHwItems = hwItems || [];
  if (!_tasks) _tasks = _loadTasks();
  const now = new Date();
  if (_calYear === undefined) { _calYear = now.getFullYear(); _calMonth = now.getMonth(); }
  _drawBigCal();
  _renderTasks();

  if (!_calListenersSet) {
    _calListenersSet = true;
    document.getElementById("hub-cal-prev")?.addEventListener("click", () => {
      _calMonth--; if (_calMonth < 0) { _calMonth = 11; _calYear--; } _drawBigCal();
    });
    document.getElementById("hub-cal-next")?.addEventListener("click", () => {
      _calMonth++; if (_calMonth > 11) { _calMonth = 0; _calYear++; } _drawBigCal();
    });
    document.getElementById("hub-add-task-btn")?.addEventListener("click", _openAddTaskForm);
  }
}

function _allCalEvents() {
  const evts = [];

  // Tasks
  (_tasks || []).forEach(t => {
    if (!t.date) return;
    const d = new Date(t.date + "T" + (t.startTime || "00:00") + ":00");
    if (isNaN(d)) return;
    evts.push({ kind: "task", colorIdx: t.color ?? 0, date: d,
      title: t.title, startTime: t.startTime, endTime: t.endTime, id: t.id, done: t.done });
  });

  // Homework
  _calHwItems.forEach(h => {
    if (!h.due_date) return;
    const d = new Date(h.due_date);
    if (isNaN(d)) return;
    evts.push({ kind: "hw", date: d, title: h.title || "Homework" });
  });

  // Reminders
  try {
    const rems = JSON.parse(localStorage.getItem("pwt_reminders") || "[]");
    rems.forEach(r => {
      if (!r.datetime || r.done) return;
      const d = new Date(r.datetime);
      if (isNaN(d)) return;
      evts.push({ kind: "rem", date: d, title: r.title });
    });
  } catch {}

  // Exams
  try {
    const exams = JSON.parse(localStorage.getItem("pwt_exams") || "[]");
    exams.forEach(e => {
      if (!e.date) return;
      const d = new Date(e.date);
      if (isNaN(d)) return;
      evts.push({ kind: "exam", date: d, title: e.name || "Exam" });
    });
  } catch {}

  return evts;
}

function _drawBigCal() {
  const grid  = document.getElementById("hub-cal-grid");
  const label = document.getElementById("hub-cal-month-label");
  if (!grid) return;

  const MONTHS_LONG = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"];
  const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
  label.textContent = `${MONTHS_LONG[_calMonth]} ${_calYear}`;

  const today = new Date();
  const first = new Date(_calYear, _calMonth, 1);
  const startDow = (first.getDay() + 6) % 7;  // Monday-first
  const daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();

  const evts = _allCalEvents();
  // Map: "YYYY-MM-DD" → sorted events
  const evtMap = {};
  evts.forEach(e => {
    const key = e.date.toISOString().slice(0, 10);
    if (!evtMap[key]) evtMap[key] = [];
    evtMap[key].push(e);
  });
  Object.values(evtMap).forEach(arr => arr.sort((a, b) => a.date - b.date));

  // DOW header
  const dowHtml = `<div class="hub-bigcal-dow">${DAYS.map(d => `<span>${d}</span>`).join("")}</div>`;

  // Cells
  let cells = "";
  // Leading empty cells from prev month
  for (let i = 0; i < startDow; i++) {
    cells += `<div class="hub-bigcal-cell bc-empty"></div>`;
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const dt = new Date(_calYear, _calMonth, d);
    const key = dt.toISOString().slice(0, 10);
    const isToday = dt.toDateString() === today.toDateString();
    const isPast  = dt < new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const dayEvts = evtMap[key] || [];

    const cls = [
      "hub-bigcal-cell",
      isToday ? "bc-today" : "",
      isPast  ? "bc-past"  : "",
    ].filter(Boolean).join(" ");

    const maxPills = 2;
    const shown = dayEvts.slice(0, maxPills);
    const more  = dayEvts.length - maxPills;

    const pills = shown.map(e => {
      const pillCls = e.kind === "task"
        ? `pill-task-${e.colorIdx ?? 0}`
        : `pill-${e.kind}`;
      const doneCls = e.done ? " bc-pill-done" : "";
      const timeStr = e.startTime ? _fmtTime(e.startTime) + " " : "";
      return `<div class="hub-bigcal-pill ${pillCls}${doneCls}">
        <span class="hub-bigcal-pill-dot"></span>${timeStr}${escHtml(e.title)}
      </div>`;
    }).join("");

    const moreHtml = more > 0 ? `<div class="hub-bigcal-pill-more">+${more} more</div>` : "";

    cells += `<div class="${cls}">
      <span class="hub-bigcal-daynum">${d}</span>
      <div class="hub-bigcal-pills">${pills}${moreHtml}</div>
    </div>`;
  }

  grid.innerHTML = dowHtml + `<div class="hub-bigcal-dates">${cells}</div>`;
}

function _renderTasks() {
  const list = document.getElementById("hub-tasks-list");
  if (!list) return;
  if (!_tasks) _tasks = _loadTasks();

  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);
  const cutoffStr = new Date(today.getTime() + 30 * 86400000).toISOString().slice(0, 10);

  // Show today + next 30 days, sorted by date+time
  const visible = _tasks
    .filter(t => t.date >= todayStr && t.date <= cutoffStr)
    .sort((a, b) => {
      if (a.date !== b.date) return a.date < b.date ? -1 : 1;
      return (a.startTime || "") < (b.startTime || "") ? -1 : 1;
    });

  if (!visible.length) {
    list.innerHTML = `<p class="hub-tasks-empty">No upcoming tasks.<br>Add one to get started.</p>`;
    return;
  }

  list.innerHTML = visible.map(t => {
    const timeStr = t.startTime
      ? `${_fmtDateLabel(t.date)} · ${_fmtTime(t.startTime)}${t.endTime ? " – " + _fmtTime(t.endTime) : ""}`
      : _fmtDateLabel(t.date);
    const sampleBadge = t.sample
      ? `<span class="hub-task-badge">Sample</span>` : "";
    return `<div class="hub-task-item${t.done ? " task-done" : ""}" data-task-id="${escHtml(t.id)}">
      <div class="hub-task-cb"></div>
      <div class="hub-task-dot tdot-${t.color ?? 0}"></div>
      <div class="hub-task-body">
        <div class="hub-task-title">${escHtml(t.title)}${sampleBadge}</div>
        <div class="hub-task-meta">${timeStr}</div>
      </div>
    </div>`;
  }).join("");

  // Wire up click-to-toggle
  list.querySelectorAll(".hub-task-item").forEach(el => {
    el.addEventListener("click", () => {
      const id = el.dataset.taskId;
      const t = _tasks.find(x => x.id === id);
      if (t) { t.done = !t.done; _saveTasks(_tasks); _renderTasks(); _drawBigCal(); }
    });
  });
}

function _openAddTaskForm() {
  if (_addFormOpen) return;
  _addFormOpen = true;
  const list = document.getElementById("hub-tasks-list");
  if (!list) return;

  const today = new Date().toISOString().slice(0, 10);
  const form = document.createElement("div");
  form.className = "hub-add-task-form";
  form.innerHTML = `
    <input type="text" id="atf-title" placeholder="Task title…" maxlength="80">
    <div class="hub-add-task-row">
      <input type="date" id="atf-date" value="${today}">
      <select id="atf-color">
        <option value="0">🔴 Red</option>
        <option value="1">🟢 Green</option>
        <option value="2">🟣 Purple</option>
        <option value="3">🟠 Orange</option>
        <option value="4">🔵 Blue</option>
      </select>
    </div>
    <div class="hub-add-task-row">
      <input type="time" id="atf-start" placeholder="Start time">
      <input type="time" id="atf-end"   placeholder="End time">
    </div>
    <div class="hub-add-task-actions">
      <button class="hub-add-task-cancel" id="atf-cancel">Cancel</button>
      <button class="hub-add-task-save"   id="atf-save">Save task</button>
    </div>`;

  list.prepend(form);
  form.querySelector("#atf-title").focus();

  form.querySelector("#atf-cancel").addEventListener("click", () => {
    form.remove(); _addFormOpen = false;
  });
  form.querySelector("#atf-save").addEventListener("click", () => {
    const title = form.querySelector("#atf-title").value.trim();
    if (!title) { form.querySelector("#atf-title").focus(); return; }
    const task = {
      id: "t" + Date.now(),
      title,
      date: form.querySelector("#atf-date").value || new Date().toISOString().slice(0,10),
      startTime: form.querySelector("#atf-start").value || "",
      endTime:   form.querySelector("#atf-end").value   || "",
      color: parseInt(form.querySelector("#atf-color").value) || 0,
      done: false,
      sample: false,
    };
    if (!_tasks) _tasks = _loadTasks();
    _tasks.push(task);
    _saveTasks(_tasks);
    form.remove();
    _addFormOpen = false;
    _renderTasks();
    _drawBigCal();
  });
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Main init ─────────────────────────────────────────────────────────────────

async function init() {
  // Non-personalised UI renders immediately (no user needed)
  renderQuickActions();
  renderCountdowns();
  initExamForm();
  initFocus();
  renderCalendar([]);

  // Fetch user first so XP/badge state is always scoped to the right account
  let currentUser = null;
  try {
    currentUser = await requireProfile();
    if (!currentUser) return;
  } catch { return; }

  renderGreeting(currentUser.name);

  // Guard: clear XP/achievement data when a different user logs in on this device
  const storedUid = localStorage.getItem("pwt_uid");
  if (storedUid && storedUid !== currentUser.id) {
    ["pwt_xp_total", "pwt_xp_log", "pwt_badges", "pwt_missions",
     "pwt_focus", "pwt_streak", "pwt_streak_max"].forEach(k => {
      try { localStorage.removeItem(k); } catch {}
    });
  }
  try { localStorage.setItem("pwt_uid", currentUser.id); } catch {}

  // Hydrate localStorage from server (source of truth for cross-device sync)
  try {
    const srv = await api("/api/stats");
    if (srv && (srv.xp_total > 0 || srv.badges?.length > 0)) {
      lsSet(K.XP, srv.xp_total);
      if (srv.xp_log?.length) lsSet(K.XP_LOG, srv.xp_log);
      lsSet(K.BADGES, srv.badges || []);
      try {
        localStorage.setItem("pwt_streak", JSON.stringify(srv.streak || 0));
        localStorage.setItem("pwt_streak_max", JSON.stringify(srv.streak_max || 0));
      } catch {}
      if (srv.focus && Object.keys(srv.focus).length) lsSet(K.FOCUS, srv.focus);
      if (srv.missions && Object.keys(srv.missions).length) lsSet(K.MISSIONS, srv.missions);
    }
  } catch { /* fall back to localStorage */ }

  // Now safe to load user-specific state
  badgesEarned = new Set(ls(K.BADGES, []));
  if (!badgesEarned.has("first_session")) {
    badgesEarned.add("first_session");
    lsSet(K.BADGES, [...badgesEarned]);
  }

  awardVisitXP();
  updateXPDisplay();
  renderMissions();
  renderBadges();
  renderHeatmap();
  watchStreak();

  // Fetch dashboard data
  try {
    const [dash, meta] = await Promise.all([api("/api/dashboard"), api("/api/meta")]);
    setStreak(dash.streak || 0);
    const timeTodayEl = document.getElementById("hub-time-today");
    if (timeTodayEl) {
      const mins = Math.round((dash.today_seconds || 0) / 60);
      timeTodayEl.textContent = `${mins}m`;
    }
    renderContinueLearning(dash.enrollments || [], meta?.subjects || []);
    renderInsights();
    checkBadges();
    renderCalendar(dash.homework?.items || []);
  } catch { /* non-fatal */ }
}


if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

// ── Pinned Notes Widget ───────────────────────────────────────────────────────
async function loadPinnedNotes() {
  const card  = document.getElementById("dash-notes-card");
  const inner = document.getElementById("dash-notes-inner");
  if (!card || !inner) return;

  try {
    const r = await fetch("/api/notes/pinned");
    if (!r.ok) return;
    const data = await r.json();
    const notes = data.notes || [];
    if (!notes.length) return;   // keep card hidden

    card.style.display = "";
    const COLORS = {
      yellow: "#FFF8C5", pink: "#FFD6E7", blue: "#D4EDFF",
      green: "#D4F5E2", purple: "#EAD8FF"
    };
    inner.innerHTML = notes.map(n => {
      const bg = COLORS[n.color] || "#FFF8C5";
      const title = n.title
        ? `<b style="font-size:.85rem;color:var(--navy)">${escH(n.title)}</b><br>`
        : "";
      const preview = (n.content || "").slice(0, 100).replace(/\n/g, " ");
      return `
        <a href="notes.html" style="display:block;margin-bottom:.55rem;text-decoration:none;">
          <div style="
            background:${n.type === "sticky" ? bg : "#fff"};
            border:1.5px solid ${n.type === "sticky" ? "transparent" : "var(--line)"};
            border-radius:11px;padding:.7rem .85rem;
          ">
            ${title}
            <span style="font-size:.8rem;color:var(--ink);line-height:1.5">${escH(preview)}${(n.content||"").length > 100 ? "…" : ""}</span>
          </div>
        </a>`;
    }).join("");
  } catch (_) { /* non-fatal */ }
}

// Hook into page load
(function () {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPinnedNotes);
  } else {
    loadPinnedNotes();
  }
})();

function escH(s) {
  if (!s) return "";
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
