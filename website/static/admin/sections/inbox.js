import { $, $$, api, esc, icon, pill, rel, fmtDate, waLink, modal, toast, drawer, loadingHtml } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Inbox";

const SOURCES = { lead: ["Demo request", "acc"], contact: ["Contact", "pro"], feedback: ["Feedback", "ok"],
                  request: ["Subject request", "warn"], support: ["Help request", "info"] };
const STATUS = { new: ["New", "bad"], replied: ["Replied", "info"], handled: ["Handled", "ok"],
                 archived: ["Archived", ""] };

export async function render(el, { params, setParams, ctx }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Inbox</h1>
      <p>Demo requests, contact messages, feedback, subject requests and help-centre chats in one place.</p></div>
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
    builtinViews: [{ name: "New", params: { status: "new" } }, { name: "Demo requests", params: { source: "lead" } },
                   { name: "Help requests", params: { source: "support" } }],
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
      { key: "title", label: "Message", render: r => `<b>${esc(r.title)}</b>${(r.meta?.snips || []).length ? ` <span class="pill">📎 ${r.meta.snips.length}</span>` : ""}<div class="small muted">${esc(snippet(r.body))}</div>` },
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

// Help-centre chats: the conversation, the device it came from, the student's account.
const HIDDEN_META = new Set(["snips", "transcript", "diag", "user_id"]);
const DIAG_LABELS = { url: "Page", ua: "Browser", screen: "Screen", viewport: "Window", dpr: "Pixel ratio", theme: "Theme",
                      lang: "Language", tz: "Time zone", online: "Online", connection: "Connection", memory: "Memory",
                      errors: "Page errors", failed: "Failed requests" };

function supportBlock(r) {
  if (r.source !== "support") return "";
  const t = r.meta?.transcript || [], dg = r.meta?.diag || {};
  const rows = Object.entries(dg).filter(([, v]) => v && (!Array.isArray(v) || v.length));
  return `
    <div data-acct>${r.meta?.user_id ? loadingHtml("Loading their account…") : `<p class="small faint">Not signed in when they wrote.</p>`}</div>
    ${t.length ? `<h3>The chat before they asked</h3><div class="chat-log">${t.map(m => `<div class="chat-line${m.role === "student" ? " me" : ""}">
      <span class="small faint">${m.role === "student" ? "Student" : "Assistant"}</span><div>${esc(String(m.text).replace(/\*\*/g, ""))}</div></div>`).join("")}</div>` : ""}
    ${rows.length ? `<details class="diag"><summary>Device and errors</summary><dl class="kv">${rows.map(([k, v]) =>
      `<dt>${esc(DIAG_LABELS[k] || k)}</dt><dd>${Array.isArray(v) ? v.map(x => `<div class="mono small">${esc(x)}</div>`).join("") : esc(v)}</dd>`).join("")}</dl></details>` : ""}`;
}

function acctHtml(a) {
  if (!a) return `<p class="small faint">Their account could not be found.</p>`;
  const pay = a.payment;
  return `<div class="card acct-card"><div class="row"><b class="grow">Account</b><a class="btn sm" href="#/student/${esc(a.id)}">Open student</a></div>
    <dl class="kv">
      <dt>Plan</dt><dd>${esc(a.plan || "Free")}${a.trial ? " (trial)" : ""}${a.expires_at ? ` · until ${esc(fmtDate(a.expires_at))}` : ""}</dd>
      ${pay ? `<dt>Last payment proof</dt><dd>${pill(pay.status, pay.status === "approved" ? "ok" : pay.status === "rejected" ? "bad" : "warn")}
        ${esc(pay.plan_label || "")}${pay.period ? ` · ${esc(pay.period)}` : ""} · ${esc(rel(pay.created_at))}</dd>` : ""}
      ${(a.failed || []).length ? `<dt>Failed builds</dt><dd>${a.failed.map(f => `<div>${esc(f.title)} - ${esc(f.why || "")}</div>`).join("")}</dd>` : ""}
      ${a.last_seen ? `<dt>Last seen</dt><dd>${esc(rel(a.last_seen))}</dd>` : ""}
    </dl></div>`;
}

function openItem(r, reload) {
  const wa = waLink(r.phone);
  const snips = (r.meta && r.meta.snips) || [];
  const meta = Object.entries(r.meta || {}).filter(([k, v]) => !HIDDEN_META.has(k) && v !== null && v !== undefined && v !== "");
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
      ${supportBlock(r)}
      ${snips.length ? `<h3>Screenshots</h3><div class="snips">${snips.map((u, i) => `<a class="snip" href="${esc(u)}" target="_blank" rel="noopener"
        title="Open full size"><img src="${esc(u)}" alt="Screenshot ${i + 1} from the student" loading="lazy"></a>`).join("")}</div>` : ""}
      ${r.replies.length ? `<h3>Replies</h3>${r.replies.map(x => `<div class="reply"><div class="small faint">${esc(x.by || "")} · ${esc(rel(x.at))}</div>
        <b>${esc(x.subject)}</b><div class="msg">${esc(x.body)}</div></div>`).join("")}` : ""}
      <div class="row">
        ${r.email ? `<button class="btn primary" data-reply>${icon("send")} Reply by email</button>` : ""}
        ${r.email && r.source === "support" ? `<button class="btn" data-draft>${icon("sparkles")} Draft a reply</button>` : ""}
        ${wa ? `<a class="btn wa" href="${wa}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}
        ${Object.keys(STATUS).filter(s => s !== r.status).map(s =>
          `<button class="btn" data-status="${s}">${esc(STATUS[s][0] === "New" ? "Mark new" : STATUS[s][0] === "Archived" ? "Archive" : `Mark ${STATUS[s][0].toLowerCase()}`)}</button>`).join("")}
      </div>
      <label class="field"><span>Private note</span><textarea class="textarea" data-note placeholder="Only admins see this">${esc(r.note || "")}</textarea></label>
      <div><button class="btn" data-save-note>Save note</button></div>`,
    onMount: (dEl, close) => {
      if (r.source === "support" && r.meta?.user_id) {
        api(`/api/admin/support/${encodeURIComponent(r.id)}/account`)
          .then(d => { const box = $("[data-acct]", dEl); if (box) box.innerHTML = acctHtml(d.account); })
          .catch(() => { const box = $("[data-acct]", dEl); if (box) box.innerHTML = ""; });
      }
      $$("[data-status]", dEl).forEach(b => b.addEventListener("click", async () => {
        await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}`, { method: "PATCH", body: { status: b.dataset.status } });
        toast("Updated"); close(); reload();
      }));
      $("[data-save-note]", dEl).addEventListener("click", async () => {
        await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}`, { method: "PATCH", body: { note: $("[data-note]", dEl).value } });
        toast("Note saved"); reload();
      });
      const reply = async (draft) => {
        const first = (r.name || "").split(/\s+/)[0] || "there";
        const ok = await modal({
          title: `Reply to ${r.email}`, submit: "Send reply", size: "lg",
          body: `<label class="field"><span>Subject</span><input class="input" name="subject" value="${esc(draft?.subject || `Re: ${r.title}`)}"></label>
            <label class="field"><span>Message</span><textarea class="textarea" name="body" autofocus>${esc(draft?.body || `Hi ${first},\n\n\n\nTee\nPrepWithTee`)}</textarea></label>
            ${draft ? `<p class="small faint">Drafted by ${esc(draft.model || "AI")} from the chat and their account - check it before sending.</p>` : ""}`,
          run: async m => {
            const subject = $("[name=subject]", m).value.trim(), body = $("[name=body]", m).value.trim();
            if (!subject || !body) return "Write a subject and a message.";
            await api(`/api/admin/inbox/${r.source}/${encodeURIComponent(r.id)}/reply`, { method: "POST", body: { subject, body } });
            return true;
          } });
        if (ok) { toast("Reply sent"); close(); reload(); }
      };
      $("[data-reply]", dEl)?.addEventListener("click", () => reply(null));
      $("[data-draft]", dEl)?.addEventListener("click", async (e) => {
        const b = e.currentTarget;
        b.disabled = true; b.textContent = "Drafting…";
        try {
          reply(await api(`/api/admin/support/${encodeURIComponent(r.id)}/draft`, { method: "POST" }));
        } catch (ex) { toast(ex.message, true); }
        b.disabled = false; b.innerHTML = `${icon("sparkles")} Draft a reply`;
      });
    },
  });
  return d;
}
