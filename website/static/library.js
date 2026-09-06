(function () {
  /* PrepWithTee paper library — a collapsible archive tree plus a viewer that
     shows a question paper and its mark scheme together. */
  const $ = (s) => document.querySelector(s);

  const state = {
    syllabus: null,     // currently expanded subject
    selected: null,     // {year, session, name, code, paper, variant, qp, ms}
    layout: "stacked",
    trees: {},          // syllabus -> fetched tree, so re-opening is instant
  };

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error("could not reach the archive");
  return r.json();
}

/* ---------- tree building ---------------------------------------------- */

function row({ depth, icon, label, count, tag, folder, onClick }) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "tree-row" + (folder ? "" : " tree-file");
  b.style.setProperty("--depth", depth);
  b.innerHTML =
    `<span class="chev">${folder ? "▶" : ""}</span>` +
    `<span class="ico">${icon}</span>` +
    `<span class="lbl">${label}</span>` +
    (tag ? `<span class="tag ${tag}">${tag.toUpperCase()}</span>` : "") +
    (count != null ? `<span class="n">${count}</span>` : "");
  b.onclick = onClick;
  return b;
}

function group(parentEl, headerRow) {
  const kids = document.createElement("div");
  kids.className = "tree-kids";
  kids.hidden = true;
  headerRow.onclick = () => {
    kids.hidden = !kids.hidden;
    headerRow.classList.toggle("open", !kids.hidden);
    if (headerRow.dataset.load && !kids.hidden && !kids.dataset.loaded) {
      kids.dataset.loaded = "1";
      loadSubject(headerRow.dataset.load, kids,
                  +headerRow.style.getPropertyValue("--depth"));
    }
  };
  parentEl.appendChild(headerRow);
  parentEl.appendChild(kids);
  return kids;
}

async function loadSubject(syllabus, container, base) {
  container.innerHTML = '<p class="hint" style="padding:6px 0 6px 34px">Loading…</p>';
  let tree = state.trees[syllabus];
  if (!tree) {
    tree = await get(`/api/library/tree?syllabus=${syllabus}`);
    state.trees[syllabus] = tree;
  }
  container.innerHTML = "";

  // Mirrors the archive on disk: past papers / year / session / files.
  const ppRow = row({ depth: base + 1, icon: "📂", label: "past papers",
                      folder: true });
  const ppKids = group(container, ppRow);

  for (const y of tree.years) {
    const yRow = row({ depth: base + 2, icon: "📂", label: String(y.year),
                       count: y.count, folder: true });
    const yKids = group(ppKids, yRow);

    for (const s of y.sessions) {
      const sRow = row({ depth: base + 3, icon: "📂", label: s.name,
                         count: s.files.length, folder: true });
      const sKids = group(yKids, sRow);

      for (const f of s.files) {
        const fRow = row({
          depth: base + 4, icon: "📄",
          label: f.filename.replace(/\.pdf$/i, ""),
          tag: f.kind,
          onClick: () => selectFile(syllabus, y.year, s, f),
        });
        fRow.dataset.fileId = f.id;
        fRow.title = f.filename;
        sKids.appendChild(fRow);
      }
    }
  }
  ppRow.click();                       // open "past papers" straight away
  if (ppKids.firstChild) ppKids.firstChild.click();   // and the newest year
}

async function buildTree() {
  const [libData, enrollRes, meRes] = await Promise.all([
    get("/api/library"),
    get("/api/enrollments").catch(() => null),
    fetch("/auth/me", { credentials: "same-origin" })
      .then(r => r.ok ? r.json() : null).catch(() => null),
  ]);
  const { boards } = libData;
  state.userRole = meRes?.role || null;
  if (enrollRes && enrollRes.enrollments) {
    state.enrolledSyllabuses = enrollRes.enrollments.map(e => e.syllabus);
  } else {
    state.enrolledSyllabuses = [];
  }
  // Build syllabus→subject lookup from the tree data (avoids an extra /api/meta call).
  state.subjectMap = {};
  for (const b of boards) {
    for (const s of b.subjects) state.subjectMap[s.syllabus] = s;
  }
  const tree = $("#tree");
  tree.innerHTML = "";
  const want = new URLSearchParams(location.search).get("syllabus");
  let target = null, targetBoard = null;

  for (const b of boards) {
    const bRow = row({ depth: 0, icon: "🎓", label: b.board, count: b.count,
                       folder: true });
    const bKids = group(tree, bRow);

    for (const s of b.subjects) {
      const sRow = row({ depth: 1, icon: "📁",
                         label: `${s.subject} — ${s.syllabus}`,
                         count: s.count, folder: true });
      sRow.dataset.load = s.syllabus;
      group(bKids, sRow);
      if (s.syllabus === want) { target = sRow; targetBoard = bRow; }
    }
  }

  // Deep link opens its board and subject; otherwise just show the boards.
  if (target) { targetBoard.click(); target.click(); }
}

