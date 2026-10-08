// Messages with my students (and the admin): /api/messages.
import { $, $$, api, esc, avatar, rel, loadingHtml, emptyState, toast } from "/admin/core.js";

export const title = "Messages";

export async function render(el, { params, ctx }) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Messages</h1><p>Conversations with your students.</p></div></div>
    <div class="msg-shell card"><aside class="msg-list" data-list>${loadingHtml()}</aside><section class="msg-thread" data-thread>
      ${emptyState("message-circle", "Pick a conversation.")}</section></div>`;
  let convs = [];
  const listBox = $("[data-list]", el);
  try { convs = (await api("/api/messages")).conversations || []; } catch (ex) { toast(ex.message, true); }
  if (!listBox.isConnected) return;
  const people = new Map();
  (ctx.students || []).forEach(s => people.set(s.id, { id: s.id, name: s.name || s.email, picture_url: s.picture_url }));
  convs.forEach(c => people.set(c.partner_id, { ...(people.get(c.partner_id) || {}), id: c.partner_id,
    name: c.partner_name || people.get(c.partner_id)?.name || "Someone", picture_url: c.partner_pic || people.get(c.partner_id)?.picture_url,
    last: c.last_body || c.last_message, at: c.last_at || c.created_at, unread: c.unread || 0 }));
  const list = [...people.values()].sort((a, b) => (b.at || "").localeCompare(a.at || "") || (a.name || "").localeCompare(b.name || ""));
  $("[data-list]", el).innerHTML = list.length ? list.map(p => `<button class="list-row link" data-pid="${esc(p.id)}">${avatar(p)}
      <span class="grow"><b>${esc(p.name)}</b>${p.last ? `<span class="small faint msg-last">${esc(p.last)}</span>` : ""}</span>
      ${p.unread ? `<span class="badge">${p.unread}</span>` : ""}</button>`).join("") : emptyState("users", "No students yet.");
  const open = async pid => {
    $$("[data-pid]", el).forEach(b => b.classList.toggle("on", b.dataset.pid === pid));
    const box = $("[data-thread]", el);
    box.innerHTML = loadingHtml();
    const { messages } = await api(`/api/messages/${encodeURIComponent(pid)}`);
    box.innerHTML = `<div class="msg-items">${messages.map(m => `<div class="bubble${m.sender_id === ctx.me.id ? " me" : ""}">
        ${esc(m.body)}<span class="small faint">${esc(rel(m.created_at))}</span></div>`).join("") || `<p class="small faint">Say hello.</p>`}</div>
      <form class="row msg-form"><label class="sr-only" for="msg-b">Message</label>
        <textarea class="textarea grow" id="msg-b" rows="2" placeholder="Write a message"></textarea><button class="btn primary">Send</button></form>`;
    const items = $(".msg-items", box);
    items.scrollTop = items.scrollHeight;
    $(".msg-form", box).addEventListener("submit", async e => {
      e.preventDefault();
      const v = $("#msg-b", box).value.trim();
      if (!v) return;
      try { await api("/api/messages", { method: "POST", body: { recipient_id: pid, body: v } }); open(pid); ctx.refresh(); }
      catch (ex) { toast(ex.message, true); }
    });
  };
  $$("[data-pid]", el).forEach(b => b.addEventListener("click", () => open(b.dataset.pid)));
  if (params.to && people.has(params.to)) open(params.to);
}
