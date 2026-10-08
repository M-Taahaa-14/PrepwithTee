import { $, $$, api, esc, icon, num, rel, loadingHtml, emptyState, toast } from "../core.js";

// Help centre: what students asked the assistant, what it couldn't answer, what
// they disliked, and the status banner + office hours the widget shows.
export const title = "Support";

const INTENTS = {
  payment_status: "Payment status", booklet_problem: "Booklet problems", quota: "Free allowance",
  trial: "Free trial", password: "Password", login: "Signing in", pricing: "Prices", plan_advice: "Which plan",
  classes: "Live classes", parent: "Parents", contact: "Contact Tee", subjects: "Subjects", problem: "Bug reports",
  navigate: "Finding a page", ai: "Answered by AI", fallback: "AI unavailable", handoff: "Sent to Tee",
};
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export async function render(el, { params, setParams }) {
  const days = [7, 30, 90].includes(+params.days) ? +params.days : 7;
  el.innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>Support</h1><p>The help centre: questions students ask, answers that missed, and what the widget tells them.</p></div>
      <label class="sr-only" for="sp-days">Period</label>
      <select class="select" id="sp-days">
        ${[7, 30, 90].map(d => `<option value="${d}"${d === days ? " selected" : ""}>Last ${d} days</option>`).join("")}
      </select>
      <a class="btn" href="#/inbox?source=support">${icon("inbox")} Help requests</a>
    </div>
    <div id="sp-body">${loadingHtml()}</div>`;
  $("#sp-days", el).addEventListener("change", e => { setParams({ days: e.target.value }); render(el, { params: { days: e.target.value }, setParams }); });

  let r, st;
  try {
    [r, st] = await Promise.all([api(`/api/admin/support/report?days=${days}`), api("/api/admin/support/status")]);
  } catch (ex) {
    $("#sp-body", el).innerHTML = `<div class="card">${emptyState("alert-triangle", "Couldn't load the support report.", ex.message)}</div>`;
    return;
  }
  const votes = r.up + r.down;
  const fixes = Object.entries(r.actions || {}).filter(([k]) => ["retry", "trial", "handoff"].includes(k));
  $("#sp-body", el).innerHTML = `
    <div class="kpis">
      ${kpi("message-question", "t-violet", "Questions asked", num(r.asked), `${num(r.people)} people`)}
      ${kpi("send", "t-sky", "Sent to you", num(r.handoffs), "chats handed to Tee")}
      ${kpi("thumb-up", "t-teal", "Helpful", votes ? `${Math.round(r.up / votes * 100)}%` : "—", `${num(votes)} votes`)}
      ${kpi("tool", "t-amber", "One-tap fixes used", num(fixes.reduce((a, [, n]) => a + n, 0)),
        fixes.map(([k, n]) => `${esc({ retry: "retries", trial: "trials", handoff: "handoffs" }[k])} ${n}`).join(" · ") || "none yet")}
    </div>
    <div class="two">
      <div class="stack">
        <div class="card"><h2>What they ask about</h2>
          ${r.by_intent.length ? r.by_intent.map(([k, n]) => `<div class="intent-row"><span>${esc(INTENTS[k] || k)}</span>
            <div class="meter" role="img" aria-label="${esc(`${INTENTS[k] || k}: ${n}`)}"><i class="tone-accent" data-w="${(n / r.by_intent[0][1] * 100).toFixed(0)}"></i></div>
            <b>${num(n)}</b></div>`).join("")
            : emptyState("chart-bar", "No questions in this period yet.")}
        </div>
        <div class="card"><h2>Most asked</h2>
          ${r.top.length ? r.top.map(t => `<div class="list-row">${icon("message")}<span class="grow">${esc(t.question)}</span>
            <span class="pill">${esc(INTENTS[t.intent] || t.intent || "")}</span><b>${num(t.count)}</b></div>`).join("")
            : emptyState("message", "Nothing yet.")}
        </div>
        ${missList("The assistant couldn't answer", "help-circle", r.unanswered, "These are the gaps - a page, an FAQ or a feature fix would answer them next time.")}
        ${missList("Answers marked not helpful", "thumb-down", r.downvoted, "Read the answer it gave - is a fact wrong or missing?")}
      </div>
      <div class="stack">
        <form class="card" id="sp-status">
          <h2>Status banner</h2>
          <p class="small faint">Shown at the top of the help centre - use it when something is broken or slow, so students don't all ask.</p>
          <label class="field"><span>Message</span><textarea class="textarea" name="banner_text" maxlength="300"
            placeholder="e.g. Booklet builds are slow this evening - we're on it.">${esc(st.status.banner?.text || "")}</textarea></label>
          <div class="row">
            <label class="field narrow"><span>Tone</span><select class="select" name="banner_tone">
              ${[["info", "Info"], ["warn", "Problem"], ["ok", "Fixed"]].map(([v, l]) =>
                `<option value="${v}"${(st.status.banner?.tone || "info") === v ? " selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="field narrow"><span>Show until</span><input class="input" type="date" name="banner_until" value="${esc(st.status.banner?.until || "")}"></label>
          </div>
          <h2>Office hours</h2>
          <p class="small faint">Pakistan time. Outside them the widget says when you'll reply. Now: <b>${esc(st.hours.text)}</b></p>
          <div class="row">
            <label class="field narrow"><span>From</span><select class="select" name="hours_start">${hourOpts(st.hours.start)}</select></label>
            <label class="field narrow"><span>Until</span><select class="select" name="hours_end">${hourOpts(st.hours.end, 1)}</select></label>
          </div>
          <div class="chips" role="group" aria-label="Days">${DAYS.map((d, i) =>
            `<label class="chip"><input type="checkbox" name="day" value="${i}"${(st.status.hours?.days || [0, 1, 2, 3, 4, 5, 6]).includes(i) ? " checked" : ""}> ${d}</label>`).join("")}</div>
          <label class="field"><span>Away message (overrides the hours)</span><input class="input" name="away" maxlength="200"
            value="${esc(st.status.away || "")}" placeholder="e.g. Tee is away until Monday - replies may take longer."></label>
          <div class="row"><button class="btn primary" type="submit">${icon("device-floppy")} Save</button>
            <button class="btn" type="button" data-clear>Clear the banner</button></div>
        </form>
      </div>
    </div>`;

  $$(".meter i[data-w]", el).forEach(i => { i.style.width = `${i.dataset.w}%`; });
  const form = $("#sp-status", el);
  const save = async (clear) => {
    const body = {
      banner_text: clear ? "" : form.banner_text.value, banner_tone: form.banner_tone.value,
      banner_until: form.banner_until.value, hours_start: +form.hours_start.value, hours_end: +form.hours_end.value,
      hours_days: $$("[name=day]", form).filter(c => c.checked).map(c => +c.value), away: form.away.value,
    };
    try {
      await api("/api/admin/support/status", { method: "PUT", body });
      toast(clear ? "Banner cleared" : "Saved - the help centre shows it from now");
      render(el, { params: { days }, setParams });
    } catch (ex) { toast(ex.message, true); }
  };
  form.addEventListener("submit", e => { e.preventDefault(); save(false); });
  $("[data-clear]", form).addEventListener("click", () => save(true));
}

function hourOpts(sel, from = 0) {
  let out = "";
  for (let h = from; h <= 23 + from; h++) {
    const label = h === 24 ? "midnight" : `${((h + 11) % 12) + 1} ${h < 12 ? "am" : "pm"}`;
    out += `<option value="${h}"${h === sel ? " selected" : ""}>${label}</option>`;
  }
  return out;
}

function missList(heading, ic, rows, hint) {
  return `<div class="card"><h2>${esc(heading)}</h2><p class="small faint">${esc(hint)}</p>
    ${rows.length ? rows.map(e => `<details class="miss"><summary>${icon(ic)}<span class="grow">${esc(e.question)}</span>
      <span class="small faint nowrap">${esc(rel(e.ts))}</span></summary>
      <div class="small faint">${esc(e.page || "")}${e.signed_in ? " · signed in" : " · guest"}</div>
      <div class="msg">${esc(e.answer || "")}</div></details>`).join("")
      : emptyState("circle-check", "None in this period.")}</div>`;
}

function kpi(ic, tone, label, value, sub) {
  return `<div class="kpi"><span class="kpi-ic ${tone}">${icon(ic)}</span><div class="l">${esc(label)}</div>
    <div class="v">${value}</div><span class="d faint">${sub}</span></div>`;
}
