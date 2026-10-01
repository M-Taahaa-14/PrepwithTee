import { $, api, esc, pill, rel, modal, toast } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Emails";

// The automatic sequence (website/scripts/email_lifecycle.py) plus manual sends.
const TEMPLATES = {
  W1: "Welcome", W2: "Your first step", W3: "Meet the AI", R1: "We miss you (3 days)",
  R2: "Still there? (7 days)", R3: "One last nudge (14 days)", F1: "Weekly study tip",
  MANUAL: "Manual email", PAY_OK: "Payment confirmed", PAY_NO: "Payment not confirmed",
  RENEW_MANUAL: "Renewal reminder (sent by you)",
};
const label = id => TEMPLATES[id] || (id.startsWith("EXP") ? `Plan ending (${id.split(":")[0]})` : id);

export async function render(el, { params, setParams }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Emails</h1>
      <p>What every student has been sent. Tick students to send one of the templates.</p></div></div>
    <div id="em"></div>`;
  const { q = "", sort, dir, page, per, ...filters } = params;
  new DataTable($("#em", el), {
    id: "emails", noun: "students", searchPlaceholder: "Search name or email",
    state: { q, sort: sort || "inactive_days", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/email-activity")).students,
    searchText: r => `${r.name} ${r.email}`,
    onState: setParams,
    filters: [
      { key: "template", label: "Any email", value: r => r.emails_sent.map(e => e.template_id.split(":")[0]),
        label_for: v => label(v) },
      { key: "never", label: "Emailed or not", value: r => (r.emails_sent.length ? "emailed" : "never"),
        options: c => [{ value: "never", label: "Never emailed", count: c.never || 0 }, { value: "emailed", label: "Emailed", count: c.emailed || 0 }] },
    ],
    columns: [
      { key: "name", label: "Student", sort: true, firstDir: "asc",
        render: r => `<a href="#/student/${esc(r.id)}"><b>${esc(r.name || "—")}</b></a><div class="small faint">${esc(r.email)}</div>` },
      { key: "inactive_days", label: "Inactive", sort: true, num: true, render: r => r.inactive_days ? `${r.inactive_days} d` : "today" },
      { key: "emails", label: "Emails sent", sortValue: r => r.emails_sent.length, sort: true,
        render: r => r.emails_sent.slice(-4).reverse().map(e => pill(label(e.template_id))).join(" ") || `<span class="faint">none</span>` },
      { key: "last", label: "Last email", sortValue: r => r.emails_sent.at(-1)?.sent_at || "", sort: true,
        render: r => esc(rel(r.emails_sent.at(-1)?.sent_at)) },
    ],
    bulk: [{ label: "Send a template", icon: "send", run: sendTemplate }],
  });
}

function sendTemplate(rows) {
  const ids = ["R1", "R2", "R3", "W1", "W2", "W3", "F1"];
  return modal({
    title: `Send to ${rows.length} student${rows.length === 1 ? "" : "s"}`, submit: "Send", size: "lg",
    body: `<label class="field"><span>Template</span><select class="select" name="t">${ids.map(i => `<option value="${i}">${esc(TEMPLATES[i])}</option>`).join("")}</select></label>
      <label class="check"><input type="checkbox" name="log" checked> Count it as sent (the automatic sequence won't repeat it)</label>
      <iframe class="preview-frame" title="Preview" sandbox=""></iframe>`,
    onMount: m => {
      const show = async () => {
        const d = await api(`/api/admin/email-preview?template=${$("[name=t]", m).value}&name=${encodeURIComponent(rows[0].name || "Student")}`);
        $("iframe", m).srcdoc = d.html;
      };
      $("[name=t]", m).addEventListener("change", show); show();
    },
    run: async m => {
      const r = await api("/api/admin/send-email", { method: "POST", body: {
        user_ids: rows.map(x => x.id), template: $("[name=t]", m).value, log_send: $("[name=log]", m).checked } });
      toast(`${r.sent} of ${r.total} sent`, r.sent < r.total);
      return true;
    },
  });
}

