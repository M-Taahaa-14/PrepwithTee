import { $, $$, api, esc, icon, pill, rel, fmtDate, num, modal, toast, confirmBox, tabBar, loadingHtml,
         emptyState, debounce } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Newsletter";

const B_TONE = { queued: "warn", sending: "info", sent: "ok", failed: "bad", cancelled: "" };

export async function render(el, { params, setParams, ctx }) {
  const tab = ["broadcasts", "subscribers"].includes(params.tab) ? params.tab : "broadcasts";
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Newsletter</h1>
      <p>People who joined the list from the site footer. Broadcasts send in the background.</p></div>
      ${tab === "broadcasts" ? `<button class="btn primary" data-new>${icon("pencil")} New broadcast</button>` : ""}</div>
    <div id="n-tabs"></div><div id="n-body">${loadingHtml()}</div>`;
  $("#n-tabs", el).innerHTML = tabBar([["broadcasts", "Broadcasts"], ["subscribers", "Subscribers"]], tab);
  $$("#n-tabs .tab", el).forEach(b => b.addEventListener("click", () => {
    setParams({ tab: b.dataset.tab }); render(el, { params: { tab: b.dataset.tab }, setParams, ctx });
  }));
  if (tab === "subscribers") return renderSubscribers($("#n-body", el), params, setParams);
  $("[data-new]", el).addEventListener("click", async () => { if (await composer()) drawBroadcasts(); });
  const drawBroadcasts = async () => {
    const { broadcasts } = await api("/api/admin/newsletter/broadcasts");
    const body = $("#n-body", el);
    if (!body) return;
    body.innerHTML = broadcasts.length ? `<div class="dt-wrap"><table class="dt"><thead><tr><th><span class="static">Subject</span></th>
      <th><span class="static">Status</span></th><th><span class="static">Progress</span></th><th><span class="static">When</span></th><th></th></tr></thead>
      <tbody>${broadcasts.map(b => {
        const done = (b.sent || 0) + (b.failed || 0), total = b.total || 0;
        return `<tr><td><b>${esc(b.subject)}</b><div class="small faint">by ${esc(b.created_by || "admin")}</div></td>
          <td>${pill(b.status, B_TONE[b.status])}</td>
          <td><div class="progress"><i data-w="${total ? Math.min(100, (done / total) * 100).toFixed(1) : 0}"></i></div>
            <span class="small faint">${num(b.sent || 0)} sent${b.failed ? `, ${num(b.failed)} failed` : ""} of ${num(total)}</span></td>
          <td>${esc(b.status === "queued" && b.scheduled_at ? `scheduled ${fmtDate(b.scheduled_at)} ${new Date(b.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : rel(b.finished_at || b.started_at || b.created_at))}</td>
          <td>${["queued", "sending"].includes(b.status) ? `<button class="btn sm danger" data-cancel="${b.id}">Cancel</button>` : ""}</td></tr>`;
      }).join("")}</tbody></table></div>` : `<div class="card">${emptyState("mail", "No broadcasts yet.", "Write one to everyone on the list.")}</div>`;
    $$(".progress i[data-w]", body).forEach(i => { i.style.width = `${i.dataset.w}%`; });
    $$("[data-cancel]", body).forEach(b => b.addEventListener("click", async () => {
      if (!(await confirmBox("Cancel broadcast", "Stop sending? People already emailed keep their copy.", "Stop sending", true))) return;
      await api(`/api/admin/newsletter/broadcasts/${b.dataset.cancel}/cancel`, { method: "POST" });
      drawBroadcasts();
    }));
    // keep the progress bars moving while something is sending
    if (broadcasts.some(b => ["queued", "sending"].includes(b.status))) {
      clearTimeout(drawBroadcasts.t);
      drawBroadcasts.t = setTimeout(() => { if (document.body.contains(body)) drawBroadcasts(); }, 4000);
    }
  };
  drawBroadcasts();
}

function composer() {
  return modal({
    title: "New broadcast", submit: "Queue for everyone", size: "xl",
    body: `
      <div class="ai-bar row"><span class="small muted">${icon("sparkles")} Draft it with AI:</span>
        <input class="input grow" name="ai_prompt" placeholder="This week: exam timetable, 3 revision tips, new chemistry notes">
        <label class="check small"><input type="checkbox" name="ai_posts" checked> feature recent posts</label>
        <button type="button" class="btn sm primary" data-ai>Write it</button></div>
      <label class="field"><span>Subject</span><input class="input" name="subject" required autofocus></label>
      <div class="composer">
        <label class="field"><span>Message (Markdown: **bold**, ## heading, - list, [link](https://…))</span>
          <textarea class="textarea" name="body" rows="14" placeholder="## This week at PrepWithTee&#10;&#10;..."></textarea></label>
        <div class="field"><span>Preview</span><iframe class="preview-frame" title="Email preview" sandbox=""></iframe></div>
      </div>
      <div class="row"><label class="field grow"><span>Button text (optional)</span><input class="input" name="cta_label" placeholder="Start practising"></label>
        <label class="field grow"><span>Button link</span><input class="input" name="cta_url" placeholder="https://prepwithtee.com/papers"></label></div>
      <div class="row"><label class="field"><span>Send at (empty = now)</span><input class="input" type="datetime-local" name="when"></label>
        <label class="field grow"><span>Send a test copy to</span><input class="input" type="email" name="test" placeholder="you@example.com"></label>
        <button type="button" class="btn" data-test>${icon("send")} Send test</button></div>
      <p class="small muted">Every email carries a working unsubscribe link. Sends go out in small batches, so a long list takes a few minutes.</p>`,
    onMount: m => {
      const val = n => $(`[name=${n}]`, m).value.trim();
      const preview = debounce(async () => {
        if (!val("body")) { $("iframe", m).srcdoc = ""; return; }
        try {
          const { html } = await api("/api/admin/newsletter/preview", { method: "POST",
            body: { body_markdown: val("body"), cta_label: val("cta_label") || null, cta_url: val("cta_url") || null } });
          $("iframe", m).srcdoc = html;
        } catch { /* preview is best-effort */ }
      }, 500);
      m.addEventListener("input", e => { if (["body", "cta_label", "cta_url"].includes(e.target.name)) preview(); });
      $("[data-ai]", m).addEventListener("click", async e => {
        const btn = e.currentTarget; btn.disabled = true; btn.textContent = "Writing…";
        try {
          const { draft } = await api("/api/admin/newsletter/ai", { method: "POST", body: {
            prompt: $("[name=ai_prompt]", m).value.trim(), include_posts: $("[name=ai_posts]", m).checked } });
          $("[name=subject]", m).value = draft.subject; $("[name=body]", m).value = draft.body_markdown;
          $("[name=cta_label]", m).value = draft.cta_label || ""; $("[name=cta_url]", m).value = draft.cta_url || "";
          preview(); toast("Drafted - read it through before sending");
        } catch (ex) { toast(ex.message, true); }
        finally { btn.disabled = false; btn.textContent = "Write it"; }
      });
      $("[data-test]", m).addEventListener("click", async () => {
        if (!val("subject") || !val("body") || !val("test")) { toast("Write a subject and message, and a test address", true); return; }
        try {
          await api("/api/admin/newsletter/broadcasts", { method: "POST", body: { subject: val("subject"), body_markdown: val("body"),
            cta_label: val("cta_label") || null, cta_url: val("cta_url") || null, test_email: val("test") } });
          toast(`Test sent to ${val("test")}`);
        } catch (ex) { toast(ex.message, true); }
      });
    },
    run: async m => {
      const val = n => $(`[name=${n}]`, m).value.trim();
      if (!val("subject") || !val("body")) return "Write a subject and a message.";
      const when = val("when");
      const r = await api("/api/admin/newsletter/broadcasts", { method: "POST", body: {
        subject: val("subject"), body_markdown: val("body"), cta_label: val("cta_label") || null,
        cta_url: val("cta_url") || null, scheduled_at: when ? new Date(when).toISOString() : null } });
      toast(when ? "Scheduled" : `Queued for ${r.broadcast.total} subscribers`);
      return true;
    },
  });
}

function renderSubscribers(body, params, setParams) {
  body.innerHTML = `<div id="subs"></div>`;
  const { q = "", sort, dir, page, per, tab, ...filters } = params;
  new DataTable($("#subs", body), {
    id: "subscribers", noun: "subscribers", searchPlaceholder: "Search email",
    state: { q, sort: sort || "subscribed_at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/newsletter/subscribers")).subscribers,
    searchText: r => r.email,
    onState: s => setParams({ ...s, tab: "subscribers" }),
    csv: () => "/api/admin/newsletter/export",
    filters: [{ key: "status", label: "Any status", value: r => r.status }],
    columns: [
      { key: "email", label: "Email", sort: true, firstDir: "asc" },
      { key: "status", label: "Status", sort: true, render: r => pill(r.status, r.status === "subscribed" ? "ok" : "") },
      { key: "subscribed_at", label: "Joined", sort: true, render: r => esc(fmtDate(r.subscribed_at)) },
      { key: "unsubscribed_at", label: "Left", sort: true, hidden: true, render: r => esc(r.unsubscribed_at ? fmtDate(r.unsubscribed_at) : "—") },
    ],
    bulk: [
      { label: "Unsubscribe", icon: "mail-off", run: rows => setStatus(rows, "unsubscribed") },
      { label: "Resubscribe", icon: "mail", run: rows => setStatus(rows, "subscribed") },
    ],
  });
}

async function setStatus(rows, status) {
  for (const r of rows) await api(`/api/admin/newsletter/subscribers/${r.id}`, { method: "PATCH", body: { status } });
  toast(`${rows.length} ${status}`);
  return true;
}
