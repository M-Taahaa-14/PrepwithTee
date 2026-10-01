import { $, $$, api, esc, icon, pill, rel, fmtDate, avatar, waLink, modal, toast, drawer, confirmBox,
         tabBar, loadingHtml, emptyState, lookup } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Teachers";

export async function render(el, { params, setParams, ctx }) {
  const tab = ["teachers", "applications", "allocations"].includes(params.tab) ? params.tab : "teachers";
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Teachers</h1>
      <p>Public teacher cards, applications and who teaches whom.</p></div>
      ${tab === "teachers" ? `<button class="btn primary" data-new>${icon("plus")} Add teacher</button>` : ""}</div>
    <div id="t-tabs"></div><div id="t-body">${loadingHtml()}</div>`;
  const go = t => { setParams({ tab: t }); render(el, { params: { tab: t }, setParams, ctx }); };
  let apps = [];
  try { apps = (await api("/api/admin/teacher-applications")).applications; } catch { /* shown below */ }
  const pendingApps = apps.filter(a => (a.status || "pending") === "pending").length;
  $("#t-tabs", el).innerHTML = tabBar([["teachers", "Teachers"], ["applications", "Applications", pendingApps],
                                       ["allocations", "Who teaches whom"]], tab);
  $$("#t-tabs .tab", el).forEach(b => b.addEventListener("click", () => go(b.dataset.tab)));
  const body = $("#t-body", el);
  const again = () => { ctx.refreshBadges?.(); render(el, { params: { ...params, tab }, setParams, ctx }); };
  if (tab === "teachers") {
    $("[data-new]", el).addEventListener("click", async () => { if (await teacherForm(null)) again(); });
    return renderTeachers(body, again);
  }
  if (tab === "applications") return renderApps(body, apps, again);
  return renderAllocations(body, params, setParams);
}

/* ── teacher cards ────────────────────────────────────────────────────── */

async function renderTeachers(body, again) {
  const { teachers } = await api("/api/admin/teachers");
  if (!teachers.length) { body.innerHTML = `<div class="card">${emptyState("users", "No teachers yet.", "Approve an application or add one.")}</div>`; return; }
  teachers.sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0));
  body.innerHTML = `<div class="dt-wrap"><table class="dt"><thead><tr>
      <th><span class="static">Teacher</span></th><th><span class="static">Subjects</span></th>
      <th class="num"><span class="static">Order</span></th><th><span class="static">On the site</span></th><th></th></tr></thead>
      <tbody>${teachers.map(t => `<tr>
        <td><div class="who">${avatar(t)}<div><b>${esc(t.name)}</b><span class="small">${esc(t.role || "")}${t.email ? ` · ${esc(t.email)}` : ""}</span></div></div></td>
        <td>${esc((t.subject_names || []).join(", ")) || "—"}</td>
        <td class="num">${esc(t.display_order ?? 0)}</td>
        <td>${t.active ? pill("shown", "ok") : pill("hidden")}</td>
        <td class="nowrap"><button class="btn sm" data-students="${t.id}">${icon("school")} Students</button>
          <button class="btn sm" data-edit="${t.id}">${icon("pencil")} Edit</button>
          <button class="btn sm icon ghost danger" data-del="${t.id}" aria-label="Delete ${esc(t.name)}">${icon("trash")}</button></td>
      </tr>`).join("")}</tbody></table></div>`;
  const byId = Object.fromEntries(teachers.map(t => [String(t.id), t]));
  $$("[data-edit]", body).forEach(b => b.addEventListener("click", async () => { if (await teacherForm(byId[b.dataset.edit])) again(); }));
  $$("[data-del]", body).forEach(b => b.addEventListener("click", async () => {
    const t = byId[b.dataset.del];
    if (!(await confirmBox("Delete teacher", `Remove ${t.name}'s card from the site? Their login and student links stay.`, "Delete", true))) return;
    await api(`/api/admin/teachers/${t.id}`, { method: "DELETE" });
    toast("Teacher removed"); again();
  }));
  $$("[data-students]", body).forEach(b => b.addEventListener("click", () => teacherStudents(byId[b.dataset.students])));
}

