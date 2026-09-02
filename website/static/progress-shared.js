/* progress-shared.js — Shared utilities for topical and yearly progress pages.
 *
 * Both pages need the same subject selector, board filtering, grade calculation,
 * and progress ring component. This module exports them as clean functions so
 * neither page duplicates the logic.
 */

import { api, teeLoader } from "/auth.js";

/* ── Constants ──────────────────────────────────────────────── */

export const BOARD_OF_GRADE = {
  "O Level": "Cambridge O Level",
  "IGCSE": "Cambridge IGCSE",
  "A Level": "Cambridge A Level",
};

export const STATUSES = [
  ["not_started", "Not started"],
  ["learning",    "Learning"],
  ["confident",   "Confident"],
];

export const PAPER_STEPS = [
  ["not_started", "Not yet", "Haven't done past-paper questions on this yet"],
  ["learning", "Some", "Done a few past-paper questions on this"],
  ["confident", "Done", "Worked through the past-paper questions on this"],
];

export { api, teeLoader };

/* ── Helpers ────────────────────────────────────────────────── */

export const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const key = (topic, subtopic) => `${topic}\0${subtopic ?? ""}`;

export const paperKey = p => `${p.year} ${p.session} ${p.paper} ${p.variant || ""}`;

/* ── Subject helpers ────────────────────────────────────────── */

export function subjectFor(meta, code) {
  return meta?.subjects?.find(s => s.syllabus === code);
}

export function mySubjects(meta, board, enrolled) {
  if (!enrolled || !enrolled.length) return [];
  return meta.subjects.filter(s => enrolled.includes(s.syllabus));
}

export function compLabel(meta, syllabus, paper) {
  const sub = meta?.subjects?.find(s => s.syllabus === syllabus);
  const c = (sub?.components || []).find(c => c.paper === paper);
  return c?.label || `Paper ${paper}`;
}

/* ── Subject pill strip ─────────────────────────────────────── */

export function renderSubjectStrip(container, subjects, enrolled, onSelect) {
  container.innerHTML = subjects.sort((a, b) =>
    (enrolled.includes(b.syllabus) ? 1 : 0) -
    (enrolled.includes(a.syllabus) ? 1 : 0)).map(s => `
    <button type="button" class="revise-pill" data-syllabus="${esc(s.syllabus)}">
      ${esc(s.short)}
      <em>${esc(s.board.replace("Cambridge ", ""))}</em>
      ${enrolled.includes(s.syllabus) ? '<span class="revise-pill-dot" title="Enrolled"></span>' : ""}
    </button>`).join("");

  container.querySelectorAll(".revise-pill").forEach(btn =>
    btn.addEventListener("click", () => onSelect(btn.dataset.syllabus)));
}

export function highlightSubjectPill(code) {
  document.querySelectorAll(".revise-pill").forEach(b =>
    b.classList.toggle("active", b.dataset.syllabus === code));
}

/* ── Grade calculation ──────────────────────────────────────── */

export function calculateGrade(score, maxScore, thresholds) {
  if (score == null || score === "" || isNaN(score) || !maxScore) return { grade: null, pct: null };
  score = Number(score);
  maxScore = Number(maxScore);
  const pct = Math.round((score / maxScore) * 100);

  if (!thresholds) {
    const fallbackGrade = pct >= 85 ? "A*" : pct >= 70 ? "A" : pct >= 60 ? "B" : pct >= 50 ? "C" : pct >= 40 ? "D" : pct >= 30 ? "E" : "U";
    return { grade: fallbackGrade, pct, isFallback: true };
  }

  if (thresholds.grade_astar != null && score >= thresholds.grade_astar) return { grade: "A*", pct };
  if (score >= thresholds.grade_a) return { grade: "A", pct };
  if (score >= thresholds.grade_b) return { grade: "B", pct };
  if (score >= thresholds.grade_c) return { grade: "C", pct };
  if (score >= thresholds.grade_d) return { grade: "D", pct };
  if (score >= thresholds.grade_e) return { grade: "E", pct };
  return { grade: "U", pct };
}

