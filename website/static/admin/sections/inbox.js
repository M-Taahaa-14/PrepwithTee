import { $, $$, api, esc, icon, pill, rel, fmtDate, waLink, modal, toast, drawer } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Inbox";

const SOURCES = { lead: ["Demo request", "acc"], contact: ["Contact", "pro"], feedback: ["Feedback", "ok"],
                  request: ["Subject request", "warn"] };
const STATUS = { new: ["New", "bad"], replied: ["Replied", "info"], handled: ["Handled", "ok"],
                 archived: ["Archived", ""] };

export async function render(el, { params, setParams, ctx }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Inbox</h1>
      <p>Demo requests, contact messages, feedback and subject requests in one place.</p></div>
      <a class="btn" href="#/calendly">${icon("calendar")} Calendly bookings</a></div>
    <div id="ib"></div>`;
  const { q = "", sort, dir, page, per, ...filters } = params;
  if (!("status" in filters) && !q) filters.status = "new";
  let table;
  const reload = () => { table.all = null; table.reload(true); ctx.refreshBadges?.(); };
  table = new DataTable($("#ib", el), {
    id: "inbox", noun: "messages", searchPlaceholder: "Search name, email or message",
    state: { q, sort: sort || "at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/inbox")).items,
    searchText: r => `${r.name} ${r.email || ""} ${r.phone || ""} ${r.title} ${r.body}`,
    onState: setParams,
    builtinViews: [{ name: "New", params: { status: "new" } }, { name: "Demo requests", params: { source: "lead" } }],
    views: "inbox",
    filters: [
      { key: "status", label: "Any status", value: r => r.status,
        options: c => Object.keys(STATUS).map(k => ({ value: k, label: STATUS[k][0], count: c[k] || 0 })) },
      { key: "source", label: "Every type", value: r => r.source,
        options: c => Object.keys(SOURCES).map(k => ({ value: k, label: SOURCES[k][0], count: c[k] || 0 })) },
    ],
    columns: [
      { key: "source", label: "Type", sort: true, firstDir: "asc", render: r => pill(...SOURCES[r.source]) },
      { key: "name", label: "From", sort: true, firstDir: "asc", render: r => `<div class="who"><div><b>${esc(r.name || "—")}</b>
          <span class="small">${esc(r.email || r.phone || "no contact details")}</span></div></div>` },
      { key: "title", label: "Message", render: r => `<b>${esc(r.title)}</b><div class="small muted">${esc(snippet(r.body))}</div>` },
      { key: "status", label: "Status", sort: true, render: r => pill(...STATUS[r.status]) },
      { key: "at", label: "Received", sort: true, render: r => `<span title="${esc(fmtDate(r.at))}">${esc(rel(r.at))}</span>` },
    ],
    onOpen: r => openItem(r, reload),
    bulk: [
      { label: "Mark handled", icon: "check", run: rows => setStatus(rows, "handled") },
      { label: "Archive", icon: "archive", run: rows => setStatus(rows, "archived") },
      { label: "Mark new", icon: "mail", run: rows => setStatus(rows, "new") },
    ],
  });
}

const snippet = t => (t || "").replace(/\s+/g, " ").slice(0, 110) + ((t || "").length > 110 ? "…" : "");

async function setStatus(rows, status) {
  await api("/api/admin/inbox/bulk", { method: "POST", body: { keys: rows.map(r => r.key), status } });
  toast(`${rows.length} marked ${STATUS[status][0].toLowerCase()}`);
  return true;
}

function openItem(r, reload) {
  const wa = waLink(r.phone);
  const meta = Object.entries(r.meta || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  const d = drawer({
    title: SOURCES[r.source][0],
    body: `
      <div class="row">${pill(...STATUS[r.status])}<span class="small faint">received ${esc(fmtDate(r.at))}</span>
        ${r.handled_by ? `<span class="small faint">· last changed by ${esc(r.handled_by)}</span>` : ""}</div>
      <h3>${esc(r.title)}</h3>
      <dl class="kv">
        <dt>From</dt><dd>${esc(r.name || "—")}</dd>
        ${r.email ? `<dt>Email</dt><dd><a href="mailto:${esc(r.email)}">${esc(r.email)}</a></dd>` : ""}
        ${r.phone ? `<dt>Phone</dt><dd>${esc(r.phone)}</dd>` : ""}
        ${meta.map(([k, v]) => `<dt>${esc(k[0].toUpperCase() + k.slice(1))}</dt><dd>${esc(v)}</dd>`).join("")}
      </dl>
      ${r.body ? `<div class="msg">${esc(r.body)}</div>` : ""}
      ${r.replies.length ? `<h3>Replies</h3>${r.replies.map(x => `<div class="reply"><div class="small faint">${esc(x.by || "")} · ${esc(rel(x.at))}</div>
        <b>${esc(x.subject)}</b><div class="msg">${esc(x.body)}</div></div>`).join("")}` : ""}
      <div class="row">
        ${r.email ? `<button class="btn primary" data-reply>${icon("send")} Reply by email</button>` : ""}
        ${wa ? `<a class="btn wa" href="${wa}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}
        ${Object.keys(STATUS).filter(s => s !== r.status).map(s =>
          `<button class="btn" data-status="${s}">${esc(STATUS[s][0] === "New" ? "Mark new" : STATUS[s][0] === "Archived" ? "Archive" : `Mark ${STATUS[s][0].toLowerCase()}`)}</button>`).join("")}
      </div>
      <label class="field"><span>Private note</span><textarea class="textarea" data-note placeholder="Only admins see this">${esc(r.note || "")}</textarea></label>
      <div><button class="btn" data-save-note>Save note</button></div>`,
    onMount: (dEl, close) => {
      $$("[data-status]", dEl).forEach(b => b.addEventListener("click", async () => {
        await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}`, { method: "PATCH", body: { status: b.dataset.status } });
        toast("Updated"); close(); reload();
      }));
      $("[data-save-note]", dEl).addEventListener("click", async () => {
        await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}`, { method: "PATCH", body: { note: $("[data-note]", dEl).value } });
        toast("Note saved"); reload();
      });
      $("[data-reply]", dEl)?.addEventListener("click", async () => {
        const first = (r.name || "").split(/\s+/)[0] || "there";
        const ok = await modal({
          title: `Reply to ${r.email}`, submit: "Send reply",
          body: `<label class="field"><span>Subject</span><input class="input" name="subject" value="${esc(`Re: ${r.title}`)}"></label>
            <label class="field"><span>Message</span><textarea class="textarea" name="body" autofocus>Hi ${esc(first)},\n\n\n\nTee\nPrepWithTee</textarea></label>`,
          run: async m => {
            const subject = $("[name=subject]", m).value.trim(), body = $("[name=body]", m).value.trim();
            if (!subject || !body) return "Write a subject and a message.";
            await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}/reply`, { method: "POST", body: { subject, body } });
            return true;
          } });
        if (ok) { toast("Reply sent"); close(); reload(); }
      });
    },
  });
  return d;
}
