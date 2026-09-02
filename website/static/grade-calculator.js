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
    if (t.max_mark > pg.max_mark) pg.max_mark = t.max_mark;
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
  const val = input.value.trim();

  if (val === "") {
    delete state.marks[mKey];
  } else {
    state.marks[mKey] = Math.min(max, Math.max(0, Number(val)));
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

function getScalingFactor(syllabus, paper, year) {
  if (syllabus === "5054") {
    if (paper === 1) return 1.5;             // MCQ: 40 -> 60
    if (paper === 2) return 4 / 3;           // Theory: 75 -> 100
    if (paper === 3 || paper === 4) return 4 / 3; // Practical/ATP: 30 -> 40
  }
  if (syllabus === "0625") {
    if (paper === 1 || paper === 2) return 1.5;  // MCQ: 40 -> 60
    if (paper === 3 || paper === 4) return 1.25; // Theory: 80 -> 100
    if (paper === 5 || paper === 6) return 1.0;  // Practical/ATP: 40 -> 40
  }
  if (syllabus === "4024") {
    if (paper === 1) return 1.25; // Paper 1: 80 -> 100
    if (paper === 2) return 1.0;  // Paper 2: 100 -> 100
  }
  if (syllabus === "2210" || syllabus === "0478") {
    if (year <= 2022) return 5 / 6; // 75 -> 62.5
    return 1.0;
  }
  if (syllabus === "9702") {
    if (paper === 1) return 1.0;
    if (paper === 2) return 1.0;
    if (paper === 3) return 0.75; // Practical: 40 -> 30
    if (paper === 4) return 1.0;
    if (paper === 5) return 1.0;
  }
  return 1.0;
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
    const codes = opt.components.split(/[\s,]+/).filter(Boolean);
    
    // Check if the student has entered marks for ALL components of this option
    let complete = true;
    let weightedTotalSum = 0;
    const steps = [];

    for (const code of codes) {
      const paper = code.length >= 2 ? parseInt(code[0]) : parseInt(code);
      const variant = code.length >= 2 ? parseInt(code.substring(1)) : 1;
      const mKey = `${paper}_${variant}`;
      const mark = state.marks[mKey];

      if (mark == null || mark === "") {
        complete = false;
        break;
      } else {
        const factor = getScalingFactor(state.syllabus, paper, opt.year);
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
    const sessions = outcome.sessions.sort((a, b) => b.year - a.year || b.session.localeCompare(a.session));
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

    html += `
      <div class="gc-option-card gc-option-complete" style="display:flex; flex-direction:column; gap:12px;">
        <div class="gc-option-header">
          <span class="gc-option-code">${esc(friendlyOptionCode(outcome.option_code))}</span>
          ${outcome.is_as_level ? '<span class="gc-as-badge">AS</span>' : ""}
        </div>
        <div class="gc-option-comps">${compChips}</div>
        <div class="gc-option-score" style="margin-top:0;">
          <span class="gc-option-marks" style="font-size:1.15rem;">~${avgWeightedScore} / ${outcome.max_mark}</span>
          <span class="gc-option-pct" style="font-size:0.8rem; padding:2px 8px;">Weighted</span>
        </div>
        <div class="gc-option-grade" style="margin:4px 0;">
          <span class="gc-big-grade ${gClass}">${predictedGrade}</span>
        </div>
        <div class="gc-dist-bar" style="font-size:0.75rem; color:var(--muted); line-height:1.4; border-top:1px solid var(--line); padding-top:8px;">
          <b>Historical outcomes:</b><br>${distHtml}
        </div>
        <button class="btn btn-secondary" style="font-size:0.72rem; padding:6px 10px; width:100%; text-align:center; border-radius:8px;" 
                onclick="toggleBreakdown('${outcome.option_code}')">
          Show Session History ▾
        </button>
        
        <div id="breakdown-${outcome.option_code}" class="gc-breakdown-panel" style="display:none; overflow-x:auto; width:100%; border-top:1px dashed var(--line); padding-top:10px;">
          <table style="width:100%; font-size:0.72rem; text-align:left; border-collapse:collapse;">
            <thead>
              <tr style="border-bottom:1px solid var(--line); color:var(--muted);">
                <th style="padding:4px 0;">Session</th>
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
                  `A:${t.grade_a}`,
                  `B:${t.grade_b}`,
                  `C:${t.grade_c}`,
                  `D:${t.grade_d}`,
                  `E:${t.grade_e}`
                ].filter(Boolean).join(", ");

                return `
                  <tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
                    <td style="padding:6px 0; font-weight:600;">${esc(sLabel)}</td>
                    <td>${s.weightedTotal}</td>
                    <td><span class="pm-tch grade-${s.grade}" style="padding:2px 6px; font-size:0.68rem; border-radius:4px; font-weight:700;">${s.grade}</span></td>
                    <td style="color:var(--muted); font-size:0.65rem;">${boundaryStr}</td>
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
  emptyEl.hidden = false;
  tableEl.innerHTML = "";
  summEl.innerHTML = "";
}