/* ---------- viewer ------------------------------------------------------ */

function selectFile(syllabus, year, session, file) {
  // Pair the clicked file with its opposite number so both load together.
  const sibling = session.files.find(
    (f) => f.code === file.code && f.kind !== file.kind);
  const qp = file.kind === "qp" ? file : sibling;
  const ms = file.kind === "ms" ? file : sibling;

  state.syllabus = syllabus;
  state.selected = {
    year,
    session: session.session,
    sessionName: session.name,
    code: file.code,
    paper: file.paper,
    variant: file.variant,
    qp,
    ms
  };

  document.querySelectorAll(".tree-file").forEach((el) =>
    el.classList.toggle("on",
      el.dataset.fileId === String(qp?.id) || el.dataset.fileId === String(ms?.id)));

  render();
}

function renderQuotaCard(detail) {
  const msg = detail?.message || "You've reached your free limit of 3 past papers this month.";
  return `
    <div class="pwt-quota-card-wrapper">
      <div class="pwt-quota-card">
        <div class="pwt-qc-badge">⚡ Monthly Limit Reached</div>
        <h3 class="pwt-qc-title">Upgrade to Keep Accessing Past Papers</h3>
        <p class="pwt-qc-sub">${msg}</p>
        
        <div class="pwt-qc-price-box">
          <span class="pwt-qc-price-tagline">Unlimited Access Starting From</span>
          <div class="pwt-qc-price-val">
            <span style="font-size:1.1rem;font-weight:700;color:var(--gold)">PKR</span> 1,000 <span style="font-size:0.85rem;font-weight:500;color:var(--grey)">/month</span>
          </div>
          <span class="pwt-qc-price-subtext">Solo Plan (Single Subject) · Cancel anytime</span>
        </div>

        <div class="pwt-qc-features">
          <div class="pwt-qc-feat">✓ Unlimited Past Papers & Mark Schemes</div>
          <div class="pwt-qc-feat">✓ 24/7 AI Tutor Socratic Doubt Solver</div>
          <div class="pwt-qc-feat">✓ Topical PDF Builder & Mark Schemes</div>
          <div class="pwt-qc-feat">✓ Exam Readiness & Performance Analytics</div>
        </div>

        <div class="pwt-qc-actions">
          <a href="pricing.html" class="pwt-qc-btn-primary">
            🚀 Upgrade Now — as low as PKR 1,000/mo →
          </a>
          <a href="pricing.html" class="pwt-qc-btn-secondary">
            View All Plans & Features
          </a>
        </div>
      </div>
    </div>
  `;
}

function paneHTML(kind, file, label) {
  if (!file) {
    return `<div class="pane ${kind}">
      <div class="pane-head"><b>${label}</b></div>
      <p class="pane-missing">Not in the archive for this paper.</p></div>`;
  }
  return `<div class="pane ${kind}">
    <div class="pane-head">
      <b>${label}</b><span class="file">${file.filename}</span>
    </div>
    <iframe class="lib-frame" title="${label}"
            src="/api/library/pdf/${file.id}#view=FitH"></iframe>
  </div>`;
}

