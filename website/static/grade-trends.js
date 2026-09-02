/* grade-trends.js — Grade threshold trend analyser with Chart.js.
 *
 * Component tab:  line chart of a single paper's grade boundary across years,
 *                 one line per variant.
 * Overall tab:    line chart of option-level thresholds across years,
 *                 one line per option_code.
 */

import { api } from "/auth.js";
import { esc } from "/progress-shared.js";

/* ── Subject list (same as grade-calculator) ─────────────────── */

const SUBJECTS = [
  { code: "5054", name: "O Level Physics",           papers: [1, 2] },
  { code: "0625", name: "IGCSE Physics",             papers: [1, 2, 4] },
  { code: "4024", name: "O Level Mathematics D",     papers: [1, 2] },
  { code: "0580", name: "IGCSE Mathematics",         papers: [2, 4] },
  { code: "2210", name: "O Level Computer Science",  papers: [1, 2] },
  { code: "0478", name: "IGCSE Computer Science",    papers: [1, 2] },
  { code: "9702", name: "A Level Physics",           papers: [1, 2, 4, 5] },
  { code: "9709", name: "A Level Mathematics",       papers: [1, 3, 4, 5] },
];

const SESSION_LABEL = { s: "M/J", w: "O/N", m: "F/M" };
const VARIANT_COLORS = {
  "1": "hsl(220, 85%, 58%)",   // blue
  "2": "hsl(340, 75%, 55%)",   // pink
  "3": "hsl(160, 70%, 42%)",   // teal
  "":  "hsl(40, 90%, 50%)",    // gold (no variant)
};
const OPTION_PALETTE = [
  "hsl(220, 85%, 58%)", "hsl(340, 75%, 55%)", "hsl(160, 70%, 42%)",
  "hsl(40, 90%, 50%)", "hsl(280, 65%, 55%)", "hsl(20, 80%, 55%)",
  "hsl(200, 75%, 50%)", "hsl(100, 60%, 45%)",
];

let chartInstance = null;

/* ── DOM refs ────────────────────────────────────────────────── */

const tabBtns          = document.querySelectorAll(".gt-tab");
const filtersComp      = document.getElementById("gt-filters-component");
const filtersOpt       = document.getElementById("gt-filters-overall");
const chartWrap        = document.getElementById("gt-chart-wrap");
const chartCanvas      = document.getElementById("gt-chart");
const tableWrap        = document.getElementById("gt-table-wrap");
const emptyEl          = document.getElementById("gt-empty");

// Component tab controls
const selSyl           = document.getElementById("gt-syllabus");
const selPaper         = document.getElementById("gt-paper");
const selGrade         = document.getElementById("gt-grade");
const selMode          = document.getElementById("gt-mode");

// Overall tab controls
const selOptSyl        = document.getElementById("gt-opt-syllabus");
const selOptCode       = document.getElementById("gt-opt-code");
const selOptGrade      = document.getElementById("gt-opt-grade");
const selOptMode       = document.getElementById("gt-opt-mode");

let activeTab = "component";
let compData = [];      // raw threshold rows for component tab
let optData  = [];      // raw grade_options rows for overall tab

/* ── Populate subject dropdowns ──────────────────────────────── */

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

  for (const sel of [selSyl, selOptSyl]) {
    sel.innerHTML = '<option value="">Select subject…</option>';
  }

  subjectsToRender.forEach(s => {
    for (const sel of [selSyl, selOptSyl]) {
      const opt = document.createElement("option");
      opt.value = s.code;
      opt.textContent = `${s.name} (${s.code})`;
      sel.appendChild(opt);
    }
  });

  for (const sel of [selSyl, selOptSyl]) {
    if (sel._sdInstance) sel._sdInstance.refresh();
  }
}
initSubjects();

/* ── Tab switching ───────────────────────────────────────────── */

tabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    activeTab = btn.dataset.tab;
    tabBtns.forEach(b => b.classList.toggle("active", b === btn));
    filtersComp.hidden = activeTab !== "component";
    filtersOpt.hidden  = activeTab !== "overall";
    hideResults();
    // Re-render if data exists
    if (activeTab === "component" && compData.length) renderComponentChart();
    else if (activeTab === "overall" && optData.length) renderOverallChart();
  });
});

/* ── Component tab events ────────────────────────────────────── */

