/* grade-calculator.js — Overall predicted grade from per-component marks.
 *
 * Fetches historical grade_thresholds + grade_options for a chosen syllabus,
 * groups by paper components, calculates historical averages, predicts grades
 * across all past sessions, and shows detailed session probability stats.
 */

import { api, teeLoader } from "/auth.js";
import {
  calculateGrade, renderGradePill, renderMiniThresholdBar, esc,
} from "/progress-shared.js";

/* ── Subject list ────────────────────────────────────────────── */

const SUBJECTS = [
  { code: "5054", name: "O Level Physics",           board: "O Level" },
  { code: "0625", name: "IGCSE Physics",             board: "IGCSE" },
  { code: "4024", name: "O Level Mathematics D",     board: "O Level" },
  { code: "0580", name: "IGCSE Mathematics",         board: "IGCSE" },
  { code: "2210", name: "O Level Computer Science",  board: "O Level" },
  { code: "0478", name: "IGCSE Computer Science",    board: "IGCSE" },
  { code: "9702", name: "A Level Physics",           board: "A Level" },
  { code: "9709", name: "A Level Mathematics",       board: "A Level" },
];

const SESSION_LABEL = { s: "May/Jun", w: "Oct/Nov", m: "Feb/Mar" };

/* ── Official Cambridge component weightings ─────────────────────
 *
 * Each paper contributes a fixed PERCENTAGE of the qualification total,
 * regardless of its raw mark. e.g. IGCSE Physics (0625): the multiple-choice
 * paper is worth 30%, the theory paper 50%, the practical 20% — even though
 * their raw marks are 40, 80 and 40 (which only sum to 160, not 200).
 *
 * A raw component mark is converted to its weighted contribution with
 *     weighted = raw × (weightPct/100 × optionMax / componentRawMax)
 * so the weighted components of an option always sum to the option max mark
 * (200 for these subjects). Both optionMax and componentRawMax are read from
 * the official grade-threshold data, so the split self-corrects year to year.
 */
const WEIGHTINGS = {
  "0625": { 1: 30, 2: 30, 3: 50, 4: 50, 5: 20, 6: 20 }, // MCQ / Theory / Practical
  "5054": { 1: 30, 2: 50, 3: 20, 4: 20 },
  "4024": { 1: 50, 2: 50 },
  "0580": { 1: 50, 2: 50, 3: 50, 4: 50 },
  "2210": { 1: 50, 2: 50 },
  "0478": { 1: 50, 2: 50 },
  "9702": { 1: 15.5, 2: 23, 3: 11.5, 4: 38.5, 5: 11.5 },
};

/* Human labels for each paper, used in the weighting cards. */
const COMP_HINTS = {
  "0625": { 1: "Multiple choice", 2: "Multiple choice", 3: "Theory", 4: "Theory", 5: "Practical", 6: "Alt. to practical" },
  "5054": { 1: "Multiple choice", 2: "Theory", 3: "Practical", 4: "Alt. to practical" },
  "4024": { 1: "Paper 1 (non-calc)", 2: "Paper 2 (calc)" },
  "0580": { 1: "Paper 1", 2: "Paper 2", 3: "Paper 3", 4: "Paper 4" },
  "2210": { 1: "Theory", 2: "Problem-solving" },
  "0478": { 1: "Theory", 2: "Problem-solving" },
  "9702": { 1: "Multiple choice", 2: "AS structured", 3: "AS practical", 4: "A2 structured", 5: "A2 planning" },
};

function weightPct(syllabus, paper) {
  const w = WEIGHTINGS[syllabus];
  return w && w[Number(paper)] != null ? w[Number(paper)] : null;
}

function compHint(syllabus, paper) {
  const h = COMP_HINTS[syllabus];
  return (h && h[Number(paper)]) || `Paper ${paper}`;
}

/* Raw max mark for a specific component, straight from the threshold rows.
 * Prefer the exact year/session row; fall back to any matching paper+variant. */
function rawMaxFor(paper, variant, year, session) {
  const P = String(paper), V = String(variant || "");
  // Exact year/session match wins.
  if (year != null) {
    const exact = state._allThresholds.find(t =>
      String(t.paper) === P && String(t.variant || "") === V &&
      t.year === year && (session == null || t.session === session));
    if (exact) return exact.max_mark;
  }
  // Otherwise take the most recent matching row — component max marks change
  // across syllabus revisions (e.g. 0625 Paper 2 was 80 pre-2016, 40 since).
  const matches = state._allThresholds
    .filter(t => String(t.paper) === P && String(t.variant || "") === V)
    .sort((a, b) => b.year - a.year);
  if (matches.length) return matches[0].max_mark;
  const anyPaper = state._allThresholds
    .filter(t => String(t.paper) === P)
    .sort((a, b) => b.year - a.year);
  return anyPaper.length ? anyPaper[0].max_mark : null;
}

