// One student, as their teacher sees them: a subject switch (the subjects I
// teach them), then the shared Folder, an Overview (numbers + timeline),
// Progress & marks (chapter progress, past papers, classes, homework - the
// admin's manage card on /api/teach) and my private Notes.

import { $, $$, api, esc, icon, avatar, pill, rel, fmtDate, minutes, num, pct, bars, loadingHtml, emptyState,
         modal, toast, confirmBox, waLink, tabBar } from "/admin/core.js";
import { mountManage } from "/admin/sections/student-manage.js";
import { renderFolder } from "./folder.js";

export const title = "Student";

const TABS = [["folder", "Folder"], ["overview", "Overview"], ["progress", "Progress & marks"], ["notes", "My notes"]];
const EVENT_ICONS = { booklet: "book", mcq: "checkbox", yearly: "calendar-event", quiz: "brain", ai_help: "sparkles",
  tutor: "message-chatbot", homework: "notebook", enrol: "school" };

export async function render(el, { rest, params, setParams }) {
  const id = rest[0];
  if (!id) { location.hash = "#/students"; return; }
  el.innerHTML = `<a class="back" href="#/students">${icon("arrow-left")} My students</a><div id="sp">${loadingHtml("Loading the student…")}</div>`;
  let detail;
  const holder = $("#sp", el);
  try { detail = await api(`/api/teach/students/${encodeURIComponent(id)}`); }
  catch (ex) {
    $("#sp", el).innerHTML = `<div class="card">${emptyState("alert-triangle",
      ex.status === 404 ? "This student isn't one of yours." : "Couldn't load this student.", ex.message)}</div>`;
    return;
  }
  if (!holder.isConnected) return;
  const p = detail.profile;
  document.title = `${p.name || p.email} · Teach · PrepWithTee`;
  const names = Object.fromEntries((detail.enrollments || []).map(e => [e.syllabus, e.name]));
  const subjects = detail.taught.length ? detail.taught : (detail.enrollments || []).map(e => e.syllabus);
  const state = { tab: TABS.some(t => t[0] === params.tab) ? params.tab : "folder",
                  syl: subjects.includes(params.syl) ? params.syl : subjects[0] };
  const wa = waLink(p.phone);
  const sp = $("#sp", el);
  sp.innerHTML = `
    <div class="card">
      <div class="profile-head">
        ${avatar(p, "lg")}
        <div class="who">
          <h1>${esc(p.name || "No name yet")}</h1>
          <div class="meta">${esc(p.email || "")}${p.grade ? ` · ${esc(p.grade)}` : ""}</div>
          <div class="pills">${(detail.enrollments || []).map(e => pill(`${e.name || e.syllabus}`,
            detail.taught.includes(e.syllabus) ? "acc" : "")).join("")}
            ${(detail.parents || []).map(x => pill(`parent: ${x.name || x.email}`, "info")).join("")}</div>
        </div>
        <div class="profile-actions">
          <button class="btn primary" data-act="msg">${icon("message-circle")} Message</button>
          ${wa ? `<a class="btn wa" href="${wa}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}
          ${p.email ? `<a class="btn" href="mailto:${esc(p.email)}">${icon("mail")} Email</a>` : ""}
        </div>
      </div>
      ${subjects.length > 1 ? `<div class="chips subj-switch" role="group" aria-label="Subject">${subjects.map(s =>
        `<button class="chip${s === state.syl ? " on" : ""}" data-syl="${esc(s)}">${esc(names[s] || s)} <span class="faint">${esc(s)}</span></button>`).join("")}</div>` : ""}
    </div>
    <div data-tabs></div>
    <div data-body></div>`;

  const drawTabs = () => {
    $("[data-tabs]", sp).innerHTML = tabBar(TABS, state.tab);
    $$("[data-tabs] .tab", sp).forEach(b => b.addEventListener("click", () => { state.tab = b.dataset.tab; sync(); }));
  };
  const sync = () => {
    setParams({ tab: state.tab === "folder" ? "" : state.tab, syl: state.syl });
    drawTabs();
    drawBody();
  };
  const drawBody = () => {
    const body = $("[data-body]", sp);
    if (!state.syl) { body.innerHTML = `<div class="card">${emptyState("school", "No subjects yet.")}</div>`; return; }
    if (state.tab === "folder") {
      body.innerHTML = `<div class="card" data-folder></div>`;
      renderFolder($("[data-folder]", body), { id: p.id, name: p.name || p.email, email: p.email }, state.syl);
    } else if (state.tab === "overview") overview(body, p.id);
    else if (state.tab === "progress") {
      body.innerHTML = `<div class="card" data-manage-card></div>`;
      mountManage($("[data-manage-card]", body), detail, () => render(el, { rest, params: { tab: "progress", syl: state.syl }, setParams }));
    } else notes(body, p.id, state.syl);
  };
  $$("[data-syl]", sp).forEach(b => b.addEventListener("click", () => {
    state.syl = b.dataset.syl;
    $$("[data-syl]", sp).forEach(x => x.classList.toggle("on", x === b));
    sync();
  }));
  $("[data-act=msg]", sp).addEventListener("click", () => message(p));
  drawTabs();
  drawBody();
}

async function overview(body, sid) {
  body.innerHTML = loadingHtml();
  let a;
  const mark = body.firstChild;
  try { a = await api(`/api/teach/students/${encodeURIComponent(sid)}/activity?limit=300`); }
  catch (ex) { body.innerHTML = `<div class="card">${emptyState("alert-triangle", ex.message)}</div>`; return; }
  if (body.firstChild !== mark || !body.isConnected) return;     // another tab was opened meanwhile
  const s = a.summary;
  body.innerHTML = `
    <div class="stat-tiles">
      ${tile("flame", "t-amber", "Streak", s.streak ? `${s.streak} days` : "0", s.streak_best ? `best ${s.streak_best}` : "")}
      ${tile("clock", "t-sky", "Time this week", minutes(s.minutes_7), `${s.active_days_7} active day${s.active_days_7 === 1 ? "" : "s"}`)}
      ${tile("book", "t-violet", "Booklets and tests", num(s.booklets))}
      ${tile("checkbox", "t-teal", "MCQ sessions", num(s.mcq_sessions), s.mcq_avg === null ? "" : `average ${pct(s.mcq_avg)}`)}
      ${tile("calendar-event", "t-amber", "Yearly papers", num(s.papers))}
      ${tile("notebook", "t-rose", "Open homework", num(s.open_homework))}
    </div>
    <div class="two">
      <div class="card"><h2>What they've been doing</h2>
        ${a.events.length ? a.events.slice(0, 200).map(e => `<div class="event"><span class="ic ${e.type}">${icon(EVENT_ICONS[e.type] || "point")}</span>
          <div class="txt">${esc(e.text)}</div><span class="when" title="${esc(e.at)}">${esc(rel(e.at))}</span></div>`).join("")
          : emptyState("mood-empty", "Nothing yet.")}</div>
      <div class="card"><h2>Time on the site, last 4 weeks</h2>${timeChart(s.time_by_day)}
        <p class="small faint">Last active ${esc(rel(s.last_active))}</p></div>
    </div>`;
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

async function notes(body, sid, syl) {
  body.innerHTML = `<div class="card"><h2>My notes</h2>
    <p class="small muted">Private - the student never sees these. Handy for "what to cover next" and how a class went.</p>
    <form class="note-box"><label class="sr-only" for="tn-body">New note</label>
      <textarea class="textarea" id="tn-body" placeholder="Struggled with negative indices - start Thursday with 5 quick ones"></textarea>
      <button class="btn primary">Add note</button></form><div data-notes>${loadingHtml()}</div></div>`;
  const list = $("[data-notes]", body);
  const draw = async () => {
    const d = await api(`/api/teach/students/${encodeURIComponent(sid)}/notes`);
    list.innerHTML = d.notes.length ? d.notes.map(n => `<div class="event"><span class="ic note">${icon("note")}</span>
        <div class="txt">${esc(n.body)}${n.syllabus && n.syllabus !== "-" ? ` <span class="small faint">${esc(n.syllabus)}</span>` : ""}</div>
        <span class="when">${esc(rel(n.at))}</span>
        <button class="btn sm icon ghost" data-del="${esc(n.id)}" aria-label="Delete note">${icon("trash")}</button></div>`).join("")
      : emptyState("note", "No notes yet.");
  };
  $(".note-box", body).addEventListener("submit", async e => {
    e.preventDefault();
    const v = $("#tn-body", body).value.trim();
    if (!v) { toast("Write the note first", true); return; }
    try {
      await api(`/api/teach/students/${encodeURIComponent(sid)}/notes`, { method: "POST", body: { body: v, syllabus: syl } });
      $("#tn-body", body).value = "";
      draw();
    } catch (ex) { toast(ex.message, true); }
  });
  list.addEventListener("click", async e => {
    const b = e.target.closest("[data-del]");
    if (!b || !(await confirmBox("Delete note", "Delete this note?", "Delete", true))) return;
    await api(`/api/teach/students/${encodeURIComponent(sid)}/notes/${b.dataset.del}`, { method: "DELETE" });
    draw();
  });
  draw();
}

export async function message(p) {
  return modal({
    title: `Message ${p.name || p.email}`, submit: "Send",
    body: `<label class="field"><span>Message</span><textarea class="textarea" name="m" autofocus
      placeholder="Well done on the test! Next time, show the formula before the numbers."></textarea></label>
      <p class="small faint">They see it in Messages on PrepWithTee. <a href="#/messages?to=${esc(p.id)}">Open the conversation</a></p>`,
    run: async m => {
      const v = $("[name=m]", m).value.trim();
      if (!v) return "Write a message first.";
      await api("/api/messages", { method: "POST", body: { recipient_id: p.id, body: v } });
      toast("Sent");
      return true;
    },
  });
}

export { fmtDate };
