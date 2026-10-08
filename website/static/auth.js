/* PrepWithTee — shared auth helpers.
 *
 * The session is an HTTP-only cookie set by the backend, so nothing here
 * reads or writes a token; every call just rides the cookie. That means the
 * page cannot know whether someone is signed in without asking the server,
 * so getUser() caches the answer for the life of the page.
 */

let _userPromise = null;

/** Current user, or null. Cached per page load. Resolves to null on timeout (12 s). */
export function getUser({ fresh = false } = {}) {
  if (fresh) _userPromise = null;
  if (!_userPromise) {
    const url = fresh ? "/auth/me?fresh=true" : "/auth/me";
    var fetchPromise = fetch(url, { credentials: "same-origin" })
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null);
    var timeoutPromise = new Promise(function(resolve) { setTimeout(resolve, 12000, null); });
    _userPromise = Promise.race([fetchPromise, timeoutPromise]);
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

/** Like requireAuth, but also bounces users who haven't finished their profile.
 *  Students who already have a grade but no subjects are sent to the dashboard
 *  enrolment section rather than back to profile.html (which can't help them). */
export async function requireProfile() {
  const user = await requireAuth();
  if (!user) return null;
  if (!user.profile_complete) {
    if (user.grade && user.role === "student") {
      // Grade is set — they just need to pick subjects.
      // If not already on the dashboard, bounce there with ?needs-subjects so
      // init() scrolls straight to the enrol grid.  If already there, let the
      // page render normally (renderSetupBanner / showWelcomeModal will guide them).
      if (location.pathname !== "/dashboard.html") {
        location.replace("/dashboard.html?needs-subjects");
        return null;
      }
      return user;
    }
    location.replace("/profile.html");
    return null;
  }
  return user;
}

/**
 * Require the user to have one of the given roles.
 * Unauthenticated users are sent to /login.html; wrong-role users to their own dashboard.
 */
export async function requireRole(...roles) {
  const user = await getUser();
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.replace(`/login.html?next=${next}`);
    return null;
  }
  if (!roles.includes(user.role)) {
    const home = user.role === "admin"   ? "/admin.html"
               : user.role === "teacher" ? "/teach"
               : user.role === "parent"  ? "/parent-dashboard.html"
               : "/dashboard.html";
    location.replace(home);
    return null;
  }
  return user;
}

export async function logout() {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  location.href = "/index.html";
}

/* ---- API helper ---------------------------------------------------------- */

/** fetch() wrapper that sends/receives JSON and throws the server's message.
 *  Default 20 s timeout — pass { timeout: 0 } to disable. */
/**
 * Thrown when a 403/429 with an upgrade_required or quota_exceeded code is returned.
 * Callers can catch this specifically to show the upgrade modal.
 */
export class UpgradeRequiredError extends Error {
  constructor(detail) {
    super(detail?.message || "Upgrade required");
    this.name = "UpgradeRequiredError";
    this.detail = detail || {};
    this.minPlan  = detail?.min_plan || "pro";
  }
}

export async function api(path, { method = "GET", body, timeout = 20000 } = {}) {
  const ac = new AbortController();
  const tid = timeout ? setTimeout(() => ac.abort(), timeout) : null;
  try {
    const res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ac.signal,
    });
    let data = null;
    try { data = await res.json(); } catch { /* empty body is fine */ }
    if (!res.ok) {
      const detail = typeof data?.detail === "object" ? data.detail : {};
      if ((res.status === 403 || res.status === 429) &&
          (detail.code === "upgrade_required" || detail.code === "quota_exceeded")) {
        throw new UpgradeRequiredError(detail);
      }
      // detail can be a string, an object ({code, message}) or FastAPI's list of
      // validation errors - never let "[object Object]" reach a student.
      const msg = typeof data?.detail === "string" ? data.detail
        : detail.message || (Array.isArray(data?.detail) && data.detail[0]?.msg?.replace(/^Value error, /, ""))
        || data?.message || `Request failed (${res.status})`;
      const err = new Error(msg);
      err.status = res.status;
      err.detail = data?.detail;
      throw err;
    }
    return data;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Request timed out — check your connection and try again.");
    throw err;
  } finally {
    if (tid) clearTimeout(tid);
  }
}

/* ---- Loading splash ------------------------------------------------------ */

/**
 * Branded loading block: bobbing owl, sweeping perch, rotating captions and
 * skeleton rows so the layout does not jump when real content lands.
 * `kind` picks a caption set; `rows` is how many skeleton bars to show.
 */
