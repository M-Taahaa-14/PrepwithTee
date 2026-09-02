/**
 * persona-quiz.js — First-visit "Who are you?" overlay.
 *
 * Shows a full-screen modal on the very first visit (localStorage key absent).
 * Three persona cards: Student / Teacher / Parent.
 *
 * - Choice is stored immediately in localStorage so repeat visits skip the quiz.
 * - If the user is signed in, the choice is also persisted to the DB so it
 *   survives across devices and flows into the JWT on the next login.
 * - The homepage hero copy swaps instantly via data attributes on the hero
 *   element; other pages just get the localStorage entry for their own use.
 *
 * Import this module on any page you want the quiz to appear on:
 *   <script type="module" src="/persona-quiz.js?v=..."></script>
 * It self-initialises on import.
 */

const STORAGE_KEY = "pwt_persona";

const PERSONAS = [
  {
    id: "student",
    emoji: "🎓",
    label: "I'm a student",
    desc: "I want to practise past papers and improve my Cambridge grades.",
    color: "#2563eb",
  },
  {
    id: "teacher",
    emoji: "📚",
    label: "I'm a teacher",
    desc: "I want to teach and grow my tutoring practice with PrepWithTee.",
    color: "#059669",
  },
  {
    id: "parent",
    emoji: "👪",
    label: "I'm a parent",
    desc: "My child needs expert Cambridge exam support.",
    color: "#c2410c",
  },
];

/* ── Hero copy swapped per persona ────────────────────────────────────────── */
const HERO_COPY = {
  student: {
    headline: "Every Cambridge past paper. Organised by topic.",
    sub: "Physics, Maths and Computer Science — sorted by chapter, not by year, so you revise what matters.",
    cta: "Start practising free",
    ctaHref: "/login.html",
  },
  teacher: {
    headline: "Grow your tutoring practice with a ready-made student base.",
    sub: "Join PrepWithTee's teacher team and get matched with motivated Cambridge students in Lahore.",
    cta: "Apply to teach",
    ctaHref: "/teacher-apply.html",
  },
  parent: {
    headline: "Expert Cambridge tutoring, with full progress visibility.",
    sub: "Your child practises real past papers under a qualified teacher. You see every session and every result.",
    cta: "Book a free demo",
    ctaHref: "https://wa.me/923204884375?text=Hi%21+I%27d+like+to+book+a+free+demo+lesson.",
  },
};

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function getStored() {
  try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
}

function setStored(persona) {
  try { localStorage.setItem(STORAGE_KEY, persona); } catch { /* private mode */ }
}

async function persistToServer(persona) {
  try {
    await fetch("/api/profile/persona", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona }),
    });
  } catch { /* not signed in or offline — localStorage is sufficient */ }
}

/* ── Hero swap ─────────────────────────────────────────────────────────────── */

export function applyPersonaHero(persona) {
  const copy = HERO_COPY[persona];
  if (!copy) return;

  const hl = document.querySelector("[data-persona-headline]");
  const sub = document.querySelector("[data-persona-sub]");
  const cta = document.querySelector("[data-persona-cta]");

  if (hl) hl.textContent = copy.headline;
  if (sub) sub.textContent = copy.sub;
  if (cta) {
    cta.textContent = copy.cta;
    cta.href = copy.ctaHref;
  }
}

/* ── Modal ─────────────────────────────────────────────────────────────────── */

function buildModal() {
  const cards = PERSONAS.map(p => `
    <button class="pq-card" data-persona="${p.id}"
            style="--pq-accent:${p.color}"
            aria-label="${p.label}">
      <span class="pq-icon">${p.emoji}</span>
      <strong class="pq-label">${p.label}</strong>
      <span class="pq-desc">${p.desc}</span>
    </button>`).join("");

  const el = document.createElement("div");
  el.id = "persona-quiz";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-label", "Tell us who you are");
  el.innerHTML = `
    <div class="pq-backdrop"></div>
    <div class="pq-panel">
      <div class="pq-logo">
        <img src="/logo.png" alt="PrepWithTee" width="48" height="48">
        <span>PrepWith<b>Tee</b></span>
      </div>
      <h2 class="pq-heading">Who are you here as?</h2>
      <p class="pq-sub">We'll personalise your experience — you can always change this later.</p>
      <div class="pq-grid">${cards}</div>
    </div>`;
  return el;
}