async function teacherForm(t) {
  const subjects = await lookup("subjects");
  const has = new Set(t?.subjects || []);
  return modal({
    title: t ? `Edit ${t.name}` : "Add a teacher", submit: t ? "Save" : "Add teacher", size: "lg",
    body: `
      <div class="row"><label class="field grow"><span>Name</span><input class="input" name="name" required value="${esc(t?.name || "")}" autofocus></label>
        <label class="field grow"><span>Role</span><input class="input" name="role" value="${esc(t?.role || "Teacher")}"></label></div>
      <div class="row"><label class="field grow"><span>Email (their login)</span><input class="input" name="email" type="email" value="${esc(t?.email || "")}"></label>
        <label class="field grow"><span>Phone</span><input class="input" name="phone" value="${esc(t?.phone || "")}"></label></div>
      <div class="field"><span>Subjects</span><div class="chips">${subjects.map(s => `<label class="chip${has.has(s.code) ? " on" : ""}">
        <input type="checkbox" name="subj" value="${esc(s.code)}" ${has.has(s.code) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}</div></div>
      <label class="field"><span>Bio (shown on the Teachers page)</span><textarea class="textarea" name="bio">${esc(t?.bio || "")}</textarea></label>
      <div class="row"><label class="field grow"><span>Qualifications</span><input class="input" name="qualifications" value="${esc(t?.qualifications || "")}"></label>
        <label class="field"><span>Years teaching</span><input class="input" name="experience_years" type="number" min="0" max="60" value="${esc(t?.experience_years ?? "")}"></label></div>
      <div class="row"><label class="field grow"><span>Photo URL</span><input class="input" name="picture_url" value="${esc(t?.picture_url || "")}"></label>
        <label class="field"><span>Order on the page</span><input class="input" name="display_order" type="number" value="${esc(t?.display_order ?? 0)}"></label></div>
      <label class="check"><input type="checkbox" name="active" ${!t || t.active ? "checked" : ""}> Show on the public Teachers page</label>`,
    onMount: m => m.addEventListener("change", () => $$("label.chip", m).forEach(c => c.classList.toggle("on", $("input", c).checked))),
    run: async m => {
      const v = n => $(`[name=${n}]`, m).value.trim();
      if (!v("name")) return "A name is required.";
      const body = { name: v("name"), role: v("role") || null, email: v("email") || null, phone: v("phone") || null,
        subjects: $$("[name=subj]:checked", m).map(i => i.value), bio: v("bio") || null,
        qualifications: v("qualifications") || null, picture_url: v("picture_url") || null,
        experience_years: v("experience_years") === "" ? null : +v("experience_years"),
        display_order: +v("display_order") || 0, active: $("[name=active]", m).checked };
      await api(t ? `/api/admin/teachers/${t.id}` : "/api/admin/teachers", { method: t ? "PATCH" : "POST", body });
      toast(t ? "Saved" : "Teacher added");
      return true;
    },
  });
}

async function teacherStudents(t) {
  const d = drawer({ title: `${t.name}'s students`, body: loadingHtml() });
  const draw = async () => {
    let list;
    try { list = (await api(`/api/admin/teachers/${t.id}/students`)).assignments; }
    catch (ex) { $(".drawer-body", d.el).innerHTML = emptyState("alert-triangle", ex.message); return; }
    const subjects = await lookup("subjects");
    $(".drawer-body", d.el).innerHTML = `
      ${list.length ? list.map(s => `<div class="list-row">${avatar(s)}<div class="grow"><a href="#/student/${esc(s.student_id)}">${esc(s.name || s.email)}</a>
          <div class="small faint">${esc(s.syllabus)} · since ${esc(fmtDate(s.allocated_at))}</div></div>
          <button class="btn sm danger" data-un="${esc(s.student_id)}" data-syl="${esc(s.syllabus)}">Remove</button></div>`).join("")
        : emptyState("school", "No students yet.")}
      <h3>Add a student</h3>
      <div class="row"><input class="input grow" data-find placeholder="Search a student by name or email">
        <select class="select" data-syl-new>${subjects.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join("")}</select></div>
      <div data-results></div>`;
    $$("[data-un]", d.el).forEach(b => b.addEventListener("click", async () => {
      await api(`/api/admin/teachers/${t.id}/students/${b.dataset.un}?syllabus=${encodeURIComponent(b.dataset.syl)}`, { method: "DELETE" });
      toast("Removed"); draw();
    }));
    let timer;
    $("[data-find]", d.el).addEventListener("input", e => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = e.target.value.trim();
        const box = $("[data-results]", d.el);
        if (q.length < 2) { box.innerHTML = ""; return; }
        const { rows } = await api(`/api/admin/students/table?q=${encodeURIComponent(q)}&per=8&sort=name&dir=asc`);
        box.innerHTML = rows.map(r => `<div class="list-row">${avatar(r)}<span class="grow">${esc(r.name || r.email)} <span class="small faint">${esc(r.email)}</span></span>
          <button class="btn sm" data-add="${esc(r.id)}">${icon("plus")} Add</button></div>`).join("") || `<p class="small muted">No match.</p>`;
        $$("[data-add]", box).forEach(b => b.addEventListener("click", async () => {
          await api(`/api/admin/teachers/${t.id}/students`, { method: "POST",
            body: { student_id: b.dataset.add, syllabus: $("[data-syl-new]", d.el).value } });
          toast("Added"); draw();
        }));
      }, 250);
    });
  };
  draw();
}

