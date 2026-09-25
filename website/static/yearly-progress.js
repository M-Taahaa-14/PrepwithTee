/* Yearly Progress — paper-by-paper score tracker + Enter Marks modal.
 *
 * Extracted from revise.js. Handles the past-papers view:
 * year/session/paper grid, grade-colored dots, the Phase 2
 * rebuilt "Enter Marks" modal with live grade calculation,
 * threshold bars, retake history, and progress rings summary.
 */

import { requireProfile } from "/auth.js";
import { lockElement, setPlan, setRole } from "/upgrade-modal.js";
import {
  BOARD_OF_GRADE,
  api, teeLoader, esc, key, paperKey,
  subjectFor, mySubjects, compLabel,
  renderSubjectStrip, highlightSubjectPill,
  calculateGrade, renderGradePill, renderMiniThresholdBar,
  renderProgressRing,
} from "/progress-shared.js";

const state = {
  meta: null,
  enrolled: [],
  board: null,
  syllabus: null,
  paperTree: {},
  papers: new Map(),
  paperComp: "",
};

/* ---- Boot ---------------------------------------------------------------- */

const dataPromise = Promise.all([api("/api/meta"), api("/api/enrollments")]);
dataPromise.catch(() => {});

const deepLink = new URLSearchParams(location.search).get("syllabus");

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
    document.getElementById("paper-list").innerHTML =
      `<p class="revise-loading">Couldn't load your subjects: ${esc(err.message)}</p>`;
    return;
  }

  renderSubjects();

  const visible = mySubjects(state.meta, state.board, state.enrolled);
  const first = (deepLink && visible.some(s => s.syllabus === deepLink)) ? deepLink
              : state.enrolled[0]
              || visible[0]?.syllabus;
  if (first) selectSubject(first);
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
}

async function selectSubject(code) {
  state.syllabus = code;
  highlightSubjectPill(code);

  const box = document.getElementById("paper-list");
  box.innerHTML = teeLoader("papers", 4);

  await renderPapers();
}

/* ---- Paper list ---------------------------------------------------------- */

const SESSION = { s: "May/Jun", w: "Oct/Nov", m: "Feb/Mar" };

