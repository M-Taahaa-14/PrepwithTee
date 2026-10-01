import { $, $$, api, esc, icon, pill, fmtDate, toast, drawer, avatar, loadingHtml, emptyState } from "../core.js";

export const title = "Groups";

const TONE = { draft: "warn", active: "ok", closed: "" };

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Groups</h1>
      <p>Small-group classes. Teachers create them; you publish or close them.</p></div></div>
    <div id="g-body">${loadingHtml()}</div>`;
  const draw = async () => {
    const [{ groups }, teachers] = await Promise.all([api("/api/admin/groups"),
      api("/api/admin/teacher-profiles").then(d => d.teachers).catch(() => [])]);
    const tname = Object.fromEntries(teachers.map(t => [t.id, t.name || t.email]));
    $("#g-body", el).innerHTML = groups.length ? `<div class="dt-wrap"><table class="dt"><thead><tr>
      <th><span class="static">Group</span></th><th><span class="static">Teacher</span></th><th><span class="static">Subject</span></th>
      <th class="num"><span class="static">Members</span></th><th><span class="static">Status</span></th><th></th></tr></thead><tbody>
      ${groups.map(g => `<tr class="click" data-open="${g.id}">
        <td><b>${esc(g.name)}</b><div class="small faint">${esc((g.description || "").slice(0, 80))}</div></td>
        <td>${esc(tname[g.teacher_id] || "—")}</td><td>${esc(g.syllabus || "—")}</td>
        <td class="num">${g.member_count ?? 0} / ${g.max_students}</td><td>${pill(g.status, TONE[g.status])}</td>
        <td class="nowrap">${["active", "draft", "closed"].filter(s => s !== g.status).map(s =>
          `<button class="btn sm" data-set="${g.id}" data-status="${s}">${s === "active" ? "Publish" : s === "closed" ? "Close" : "Back to draft"}</button>`).join(" ")}</td>
      </tr>`).join("")}</tbody></table></div>` : `<div class="card">${emptyState("users-group", "No groups yet.", "Teachers create groups from their dashboard.")}</div>`;
    $$("[data-set]", el).forEach(b => b.addEventListener("click", async e => {
      e.stopPropagation();
      await api(`/api/admin/groups/${b.dataset.set}/status`, { method: "PATCH", body: { status: b.dataset.status } });
      toast("Updated"); draw();
    }));
    $$("[data-open]", el).forEach(tr => tr.addEventListener("click", e => { if (!e.target.closest("button")) openGroup(tr.dataset.open, tname); }));
  };
  draw();
}

async function openGroup(id, tname) {
  const d = drawer({ title: "Group", body: loadingHtml() });
  const { group: g, members, sessions } = await api(`/api/admin/groups/${id}`);
  $("#d-title", d.el).textContent = g.name;
  $(".drawer-body", d.el).innerHTML = `
    <dl class="kv"><dt>Teacher</dt><dd>${esc(tname[g.teacher_id] || "—")}</dd><dt>Subject</dt><dd>${esc(g.syllabus || "—")}</dd>
      <dt>Status</dt><dd>${pill(g.status, TONE[g.status])}</dd><dt>Created</dt><dd>${esc(fmtDate(g.created_at))}</dd></dl>
    ${g.description ? `<div class="msg">${esc(g.description)}</div>` : ""}
    <h3>Members (${members.length}/${g.max_students})</h3>
    ${members.length ? members.map(m => {
      const p = m.profiles || m;              // Supabase nests the join under "profiles"
      return `<div class="list-row">${avatar(p)}<a class="grow" href="#/student/${esc(m.student_id)}">${esc(p.name || p.email || "Student")}</a>
        <span class="small faint">${esc(m.status || "")} · joined ${esc(fmtDate(m.joined_at))}</span></div>`;
    }).join("") : emptyState("users", "No members yet.")}
    <h3>Sessions (${sessions.length})</h3>
    ${sessions.length ? sessions.map(s => `<div class="list-row">${icon("calendar")}<span class="grow">${esc(s.topic || "Session")}${s.duration_min ? ` · ${s.duration_min} min` : ""}</span>
      <span class="small faint">${esc(s.status || "")} · ${esc(fmtDate(s.session_date))}</span></div>`).join("") : emptyState("calendar", "No sessions yet.")}`;
}
