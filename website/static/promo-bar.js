/* promo-bar.js - the current campaign, shown two ways:
 *
 *   bar   a slim strip above the site header on every page (closed = gone for
 *         this campaign, in this browser);
 *   card  a bigger slide-in card (bottom-left; a bottom sheet on phones) with a
 *         countdown, both prices and the WhatsApp button. Closing it hides it for
 *         CARD_SNOOZE_DAYS, then it comes back once more - the bar stays meanwhile.
 *
 * Loaded from partials/nav.html, so every page with the shared header gets it
 * (static pages via sync_nav.py, SSR pages via blog._nav()). Change PROMO to run
 * a new campaign: a new `id` shows both again to everyone. It switches itself off
 * after `until`, stays quiet on the page it links to and on the app surfaces in
 * QUIET. While the bar shows it stands in for the home page's own static
 * `.announce` strip, and while the card shows the "What's new" card waits (they
 * would sit in the same corner) - and on the course page itself it never shows.
 */
(function () {
  var PROMO = {
    id: "maths-batch-2026-10",
    start: "2026-10-31",
    until: "2026-11-15",                       // last day it shows (late joiners still welcome)
    badge: "New batch",
    text: "Maths, Physics & Computer Science batches start 31 October - O Level & IGCSE from PKR 8,499/month, money-back guarantee.",
    short: "New batches from 31 Oct · from PKR 8,499/mo",
    subjects: [                               // [label, page, A Level courses]
      ["Maths", "/maths-classes.html", "9709 · P1 · P3 · M1 · S1"],
      ["Physics", "/physics-classes.html", "9702 · AS · A2"],
      ["CS", "/cs-classes.html", "9618 · P1 – P4"],
    ],
    wa: "https://wa.me/923204884375?text=Hi%20Tee%21%20I%27d%20like%20to%20book%20a%20free%20demo%20for%20the%20batch%20starting%2031%20October.%20Subject%3A%20",
  };
  var BAR_KEY = "pwt-promo-closed";
  var CARD_KEY = "pwt-promo-card";            // JSON {id, at}
  var CARD_SNOOZE_DAYS = 3;
  var QUIET = /^\/(maths-classes|physics-classes|cs-classes|admin|login|set-password|reset-password|forgot-password|whiteboard\/|papers\/view|yearly\/view|mcq\/session)/;

  if (window.__pwtPromo) return;
  window.__pwtPromo = true;
  if (/^\/(maths|physics|cs)-classes/.test(location.pathname)) window.__pwtWhatsNew = true;  // keep the course page clean
  if (QUIET.test(location.pathname)) return;
  if (new Date() > new Date(PROMO.until + "T23:59:59+05:00")) return;

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }

  var showBar = get(BAR_KEY) !== PROMO.id;
  var showCard = (function () {
    try {
      var c = JSON.parse(get(CARD_KEY) || "null");
      return !c || c.id !== PROMO.id || Date.now() - c.at > CARD_SNOOZE_DAYS * 864e5;
    } catch (e) { return true; }
  })();
  if (!showBar && !showCard) return;
  if (showCard) window.__pwtWhatsNew = true;   // one bottom-left card at a time

  var WA_SVG = '<svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true"><path d="M16 3a13 13 0 0 0-11.2 19.6L3 29l6.6-1.7A13 13 0 1 0 16 3zm5.8 15.7c-.3-.2-1.9-.9-2.2-1-.3-.1-.5-.2-.7.2l-1 1.2c-.2.2-.4.2-.7.1a8.7 8.7 0 0 1-4.3-3.8c-.3-.6.3-.5 1-1.7.1-.2 0-.4 0-.5l-1-2.4c-.3-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.5s1.1 2.9 1.2 3.1c.2.2 2.1 3.2 5.1 4.5 1.9.8 2.6.9 3.6.7.6-.1 1.9-.8 2.1-1.5.3-.7.3-1.4.2-1.5-.1-.1-.3-.2-.6-.3z"/></svg>';

  var CSS =
    ".pwt-promo,.pwt-pc{--pp-a:#2E1B4A;--pp-b:#4C2E72;--pp-ink:#fff;--pp-sub:rgba(255,255,255,.78);--pp-gold:#E8913A;--pp-gold-ink:#2b1606;" +
      "--pp-wa:#25D366;--pp-wa-ink:#06301a;--pp-glass:rgba(255,255,255,.08);--pp-line:rgba(255,255,255,.16)}" +
    /* bar */
    ".pwt-promo{background:linear-gradient(90deg,var(--pp-a),var(--pp-b) 55%,var(--pp-a));color:var(--pp-ink);font:600 .9rem/1.35 'Hanken Grotesk',system-ui,sans-serif;position:relative;z-index:60}" +
    ".pwt-promo-in{max-width:1240px;margin:0 auto;padding:9px 48px 9px 16px;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;text-align:center}" +
    ".pwt-promo-badge{font:800 .7rem/1 Archivo,sans-serif;letter-spacing:.12em;text-transform:uppercase;background:var(--pp-gold);color:var(--pp-gold-ink);padding:5px 9px;border-radius:999px}" +
    ".pwt-promo-links{display:inline-flex;gap:6px;flex-wrap:wrap;justify-content:center}" +
    ".pwt-promo-links a{color:var(--pp-gold-ink);background:var(--pp-gold);font-weight:800;font-size:.8rem;text-decoration:none;white-space:nowrap;padding:4px 10px;border-radius:999px}" +
    ".pwt-promo-links a:hover{filter:brightness(1.08)}" +
    ".pwt-x{position:absolute;width:30px;height:30px;border:0;border-radius:50%;background:transparent;color:var(--pp-ink);opacity:.75;font-size:1.25rem;line-height:1;cursor:pointer}" +
    ".pwt-x:hover,.pwt-x:focus-visible{opacity:1;background:rgba(255,255,255,.14)}" +
    ".pwt-promo .pwt-x{right:10px;top:50%;transform:translateY(-50%)}" +
    ".pwt-promo-short{display:none}" +
    "@media (max-width:720px){.pwt-promo-long{display:none}.pwt-promo-short{display:inline}.pwt-promo{font-size:.84rem}}" +
    /* card */
    ".pwt-pc{position:fixed;left:20px;bottom:20px;z-index:10000;width:min(390px,calc(100vw - 40px));color:var(--pp-ink);font-family:'Hanken Grotesk',system-ui,sans-serif;" +
      "background:radial-gradient(420px 260px at 100% 0,#6B3FA0 0,transparent 70%),linear-gradient(160deg,var(--pp-b),var(--pp-a));border-radius:24px;padding:22px 22px 20px;" +
      "box-shadow:0 24px 60px rgba(20,10,40,.45),inset 0 0 0 1px var(--pp-line);transform:translateY(24px) scale(.98);opacity:0;transition:transform .35s cubic-bezier(.2,.9,.3,1.2),opacity .25s;overflow:hidden}" +
    ".pwt-pc.is-on{transform:none;opacity:1}" +
    ".pwt-pc .pwt-x{right:12px;top:12px}" +
    ".pwt-pc-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-right:30px}" +
    ".pwt-pc-badge{font:800 .68rem/1 Archivo,sans-serif;letter-spacing:.12em;text-transform:uppercase;background:var(--pp-gold);color:var(--pp-gold-ink);padding:6px 9px;border-radius:999px}" +
    ".pwt-pc-count{font:800 .78rem/1 Archivo,sans-serif;color:var(--pp-gold);letter-spacing:.04em}" +
    ".pwt-pc h3{font:900 1.55rem/1.08 'Playfair Display',Georgia,serif;margin:12px 0 4px;color:var(--pp-ink)}" +
    ".pwt-pc h3 em{color:var(--pp-gold);font-style:italic;font-weight:700}" +
    ".pwt-pc-sub{color:var(--pp-sub);font-size:.9rem;line-height:1.45;margin:0}" +
    ".pwt-pc-rows{display:grid;gap:8px;margin:14px 0 12px}" +
    ".pwt-pc-row{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--pp-glass);border:1px solid var(--pp-line);border-radius:14px;padding:10px 12px;color:var(--pp-ink);text-decoration:none;transition:border-color .15s,background .15s}" +
    "a.pwt-pc-row:hover{border-color:var(--pp-gold);background:rgba(255,255,255,.12)}" +
    ".pwt-pc-row .go{color:var(--pp-gold);font-weight:900;font-size:1.1rem}" +
    ".pwt-pc-row b{display:block;font:800 .92rem/1.2 Archivo,sans-serif}" +
    ".pwt-pc-row small{display:block;color:var(--pp-sub);font-size:.76rem;margin-top:2px}" +
    ".pwt-pc-from{color:var(--pp-sub);font-size:.8rem;margin:0 0 10px}.pwt-pc-from b{color:var(--pp-gold)}" +
    ".pwt-pc-guar{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.82rem;background:rgba(232,145,58,.18);border:1px solid rgba(232,145,58,.45);padding:6px 10px;border-radius:999px}" +
    ".pwt-pc-acts{display:flex;gap:8px;margin-top:14px}" +
    ".pwt-pc-acts a{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:7px;border-radius:999px;padding:11px 12px;font-weight:800;font-size:.9rem;text-decoration:none;white-space:nowrap}" +
    ".pwt-pc-acts a:hover{filter:brightness(1.06)}" +
    ".pwt-pc-wa{background:var(--pp-wa);color:var(--pp-wa-ink)}" +
    ".pwt-pc-wa svg{width:17px;height:17px}" +
    "@media (max-width:560px){.pwt-pc{left:10px;right:10px;bottom:10px;width:auto;padding:18px 16px 16px;border-radius:20px}.pwt-pc h3{font-size:1.3rem}.pwt-pc-sub{display:none}}" +
    "@media (prefers-reduced-motion:reduce){.pwt-pc{transition:none}}";

  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; }
  function daysLeft() { return Math.ceil((new Date(PROMO.start + "T00:00:00+05:00") - new Date()) / 864e5); }

  function mountBar(header) {
    var bar = el("div", "pwt-promo",
      '<div class="pwt-promo-in"><span class="pwt-promo-badge"></span>' +
      '<span><span class="pwt-promo-long"></span><span class="pwt-promo-short"></span></span>' +
      '<span class="pwt-promo-links"></span></div>' +
      '<button type="button" class="pwt-x" aria-label="Close announcement">×</button>');
    bar.setAttribute("role", "region");
    bar.setAttribute("aria-label", "Announcement");
    bar.querySelector(".pwt-promo-badge").textContent = PROMO.badge;
    bar.querySelector(".pwt-promo-long").textContent = PROMO.text;
    bar.querySelector(".pwt-promo-short").textContent = PROMO.short;
    var links = bar.querySelector(".pwt-promo-links");
    PROMO.subjects.forEach(function (sub) {
      var a = document.createElement("a");
      a.href = sub[1];
      a.textContent = sub[0] + " →";
      links.appendChild(a);
    });
    var old = document.querySelector(".announce");
    bar.querySelector(".pwt-x").addEventListener("click", function () {
      set(BAR_KEY, PROMO.id);
      bar.remove();
      if (old) old.hidden = false;
    });
    if (old) old.hidden = true;
    (old || header).parentNode.insertBefore(bar, old || header);
  }

  function mountCard() {
    var d = daysLeft();
    var count = d > 1 ? d + " days to go" : d === 1 ? "Starts tomorrow" : d === 0 ? "Starts today" : "Started · seats still open";
    var card = el("aside", "pwt-pc",
      '<button type="button" class="pwt-x" aria-label="Close">×</button>' +
      '<div class="pwt-pc-top"><span class="pwt-pc-badge">New batch · 31 Oct</span><span class="pwt-pc-count"></span></div>' +
      '<h3>May/June 2027 classes, <em>ready by April.</em></h3>' +
      '<p class="pwt-pc-sub">Maths, Physics &amp; Computer Science. Full syllabus Nov–Jan, past papers Feb–Apr, 4 classes + 1 test every week.</p>' +
      '<div class="pwt-pc-rows"></div>' +
      '<span class="pwt-pc-guar">💯 Not happy after the first paid class? Full refund.</span>' +
      '<p class="pwt-pc-from">O Level &amp; IGCSE <b>PKR 8,499</b>/mo · A Level courses from <b>PKR 12,999</b>/mo</p>' +
      '<div class="pwt-pc-acts"><a class="pwt-pc-wa" target="_blank" rel="noopener" data-go>' + WA_SVG + 'Book a free demo class</a></div>');
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "New Maths batch");
    card.querySelector(".pwt-pc-count").textContent = count;
    var rows = card.querySelector(".pwt-pc-rows");
    var ICON = { Maths: "📐", Physics: "⚛️", CS: "💻" };
    PROMO.subjects.forEach(function (sub) {
      var r = document.createElement("a");
      r.className = "pwt-pc-row";
      r.href = sub[1];
      r.setAttribute("data-go", "");
      r.innerHTML = '<div><b></b><small></small></div><span class="go" aria-hidden="true">→</span>';
      r.querySelector("b").textContent = ICON[sub[0]] + " " + (sub[0] === "CS" ? "Computer Science" : sub[0]);
      r.querySelector("small").textContent = "A Level: " + sub[2];
      rows.appendChild(r);
    });
    card.querySelector(".pwt-pc-wa").href = PROMO.wa;
    var snooze = function () { set(CARD_KEY, JSON.stringify({ id: PROMO.id, at: Date.now() })); };
    var close = function () {
      snooze();
      card.classList.remove("is-on");
      setTimeout(function () { card.remove(); }, 300);
      document.removeEventListener("keydown", onKey);
    };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    card.querySelector(".pwt-x").addEventListener("click", close);
    card.querySelectorAll("[data-go]").forEach(function (x) { x.addEventListener("click", snooze); });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(card);
    requestAnimationFrame(function () { requestAnimationFrame(function () { card.classList.add("is-on"); }); });
  }

  function mount() {
    var header = document.querySelector(".site-header");
    if (!header || document.querySelector(".pwt-promo, .pwt-pc")) return;
    var css = document.createElement("style");
    css.textContent = CSS;
    document.head.appendChild(css);
    if (showBar) mountBar(header);
    if (showCard) setTimeout(mountCard, 2500);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