export function renderGradePill(grade, label) {
  if (!grade) return `<span class="pap-grade-pill grade-none">${label || "—"}</span>`;
  const gClass = grade === "A*" ? "grade-Astar" : `grade-${grade}`;
  return `<span class="pap-grade-pill ${gClass}">${grade}</span>`;
}

/* ── Mini threshold bar (class-based, no inline styles) ────── */

export function renderMiniThresholdBar(score, maxScore, thresholds) {
  if (!thresholds || maxScore <= 0) {
    return ``;
  }
  const scorePct = Math.min(100, Math.max(0, Math.round(((score || 0) / maxScore) * 100)));
  const ePct = Math.round(((thresholds.grade_e || 0) / maxScore) * 100);
  const dPct = Math.round(((thresholds.grade_d || 0) / maxScore) * 100);
  const cPct = Math.round(((thresholds.grade_c || 0) / maxScore) * 100);
  const bPct = Math.round(((thresholds.grade_b || 0) / maxScore) * 100);
  const aPct = Math.round(((thresholds.grade_a || 0) / maxScore) * 100);
  const asPct = thresholds.grade_astar != null ? Math.round((thresholds.grade_astar / maxScore) * 100) : null;

  const hasScore = score != null && score !== "" && !isNaN(score);

  return `
    <div class="pm-mini-bar-wrap" title="Score position vs grade boundaries">
      <div class="pm-mini-bar-zone pm-mini-bar-zone-u" style="left:0; width:${ePct}%"></div>
      <div class="pm-mini-bar-zone pm-mini-bar-zone-e" style="left:${ePct}%; width:${dPct-ePct}%"></div>
      <div class="pm-mini-bar-zone pm-mini-bar-zone-d" style="left:${dPct}%; width:${cPct-dPct}%"></div>
      <div class="pm-mini-bar-zone pm-mini-bar-zone-c" style="left:${cPct}%; width:${bPct-cPct}%"></div>
      <div class="pm-mini-bar-zone pm-mini-bar-zone-b" style="left:${bPct}%; width:${aPct-bPct}%"></div>
      ${asPct != null
        ? `<div class="pm-mini-bar-zone pm-mini-bar-zone-a" style="left:${aPct}%; width:${asPct-aPct}%"></div>
           <div class="pm-mini-bar-zone pm-mini-bar-zone-as" style="left:${asPct}%; right:0"></div>`
        : `<div class="pm-mini-bar-zone pm-mini-bar-zone-a" style="left:${aPct}%; right:0"></div>`}
      ${hasScore ? `<div class="pm-mini-bar-marker" style="left:${scorePct}%"></div>` : ''}
    </div>`;
}

/* ── Progress Ring component ────────────────────────────────── */

/**
 * Renders a single progress ring card.
 * @param {Object} opts
 * @param {number} opts.pct         - Percentage (0–100)
 * @param {string} opts.color       - Color class: green, blue, gold, lav, orange, teal, pink
 * @param {string} opts.label       - Label below the ring
 * @param {string} [opts.centerText] - Override center (e.g. "12 of 28") instead of pct
 * @param {string} [opts.tooltip]    - Hover tooltip text
 */
export function renderProgressRing({ pct, color, label, centerText, tooltip }) {
  const r = 38;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - Math.min(pct, 100) / 100);

  const center = centerText
    ? `<span class="ring-center-text">${esc(centerText)}</span>`
    : `<span class="ring-center-pct">${pct}<em>%</em></span>`;

  return `
    <div class="progress-ring-card" tabindex="0">
      ${tooltip ? `<span class="ring-tooltip">${esc(tooltip)}</span>` : ""}
      <div class="ring-wrap">
        <svg class="progress-ring" viewBox="0 0 90 90" aria-hidden="true">
          <circle class="ring-track" cx="45" cy="45" r="${r}"></circle>
          <circle class="ring-fill ring-color-${color}" cx="45" cy="45" r="${r}"
                  stroke-dasharray="${c}" stroke-dashoffset="${offset}"
                  style="--ring-circumference:${c}"></circle>
        </svg>
        <div class="ring-center">${center}</div>
      </div>
      <span class="ring-label">${esc(label)}</span>
    </div>`;
}
