import { $, $$, api, esc, icon, qs, avatar, planPill, pill, rel, fmtDate, pct, minutes, num,
         modal, toast, lookup, waLink, PLAN_LABELS, PLAN_SUBJECT_LIMITS, BOARD_LABELS } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Students";

const COLUMNS = [
  { key: "name", label: "Student", sort: true, firstDir: "asc", render: r => `
      <div class="who">${avatar(r)}<div><b>${esc(r.name || "—")}</b>
        <span class="small">${esc(r.email || "")}</span>
        ${r.missing_fields?.length ? `<div>${pill(`missing ${r.missing_fields.join(", ")}`, "warn")}</div>` : ""}</div></div>` },
  { key: "country", label: "WhatsApp · Country", sort: true, firstDir: "asc", render: r => {
      const wa = waLink(r.phone);
      if (!r.phone) return `<span class="faint">—</span>`;
      return `<span class="nowrap">${esc(r.phone)}</span>${wa
        ? ` <a class="btn sm icon ghost wa" href="${wa}" target="_blank" rel="noopener" aria-label="WhatsApp ${esc(r.name || "")}">${icon("brand-whatsapp")}</a>` : ""}
        <div class="small country">${r.country
          ? `<span class="cc">${esc(r.country)}</span> ${esc(r.country_name)}`
          : `<span class="faint">country unknown</span>`}</div>`;
    } },
  { key: "boards", label: "Boards", render: r => r.boards.map(b => esc(BOARD_LABELS[b] || b)).join(", ") || `<span class="faint">—</span>` },
  { key: "plan", label: "Plan", sort: true, render: r => `${planPill(r)}
      ${r.plan_subjects?.length && r.plan !== "all" ? `<div class="small faint">${esc(r.plan_subjects.join(", "))}</div>` : ""}
      ${r.plan !== "free" && r.plan_expires_at ? `<div class="small ${r.plan_expired ? "tone-bad" : "faint"}">${r.plan_expired ? "expired" : "until"} ${esc(fmtDate(r.plan_expires_at))}</div>` : ""}` },
  { key: "plan_expires_at", label: "Plan expires", sort: true, hidden: true, render: r => r.plan !== "free" ? esc(fmtDate(r.plan_expires_at)) : "—" },
  { key: "subjects", label: "Subjects", sort: true, render: r => short(r.subjects) || `<span class="faint">none</span>` },
  { key: "teachers", label: "Teacher", render: r => esc(r.teachers.join(", ")) || `<span class="faint">—</span>` },
  { key: "streak", label: "Streak", sort: true, num: true, render: r => r.streak ? `${r.streak} d` : `<span class="faint">0</span>` },
  { key: "minutes_7", label: "Time 7d", sort: true, num: true, render: r => r.minutes_7 ? esc(minutes(r.minutes_7)) : `<span class="faint">—</span>` },
  { key: "booklets", label: "Booklets", sort: true, num: true, render: r => num(r.booklets) },
  { key: "mcq_avg", label: "MCQ avg", sort: true, num: true, render: r => r.mcq_avg === null ? `<span class="faint">—</span>` : `${pct(r.mcq_avg)} <span class="small faint">(${r.mcq_sessions})</span>` },
  { key: "quiz_avg", label: "Quiz avg", sort: true, num: true, hidden: true, render: r => r.quiz_avg === null ? "—" : `${pct(r.quiz_avg)} <span class="small faint">(${r.quiz_count})</span>` },
  { key: "confident_pct", label: "Chapters confident", sort: true, num: true, hidden: true, render: r => `${pct(r.confident_pct)} <span class="small faint">(${r.topics_confident}/${r.topics_tracked})</span>` },
  { key: "papers_done", label: "Yearly done", sort: true, num: true, render: r => num(r.papers_done) },
  { key: "open_homework", label: "Homework", sort: true, num: true, render: r => r.open_homework ? pill(`${r.open_homework} open`, "bad") : `<span class="faint">—</span>` },
  { key: "last_active", label: "Last active", sort: true, render: r => `<span class="nowrap ${isStale(r.last_active) ? "tone-bad" : ""}">${esc(rel(r.last_active))}</span>` },
  { key: "created_at", label: "Joined", sort: true, hidden: true, render: r => esc(fmtDate(r.created_at)) },
];

/** First three, then "+N" with the full list on hover. */
function short(list) {
  if (list.length <= 3) return esc(list.join(", "));
  return `<span title="${esc(list.join(", "))}">${esc(list.slice(0, 3).join(", "))} ${pill(`+${list.length - 3}`)}</span>`;
}

const isStale = iso => !iso || Date.now() - new Date(iso).getTime() > 7 * 86400000;