export function teeLoader(kind = "subjects", rows = 4) {
  return `
    <div class="tee-load" role="status" aria-live="polite">
      <div class="tee-skeleton" aria-hidden="true">
        ${Array.from({ length: rows }, () => "<i></i>").join("")}
      </div>
    </div>`;
}

/* ---- Navbar -------------------------------------------------------------- */

const INITIALS = name =>
  (name || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();

/**
 * Swap the "Book a demo lesson" CTA for an account menu once signed in.
 * Every page keeps its own static nav; this only touches the tail end of it.
 */
/**
 * Below 1200px the links live in a drawer. The button is injected rather than
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
  const right = row.querySelector(".header-right");
  (right || row).appendChild(btn);

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
  matchMedia("(max-width: 1200px)").addEventListener("change", e => {
    if (!e.matches) setOpen(false);
  });
}

/** Badge the Homework link with the number of open tasks, red once overdue. */
async function refreshHomeworkBadge(link) {
  try {
    const { open = 0, overdue = 0 } = await api("/api/assignments");
    if (!open) return;
    const dot = document.createElement("span");
    dot.className = "nav-badge" + (overdue ? " nav-badge-late" : "");
    dot.textContent = open;
    dot.title = overdue
      ? `${overdue} overdue of ${open} open`
      : `${open} piece${open === 1 ? "" : "s"} of homework to do`;
    link.appendChild(dot);
  } catch { /* signed out mid-flight, or the API is down — leave it unbadged */ }
}

/* ---- Notification bell ----------------------------------------------------
 *
 * Injected into the nav rather than written into 24 HTML files, so every page
 * a student can be on carries the same alerts.
 *
 * "Read" is a single timestamp in localStorage, not server state: the feed is
 * derived from assignments the student already owns, so there is nothing worth
 * a write path — and marking one device read should not silently mark another.
 */
const NOTIF_SEEN_KEY = "pwt_notifs_seen";

function notifSeenAt() {
  try { return localStorage.getItem(NOTIF_SEEN_KEY) || ""; } catch { return ""; }
}
function markNotifsSeen(latest) {
  try { localStorage.setItem(NOTIF_SEEN_KEY, latest || new Date().toISOString()); }
  catch { /* private mode — the bell just stops remembering, which is survivable */ }
}

function notifWhen(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d} days ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

function mountBell(nav) {
  const right = document.querySelector(".header-right");
  const target = right || nav;
  const wrap = document.createElement("div");
  wrap.className = "notif-wrap";
  wrap.innerHTML = `
    <button type="button" class="notif-btn" aria-haspopup="true" aria-expanded="false"
            aria-label="Notifications" title="Notifications">
      <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
        <path d="M12 3a5.5 5.5 0 0 0-5.5 5.5c0 3.2-.8 5-1.7 6.1-.5.6-.1 1.6.7 1.6h13c.8 0 1.2-1 .7-1.6-.9-1.1-1.7-2.9-1.7-6.1A5.5 5.5 0 0 0 12 3Z"
              fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
        <path d="M10 19.5a2 2 0 0 0 4 0" fill="none" stroke="currentColor"
              stroke-width="1.7" stroke-linecap="round"/>
      </svg>
      <span class="notif-dot" hidden></span>
    </button>
    <div class="notif-panel" hidden role="dialog" aria-label="Notifications">
      <div class="notif-head">
        <b>Notifications</b>
        <a href="/homework.html">All homework</a>
      </div>
      <div class="notif-list"><p class="notif-empty">Loading…</p></div>
    </div>`;
  target.appendChild(wrap);

  const btn = wrap.querySelector(".notif-btn");
  const panel = wrap.querySelector(".notif-panel");
  const dot = wrap.querySelector(".notif-dot");
  const list = wrap.querySelector(".notif-list");
  let loaded = null;

  const setOpen = open => {
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open && loaded) {
      // Opening IS reading — clear the badge against the newest item so a
      // later one still counts as new.
      markNotifsSeen(loaded.latest_at);
      dot.hidden = true;
      wrap.classList.remove("has-unread");
    }
  };

  btn.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(panel.hidden);
  });
  document.addEventListener("click", e => {
    if (!wrap.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") setOpen(false);
  });

  (async () => {
    try {
      loaded = await api("/api/notifications");
    } catch {
      list.innerHTML = `<p class="notif-empty">Couldn't load notifications.</p>`;
      return;
    }
    const notes = loaded.notifications || [];
    const seen = notifSeenAt();
    const unread = notes.filter(n => !n.done && String(n.at || "") > seen);

    if (unread.length) {
      dot.hidden = false;
      dot.textContent = unread.length > 9 ? "9+" : String(unread.length);
      wrap.classList.add("has-unread");
    }

    list.innerHTML = notes.length
      ? notes.slice(0, 12).map(n => {
          const isNew = !n.done && String(n.at || "") > seen;
          return `
            <a class="notif-item${isNew ? " is-new" : ""}${n.done ? " is-done" : ""}"
               href="${n.href || "/homework.html"}">
              <span class="notif-ic notif-ic-${n.kind}">${n.icon || "🔔"}</span>
              <span class="notif-body">
                <b>${escapeHtml(n.title)}</b>
                <em>${escapeHtml(n.body || "")}</em>
              </span>
              <span class="notif-time">${escapeHtml(notifWhen(n.at))}</span>
            </a>`;
        }).join("")
      : `<p class="notif-empty">Nothing new. You're all caught up.</p>`;
  })();
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function mountDmToggle() {
  if (document.querySelector(".dm-toggle")) return;
  const right = document.querySelector(".header-right") || document.querySelector(".header-nav");
  if (!right) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dm-toggle";
  btn.setAttribute("aria-label", "Toggle dark mode");
  const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";
  btn.textContent = isDark() ? "☀️" : "🌙";
  btn.addEventListener("click", () => {
    const dark = !isDark();
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch {}
    btn.textContent = dark ? "☀️" : "🌙";
  });
  right.appendChild(btn);
}

export async function initNavbar() {
  const nav = document.querySelector(".header-nav");
  if (!nav) return;

  initNavToggle(nav);
  mountDmToggle();

  const user = await getUser();

  const right = document.querySelector(".header-right") || nav;

  if (!user) {
    // Signed out: sign-in button goes in header-right (or nav if no right rail).
    if (!document.querySelector(".nav-signin")) {
      const link = document.createElement("a");
      link.href = "/login.html";
      link.className = "btn btn-gold nav-signin";
      link.textContent = "Sign in";
      right.appendChild(link);
    }
    return;
  }

  // Signed in: update dashboard link href for non-student roles.
  document.querySelector(".nav-signin")?.remove();
  const existingDash = nav.querySelector(".nav-dashboard");
  if (existingDash) {
    existingDash.href = user.role === "teacher" ? "/teach"
                      : user.role === "admin"   ? "/admin.html"
                      : user.role === "parent"  ? "/parent-dashboard.html"
                      : "/dashboard.html";
    existingDash.textContent = user.role === "teacher" ? "Teacher portal"
                             : user.role === "admin"   ? "Admin"
                             : user.role === "parent"  ? "Parent portal"
                             : "Dashboard";
  }

  // Homework badge (students only) — badge is appended to the mega-menu item.
  if (user.role === "student") {
    const hw = nav.querySelector(".nav-homework");
    if (hw) refreshHomeworkBadge(hw);
  }

  if (!document.querySelector(".notif-wrap")) mountBell(nav);

  if (document.querySelector(".account-menu")) return;

  const wrap = document.createElement("div");
  wrap.className = "account-menu";
  const AI = {
    dash: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    papers: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>',
    board: '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
    progress: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
    keys: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 9.5h.01M9.5 9.5h.01M13 9.5h.01M16.5 9.5h.01M6.5 13h.01M17.5 13h.01M9 14.5h6"/>',
    moon: '<path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z"/>',
    spark: '<path d="M12 3l2 5.5L20 10l-6 1.5L12 17l-2-5.5L4 10l6-1.5z"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.6 2.6 0 015 .9c0 1.8-2.5 2.2-2.5 3.9M12 17h.01"/>',
    out: '<path d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
  };
  const ic = (k) => `<span class="am-ic" aria-hidden="true"><svg viewBox="0 0 24 24">${AI[k]}</svg></span>`;
  const dashHref = user.role === "teacher" ? "/teach" : user.role === "admin" ? "/admin"
                 : user.role === "parent" ? "/parent-dashboard.html" : "/dashboard.html";
  const PLAN = { free: "Free plan", solo: "Solo plan", three: "3 Subjects plan", all: "All Access" };
  const badge = user.role === "teacher" ? "Teacher" : user.role === "admin" ? "Admin" : user.role === "parent" ? "Parent"
              : PLAN[user.plan] || "Free plan";
  const free = user.role === "student" && (!user.plan || user.plan === "free");
  const avatar = (cls) => user.picture_url
    ? `<img class="account-avatar ${cls}" src="${escapeHtml(user.picture_url)}" alt="" referrerpolicy="no-referrer">`
    : `<span class="account-avatar account-initials ${cls}">${INITIALS(user.name)}</span>`;
  wrap.innerHTML = `
    <button type="button" class="account-trigger" aria-haspopup="menu" aria-expanded="false"
            title="${escapeHtml(user.name || "Account")}" aria-label="Account menu for ${escapeHtml(user.name || "you")}">
      ${avatar("")}
      <span class="account-name">${escapeHtml(user.name?.split(" ")[0] || "Account")}</span>
      <svg viewBox="0 0 12 8" width="11" height="8" aria-hidden="true">
        <path d="M1 1.5 6 6.5 11 1.5" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <div class="account-dropdown" role="menu" aria-label="Account" hidden>
      <div class="am-head">
        ${avatar("am-avatar")}
        <div class="am-who">
          <b>${escapeHtml(user.name || "Your account")}</b>
          <span>${escapeHtml(user.email || "")}</span>
        </div>
        <div class="am-plan-row">
          <span class="am-plan${free ? "" : " is-paid"}">${escapeHtml(badge)}</span>
          ${free ? '<a class="am-up" href="/pricing.html" role="menuitem">Upgrade →</a>' : ""}
        </div>
      </div>
      <div class="am-group">
        <a href="${dashHref}" role="menuitem">${ic("dash")}<span>Dashboard</span></a>
        ${user.role === "student" ? `<a href="/my-papers" role="menuitem">${ic("papers")}<span>My papers</span></a>` : ""}
        <a href="/whiteboard" role="menuitem">${ic("board")}<span>Whiteboard</span></a>
        ${user.role === "student" ? `<a href="/topical-progress.html" role="menuitem">${ic("progress")}<span>My progress</span></a>` : ""}
      </div>
      <div class="am-group">
        <a href="/profile.html" role="menuitem">${ic("user")}<span>Profile &amp; settings</span></a>
        <button type="button" class="am-theme" role="menuitemcheckbox" aria-checked="false">${ic("moon")}<span>Dark mode</span><i class="am-switch" aria-hidden="true"></i></button>
        <button type="button" data-shortcuts role="menuitem">${ic("keys")}<span>Keyboard shortcuts</span><kbd>?</kbd></button>
        <a href="/features" role="menuitem">${ic("spark")}<span>What's new</span><em class="am-new">New</em></a>
        <button type="button" data-support="home" role="menuitem">${ic("help")}<span>Help &amp; support</span></button>
      </div>
      <button type="button" class="account-logout" role="menuitem">${ic("out")}<span>Sign out</span></button>
    </div>`;
  right.appendChild(wrap);
  // a profile photo that won't load (expired Google link) falls back to initials, not a broken icon
  wrap.querySelectorAll("img.account-avatar").forEach((img) => img.addEventListener("error", (e) => {
    const s = document.createElement("span");
    s.className = `${e.target.className} account-initials`;
    s.textContent = INITIALS(user.name);
    e.target.replaceWith(s);
  }, { once: true }));

  const trigger = wrap.querySelector(".account-trigger");
  const drop = wrap.querySelector(".account-dropdown");
  const items = () => [...drop.querySelectorAll('[role^="menuitem"]')];
  const themeBtn = drop.querySelector(".am-theme");
  const paintTheme = () => themeBtn.setAttribute("aria-checked",
    String(document.documentElement.getAttribute("data-theme") === "dark"));
  const setOpen = (open, focus = false) => {
    drop.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
    if (open) { paintTheme(); if (focus) items()[0]?.focus(); }
  };

  trigger.addEventListener("click", e => {
    e.stopPropagation();
    setOpen(drop.hidden, e.detail === 0);                 // keyboard-opened: focus the first item
  });
  trigger.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true, true); }
  });
  drop.addEventListener("click", e => e.stopPropagation());
  drop.addEventListener("keydown", e => {
    const list = items(), i = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
    else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
    else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
    else if (e.key === "Tab") setOpen(false);
  });
  themeBtn.addEventListener("click", () => {
    // set it here (clicking the header's toggle would bubble a click that closes this menu)
    const dark = document.documentElement.getAttribute("data-theme") !== "dark";
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch {}
    const btn = document.querySelector(".dm-toggle");
    if (btn) btn.textContent = dark ? "☀️" : "🌙";
    paintTheme();
  });
  drop.querySelector("[data-shortcuts]").addEventListener("click", () => setOpen(false));
  // the dropdown stops clicks bubbling, so open the help centre here (loading it if this page hasn't)
  drop.querySelector("[data-support]").addEventListener("click", () => {
    setOpen(false);
    if (window.pwtSupport) return window.pwtSupport.open("home");
    const s = document.createElement("script");
    s.src = "/support.js?v=20261009a";
    s.onload = () => window.pwtSupport && window.pwtSupport.open("home");
    document.head.appendChild(s);
  });
  document.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !drop.hidden) { setOpen(false); trigger.focus(); }
  });
  wrap.querySelector(".account-logout").addEventListener("click", logout);

  // Active time spent tracking for students
  if (user && user.role === "student") {
    // the student's own calendar day, so streaks roll over at THEIR midnight
    const localDay = () => { const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
    let activeSeconds = 0;
    let isTabActive = true;

    document.addEventListener("visibilitychange", () => {
      isTabActive = !document.hidden;
    });
    window.addEventListener("focus", () => { isTabActive = true; });
    window.addEventListener("blur", () => { isTabActive = false; });

    setInterval(() => {
      if (isTabActive) {
        activeSeconds++;
        if (activeSeconds >= 30) {
          fetch("/api/time-spent", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ seconds: 30, day: localDay() }),
            keepalive: true
          }).catch(() => {});
          activeSeconds = 0;
        }
      }
    }, 1000);

    window.addEventListener("pagehide", () => {
      if (activeSeconds > 0) {
        // as JSON: a bare string beacon is text/plain, which the API rejected (422)
        navigator.sendBeacon("/api/time-spent", new Blob(
          [JSON.stringify({ seconds: activeSeconds, day: localDay() })], { type: "application/json" }));
      }
    });
  }

  // Mount the "Get Started" checklist panel (lazy import — no cost on sign-out pages)
  import("/onboarding-panel.js")
    .then(m => m.mountOnboarding(user))
    .catch(() => {});
}