const STYLE = `
  #persona-quiz {
    position: fixed; inset: 0; z-index: 9000;
    display: flex; align-items: center; justify-content: center;
    padding: 16px;
    font-family: 'Hanken Grotesk', system-ui, sans-serif;
  }
  .pq-backdrop {
    position: absolute; inset: 0;
    background: rgba(10,14,30,.72);
    backdrop-filter: blur(4px);
    animation: pq-fade-in .2s ease;
  }
  .pq-panel {
    position: relative;
    background: #fff; border-radius: 20px;
    padding: 40px 36px 36px;
    max-width: 580px; width: 100%;
    box-shadow: 0 24px 60px rgba(0,0,0,.22);
    animation: pq-slide-up .25s cubic-bezier(.22,1,.36,1);
    text-align: center;
  }
  .pq-logo {
    display: flex; align-items: center; justify-content: center;
    gap: 10px; margin-bottom: 24px;
    font-size: 1.15rem; font-weight: 800; color: #1a2340;
  }
  .pq-logo img { border-radius: 8px; }
  .pq-logo b { color: #c9a227; }
  .pq-heading {
    font-size: clamp(1.4rem, 4vw, 1.8rem); font-weight: 800;
    color: #1a2340; margin-bottom: 10px; line-height: 1.2;
  }
  .pq-sub { font-size: .88rem; color: #6b7280; margin-bottom: 28px; }
  .pq-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  @media (max-width: 500px) { .pq-grid { grid-template-columns: 1fr; } }
  .pq-card {
    display: flex; flex-direction: column; align-items: center;
    gap: 8px; padding: 20px 14px;
    background: #f9fafb; border: 2px solid #e5e7eb; border-radius: 14px;
    cursor: pointer; transition: border-color .15s, box-shadow .15s, transform .12s;
    font-family: inherit; text-align: center;
  }
  .pq-card:hover {
    border-color: var(--pq-accent);
    box-shadow: 0 4px 20px rgba(0,0,0,.1);
    transform: translateY(-2px);
  }
  .pq-card:focus-visible {
    outline: 2px solid var(--pq-accent); outline-offset: 2px;
  }
  .pq-icon { font-size: 2rem; line-height: 1; }
  .pq-label {
    font-size: .9rem; font-weight: 700; color: #1a2340; display: block;
  }
  .pq-desc { font-size: .75rem; color: #6b7280; line-height: 1.45; }
  @keyframes pq-fade-in { from { opacity: 0; } to { opacity: 1; } }
  @keyframes pq-slide-up {
    from { opacity: 0; transform: translateY(24px) scale(.97); }
    to   { opacity: 1; transform: none; }
  }
`;

/* ── Init ──────────────────────────────────────────────────────────────────── */

function init() {
  const existing = getStored();

  // Already answered — just apply hero copy and exit.
  if (existing) {
    applyPersonaHero(existing);
    return;
  }

  // Inject styles once.
  if (!document.getElementById("persona-quiz-style")) {
    const s = document.createElement("style");
    s.id = "persona-quiz-style";
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  const modal = buildModal();
  document.body.appendChild(modal);

  // Trap focus inside the panel.
  const panel = modal.querySelector(".pq-panel");
  const firstBtn = panel.querySelector(".pq-card");
  firstBtn?.focus();

  modal.querySelectorAll(".pq-card").forEach(btn => {
    btn.addEventListener("click", () => choose(btn.dataset.persona));
  });
}

async function choose(persona) {
  setStored(persona);
  applyPersonaHero(persona);

  // Animate out.
  const modal = document.getElementById("persona-quiz");
  if (modal) {
    modal.style.transition = "opacity .2s";
    modal.style.opacity = "0";
    setTimeout(() => modal.remove(), 220);
  }

  // Persist to DB if the user happens to be signed in.
  await persistToServer(persona);
}

// Self-initialise after DOM is ready.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
