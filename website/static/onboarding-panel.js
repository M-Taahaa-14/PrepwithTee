/* onboarding-panel.js — "Get Started" checklist panel + ? help button.
 *
 * Exported: mountOnboarding(user)  — called from auth.js after sign-in.
 *
 * The ? button sits in the nav next to the notification bell. The panel is a
 * fixed bottom-right card listing the six major platform areas. Clicking
 * "Explore →" marks that area explored and navigates to it (with ?tour=1 so
 * page walkthroughs auto-trigger once they're built in Phase C).
 */

import { getAllFlags, setFlag } from "/onboarding.js";

// ── Checklist definition ──────────────────────────────────────────────────────

const ITEMS = [
  {
    key:   "dashboard",
    icon:  "📊",
    title: "Dashboard",
    desc:  "Your progress rings, weekly streak, and scheduled work at a glance.",
    href:  "/dashboard.html",
  },
  {
    key:   "revise",
    icon:  "📖",
    title: "Chapter Tracker",
    desc:  "Mark topics as learning or confident — chapter by chapter.",
    href:  "/topical-progress.html",
  },
  {
    key:   "papers",
    icon:  "📄",
    title: "Topical Past Papers",
    desc:  "Build filtered practice sets from real Cambridge past papers.",
    href:  "/papers",
  },
  {
    key:   "ask",
    icon:  "🤖",
    title: "AI Tutor",
    desc:  "Ask any exam question and get an instant, detailed explanation.",
    href:  "/ask.html",
  },
  {
    key:   "resources",
    icon:  "📚",
    title: "Resources",
    desc:  "Notes, command words, formula sheets, and revision guides.",
    href:  "/resources",
  },
  {
    key:   "tools",
    icon:  "🧮",
    title: "Study Tools",
    desc:  "Calculator, graph plotter, periodic table, and more.",
    href:  "/formulas.html",
  },
];

const FLAG = key => "tour_" + key;

// ── Module state ──────────────────────────────────────────────────────────────

let _user = null;
let _panel = null;
let _helpBtn = null;
let _open = false;

// ── Public entry point ────────────────────────────────────────────────────────

export function mountOnboarding(user) {
  if (!user) return;
  _user = user;
  /* Nav ? button removed at tutor's request 2026-08-24.
     Panel is still available via openOnboarding() if wired elsewhere. */
}

// ── ? Help button ─────────────────────────────────────────────────────────────

function _mountHelpButton() {
  const nav = document.querySelector(".header-nav");
  if (!nav || nav.querySelector(".ob-help-btn")) return;

  _helpBtn = document.createElement("button");
  _helpBtn.type = "button";
  _helpBtn.className = "ob-help-btn";
  _helpBtn.setAttribute("aria-label", "Get Started — onboarding checklist");
  _helpBtn.title = "Get Started";
  _helpBtn.innerHTML = `
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"
         fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
      <circle cx="12" cy="17" r=".5" fill="currentColor" stroke="none"/>
    </svg>`;

  // Insert before the notification bell, or append if bell isn't mounted yet
  const notifWrap = nav.querySelector(".notif-wrap");
  if (notifWrap) nav.insertBefore(_helpBtn, notifWrap);
  else nav.appendChild(_helpBtn);

  _helpBtn.addEventListener("click", e => {
    e.stopPropagation();
    _open ? _closePanel() : _openPanel();
  });
}

// ── Panel ─────────────────────────────────────────────────────────────────────

function _buildPanel() {
  const flags = getAllFlags(_user);
  const explored = ITEMS.filter(it => flags[FLAG(it.key)]).length;
  const total = ITEMS.length;
  const pct = Math.round((explored / total) * 100);
  const allDone = explored === total;

  const el = document.createElement("div");
  el.className = "ob-panel";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "Get Started checklist");
  el.innerHTML = `
    <div class="ob-panel-head">
      <span class="ob-panel-title">Get Started</span>
      <button type="button" class="ob-close" aria-label="Close">&times;</button>
    </div>
    <div class="ob-panel-progress">
      <div class="ob-progress-label">
        ${allDone
          ? `<b>All done!</b> You've explored everything 🎉`
          : `<b>${explored} of ${total}</b> areas explored`}
      </div>
      <div class="ob-progress-track" role="progressbar"
           aria-valuenow="${explored}" aria-valuemax="${total}"
           aria-label="${explored} of ${total} explored">
        <div class="ob-progress-fill" style="width:${pct}%"></div>
      </div>
    </div>
    <ul class="ob-list" role="list">
      ${ITEMS.map(item => _itemHTML(item, flags)).join("")}
    </ul>
    <div class="ob-panel-foot">
      <button type="button" class="ob-btn-ghost ob-dismiss">Remind me later</button>
      <a href="/walkthrough.html" class="ob-btn-outline">Full guide →</a>
    </div>`;

  el.querySelector(".ob-close").addEventListener("click", _closePanel);
  el.querySelector(".ob-dismiss").addEventListener("click", () => {
    setFlag(_user, "onboarding_dismissed", true);
    _closePanel();
  });

  el.querySelectorAll(".ob-explore-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.key;
      setFlag(_user, FLAG(key), true);
      const item = ITEMS.find(i => i.key === key);
      if (item) location.href = item.href + "?tour=1";
    });
  });

  return el;
}

function _itemHTML(item, flags) {
  const done = !!flags[FLAG(item.key)];
  return `
    <li class="ob-item${done ? " ob-item-done" : ""}" role="listitem">
      <span class="ob-item-icon" aria-hidden="true">${item.icon}</span>
      <div class="ob-item-body">
        <b class="ob-item-title">${item.title}</b>
        <span class="ob-item-desc">${item.desc}</span>
      </div>
      ${done
        ? `<span class="ob-check" aria-label="Explored" title="Explored">✓</span>`
        : `<button type="button" class="ob-explore-btn" data-key="${item.key}"
                   aria-label="Explore ${item.title}">
             Explore →
           </button>`}
    </li>`;
}

function _openPanel() {
  if (_panel) _panel.remove();
  _panel = _buildPanel();
  document.body.appendChild(_panel);
  _open = true;

  requestAnimationFrame(() => {
    requestAnimationFrame(() => _panel?.classList.add("ob-panel-visible"));
  });

  setTimeout(() => {
    document.addEventListener("click", _onDocClick);
    document.addEventListener("keydown", _onDocKey);
  }, 0);
}

function _closePanel() {
  if (!_panel) return;
  _panel.classList.remove("ob-panel-visible");
  _open = false;
  setTimeout(() => { _panel?.remove(); _panel = null; }, 240);
  document.removeEventListener("click", _onDocClick);
  document.removeEventListener("keydown", _onDocKey);
}

function _onDocClick(e) {
  if (_panel && !_panel.contains(e.target) && e.target !== _helpBtn) _closePanel();
}

function _onDocKey(e) {
  if (e.key === "Escape") _closePanel();
}