/* Weighting factor for one component within an option.
 * Uses the official percentage where known, otherwise scales the option's raw
 * marks proportionally so they still total the option max. */
function componentFactor(paper, rawMax, optionMax, sumRaw) {
  const pct = weightPct(state.syllabus, paper);
  if (pct != null && rawMax) return (pct / 100) * optionMax / rawMax;
  if (sumRaw) return optionMax / sumRaw;           // proportional fallback
  return 1.0;
}

/* ── State ───────────────────────────────────────────────────── */

let state = {
  syllabus: "",
  variant: "",
  thresholds: [],      // average grade_thresholds rows mapped by paper
  _allThresholds: [],  // all raw grade_thresholds rows
  _allOptions: [],     // all raw grade_options rows
  marks: {},           // { "paper_variant": value } e.g. "2_2": 54
};

/* ── Init ────────────────────────────────────────────────────── */

const selSyl     = document.getElementById("gc-syllabus");
const selVariant = document.getElementById("gc-variant");
const bodyEl     = document.getElementById("gc-body");
const tableEl    = document.getElementById("gc-table-wrap");
const summEl     = document.getElementById("gc-summary");
const weightEl   = document.getElementById("gc-weighting");
const emptyEl    = document.getElementById("gc-empty");

// Populate subject dropdown
async function initSubjects() {
  let enrolled = [];
  try {
    const enrollRes = await api("/api/enrollments");
    if (enrollRes && enrollRes.enrollments) {
      enrolled = enrollRes.enrollments.map(e => e.syllabus);
    }
  } catch(e) {}

  const subjectsToRender = enrolled.length > 0
    ? SUBJECTS.filter(s => enrolled.includes(s.code))
    : SUBJECTS;

  selSyl.innerHTML = '<option value="">Choose a subject…</option>';
  subjectsToRender.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s.code;
    opt.textContent = `${s.name} (${s.code})`;
    selSyl.appendChild(opt);
  });
  if (selSyl._sdInstance) selSyl._sdInstance.refresh();
}
initSubjects();

selSyl.addEventListener("change",  onSyllabusChange);
selVariant.addEventListener("change", onVariantChange);

/* ── Helper to format Zone ──────────────────────────────────── */

function getZoneLabel(variant) {
  if (variant === "2") return "Zone 4 — Pakistan / Middle East";
  if (variant === "1") return "Zone 1 — Europe / Africa";
  if (variant === "3") return "Zone 3 — East Asia / Australia";
  return `Zone ${variant}`;
}

/* ── Syllabus change → load all history & extract variants ───── */

async function onSyllabusChange() {
  state.syllabus = selSyl.value;
  state.variant = "";
  selVariant.innerHTML = '<option value="">—</option>';
  selVariant.disabled = true;
  hideResults();

  if (!state.syllabus) return;

  bodyEl.hidden = false;
  emptyEl.hidden = true;
  tableEl.innerHTML = teeLoader("variants & components", 3);

  try {
    const [threshRes, optRes] = await Promise.all([
      api(`/api/grade-thresholds?syllabus=${encodeURIComponent(state.syllabus)}`),
      api(`/api/grade-options?syllabus=${encodeURIComponent(state.syllabus)}`)
    ]);

    state._allThresholds = threshRes.thresholds || [];
    state._allOptions = optRes.options || [];
    state.marks = {};

    // Extract unique variants (e.g. "1", "2", "3")
    const variants = [...new Set(
      state._allThresholds
        .map(t => String(t.variant || ""))
        .filter(v => v !== "" && /^\d+$/.test(v))
    )].sort();

    if (variants.length > 0) {
      selVariant.innerHTML = '<option value="">Choose a variant…</option>';
      variants.forEach(v => {
        const opt = document.createElement("option");
        opt.value = v;
        opt.textContent = `Variant ${v} (${getZoneLabel(v)})`;
        selVariant.appendChild(opt);
      });
      selVariant.disabled = false;
      if (selVariant._sdInstance) selVariant._sdInstance.refresh();

      // Default to Variant 2 if available (Zone 4 / Pakistan), else first
      if (variants.includes("2")) {
        selVariant.value = "2";
      } else {
        selVariant.value = variants[0];
      }
      if (selVariant._sdInstance) selVariant._sdInstance.refresh();
      onVariantChange();
    } else {
      // If no variants at all (common in 2059/2058 which have no variant choice)
      selVariant.innerHTML = '<option value="">Standard (No Variants)</option>';
      selVariant.disabled = true;
      if (selVariant._sdInstance) selVariant._sdInstance.refresh();
      state.variant = "";
      processAverages();
      renderComponentTable();
      renderWeightingReference();
      updateOverallGrade();
    }
  } catch (err) {
    console.error("Failed to load syllabus thresholds:", err);
    tableEl.innerHTML = `<p class="revise-loading">Could not load data: ${esc(err.message)}</p>`;
  }
}

