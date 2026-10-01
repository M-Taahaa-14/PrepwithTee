import { $, api, esc, icon, pill, loadingHtml, emptyState } from "../core.js";

export const title = "Calendly";

export async function render(el) {
  el.innerHTML = `<a class="back" href="#/inbox">${icon("arrow-left")} Inbox</a>
    <div class="page-head"><div class="grow"><h1>Calendly bookings</h1><p>Sessions booked through your Calendly link.</p></div>
      <button class="btn" data-refresh>${icon("refresh")} Refresh</button></div><div id="cal">${loadingHtml()}</div>`;
  const load = async (refresh = false) => {
    $("#cal", el).innerHTML = loadingHtml();
    let d;
    try { d = await api(`/api/admin/calendly${refresh ? "?refresh=true" : ""}`); }
    catch (ex) { if (el.isConnected) $("#cal", el).innerHTML = `<div class="card">${emptyState("alert-triangle", "Couldn't reach Calendly.", ex.message)}</div>`; return; }
    if (!el.isConnected || !$("#cal", el)) return;          // the admin moved on meanwhile

    if (!d.configured) { $("#cal", el).innerHTML = `<div class="card">${emptyState("plug", "Calendly isn't connected.", d.message)}</div>`; return; }
    const now = new Date().toISOString();
    const up = d.events.filter(e => e.start_time >= now).reverse(), past = d.events.filter(e => e.start_time < now);
    const card = e => `<div class="card"><div class="card-head"><h3 class="grow">${esc(e.name)}</h3>
        ${pill(e.status === "active" ? "booked" : e.status, e.status === "active" ? "ok" : "bad")}</div>
        <div class="small muted">${esc(new Date(e.start_time).toLocaleString())}${e.location ? ` · ${esc(e.location)}` : ""}</div>
        ${(e.invitees || []).map(i => `<div class="list-row">${icon("user")}<div class="grow"><b>${esc(i.name)}</b>
          <div class="small"><a href="mailto:${esc(i.email)}">${esc(i.email)}</a> ${i.timezone ? `· ${esc(i.timezone)}` : ""}</div>
          ${(i.questions || []).map(q => `<div class="small muted">${esc(q.question)}: <b>${esc(q.answer)}</b></div>`).join("")}</div></div>`).join("")}
        ${e.join_url ? `<a class="btn sm" href="${esc(e.join_url)}" target="_blank" rel="noopener">${icon("video")} Join link</a>` : ""}</div>`;
    $("#cal", el).innerHTML = `
      <h2>Upcoming (${up.length})</h2><div class="grid two">${up.map(card).join("") || emptyState("calendar", "Nothing booked yet.")}</div>
      <h2 class="small muted">Past (${past.length})</h2><div class="grid two">${past.slice(0, 30).map(card).join("")}</div>`;
  };
  $("[data-refresh]", el).addEventListener("click", () => load(true));
  load();
}