selSyl.addEventListener("change", () => {
  const code = selSyl.value;
  selPaper.innerHTML = '<option value="">—</option>';
  selPaper.disabled = true;
  hideResults();
  compData = [];

  if (!code) {
    if (selPaper._sdInstance) selPaper._sdInstance.refresh();
    return;
  }
  const subj = SUBJECTS.find(s => s.code === code);
  if (subj) {
    subj.papers.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = `Paper ${p}`;
      selPaper.appendChild(opt);
    });
    selPaper.disabled = false;
  }
  if (selPaper._sdInstance) selPaper._sdInstance.refresh();
});

selPaper.addEventListener("change", loadComponentData);
selGrade.addEventListener("change", () => { if (compData.length) renderComponentChart(); });
selMode.addEventListener("change",  () => { if (compData.length) renderComponentChart(); });

async function loadComponentData() {
  const syllabus = selSyl.value;
  const paper = selPaper.value;
  hideResults();
  compData = [];

  if (!syllabus || !paper) return;

  try {
    const { thresholds } = await api(
      `/api/grade-thresholds/history?syllabus=${syllabus}&paper=${paper}`);
    compData = thresholds || [];
    if (compData.length) renderComponentChart();
    else {
      emptyEl.hidden = false;
      emptyEl.querySelector("p").textContent = "No threshold data found for this paper.";
    }
  } catch (err) {
    console.error(err);
  }
}

/* ── Overall tab events ──────────────────────────────────────── */

selOptSyl.addEventListener("change", loadOverallData);
selOptCode.addEventListener("change", () => { if (optData.length) renderOverallChart(); });
selOptGrade.addEventListener("change", () => { if (optData.length) renderOverallChart(); });
selOptMode.addEventListener("change",  () => { if (optData.length) renderOverallChart(); });

async function loadOverallData() {
  const syllabus = selOptSyl.value;
  hideResults();
  optData = [];
  selOptCode.innerHTML = '<option value="">All options</option>';
  selOptCode.disabled = true;
  if (selOptCode._sdInstance) selOptCode._sdInstance.refresh();

  if (!syllabus) return;

  try {
    const { options } = await api(
      `/api/grade-options/history?syllabus=${syllabus}`);
    optData = options || [];

    // Populate option codes
    const codes = [...new Set(optData.map(o => o.option_code))].sort();
    codes.forEach(c => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = friendlyCode(c);
      selOptCode.appendChild(opt);
    });
    selOptCode.disabled = false;
    if (selOptCode._sdInstance) selOptCode._sdInstance.refresh();

    if (optData.length) renderOverallChart();
    else {
      emptyEl.hidden = false;
      emptyEl.querySelector("p").textContent = "No option data found for this subject.";
    }
  } catch (err) {
    console.error(err);
  }
}

/* ── Component chart rendering ───────────────────────────────── */

function renderComponentChart() {
  const gradeKey = selGrade.value;
  const pctMode = selMode.value === "pct";
  const gradeName = selGrade.options[selGrade.selectedIndex].text;

  // Group by variant
  const variants = {};
  for (const t of compData) {
    const v = String(t.variant || "");
    if (!variants[v]) variants[v] = [];
    variants[v].push(t);
  }

  // Build labels (sorted chronologically)
  const allLabels = new Set();
  for (const rows of Object.values(variants)) {
    for (const t of rows) {
      allLabels.add(`${SESSION_LABEL[t.session] || t.session} ${t.year}`);
    }
  }
  const labels = [...allLabels].sort((a, b) => {
    const [, ya] = a.split(" "), [, yb] = b.split(" ");
    if (ya !== yb) return Number(ya) - Number(yb);
    return a.localeCompare(b);
  });

  const datasets = Object.entries(variants).map(([v, rows]) => {
    const labelMap = {};
    for (const t of rows) {
      const lbl = `${SESSION_LABEL[t.session] || t.session} ${t.year}`;
      const val = t[gradeKey];
      if (val == null) continue;
      labelMap[lbl] = pctMode ? Math.round((val / t.max_mark) * 100) : val;
    }
    return {
      label: v ? `Variant ${v}` : "All variants",
      data: labels.map(l => labelMap[l] ?? null),
      borderColor: VARIANT_COLORS[v] || VARIANT_COLORS["1"],
      backgroundColor: (VARIANT_COLORS[v] || VARIANT_COLORS["1"]).replace(")", ", 0.1)").replace("hsl", "hsla"),
      tension: 0.3,
      pointRadius: 4,
      pointHoverRadius: 7,
      spanGaps: true,
    };
  });

  drawChart(labels, datasets, {
    yLabel: pctMode ? `${gradeName} threshold (% of max)` : `${gradeName} threshold (marks)`,
    pctMode,
  });
  renderComponentTable(gradeKey, pctMode);
}

