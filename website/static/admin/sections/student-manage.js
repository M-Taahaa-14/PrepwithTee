// The "Manage" card on a student's page: chapter progress, past-paper marks,
// the class log and homework - what the classic page's student console did.

import { $, $$, api, esc, icon, pill, rel, fmtDate, modal, toast, confirmBox, tabBar, loadingHtml,
         emptyState, ring, gradeFor, gradePill } from "../core.js";
import { setHomework, openAssignment, stateOf, STATES } from "./homework.js";

const LEVELS = [["not_started", "Not started"], ["learning", "Learning"], ["confident", "Confident"]];
const SESSIONS = { s: "May/June", w: "Oct/Nov", m: "Feb/March" };
const CLASS_STATUS = { held: ["Held", "ok"], cancelled: ["Cancelled", ""], missed: ["Missed", "bad"], rescheduled: ["Rescheduled", "warn"] };

// Remembered per student, so saving something (which re-renders the page) keeps
// the admin on the tab and subject they were working in.
const remembered = new Map();

export function mountManage(box, detail, reload) {
  const sid = detail.profile.id;
  const subjects = (detail.enrollments || []).filter(e => e.status !== "inactive").map(e => e.syllabus);
  const names = Object.fromEntries((detail.enrollments || []).map(e => [e.syllabus, e.name]));
  const state = remembered.get(sid) || { tab: "chapters", syl: subjects[0] || null };
  remembered.set(sid, state);
  const draw = () => {
    box.innerHTML = `<div class="card-head"><h2 class="grow">Manage</h2></div>
      ${tabBar([["chapters", "Chapter progress"], ["papers", "Past papers and marks"],
                ["classes", "Classes", (detail.classes || []).length], ["homework", "Homework", (detail.assignments || []).length]], state.tab)}
      <div data-manage></div>`;
    $$(".tab", box).forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.tab; draw(); }));
    const body = $("[data-manage]", box);
    if (state.tab === "classes") return classes(body, sid, detail, reload);
    if (state.tab === "homework") return homework(body, detail, reload);
    if (!subjects.length) { body.innerHTML = emptyState("school", "Not enrolled in any subject yet."); return; }
    body.innerHTML = `<div class="chips" data-subj>${subjects.map(s =>
      `<button class="chip${s === state.syl ? " on" : ""}" data-s="${esc(s)}">${esc(names[s] || s)} <span class="faint">${esc(s)}</span></button>`).join("")}</div><div data-inner>${loadingHtml()}</div>`;
    $$("[data-s]", body).forEach(b => b.addEventListener("click", () => { state.syl = b.dataset.s; draw(); }));
    const inner = $("[data-inner]", body);
    (state.tab === "chapters" ? chapters : papers)(inner, sid, state.syl, detail);
  };
  draw();
}

function seg(name, current, data) {
  return `<span class="chips seg" role="group" aria-label="${esc(name)}">${LEVELS.map(([k, l]) =>
    `<button class="chip sm${k === (current || "not_started") ? " on" : ""}" ${data} data-v="${k}" aria-pressed="${k === (current || "not_started")}">${l}</button>`).join("")}</span>`;
}

/* ── chapter progress ─────────────────────────────────────────────────── */

