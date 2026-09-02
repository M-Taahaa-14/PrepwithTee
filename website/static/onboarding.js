/* onboarding.js — shared flag store for the onboarding system.
 *
 * flags_json lives on the user's profile row and is embedded in the JWT,
 * so it travels to the browser with every /auth/me response.
 * localStorage is the write-cache: updated optimistically so reads are
 * instant; PATCH /api/flags syncs to the server in the background.
 */

const LS_PFX = "pwt_ob_";

function _key(userId) { return LS_PFX + (userId || "anon"); }

function _parse(raw) {
  try { return typeof raw === "string" ? JSON.parse(raw) : (raw || {}); }
  catch { return {}; }
}

/** Read one boolean flag. Checks localStorage cache first, falls back to JWT. */
export function getFlag(user, key) {
  try {
    const cached = _parse(localStorage.getItem(_key(user.id)));
    if (key in cached) return !!cached[key];
  } catch {}
  return !!_parse(user.flags_json)[key];
}

/** All flags merged: server values overridden by the localStorage write-cache. */
export function getAllFlags(user) {
  const server = _parse(user.flags_json);
  let cached = {};
  try { cached = _parse(localStorage.getItem(_key(user.id))); } catch {}
  return { ...server, ...cached };
}

/**
 * Set a flag optimistically in localStorage, then sync to the server.
 * Fire-and-forget — no await required from the caller.
 */
export function setFlag(user, key, value = true) {
  // Optimistic write
  try {
    const lsKey = _key(user.id);
    const cached = _parse(localStorage.getItem(lsKey));
    cached[key] = value;
    localStorage.setItem(lsKey, JSON.stringify(cached));
  } catch {}

  // Background server sync — silent on failure; localStorage stays as truth
  fetch("/api/flags", {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  }).catch(() => {});
}