async function renderPapers() {
  const box = document.getElementById("paper-list");
  const code = state.syllabus;
  if (!code) {
    box.innerHTML = `<p class="revise-loading">Pick a subject first.</p>`;
    return;
  }

  try {
    if (!state.paperTree[code]) {
      state.paperTree[code] = await api(
        `/api/library/tree?syllabus=${encodeURIComponent(code)}`);
    }
    const { papers } = await api(
      `/api/papers-progress?syllabus=${encodeURIComponent(code)}`);
    state.papers = new Map(papers.map(p => [paperKey(p), p]));
  } catch (err) {
    box.innerHTML = `<p class="revise-loading">Couldn't load papers: ${esc(err.message)}</p>`;
    return;
  }

  const tree = state.paperTree[code];
  let done = 0, started = 0, totalPapers = 0;
  let totalScore = 0, scoreCount = 0, bestScore = 0;

  const perComp = new Map();
  const tally = p => perComp.get(p) || perComp.set(p, { total: 0, done: 0, started: 0 }).get(p);

  const years = (tree.years || []).map(y => {
    const byComp = new Map();
    for (const sess of y.sessions) {
      for (const f of sess.files.filter(x => x.kind === "qp")) {
        const rec = state.papers.get(paperKey({
          year: y.year, session: sess.session,
          paper: f.paper, variant: f.variant || "" }));
        const status = rec?.status || "not_started";
        const t = tally(f.paper);
        t.total++; totalPapers++;
        if (status === "confident") { done++; t.done++; }
        else if (status === "learning") { started++; t.started++; }
        if (!byComp.has(f.paper)) byComp.set(f.paper, []);

        // Score tracking for rings
        if (rec?.score != null && rec?.max_score) {
          const pct = Math.round((rec.score / rec.max_score) * 100);
          totalScore += pct;
          scoreCount++;
          if (pct > bestScore) bestScore = pct;
        }

        const gradePillHtml = rec?.grade
          ? renderGradePill(rec.grade)
          : (rec?.score != null ? `<span class="pap-grade-pill grade-none">${rec.score}/${rec.max_score || '?'}</span>` : (status === "confident" ? `<span class="pap-grade-pill grade-none">Done</span>` : ""));

        byComp.get(f.paper).push(`
          <div class="pap-row">
            <span class="pap-name">
              <strong>${esc(SESSION[sess.session] || sess.session)} ${y.year}</strong>
              <em>Paper ${f.paper}${f.variant ? " · variant " + esc(f.variant) : ""}</em>
            </span>
            <div class="pap-grade-badge">${gradePillHtml}</div>
            <span class="pap-seg" data-year="${y.year}" data-session="${esc(sess.session)}"
                  data-paper="${f.paper}" data-variant="${esc(f.variant || "")}">
              ${[["not_started", "Not done"], ["learning", "Started"],
                 ["confident", "Done"]].map(([v, l]) => `
                <button type="button" class="pap-btn pap-${v}${status === v ? " on" : ""}"
                        data-status="${v}">${l}</button>`).join("")}
              <button type="button" class="pap-btn pap-score-btn" data-year="${y.year}" data-session="${esc(sess.session)}" data-paper="${f.paper}" data-variant="${esc(f.variant || "")}" title="Enter marks &amp; calculate grade">✎ Marks</button>
            </span>
          </div>`);
      }
    }
    if (!byComp.size) return "";
    const total = [...byComp.values()].reduce((s, r) => s + r.length, 0);
    const groups = [...byComp.keys()].sort((a, b) => a - b).map(p => `
      <div class="pap-group" data-comp="${p}">
        <p class="pap-group-head">${esc(compLabel(state.meta, code, p))}
          <span>${byComp.get(p).length}</span></p>
        ${byComp.get(p).join("")}
      </div>`).join("");
    return `
      <details class="pap-year" data-comps="${[...byComp.keys()].join(",")}">
        <summary><b>${y.year}</b><span>${total} papers</span></summary>
        <div class="pap-rows">${groups}</div>
      </details>`;
  }).join("");

  if (!years) {
    box.innerHTML = `<p class="revise-loading">No papers in the archive for this subject yet.</p>`;
    return;
  }

  const comps = [...perComp.keys()].sort((a, b) => a - b);
  const filter = comps.length < 2 ? "" : `
    <div class="pap-filter" id="pap-filter">
      <button type="button" class="pap-fbtn on" data-comp="">All papers
        <span>${done}/${[...perComp.values()].reduce((s, c) => s + c.total, 0)}</span></button>
      ${comps.map(p => `
        <button type="button" class="pap-fbtn" data-comp="${p}">${esc(compLabel(state.meta, code, p))}
          <span>${perComp.get(p).done}/${perComp.get(p).total}</span></button>`).join("")}
    </div>`;

  box.innerHTML = `
    <p class="pap-summary"><strong>${done}</strong> done ·
      <strong>${started}</strong> started · tick them off as you work through them.</p>
    ${filter}
    ${years}`;

  // Render progress rings
  const avgScore = scoreCount ? Math.round(totalScore / scoreCount) : 0;
  const completionPct = totalPapers ? Math.round((done / totalPapers) * 100) : 0;
  const summaryBox = document.getElementById("revise-summary");
  summaryBox.hidden = false;
  summaryBox.innerHTML = `
    <div class="progress-rings-row">
      ${renderProgressRing({
        pct: completionPct, color: "green", label: "Completion",
        tooltip: `${done} of ${totalPapers} papers done`
      })}
      ${renderProgressRing({
        pct: avgScore, color: "blue", label: "Avg Score",
        tooltip: scoreCount ? `Average ${avgScore}% across ${scoreCount} scored papers` : "No scored papers yet"
      })}
      ${renderProgressRing({
        pct: bestScore, color: "gold", label: "Best Score",
        tooltip: scoreCount ? `Best result: ${bestScore}%` : "No scored papers yet"
      })}
      ${renderProgressRing({
        pct: totalPapers ? Math.round((done / totalPapers) * 100) : 0,
        color: "lav", label: "Papers Done",
        centerText: `${done} of ${totalPapers}`,
        tooltip: `${done} completed, ${started} started, ${totalPapers - done - started} not started`
      })}
    </div>`;

  box.querySelectorAll(".pap-btn:not(.pap-score-btn)").forEach(btn =>
    btn.addEventListener("click", () => savePaper(btn)));
  box.querySelectorAll(".pap-score-btn").forEach(btn =>
    btn.addEventListener("click", () => openPaperMarksModal(btn.dataset.year, btn.dataset.session, btn.dataset.paper, btn.dataset.variant)));
  box.querySelectorAll(".pap-fbtn").forEach(btn =>
    btn.addEventListener("click", () => filterByComponent(btn.dataset.comp)));
  filterByComponent(state.paperComp || "");
}