async function chapters(box, sid, syl, detail) {
  let tax;
  try { tax = await api(`/api/admin/syllabus/${encodeURIComponent(syl)}/topics`); }
  catch (ex) { box.innerHTML = emptyState("alert-triangle", ex.message); return; }
  const idx = {};
  (detail.progress || []).filter(p => p.syllabus === syl).forEach(p => { idx[`${p.topic}|${p.subtopic || ""}`] = p; });
  box.innerHTML = `<p class="small muted">Two separate things per chapter: how well they know it, and whether they've drilled its past-paper questions.</p>
    ${tax.topics.map((t, i) => {
      const p = idx[`${t.name}|`] || {};
      return `<details class="chapter"><summary class="row"><b class="grow">${i + 1}. ${esc(t.name)}</b>
          <span class="small faint">knows</span>${seg("Knows", p.status, `data-t="${esc(t.name)}" data-f="status"`)}
          <span class="small faint">papers</span>${seg("Past papers", p.papers_status, `data-t="${esc(t.name)}" data-f="papers_status"`)}</summary>
        ${t.subtopics.length ? `<div class="subtopics">${t.subtopics.map(st => {
          const q = idx[`${t.name}|${st}`] || {};
          return `<div class="row"><span class="grow small">${esc(st)}</span>${seg("Knows", q.status, `data-t="${esc(t.name)}" data-st="${esc(st)}" data-f="status"`)}</div>`;
        }).join("")}
          <button class="btn sm" data-all="${esc(t.name)}">Set every subtopic to the chapter's level</button></div>` : ""}
      </details>`;
    }).join("")}`;
  box.addEventListener("click", async e => {
    const b = e.target.closest("[data-v]");
    if (b) {
      e.preventDefault();
      const body = { syllabus: syl, topic: b.dataset.t, subtopic: b.dataset.st || null, [b.dataset.f]: b.dataset.v };
      try {
        await api(`/api/admin/students/${encodeURIComponent(sid)}/progress`, { method: "POST", body });
        $$(".chip", b.parentElement).forEach(c => { const on = c === b; c.classList.toggle("on", on); c.setAttribute("aria-pressed", on); });
        const key = `${b.dataset.t}|${b.dataset.st || ""}`;
        idx[key] = { ...(idx[key] || {}), [b.dataset.f]: b.dataset.v };
      } catch (ex) { toast(ex.message, true); }
      return;
    }
    const all = e.target.closest("[data-all]");
    if (all) {
      const t = tax.topics.find(x => x.name === all.dataset.all);
      const level = idx[`${t.name}|`]?.status || "not_started";
      try {
        await api(`/api/admin/students/${encodeURIComponent(sid)}/progress/bulk`, { method: "POST",
          body: { items: t.subtopics.map(st => ({ syllabus: syl, topic: t.name, subtopic: st, status: level })) } });
        t.subtopics.forEach(st => { idx[`${t.name}|${st}`] = { status: level }; });
        $$(`[data-t="${CSS.escape(t.name)}"][data-st]`, box).forEach(c => c.classList.toggle("on", c.dataset.v === level));
        toast(`${t.subtopics.length} subtopics set to ${level.replace("_", " ")}`);
      } catch (ex) { toast(ex.message, true); }
    }
  });
}

/* ── past papers and marks ────────────────────────────────────────────── */
// Same model as the student's own Yearly progress page: a status per sitting
// (not done / started / done), marks per variant with the official grade
// thresholds for that sitting, the grade worked out as you type, and rings.

const STATUS3 = [["not_started", "Not done"], ["learning", "Started"], ["confident", "Done"]];