/* ── Variant change → reload table ───────────────────────────── */

function onVariantChange() {
  state.variant = selVariant.value;
  state.marks = {};
  hideResults();
  
  if (state.syllabus) {
    bodyEl.hidden = false;
    emptyEl.hidden = true;
    processAverages();
    renderComponentTable();
    renderWeightingReference();
    updateOverallGrade();
  }
}

/* ── Process historical averages for components ─────────────── */

function processAverages() {
  const paperGroups = {};

  state._allThresholds.forEach(t => {
    // If state.variant is set, skip rows with mismatching variant
    const vStr = String(t.variant || "");
    if (state.variant && vStr !== "" && vStr !== state.variant) return;

    const p = t.paper;
    if (!paperGroups[p]) {
      paperGroups[p] = {
        paper: p,
        variant: t.variant || "",
        max_mark: t.max_mark || 0,
        _max_year: t.year || 0,
        _max_session: t.session || "",
        grade_astar_sum: 0, grade_astar_cnt: 0,
        grade_a_sum: 0, grade_a_cnt: 0,
        grade_b_sum: 0, grade_b_cnt: 0,
        grade_c_sum: 0, grade_c_cnt: 0,
        grade_d_sum: 0, grade_d_cnt: 0,
        grade_e_sum: 0, grade_e_cnt: 0,
        grade_f_sum: 0, grade_f_cnt: 0,
        grade_g_sum: 0, grade_g_cnt: 0,
      };
    }

    const pg = paperGroups[p];
    if (t.grade_astar != null) { pg.grade_astar_sum += t.grade_astar; pg.grade_astar_cnt++; }
    if (t.grade_a != null) { pg.grade_a_sum += t.grade_a; pg.grade_a_cnt++; }
    if (t.grade_b != null) { pg.grade_b_sum += t.grade_b; pg.grade_b_cnt++; }
    if (t.grade_c != null) { pg.grade_c_sum += t.grade_c; pg.grade_c_cnt++; }
    if (t.grade_d != null) { pg.grade_d_sum += t.grade_d; pg.grade_d_cnt++; }
    if (t.grade_e != null) { pg.grade_e_sum += t.grade_e; pg.grade_e_cnt++; }
    if (t.grade_f != null) { pg.grade_f_sum += t.grade_f; pg.grade_f_cnt++; }
    if (t.grade_g != null) { pg.grade_g_sum += t.grade_g; pg.grade_g_cnt++; }
    // Use the MOST RECENT max_mark (not the historical maximum) so a reduced
    // mark scheme (e.g. 0580 P4 dropped from 130→100) shows the current value.
    const tYear = t.year || 0;
    const tSess = t.session || "";
    if (tYear > pg._max_year || (tYear === pg._max_year && tSess > pg._max_session)) {
      pg.max_mark = t.max_mark;
      pg._max_year = tYear;
      pg._max_session = tSess;
    }
  });

  state.thresholds = Object.values(paperGroups).map(pg => {
    return {
      paper: pg.paper,
      variant: state.variant || pg.variant,
      max_mark: pg.max_mark,
      grade_astar: pg.grade_astar_cnt ? Math.round(pg.grade_astar_sum / pg.grade_astar_cnt) : null,
      grade_a: pg.grade_a_cnt ? Math.round(pg.grade_a_sum / pg.grade_a_cnt) : null,
      grade_b: pg.grade_b_cnt ? Math.round(pg.grade_b_sum / pg.grade_b_cnt) : null,
      grade_c: pg.grade_c_cnt ? Math.round(pg.grade_c_sum / pg.grade_c_cnt) : null,
      grade_d: pg.grade_d_cnt ? Math.round(pg.grade_d_sum / pg.grade_d_cnt) : null,
      grade_e: pg.grade_e_cnt ? Math.round(pg.grade_e_sum / pg.grade_e_cnt) : null,
      grade_f: pg.grade_f_cnt ? Math.round(pg.grade_f_sum / pg.grade_f_cnt) : null,
      grade_g: pg.grade_g_cnt ? Math.round(pg.grade_g_sum / pg.grade_g_cnt) : null,
    };
  }).sort((a, b) => a.paper - b.paper);
}

