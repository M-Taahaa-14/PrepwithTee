/**
 * PrepWithTee upgrade modal + quota enforcement.
 *
 * Usage:
 *   import { interceptFetch, showUpgradeModal, initUsageMeter } from '/upgrade-modal.js';
 *   interceptFetch();          // wraps fetch() to auto-show modal on 403/429
 *   initUsageMeter('#meter');  // renders usage bars into a container
 */

const PLAN_ORDER  = ["free", "solo", "three", "all"];
const PLAN_LABELS = { free: "Free", solo: "Solo", three: "3 Subjects", all: "All Subjects" };
const PLAN_PRICES = { free: "Free forever", solo: "PKR 1,000/mo", three: "PKR 2,000/mo", all: "PKR 3,000/mo" };

const EVENT_LABELS = {
  topical_paper: "Topical papers",
  yearly_paper:  "Yearly papers",
  ai_quiz:       "AI practice quizzes",
  ai_tutor:      "AI tutor questions",
  topic_test:    "Topic tests",
};

const PLAN_LIMITS = {
  topical_paper: { free: 5,  solo: null, three: null, all: null },
  yearly_paper:  { free: 3,  solo: null, three: null, all: null },
  ai_quiz:       { free: 2,  solo: null, three: null, all: null },
  ai_tutor:      { free: 5,  solo: null, three: null, all: null },
  topic_test:    { free: 3,  solo: null, three: null, all: null },
};

// ── CSS ──────────────────────────────────────────────────────────────────────

const _css = `
  #pwt-upgrade-backdrop {
    position: fixed; inset: 0; background: rgba(26,10,46,.55);
    z-index: 9000; display: flex; align-items: center; justify-content: center;
    padding: 16px; animation: fadeIn .18s ease;
  }
  @keyframes fadeIn { from { opacity:0 } to { opacity:1 } }
  #pwt-upgrade-modal {
    background: #F8F4EE; border-radius: 20px; padding: 36px 32px 28px;
    max-width: 520px; width: 100%; box-shadow: 0 24px 80px rgba(26,10,46,.25);
    position: relative; font-family: "Hanken Grotesk", sans-serif;
  }
  #pwt-upgrade-modal h2 { font-size: 1.45rem; color: #2E1B4A; margin: 0 0 6px; }
  #pwt-upgrade-modal p.sub { color: #5C5069; margin: 0 0 24px; font-size: .95rem; }
  .pwt-plans { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }
  .pwt-plan {
    border: 2px solid #E8DFCE; border-radius: 14px; padding: 16px 14px;
    background: #fff; cursor: pointer; transition: border-color .15s, box-shadow .15s;
  }
  .pwt-plan.current { border-color: #C9BDF0; background: #F0ECFC; }
  .pwt-plan.target  { border-color: #C9A44E; box-shadow: 0 0 0 3px rgba(201,164,78,.2); }
  .pwt-plan .pl-name { font-weight: 700; font-size: 1rem; color: #2E1B4A; }
  .pwt-plan .pl-price { font-size: .82rem; color: #857E93; margin: 2px 0 10px; }
  .pwt-plan .pl-badge {
    display: inline-block; font-size: .72rem; font-weight: 700;
    padding: 2px 8px; border-radius: 99px;
    background: #C9BDF0; color: #4A2E8F; margin-bottom: 8px;
  }
  .pwt-plan .pl-badge.current-badge { background: #C9BDF0; color: #4A2E8F; }
  .pwt-plan .pl-badge.target-badge  { background: #C9A44E; color: #fff; }
  .pwt-plan-cta {
    width: 100%; padding: 12px; border-radius: 10px; border: 0;
    font: 700 .93rem "Hanken Grotesk", sans-serif; cursor: pointer;
    background: linear-gradient(135deg, #C9A44E, #f0c040);
    color: #2E1B4A; transition: opacity .15s, transform .15s;
  }
  .pwt-plan-cta:hover { opacity: .88; transform: translateY(-1px); }
  .pwt-modal-close {
    position: absolute; top: 14px; right: 16px; background: none; border: 0;
    font-size: 1.4rem; color: #857E93; cursor: pointer; line-height: 1;
  }
  .pwt-modal-close:hover { color: #2E1B4A; }
  /* Usage meter bars */
  .pwt-usage-bar-wrap { margin: 8px 0; }
  .pwt-usage-label { display: flex; justify-content: space-between;
    font-size: .82rem; color: #5C5069; margin-bottom: 4px; }
  .pwt-usage-track { height: 7px; border-radius: 99px; background: #E8DFCE; overflow: hidden; }
  .pwt-usage-fill { height: 100%; border-radius: 99px;
    background: linear-gradient(90deg, #C9A44E, #f0c040); transition: width .4s ease; }
  .pwt-usage-fill.full { background: #D44; }
  /* Locked feature overlay */
  .pwt-locked { position: relative; }
  .pwt-locked > * { pointer-events: none; opacity: .42; user-select: none; filter: blur(1px); }
  .pwt-lock-chip {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    z-index: 2;
  }
  .pwt-lock-chip button {
    background: linear-gradient(135deg, #C9A44E, #f0c040); color: #2E1B4A;
    border: 0; border-radius: 8px; padding: 7px 16px;
    font: 700 .85rem "Hanken Grotesk", sans-serif; cursor: pointer;
    box-shadow: 0 4px 14px rgba(201,164,78,.35);
  }
  .pwt-lock-chip button:hover { opacity: .9; }
`;

