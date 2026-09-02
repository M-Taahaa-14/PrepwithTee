/* Teacher student console — tabs for a single assigned student.
 *
 * Port of admin-student.js; all API calls go to /api/teacher/ instead of
 * /api/admin/. Helpers (api, esc, panel, toast, openDrawer, closeDrawer,
 * subjectName, table, empty, uploadWithProgress) are injected via init().
 *
 * Usage (in teacher-dashboard.html):
 *   import * as TS from "/teacher-student.js";
 *   TS.init(H);                    // once on page load
 *   TS.mount(detail, box, syllabuses); // when a student row is opened
 *   box.innerHTML += TS.tabsHtml(); // insert tab markup into the DOM
 *   TS.wireTabs(box);              // wire click events + call render
 */

let H = null;

const STATUS_ORDER = ["not_started", "learning", "confident"];
const STATUS_LABEL = {
  not_started: "Not started", learning: "Learning", confident: "Confident",
};
const CLASS_STATUS = ["held", "cancelled", "missed", "rescheduled"];
const KINDS = [
  ["homework", "Homework"], ["reading", "Reading"],
  ["practice", "Practice"], ["test", "Test"],
];
const SESSION_NAME = { s: "May/Jun", w: "Oct/Nov", m: "Feb/Mar" };

const GRADE_COLORS = { "A*": "#7c3aed", A: "#2563eb", B: "#16a34a", C: "#ca8a04", D: "#ea580c", E: "#dc2626", U: "#6b7280" };

function gradeChip(g) {
  const bg = GRADE_COLORS[g] || "#6b7280";
  return `<span style="display:inline-block;min-width:26px;padding:1px 7px;border-radius:12px;background:${bg};color:#fff;font-size:.65rem;font-weight:800;text-align:center;vertical-align:middle;line-height:1.6">${H.esc(String(g))}</span>`;
}

function calcGrade(score, tRec) {
  if (score === "" || score == null || !tRec) return null;
  const s = Number(score);
  if (isNaN(s)) return null;
  if (tRec.grade_astar != null && s >= tRec.grade_astar) return "A*";
  if (tRec.grade_a    != null && s >= tRec.grade_a)    return "A";
  if (tRec.grade_b    != null && s >= tRec.grade_b)    return "B";
  if (tRec.grade_c    != null && s >= tRec.grade_c)    return "C";
  if (tRec.grade_d    != null && s >= tRec.grade_d)    return "D";
  if (tRec.grade_e    != null && s >= tRec.grade_e)    return "E";
  return "U";
}

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtTime(secs) {
  if (!isFinite(secs) || secs < 0) return "—";
  if (secs < 1) return "under a second";
  if (secs < 60) return `${Math.round(secs)}s`;
  const m = Math.floor(secs / 60);
  return `${m}m ${Math.round(secs % 60)}s`;
}

let S = null;

export function init(helpers) { H = helpers; }

export function mount(detail, root, allocatedSyllabuses) {
  S = {
    id: detail.profile.id,
    detail,
    tab: "progress",
    taxonomy: {},
    progress: indexProgress(detail.progress),
    papers: indexPapers(detail.papers || []),
    paperTree: {},
    classes: detail.classes || [],
    assignments: detail.assignments || [],
    progressSyllabus: null,
    paperSyllabus: null,
    month: startOfMonth(new Date()),
    calScope: "month",
    resources: null,
    allocatedSyllabuses: allocatedSyllabuses || [],
    root,
  };
  const subjects = subjectCodes();
  S.progressSyllabus = subjects[0] || null;
  S.paperSyllabus = subjects[0] || null;
  render();
}

/* ---- indexes ------------------------------------------------------------- */

const pkey = (syllabus, topic, subtopic) => `${syllabus} ${topic} ${subtopic || ""}`;

function indexProgress(rows) {
  const map = new Map();
  for (const r of rows || []) {
    map.set(pkey(r.syllabus, r.topic, r.subtopic), r.status || "not_started");
  }
  return map;
}

const paperKey = p => `${p.syllabus} ${p.year} ${p.session} ${p.paper} ${p.variant || ""}`;

function indexPapers(rows) {
  const map = new Map();
  for (const r of rows) map.set(paperKey(r), r);
  return map;
}

function subjectCodes() {
  const seen = [];
  const add = c => { if (c && !seen.includes(c)) seen.push(c); };
  (S.allocatedSyllabuses || []).forEach(add);
  (S.detail.enrollments || []).filter(e => e.status === "active").forEach(e => add(e.syllabus));
  (S.detail.enrollments || []).forEach(e => add(e.syllabus));
  (S.detail.by_syllabus || []).forEach(s => add(s.syllabus));
  (S.detail.papers || []).forEach(p => add(p.syllabus));
  (S.detail.assignments || []).forEach(a => add(a.syllabus));
  return seen;
}

/* ---- shell --------------------------------------------------------------- */

const TABS = [
  ["progress", "Chapter progress"],
  ["papers", "Past papers"],
  ["calendar", "Class calendar"],
  ["homework", "Homework diary"],
];

function render() {
  const body = document.getElementById("stu-tab-body");
  if (!body) return;
  document.querySelectorAll("#stu-tabs .stu-tab").forEach(b =>
    b.classList.toggle("on", b.dataset.tab === S.tab));
  if (S.tab === "progress") renderProgress(body);
  else if (S.tab === "papers") renderPapers(body);
  else if (S.tab === "calendar") renderCalendar(body);
  else renderHomework(body);
}

export function tabsHtml() {
  return `
    <div class="stu-tabs" id="stu-tabs">
      ${TABS.map(([id, label], i) => `
        <button class="stu-tab${i === 0 ? " on" : ""}" data-tab="${id}">${label}</button>`
      ).join("")}
    </div>
    <div id="stu-tab-body"></div>`;
}

export function wireTabs(scope) {
  scope.querySelectorAll("#stu-tabs .stu-tab").forEach(b =>
    b.addEventListener("click", () => { S.tab = b.dataset.tab; render(); }));
  render();
}

function subjectPills(active, onPick) {
  const codes = subjectCodes();
  if (!codes.length) return "";
  return `<div class="stu-pills">${codes.map(c => `
    <button class="stu-pill${c === active ? " on" : ""}" data-${onPick}="${H.esc(c)}">
      ${H.esc(H.subjectName(c))}<em>${H.esc(c)}</em>
    </button>`).join("")}</div>`;
}

/* ---- 1. Chapter progress ------------------------------------------------- */

function seg(current, dataAttrs) {
  return `<div class="seg">${STATUS_ORDER.map(v => `
    <button type="button" class="seg-btn seg-${v}${current === v ? " on" : ""}"
            ${dataAttrs} data-status="${v}">${STATUS_LABEL[v]}</button>`).join("")}</div>`;
}