/* Auto-wire the navbar on every page that loads this module. `currentScript`
   is always null inside an ES module, so there is no opt-in attribute to
   read - importing auth.js is itself the opt-in. */
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initNavbar);
} else {
  initNavbar();
}

export function showAuthRequiredModal({ heading, text, nextUrl, container }) {
  const containerEl = typeof container === "string" ? document.querySelector(container) : container;
  if (!containerEl) return;

  if (containerEl.querySelector(".lib-auth-wall")) return;

  let next = nextUrl;
  if (!next) {
    next = location.pathname + location.search;
  }
  const nextEncoded = encodeURIComponent(next);

  const authWall = document.createElement("div");
  authWall.className = "lib-auth-wall";
  authWall.style.position = "absolute";
  authWall.style.inset = "0";
  authWall.style.zIndex = "100";
  authWall.style.minHeight = "auto";
  authWall.style.display = "flex";
  authWall.style.alignItems = "center";
  authWall.style.justifyContent = "center";

  authWall.innerHTML = `
    <div class="lib-auth-blur" aria-hidden="true" style="opacity: 0.8; filter: blur(8px);">
      ${Array.from({length: 12}, (_, i) =>
        `<span class="lib-auth-line" style="width:${55+Math.sin(i*1.7)*30}%"></span>`
      ).join("")}
    </div>
    <div class="lib-auth-card" style="box-shadow: 0 10px 40px rgba(0,0,0,0.15); max-width: 380px; width: 90%;">
      <div class="lib-auth-icon">🔒</div>
      <h3>${heading || "Sign in to view papers"}</h3>
      <p>${text || "You need a free PrepWithTee account to access this feature."}</p>
      <a class="btn btn-gold" href="/login.html?next=${nextEncoded}">Sign in</a>
      <a class="btn btn-outline lib-auth-signup" href="/login.html?next=${nextEncoded}&signup=1">Create free account</a>
    </div>
  `;

  if (getComputedStyle(containerEl).position === "static") {
    containerEl.style.position = "relative";
  }

  Array.from(containerEl.children).forEach(child => {
    if (child !== authWall) {
      child.style.filter = "blur(4px)";
      child.style.pointerEvents = "none";
      child.style.opacity = "0.6";
    }
  });

  containerEl.appendChild(authWall);
}

if (typeof window !== "undefined") {
  window.showAuthRequiredModal = showAuthRequiredModal;
}

// The pen button on every non-PDF page (scratch ink, never saved).
import("/scratch-pen.js?v=20261009t").catch(() => {});
import("/whats-new.js?v=20261005a").catch(() => {});        // feature spotlight + rail coach mark