/* ---- Component filter ---------------------------------------------------- */

function filterByComponent(comp) {
  state.paperComp = comp || "";
  const box = document.getElementById("paper-list");
  box.querySelectorAll(".pap-fbtn").forEach(b =>
    b.classList.toggle("on", (b.dataset.comp || "") === state.paperComp));
  box.querySelectorAll(".pap-group").forEach(g => {
    g.hidden = !!state.paperComp && g.dataset.comp !== state.paperComp;
  });
  box.querySelectorAll(".pap-year").forEach(y => {
    const visible = [...y.querySelectorAll(".pap-group")].filter(g => !g.hidden);
    y.hidden = !visible.length;
    const count = visible.reduce((s, g) => s + g.querySelectorAll(".pap-row").length, 0);
    const tag = y.querySelector("summary span");
    if (tag) tag.textContent = `${count} paper${count === 1 ? "" : "s"}`;
  });
  box.querySelectorAll(".pap-group-head").forEach(h => {
    h.style.display = state.paperComp ? "none" : "";
  });
}

function updateComponentCounts() {
  const box = document.getElementById("paper-list");
  if (!box) return;
  let allDone = 0, allTotal = 0;
  box.querySelectorAll(".pap-fbtn[data-comp]").forEach(btn => {
    const comp = btn.dataset.comp;
    if (!comp) return;
    const rows = box.querySelectorAll(`.pap-group[data-comp="${comp}"] .pap-row`);
    const done = [...rows].filter(r => r.querySelector(".pap-confident.on")).length;
    allDone += done; allTotal += rows.length;
    const tag = btn.querySelector("span");
    if (tag) tag.textContent = `${done}/${rows.length}`;
  });
  const allBtn = box.querySelector('.pap-fbtn[data-comp=""] span');
  if (allBtn) allBtn.textContent = `${allDone}/${allTotal}`;
}

/* ---- Save paper status --------------------------------------------------- */

async function savePaper(btn) {
  const seg = btn.parentElement;
  const previous = [...seg.children].find(c => c.classList.contains("on"));
  seg.querySelectorAll(".pap-btn:not(.pap-score-btn)").forEach(b => b.classList.toggle("on", b === btn));

  const body = {
    syllabus: state.syllabus,
    year: Number(seg.dataset.year),
    session: seg.dataset.session,
    paper: Number(seg.dataset.paper),
    variant: seg.dataset.variant || "",
    status: btn.dataset.status,
  };
  try {
    const row = await api("/api/papers-progress", { method: "POST", body });
    state.papers.set(paperKey(row), row);

    const summary = document.querySelector(".pap-summary");
    if (summary) {
      const all = [...state.papers.values()];
      summary.innerHTML = `<strong>${all.filter(p => p.status === "confident").length}</strong> done ·
        <strong>${all.filter(p => p.status === "learning").length}</strong> started ·
        tick them off as you work through them.`;
    }
    updateComponentCounts();

    if (btn.dataset.status === "confident") {
      openPaperMarksModal(seg.dataset.year, seg.dataset.session, seg.dataset.paper, seg.dataset.variant);
    }
  } catch (err) {
    seg.querySelectorAll(".pap-btn:not(.pap-score-btn)").forEach(b => b.classList.toggle("on", b === previous));
    alert(err.message);
  }
}