async function papers(box, sid, syl, detail) {
  let tree;
  try { tree = await api(`/api/library/tree?syllabus=${encodeURIComponent(syl)}`); }
  catch (ex) { box.innerHTML = emptyState("alert-triangle", ex.message); return; }
  const key = (y, s, p, v) => `${y}|${s}|${p}|${v || ""}`;
  const done = {};
  (detail.papers || []).filter(p => p.syllabus === syl).forEach(p => { done[key(p.year, p.session, p.paper, p.variant)] = p; });
  const sittings = [];
  for (const y of tree.years) for (const s of y.sessions) for (const f of s.files.filter(x => x.kind === "qp")) {
    sittings.push({ year: y.year, session: s.session, sname: s.name || SESSIONS[s.session] || s.session,
                    paper: f.paper, variant: f.variant || "", code: f.code });
  }
  if (!sittings.length) { box.innerHTML = emptyState("files", "No papers in the archive for this subject."); return; }
  const comps = [...new Set(sittings.map(s => s.paper))].sort((a, b) => a - b);
  let comp = "";

  const draw = () => {
    const list = sittings.filter(s => !comp || s.paper === +comp);
    let n = 0, started = 0, scored = 0, sum = 0, best = 0;
    for (const s of list) {
      const r = done[key(s.year, s.session, s.paper, s.variant)];
      if (r?.status === "confident") n++; else if (r?.status === "learning") started++;
      if (r?.score != null && r?.max_score) { const pc = Math.round(100 * r.score / r.max_score); scored++; sum += pc; best = Math.max(best, pc); }
    }
    const byYear = new Map();
    for (const s of list) { if (!byYear.has(s.year)) byYear.set(s.year, []); byYear.get(s.year).push(s); }
    const years = [...byYear.keys()].sort((a, b) => b - a);
    box.innerHTML = `
      <div class="rings">
        ${ring(list.length ? 100 * n / list.length : 0, "Completion", "teal", null, `${n} of ${list.length} papers done`)}
        ${ring(scored ? sum / scored : 0, "Average score", "sky", scored ? null : "—", scored ? `across ${scored} marked papers` : "no marks yet")}
        ${ring(best, "Best score", "amber", scored ? null : "—", scored ? "highest percentage" : "no marks yet")}
        ${ring(list.length ? 100 * (n + started) / list.length : 0, "Papers touched", "violet", `${n + started}`, `${started} started, ${n} done`)}
      </div>
      ${comps.length > 1 ? `<div class="chips">${["", ...comps].map(c => {
        const sub = sittings.filter(s => !c || s.paper === c);
        const d = sub.filter(s => done[key(s.year, s.session, s.paper, s.variant)]?.status === "confident").length;
        return `<button class="chip${String(c) === String(comp) ? " on" : ""}" data-comp="${c}">${c ? `Paper ${c}` : "All papers"} <span class="faint">${d}/${sub.length}</span></button>`;
      }).join("")}</div>` : ""}
      <div class="stack">${years.map((y, i) => {
        const rows = byYear.get(y);
        const dn = rows.filter(s => done[key(s.year, s.session, s.paper, s.variant)]?.status === "confident").length;
        const groups = [...new Set(rows.map(r => r.paper))].sort((a, b) => a - b);
        return `<details class="pp-year"${i === 0 ? " open" : ""}><summary><b>${y}</b>
            <span class="small muted">${dn} of ${rows.length} done</span><span class="grow"></span>${icon("chevron-down")}</summary>
          ${groups.map(p => `<div class="pp-comp"><div class="pp-comp-h">Paper ${p}</div>${rows.filter(r => r.paper === p).map(s => {
            const r = done[key(s.year, s.session, s.paper, s.variant)] || {};
            const marks = r.score != null && r.max_score ? `${r.score}/${r.max_score}` : "";
            return `<div class="pp-row"><div class="nm"><b>${esc(s.sname)} ${s.year} · Paper ${s.paper}${s.variant ? ` variant ${esc(s.variant)}` : ""}</b>
                <span>${esc(s.code || "")}${r.set_by === "tutor" ? " · set by you" : ""}</span></div>
              ${r.grade || marks ? gradePill(r.grade, marks) : `<span></span>`}
              <span class="seg" role="group" aria-label="Status">${STATUS3.map(([v, l]) =>
                `<button type="button" class="${(r.status || "not_started") === v ? "on" : ""}" data-v="${v}" aria-pressed="${(r.status || "not_started") === v}"
                  data-k="${esc(key(s.year, s.session, s.paper, s.variant))}">${l}</button>`).join("")}</span>
              <button class="btn sm" data-marks="${esc(key(s.year, s.session, s.paper, s.variant))}">${icon("pencil")} Marks</button></div>`;
          }).join("")}</div>`).join("")}</details>`;
      }).join("")}</div>`;
  };

  const save = async (k, extra) => {
    const [y, ss, p, va] = k.split("|");
    const cur = done[k] || {};
    const body = { syllabus: syl, year: +y, session: ss, paper: +p, variant: va, status: cur.status || "confident",
                   score: cur.score ?? null, max_score: cur.max_score ?? null, grade: cur.grade ?? null, note: cur.note ?? null, ...extra };
    const r = await api(`/api/admin/students/${encodeURIComponent(sid)}/papers`, { method: "POST", body });
    done[k] = { ...cur, ...extra, ...(r.paper || {}), set_by: "tutor" };
  };

  box.addEventListener("click", async e => {
    const c = e.target.closest("[data-comp]");
    if (c) { comp = c.dataset.comp; draw(); return; }
    const b = e.target.closest(".seg [data-v]");
    if (b) {
      try { await save(b.dataset.k, { status: b.dataset.v }); draw(); } catch (ex) { toast(ex.message, true); }
      return;
    }
    const mk = e.target.closest("[data-marks]");
    if (mk && await marksModal(mk.dataset.marks)) draw();
  });

  async function marksModal(k) {
    const [y, ss, p] = k.split("|");
    const variants = sittings.filter(s => String(s.year) === y && s.session === ss && String(s.paper) === p);
    let th = [];
    try { th = (await api(`/api/grade-thresholds?syllabus=${encodeURIComponent(syl)}&year=${y}&session=${ss}`)).thresholds || []; }
    catch { /* thresholds are optional: grades fall back to percentages */ }
    const tFor = v => th.find(t => +t.paper === +p && (String(t.variant || "") === String(v) || !t.variant));
    const sess = SESSIONS[ss] || ss;
    return modal({
      title: `${syl} · ${sess} ${y} · Paper ${p}`, submit: "Save marks", size: "lg",
      body: `<p class="small muted">${th.length ? "Official grade thresholds for this sitting are loaded; the grade fills in as you type."
          : "No official thresholds stored for this sitting - the grade is an estimate from the percentage."}</p>
        <table class="marks-table"><thead><tr><th>Variant</th><th>Marks</th><th>Out of</th><th>Thresholds</th><th>Grade</th></tr></thead><tbody>
        ${variants.map(v => {
          const t = tFor(v.variant), cur = done[key(v.year, v.session, v.paper, v.variant)] || {};
          const max = cur.max_score || t?.max_mark || "";
          const g = gradeFor(cur.score ?? "", max, t);
          return `<tr data-v="${esc(v.variant)}"><td><b>${esc(v.code || `${p}${v.variant}`)}</b>
              <a class="small" href="/yearly/open?syllabus=${encodeURIComponent(syl)}&year=${y}&session=${ss}&paper=${p}&variant=${encodeURIComponent(v.variant)}" target="_blank" rel="noopener">${icon("external-link")} paper</a></td>
            <td><input class="input" type="number" min="0" name="s" value="${esc(cur.score ?? "")}" aria-label="Marks for ${esc(v.code || v.variant)}"></td>
            <td><input class="input" type="number" min="1" name="m" value="${esc(max)}" aria-label="Out of"></td>
            <td><div class="thresh">${t ? [["A*", t.grade_astar], ["A", t.grade_a], ["B", t.grade_b], ["C", t.grade_c], ["D", t.grade_d], ["E", t.grade_e]]
              .filter(([, n]) => n != null).map(([gg, n]) => gradePill(gg, String(n))).join("") : `<span class="small faint">none stored</span>`}</div></td>
            <td data-g>${gradePill(g.grade, g.pct != null ? `${g.pct}%${g.estimated ? " est." : ""}` : "")}</td></tr>`;
        }).join("")}</tbody></table>
        <label class="field"><span>Note (optional)</span><input class="input" name="note" value="${esc((done[k] || {}).note || "")}" placeholder="Lost marks on graph questions"></label>`,
      onMount: m => m.addEventListener("input", e => {
        const tr = e.target.closest("tr[data-v]"); if (!tr) return;
        const t = tFor(tr.dataset.v);
        const g = gradeFor($("[name=s]", tr).value, $("[name=m]", tr).value, t);
        $("[data-g]", tr).innerHTML = gradePill(g.grade, g.pct != null ? `${g.pct}%${g.estimated ? " est." : ""}` : "");
      }),
      run: async m => {
        const rows = $$("tr[data-v]", m);
        for (const tr of rows) {
          const s = $("[name=s]", tr).value, mx = $("[name=m]", tr).value;
          if (s !== "" && (mx === "" || +s > +mx || +s < 0)) return "Check the marks - each must be between 0 and the total.";
        }
        const note = $("[name=note]", m).value.trim() || null;
        for (const tr of rows) {
          const s = $("[name=s]", tr).value, mx = $("[name=m]", tr).value;
          if (s === "") continue;
          const g = gradeFor(s, mx, tFor(tr.dataset.v));
          await save(key(y, ss, p, tr.dataset.v), { status: "confident", score: +s, max_score: +mx, grade: g.grade, note });
        }
        toast("Marks saved");
        return true;
      },
    });
  }
  draw();
}