/* ── Render component input table ────────────────────────────── */

function renderThreshChips(tRec) {
  if (!tRec) return `<span class="pm-no-thresh">—</span>`;
  const chips = [];
  if (tRec.grade_astar != null)
    chips.push(`<span class="pm-tch grade-Astar">A* ~${tRec.grade_astar}</span>`);
  chips.push(`<span class="pm-tch grade-A">A ~${tRec.grade_a}</span>`);
  chips.push(`<span class="pm-tch grade-B">B ~${tRec.grade_b}</span>`);
  chips.push(`<span class="pm-tch grade-C">C ~${tRec.grade_c}</span>`);
  chips.push(`<span class="pm-tch grade-D">D ~${tRec.grade_d}</span>`);
  chips.push(`<span class="pm-tch grade-E">E ~${tRec.grade_e}</span>`);
  if (tRec.grade_f != null)
    chips.push(`<span class="pm-tch grade-E">F ~${tRec.grade_f}</span>`);
  if (tRec.grade_g != null)
    chips.push(`<span class="pm-tch grade-E">G ~${tRec.grade_g}</span>`);
  return `<div class="pm-tch-row">${chips.join("")}</div>`;
}

function renderComponentTable() {
  if (!state.thresholds.length) {
    tableEl.innerHTML = `<p class="revise-loading">No thresholds found for this combination.</p>`;
    return;
  }

  let html = `
    <table class="gc-table">
      <thead><tr>
        <th>Component</th>
        <th>Marks</th>
        <th>Max</th>
        <th>Historical Average Boundaries</th>
        <th>Grade</th>
        <th class="gc-bar-col">Position</th>
      </tr></thead>
      <tbody>`;

  state.thresholds.forEach(t => {
    const compCode = `${t.paper}${t.variant || ""}`;
    const mKey = `${t.paper}_${t.variant || ""}`;
    const maxMark = t.max_mark || 0;

    html += `
      <tr data-mkey="${esc(mKey)}">
        <td data-label="Component">
          <b class="gc-comp-code">${esc(compCode)}</b>
          <span class="gc-comp-label">Paper ${t.paper}${t.variant ? " v" + t.variant : ""}</span>
        </td>
        <td data-label="Marks">
          <input type="number" min="0" max="${maxMark}" class="gc-marks-input"
                 data-mkey="${esc(mKey)}" data-max="${maxMark}" placeholder="—">
        </td>
        <td data-label="Max"><b>${maxMark}</b></td>
        <td data-label="Boundaries">${renderThreshChips(t)}</td>
        <td data-label="Grade">
          <div class="gc-grade-cell" data-mkey="${esc(mKey)}">${renderGradePill(null)}</div>
        </td>
        <td data-label="Position" class="gc-bar-col">
          <div class="gc-bar-cell" data-mkey="${esc(mKey)}">
            ${renderMiniThresholdBar(null, maxMark, t)}
          </div>
        </td>
      </tr>`;
  });

  html += `</tbody></table>`;
  tableEl.innerHTML = html;

  // Wire up input events
  tableEl.querySelectorAll(".gc-marks-input").forEach(input => {
    input.addEventListener("input", () => onMarkInput(input));
  });
}

/* ── Mark input handler ──────────────────────────────────────── */