const FILTERS = [
  { key: "board", label: "All boards", options: c => Object.keys(BOARD_LABELS).map(b => ({ value: b, label: BOARD_LABELS[b], count: c[b] || 0 })) },
  { key: "plan", label: "All plans", options: c => ["free", "trial", "solo", "three", "all", "expired"]
      .map(p => ({ value: p, label: PLAN_LABELS[p], count: c[p] || 0 })) },
  { key: "country", label: "All countries", options: (c, meta) => Object.keys(c)
      .sort((a, b) => c[b] - c[a] || a.localeCompare(b))      // most students first
      .map(k => ({ value: k, label: k === "unknown" ? "Unknown country" : (meta.country_names?.[k] || k), count: c[k] })) },
  { key: "subject", label: "All subjects", options: c => Object.keys(c).sort().map(s => ({ value: s, label: s, count: c[s] })) },
  { key: "active", label: "Any activity", options: () => [
      { value: "today", label: "Active today" }, { value: "7", label: "Active in 7 days" },
      { value: "30", label: "Active in 30 days" }, { value: "inactive7", label: "Inactive 7+ days" },
      { value: "inactive30", label: "Inactive 30+ days" }, { value: "never", label: "Never practised" }] },
  { key: "profile", label: "Any profile", options: () => [
      { value: "complete", label: "Profile complete" }, { value: "incomplete", label: "Profile incomplete" }] },
  { key: "teacher", label: "Any teacher", options: () => [
      { value: "yes", label: "Has a teacher" }, { value: "no", label: "No teacher" }] },
  { key: "expiring", label: "Any expiry", options: () => [
      { value: "3", label: "Plan expires in 3 days" }, { value: "7", label: "Plan expires in 7 days" },
      { value: "30", label: "Plan expires in 30 days" }] },
];

const BUILTIN_VIEWS = [
  { name: "Inactive 7 days", params: { active: "inactive7" } },
  { name: "Plans expiring", params: { expiring: "7" } },
  { name: "Incomplete profiles", params: { profile: "incomplete" } },
  { name: "No teacher", params: { teacher: "no" } },
];

export async function render(el, { params, setParams }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Students</h1>
      <p>Click a row for the full activity log. Tick rows for bulk actions.</p></div></div>
    <div id="st-table"></div>`;
  const { q = "", sort, dir, page, per, ...filters } = params;
  new DataTable($("#st-table", el), {
    id: "students", views: "students", builtinViews: BUILTIN_VIEWS, noun: "students",
    columns: COLUMNS, filters: FILTERS, defaultSort: "last_active",
    searchPlaceholder: "Search name, email or phone",
    state: { q, sort: sort || "last_active", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    load: (s, fresh) => api(`/api/admin/students/table${qs({ ...s, fresh: fresh ? 1 : "" })}`),
    csv: s => `/api/admin/students/export.csv${qs(s)}`,
    onState: s => setParams(s),
    onOpen: (r, e) => {
      const url = `#/student/${r.id}`;
      if (e.ctrlKey || e.metaKey) open(url, "_blank"); else location.hash = url;
    },
    bulk: [
      { label: "Email", icon: "mail", run: bulkEmail },
      { label: "Copy WhatsApp list", icon: "brand-whatsapp", run: copyWhatsApp },
      { label: "Change plan", icon: "credit-card", run: bulkPlan },
      { label: "Assign teacher", icon: "user-plus", run: rows => bulkTeacher(rows, true) },
      { label: "Remove teacher", icon: "user-minus", run: rows => bulkTeacher(rows, false) },
      { label: "Export selected", icon: "download", run: exportSelected },
    ],
  });
}

/* ── bulk actions ─────────────────────────────────────────────────────── */

async function bulk(body) {
  const r = await api("/api/admin/students/bulk", { method: "POST", body });
  const failed = r.failed?.length ? ` (${r.failed.length} failed)` : "";
  toast(`Done for ${r.done} student${r.done === 1 ? "" : "s"}${failed}`, !!r.failed?.length && !r.done);
  return true;
}

function bulkEmail(rows) {
  const noEmail = rows.filter(r => !r.email).length;
  return modal({
    title: `Email ${rows.length} student${rows.length === 1 ? "" : "s"}`, submit: "Send", size: "lg",
    body: `
      <label class="field"><span>Subject</span><input class="input" name="subject" required autofocus></label>
      <label class="field"><span>Message</span><textarea class="textarea" name="body" required
        placeholder="Hi {first_name}, ..."></textarea></label>
      <p class="small muted">{first_name} and {name} are filled in for each student. Sends are logged on each student's timeline.
        ${noEmail ? `<br>${noEmail} selected student${noEmail === 1 ? " has" : "s have"} no email and will be skipped.` : ""}</p>`,
    run: async el => {
      const subject = $("[name=subject]", el).value.trim(), body = $("[name=body]", el).value.trim();
      if (!subject || !body) return "Write a subject and a message.";
      return bulk({ ids: rows.map(r => r.id), action: "email", subject, body });
    },
  });
}

async function copyWhatsApp(rows) {
  const nums = rows.map(r => r.phone).filter(Boolean);
  if (!nums.length) { toast("None of the selected students has a WhatsApp number", true); return false; }
  try {
    await navigator.clipboard.writeText(nums.join("\n"));
    toast(`Copied ${nums.length} number${nums.length === 1 ? "" : "s"}${nums.length < rows.length ? ` (${rows.length - nums.length} have none)` : ""}`);
  } catch {
    toast("Couldn't reach the clipboard - your browser blocked it", true);
  }
  return false;
}