/* ── classes ──────────────────────────────────────────────────────────── */

function classes(box, sid, detail, reload) {
  const list = [...(detail.classes || [])].sort((a, b) => `${b.class_date} ${b.start_time || ""}`.localeCompare(`${a.class_date} ${a.start_time || ""}`));
  box.innerHTML = `<div class="row"><button class="btn primary" data-add>${icon("plus")} Log a class</button>
      <span class="small muted">${list.filter(c => (c.status || "held") === "held").length} held</span></div>
    ${list.length ? list.map(c => `<div class="list-row">${icon("calendar")}<div class="grow">
        <b>${esc(fmtDate(c.class_date))}${c.start_time ? ` · ${esc(c.start_time)}` : ""}${c.duration_min ? ` · ${c.duration_min} min` : ""}</b>
        <div class="small muted">${esc([c.syllabus, c.topic].filter(Boolean).join(" · "))}${c.note ? ` - ${esc(c.note)}` : ""}</div></div>
        ${pill(...(CLASS_STATUS[c.status || "held"] || [c.status, ""]))}
        <button class="btn sm icon ghost" data-edit="${c.id}" aria-label="Edit class">${icon("pencil")}</button>
        <button class="btn sm icon ghost danger" data-del="${c.id}" aria-label="Delete class">${icon("trash")}</button></div>`).join("")
      : emptyState("calendar", "No classes logged yet.")}`;
  $("[data-add]", box).addEventListener("click", async () => { if (await classForm(sid, null, detail)) reload(); });
  $$("[data-edit]", box).forEach(b => b.addEventListener("click", async () => {
    if (await classForm(sid, list.find(c => String(c.id) === b.dataset.edit), detail)) reload();
  }));
  $$("[data-del]", box).forEach(b => b.addEventListener("click", async () => {
    if (!(await confirmBox("Delete class", "Delete this class from the log?", "Delete", true))) return;
    await api(`/api/admin/classes/${b.dataset.del}`, { method: "DELETE" });
    toast("Deleted"); reload();
  }));
}