/* ── Overall chart rendering ─────────────────────────────────── */

function renderOverallChart() {
  const gradeKey = selOptGrade.value;
  const pctMode = selOptMode.value === "pct";
  const gradeName = selOptGrade.options[selOptGrade.selectedIndex].text;
  const filterCode = selOptCode.value;

  const filtered = filterCode
    ? optData.filter(o => o.option_code === filterCode)
    : optData;

  // Group by option_code
  const groups = {};
  for (const o of filtered) {
    if (!groups[o.option_code]) groups[o.option_code] = [];
    groups[o.option_code].push(o);
  }

  const allLabels = new Set();
  for (const rows of Object.values(groups)) {
    for (const o of rows) {
      allLabels.add(`${SESSION_LABEL[o.session] || o.session} ${o.year}`);
    }
  }
  const labels = [...allLabels].sort((a, b) => {
    const [, ya] = a.split(" "), [, yb] = b.split(" ");
    if (ya !== yb) return Number(ya) - Number(yb);
    return a.localeCompare(b);
  });

  const datasets = Object.entries(groups).map(([code, rows], i) => {
    const labelMap = {};
    for (const o of rows) {
      const lbl = `${SESSION_LABEL[o.session] || o.session} ${o.year}`;
      const val = o[gradeKey];
      if (val == null) continue;
      labelMap[lbl] = pctMode ? Math.round((val / o.max_mark) * 100) : val;
    }
    return {
      label: friendlyCode(code),
      data: labels.map(l => labelMap[l] ?? null),
      borderColor: OPTION_PALETTE[i % OPTION_PALETTE.length],
      backgroundColor: OPTION_PALETTE[i % OPTION_PALETTE.length].replace(")", ", 0.1)").replace("hsl", "hsla"),
      tension: 0.3,
      pointRadius: 4,
      pointHoverRadius: 7,
      spanGaps: true,
    };
  });

  drawChart(labels, datasets, {
    yLabel: pctMode ? `${gradeName} threshold (% of max)` : `${gradeName} threshold (marks)`,
    pctMode,
  });
  renderOverallTable(gradeKey, pctMode, filtered);
}

/* ── Shared Chart.js draw ────────────────────────────────────── */

function drawChart(labels, datasets, opts) {
  chartWrap.hidden = false;
  emptyEl.hidden = true;

  if (chartInstance) chartInstance.destroy();

  const isDark = document.documentElement.getAttribute("data-theme") === "dark"
    || window.matchMedia("(prefers-color-scheme: dark)").matches;

  const gridColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)";
  const textColor = isDark ? "rgba(255,255,255,0.7)"  : "rgba(0,0,0,0.6)";

  chartInstance = new Chart(chartCanvas, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: textColor, font: { family: "Hanken Grotesk", size: 13 } } },
        tooltip: {
          backgroundColor: isDark ? "rgba(30,30,40,0.95)" : "rgba(255,255,255,0.95)",
          titleColor: isDark ? "#fff" : "#111",
          bodyColor: isDark ? "#ddd" : "#333",
          borderColor: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)",
          borderWidth: 1,
          padding: 12,
          cornerRadius: 10,
          titleFont: { family: "Hanken Grotesk", weight: "600" },
          bodyFont: { family: "Hanken Grotesk" },
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y;
              return v != null ? `${ctx.dataset.label}: ${v}${opts.pctMode ? "%" : ""}` : "";
            }
          }
        },
      },
      scales: {
        x: {
          ticks: { color: textColor, font: { family: "Hanken Grotesk", size: 11 }, maxRotation: 60 },
          grid: { color: gridColor },
        },
        y: {
          title: { display: true, text: opts.yLabel, color: textColor, font: { family: "Hanken Grotesk", size: 12 } },
          ticks: { color: textColor, font: { family: "Hanken Grotesk" } },
          grid: { color: gridColor },
          min: 0,
          ...(opts.pctMode ? { max: 100 } : {}),
        },
      },
    },
  });
}

