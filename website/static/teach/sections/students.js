import { $, api, esc, avatar, rel, pill, emptyState, loadingHtml } from "/admin/core.js";
import { DataTable } from "/admin/datatable.js";
import { card } from "./today.js";

export const title = "My students";

export async function render(el, { params, setParams, ctx }) {
  const view = params.view === "table" ? "table" : "cards";
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>My students</h1>
      <p>Everyone the PrepWithTee admin has assigned to you. Open a student to teach them.</p></div>
      <div class="tabs" role="tablist">
        <button class="tab${view === "cards" ? " on" : ""}" data-v="cards">Cards</button>
        <button class="tab${view === "table" ? " on" : ""}" data-v="table">Table</button></div></div>
    <div id="sl">${loadingHtml()}</div>`;
  el.querySelectorAll("[data-v]").forEach(b => b.addEventListener("click", () => {
    setParams({ view: b.dataset.v === "cards" ? "" : b.dataset.v });
    render(el, { params: { view: b.dataset.v }, setParams, ctx });
  }));
  const box = $("#sl", el);
  if (view === "cards") {
    let rows;
    try { rows = (await api("/api/teach/students")).students; }
    catch (ex) { box.innerHTML = `<div class="card">${emptyState("alert-triangle", ex.message)}</div>`; return; }
    ctx.students = rows;
    if (!box.isConnected) return;
    box.innerHTML = rows.length ? `<div class="stu-grid wide">${rows.map(card).join("")}</div>`
      : `<div class="card">${emptyState("school", "No students yet.", "When the admin assigns students to you, they appear here.")}</div>`;
    return;
  }
  box.innerHTML = "";
  new DataTable(box, {
    id: "teach-students", noun: "students", searchPlaceholder: "Search by name or email",
    loadAll: async () => (await api("/api/teach/students")).students,
    searchText: r => `${r.name} ${r.email} ${r.subjects.join(" ")}`,
    rowId: r => r.id,
    onOpen: r => { location.hash = `#/student/${r.id}`; },
    filters: [{ key: "subject", label: "Every subject", value: r => r.subjects }],
    defaultSort: "name", defaultDir: "asc",
    columns: [
      { key: "name", label: "Student", sort: true, firstDir: "asc",
        render: r => `<a class="row" href="#/student/${esc(r.id)}">${avatar(r)}<span><b>${esc(r.name || r.email)}</b>
          <span class="small faint"> ${esc(r.email || "")}</span></span></a>` },
      { key: "subjects", label: "Subjects", render: r => r.subjects.map(s => `<span class="chip sm">${esc(s)}</span>`).join(" ") },
      { key: "last_active", label: "Last active", sort: true, render: r => esc(rel(r.last_active)) },
      { key: "to_mark", label: "To mark", sort: true, render: r => r.to_mark ? pill(r.to_mark, "acc") : "" },
      { key: "open_homework", label: "Open homework", sort: true,
        render: r => `${r.open_homework || ""}${r.overdue ? ` ${pill(`${r.overdue} overdue`, "bad")}` : ""}` },
      { key: "items", label: "In folder", sort: true },
    ],
  });
}