/* ── applications ─────────────────────────────────────────────────────── */

function renderApps(body, apps, again) {
  if (!apps.length) { body.innerHTML = `<div class="card">${emptyState("user-plus", "No applications yet.")}</div>`; return; }
  const tone = { pending: "warn", approved: "ok", rejected: "bad" };
  apps.sort((a, b) => ((a.status || "pending") === "pending" ? -1 : 0) - ((b.status || "pending") === "pending" ? -1 : 0)
    || (b.created_at || "").localeCompare(a.created_at || ""));
  body.innerHTML = `<div class="dt-wrap"><table class="dt"><thead><tr><th><span class="static">Applicant</span></th>
    <th><span class="static">Subjects</span></th><th><span class="static">Experience</span></th><th><span class="static">Status</span></th>
    <th><span class="static">Applied</span></th></tr></thead><tbody>${apps.map(a => `<tr class="click" data-app="${a.id}">
      <td><b>${esc(a.name)}</b><div class="small faint">${esc(a.email || "")} ${a.phone ? `· ${esc(a.phone)}` : ""}</div></td>
      <td>${esc(a.subjects || a.subject_codes || "")}</td><td>${esc(a.experience || "—")}</td>
      <td>${pill(a.status || "pending", tone[a.status || "pending"])}</td><td>${esc(rel(a.created_at))}</td></tr>`).join("")}</tbody></table></div>`;
  const byId = Object.fromEntries(apps.map(a => [String(a.id), a]));
  $$("[data-app]", body).forEach(tr => tr.addEventListener("click", () => openApp(byId[tr.dataset.app], again)));
}