async function renderProgress(box) {
  const codes = subjectCodes();
  if (!codes.length) {
    box.innerHTML = H.panel("Chapter progress", H.empty("📗",
      "This student has no subjects yet.",
      "They pick subjects on their dashboard."));
    return;
  }
  const syl = S.progressSyllabus;
  box.innerHTML = H.panel("Chapter progress",
    `${subjectPills(syl, "psyl")}
     <div class="panel-body" id="prog-body">
       ${H.empty("⏳", "Loading the syllabus…")}
     </div>`,
    `<span class="stu-hint">Sets the same status the student sees in Progress Tracker</span>`);

  box.querySelectorAll("[data-psyl]").forEach(b => b.addEventListener("click", () => {
    S.progressSyllabus = b.dataset.psyl;
    render();
  }));

  let tax;
  try {
    tax = await taxonomy(syl);
  } catch (ex) {
    document.getElementById("prog-body").innerHTML =
      H.empty("⚠️", "No syllabus file for this subject.", ex.message);
    return;
  }

  const rows = tax.topics.map((t, i) => {
    const chapter = S.progress.get(pkey(syl, t.name, null)) || "not_started";
    const subs = t.subtopics.map(name => {
      const st = S.progress.get(pkey(syl, t.name, name)) || "not_started";
      return `<div class="sub-row">
        <span class="sub-name">${H.esc(name)}</span>
        ${seg(st, `data-topic="${H.esc(t.name)}" data-sub="${H.esc(name)}"`)}
      </div>`;
    }).join("");

    const done = t.subtopics.filter(n =>
      S.progress.get(pkey(syl, t.name, n)) === "confident").length;

    return `
      <div class="chap${subs ? "" : " chap-flat"}" data-chap="${i}">
        <div class="chap-head">
          ${subs ? `<button class="chap-toggle" data-toggle="${i}" aria-expanded="false">▸</button>`
                 : `<span class="chap-toggle chap-toggle-flat"></span>`}
          <div class="chap-name">
            <strong>${H.esc(t.name)}</strong>
            ${t.subtopics.length
              ? `<em>${done}/${t.subtopics.length} subtopics confident</em>`
              : `<em>no subtopics in this syllabus</em>`}
          </div>
          ${seg(chapter, `data-topic="${H.esc(t.name)}" data-sub=""`)}
          ${t.subtopics.length
            ? `<button class="btn btn-ghost chap-all" data-all="${H.esc(t.name)}"
                       title="Apply the chapter status to every subtopic">Apply to all</button>`
            : ""}
        </div>
        ${subs ? `<div class="chap-subs" hidden>${subs}</div>` : ""}
      </div>`;
  }).join("");

  const ringSummary = await buildRingsSummary();
  const el = document.getElementById("prog-body");
  el.innerHTML = `${ringSummary}<div class="chap-list">${rows}</div>`;

  el.querySelectorAll("[data-ring-syl]").forEach(b => b.addEventListener("click", () => {
    S.progressSyllabus = b.dataset.ringSyl;
    render();
  }));

  el.querySelectorAll("[data-toggle]").forEach(b => b.addEventListener("click", () => {
    const wrap = b.closest(".chap").querySelector(".chap-subs");
    wrap.hidden = !wrap.hidden;
    b.textContent = wrap.hidden ? "▸" : "▾";
    b.setAttribute("aria-expanded", String(!wrap.hidden));
  }));

  el.querySelectorAll(".seg-btn").forEach(b => b.addEventListener("click", () =>
    setProgress(b, syl)));

  el.querySelectorAll("[data-all]").forEach(b => b.addEventListener("click", () =>
    applyToAll(b.dataset.all, syl)));
}

async function taxonomy(syllabus) {
  if (!S.taxonomy[syllabus]) {
    S.taxonomy[syllabus] = await H.api(
      `/api/teacher/syllabus/${encodeURIComponent(syllabus)}/topics`);
  }
  return S.taxonomy[syllabus];
}

async function buildRingsSummary() {
  const codes = subjectCodes();
  if (!codes.length) return "";
  const results = await Promise.allSettled(codes.map(async syl => {
    let tax;
    try { tax = await taxonomy(syl); } catch { return null; }
    const topics = tax.topics || [];
    if (!topics.length) return null;
    const confident = topics.filter(t => S.progress.get(pkey(syl, t.name, null)) === "confident").length;
    const learning  = topics.filter(t => S.progress.get(pkey(syl, t.name, null)) === "learning").length;
    const pct = Math.round(confident / topics.length * 100);
    return { syl, confident, learning, total: topics.length, pct };
  }));
  const stats = results.filter(r => r.status === "fulfilled" && r.value).map(r => r.value);
  if (!stats.length) return "";
  const r = 28, circ = +(2 * Math.PI * r).toFixed(2);
  const cards = stats.map(s => {
    const offset = +(circ * (1 - s.pct / 100)).toFixed(2);
    const isActive = s.syl === S.progressSyllabus;
    return `<div data-ring-syl="${H.esc(s.syl)}"
      style="display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 10px;border-radius:10px;
             cursor:pointer;background:${isActive ? "var(--bg-muted,#f3f0fb)" : "transparent"};
             border:1px solid ${isActive ? "var(--navy,#2E1B4A)" : "transparent"};
             transition:background .15s;min-width:76px;max-width:90px">
      <div style="position:relative;width:64px;height:64px">
        <svg viewBox="0 0 64 64" width="64" height="64">
          <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--border,#e5e7eb)" stroke-width="6"/>
          <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--navy,#2E1B4A)" stroke-width="6"
                  stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
                  stroke-linecap="round" transform="rotate(-90 32 32)"/>
        </svg>
        <span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                     font-size:.68rem;font-weight:800;color:var(--text,#111)">${s.pct}%</span>
      </div>
      <div style="font-size:.62rem;font-weight:700;text-align:center;color:var(--text,#111);
                  max-width:78px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${H.esc(H.subjectName(s.syl))}</div>
      <div style="font-size:.58rem;color:var(--muted,#888)">${s.confident}/${s.total} chapters</div>
      ${s.learning ? `<div style="font-size:.58rem;color:#ca8a04">${s.learning} learning</div>` : ""}
    </div>`;
  }).join("");
  return `<div style="display:flex;flex-wrap:wrap;gap:6px;padding:12px 4px 16px;
                      margin-bottom:12px;border-bottom:1px solid var(--border,#e5e7eb)">
    ${cards}
  </div>`;
}

