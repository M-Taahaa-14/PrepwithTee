import { $, api, esc, rel, fmtDate, pill } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Audit log";

export async function render(el, { params, setParams }) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Audit log</h1>
    <p>Every change made through the admin console: who, what and when.</p></div></div><div id="au"></div>`;
  const { q = "", sort, dir, page, per, ...filters } = params;
  new DataTable($("#au", el), {
    id: "audit", noun: "entries", searchPlaceholder: "Search action, target or admin",
    state: { q, sort: sort || "created_at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/audit?limit=500")).rows,
    searchText: r => `${r.action} ${r.target || ""} ${r.admin_email || ""} ${JSON.stringify(r.details || {})}`,
    onState: setParams,
    filters: [
      { key: "ok", label: "Any result", value: r => (r.ok ? "ok" : "failed"),
        options: c => [{ value: "ok", label: "Succeeded", count: c.ok || 0 }, { value: "failed", label: "Failed", count: c.failed || 0 }] },
      { key: "admin", label: "Any admin", value: r => r.admin_email || "admin key" },
    ],
    columns: [
      { key: "created_at", label: "When", sort: true, render: r => `<span title="${esc(fmtDate(r.created_at))}">${esc(rel(r.created_at))}</span>` },
      { key: "admin_email", label: "Admin", sort: true, firstDir: "asc", render: r => esc(r.admin_email || "admin key") },
      { key: "action", label: "Action", sort: true, firstDir: "asc", render: r => `<code>${esc(r.action)}</code>` },
      { key: "target", label: "Target", render: r => r.target?.includes("user_id=")
          ? `<a href="#/student/${esc(r.target.split("user_id=")[1].split(",")[0])}">${esc(r.target)}</a>` : esc(r.target || "—") },
      { key: "ok", label: "Result", sort: true, render: r => r.ok ? pill("ok", "ok")
          : pill(`failed${r.details?.status ? ` (${r.details.status})` : ""}`, "bad") },
    ],
  });
}