function onMarkInput(input) {
  const mKey = input.dataset.mkey;
  const max = Number(input.dataset.max);
  const raw = input.value.trim();

  if (raw === "") {
    delete state.marks[mKey];
  } else {
    const num = parseFloat(raw);
    if (isNaN(num)) {
      input.value = "";
      delete state.marks[mKey];
    } else {
      const clamped = Math.min(max, Math.max(0, Math.round(num)));
      if (clamped !== num) input.value = clamped;  // snap visual back to valid range
      state.marks[mKey] = clamped;
    }
  }

  // Find average threshold record
  const [paper, variant] = mKey.split("_");
  const tRec = state.thresholds.find(t =>
    String(t.paper) === paper && String(t.variant || "") === variant);

  // Update per-component grade
  const score = state.marks[mKey];
  const calc = calculateGrade(score, tRec?.max_mark, tRec);
  const gradeCell = tableEl.querySelector(`.gc-grade-cell[data-mkey="${mKey}"]`);
  if (gradeCell) gradeCell.innerHTML = renderGradePill(calc.grade);

  // Update mini bar
  const barCell = tableEl.querySelector(`.gc-bar-cell[data-mkey="${mKey}"]`);
  if (barCell && tRec) barCell.innerHTML = renderMiniThresholdBar(score, tRec.max_mark, tRec);

  // Recalculate overall
  updateOverallGrade();
}

/* ── Overall grade calculation ───────────────────────────────── */

/* ── Weighting reference + A* targets ────────────────────────────
 *
 * Picks the extended (A*-bearing) option that matches the chosen variant and
 * has the most historical sessions, then shows how each of its papers is
 * weighted and what mark you'd need in each paper to reach an A*.
 */
function primaryOption() {
  const byCode = {};
  for (const opt of state._allOptions) {
    if (!opt.max_mark || opt.max_mark <= 0) continue;      // skip stale rows
    if (opt.grade_astar == null) continue;                 // extended only
    const codes = opt.components.split(/[\s,]+/).filter(Boolean);
    // Skip options where an explicit variant digit contradicts the selected variant.
    // Single-digit codes (bare paper number) are variant-agnostic — allow them.
    if (state.variant && !codes.every(c =>
      c.length < 2 || c.slice(-1) === state.variant)) continue;
    (byCode[opt.option_code] = byCode[opt.option_code] || []).push(opt);
  }
  // Prefer the option with more components (e.g. full A Level > A2-only).
  // Break ties by session count (more historical data = better averages).
  let best = null, bestN = 0, bestComps = 0;
  for (const rows of Object.values(byCode)) {
    const compCount = rows[0].components.split(/[\s,]+/).filter(Boolean).length;
    if (compCount > bestComps || (compCount === bestComps && rows.length > bestN)) {
      bestComps = compCount; bestN = rows.length; best = rows;
    }
  }
  return best;   // array of option rows sharing one code, or null
}

/* Break an option into its per-component weighting, using averaged raw maxes. */
function optionBreakdown(rows) {
  // Use the most recent session of this option as the reference structure.
  const sorted = [...rows].sort((a, b) => b.year - a.year ||
    String(b.session).localeCompare(String(a.session)));
  const opt = sorted[0];
  const optionMax = opt.max_mark;
  const codes = opt.components.split(/[\s,]+/).filter(Boolean);
  const comps = codes.map(code => {
    // Codes are either "42" (paper 4 variant 2) or bare "4" (variant-agnostic).
    const paper   = code.length >= 2 ? parseInt(code.slice(0, code.length - 1), 10) : parseInt(code, 10);
    const variant = code.length >= 2 ? code.slice(-1) : (state.variant || "");
    const rawMax = rawMaxFor(paper, variant, opt.year, opt.session) || 0;
    return { code, paper, variant, rawMax };
  });
  const sumRaw = comps.reduce((s, c) => s + c.rawMax, 0);
  comps.forEach(c => {
    c.factor = componentFactor(c.paper, c.rawMax, optionMax, sumRaw);
    c.weightedMax = c.rawMax * c.factor;
    c.pct = weightPct(state.syllabus, c.paper);
    if (c.pct == null && optionMax) c.pct = Math.round(c.weightedMax / optionMax * 100);
  });
  // Average A* threshold across this option's sessions (out of optionMax).
  const astars = rows.filter(r => r.max_mark === optionMax)
    .map(r => r.grade_astar).filter(v => v != null);
  const avgAstar = astars.length ? Math.round(astars.reduce((a, b) => a + b, 0) / astars.length) : null;
  return { opt, optionMax, comps, avgAstar };
}

