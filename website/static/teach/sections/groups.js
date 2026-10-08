// Small-group classes the teacher runs (teacher.py /api/teacher/groups*).
import { $, $$, api, esc, icon, pill, fmtDate, toast, drawer, modal, avatar, loadingHtml, emptyState } from "/admin/core.js";

export const title = "Groups";
const TONE = { draft: "warn", active: "ok", closed: "" };

export async function render(el, { ctx }) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Groups</h1>
      <p>Small-group classes. Create one; the admin publishes it.</p></div>
      <button class="btn primary" data-new>${icon("plus")} New group</button></div><div id="g-body">${loadingHtml()}</div>`;
  const box = $("#g-body", el);
  const draw = async () => {
    const { groups } = await api("/api/teacher/groups");
    if (!box.isConnected) return;                 // navigated away meanwhile
    box.innerHTML = groups.length ? `<div class="stu-grid wide">${groups.map(g => `
      <button class="stu-card" data-open="${g.id}">${icon("users-group")}<span class="stu-name">${esc(g.name)}</span>
        <span class="small faint">${esc(g.syllabus || "Any subject")} · ${g.member_count ?? 0} / ${g.max_students}</span>
        ${pill(g.status || "draft", TONE[g.status || "draft"])}</button>`).join("")}</div>`
      : `<div class="card">${emptyState("users-group", "No groups yet.", "Create one to teach several students together.")}</div>`;
    $$("[data-open]", el).forEach(b => b.addEventListener("click", () => openGroup(b.dataset.open, ctx, draw)));
  };
  $("[data-new]", el).addEventListener("click", async () => {
    const ok = await modal({ title: "New group", submit: "Create",
      body: `<label class="field"><span>Name</span><input class="input" name="n" required autofocus placeholder="O Level Maths - Saturday batch"></label>
        <div class="row"><label class="field"><span>Subject</span><input class="input" name="s" placeholder="4024"></label>
          <label class="field narrow"><span>Seats</span><input class="input" type="number" name="m" min="1" max="40" value="6"></label></div>
        <label class="field"><span>About it</span><textarea class="textarea" name="d"></textarea></label>`,
      run: async m => {
        const name = $("[name=n]", m).value.trim();
        if (!name) return "Give the group a name.";
        await api("/api/teacher/groups", { method: "POST", body: { name, syllabus: $("[name=s]", m).value.trim() || null,
          max_students: +$("[name=m]", m).value || 6, description: $("[name=d]", m).value.trim() || null } });
        return true;
      } });
    if (ok) { toast("Group created"); draw(); }
  });
  draw();
}

async function openGroup(id, ctx, redraw) {
  const d = drawer({ title: "Group", body: loadingHtml() });
  const paint = async () => {
    const { group: g, members, sessions } = await api(`/api/teacher/groups/${id}`);
    $("#d-title", d.el).textContent = g.name;
    const inGroup = new Set(members.map(m => m.student_id));
    const others = (ctx.students || []).filter(s => !inGroup.has(s.id));
    $(".drawer-body", d.el).innerHTML = `
      <dl class="kv"><dt>Subject</dt><dd>${esc(g.syllabus || "—")}</dd><dt>Status</dt><dd>${pill(g.status || "draft", TONE[g.status || "draft"])}</dd>
        <dt>Created</dt><dd>${esc(fmtDate(g.created_at))}</dd></dl>
      ${g.description ? `<div class="msg">${esc(g.description)}</div>` : ""}
      <h3>Members (${members.length}/${g.max_students})</h3>
      ${members.map(m => { const p = m.profiles || m; return `<div class="list-row">${avatar(p)}
        <a class="grow" href="#/student/${esc(m.student_id)}">${esc(p.name || p.email || "Student")}</a>
        <button class="btn sm ghost" data-rm="${esc(m.student_id)}">Remove</button></div>`; }).join("") || emptyState("users", "No members yet.")}
      ${others.length ? `<div class="row"><select class="select" data-add-sel aria-label="Student">${others.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</select>
        <button class="btn" data-add>${icon("user-plus")} Add</button></div>` : ""}
      <h3>Sessions (${sessions.length})</h3>
      <form class="row" data-sess><input class="input" type="date" name="d" required aria-label="Date" value="${new Date().toISOString().slice(0, 10)}">
        <input class="input" name="t" placeholder="Topic" aria-label="Topic"><input class="input narrow" type="number" name="m" value="60" min="10" max="300" aria-label="Minutes">
        <button class="btn">Log session</button></form>
      ${sessions.map(s => `<div class="list-row">${icon("calendar")}<span class="grow">${esc(s.topic || "Session")}${s.duration_min ? ` · ${s.duration_min} min` : ""}</span>
        <span class="small faint">${esc(fmtDate(s.session_date))}</span></div>`).join("")}`;
    $("[data-add]", d.el)?.addEventListener("click", async () => {
      await api(`/api/teacher/groups/${id}/members`, { method: "POST", body: { student_ids: [$("[data-add-sel]", d.el).value] } });
      paint(); redraw();
    });
    $$("[data-rm]", d.el).forEach(b => b.addEventListener("click", async () => {
      await api(`/api/teacher/groups/${id}/members/${b.dataset.rm}`, { method: "DELETE" }); paint(); redraw();
    }));
    $("[data-sess]", d.el).addEventListener("submit", async e => {
      e.preventDefault();
      const f = e.target;
      await api(`/api/teacher/groups/${id}/sessions`, { method: "POST", body: { session_date: f.d.value,
        topic: f.t.value.trim() || null, duration_min: +f.m.value || 60 } });
      toast("Session logged"); paint();
    });
  };
  paint();
}
