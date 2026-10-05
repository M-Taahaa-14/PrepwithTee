/* whats-new.js — tell students about features they haven't found.
 *
 * Most students only use topical papers (tutor, 2026-10-05). Two nudges, each
 * shown ONCE per browser (localStorage "pwt-wn"), never both on one page:
 *   spotlight  a card bottom-left announcing the newest thing (ANNOUNCEMENTS[0])
 *              with "Try it" and "See everything" (/features);
 *   coach      on a paper viewer, a bubble beside the annotation rail the first
 *              time it appears ("your pen tools are here now").
 * Loaded by auth.js on every page; quiet on the pages the news is about.
 * Keep the wording in step with website/features.py NEW.
 */
const KEY = "pwt-wn";
const ANNOUNCEMENTS = [
  { id: "board-2026-10", emoji: "🖊️", title: "New: your own whiteboard",
    text: "Work questions out on lined, squared or graph paper - or an infinite canvas - with real pens, a compass and stickers. Saved to your account, exported as PDF.",
    cta: "Try the whiteboard", url: "/whiteboard" },
  { id: "instagram-2026-10", emoji: "📸", title: "Follow us on Instagram",
    text: "Daily exam tips, past-paper tricks, grade boundaries and results - follow @prepwithtee so you never miss one.",
    cta: "Follow @prepwithtee", url: "https://www.instagram.com/prepwithtee/", external: true },
];
const QUIET = /^\/(whiteboard|features|login|admin|set-password|reset-password|forgot-password)/;

function seen() { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } }
function mark(id) { try { localStorage.setItem(KEY, JSON.stringify({ ...seen(), [id]: Date.now() })); } catch { /* ignore */ } }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function spotlight(a) {
  const el = document.createElement("aside");
  el.className = "wn-card";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", a.title);
  el.innerHTML = `<button type="button" class="wn-x" aria-label="Dismiss">×</button>
    <span class="wn-emoji" aria-hidden="true">${a.emoji}</span>
    <div class="wn-body"><p class="wn-eyebrow">What's new</p><b>${esc(a.title)}</b><p>${esc(a.text)}</p>
      <div class="wn-acts"><a class="wn-btn" href="${a.url}" data-go ${a.external ? 'target="_blank" rel="noopener"' : ""}>${esc(a.cta)}</a>
        <a class="wn-link" href="/features" data-go>See everything you can do →</a></div></div>`;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("is-on"));
  const close = () => { mark(a.id); el.classList.remove("is-on"); setTimeout(() => el.remove(), 250); };
  el.querySelector(".wn-x").addEventListener("click", close);
  el.querySelectorAll("[data-go]").forEach((x) => x.addEventListener("click", () => mark(a.id)));
}

function coach(rail) {
  const r = rail.getBoundingClientRect();
  const el = document.createElement("div");
  el.className = "wn-coach";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-label", "New pen tools");
  el.innerHTML = `<b>✏️ Your pen tools are here now</b>
    <p>Pens, highlighter, shapes, sticky notes, stickers, images - plus a ruler, protractor and a <b>compass</b>.
      Hold a tool (or tap it twice) for its options; the pin keeps the bar open.</p>
    <div class="wn-acts"><button type="button" class="wn-btn" data-ok>Got it</button>
      <a class="wn-link" href="/features#new" data-ok>What else is new →</a></div>`;
  document.body.appendChild(el);
  el.style.left = `${Math.round(r.right + 14)}px`;
  el.style.top = `${Math.round(Math.min(window.innerHeight - el.offsetHeight - 12, r.top + 60))}px`;
  requestAnimationFrame(() => el.classList.add("is-on"));
  const close = () => { mark("coach-rail"); el.remove(); };
  el.querySelectorAll("[data-ok]").forEach((x) => x.addEventListener("click", close));
  document.addEventListener("keydown", function k(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", k); } });
}

function start() {
  if (QUIET.test(location.pathname) || window.__pwtWhatsNew) return;
  window.__pwtWhatsNew = true;
  const s = seen();
  // a paper viewer: the rail appears once the paper loads
  if (document.getElementById("vw") || document.getElementById("mq")) {
    if (s["coach-rail"]) return;
    let tries = 0;
    const t = setInterval(() => {
      const rail = document.querySelector(".ink-rail:not([hidden])");
      if (rail && rail.getBoundingClientRect().width) { clearInterval(t); setTimeout(() => coach(rail), 900); }
      else if (++tries > 40) clearInterval(t);
    }, 500);
    return;
  }
  // one card per visit; the next announcement waits at least a day after the last one was seen
  const last = Math.max(0, ...ANNOUNCEMENTS.map((x) => s[x.id] || 0));
  const a = Date.now() - last > 20 * 3600 * 1000 ? ANNOUNCEMENTS.find((x) => !s[x.id]) : null;
  if (a) setTimeout(() => spotlight(a), 2500);      // after the page has settled
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
