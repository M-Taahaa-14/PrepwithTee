import { $, $$, api, esc, icon, avatar, pill, rel, fmtDate, pct, minutes, num, bars,
         loadingHtml, emptyState, modal, toast, confirmBox, waLink,
         PLAN_LABELS, PLAN_TONES, BOARD_LABELS } from "../core.js";
import { planModal, teacherModal } from "./students.js";
import { mountManage } from "./student-manage.js";

export const title = "Student";

const TABS = [
  ["all", "All activity"], ["booklet", "Booklets"], ["mcq", "MCQ"], ["yearly", "Yearly papers"],
  ["quiz", "AI quizzes"], ["ai_help", "AI help"], ["tutor", "AI tutor"], ["homework", "Homework"],
  ["payment", "Payments"], ["email", "Emails"], ["note", "Notes"], ["enrol", "Subjects"],
];
const EVENT_ICONS = { booklet: "book", mcq: "checkbox", yearly: "calendar-event", quiz: "brain",
  ai_help: "sparkles", tutor: "message-chatbot", homework: "notebook", payment: "receipt",
  email: "mail", note: "note", enrol: "school" };

export async function render(el, { rest, params, setParams }) {
  const id = rest[0];
  if (!id) { location.hash = "#/students"; return; }
  el.innerHTML = `<a class="back" href="#/students">${icon("arrow-left")} Students</a><div id="sp">${loadingHtml("Loading the student…")}</div>`;
  let detail, act;
  try {
    [detail, act] = await Promise.all([
      api(`/api/admin/students/${encodeURIComponent(id)}`),
      api(`/api/admin/students/${encodeURIComponent(id)}/activity?limit=2000`),
    ]);
  } catch (ex) {
    $("#sp", el).innerHTML = `<div class="card">${emptyState("alert-triangle",
      ex.status === 404 ? "This student doesn't exist any more." : "Couldn't load this student.", ex.message)}</div>`;
    return;
  }
  const p = detail.profile;
  const s = act.summary;
  const plan = act.plan || {};
  document.title = `${p.name || p.email} · Admin · PrepWithTee`;
  const wa = waLink(p.phone);
  const planKey = plan.expired ? "expired" : plan.trial ? "trial" : (plan.plan || "free");
  const row = { id: p.id, name: p.name, email: p.email, plan: p.plan, plan_subjects: plan.plan_subjects || [] };

  $("#sp", el).innerHTML = `
    <div class="card">
      <div class="profile-head">
        ${avatar(p, "lg")}
        <div class="who">
          <h1>${esc(p.name || "No name yet")}</h1>
          <div class="meta">${esc(p.email || "")}${p.phone ? ` · ${esc(p.phone)}` : ""} · joined ${esc(fmtDate(p.created_at))}
            · last active ${esc(rel(s.last_active))}</div>
          <div class="pills">
            ${pill(PLAN_LABELS[planKey] || planKey, PLAN_TONES[planKey])}
            ${plan.expires_at && plan.plan !== "free" ? pill(`${plan.expired ? "expired" : "until"} ${fmtDate(plan.expires_at)}`, plan.expired ? "bad" : "") : ""}
            ${(plan.plan_subjects || []).length ? pill(`covers ${plan.plan_subjects.join(", ")}`, "info") : ""}
            ${act.boards.map(b => pill(BOARD_LABELS[b] || b)).join("")}
            ${act.teachers.map(t => pill(`teacher: ${t.name || t.email}`, "ok")).join("")}
          </div>
        </div>
        <div class="profile-actions">
          ${wa ? `<a class="btn wa" href="${wa}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}
          ${p.email ? `<a class="btn" href="mailto:${esc(p.email)}">${icon("mail")} Email</a>` : ""}
          <button class="btn" data-act="plan">${icon("credit-card")} Change plan</button>
          <button class="btn" data-act="teacher">${icon("user-plus")} Assign teacher</button>
          <button class="btn ghost" data-act="manage">${icon("adjustments")} Progress, marks, classes</button>
        </div>
      </div>
    </div>

    <div class="stat-tiles">
      ${tile("flame", "t-amber", "Streak", s.streak ? `${s.streak} days` : "0", s.streak_best ? `best ${s.streak_best}` : "")}
      ${tile("clock", "t-sky", "Time this week", minutes(s.minutes_7), `${s.active_days_7} active day${s.active_days_7 === 1 ? "" : "s"}`)}
      ${tile("book", "t-violet", "Booklets and tests", num(s.booklets))}
      ${tile("checkbox", "t-teal", "MCQ sessions", num(s.mcq_sessions), s.mcq_avg === null ? "" : `average ${pct(s.mcq_avg)}`)}
      ${tile("calendar-event", "t-amber", "Yearly papers", num(s.papers))}
      ${tile("brain", "t-sky", "AI quizzes", num(s.quizzes))}
      ${tile("sparkles", "t-violet", "Worked solutions", num(s.explanations))}
      ${tile("notebook", "t-rose", "Open homework", num(s.open_homework))}
    </div>

    <div class="two">
      <div class="card">
        <div class="tabs" role="tablist" data-timeline>${TABS.map(([k, label]) => {
          const n = k === "all" ? act.events.length : act.counts[k] || 0;
          return `<button class="tab" role="tab" data-tab="${k}">${esc(label)}<span class="n">${n}</span></button>`;
        }).join("")}</div>
        <div data-note-box hidden>
          <form class="note-box"><label class="sr-only" for="note-body">New note</label>
            <textarea class="textarea" id="note-body" placeholder="Private note about this student (only admins see it)"></textarea>
            <button class="btn primary">Add note</button></form>
        </div>
        <div data-events></div>
      </div>
      <div class="stack">
        <div class="card"><h2>Time on the site, last 4 weeks</h2>${timeChart(s.time_by_day)}</div>
        <div class="card"><h2>Chapter progress</h2>${progress(detail.by_syllabus)}</div>
      </div>
    </div>
    <div class="card" id="manage" data-manage-card></div>`;

  const sp = $("#sp", el);
  mountManage($("[data-manage-card]", sp), detail, () => render(el, { rest, params, setParams }));
  $("[data-act=manage]", sp).addEventListener("click", () => $("#manage", sp).scrollIntoView({ behavior: "smooth" }));
  // Widths come from data, so they're set as properties (no inline style strings).
  $$(".meter i[data-w]", sp).forEach(i => { i.style.width = `${i.dataset.w}%`; });
  $("[data-act=plan]", sp).addEventListener("click", async () => { if (await planModal([row])) render(el, { rest, params, setParams }); });
  $("[data-act=teacher]", sp).addEventListener("click", async () => { if (await teacherModal([row], true)) render(el, { rest, params, setParams }); });

  let tab = TABS.some(t => t[0] === params.tab) ? params.tab : "all";
  const drawEvents = () => {
    $$("[data-timeline] .tab", sp).forEach(b => { const on = b.dataset.tab === tab; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
    $("[data-note-box]", sp).hidden = tab !== "note";
    const list = act.events.filter(e => tab === "all" || e.type === tab);
    $("[data-events]", sp).innerHTML = list.length ? list.slice(0, 400).map(e => `
      <div class="event"><span class="ic ${e.type}">${icon(EVENT_ICONS[e.type] || "point")}</span>
        <div class="txt">${esc(e.text)}${e.by ? `<div class="small faint">by ${esc(e.by)}</div>` : ""}</div>
        <span class="when" title="${esc(e.at)}">${esc(rel(e.at))}</span>
        ${e.type === "note" ? `<button class="btn sm icon ghost" data-del-note="${e.id}" aria-label="Delete note">${icon("trash")}</button>` : ""}
      </div>`).join("") + (list.length > 400 ? `<p class="small faint">Showing the latest 400.</p>` : "")
      : emptyState("mood-empty", tab === "note" ? "No notes yet." : "Nothing here yet.");
  };
  $$("[data-timeline] .tab", sp).forEach(b => b.addEventListener("click", () => { tab = b.dataset.tab; setParams({ tab: tab === "all" ? "" : tab }); drawEvents(); }));
  $(".note-box", sp).addEventListener("submit", async e => {
    e.preventDefault();
    const body = $("#note-body", sp).value.trim();
    if (!body) { toast("Write the note first", true); return; }
    try {
      await api(`/api/admin/students/${encodeURIComponent(id)}/notes`, { method: "POST", body: { body } });
      act = await api(`/api/admin/students/${encodeURIComponent(id)}/activity?limit=2000`);
      $("#note-body", sp).value = "";
      toast("Note saved");
      refreshCounts();
      drawEvents();
    } catch (ex) { toast(ex.message, true); }
  });
  $("[data-events]", sp).addEventListener("click", async e => {
    const btn = e.target.closest("[data-del-note]");
    if (!btn || !(await confirmBox("Delete note", "Delete this note? This can't be undone.", "Delete", true))) return;
    try {
      await api(`/api/admin/students/${encodeURIComponent(id)}/notes/${btn.dataset.delNote}`, { method: "DELETE" });
      act.events = act.events.filter(x => !(x.type === "note" && String(x.id) === btn.dataset.delNote));
      act.counts.note = (act.counts.note || 1) - 1;
      refreshCounts();
      drawEvents();
    } catch (ex) { toast(ex.message, true); }
  });
  const refreshCounts = () => $$("[data-timeline] .tab", sp).forEach(b => {
    const k = b.dataset.tab;
    $(".n", b).textContent = k === "all" ? act.events.length : act.counts[k] || 0;
  });
  drawEvents();
}

function tile(ic, tone, label, value, sub = "") {
  return `<div class="kpi"><span class="kpi-ic ${tone}">${icon(ic)}</span><div class="l">${esc(label)}</div><div class="v">${esc(value)}</div>${sub ? `<div class="d faint">${esc(sub)}</div>` : ""}</div>`;
}

function timeChart(days) {
  const by = Object.fromEntries((days || []).map(d => [d.date, d.minutes]));
  const series = [];
  for (let i = 27; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    series.push({ label: d, value: by[d] || 0 });
  }
  return series.some(x => x.value) ? bars(series) : emptyState("clock", "No tracked time in the last 4 weeks.");
}

function progress(bySyl) {
  if (!bySyl?.length) return emptyState("list-check", "No chapters tracked yet.");
  return `<div class="subj-progress">${bySyl.map(s => {
    const total = s.chapters_total || 1;
    const c = (s.confident / total) * 100, l = (s.learning / total) * 100;
    const heat = (s.topics || []).map(t => {
      const h = t.status === "confident" ? "h3" : t.status === "learning" ? "h2" : "h1";
      return `<span class="${h}" title="${esc(t.topic)}: ${esc(t.status || "not started")}"></span>`;
    }).join("");
    return `<div><div class="row"><b class="grow">${esc(s.name)}</b>
        <span class="small muted">${s.confident} confident · ${s.learning} learning · ${s.not_started} not started</span></div>
      <div class="meter" role="img" aria-label="${esc(`${s.name}: ${s.pct}% of chapters confident`)}">
        <i class="c" data-w="${c.toFixed(1)}"></i><i class="l" data-w="${l.toFixed(1)}"></i></div>
      ${heat ? `<div class="heat">${heat}</div>` : ""}</div>`;
  }).join("")}</div>`;
}