async function openApp(a, again) {
  const pending = (a.status || "pending") === "pending";
  const subjects = await lookup("subjects");
  const codes = new Set((a.subject_codes || "").split(",").map(s => s.trim()).filter(Boolean));
  const wa = waLink(a.phone);
  drawer({
    title: `Application: ${a.name}`,
    body: `
      <dl class="kv"><dt>Email</dt><dd>${esc(a.email || "—")}</dd><dt>Phone</dt><dd>${esc(a.phone || "—")}</dd>
        <dt>Subjects</dt><dd>${esc(a.subjects || a.subject_codes || "—")}</dd><dt>Qualifications</dt><dd>${esc(a.qualifications || "—")}</dd>
        <dt>Experience</dt><dd>${esc(a.experience || "—")}</dd><dt>Applied</dt><dd>${esc(fmtDate(a.created_at))}</dd>
        ${a.admin_note ? `<dt>Your note</dt><dd>${esc(a.admin_note)}</dd>` : ""}</dl>
      ${a.message ? `<div class="msg">${esc(a.message)}</div>` : ""}
      <div class="row">${wa ? `<a class="btn wa" href="${wa}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}
        ${a.email ? `<a class="btn" href="mailto:${esc(a.email)}">${icon("mail")} Email</a>` : ""}</div>
      ${pending ? `
      <h3>Approve</h3>
      <p class="small muted">Creates their public card and a login (they get an email with a temporary password).</p>
      <div class="field"><span>Subjects they'll teach</span><div class="chips">${subjects.map(s => `<label class="chip${codes.has(s.code) ? " on" : ""}">
        <input type="checkbox" name="subj" value="${esc(s.code)}" ${codes.has(s.code) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}</div></div>
      <label class="field"><span>Role on the card</span><input class="input" name="role" value="Teacher"></label>
      <label class="field"><span>Bio</span><textarea class="textarea" name="bio"></textarea></label>
      <div class="row"><button class="btn primary" data-approve>${icon("check")} Approve</button>
        <span class="grow"></span><button class="btn danger" data-reject>${icon("x")} Reject</button></div>` : ""}`,
    onMount: (d, close) => {
      d.addEventListener("change", () => $$("label.chip", d).forEach(c => c.classList.toggle("on", $("input", c).checked)));
      $("[data-approve]", d)?.addEventListener("click", async () => {
        try {
          const r = await api(`/api/admin/teacher-applications/${a.id}/approve`, { method: "POST", body: {
            subjects: $$("[name=subj]:checked", d).map(i => i.value), role: $("[name=role]", d).value || null,
            bio: $("[name=bio]", d).value || null } });
          close();
          await modal({ title: `${a.name} is approved`, submit: "Done", cancel: "",
            body: r.temp_password ? `<p>Their login was created${r.email_sent ? " and emailed to them" : ", but the email didn't send"}.</p>
              <p>Temporary password: <code>${esc(r.temp_password)}</code></p><p class="small muted">They'll be asked to change it on first sign-in.</p>`
              : `<p>They already had an account, which is now a teacher account.</p>` });
          again();
        } catch (ex) { toast(ex.message, true); }
      });
      $("[data-reject]", d)?.addEventListener("click", async () => {
        const ok = await modal({ title: `Reject ${a.name}`, submit: "Reject", danger: true,
          body: `<label class="field"><span>Private note (not sent)</span><input class="input" name="note" autofocus></label>`,
          run: async m => { await api(`/api/admin/teacher-applications/${a.id}/reject`, { method: "POST", body: { admin_note: $("[name=note]", m).value || null } }); return true; } });
        if (ok) { close(); toast("Rejected"); again(); }
      });
    },
  });
}

/* ── allocations ──────────────────────────────────────────────────────── */

function renderAllocations(body, params, setParams) {
  body.innerHTML = `<div id="alloc"></div>`;
  const { q = "", sort, dir, page, per, tab, ...filters } = params;
  const table = new DataTable($("#alloc", body), {
    id: "allocations", noun: "links", searchPlaceholder: "Search teacher or student",
    state: { q, sort: sort || "allocated_at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/allocations")).allocations,
    searchText: r => `${r.teacher_name} ${r.student_name} ${r.student_email} ${r.syllabus}`,
    onState: s => setParams({ ...s, tab: "allocations" }),
    filters: [{ key: "teacher", label: "Every teacher", value: r => r.teacher_name || "" },
              { key: "syllabus", label: "Every subject", value: r => r.syllabus }],
    columns: [
      { key: "teacher_name", label: "Teacher", sort: true, firstDir: "asc" },
      { key: "student_name", label: "Student", sort: true, firstDir: "asc",
        render: r => `<a href="#/student/${esc(r.student_id)}">${esc(r.student_name || r.student_id)}</a> <span class="small faint">${esc(r.student_email || "")}</span>` },
      { key: "syllabus", label: "Subject", sort: true },
      { key: "allocated_at", label: "Since", sort: true, render: r => esc(fmtDate(r.allocated_at)) },
    ],
    bulk: [{ label: "Remove", icon: "trash", run: async rows => {
      if (!(await confirmBox("Remove links", `Remove ${rows.length} teacher-student link${rows.length === 1 ? "" : "s"}?`, "Remove", true))) return false;
      for (const r of rows) await api(`/api/admin/allocations/${r.id}`, { method: "DELETE" });
      toast("Removed"); return true;
    } }],
  });
  return table;
}