/* ---- Enter Marks Modal --------------------------------------------------- */

let activeMarksSession = null;

const PM_SESSION = { s: "MAY/JUNE", w: "OCT/NOV", m: "FEB/MAR" };

function renderThreshChips(tRec) {
  if (!tRec) return `<span class="pm-no-thresh">—</span>`;
  const chips = [];
  if (tRec.grade_astar != null)
    chips.push(`<span class="pm-tch grade-Astar">A* ${tRec.grade_astar}</span>`);
  chips.push(`<span class="pm-tch grade-A">A ${tRec.grade_a}</span>`);
  chips.push(`<span class="pm-tch grade-B">B ${tRec.grade_b}</span>`);
  chips.push(`<span class="pm-tch grade-C">C ${tRec.grade_c}</span>`);
  chips.push(`<span class="pm-tch grade-D">D ${tRec.grade_d}</span>`);
  chips.push(`<span class="pm-tch grade-E">E ${tRec.grade_e}</span>`);
  if (tRec.grade_f != null)
    chips.push(`<span class="pm-tch grade-E">F ${tRec.grade_f}</span>`);
  if (tRec.grade_g != null)
    chips.push(`<span class="pm-tch grade-E">G ${tRec.grade_g}</span>`);
  return `<div class="pm-tch-row">${chips.join("")}</div>`;
}

async function openPaperMarksModal(year, session, paper, variant = "") {
  const overlay = document.getElementById("paper-marks-overlay");

  // Eyebrow: "2016 | MAY/JUNE | P3"
  document.getElementById("pm-eyebrow").textContent =
    `${year} | ${PM_SESSION[session] || session.toUpperCase()} | P${paper}`;

  let thresholds = [];
  try {
    const res = await api(
      `/api/grade-thresholds?syllabus=${state.syllabus}&year=${year}&session=${session}`);
    thresholds = res.thresholds || [];
  } catch (err) {
    console.warn("Could not load thresholds:", err);
  }

  const tree = state.paperTree[state.syllabus];
  const yearObj = (tree?.years || []).find(y => y.year === Number(year));
  const sessObj = (yearObj?.sessions || []).find(s => s.session === session);
  const qpFiles = (sessObj?.files || []).filter(
    f => f.kind === "qp" && f.paper === Number(paper));
  const rows = qpFiles.length ? qpFiles : [{ paper: Number(paper), variant: variant || "" }];

  activeMarksSession = { year, session, paper, rows, thresholds, data: new Map() };

  let html = `
    <table class="pm-table">
      <thead><tr>
        <th>Variant</th><th>Type</th><th>Marks</th>
        <th>Total</th><th>Grade Threshold</th><th>Grade</th>
      </tr></thead>
      <tbody>`;

  rows.forEach((r, idx) => {
    const vStr = r.variant || "";
    const rec = state.papers.get(paperKey({ year, session, paper, variant: vStr })) || {};
    const tRec = thresholds.find(t =>
      t.paper === Number(paper) &&
      (String(t.variant) === String(vStr) || !t.variant));
    const maxMark = tRec?.max_mark || (Number(paper) === 1 ? 40 : 80);
    const isMcq = rec.synced || r.type === "mcq";
    const currentScore = rec.score != null ? rec.score : "";
    const g = calculateGrade(currentScore, maxMark, tRec);

    // Variant code = paperNumber + variantDigit, e.g. "31"
    const varCode = `${paper}${vStr || "1"}`;

    const paperLink = `/yearly/open?syllabus=${state.syllabus}` +
      `&year=${year}&session=${session}&paper=${paper}&variant=${vStr}`;

    html += `
      <tr data-idx="${idx}" data-variant="${esc(vStr)}" data-max="${maxMark}">
        <td data-label="Variant">
          <b class="pm-variant-code">${esc(varCode)}</b>
          <a href="${paperLink}" target="_blank" class="pm-view-paper-link">↗ View paper</a>
        </td>
        <td data-label="Type">
          <span class="pm-type-badge ${isMcq ? "pm-type-mcq" : "pm-type-theory"}">
            ${isMcq ? "MCQ" : "Theory"}
          </span>
        </td>
        <td data-label="Marks">
          <input type="number" min="0" max="${maxMark}" class="pm-marks-input"
                 data-idx="${idx}" value="${currentScore}" placeholder="—">
        </td>
        <td data-label="Total"><b>${maxMark}</b></td>
        <td data-label="Grade Threshold">${renderThreshChips(tRec)}</td>
        <td data-label="Grade">
          <div class="pm-grade-cell" data-idx="${idx}">${renderGradePill(g.grade)}</div>
        </td>
      </tr>`;

    activeMarksSession.data.set(idx, {
      variant: vStr,
      maxMark,
      thresholds: tRec,
      score: currentScore !== "" ? Number(currentScore) : null,
      grade: g.grade,
      confidence: rec.confidence || "ok",
      attempts: rec.attempts_json
        ? (typeof rec.attempts_json === "string"
            ? JSON.parse(rec.attempts_json) : rec.attempts_json)
        : [],
    });
  });

  html += `</tbody></table>`;
  document.getElementById("pm-table-wrap").innerHTML = html;
  wireModalEvents();
  overlay.hidden = false;
  document.body.style.overflow = "hidden";
}