async function classForm(sid, c, detail) {
  const subjects = (detail.enrollments || []).map(e => e.syllabus);
  return modal({
    title: c ? "Edit class" : "Log a class", submit: "Save",
    body: `<div class="row"><label class="field"><span>Date</span><input class="input" type="date" name="date" required value="${esc(c?.class_date || new Date().toISOString().slice(0, 10))}"></label>
        <label class="field"><span>Start</span><input class="input" type="time" name="time" value="${esc(c?.start_time || "")}"></label>
        <label class="field"><span>Minutes</span><input class="input" type="number" min="5" max="600" name="dur" value="${esc(c?.duration_min ?? 60)}"></label></div>
      <div class="row"><label class="field grow"><span>Subject</span><select class="select" name="syl"><option value="">-</option>
          ${subjects.map(s => `<option${s === c?.syllabus ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
        <label class="field grow"><span>Status</span><select class="select" name="status">${Object.entries(CLASS_STATUS).map(([k, [l]]) =>
          `<option value="${k}"${k === (c?.status || "held") ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <label class="field"><span>Topic</span><input class="input" name="topic" value="${esc(c?.topic || "")}"></label>
      <label class="field"><span>Note</span><textarea class="textarea" name="note">${esc(c?.note || "")}</textarea></label>`,
    run: async el => {
      const v = n => $(`[name=${n}]`, el).value.trim();
      if (!v("date")) return "Pick a date.";
      const body = { class_date: v("date"), start_time: v("time") || null, duration_min: v("dur") ? +v("dur") : null,
                     syllabus: v("syl") || null, status: v("status"), topic: v("topic") || null, note: v("note") || null };
      await api(c ? `/api/admin/classes/${c.id}` : `/api/admin/students/${encodeURIComponent(sid)}/classes`,
                { method: c ? "PATCH" : "POST", body });
      toast("Saved");
      return true;
    } });
}

/* ── homework ─────────────────────────────────────────────────────────── */

function homework(box, detail, reload) {
  const p = detail.profile;
  const items = (detail.assignments || []).map(a => ({ ...a, student_name: p.name || p.email,
    submissions: (a.submissions || []).map((s, i) => ({ idx: i, name: s.name, size: s.size, submitted_at: s.submitted_at })) }))
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  box.innerHTML = `<div class="row"><button class="btn primary" data-add>${icon("plus")} Set homework</button></div>
    ${items.length ? items.map((a, i) => `<button class="list-row link" data-open="${i}">${icon("notebook")}
        <span class="grow"><b>${esc(a.title)}</b><span class="small faint"> ${esc(a.syllabus || "")} ${a.due_date ? `· due ${esc(fmtDate(a.due_date))}` : ""}</span></span>
        ${pill(...STATES[stateOf(a)])}<span class="small faint">${esc(rel(a.created_at))}</span></button>`).join("")
      : emptyState("notebook", "No homework set yet.")}`;
  $("[data-add]", box).addEventListener("click", async () => { if (await setHomework([{ id: p.id, name: p.name, email: p.email }])) reload(); });
  $$("[data-open]", box).forEach(b => b.addEventListener("click", () => openAssignment(items[+b.dataset.open], reload)));
}