export async function planModal(rows) {
  const subjects = await lookup("subjects");
  const one = rows.length === 1 ? rows[0] : null;
  const current = one ? (one.plan_subjects || []) : [];
  return modal({
    title: one ? `Change plan for ${one.name || one.email}` : `Change plan for ${rows.length} students`,
    submit: "Apply plan", size: "lg",
    body: `
      <div class="field"><span>Plan</span><div class="chips" role="radiogroup">
        ${["free", "solo", "three", "all"].map(p => `<label class="chip${(one?.plan || "free") === p ? " on" : ""}">
          <input type="radio" name="plan" value="${p}" ${(one?.plan || "free") === p ? "checked" : ""}>${esc(PLAN_LABELS[p])}</label>`).join("")}
      </div></div>
      <div class="field" data-subjects hidden><span data-subjects-label></span>
        <div class="chips">${subjects.map(s => `<label class="chip"><input type="checkbox" name="subj" value="${esc(s.code)}"
          ${current.includes(s.code) ? "checked" : ""}>${esc(s.name)} <span class="faint">${esc(s.code)}</span></label>`).join("")}</div>
        <span class="small muted">Every other subject gets free-plan limits.</span></div>
      <label class="check"><input type="checkbox" name="trial"> 7-day trial instead of 30 days</label>
      <p class="small muted">The plan starts today. A paid plan runs 30 days (7 for a trial).</p>`,
    onMount: el => {
      const sync = () => {
        const plan = $("[name=plan]:checked", el).value;
        $$(".chips label.chip", el).forEach(c => { const i = $("input", c); c.classList.toggle("on", i.checked); });
        const need = PLAN_SUBJECT_LIMITS[plan];
        $("[data-subjects]", el).hidden = !need;
        if (need) $("[data-subjects-label]", el).textContent = need === 1 ? "The subject this plan covers" : `The ${need} subjects this plan covers`;
      };
      el.addEventListener("change", e => {
        const plan = $("[name=plan]:checked", el).value;
        const need = PLAN_SUBJECT_LIMITS[plan];
        if (e.target.name === "subj" && need) {
          const ticked = $$("[name=subj]:checked", el);
          if (need === 1 && e.target.checked) ticked.forEach(i => { if (i !== e.target) i.checked = false; });
          else if (ticked.length > need) e.target.checked = false;
        }
        sync();
      });
      sync();
    },
    run: el => {
      const plan = $("[name=plan]:checked", el).value;
      const need = PLAN_SUBJECT_LIMITS[plan];
      const subjects = $$("[name=subj]:checked", el).map(i => i.value);
      if (need && subjects.length !== need) return `Tick exactly ${need} subject${need === 1 ? "" : "s"}.`;
      return bulk({ ids: rows.map(r => r.id), action: "plan", plan, trial: $("[name=trial]", el).checked,
                    subjects: need ? subjects : undefined });
    },
  });
}
const bulkPlan = rows => planModal(rows);

export async function teacherModal(rows, assign) {
  const [teachers, subjects] = await Promise.all([lookup("teachers"), lookup("subjects")]);
  if (!teachers.length) { toast("No teacher accounts yet. Approve an application first.", true); return false; }
  const n = rows.length;
  return modal({
    title: `${assign ? "Assign a teacher to" : "Remove a teacher from"} ${n === 1 ? (rows[0].name || rows[0].email) : `${n} students`}`,
    submit: assign ? "Assign" : "Remove",
    danger: !assign,
    body: `
      <label class="field"><span>Teacher</span><select class="select" name="teacher" required>
        ${teachers.map(t => `<option value="${esc(t.id)}">${esc(t.name || t.email)}</option>`).join("")}</select></label>
      <label class="field"><span>Subject${assign ? "" : " (leave empty for every subject)"}</span>
        <select class="select" name="syllabus" ${assign ? "required" : ""}>
        ${assign ? "" : `<option value="">Every subject</option>`}
        ${subjects.map(s => `<option value="${esc(s.code)}">${esc(s.name)} (${esc(s.code)})</option>`).join("")}</select></label>`,
    run: el => bulk({ ids: rows.map(r => r.id), action: assign ? "assign_teacher" : "unassign_teacher",
                      teacher_id: $("[name=teacher]", el).value, syllabus: $("[name=syllabus]", el).value || null }),
  });
}
const bulkTeacher = (rows, assign) => teacherModal(rows, assign);

function exportSelected(rows) {
  const cols = ["name", "email", "phone", "plan_effective", "subjects", "teachers", "streak",
                "booklets", "mcq_avg", "last_active"];
  const cell = v => `"${String(Array.isArray(v) ? v.join("; ") : v ?? "").replace(/"/g, '""')}"`;
  const csv = [cols.join(","), ...rows.map(r => cols.map(c => cell(r[c])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `students-selected-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return false;
}