/* ── Component data table ────────────────────────────────────── */

function renderComponentTable(gradeKey, pctMode) {
  const gradeName = selGrade.options[selGrade.selectedIndex].text;

  let html = `<table class="gt-data-table">
    <thead><tr>
      <th class="gt-sortable" data-sort="year">Year ↕</th>
      <th>Session</th>
      <th>Variant</th>
      <th>Max</th>
      <th class="gt-sortable" data-sort="val">${gradeName} threshold ↕</th>
      ${pctMode ? `<th>% of max</th>` : ""}
    </tr></thead><tbody>`;

  const rows = compData
    .filter(t => t[gradeKey] != null)
    .map(t => ({
      year: t.year,
      session: SESSION_LABEL[t.session] || t.session,
      variant: t.variant || "—",
      max: t.max_mark,
      val: t[gradeKey],
      pct: Math.round((t[gradeKey] / t.max_mark) * 100),
    }))
    .sort((a, b) => a.year - b.year);

  for (const r of rows) {
    html += `<tr>
      <td>${r.year}</td><td>${esc(r.session)}</td><td>${esc(r.variant)}</td>
      <td>${r.max}</td><td><b>${r.val}</b></td>
      ${pctMode ? `<td>${r.pct}%</td>` : ""}
    </tr>`;
  }
  html += `</tbody></table>`;
  tableWrap.innerHTML = html;
  tableWrap.hidden = false;

  wireSortableHeaders();
}

/* ── Overall data table ──────────────────────────────────────── */

function renderOverallTable(gradeKey, pctMode, data) {
  const gradeName = selOptGrade.options[selOptGrade.selectedIndex].text;

  let html = `<table class="gt-data-table">
    <thead><tr>
      <th class="gt-sortable" data-sort="year">Year ↕</th>
      <th>Session</th>
      <th>Option</th>
      <th>Components</th>
      <th>Max</th>
      <th class="gt-sortable" data-sort="val">${gradeName} threshold ↕</th>
      ${pctMode ? `<th>% of max</th>` : ""}
    </tr></thead><tbody>`;

  const rows = data
    .filter(o => o[gradeKey] != null)
    .map(o => ({
      year: o.year,
      session: SESSION_LABEL[o.session] || o.session,
      code: friendlyCode(o.option_code),
      comps: o.components,
      max: o.max_mark,
      val: o[gradeKey],
      pct: Math.round((o[gradeKey] / o.max_mark) * 100),
    }))
    .sort((a, b) => a.year - b.year);

  for (const r of rows) {
    html += `<tr>
      <td>${r.year}</td><td>${esc(r.session)}</td>
      <td><b>${esc(r.code)}</b></td><td>${esc(r.comps)}</td>
      <td>${r.max}</td><td><b>${r.val}</b></td>
      ${pctMode ? `<td>${r.pct}%</td>` : ""}
    </tr>`;
  }
  html += `</tbody></table>`;
  tableWrap.innerHTML = html;
  tableWrap.hidden = false;

  wireSortableHeaders();
}

/* ── Sortable table headers ──────────────────────────────────── */

let sortDir = {};

function wireSortableHeaders() {
  tableWrap.querySelectorAll(".gt-sortable").forEach(th => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortDir[key] = !(sortDir[key] ?? false);
      const tbody = th.closest("table").querySelector("tbody");
      const rows = [...tbody.querySelectorAll("tr")];
      const colIdx = [...th.parentElement.children].indexOf(th);
      rows.sort((a, b) => {
        const va = a.children[colIdx]?.textContent.trim();
        const vb = b.children[colIdx]?.textContent.trim();
        const na = parseFloat(va), nb = parseFloat(vb);
        const cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : va.localeCompare(vb);
        return sortDir[key] ? -cmp : cmp;
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
}

/* ── Helpers ──────────────────────────────────────────────────── */

function friendlyCode(code) {
  if (/^OPT\d+$/i.test(code)) return `Option ${code.replace(/\D/g, "")}`;
  return code;
}

function hideResults() {
  chartWrap.hidden = true;
  tableWrap.hidden = true;
  tableWrap.innerHTML = "";
  emptyEl.hidden = false;
  emptyEl.querySelector("p").textContent = "Select a subject and paper above to see grade threshold trends.";
  if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
}
