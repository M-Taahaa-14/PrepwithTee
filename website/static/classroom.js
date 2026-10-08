/* My classroom (/classroom/{subject}): filter chips, "I've done this", and
   telling the teacher when something was opened. The page itself is
   server-rendered (classroom.py). */
(function () {
  const post = (url) => fetch(url, { method: "POST", credentials: "same-origin" });

  document.addEventListener("click", async (e) => {
    const chip = e.target.closest("[data-show]");
    if (chip) {
      const k = chip.dataset.show;
      document.querySelectorAll("[data-show]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      document.querySelectorAll(".cr-item").forEach((it) => { it.hidden = !!k && it.dataset.kind !== k; });
      return;
    }
    const open = e.target.closest("[data-open]");
    if (open) {
      // sendBeacon survives the navigation that follows
      const url = `/api/classroom/items/${encodeURIComponent(open.dataset.open)}/open`;
      if (!(navigator.sendBeacon && navigator.sendBeacon(url))) post(url);
      return;
    }
    const btn = e.target.closest("[data-done], [data-undo]");
    if (!btn) return;
    const id = btn.dataset.done || btn.dataset.undo;
    btn.disabled = true;
    const r = await post(`/api/classroom/items/${encodeURIComponent(id)}/done${btn.dataset.undo ? "?undo=1" : ""}`);
    if (r.ok) location.reload();
    else {
      btn.disabled = false;
      const d = await r.json().catch(() => ({}));
      alert(typeof d.detail === "string" ? d.detail : "Couldn't save that - try again.");
    }
  });
})();
