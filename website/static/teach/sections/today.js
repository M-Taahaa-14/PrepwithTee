import { $, api, esc, icon, avatar, rel, fmtDate, loadingHtml, emptyState, pill } from "/admin/core.js";
import { KIND_ICONS, KIND_LABELS } from "./folder.js";

export const title = "Today";

export async function render(el, { ctx }) {
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>${esc(hello)}, ${esc((ctx.me.name || "").split(" ")[0] || "teacher")}</h1>
      <p>Who needs you today, and what's waiting to be marked.</p></div></div><div id="td">${loadingHtml()}</div>`;
  const td = $("#td", el);
  let d;
  try { d = await api("/api/teach/overview"); }
  catch (ex) { if (td.isConnected) td.innerHTML = `<div class="card">${emptyState("alert-triangle", "Couldn't load today.", ex.message)}</div>`; return; }
  ctx.students = d.students;
  if (!td.isConnected) return;                    // navigated away meanwhile
  if (!d.students.length) {
    $("#td", el).innerHTML = `<div class="card">${emptyState("school", "No students yet.",
      "When the PrepWithTee admin assigns students to you, they appear here.")}</div>`;
    return;
  }
  const t = d.totals;
  $("#td", el).innerHTML = `
    <div class="kpis">
      ${kpi("school", "t-violet", "My students", t.students)}
      ${kpi("checklist", "t-rose", "Waiting to be marked", t.to_mark)}
      ${kpi("notebook", "t-amber", "Open homework", t.open, t.overdue ? `${t.overdue} overdue` : "none overdue")}
      ${kpi("user-off", "t-sky", "Quiet this week", d.quiet.length, "not on the site for 7 days")}
    </div>
    ${d.live.length ? `<div class="card live-card">${icon("broadcast")} <b>Class in progress</b> with
      ${d.live.map(s => `<a href="#/student/${esc(s.id)}">${esc(s.name)}</a>`).join(", ")}</div>` : ""}
    <div class="two">
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">Waiting to be marked</h2></div>
          ${d.to_mark.length ? d.to_mark.map(i => `<a class="list-row link" href="#/student/${esc(i.student_id)}?tab=folder&syl=${esc(i.syllabus)}">
              ${icon(KIND_ICONS[i.kind] || "file")}<span class="grow"><b>${esc(i.title)}</b>
              <span class="small faint">${esc(i.student)} · ${esc(KIND_LABELS[i.kind] || i.kind)}</span></span>
              <span class="small faint">finished ${esc(rel(i.student_done_at || i.updated_at))}</span></a>`).join("")
            : emptyState("circle-check", "Nothing to mark.", "Finished papers and handed-in homework land here.")}
        </div>
        <div class="card"><div class="card-head"><h2 class="grow">Homework</h2><a class="btn sm ghost" href="#/homework">All homework</a></div>
          ${[...d.handed_in, ...d.overdue.filter(s => !d.handed_in.includes(s))].length
            ? [...new Map([...d.handed_in, ...d.overdue].map(s => [s.id, s])).values()].map(s => `
              <a class="list-row link" href="#/student/${esc(s.id)}?tab=progress&mtab=homework">${avatar(s)}<span class="grow"><b>${esc(s.name)}</b></span>
                ${s.handed_in ? pill(`${s.handed_in} handed in`, "info") : ""}${s.overdue ? pill(`${s.overdue} overdue`, "bad") : ""}</a>`).join("")
            : emptyState("notebook", "No homework handed in or overdue.")}
        </div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">My students</h2><a class="btn sm ghost" href="#/students">All</a></div>
          <div class="stu-grid">${d.students.map(s => card(s)).join("")}</div></div>
        ${d.quiet.length ? `<div class="card"><h2>Quiet this week</h2><p class="small muted">A message or a short task often brings them back.</p>
          ${d.quiet.map(s => `<a class="list-row link" href="#/student/${esc(s.id)}">${avatar(s)}<span class="grow">${esc(s.name)}</span>
            <span class="small faint">last seen ${esc(rel(s.last_active))}</span></a>`).join("")}</div>` : ""}
      </div>
    </div>`;
}

function kpi(ic, tone, label, value, sub = "") {
  return `<div class="kpi"><span class="kpi-ic ${tone}">${icon(ic)}</span><div class="l">${esc(label)}</div>
    <div class="v">${esc(value)}</div>${sub ? `<div class="d faint">${esc(sub)}</div>` : ""}</div>`;
}

export function card(s) {
  return `<a class="stu-card" href="#/student/${esc(s.id)}">${avatar(s, "lg")}
    <span class="stu-name">${esc(s.name || s.email)}</span>
    <span class="chips">${s.subjects.map(c => `<span class="chip sm">${esc(c)}</span>`).join("")}</span>
    <span class="small faint">${s.last_active ? `active ${esc(rel(s.last_active))}` : "not active yet"}</span>
    <span class="row">${s.to_mark ? pill(`${s.to_mark} to mark`, "acc") : ""}${s.overdue ? pill(`${s.overdue} overdue`, "bad") : ""}
      ${s.live ? pill("in class", "ok") : ""}</span></a>`;
}

export { fmtDate };