function renderWeightingReference() {
  if (!weightEl) return;
  const rows = primaryOption();
  if (!rows || !rows.length) { weightEl.hidden = true; weightEl.innerHTML = ""; return; }

  const { optionMax, comps, avgAstar } = optionBreakdown(rows);
  // A* is reachable at a uniform performance level p = avgAstar / optionMax.
  const p = avgAstar != null && optionMax ? avgAstar / optionMax : null;

  const cards = comps.map(c => {
    const pct = c.pct != null ? c.pct : "—";
    return `
      <div class="gcw-card">
        <div class="gcw-card-head">
          <span class="gcw-paper">Paper ${c.paper}<span class="gcw-variant">v${c.variant}</span></span>
          <span class="gcw-weight">${pct}%</span>
        </div>
        <div class="gcw-hint">${esc(compHint(state.syllabus, c.paper))}</div>
        <div class="gcw-convert">
          <span class="gcw-raw">${c.rawMax}<em>raw</em></span>
          <span class="gcw-arrow">→</span>
          <span class="gcw-wtd">${Math.round(c.weightedMax)}<em>weighted</em></span>
        </div>
        <div class="gcw-factor">× ${c.factor.toFixed(3)} scaling</div>
      </div>`;
  }).join("");

  let targetHtml = "";
  if (p != null) {
    const targetRows = comps.map(c => {
      const need = Math.min(c.rawMax, Math.ceil(p * c.rawMax));
      return `
        <div class="gcw-target-row">
          <span class="gcw-t-paper">Paper ${c.paper} <em>v${c.variant}</em></span>
          <span class="gcw-t-need"><b>${need}</b> / ${c.rawMax}</span>
          <span class="gcw-t-pct">${Math.round(need / c.rawMax * 100)}%</span>
        </div>`;
    }).join("");
    targetHtml = `
      <div class="gcw-target">
        <div class="gcw-target-head">
          <span class="gcw-target-title">🎯 Marks needed for an <b class="grade-Astar" style="padding:1px 7px;border-radius:6px">A*</b></span>
          <span class="gcw-target-sub">A* needs ~${avgAstar}/${optionMax} (${Math.round(p * 100)}%) overall · balanced target per paper</span>
        </div>
        <div class="gcw-target-list">${targetRows}</div>
        <p class="gcw-target-note">Balanced target = the same ${Math.round(p * 100)}% in every paper. You can trade a weaker paper for a stronger one as long as your <b>weighted total clears ~${avgAstar}</b>.</p>
      </div>`;
  }

  weightEl.innerHTML = `
    <div class="gcw-block">
      <h2 class="gc-summary-title">How your papers are weighted</h2>
      <p class="gcw-lead">Cambridge scales each paper to a fixed share of <b>${optionMax}</b> marks
        (variant ${state.variant || "—"} · option ${esc(friendlyOptionCode(rows[0].option_code))}).
        Your raw marks are converted before being compared to the grade boundaries.</p>
      <div class="gcw-grid">${cards}</div>
      ${targetHtml}
    </div>`;
  weightEl.hidden = false;
}

function calculateOverallGrade(score, option) {
  if (score == null) return null;
  const grades = [];
  if (option.grade_astar != null) grades.push(["A*", option.grade_astar]);
  grades.push(["A", option.grade_a]);
  grades.push(["B", option.grade_b]);
  grades.push(["C", option.grade_c]);
  grades.push(["D", option.grade_d]);
  grades.push(["E", option.grade_e]);
  if (option.grade_f != null) grades.push(["F", option.grade_f]);
  if (option.grade_g != null) grades.push(["G", option.grade_g]);

  for (const [letter, threshold] of grades) {
    if (score >= threshold) return letter;
  }
  return "U";
}

function friendlyOptionCode(code) {
  if (/^OPT\d+$/i.test(code)) return `Option ${code.replace(/\D/g, "")}`;
  return code;
}