function wireModalEvents() {
  const overlay = document.getElementById("paper-marks-overlay");

  overlay.querySelectorAll("[data-close-marks]").forEach(el =>
    el.addEventListener("click", closePaperMarksModal));

  overlay.querySelectorAll(".pm-marks-input").forEach(input => {
    input.addEventListener("input", () => {
      const idx = Number(input.dataset.idx);
      const rowData = activeMarksSession.data.get(idx);
      if (!rowData) return;
      const val = input.value;
      const score = val === ""
        ? null : Math.min(rowData.maxMark, Math.max(0, Number(val)));
      rowData.score = score;
      const calc = calculateGrade(score, rowData.maxMark, rowData.thresholds);
      rowData.grade = calc.grade;
      const gradeCell = overlay.querySelector(`.pm-grade-cell[data-idx="${idx}"]`);
      if (gradeCell) gradeCell.innerHTML = renderGradePill(calc.grade);
    });
  });

  document.getElementById("pm-save").onclick = savePaperMarksModal;
}

function closePaperMarksModal() {
  document.getElementById("paper-marks-overlay").hidden = true;
  document.body.style.overflow = "";
  activeMarksSession = null;
}

async function savePaperMarksModal() {
  if (!activeMarksSession) return;
  const { year, session, paper, data } = activeMarksSession;

  const saveBtn = document.getElementById("pm-save");
  saveBtn.disabled = true;
  saveBtn.textContent = "Saving…";

  try {
    for (const [idx, item] of data.entries()) {
      const vStr = item.variant || "";
      const status = item.score != null ? "confident" : "not_started";

      let attempts = item.attempts || [];
      if (item.score != null) {
        attempts.push({
          date: new Date().toISOString().split("T")[0],
          score: item.score,
          max_score: item.maxMark,
          grade: item.grade
        });

        // Also save to student-scores database for Phase 2/3 grade calculator/trends
        try {
          const scoreBody = {
            syllabus: state.syllabus,
            year: Number(year),
            session: session,
            paper: Number(paper),
            variant: vStr,
            raw_mark: Number(item.score),
            max_mark: Number(item.maxMark),
            component_grade: item.grade,
            notes: ""
          };
          await api("/api/student-scores", { method: "POST", body: scoreBody });
        } catch (scoreErr) {
          console.warn("Could not save to student-scores:", scoreErr);
        }
      }

      const body = {
        syllabus: state.syllabus,
        year: Number(year),
        session: session,
        paper: Number(paper),
        variant: vStr,
        status,
        score: item.score,
        max_score: item.maxMark,
        grade: item.grade,
        confidence: item.confidence,
        attempts_json: JSON.stringify(attempts),
        synced: 0
      };

      const row = await api("/api/papers-progress", { method: "POST", body });
      state.papers.set(paperKey(row), row);
    }

    closePaperMarksModal();
    renderPapers();
  } catch (err) {
    alert("Could not save marks: " + err.message);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = "Save Marks";
  }
}
