/* PrepWithTee — shared auth helpers.
 *
 * The session is an HTTP-only cookie set by the backend, so nothing here
 * reads or writes a token; every call just rides the cookie. That means the
 * page cannot know whether someone is signed in without asking the server,
 * so getUser() caches the answer for the life of the page.
 */

let _userPromise = null;

/** Current user, or null. Cached per page load. */
export function getUser({ fresh = false } = {}) {
  if (fresh) _userPromise = null;
  if (!_userPromise) {
    _userPromise = fetch("/auth/me", { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _userPromise;
}

/** Send unauthenticated visitors to the login page, preserving where they were. */
export async function requireAuth() {
  const user = await getUser();
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.replace(`/login.html?next=${next}`);
    return null;
  }
  return user;
}

/** Like requireAuth, but also bounces users who haven't finished their profile. */
export async function requireProfile() {
  const user = await requireAuth();
  if (user && !user.profile_complete) {
    location.replace("/profile.html");
    return null;
  }
  return user;
}

export async function logout() {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  location.href = "/index.html";
}

/* ---- API helper ---------------------------------------------------------- */

/** fetch() wrapper that sends/receives JSON and throws the server's message. */
export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body is fine */ }
  if (!res.ok) {
    throw new Error(data?.detail || data?.message || `Request failed (${res.status})`);
  }
  return data;
}

/* ---- Navbar -------------------------------------------------------------- */

const INITIALS = name =>
  (name || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();

/**
 * Swap the "Book a demo lesson" CTA for an account menu once signed in.
 * Every page keeps its own static nav; this only touches the tail end of it.
 */
/**
 * Below 1080px the links live in a drawer. The button is injected rather than
 * added to nine HTML files, and lives next to the nav so CSS alone decides
 * whether it shows.
 */
function initNavToggle(nav) {
  const row = nav.closest(".header-row");
  if (!row || row.querySelector(".nav-toggle")) return;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "nav-toggle";
  btn.setAttribute("aria-label", "Menu");
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-controls", "site-nav");
  btn.innerHTML = `<span class="nav-toggle-bars"><span></span></span>`;
  nav.id ||= "site-nav";
  row.appendChild(btn);

  const setOpen = open => {
    nav.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
  };

  btn.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(!nav.classList.contains("open"));
  });
  // Tapping a link or anywhere off the drawer closes it.
  nav.addEventListener("click", e => {
    if (e.target.closest("a")) setOpen(false);
  });
  document.addEventListener("click", e => {
    if (!nav.contains(e.target) && !btn.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") setOpen(false); });
  // Leaving the drawer breakpoint must not strand an .open class on the desktop nav.
  matchMedia("(max-width: 1080px)").addEventListener("change", e => {
    if (!e.matches) setOpen(false);
  });
}

export async function initNavbar() {
  const nav = document.querySelector(".header-nav");
  if (!nav) return;

  initNavToggle(nav);

  const user = await getUser();

  if (!user) {
    // Signed out: append a prominent Sign in button.
    if (!nav.querySelector(".nav-signin")) {
      const link = document.createElement("a");
      link.href = "/login.html";
      link.className = "btn btn-gold nav-signin";
      link.textContent = "Sign in";
      nav.appendChild(link);
    }
    return;
  }

  // Signed in: Revise link + avatar menu; remove any lingering sign-in button.
  nav.querySelector(".nav-signin")?.remove();

  if (!nav.querySelector(".nav-revise")) {
    const revise = document.createElement("a");
    revise.href = "/revise.html";
    revise.className = "nav-link nav-revise";
    revise.textContent = "Revise";
    nav.appendChild(revise);
  }
  if (nav.querySelector(".account-menu")) return;

  const wrap = document.createElement("div");
  wrap.className = "account-menu";
  wrap.innerHTML = `
    <button type="button" class="account-trigger" aria-haspopup="true" aria-expanded="false">
      ${user.picture_url
        ? `<img class="account-avatar" src="${user.picture_url}" alt="">`
        : `<span class="account-avatar account-initials">${INITIALS(user.name)}</span>`}
      <span class="account-name">${user.name?.split(" ")[0] || "Account"}</span>
      <svg viewBox="0 0 12 8" width="11" height="8" aria-hidden="true">
        <path d="M1 1.5 6 6.5 11 1.5" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="account-dropdown" hidden>
      <a href="/dashboard.html">Dashboard</a>
      <a href="/revise.html">Revision mode</a>
      <a href="/papers.html">Past papers</a>
      <a href="/profile.html">Edit profile</a>
      <button type="button" class="account-logout">Sign out</button>
    </div>`;
  nav.appendChild(wrap);

  const trigger = wrap.querySelector(".account-trigger");
  const drop = wrap.querySelector(".account-dropdown");
  const setOpen = open => {
    drop.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
  };

  trigger.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(drop.hidden);
  });
  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", e => { if (e.key === "Escape") setOpen(false); });
  wrap.querySelector(".account-logout").addEventListener("click", logout);
}

/* Auto-wire the navbar on every page that loads this module. `currentScript`
   is always null inside an ES module, so there is no opt-in attribute to
   read - importing auth.js is itself the opt-in. */
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initNavbar);
} else {
  initNavbar();
}