function updateOverallGrade() {
  if (!state._allOptions || !state._allOptions.length) {
    summEl.hidden = true;
    return;
  }

  // Group historical outcomes by Option Code
  const optionOutcomes = {};

  for (const opt of state._allOptions) {
    if (!opt.max_mark || opt.max_mark <= 0) continue;   // skip stale/degenerate rows
    const codes = opt.components.split(/[\s,]+/).filter(Boolean);

    // Check if the student has entered marks for ALL components of this option
    let complete = true;
    let weightedTotalSum = 0;
    const steps = [];

    // Resolve paper+variant from a component code.
    // Codes are either "42" (paper 4 variant 2) or bare "4" (variant-agnostic).
    // For bare codes use the selected variant so the mKey matches entered marks.
    function parseCode(code) {
      if (code.length >= 2) {
        return { paper: parseInt(code.slice(0, code.length - 1)), variantStr: code.slice(-1) };
      }
      return { paper: parseInt(code), variantStr: state.variant || "1" };
    }

    // Raw maxes for this option's components → proportional fallback if a
    // paper has no official weighting on file.
    const compMax = codes.map(code => {
      const { paper, variantStr } = parseCode(code);
      return rawMaxFor(paper, variantStr, opt.year, opt.session) || 0;
    });
    const sumRaw = compMax.reduce((a, b) => a + b, 0);

    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      const { paper, variantStr } = parseCode(code);
      const mKey = `${paper}_${variantStr}`;
      const mark = state.marks[mKey];

      if (mark == null || mark === "") {
        complete = false;
        break;
      } else {
        const factor = componentFactor(paper, compMax[i], opt.max_mark, sumRaw);
        weightedTotalSum += Number(mark) * factor;
        steps.push(`P${code} (${mark}×${factor.toFixed(2)})`);
      }
    }

    if (!complete) continue;

    const weightedTotal = Math.round(weightedTotalSum);
    const grade = calculateOverallGrade(weightedTotal, opt);
    const formulaStr = steps.join(" + ");

    if (!optionOutcomes[opt.option_code]) {
      optionOutcomes[opt.option_code] = {
        option_code: opt.option_code,
        components: opt.components,
        max_mark: opt.max_mark,
        is_as_level: opt.is_as_level,
        sessions: []
      };
    }
    optionOutcomes[opt.option_code].sessions.push({
      year: opt.year,
      session: opt.session,
      grade: grade,
      weightedTotal: weightedTotal,
      formulaStr: formulaStr,
      thresholds: opt
    });
  }

  // Render the predicted grade cards for each matching option
  const optionCodes = Object.keys(optionOutcomes).sort();
  if (optionCodes.length === 0) {
    summEl.innerHTML = `<h2 class="gc-summary-title">Predicted Overall Grade</h2>
      <p class="gc-option-hint" style="text-align: center; padding: 20px;">Enter marks for all papers in a component combination to see predictions.</p>`;
    summEl.hidden = false;
    return;
  }

  let html = `<h2 class="gc-summary-title">Predicted Overall Grade</h2><div class="gc-options-grid">`;

  for (const optCode of optionCodes) {
    const outcome = optionOutcomes[optCode];
    const allSessions = outcome.sessions.sort((a, b) => b.year - a.year || b.session.localeCompare(a.session));
    // Keep only the current syllabus era: component/option max marks change
    // across revisions (e.g. 5054 moved from a 145 total to a weighted 200),
    // and mixing eras would distort the average score and the A* boundary.
    const latestMax = allSessions[0].thresholds.max_mark;
    const sessions = allSessions.filter(s => s.thresholds.max_mark === latestMax);
    outcome.max_mark = latestMax;
    const totalSessions = sessions.length;

    // Calculate grade distribution statistics
    const gradeCounts = {};
    sessions.forEach(s => {
      gradeCounts[s.grade] = (gradeCounts[s.grade] || 0) + 1;
    });

    // Find the most frequent grade (predicted grade)
    let predictedGrade = "U";
    let maxCount = -1;
    for (const [g, count] of Object.entries(gradeCounts)) {
      if (count > maxCount) {
        maxCount = count;
        predictedGrade = g;
      }
    }

    // Sort grades by hierarchy for the distribution description
    const sortedGrades = Object.entries(gradeCounts).sort((a, b) => {
      const order = { "A*": 8, "A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1, "U": 0 };
      return (order[b[0]] || 0) - (order[a[0]] || 0);
    });

    const distStrings = sortedGrades.map(([g, count]) => {
      const pct = Math.round((count / totalSessions) * 100);
      return `<span style="font-weight:600; color:var(--text);">${g}</span>: ${pct}%`;
    });
    const distHtml = distStrings.join(" | ");

    const gClass = predictedGrade === "A*" ? "grade-Astar" : `grade-${predictedGrade}`;
    const compChips = outcome.components.split(/[\s,]+/).filter(Boolean)
      .map(c => `<span class="gc-comp-chip">${c}</span>`).join("");

    // Calculate overall average weighted score text
    const avgWeightedScore = Math.round(sessions.reduce((sum, s) => sum + s.weightedTotal, 0) / totalSessions);

    // A* gap: how far the weighted total is from the average A* boundary.
    const optAstars = sessions.map(s => s.thresholds.grade_astar).filter(v => v != null);
    const avgAstar = optAstars.length
      ? Math.round(optAstars.reduce((a, b) => a + b, 0) / optAstars.length) : null;
    let astarNote = "";
    if (avgAstar != null) {
      const gap = avgAstar - avgWeightedScore;
      astarNote = gap <= 0
        ? `<div class="gc-astar-note is-hit">🎉 Clears A* — ~${avgWeightedScore} vs A* ~${avgAstar}</div>`
        : `<div class="gc-astar-note">A* is ~${avgAstar}/${outcome.max_mark} — you need <b>+${gap}</b> more weighted marks</div>`;
    }

    const variantLabel = state.variant ? `v${state.variant}` : "";
    const asBadge = outcome.is_as_level
      ? `<span class="gc-as-badge">AS</span>` : "";

    html += `
      <div class="gc-option-card gc-option-complete">
        <!-- header row: option code + AS badge -->
        <div class="gc-card-topbar">
          <span class="gc-option-code">${esc(friendlyOptionCode(outcome.option_code))} ${variantLabel}</span>
          ${asBadge}
        </div>

        <!-- component chips -->
        <div class="gc-option-comps">${compChips}</div>

        <!-- grade hero -->
        <div class="gc-card-hero">
          <div class="gc-card-hero-left">
            <div class="gc-card-label">Predicted Grade</div>
            <span class="gc-big-grade ${gClass}">${predictedGrade}</span>
          </div>
          <div class="gc-card-hero-right">
            <div class="gc-card-label">Weighted Score</div>
            <div class="gc-card-score">~${avgWeightedScore}<span class="gc-card-score-max"> / ${outcome.max_mark}</span></div>
          </div>
        </div>

        ${astarNote}

        <!-- historical distribution -->
        <div class="gc-dist-section">
          <div class="gc-dist-label">Historical outcomes across ${totalSessions} sessions</div>
          <div class="gc-dist-pills">${sortedGrades.map(([g, count]) => {
            const pct = Math.round((count / totalSessions) * 100);
            const gc2 = g === "A*" ? "grade-Astar" : `grade-${g}`;
            return `<span class="gc-dist-pill ${gc2}">${g} <em>${pct}%</em></span>`;
          }).join("")}</div>
        </div>

        <button class="gc-history-btn"
                onclick="toggleBreakdown('${outcome.option_code}')">
          Show session history ▾
        </button>

        <div id="breakdown-${outcome.option_code}" class="gc-breakdown-panel" style="display:none;">
          <table class="gc-breakdown-table">
            <thead>
              <tr>
                <th>Session</th>
                <th>Weighted</th>
                <th>Grade</th>
                <th>Boundaries</th>
              </tr>
            </thead>
            <tbody>
              ${sessions.map(s => {
                const sLabel = `${s.year} ${SESSION_LABEL[s.session] || s.session.toUpperCase()}`;
                const t = s.thresholds;
                const boundaryStr = [
                  t.grade_astar != null ? `A*:${t.grade_astar}` : '',
                  `A:${t.grade_a}`, `B:${t.grade_b}`,
                  `C:${t.grade_c}`, `D:${t.grade_d}`, `E:${t.grade_e}`
                ].filter(Boolean).join(", ");
                const sGc = s.grade === "A*" ? "grade-Astar" : `grade-${s.grade}`;
                return `
                  <tr>
                    <td><b>${esc(sLabel)}</b></td>
                    <td>${s.weightedTotal}</td>
                    <td><span class="pm-tch ${sGc}" style="padding:2px 6px;font-size:.68rem;border-radius:4px;font-weight:700;">${s.grade}</span></td>
                    <td class="gc-bnd-cell">${boundaryStr}</td>
                  </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  html += `</div>`;
  summEl.innerHTML = html;
  summEl.hidden = false;
}

/* ── Global breakdown toggle handler ─────────────────────────── */

window.toggleBreakdown = function(optCode) {
  const el = document.getElementById(`breakdown-${optCode}`);
  if (el) {
    const isHidden = el.style.display === "none";
    el.style.display = isHidden ? "block" : "none";
    const btn = el.previousElementSibling;
    if (btn) {
      btn.textContent = isHidden ? "Hide Session History ▴" : "Show Session History ▾";
    }
  }
};

/* ── Helpers ──────────────────────────────────────────────────── */

function hideResults() {
  bodyEl.hidden = true;
  summEl.hidden = true;
  if (weightEl) { weightEl.hidden = true; weightEl.innerHTML = ""; }
  emptyEl.hidden = false;
  tableEl.innerHTML = "";
  summEl.innerHTML = "";
}
