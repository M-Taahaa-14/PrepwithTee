import { $, api, esc, icon, num, pkr, rel, bars, loadingHtml, emptyState } from "../core.js";

export const title = "Overview";

const ATTENTION = [
  { key: "inbox_new", icon: "inbox", text: n => `${n} new message${n === 1 ? "" : "s"} in the inbox`,
    href: "#/inbox", tone: "bad" },
  { key: "pending_proofs", icon: "receipt", text: n => `${n} payment proof${n === 1 ? "" : "s"} to verify`,
    href: "#/payments", tone: "warn" },
  { key: "applications", icon: "user-plus", text: n => `${n} teacher application${n === 1 ? "" : "s"}`,
    href: "#/teachers?tab=applications", tone: "acc" },
  { key: "expiring_7", icon: "clock", text: n => `${n} plan${n === 1 ? "" : "s"} expire this week`,
    href: "#/students?expiring=7", tone: "warn" },
  { key: "overdue_homework", icon: "notebook", text: n => `${n} homework item${n === 1 ? "" : "s"} overdue`,
    href: "#/homework?state=overdue", tone: "bad" },
  { key: "incomplete_profiles", icon: "user-exclamation", text: n => `${n} incomplete profile${n === 1 ? "" : "s"}`,
    href: "#/students?profile=incomplete", tone: "" },
];
const FEED_ICONS = { booklet: "book", mcq: "checkbox", signup: "user-plus", payment: "receipt" };

export async function render(el, { params, setParams }) {
  const days = [7, 30, 90].includes(+params.days) ? +params.days : 7;
  el.innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>Overview</h1><p>What's happening across PrepWithTee.</p></div>
      <label class="sr-only" for="ov-days">Period</label>
      <select class="select" id="ov-days">
        ${[7, 30, 90].map(d => `<option value="${d}"${d === days ? " selected" : ""}>Last ${d} days</option>`).join("")}
      </select>
    </div>
    <div id="ov-body">${loadingHtml()}</div>`;
  $("#ov-days", el).addEventListener("change", e => { setParams({ days: e.target.value }); render(el, { params: { days: e.target.value }, setParams }); });

  let d;
  try {
    d = await api(`/api/admin/overview/stats?days=${days}`);
  } catch (ex) {
    $("#ov-body", el).innerHTML = `<div class="card">${emptyState("alert-triangle", "Couldn't load the overview.", ex.message)}</div>`;
    return;
  }
  const k = d.kpis;
  const delta = (cur, prev, fmt = num) => {
    if (!prev && !cur) return `<span class="d faint">no change</span>`;
    if (!prev) return `<span class="d tone-ok">new this period</span>`;
    const p = Math.round(((cur - prev) / prev) * 100);
    const cls = p > 0 ? "tone-ok" : p < 0 ? "tone-bad" : "faint";
    return `<span class="d ${cls}">${p > 0 ? "+" : ""}${p}% vs previous ${days} days (${fmt(prev)})</span>`;
  };
  const att = ATTENTION.filter(a => d.attention[a.key]);
  $("#ov-body", el).innerHTML = `
    <div class="kpis">
      ${kpi("users", "t-violet", "Active students", num(k.active.cur), delta(k.active.cur, k.active.prev))}
      ${kpi("user-plus", "t-teal", "New sign-ups", num(k.signups.cur), delta(k.signups.cur, k.signups.prev))}
      ${kpi("books", "t-sky", "Booklets and MCQ sessions", num(k.practice.cur), delta(k.practice.cur, k.practice.prev))}
      ${kpi("cash", "t-amber", "Payments approved", pkr(k.revenue.cur), delta(k.revenue.cur, k.revenue.prev, pkr))}
      ${kpi("school", "t-rose", "Students in total", num(k.students), `<span class="d faint">all registered accounts</span>`)}
    </div>
    <div class="two">
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">Needs your attention</h2></div>
          ${att.length ? att.map(a => `
            <a class="list-row link" href="${a.href}">${icon(a.icon)}<span class="grow">${esc(a.text(d.attention[a.key]))}</span>
              ${a.key === "pending_proofs" && d.attention.oldest_proof
                ? `<span class="pill ${a.tone}">oldest ${esc(rel(d.attention.oldest_proof))}</span>`
                : `<span class="pill ${a.tone}">open</span>`}</a>`).join("")
            : emptyState("circle-check", "All clear.", "Nothing is waiting on you.")}
        </div>
        <div class="card"><h2>Practice per day</h2>
          ${d.practice_by_day.length ? bars(fillDays(d.practice_by_day, days).map(x => ({ label: x.date, value: x.count })))
            : emptyState("chart-bar", "No practice in this period yet.")}
        </div>
      </div>
      <div class="card"><h2>Recent activity</h2>
        ${d.feed.length ? d.feed.map(f => `
          <a class="list-row link" href="#/student/${esc(f.user_id)}">${icon(FEED_ICONS[f.type] || "point")}
            <span class="grow">${esc(f.text)}</span><span class="small faint nowrap">${esc(rel(f.at))}</span></a>`).join("")
          : emptyState("activity", "No activity yet.")}
      </div>
    </div>`;
}

function kpi(ic, tone, label, value, sub) {
  return `<div class="kpi"><span class="kpi-ic ${tone}">${icon(ic)}</span><div class="l">${esc(label)}</div>
    <div class="v">${value}</div>${sub}</div>`;
}

function fillDays(series, days) {
  const by = Object.fromEntries(series.map(s => [s.date, s.count]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    out.push({ date: d, count: by[d] || 0 });
  }
  return out;
}
