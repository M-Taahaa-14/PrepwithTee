import { $, $$, api, esc, icon, pill, pkr, rel, fmtDate, avatar, waLink, modal, toast, drawer,
         tabBar, loadingHtml, emptyState, lookup, PLAN_LABELS, PLAN_SUBJECT_LIMITS } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Payments";

const STATUS_TONE = { pending: "warn", approved: "ok", rejected: "bad" };

export async function render(el, { params, setParams, ctx }) {
  const tab = ["pending", "history", "expiring"].includes(params.tab) ? params.tab : "pending";
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Payments</h1>
      <p>Checks run automatically. You only confirm the money actually arrived.</p></div></div>
    <div id="pay-tabs"></div><div id="pay-body">${loadingHtml()}</div>`;
  let data;
  try { data = await api("/api/admin/payments"); }
  catch (ex) { $("#pay-body", el).innerHTML = `<div class="card">${emptyState("alert-triangle", "Couldn't load payments.", ex.message)}</div>`; return; }
  const pending = data.proofs.filter(p => p.status === "pending");
  $("#pay-tabs", el).innerHTML = tabBar([["pending", "To verify", pending.length], ["history", "Approved and rejected"],
                                         ["expiring", "Expiring plans"]], tab);
  $$("#pay-tabs .tab", el).forEach(b => b.addEventListener("click", () => {
    setParams({ tab: b.dataset.tab }); render(el, { params: { tab: b.dataset.tab }, setParams, ctx });
  }));
  const body = $("#pay-body", el);
  const again = () => { ctx.refreshBadges?.(); render(el, { params: { tab }, setParams, ctx }); };
  if (tab === "pending") renderPending(body, pending, data.periods, again);
  else if (tab === "history") renderHistory(body, data.proofs.filter(p => p.status !== "pending"), params, setParams);
  else renderExpiring(body);
}

/* ── to verify ────────────────────────────────────────────────────────── */

function renderPending(body, proofs, periods, again) {
  if (!proofs.length) { body.innerHTML = `<div class="card">${emptyState("circle-check", "Nothing to verify.", "New payment proofs show up here.")}</div>`; return; }
  proofs.sort((a, b) => (a.created_at > b.created_at ? 1 : -1));
  body.innerHTML = `<div class="proof-grid">${proofs.map(p => {
    const s = p.student;
    const shot = p.has_screenshot
      ? `<img class="shot" src="/api/admin/payments/${p.id}/screenshot" alt="Payment screenshot" loading="lazy" data-zoom="${p.id}">`
      : `<div class="shot-empty">${icon("photo-off")} no screenshot</div>`;
    const cur = s.plan && s.plan !== "free" ? `${PLAN_LABELS[s.plan] || s.plan} until ${fmtDate(s.plan_expires_at)}` : "Free plan";
    return `<div class="card proof" data-proof="${p.id}">
      <div>${shot}</div>
      <div class="stack">
        <div class="row">${avatar(s)}<div class="grow"><b><a href="#/student/${esc(s.id)}">${esc(s.name || s.email)}</a></b>
          <div class="small faint">${esc(s.email || "")} · sent ${esc(rel(p.created_at))}</div></div></div>
        <dl class="kv">
          <dt>Plan</dt><dd>${esc(PLAN_LABELS[p.plan] || p.plan)} · ${esc(p.period_label || "Monthly")}</dd>
          <dt>Amount</dt><dd>${p.amount_pkr ? pkr(p.amount_pkr) : "—"} via ${esc(p.method || "?")}</dd>
          <dt>Transaction id</dt><dd>${esc(p.transaction_id || "—")}</dd>
          <dt>Now on</dt><dd>${esc(cur)}</dd>
          ${p.subjects?.length ? `<dt>Subjects</dt><dd>${esc(p.subjects.join(", "))}</dd>` : ""}
          ${p.note ? `<dt>Student's note</dt><dd>${esc(p.note)}</dd>` : ""}
        </dl>
        <div class="checks">${p.checks.map(c => `<div class="check-row ${c.ok ? "ok" : "bad"}">${icon(c.ok ? "circle-check" : "alert-triangle")}<span>${esc(c.text)}</span></div>`).join("")}</div>
        <div class="manual">${icon("hand-finger")} Check ${p.amount_pkr ? pkr(p.amount_pkr) : "the payment"} arrived in your ${esc(p.method || "account")}</div>
        <div class="row"><button class="btn primary" data-approve="${p.id}">${icon("check")} Approve</button>
          <button class="btn danger" data-reject="${p.id}">${icon("x")} Reject</button>
          ${waLink(s.phone) ? `<a class="btn wa" href="${waLink(s.phone)}" target="_blank" rel="noopener">${icon("brand-whatsapp")}</a>` : ""}</div>
      </div></div>`;
  }).join("")}</div>`;
  const byId = Object.fromEntries(proofs.map(p => [String(p.id), p]));
  $$("[data-zoom]", body).forEach(img => img.addEventListener("click", () => drawer({
    title: "Payment screenshot",
    body: `<img class="shot-full" src="/api/admin/payments/${img.dataset.zoom}/screenshot" alt="Payment screenshot">
      <a class="btn" href="/api/admin/payments/${img.dataset.zoom}/screenshot" target="_blank" rel="noopener">${icon("external-link")} Open full size</a>` })));
  $$("[data-approve]", body).forEach(b => b.addEventListener("click", async () => {
    if (await approveModal(byId[b.dataset.approve], periods)) again();
  }));
  $$("[data-reject]", body).forEach(b => b.addEventListener("click", async () => {
    const p = byId[b.dataset.reject];
    const ok = await modal({
      title: `Reject ${p.student.name || p.student.email}'s payment`, submit: "Reject and email", danger: true,
      body: `<label class="field"><span>Reason (emailed to the student)</span>
        <textarea class="textarea" name="reason" autofocus placeholder="No payment arrived with this transaction id."></textarea></label>
        <div class="chips">${["No payment arrived with this transaction id.", "The amount is less than the plan costs.",
          "The screenshot is unclear - please send a clearer one."].map(t => `<button type="button" class="chip" data-reason="${esc(t)}">${esc(t)}</button>`).join("")}</div>`,
      onMount: m => $$("[data-reason]", m).forEach(c => c.addEventListener("click", () => { $("[name=reason]", m).value = c.dataset.reason; })),
      run: async m => {
        const reason = $("[name=reason]", m).value.trim();
        if (!reason) return "Give the student a reason.";
        const r = await api(`/api/admin/payments/${p.id}/reject`, { method: "POST", body: { reason } });
        toast(r.emailed ? "Rejected - the student was emailed" : "Rejected (email not sent - mail isn't configured)");
        return true;
      } });
    if (ok) again();
  }));
}

async function approveModal(p, periods) {
  const need = PLAN_SUBJECT_LIMITS[p.plan];
  const subjects = need ? await lookup("subjects") : [];
  const chosen = p.subjects?.length ? p.subjects : (p.student.plan === p.plan ? p.student.plan_subjects : []);
  return modal({
    title: `Approve ${p.student.name || p.student.email}`, submit: "Approve and email", size: "lg",
    body: `
      <label class="field"><span>Billing period</span><select class="select" name="period">
        ${Object.entries(periods).map(([k, v]) => `<option value="${k}"${k === (p.period || "monthly") ? " selected" : ""}>${esc(v.label)} - ${pkr(v.amount[p.plan] || 0)}</option>`).join("")}
      </select></label>
      ${need ? `<div class="field"><span>The ${need === 1 ? "subject" : `${need} subjects`} this plan covers</span><div class="chips">
        ${subjects.map(s => `<label class="chip${chosen.includes(s.code) ? " on" : ""}"><input type="checkbox" name="subj" value="${esc(s.code)}" ${chosen.includes(s.code) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}</div></div>` : ""}
      <label class="field"><span>Note to the student (optional)</span><input class="input" name="note" placeholder="Thanks - see you in class!"></label>
      <label class="manual"><input type="checkbox" name="received"> I've seen ${p.amount_pkr ? pkr(p.amount_pkr) : "the money"} arrive in the account</label>
      <p class="small muted">The plan starts now. Renewing early adds to the student's current end date, so no paid days are lost.</p>`,
    onMount: m => m.addEventListener("change", e => {
      if (e.target.name !== "subj") return;
      const ticked = $$("[name=subj]:checked", m);
      if (need === 1 && e.target.checked) ticked.forEach(i => { if (i !== e.target) i.checked = false; });
      else if (ticked.length > need) e.target.checked = false;
      $$("label.chip", m).forEach(c => c.classList.toggle("on", $("input", c).checked));
    }),
    run: async m => {
      if (!$("[name=received]", m).checked) return "Tick the box once you've seen the money in the account.";
      const subs = $$("[name=subj]:checked", m).map(i => i.value);
      if (need && subs.length !== need) return `Choose exactly ${need} subject${need === 1 ? "" : "s"}.`;
      const r = await api(`/api/admin/payments/${p.id}/approve`, { method: "POST", body: {
        received: true, period: $("[name=period]", m).value, note: $("[name=note]", m).value || null,
        subjects: need ? subs : null } });
      toast(`Approved - active until ${fmtDate(r.expires_at)}${r.emailed ? ", student emailed" : ""}`);
      return true;
    },
  });
}

/* ── history ──────────────────────────────────────────────────────────── */

function renderHistory(body, proofs, params, setParams) {
  body.innerHTML = `<div id="pay-hist"></div>`;
  const { q = "", sort, dir, page, per, tab, ...filters } = params;
  new DataTable($("#pay-hist", body), {
    id: "payments-history", noun: "payments", searchPlaceholder: "Search student, transaction id or note",
    state: { q, sort: sort || "reviewed_at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => proofs,
    searchText: r => `${r.student.name} ${r.student.email} ${r.transaction_id || ""} ${r.reviewer_note || ""}`,
    onState: s => setParams({ ...s, tab: "history" }),
    filters: [
      { key: "status", label: "Any result", value: r => r.status },
      { key: "plan", label: "Any plan", value: r => r.plan, label_for: v => PLAN_LABELS[v] || v },
      { key: "method", label: "Any method", value: r => r.method || "" },
    ],
    columns: [
      { key: "student", label: "Student", sortValue: r => (r.student.name || "").toLowerCase(), sort: true, firstDir: "asc",
        render: r => `<a href="#/student/${esc(r.student.id)}">${esc(r.student.name || r.student.email)}</a>` },
      { key: "plan", label: "Plan", sort: true, render: r => `${esc(PLAN_LABELS[r.plan] || r.plan)} <span class="small faint">${esc(r.period_label || "")}</span>` },
      { key: "amount_pkr", label: "Amount", sort: true, num: true, render: r => r.amount_pkr ? pkr(r.amount_pkr) : "—" },
      { key: "method", label: "Method", sort: true },
      { key: "transaction_id", label: "Transaction id" },
      { key: "status", label: "Result", sort: true, render: r => pill(r.status, STATUS_TONE[r.status]) },
      { key: "reviewer_note", label: "Note", render: r => esc(r.reviewer_note || "") },
      { key: "reviewed_by", label: "By", sort: true, hidden: true },
      { key: "reviewed_at", label: "Reviewed", sort: true, render: r => esc(fmtDate(r.reviewed_at)) },
    ],
  });
}

/* ── expiring plans ───────────────────────────────────────────────────── */

async function renderExpiring(body) {
  body.innerHTML = `<div class="toolbar-row"><label class="row">Ending within
      <select class="select" data-days>${[7, 14, 30, 60].map(d => `<option${d === 14 ? " selected" : ""}>${d}</option>`).join("")}</select> days</label></div>
    <div id="exp"></div>`;
  const draw = async () => {
    const days = $("[data-days]", body).value;
    $("#exp", body).innerHTML = loadingHtml();
    const { rows } = await api(`/api/admin/payments/expiring?days=${days}`);
    $("#exp", body).innerHTML = rows.length ? `<div class="dt-wrap"><table class="dt"><thead><tr>
        <th><span class="static">Student</span></th><th><span class="static">Plan</span></th><th><span class="static">Ends</span></th>
        <th><span class="static">Last active</span></th><th></th></tr></thead><tbody>${rows.map(r => `<tr>
        <td><a href="#/student/${esc(r.id)}">${esc(r.name || r.email)}</a></td>
        <td>${esc(PLAN_LABELS[r.plan] || r.plan)}</td><td>${esc(fmtDate(r.plan_expires_at))} <span class="small faint">(${esc(rel(r.plan_expires_at))})</span></td>
        <td>${esc(rel(r.last_active))}</td>
        <td class="nowrap"><button class="btn sm" data-remind="${esc(r.id)}">${icon("mail")} Email reminder</button>
          ${waLink(r.phone) ? `<a class="btn sm wa" href="${waLink(r.phone)}?text=${encodeURIComponent(`Hi ${(r.name || "").split(" ")[0]}, your PrepWithTee plan ends on ${fmtDate(r.plan_expires_at)}. Renew at prepwithtee.com/pricing.html to keep full access.`)}" target="_blank" rel="noopener">${icon("brand-whatsapp")} WhatsApp</a>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>
      <p class="small muted">Reminder emails also go out automatically 7, 3 and 1 day before a plan ends.</p>`
      : `<div class="card">${emptyState("clock", "No paid plans end in this window.")}</div>`;
    $$("[data-remind]", body).forEach(b => b.addEventListener("click", async () => {
      b.disabled = true;
      try { await api(`/api/admin/students/${b.dataset.remind}/renewal-reminder`, { method: "POST" }); toast("Reminder sent"); b.textContent = "Sent"; }
      catch (ex) { toast(ex.message, true); b.disabled = false; }
    }));
  };
  $("[data-days]", body).addEventListener("change", draw);
  draw();
}
