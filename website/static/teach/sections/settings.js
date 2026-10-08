// The teacher's own settings: public profile (the Teachers page card) + password.
import { $, api, esc, toast, loadingHtml } from "/admin/core.js";

export const title = "Settings";

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Settings</h1></div></div><div class="two">
    <div class="card" data-prof>${loadingHtml()}</div>
    <div class="card"><h2>Change password</h2>
      <form class="stack" data-pw>
        <label class="field"><span>Current password</span><input class="input" type="password" name="cur" autocomplete="current-password"></label>
        <label class="field"><span>New password</span><input class="input" type="password" name="pw" autocomplete="new-password" minlength="8" required></label>
        <p class="small faint">At least 8 characters with a letter and a number.</p>
        <button class="btn primary">Change password</button></form></div></div>`;
  const pbox = $("[data-prof]", el);
  const prof = (await api("/api/teacher/profile").catch(() => ({}))).profile || {};
  if (!pbox.isConnected) return;
  pbox.innerHTML = `<h2>Public profile</h2><p class="small muted">What students and parents see on the Teachers page.</p>
    <form class="stack" data-pf>
      <label class="field"><span>About you</span><textarea class="textarea" name="bio">${esc(prof.bio || "")}</textarea></label>
      <label class="field"><span>Qualifications</span><input class="input" name="q" value="${esc(prof.qualifications || "")}"></label>
      <div class="row"><label class="field narrow"><span>Years teaching</span><input class="input" type="number" name="y" min="0" max="60" value="${esc(prof.experience_years ?? "")}"></label>
        <label class="field"><span>Phone</span><input class="input" name="ph" value="${esc(prof.phone || "")}"></label></div>
      <button class="btn primary">Save profile</button></form>`;
  $("[data-pf]", el).addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target;
    try {
      await api("/api/teacher/profile", { method: "PUT", body: { bio: f.bio.value.trim(), qualifications: f.q.value.trim(),
        experience_years: f.y.value === "" ? null : +f.y.value, phone: f.ph.value.trim() } });
      toast("Profile saved");
    } catch (ex) { toast(ex.message, true); }
  });
  $("[data-pw]", el).addEventListener("submit", async e => {
    e.preventDefault();
    const f = e.target;
    // plain fetch: a wrong current password is a 401, which api() would treat as "signed out"
    const r = await fetch("/auth/set-password", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: f.pw.value, current_password: f.cur.value }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok) { toast("Password changed"); f.reset(); }
    else toast(typeof d.detail === "string" ? d.detail : "Couldn't change the password", true);
  });
}