async function render() {
  const s = state.selected;
  if (!s) return;
  $("#lib-empty").hidden = true;
  $("#panes").hidden = false;
  $("#lib-layout").hidden = false;
  const fsBtn = $("#lib-fullscreen-btn");
  if (fsBtn) fsBtn.hidden = false;
  const darkBtn = $("#lib-dark-btn");
  if (darkBtn) darkBtn.hidden = false;

  $("#lib-title").textContent =
    `${state.syllabus}/${s.code} · ${s.sessionName} ${s.year}`;
  $("#lib-sub").textContent = s.qp && s.ms
    ? "Question paper and mark scheme"
    : (s.qp ? "Question paper only" : "Mark scheme only");

  // Paper mark-as-done checkmark logic
  if (!state.paperProgress) state.paperProgress = {};
  if (!state.paperProgress[state.syllabus]) {
    try {
      const res = await get('/api/papers-progress?syllabus=' + state.syllabus);
      state.paperProgress[state.syllabus] = res.papers || [];
    } catch (err) {
      state.paperProgress[state.syllabus] = [];
    }
  }

  const currentProgress = state.paperProgress[state.syllabus].find(p =>
    p.year === s.year &&
    p.session === s.session &&
    p.paper === s.paper &&
    String(p.variant) === String(s.variant)
  );
  const isDone = currentProgress && currentProgress.status === "confident";

  const tickBtn = $("#lib-mark-done-btn");
  if (tickBtn) {
    tickBtn.style.display = "flex";
    const circle = tickBtn.querySelector(".tick-circle");
    const check = tickBtn.querySelector(".tick-check");
    if (isDone) {
      circle.style.fill = "#ff7b00";
      circle.style.stroke = "#ff7b00";
      check.style.stroke = "#ffffff";
      tickBtn.title = "Marked as Done (Double-click to enter marks)";
    } else {
      circle.style.fill = "none";
      circle.style.stroke = "#888";
      check.style.stroke = "transparent";
      tickBtn.title = "Mark as Done (Double-click to enter marks)";
    }

    tickBtn.onmouseenter = () => {
      if (!isDone) {
        circle.style.stroke = "#ff7b00";
      }
    };
    tickBtn.onmouseleave = () => {
      if (!isDone) {
        circle.style.stroke = "#888";
      }
    };

    tickBtn.onclick = async (evt) => {
      evt.preventDefault();
      const enrolled = state.enrolledSyllabuses || [];
      const isPrivileged = state.userRole === "teacher" || state.userRole === "admin";
      if (!isPrivileged && state.enrolledSyllabuses && !enrolled.includes(state.syllabus)) {
        openEnrollGatingModal(state.syllabus, async () => {
          state.enrolledSyllabuses = [...enrolled, state.syllabus];
          tickBtn.click();
        });
        return;
      }

      const newStatus = isDone ? "not_started" : "confident";
      try {
        await fetch("/api/papers-progress", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            syllabus: state.syllabus,
            year: s.year,
            session: s.session,
            paper: s.paper,
            variant: String(s.variant),
            status: newStatus
          })
        });

        if (!currentProgress) {
          state.paperProgress[state.syllabus].push({
            year: s.year,
            session: s.session,
            paper: s.paper,
            variant: String(s.variant),
            status: newStatus
          });
        } else {
          currentProgress.status = newStatus;
        }
        render();
      } catch (err) {
        alert("Could not update paper progress: " + err.message);
      }
    };

    tickBtn.ondblclick = (evt) => {
      evt.preventDefault();
      openEnterMarksModal();
    };
  }

  $("#panes").className = "lib-panes " + state.layout;

  $("#panes").innerHTML =
    paneHTML("qp", s.qp, "Question paper") + paneHTML("ms", s.ms, "Mark scheme");

  renderThresholds(s);

  const dl = $("#lib-download");
  const openBtn = $("#lib-open");
  const primary = s.qp || s.ms;
  dl.hidden = !primary;
  openBtn.hidden = !primary;
  if (primary) {
    dl.href = `/api/library/pdf/${primary.id}`;
    dl.setAttribute("download", primary.filename);
    openBtn.href = `/api/library/pdf/${primary.id}`;
  }
}

/* ---------- grade thresholds ------------------------------------------- */

const GT_SESSION_FULL = { s: "May/June", w: "Oct/Nov", m: "Feb/March" };