async function loadGradeBadges(container, syl) {
  const rows = [...container.querySelectorAll(".pp-row")];
  const groups = new Map();
  rows.forEach(row => {
    const inp = row.querySelector(".pp-score");
    if (!inp || inp.value === "") return;
    const key = `${inp.dataset.year}__${inp.dataset.session}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ inp, row });
  });
  if (!groups.size) return;

  for (const [key, items] of groups) {
    const [year, session] = key.split("__");
    let thresholds = [];
    try {
      const res = await H.api(
        `/api/grade-thresholds?syllabus=${encodeURIComponent(syl)}&year=${year}&session=${encodeURIComponent(session)}`);
      thresholds = res.thresholds || [];
    } catch { /* silently skip */ }

    items.forEach(({ inp, row }) => {
      const paper  = Number(inp.dataset.paper);
      const variant = inp.dataset.variant || "";
      const tRec = thresholds.find(t =>
        t.paper === paper && (String(t.variant || "") === String(variant) || !t.variant));
      const grade = calcGrade(inp.value, tRec);
      const badge = row.querySelector(".pp-grade-badge");
      if (!badge) return;
      if (grade) {
        const maxPart = tRec?.max_mark ? `<span style="font-size:.6rem;color:var(--muted,#888);margin-left:3px">/${tRec.max_mark}</span>` : "";
        badge.innerHTML = gradeChip(grade) + maxPart;
      } else {
        badge.innerHTML = "";
      }
    });
  }
}

async function setProgress(btn, syllabus) {
  const topic = btn.dataset.topic;
  const sub = btn.dataset.sub || null;
  const status = btn.dataset.status;
  const group = btn.parentElement;
  const previous = [...group.children].find(c => c.classList.contains("on"));

  group.querySelectorAll(".seg-btn").forEach(b => b.classList.toggle("on", b === btn));
  group.classList.add("seg-saving");

  try {
    await H.api(`/api/teacher/student/${encodeURIComponent(S.id)}/progress`, {
      method: "POST", body: { syllabus, topic, subtopic: sub, status },
    });
    S.progress.set(pkey(syllabus, topic, sub), status);
    refreshChapterCount(btn, syllabus);
  } catch (ex) {
    group.querySelectorAll(".seg-btn").forEach(b =>
      b.classList.toggle("on", b === previous));
    H.toast(ex.message, true);
  } finally {
    group.classList.remove("seg-saving");
  }
}

function refreshChapterCount(btn, syllabus) {
  const chap = btn.closest(".chap");
  if (!chap) return;
  const tax = S.taxonomy[syllabus];
  const name = btn.dataset.topic;
  const topic = tax?.topics.find(t => t.name === name);
  if (!topic || !topic.subtopics.length) return;
  const done = topic.subtopics.filter(n =>
    S.progress.get(pkey(syllabus, name, n)) === "confident").length;
  const em = chap.querySelector(".chap-name em");
  if (em) em.textContent = `${done}/${topic.subtopics.length} subtopics confident`;
}

async function applyToAll(topic, syllabus) {
  const tax = S.taxonomy[syllabus];
  const t = tax.topics.find(x => x.name === topic);
  if (!t) return;
  const status = S.progress.get(pkey(syllabus, topic, null)) || "not_started";
  try {
    await H.api(`/api/teacher/student/${encodeURIComponent(S.id)}/progress/bulk`, {
      method: "POST",
      body: { items: t.subtopics.map(name => ({ syllabus, topic, subtopic: name, status })) },
    });
    t.subtopics.forEach(name => S.progress.set(pkey(syllabus, topic, name), status));
    H.toast(`All ${t.subtopics.length} subtopics set to ${STATUS_LABEL[status]}.`);
    render();
  } catch (ex) {
    H.toast(ex.message, true);
  }
}

/* ---- 2. Past papers ------------------------------------------------------ */

async function renderPapers(box) {
  const codes = subjectCodes();
  if (!codes.length) {
    box.innerHTML = H.panel("Past papers",
      H.empty("📄", "No subjects yet.", "Papers appear once the student has a subject."));
    return;
  }
  const syl = S.paperSyllabus;
  const tracked = [...S.papers.values()].filter(p => p.syllabus === syl);
  const done = tracked.filter(p => p.status === "confident").length;

  box.innerHTML = H.panel("Past papers worked through",
    `${subjectPills(syl, "qsyl")}
     <div class="panel-body" id="paper-body">${H.empty("⏳", "Loading the archive…")}</div>`,
    `<span class="stu-hint">${done} marked done · ${tracked.length} tracked</span>`);

  box.querySelectorAll("[data-qsyl]").forEach(b => b.addEventListener("click", () => {
    S.paperSyllabus = b.dataset.qsyl;
    render();
  }));

  let tree;
  try {
    if (!S.paperTree[syl]) {
      S.paperTree[syl] = await H.api(
        `/api/library/tree?syllabus=${encodeURIComponent(syl)}`);
    }
    tree = S.paperTree[syl];
  } catch (ex) {
    document.getElementById("paper-body").innerHTML =
      H.empty("⚠️", "Couldn't load the paper archive.", ex.message);
    return;
  }

  const years = (tree.years || []).map(y => {
    const rows = [];
    for (const sess of y.sessions) {
      const qps = sess.files.filter(f => f.kind === "qp");
      for (const f of qps) {
        const rec = S.papers.get(paperKey({
          syllabus: syl, year: y.year, session: sess.session,
          paper: f.paper, variant: f.variant || "",
        }));
        const status = rec?.status || "not_started";
        rows.push(`
          <div class="pp-row">
            <div class="pp-name">
              <strong>${H.esc(sess.name)} ${y.year}</strong>
              <em>Paper ${f.paper}${f.variant ? " · variant " + H.esc(f.variant) : ""}</em>
            </div>
            <input class="pp-score" type="number" min="0" placeholder="score"
                   value="${rec?.score ?? ""}"
                   data-year="${y.year}" data-session="${H.esc(sess.session)}"
                   data-paper="${f.paper}" data-variant="${H.esc(f.variant || "")}">
            <span class="pp-grade-badge">${rec?.grade ? gradeChip(rec.grade) : ""}</span>
            ${seg(status, `data-year="${y.year}" data-session="${H.esc(sess.session)}"
                           data-paper="${f.paper}" data-variant="${H.esc(f.variant || "")}"`)}
          </div>`);
      }
    }
    if (!rows.length) return "";
    const yDone = rows.filter(r => r.includes("seg-confident on")).length;
    return `
      <details class="pp-year"${yDone ? " open" : ""}>
        <summary><b>${y.year}</b><span>${rows.length} papers</span>
          ${yDone ? `<span class="pp-done">${yDone} done</span>` : ""}</summary>
        <div class="pp-rows">${rows.join("")}</div>
      </details>`;
  }).join("");

  const el = document.getElementById("paper-body");
  el.innerHTML = years || H.empty("📄", "No papers downloaded for this subject yet.");

  el.querySelectorAll(".seg-btn").forEach(b =>
    b.addEventListener("click", () => savePaper(b, syl, b.dataset.status)));
  el.querySelectorAll(".pp-score").forEach(inp =>
    inp.addEventListener("change", () => savePaper(inp, syl, null)));

  loadGradeBadges(el, syl);
}

async function savePaper(el, syllabus, status) {
  const row = el.closest(".pp-row");
  const scoreInput = row.querySelector(".pp-score");
  const key = {
    syllabus,
    year: Number(el.dataset.year),
    session: el.dataset.session,
    paper: Number(el.dataset.paper),
    variant: el.dataset.variant || "",
  };
  const existing = S.papers.get(paperKey(key));
  const body = {
    ...key,
    status: status || existing?.status || "learning",
    score: scoreInput.value === "" ? null : Number(scoreInput.value),
  };

  if (status) {
    const group = el.parentElement;
    group.querySelectorAll(".seg-btn").forEach(b => b.classList.toggle("on", b === el));
  }
  try {
    const res = await H.api(`/api/teacher/student/${encodeURIComponent(S.id)}/papers`, {
      method: "POST", body,
    });
    S.papers.set(paperKey(key), res.paper);
  } catch (ex) {
    H.toast(ex.message, true);
    render();
  }
}

/* ---- 3. Class calendar --------------------------------------------------- */

function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const STATUS_META = {
  held:        { label: "Classes taken",  icon: "✅", tint: "grn" },
  rescheduled: { label: "Rescheduled",    icon: "🔄", tint: "org" },
  cancelled:   { label: "Cancelled",      icon: "✖",  tint: "gry" },
  missed:      { label: "Missed",         icon: "⚠",  tint: "pnk" },
};

function renderCalendar(box) {
  const month = S.month;
  const label = month.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const monthKey = iso(month).slice(0, 7);

  const byDate = new Map();
  for (const c of S.classes) {
    if (!byDate.has(c.class_date)) byDate.set(c.class_date, []);
    byDate.get(c.class_date).push(c);
  }

  const scope = S.calScope === "month"
    ? S.classes.filter(c => (c.class_date || "").startsWith(monthKey))
    : S.classes;
  const countOf = st => scope.filter(c => (c.status || "held") === st).length;
  const minutes = scope.filter(c => (c.status || "held") === "held")
                       .reduce((n, c) => n + (c.duration_min || 0), 0);

  const tiles = CLASS_STATUS.map(st => {
    const m = STATUS_META[st];
    return `<div class="calstat calstat-${m.tint}">
      <span class="calstat-ic">${m.icon}</span>
      <b>${countOf(st)}</b>
      <span class="calstat-lbl">${m.label}</span>
    </div>`;
  }).join("") + `
    <div class="calstat calstat-lav">
      <span class="calstat-ic">⏱</span>
      <b>${minutes >= 60 ? (minutes / 60).toFixed(minutes % 60 ? 1 : 0) + "h" : minutes + "m"}</b>
      <span class="calstat-lbl">Teaching time</span>
    </div>`;

  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const lead = (first.getDay() + 6) % 7;
  const daysIn = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const todayIso = iso(new Date());

  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(`<div class="cal-cell cal-pad"></div>`);
  for (let d = 1; d <= daysIn; d++) {
    const date = iso(new Date(month.getFullYear(), month.getMonth(), d));
    const list = byDate.get(date) || [];
    const chips = list.slice(0, 3).map(c => `
      <span class="cal-chip cal-chip-${H.esc(c.status || "held")}"
            title="${H.esc((c.topic || "Lesson") + " · " + (c.status || "held"))}">
        ${c.start_time ? H.esc(c.start_time) + " " : ""}${H.esc(
          (c.topic || (c.syllabus ? H.subjectName(c.syllabus) : "Lesson")).slice(0, 16))}
      </span>`).join("");
    cells.push(`
      <div class="cal-cell${list.length ? " has" : ""}${date === todayIso ? " today" : ""}"
           data-day="${date}" role="button" tabindex="0"
           aria-label="${date}${list.length ? `, ${list.length} class` : ", no classes — click to log one"}">
        <span class="cal-num">${d}${date === todayIso ? `<em>today</em>` : ""}</span>
        <span class="cal-chips">${chips}${
          list.length > 3 ? `<span class="cal-more">+${list.length - 3} more</span>` : ""}</span>
      </div>`);
  }

  const listRows = S.classes.length ? S.classes.map(c => {
    const st = c.status || "held";
    return `
    <tr>
      <td class="ts">${H.esc(c.class_date)}${c.start_time ? `<div class="ts">${H.esc(c.start_time)}</div>` : ""}</td>
      <td><span class="badge badge-${H.esc(st)}">${STATUS_META[st]?.icon || ""} ${H.esc(STATUS_META[st]?.label || st)}</span></td>
      <td>${H.esc(c.syllabus ? H.subjectName(c.syllabus) : "—")}</td>
      <td>${H.esc(c.topic || "—")}</td>
      <td>${c.duration_min ? H.esc(c.duration_min) + " min" : "—"}</td>
      <td>${H.esc(c.note || "—")}</td>
      <td class="row-acts">
        <button class="btn btn-ghost" data-editclass="${c.id}">Edit</button>
        <button class="btn btn-danger" data-delclass="${c.id}">Delete</button>
      </td>
    </tr>`;
  }).join("") : "";

  box.innerHTML = H.panel("Class calendar",
    `<div class="cal-wrap">
       <div class="calstat-row">${tiles}</div>
       <div class="calstat-scope">
         <button class="scope-btn${S.calScope === "month" ? " on" : ""}" data-scope="month">This month</button>
         <button class="scope-btn${S.calScope === "all" ? " on" : ""}" data-scope="all">All time</button>
       </div>

       <div class="cal-head">
         <button class="btn btn-ghost cal-nav" id="cal-prev" aria-label="Previous month">‹</button>
         <h4>${H.esc(label)}</h4>
         <button class="btn btn-ghost cal-nav" id="cal-next" aria-label="Next month">›</button>
         <button class="btn btn-ghost" id="cal-today">Today</button>
         <span class="sp"></span>
         <span class="stu-hint">Click any day to log a class</span>
       </div>
       <div class="cal-dow">${["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
         .map(d => `<span>${d}</span>`).join("")}</div>
       <div class="cal-grid">${cells.join("")}</div>
       <div class="cal-key">
         ${CLASS_STATUS.map(s => `<span><i class="dot dot-${s}"></i>${
           STATUS_META[s].label}</span>`).join("")}
       </div>
     </div>
     <div class="panel-body">
       ${listRows ? H.table(["Date", "Status", "Subject", "What you covered", "Length", "Note", ""], listRows)
                  : H.empty("📅", "No classes logged yet.",
                            "Click any day above, or use Log a class.")}
     </div>`,
    `<button class="btn btn-ok" id="cal-add">＋ Log a class</button>`);

  document.getElementById("cal-prev").addEventListener("click", () => {
    S.month = new Date(month.getFullYear(), month.getMonth() - 1, 1); render();
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    S.month = new Date(month.getFullYear(), month.getMonth() + 1, 1); render();
  });
  document.getElementById("cal-today").addEventListener("click", () => {
    S.month = startOfMonth(new Date()); render();
  });
  document.getElementById("cal-add").addEventListener("click", () => classForm());
  box.querySelectorAll("[data-scope]").forEach(b => b.addEventListener("click", () => {
    S.calScope = b.dataset.scope; render();
  }));
  box.querySelectorAll("[data-day]").forEach(c => {
    c.addEventListener("click", () => classForm(null, c.dataset.day));
    c.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); classForm(null, c.dataset.day); }
    });
  });
  box.querySelectorAll("[data-editclass]").forEach(b =>
    b.addEventListener("click", () => classForm(
      S.classes.find(c => String(c.id) === b.dataset.editclass))));
  box.querySelectorAll("[data-delclass]").forEach(b =>
    b.addEventListener("click", () => deleteClass(Number(b.dataset.delclass))));
}

function classForm(entry = null, presetDate = null) {
  const codes = subjectCodes();
  const e = entry || {};
  H.openDrawer(`
    <h3 class="drawer-title">${entry ? "Edit class" : "Log a class"}</h3>
    <form id="class-form" class="adm-form">
      <label>Date<input type="date" name="class_date" required
        value="${H.esc(e.class_date || presetDate || iso(new Date()))}"></label>
      <div class="adm-row">
        <label>Start time <em>optional</em>
          <input type="time" name="start_time" value="${H.esc(e.start_time || "")}"></label>
        <label>Length (min) <em>optional</em>
          <input type="number" name="duration_min" min="0" step="15"
                 value="${e.duration_min ?? ""}"></label>
      </div>
      <div class="adm-row">
        <label>Subject
          <select name="syllabus">
            <option value="">—</option>
            ${codes.map(c => `<option value="${H.esc(c)}"${c === e.syllabus ? " selected" : ""}>
              ${H.esc(H.subjectName(c))}</option>`).join("")}
          </select></label>
        <label>Status
          <select name="status">
            ${CLASS_STATUS.map(s => `<option value="${s}"${
              s === (e.status || "held") ? " selected" : ""}>${s}</option>`).join("")}
          </select></label>
      </div>
      <label>What you covered
        <input type="text" name="topic" placeholder="e.g. Circle theorems — cyclic quadrilaterals"
               value="${H.esc(e.topic || "")}"></label>
      <label>Note <em>optional</em>
        <textarea name="note" rows="3">${H.esc(e.note || "")}</textarea></label>
      <div class="adm-actions">
        <button type="submit" class="btn btn-ok">${entry ? "Save changes" : "Log class"}</button>
        <button type="button" class="btn" id="class-cancel">Cancel</button>
      </div>
    </form>`);

  document.getElementById("class-cancel").addEventListener("click", H.closeDrawer);
  document.getElementById("class-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const body = {
      class_date: f.class_date.value,
      start_time: f.start_time.value || null,
      duration_min: f.duration_min.value ? Number(f.duration_min.value) : null,
      syllabus: f.syllabus.value || null,
      status: f.status.value,
      topic: f.topic.value.trim() || null,
      note: f.note.value.trim() || null,
    };
    const btn = f.querySelector('button[type="submit"]');
    btn.disabled = true; btn.textContent = "Saving…";
    try {
      if (entry) {
        const res = await H.api(`/api/teacher/class/${entry.id}`,
                                { method: "PATCH", body });
        S.classes = S.classes.map(c => c.id === entry.id ? res.class : c);
      } else {
        const res = await H.api(
          `/api/teacher/student/${encodeURIComponent(S.id)}/class`,
          { method: "POST", body });
        S.classes = [res.entry, ...S.classes];
      }
      S.classes.sort((a, b) => String(b.class_date).localeCompare(String(a.class_date)));
      H.closeDrawer();
      H.toast(entry ? "Class updated." : "Class logged.");
      render();
    } catch (ex) {
      H.toast(ex.message, true);
      btn.disabled = false;
      btn.textContent = entry ? "Save changes" : "Log class";
    }
  });
}

async function deleteClass(id) {
  if (!confirm("Delete this class entry?")) return;
  try {
    await H.api(`/api/teacher/class/${id}`, { method: "DELETE" });
    S.classes = S.classes.filter(c => c.id !== id);
    H.toast("Class deleted.");
    render();
  } catch (ex) { H.toast(ex.message, true); }
}

/* ---- 4. Homework diary --------------------------------------------------- */

function submissionsHtml(a) {
  const subs = a.submissions || [];
  if (!subs.length) return `<p class="hw-dnone">Nothing handed in yet.</p>`;
  return `
    <div class="hw-dfiles hw-dsubs">
      <p class="hw-dfiles-lbl">Student submitted (${subs.length})</p>
      ${subs.map((s, i) => `
        <a class="hw-dsub-file" target="_blank" rel="noopener"
           href="/api/teacher/homework/${a.id}/submission/${i}">
          <span class="hw-dsub-ic">📥</span>
          <span><b>${H.esc(s.name || "Submission")}</b>
            <em>${s.submitted_at
              ? "Handed in " + H.esc(String(s.submitted_at).slice(0, 10))
              : "Download"}</em></span>
        </a>`).join("")}
    </div>`;
}

function renderHomework(box) {
  const open = S.assignments.filter(a => a.status !== "done");
  const done = S.assignments.filter(a => a.status === "done");

  const card = a => {
    const overdue = a.status !== "done" && a.due_date &&
                    a.due_date < iso(new Date());
    return `
      <div class="hw-card${a.status === "done" ? " hw-done" : ""}${overdue ? " hw-late" : ""}">
        <div class="hw-top">
          <span class="badge badge-kind">${H.esc(a.kind || "homework")}</span>
          ${a.syllabus ? `<span class="badge badge-lav">${H.esc(H.subjectName(a.syllabus))}</span>` : ""}
          ${a.due_date ? `<span class="hw-due${overdue ? " late" : ""}">Due ${H.esc(a.due_date)}</span>` : ""}
          <span class="sp"></span>
          ${a.status === "done"
            ? `<span class="badge badge-ok">done</span>`
            : a.seen_at ? `<span class="badge badge-pending">seen</span>`
                        : `<span class="badge badge-issue">unread</span>`}
        </div>
        <h4>${H.esc(a.title)}</h4>
        ${a.instructions ? `<p class="hw-instr">${H.esc(a.instructions)}</p>` : ""}
        ${a.topics?.length
          ? `<div class="pill-row">${a.topics.map(t =>
              `<span class="pill">${H.esc(t)}</span>`).join("")}</div>` : ""}
        ${a.attachments?.length ? `<div class="hw-atts">${a.attachments.map(t => `
          <span class="hw-att hw-att-${H.esc(t.type)}">
            ${t.type === "upload" ? "📎" : t.type === "resource" ? "📄" : "📚"}
            ${H.esc(t.name || t.rel || "attachment")}</span>`).join("")}</div>` : ""}
        ${submissionsHtml(a)}
        ${a.student_note ? `<p class="hw-note"><strong>Student note:</strong> ${H.esc(a.student_note)}</p>` : ""}
        <div class="hw-acts">
          <button class="btn btn-ghost" data-hwfile="${a.id}">＋ Attach</button>
          <button class="btn btn-ghost" data-hwedit="${a.id}">Edit</button>
          <button class="btn btn-danger" data-hwdel="${a.id}">Delete</button>
        </div>
      </div>`;
  };

  box.innerHTML = H.panel(`Homework — ${open.length} open`,
    `<div class="panel-body">
       ${open.length ? `<div class="hw-grid">${open.map(card).join("")}</div>`
                     : H.empty("📗", "Nothing outstanding.",
                               "Use Assign work to set homework, reading or a practice booklet.")}
       ${done.length ? `<h4 class="hw-sub">Completed (${done.length})</h4>
         <div class="hw-grid">${done.map(card).join("")}</div>` : ""}
     </div>`,
    `<button class="btn" id="hw-remind"${open.length ? "" : " disabled"}>✉ Remind student</button>
     <button class="btn btn-ok" id="hw-add">＋ Assign work</button>`);

  document.getElementById("hw-add").addEventListener("click", () => assignmentForm());
  document.getElementById("hw-remind").addEventListener("click", sendReminder);
  box.querySelectorAll("[data-hwedit]").forEach(b => b.addEventListener("click", () =>
    assignmentForm(S.assignments.find(a => String(a.id) === b.dataset.hwedit))));
  box.querySelectorAll("[data-hwdel]").forEach(b => b.addEventListener("click", () =>
    deleteAssignment(Number(b.dataset.hwdel))));
  box.querySelectorAll("[data-hwfile]").forEach(b => b.addEventListener("click", () =>
    attachDrawer(S.assignments.find(a => String(a.id) === b.dataset.hwfile))));
}

async function sendReminder() {
  const btn = document.getElementById("hw-remind");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const r = await H.api(
      `/api/teacher/student/${encodeURIComponent(S.id)}/remind`, { method: "POST" });
    H.toast(r.sent
      ? `Reminder emailed to ${r.email} — ${r.count} task${r.count === 1 ? "" : "s"}.`
      : (r.detail || "Email could not be sent."), !r.sent);
    if (r.whatsapp) {
      H.openDrawer(`
        <h3 class="drawer-title">Reminder sent</h3>
        <p class="drawer-sub">${r.sent
          ? `Emailed to ${H.esc(r.email)}.`
          : H.esc(r.detail || "Email is not configured on this server.")}</p>
        <p class="stu-hint" style="margin-bottom:14px">
          Want to nudge them on WhatsApp too? This opens WhatsApp with the
          message already written — you press send.</p>
        <div class="adm-actions">
          <a class="btn btn-ok" href="${H.esc(r.whatsapp)}" target="_blank"
             rel="noopener">Open WhatsApp</a>
          <button type="button" class="btn" id="rem-close">Done</button>
        </div>`);
      document.getElementById("rem-close").addEventListener("click", H.closeDrawer);
    }
  } catch (ex) {
    H.toast(ex.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "✉ Remind student";
  }
}

async function assignmentForm(entry = null) {
  const codes = subjectCodes();
  const a = entry || {};
  H.openDrawer(`
    <h3 class="drawer-title">${entry ? "Edit assignment" : "Assign work"}</h3>
    <form id="hw-form" class="adm-form">
      <div class="adm-row">
        <label>Subject
          <select name="syllabus" id="hw-syllabus">
            <option value="">—</option>
            ${codes.map(c => `<option value="${H.esc(c)}"${c === a.syllabus ? " selected" : ""}>
              ${H.esc(H.subjectName(c))}</option>`).join("")}
          </select></label>
        <label>Type
          <select name="kind">
            ${KINDS.map(([v, l]) => `<option value="${v}"${
              v === (a.kind || "homework") ? " selected" : ""}>${l}</option>`).join("")}
          </select></label>
      </div>
      <label>Title
        <input type="text" name="title" required maxlength="140"
               placeholder="e.g. Circle theorems — past-paper drill"
               value="${H.esc(a.title || "")}"></label>
      <label>Instructions
        <textarea name="instructions" rows="4"
          placeholder="e.g. Do Q1–Q8 from the attached worksheet. Show every step of working.">${H.esc(a.instructions || "")}</textarea></label>
      <div class="adm-row">
        <label><span id="hw-date-lbl">${(a.kind || "homework") === "test" ? "Test date" : "Due date"}</span> <em>optional</em>
          <input type="date" name="due_date" value="${H.esc(a.due_date || "")}"></label>
        <label>Status
          <select name="status">
            <option value="assigned"${a.status !== "done" ? " selected" : ""}>Assigned</option>
            <option value="done"${a.status === "done" ? " selected" : ""}>Done</option>
          </select></label>
      </div>
      <label>Chapters this covers <em>optional</em>
        <div class="hw-topics" id="hw-topics">
          <span class="stu-hint">Pick a subject to list its chapters.</span>
        </div></label>
      <div class="adm-actions">
        <button type="submit" class="btn btn-ok">${entry ? "Save changes" : "Assign"}</button>
        <button type="button" class="btn" id="hw-cancel">Cancel</button>
      </div>
    </form>`);

  document.getElementById("hw-cancel").addEventListener("click", H.closeDrawer);

  const sylSel = document.getElementById("hw-syllabus");
  const loadTopics = async () => {
    const box = document.getElementById("hw-topics");
    const code = sylSel.value;
    if (!code) { box.innerHTML = `<span class="stu-hint">Pick a subject to list its chapters.</span>`; return; }
    box.innerHTML = `<span class="stu-hint">Loading chapters…</span>`;
    try {
      const tax = await taxonomy(code);
      const chosen = new Set(a.topics || []);
      box.innerHTML = tax.topics.map(t => `
        <label class="hw-topic"><input type="checkbox" value="${H.esc(t.name)}"
          ${chosen.has(t.name) ? "checked" : ""}> ${H.esc(t.name)}</label>`).join("");
    } catch (ex) {
      box.innerHTML = `<span class="stu-hint">No chapter list for this subject.</span>`;
    }
  };
  sylSel.addEventListener("change", loadTopics);
  if (sylSel.value) loadTopics();

  const kindSel = document.querySelector('#hw-form select[name="kind"]');
  kindSel?.addEventListener("change", () => {
    const lbl = document.getElementById("hw-date-lbl");
    if (lbl) lbl.textContent = kindSel.value === "test" ? "Test date" : "Due date";
  });

  document.getElementById("hw-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const body = {
      syllabus: f.syllabus.value || null,
      kind: f.kind.value,
      title: f.title.value.trim(),
      instructions: f.instructions.value.trim() || null,
      due_date: f.due_date.value || "",
      status: f.status.value,
      topics: [...document.querySelectorAll("#hw-topics input:checked")].map(c => c.value),
    };
    const btn = f.querySelector('button[type="submit"]');
    btn.disabled = true; btn.textContent = "Saving…";
    try {
      let res;
      if (entry) {
        res = await H.api(`/api/teacher/homework/${entry.id}`, { method: "PATCH", body });
        S.assignments = S.assignments.map(x => x.id === entry.id ? res.assignment : x);
      } else {
        res = await H.api(`/api/teacher/student/${encodeURIComponent(S.id)}/homework`,
                          { method: "POST", body: {
                            syllabus: body.syllabus,
                            kind: body.kind,
                            title: body.title,
                            instructions: body.instructions,
                            topics_json: JSON.stringify(body.topics),
                            due_date: body.due_date || null,
                          }});
        S.assignments = [res.assignment, ...S.assignments];
      }
      H.closeDrawer();
      H.toast(entry ? "Assignment updated." : "Work assigned.");
      render();
      if (!entry) attachDrawer(res.assignment);
    } catch (ex) {
      H.toast(ex.message, true);
      btn.disabled = false;
      btn.textContent = entry ? "Save changes" : "Assign";
    }
  });
}

async function deleteAssignment(id) {
  if (!confirm("Delete this assignment? Any file you uploaded to it goes too.")) return;
  try {
    await H.api(`/api/teacher/homework/${id}`, { method: "DELETE" });
    S.assignments = S.assignments.filter(a => a.id !== id);
    H.toast("Assignment deleted.");
    render();
  } catch (ex) { H.toast(ex.message, true); }
}

async function attachDrawer(assignment) {
  if (!assignment) return;
  const current = assignment.attachments || [];

  H.openDrawer(`
    <h3 class="drawer-title">Attachments</h3>
    <p class="drawer-sub">${H.esc(assignment.title)}</p>

    <div class="att-current" id="att-current">
      ${current.length ? current.map((t, i) => `
        <div class="att-row">
          <span>${t.type === "upload" ? "📎" : t.type === "resource" ? "📄" : "📚"}
            ${H.esc(t.name || t.rel)}</span>
          <button class="btn btn-danger" data-rmatt="${i}">Remove</button>
        </div>`).join("")
        : `<span class="stu-hint">Nothing attached yet.</span>`}
    </div>

    <h4 class="att-head">Upload a file</h4>
    <form id="att-upload" class="adm-form">
      <label>File <em>PDF, image, doc — up to 25 MB</em>
        <input type="file" name="file" required></label>
      <label>Label the student sees <em>optional</em>
        <input type="text" name="label" placeholder="e.g. Week 3 worksheet"></label>
      <div class="up-progress" id="up-progress" hidden>
        <div class="up-bar"><i id="up-fill"></i></div>
        <div class="up-meta">
          <span id="up-pct">0%</span>
          <span id="up-detail"></span>
        </div>
      </div>
      <button type="submit" class="btn btn-ok">Upload &amp; attach</button>
    </form>

    <h4 class="att-head">Assign notes from Resources</h4>
    <div class="res-picker" id="res-picker">
      <div class="res-scope" id="res-scope"></div>
      <input type="search" id="res-search" class="res-search"
             placeholder="Search within these notes…">
      <div class="res-crumbs" id="res-crumbs" hidden></div>
      <div class="res-results" id="res-results">
        <p class="stu-hint">Loading resources…</p>
      </div>
      <div class="res-chosen" id="res-chosen" hidden></div>
      <button type="button" class="btn btn-ok" id="res-attach" disabled>Attach these notes</button>
    </div>

    <h4 class="att-head">Attach a practice booklet</h4>
    <form id="att-booklet" class="adm-form">
      <p class="stu-hint">Builds a topical booklet from the chapters on this
        assignment. The student downloads it from their homework page.</p>
      <div class="adm-row">
        <label>From year<input type="number" name="year_from" value="2022" min="2015" max="2030"></label>
        <label>To year<input type="number" name="year_to" value="2025" min="2015" max="2030"></label>
      </div>
      <label>Mode
        <select name="mode">
          <option value="topical">Topical booklet (mark scheme included)</option>
          <option value="test">Mock test (mark scheme separate)</option>
        </select></label>
      <button type="submit" class="btn btn-ok">Attach booklet</button>
    </form>

    <div class="adm-actions">
      <button type="button" class="btn" id="att-close">Done</button>
    </div>`);

  document.getElementById("att-close").addEventListener("click", H.closeDrawer);

  const refresh = updated => {
    S.assignments = S.assignments.map(a => a.id === updated.id ? updated : a);
    render();
    attachDrawer(updated);
  };

  document.querySelectorAll("[data-rmatt]").forEach(b =>
    b.addEventListener("click", async () => {
      const keep = current.filter((_, i) => i !== Number(b.dataset.rmatt));
      try {
        const res = await H.api(`/api/teacher/homework/${assignment.id}`, {
          method: "PATCH",
          body: { attachments: keep.map(t => ({
            type: t.type, name: t.name, rel: t.rel, params: t.params })) },
        });
        H.toast("Attachment removed.");
        refresh(res.assignment);
      } catch (ex) { H.toast(ex.message, true); }
    }));

  document.getElementById("att-upload").addEventListener("submit", ev => {
    ev.preventDefault();
    const f = ev.target;
    if (!f.file.files.length) return;
    const file = f.file.files[0];
    const fd = new FormData();
    fd.append("file", file);
    if (f.label.value.trim()) fd.append("label", f.label.value.trim());

    const btn = f.querySelector("button");
    const wrap = document.getElementById("up-progress");
    const fill = document.getElementById("up-fill");
    const pct = document.getElementById("up-pct");
    const detail = document.getElementById("up-detail");
    wrap.hidden = false;
    btn.disabled = true;
    btn.textContent = "Uploading…";
    const started = Date.now();

    H.uploadWithProgress(
      `/api/teacher/homework/${assignment.id}/files`, fd,
      ({ loaded, total, done }) => {
        const share = total ? loaded / total : 0;
        fill.style.width = (share * 100).toFixed(1) + "%";
        pct.textContent = Math.round(share * 100) + "%";
        if (done) { detail.textContent = "Saving on the server…"; return; }
        const secs = (Date.now() - started) / 1000;
        const rate = secs > 0.4 ? loaded / secs : 0;
        const left = rate ? (total - loaded) / rate : 0;
        detail.textContent =
          `${fmtBytes(loaded)} of ${fmtBytes(total)}` +
          (rate ? ` · ${fmtBytes(rate)}/s · ${fmtTime(left)} left` : "");
      })
      .then(res => {
        fill.style.width = "100%";
        pct.textContent = "100%";
        detail.textContent = `Uploaded in ${fmtTime((Date.now() - started) / 1000)}`;
        H.toast("File attached.");
        setTimeout(() => refresh(res.assignment), 500);
      })
      .catch(ex => {
        wrap.hidden = true;
        H.toast(ex.message, true);
        btn.disabled = false;
        btn.textContent = "Upload & attach";
      });
  });

  if (!S.resources) {
    try {
      S.resources = (await H.api("/api/teacher/resources-flat")).files || [];
    } catch { S.resources = []; }
  }

  let chosenRel = null;
  const search = document.getElementById("res-search");
  const results = document.getElementById("res-results");
  const crumbs = document.getElementById("res-crumbs");
  const chosenBox = document.getElementById("res-chosen");
  const attachBtn = document.getElementById("res-attach");

  const grade = S.detail.profile.grade;
  const boardWords = { "O Level": ["o level"], "IGCSE": ["igcse"],
                       "A Level": ["a level", "as level"] }[grade] || [];

  function inScope(f) {
    const cat = (f.category || "").toLowerCase();
    if (assignment.syllabus) return cat.includes(assignment.syllabus);
    return boardWords.length ? boardWords.some(w => cat.includes(w)) : true;
  }

  const scoped = S.resources.filter(inScope);
  const scopeFolders = [...new Set(scoped.map(f => f.category))].filter(Boolean);
  let scopeOn = scoped.length > 0;
  const scopeLabel = assignment.syllabus
    ? (scopeFolders[0] || H.subjectName(assignment.syllabus))
    : grade ? `${grade} subjects` : "All subjects";

  let cwd = scopeOn && scopeFolders.length === 1 ? [scopeFolders[0]] : [];

  const pool = () => (scopeOn ? scoped : S.resources);
  const segs = f => f.rel.split("/");

  const scopeBar = document.getElementById("res-scope");
  function paintScope() {
    scopeBar.innerHTML = scopeOn
      ? `<span class="res-scope-on">📁 ${H.esc(scopeLabel)}
           <em>${scoped.length} file${scoped.length === 1 ? "" : "s"}</em></span>
         <button type="button" class="res-scope-toggle" data-showall="1">Show all subjects</button>`
      : `<span class="res-scope-off">Browsing every subject</span>
         ${scoped.length ? `<button type="button" class="res-scope-toggle"
              data-showall="0">Back to ${H.esc(scopeLabel)}</button>` : ""}`;
    scopeBar.querySelectorAll("[data-showall]").forEach(b =>
      b.addEventListener("click", () => {
        scopeOn = b.dataset.showall === "0";
        cwd = scopeOn && scopeFolders.length === 1 ? [scopeFolders[0]] : [];
        search.value = "";
        paintScope();
        renderPicker();
      }));
  }

  function paintCrumbs() {
    crumbs.hidden = false;
    const start = scopeOn && scopeFolders.length === 1 ? 1 : 0;
    const parts = [`<button type="button" class="res-crumb" data-depth="${start}">
        ${scopeOn ? "📁 " + H.esc(scopeLabel) : "📁 All subjects"}</button>`];
    cwd.slice(start).forEach((seg, i) => {
      parts.push(`<span class="res-crumb-sep">›</span>
        <button type="button" class="res-crumb" data-depth="${start + i + 1}">${H.esc(seg)}</button>`);
    });
    crumbs.innerHTML = parts.join("");
    crumbs.querySelectorAll(".res-crumb").forEach(b =>
      b.addEventListener("click", () => {
        cwd = cwd.slice(0, Number(b.dataset.depth));
        renderPicker();
      }));
  }

  function pickFile(btn) {
    chosenRel = btn.dataset.rel;
    results.querySelectorAll(".res-file").forEach(x =>
      x.classList.toggle("on", x === btn));
    const f = S.resources.find(x => x.rel === chosenRel);
    chosenBox.hidden = false;
    chosenBox.innerHTML =
      `<strong>Selected:</strong> ${H.esc(f.name)}<em>${H.esc(f.rel)}</em>`;
    attachBtn.disabled = false;
  }

  function fileRow(f) {
    return `<button type="button" class="res-file${f.rel === chosenRel ? " on" : ""}"
                    data-rel="${H.esc(f.rel)}">
      <span class="res-file-ic">📄</span>
      <span class="res-file-name">${H.esc(f.name)}</span>
      <span class="res-file-size">${fmtBytes(f.size)}</span>
    </button>`;
  }

  function renderSearch(q) {
    crumbs.hidden = true;
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = pool().filter(f => {
      const hay = (f.rel + " " + f.name).toLowerCase();
      return terms.every(t => hay.includes(t));
    });
    if (!hits.length) {
      results.innerHTML = `<p class="stu-hint">Nothing matches "${H.esc(q)}"${
        scopeOn ? ` in ${H.esc(scopeLabel)} — try "Show all subjects".` : "."}</p>`;
      return;
    }
    const shown = hits.slice(0, 150);
    results.innerHTML =
      `<p class="res-count">${hits.length} match${hits.length === 1 ? "" : "es"}${
        hits.length > shown.length ? ` · showing first ${shown.length}` : ""}</p>` +
      shown.map(f => `
        <div class="res-hit">
          ${fileRow(f)}
          <span class="res-hit-path">${H.esc(segs(f).slice(0, -1).join(" › "))}</span>
        </div>`).join("");
    results.querySelectorAll(".res-file").forEach(b =>
      b.addEventListener("click", () => pickFile(b)));
  }

  function renderBrowse() {
    paintCrumbs();
    const depth = cwd.length;
    const here = pool().filter(f => {
      const s = segs(f);
      return cwd.every((c, i) => s[i] === c);
    });

    const folders = new Map();
    const files = [];
    for (const f of here) {
      const s = segs(f);
      if (s.length > depth + 1) {
        folders.set(s[depth], (folders.get(s[depth]) || 0) + 1);
      } else {
        files.push(f);
      }
    }

    if (!folders.size && !files.length) {
      results.innerHTML = `<p class="stu-hint">This folder is empty.</p>`;
      return;
    }

    const folderHtml = [...folders.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([name, n]) => `
        <button type="button" class="res-dir" data-dir="${H.esc(name)}">
          <span class="res-dir-ic">📁</span>
          <span class="res-dir-name">${H.esc(name)}</span>
          <span class="res-dir-count">${n} file${n === 1 ? "" : "s"}</span>
          <span class="res-dir-go">›</span>
        </button>`).join("");

    results.innerHTML =
      folderHtml +
      (files.length
        ? `<div class="res-files">${files
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(fileRow).join("")}</div>`
        : "");

    results.querySelectorAll("[data-dir]").forEach(b =>
      b.addEventListener("click", () => {
        cwd = [...cwd, b.dataset.dir];
        results.scrollTop = 0;
        renderPicker();
      }));
    results.querySelectorAll(".res-file").forEach(b =>
      b.addEventListener("click", () => pickFile(b)));
  }

  function renderPicker() {
    const q = search.value.trim();
    if (q) renderSearch(q); else renderBrowse();
  }

  paintScope();
  renderPicker();
  let searchTimer = null;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderPicker, 120);
  });

  attachBtn.addEventListener("click", async () => {
    if (!chosenRel) return H.toast("Pick a file first.", true);
    const chosen = S.resources.find(f => f.rel === chosenRel);
    attachBtn.disabled = true;
    attachBtn.textContent = "Attaching…";
    try {
      const res = await H.api(`/api/teacher/homework/${assignment.id}`, {
        method: "PATCH",
        body: {
          attachments: [
            ...current.map(t => ({ type: t.type, name: t.name, rel: t.rel, params: t.params })),
            { type: "resource", rel: chosenRel, name: chosen?.name || chosenRel },
          ],
        },
      });
      H.toast("Notes attached.");
      refresh(res.assignment);
    } catch (ex) {
      H.toast(ex.message, true);
      attachBtn.disabled = false;
      attachBtn.textContent = "Attach these notes";
    }
  });

  document.getElementById("att-booklet").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target;
    const topics = assignment.topics || [];
    if (!assignment.syllabus || !topics.length) {
      return H.toast("Set a subject and tick at least one chapter on the assignment first.", true);
    }
    const params = {
      syllabus: assignment.syllabus,
      topics,
      year_from: Number(f.year_from.value),
      year_to: Number(f.year_to.value),
      mode: f.mode.value,
    };
    try {
      const res = await H.api(`/api/teacher/homework/${assignment.id}`, {
        method: "PATCH",
        body: {
          attachments: [
            ...current.map(t => ({ type: t.type, name: t.name, rel: t.rel, params: t.params })),
            { type: "booklet",
              name: `${topics.slice(0, 2).join(", ")}${topics.length > 2 ? "…" : ""} · ${params.year_from}–${params.year_to}`,
              params },
          ],
        },
      });
      H.toast("Booklet attached.");
      refresh(res.assignment);
    } catch (ex) { H.toast(ex.message, true); }
  });
}