function _injectStyles() {
  if (document.getElementById("pwt-upgrade-styles")) return;
  const s = document.createElement("style");
  s.id = "pwt-upgrade-styles";
  s.textContent = _css;
  document.head.appendChild(s);
}

// ── Modal ─────────────────────────────────────────────────────────────────────

let _currentPlan = "free";
let _currentRole = "student";

export function setPlan(plan) { _currentPlan = plan; }
export function setRole(role) { _currentRole = role || "student"; }
function _isPrivileged() { return _currentRole === "teacher" || _currentRole === "admin"; }

export function showUpgradeModal({ minPlan = "pro", message = null } = {}) {
  if (_isPrivileged()) return;   // teachers/admins never see the upgrade wall
  _injectStyles();
  const existing = document.getElementById("pwt-upgrade-backdrop");
  if (existing) existing.remove();

  const backdrop = document.createElement("div");
  backdrop.id = "pwt-upgrade-backdrop";

  const targetPlans = PLAN_ORDER.filter(p =>
    PLAN_ORDER.indexOf(p) >= PLAN_ORDER.indexOf(minPlan) &&
    p !== "free"
  );

  const plansHtml = targetPlans.map(plan => {
    const isCurrent = plan === _currentPlan;
    const isTarget  = plan === minPlan;
    return `
      <div class="pwt-plan ${isCurrent ? "current" : ""} ${isTarget ? "target" : ""}">
        ${isCurrent ? `<div class="pl-badge current-badge">Your plan</div>` :
          isTarget ? `<div class="pl-badge target-badge">Recommended</div>` : ""}
        <div class="pl-name">${PLAN_LABELS[plan]}</div>
        <div class="pl-price">${PLAN_PRICES[plan]}</div>
        ${!isCurrent ? `<button class="pwt-plan-cta" data-plan="${plan}">
          Upgrade to ${plan.charAt(0).toUpperCase() + plan.slice(1)}</button>` :
          `<div style="font-size:.82rem;color:#857E93;margin-top:4px;">Current plan</div>`}
      </div>`;
  }).join("");

  backdrop.innerHTML = `
    <div id="pwt-upgrade-modal">
      <button class="pwt-modal-close" id="pwt-modal-close-btn" aria-label="Close">×</button>
      <h2>Upgrade your plan</h2>
      <p class="sub">${message || "This feature isn't available on your current plan."}</p>
      <div class="pwt-plans">${plansHtml}</div>
    </div>`;

  document.body.appendChild(backdrop);
  document.getElementById("pwt-modal-close-btn").onclick = () => backdrop.remove();
  backdrop.addEventListener("click", e => { if (e.target === backdrop) backdrop.remove(); });
  backdrop.querySelectorAll(".pwt-plan-cta[data-plan]").forEach(btn => {
    btn.addEventListener("click", () => {
      window.location.href = "/pricing.html";
    });
  });
}

// ── Fetch interceptor ────────────────────────────────────────────────────────

let _interceptActive = false;

export function interceptFetch() {
  if (_interceptActive) return;
  _interceptActive = true;
  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await _origFetch.apply(this, args);
    if (!_isPrivileged() && (res.status === 403 || res.status === 429)) {
      const clone = res.clone();
      try {
        const data = await clone.json();
        const detail = data.detail || {};
        if (detail.code === "upgrade_required" || detail.code === "quota_exceeded") {
          showUpgradeModal({
            minPlan: detail.min_plan || "pro",
            message: detail.message || null,
          });
        }
      } catch (_) {}
    }
    return res;
  };
}

// ── Usage meter ──────────────────────────────────────────────────────────────

export async function initUsageMeter(containerSelector) {
  _injectStyles();
  const container = document.querySelector(containerSelector);
  if (!container) return;

  let data;
  try {
    const res = await fetch("/api/usage");
    if (!res.ok) return;
    data = await res.json();
  } catch (_) { return; }

  _currentPlan = data.plan || "free";

  const bars = Object.entries(data.usage)
    .filter(([, u]) => !u.unlimited)
    .map(([type, u]) => {
      const pct = u.limit ? Math.min(100, Math.round(u.used / u.limit * 100)) : 0;
      const full = u.used >= u.limit;
      return `
        <div class="pwt-usage-bar-wrap">
          <div class="pwt-usage-label">
            <span>${EVENT_LABELS[type] || type}</span>
            <span>${u.used}/${u.limit}</span>
          </div>
          <div class="pwt-usage-track">
            <div class="pwt-usage-fill${full ? " full" : ""}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join("");

  container.innerHTML = bars || "";
}

// ── Lock overlay helper ──────────────────────────────────────────────────────

/**
 * Wrap el (or querySelector result) in a locked overlay.
 * The overlay shows an "Upgrade" chip that opens the modal.
 *
 * Usage:
 *   lockElement(document.querySelector('.quiz-section'), { minPlan: 'pro',
 *     message: 'Upgrade to Pro to use AI quizzes.' });
 */
export function lockElement(el, { minPlan = "pro", label = "Upgrade to unlock", message = null } = {}) {
  if (!el) return;
  _injectStyles();
  el.classList.add("pwt-locked");
  const chip = document.createElement("div");
  chip.className = "pwt-lock-chip";
  chip.innerHTML = `<button>${label} →</button>`;
  chip.querySelector("button").addEventListener("click", () =>
    showUpgradeModal({ minPlan, message }));
  el.appendChild(chip);
}