const escGt = (v) => String(v ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function gtChips(t) {
  if (!t) return `<span class="lib-th-none">Not published for this component.</span>`;
  const c = [];
  if (t.grade_astar != null) c.push(`<span class="pm-tch grade-Astar">A* ${t.grade_astar}</span>`);
  [["a", "A"], ["b", "B"], ["c", "C"], ["d", "D"], ["e", "E"]].forEach(([k, g]) => {
    if (t["grade_" + k] != null) c.push(`<span class="pm-tch grade-${g}">${g} ${t["grade_" + k]}</span>`);
  });
  if (t.grade_f != null) c.push(`<span class="pm-tch grade-E">F ${t.grade_f}</span>`);
  if (t.grade_g != null) c.push(`<span class="pm-tch grade-E">G ${t.grade_g}</span>`);
  return `<div class="pm-tch-row">${c.join("")}</div>`;
}

async function renderThresholds(s) {
  const box = $("#lib-thresholds");
  if (!box) return;
  box.hidden = false;
  const when = `${GT_SESSION_FULL[s.session] || s.sessionName} ${s.year}`;
  box.innerHTML =
    `<div class="lib-th-head"><b>📊 Grade thresholds</b><span>${escGt(when)}</span></div>
     <p class="lib-th-none" style="padding:8px 2px">Loading official boundaries…</p>`;

  state.gt = state.gt || {};
  const syl = state.syllabus;
  if (!state.gt[syl]) {
    try {
      const [th, op] = await Promise.all([
        get(`/api/grade-thresholds?syllabus=${encodeURIComponent(syl)}`),
        get(`/api/grade-options?syllabus=${encodeURIComponent(syl)}`).catch(() => ({ options: [] })),
      ]);
      state.gt[syl] = { thresholds: th.thresholds || [], options: op.options || [] };
    } catch (err) {
      box.innerHTML =
        `<div class="lib-th-head"><b>📊 Grade thresholds</b></div>
         <p class="lib-th-none" style="padding:8px 2px">Grade thresholds are unavailable for this paper.</p>`;
      return;
    }
  }
  // The user may have clicked another paper while we were loading.
  if (state.selected !== s) return;

  const { thresholds, options } = state.gt[syl];
  const V = String(s.variant || "");

  const comp = thresholds.find(t => t.year === s.year && t.session === s.session &&
    String(t.paper) === String(s.paper) && String(t.variant || "") === V);

  const sessOpts = options.filter(o => o.year === s.year && o.session === s.session &&
    o.max_mark > 0 && (!V ||
    (o.components || "").split(/[\s,]+/).filter(Boolean)
      .every(c => c.length >= 2 && c.slice(-1) === V)));

  let html =
    `<div class="lib-th-head"><b>📊 Grade thresholds</b>
       <span>${escGt(when)} · official Cambridge</span></div>`;

  html +=
    `<div class="lib-th-block">
       <div class="lib-th-label">This component — Paper ${escGt(s.paper)}${V ? " v" + escGt(V) : ""}${comp ? " · out of " + comp.max_mark : ""}</div>
       ${gtChips(comp)}
     </div>`;

  if (sessOpts.length) {
    html +=
      `<div class="lib-th-block">
         <div class="lib-th-label">Overall grade — weighted total (this combination of papers)</div>
         ${sessOpts.map(o => `
           <div class="lib-th-opt">
             <span class="lib-th-opt-code">${escGt(o.option_code)}</span>
             <span class="lib-th-opt-comp">${escGt(o.components)} · out of ${o.max_mark}</span>
             ${gtChips(o)}
           </div>`).join("")}
         <p class="lib-th-note">Cambridge scales each paper to a fixed share of the total before comparing to these overall boundaries.
           See the <a href="grade-calculator.html">Grade Calculator</a> to predict your grade.</p>
       </div>`;
  }
  box.innerHTML = html;
}

document.querySelectorAll("#lib-layout button").forEach((b) => {
  b.onclick = () => {
    state.layout = b.dataset.layout;
    document.querySelectorAll("#lib-layout button").forEach((x) =>
      x.classList.toggle("on", x === b));
    render();
  };
});

const fsBtn = $("#lib-fullscreen-btn");
if (fsBtn) {
  fsBtn.onclick = () => {
    const viewer = $(".lib-viewer");
    const isFs = viewer.classList.toggle("lib-fullscreen-active");
    fsBtn.innerHTML = isFs ? "✕ Exit Fullscreen" : "⛶ Fullscreen";
  };
}

const darkBtn = $("#lib-dark-btn");
if (darkBtn) {
  darkBtn.onclick = () => {
    const viewer = $(".lib-viewer");
    const isDark = viewer.classList.toggle("lib-dark-active");
    darkBtn.innerHTML = isDark ? "☀️ Light Mode" : "🌙 Night Mode";
  };
}

/* ---------- search ------------------------------------------------------ */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* Results come back as whole sittings carrying both file ids, so opening one
   needs no tree loading at all — it feeds straight into the same viewer state
   a tree click produces. */
function openResult(r) {
  state.syllabus = r.syllabus;
  state.selected = {
    year: r.year,
    session: r.session,
    sessionName: r.session_name,
    code: r.code,
    paper: r.paper,
    variant: r.variant,
    qp: r.qp,
    ms: r.ms,
  };
  document.querySelectorAll(".tree-file").forEach((el) => el.classList.remove("on"));
  document.querySelectorAll(".lib-result").forEach((el) =>
    el.classList.toggle("on", el.dataset.key === resultKey(r)));
  render();
  // On mobile the panel is a drawer over the viewer; opening a paper means
  // the student wants to read it, not keep browsing.
  const panel = $("#lib-panel");
  if (panel && panel.classList.contains("open")) {
    panel.classList.remove("open");
    const t = $("#lib-panel-toggle");
    if (t) { t.setAttribute("aria-expanded", "false"); t.textContent = "📂 Browse papers"; }
  }
}

const resultKey = (r) =>
  `${r.syllabus}-${r.year}-${r.session}-${r.paper}-${r.variant}`;

function renderResults(data) {
  const box = $("#lib-results");
  const list = data.results || [];
  if (!list.length) {
    box.innerHTML = `<p class="lib-no-results">No papers match that. Try a code
      like <b>0625</b>, or a year.</p>`;
    return;
  }
  box.innerHTML =
    (data.truncated
      ? `<p class="lib-results-head">First ${list.length} of ${data.total} matches</p>`
      : `<p class="lib-results-head">${data.total} match${data.total === 1 ? "" : "es"}</p>`) +
    list.map((r) => `
      <button type="button" class="lib-result" data-key="${esc(resultKey(r))}">
        <span class="lib-result-main">
          <b>${esc(r.subject)} ${esc(r.syllabus)}</b>
          <em>${esc(r.session_name)} ${r.year} · Paper ${r.paper}${
            r.variant ? " variant " + esc(r.variant) : ""}</em>
        </span>
        <span class="lib-result-tags">
          ${r.qp ? '<i class="lib-tag qp">QP</i>' : ""}
          ${r.ms ? '<i class="lib-tag ms">MS</i>' : ""}
        </span>
      </button>`).join("");
  box.querySelectorAll(".lib-result").forEach((btn, i) => {
    btn.onclick = () => openResult(list[i]);
  });
}

function initSearch() {
  const input = $("#lib-search");
  const box = $("#lib-results");
  const tree = $("#tree");
  const hint = $("#lib-search-hint");
  const clear = $("#lib-search-clear");
  if (!input) return;

  let timer = null;
  let seq = 0;

  function showTree() {
    box.hidden = true;
    tree.hidden = false;
    hint.hidden = false;
    clear.hidden = true;
  }

  async function run(q) {
    // Every response carries the query number it answered, so a slow reply to
    // an older keystroke can never paint over a newer one.
    const mine = ++seq;
    try {
      const data = await get(`/api/library/search?q=${encodeURIComponent(q)}`);
      if (mine !== seq) return;
      renderResults(data);
    } catch (err) {
      if (mine !== seq) return;
      box.innerHTML = `<p class="lib-no-results">Search unavailable: ${esc(err.message)}</p>`;
    }
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearTimeout(timer);
    clear.hidden = !q;
    if (q.length < 2) { showTree(); return; }
    box.hidden = false;
    tree.hidden = true;
    hint.hidden = true;
    if (!box.innerHTML) box.innerHTML = `<p class="lib-results-head">Searching…</p>`;
    timer = setTimeout(() => run(q), 180);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; showTree(); }
    // Enter on a single unambiguous match opens it — the common case when a
    // student types a full paper code.
    if (e.key === "Enter") {
      const first = box.querySelector(".lib-result");
      if (first && !box.hidden) { e.preventDefault(); first.click(); }
    }
  });

  clear.onclick = () => { input.value = ""; showTree(); input.focus(); };
}

  initSearch();
  buildTree().catch((err) => {
    $("#lib-empty").innerHTML =
      `<span>⚠️</span><b>Archive unavailable</b><p>${err.message}</p>`;
  });

  function openEnrollGatingModal(syllabus, onEnrollSuccess) {
    const sub = state.subjectMap?.[syllabus] || { subject: syllabus, syllabus: syllabus };
    const subjectLabel = sub.short || sub.subject || syllabus;
    const displayName = `${subjectLabel} (${syllabus})`;

    const msg = document.getElementById("lib-enroll-gate-message");
    msg.innerHTML = `You're not enrolled in <strong>[${displayName}]</strong> — enroll to track this paper in your dashboard.`;
    
    const modal = document.getElementById("lib-enroll-gate-modal");
    modal.style.display = "flex";

    document.getElementById("lib-enroll-gate-no").onclick = () => {
      modal.style.display = "none";
    };

    document.getElementById("lib-enroll-gate-yes").onclick = async () => {
      const btn = document.getElementById("lib-enroll-gate-yes");
      const status = document.getElementById("lib-enroll-gate-status");
      btn.disabled = true;
      btn.textContent = "Enrolling…";
      status.textContent = "";
      try {
        const r = await fetch("/api/enrollments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ syllabus })
        });
        if (!r.ok) throw new Error("failed to enroll");
        modal.style.display = "none";
        if (onEnrollSuccess) onEnrollSuccess();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "Enroll now";
        status.textContent = "Could not enroll: " + err.message;
      }
    };
  }

  function openEnterMarksModal() {
    const s = state.selected;
    if (!s) return;

    const enrolled = state.enrolledSyllabuses || [];
    const isPrivileged = state.userRole === "teacher" || state.userRole === "admin";
    if (!isPrivileged && state.enrolledSyllabuses && !enrolled.includes(state.syllabus)) {
      openEnrollGatingModal(state.syllabus, () => {
        state.enrolledSyllabuses = [...enrolled, state.syllabus];
        openEnterMarksModal();
      });
      return;
    }

    const currentProgress = state.paperProgress?.[state.syllabus]?.find(p => 
      p.year === s.year && 
      p.session === s.session && 
      p.paper === s.paper && 
      String(p.variant) === String(s.variant)
    );

    const modal = document.getElementById("lib-marks-modal");
    const title = document.getElementById("lib-marks-title");
    const scoreInput = document.getElementById("lib-marks-score");
    const maxInput = document.getElementById("lib-marks-max");
    const statusMsg = document.getElementById("lib-marks-status");

    title.textContent = `${state.syllabus}/${s.code} · ${s.sessionName} ${s.year}`;
    scoreInput.value = currentProgress?.score != null ? currentProgress.score : "";
    maxInput.value = currentProgress?.max_score != null ? currentProgress.max_score : "40";
    statusMsg.textContent = "";

    modal.style.display = "flex";

    document.getElementById("lib-marks-cancel-btn").onclick = () => {
      modal.style.display = "none";
    };

    document.getElementById("lib-marks-save-btn").onclick = async () => {
      const scoreVal = scoreInput.value.trim();
      const maxVal = maxInput.value.trim();
      if (!scoreVal || !maxVal) {
        statusMsg.textContent = "Please enter both score and max score.";
        return;
      }
      const score = parseInt(scoreVal, 10);
      const max_score = parseInt(maxVal, 10);
      if (isNaN(score) || isNaN(max_score) || score < 0 || max_score <= 0) {
        statusMsg.textContent = "Invalid score inputs.";
        return;
      }

      const saveBtn = document.getElementById("lib-marks-save-btn");
      saveBtn.disabled = true;
      saveBtn.textContent = "Saving…";

      try {
        await fetch("/api/papers-progress", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            syllabus: state.syllabus,
            year: s.year,
            session: s.session,
            paper: s.paper,
            variant: String(s.variant),
            status: "confident",
            score: score,
            max_score: max_score
          })
        });

        if (!currentProgress) {
          state.paperProgress[state.syllabus].push({
            year: s.year,
            session: s.session,
            paper: s.paper,
            variant: String(s.variant),
            status: "confident",
            score: score,
            max_score: max_score
          });
        } else {
          currentProgress.status = "confident";
          currentProgress.score = score;
          currentProgress.max_score = max_score;
        }

        modal.style.display = "none";
        render();
      } catch (err) {
        statusMsg.textContent = "Could not save: " + err.message;
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      }
    };
  }
})();
