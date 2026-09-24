/* Enhanced site behaviour: active nav, scroll-reveal with variants,
   staggered animations, count-up numbers, and parallax effects.
   Uses rect checks rather than IntersectionObserver for broad compatibility. */

// ── One-time notice toasts (set via ?pwt_notice= from server redirects) ───────
(function () {
  const NOTICES = {
    google_linked: "✅ Google account linked — you can now sign in with either Google or your password.",
    google_new:    "👋 Welcome! Your account has been created via Google.",
  };
  const p = new URLSearchParams(location.search);
  const notice = p.get("pwt_notice");
  if (!notice || !NOTICES[notice]) return;

  // Strip the param from the URL without a reload
  p.delete("pwt_notice");
  const clean = location.pathname + (p.toString() ? "?" + p.toString() : "") + location.hash;
  history.replaceState(null, "", clean);

  const toast = document.createElement("div");
  toast.textContent = NOTICES[notice];
  Object.assign(toast.style, {
    position: "fixed", bottom: "24px", left: "50%", transform: "translateX(-50%) translateY(20px)",
    background: "var(--navy, #1a2e5a)", color: "#fff",
    padding: "12px 22px", borderRadius: "10px", fontSize: ".9rem",
    fontFamily: "inherit", zIndex: "9999", opacity: "0",
    boxShadow: "0 4px 20px rgba(0,0,0,.22)", maxWidth: "92vw", textAlign: "center",
    transition: "opacity .3s, transform .3s",
  });
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    toast.style.opacity = "1";
    toast.style.transform = "translateX(-50%) translateY(0)";
  });
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(-50%) translateY(20px)";
    setTimeout(() => toast.remove(), 400);
  }, 5000);
})();

// Mark the current page's nav link
const here = location.pathname.split("/").pop() || "index.html";
document.querySelectorAll(".nav-link, .nav-drop-item").forEach((a) => {
  const href = a.getAttribute("href");
  if (href && href.split("#")[0] === here) {
    a.classList.add("active");
    // Also highlight the parent group button
    a.closest(".nav-group")?.querySelector(".nav-group-btn")?.classList.add("active");
  }
});

// Nav-group dropdown behaviour is handled by tools-nav.js (present on all pages).

// Collect all revealable elements (all variants)
const revealSelectors = ".reveal, .reveal-left, .reveal-right, .reveal-scale";
const reveals = [...document.querySelectorAll(revealSelectors)];
const counts = [...document.querySelectorAll(".count")];

// Auto-stagger: children inside .reveal-stagger get ascending --delay
document.querySelectorAll(".reveal-stagger").forEach((parent) => {
  const kids = parent.querySelectorAll(revealSelectors);
  kids.forEach((el, i) => {
    el.style.setProperty("--delay", `${i * 100}ms`);
  });
});

function inView(el, margin = 80) {
  const r = el.getBoundingClientRect();
  // Anything already scrolled past counts as revealed. You cannot animate in
  // something the reader has gone by, and a fast flick on a phone or a jump to
  // an #anchor would otherwise strand it at opacity 0 — a permanent blank gap.
  if (r.bottom <= 0) return true;
  return r.top < innerHeight - margin;
}

function runCount(el) {
  const target = +el.dataset.target;
  const suffix = el.dataset.suffix || "";
  const t0 = performance.now(), dur = 1200;
  (function tick(t) {
    const p = Math.min((t - t0) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * eased).toLocaleString() + suffix;
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
  // Fallback: if rAF is throttled, snap to the final value.
  setTimeout(() => {
    el.textContent = target.toLocaleString() + suffix;
  }, dur + 200);
}

function sweep() {
  for (let i = reveals.length - 1; i >= 0; i--) {
    if (inView(reveals[i])) {
      reveals[i].classList.add("in");
      reveals.splice(i, 1);
    }
  }
  for (let i = counts.length - 1; i >= 0; i--) {
    if (inView(counts[i])) {
      runCount(counts[i]);
      counts.splice(i, 1);
    }
  }
}

addEventListener("scroll", sweep, { passive: true });
addEventListener("resize", sweep);
addEventListener("load", sweep);
sweep();

// Safety net for contexts where scroll events are throttled
const timer = setInterval(() => {
  sweep();
  if (!reveals.length && !counts.length) clearInterval(timer);
}, 600);

// ============ Smooth header shadow on scroll ============
const header = document.querySelector(".site-header");
if (header) {
  let ticking = false;
  addEventListener("scroll", () => {
    if (!ticking) {
      requestAnimationFrame(() => {
        if (scrollY > 10) {
          header.style.boxShadow = "0 4px 24px rgba(41,53,84,.08)";
        } else {
          header.style.boxShadow = "none";
        }
        ticking = false;
      });
      ticking = true;
    }
  }, { passive: true });
}

// ============ Parallax floating shapes ============
// Add subtle parallax to decorative elements if present
const parallaxEls = document.querySelectorAll(".parallax-float");
if (parallaxEls.length) {
  addEventListener("scroll", () => {
    const y = scrollY;
    parallaxEls.forEach((el) => {
      const speed = parseFloat(el.dataset.speed || "0.3");
      el.style.transform = `translateY(${y * speed}px)`;
    });
  }, { passive: true });
}

// ============ Demo Booking — Choice Modal + Form + Calendly ============

document.addEventListener("DOMContentLoaded", () => {

  // ---- Choice modal HTML ----
  const choiceHTML = `
<div class="bk-choice" id="bkChoice" aria-hidden="true">
  <div class="bkc-backdrop" id="bkChoiceBackdrop"></div>
  <div class="bkc-inner" role="dialog" aria-labelledby="bkcTitle">
    <button class="bkc-close" id="bkChoiceClose" aria-label="Close">&times;</button>
    <div class="bkc-head">
      <h3 id="bkcTitle">Book a Free Demo Lesson</h3>
      <p>A 30-minute session with Tee &mdash; no commitment, no sales pitch.<br>How would you like to book?</p>
    </div>
    <div class="bkc-options">
      <button class="bkc-opt primary" id="bkcFormBtn">
        <span class="bkc-badge">Recommended</span>
        <span class="bkc-icon">📋</span>
        <b>Fill a quick form</b>
        <p>Share your student&rsquo;s details, board, and subjects. Tee will reach out within 24 hours to confirm a slot.</p>
        <span class="bkc-cta">Send request &rarr;</span>
      </button>
      <button class="bkc-opt" id="bkcCalBtn">
        <span class="bkc-icon">📅</span>
        <b>Pick a time yourself</b>
        <p>Choose a slot from Tee&rsquo;s live calendar &mdash; confirmed instantly.</p>
        <span class="bkc-note">Tee will WhatsApp you before the session to learn more about your student.</span>
        <span class="bkc-cta">Open calendar &rarr;</span>
      </button>
    </div>
  </div>
</div>`;

  // ---- Booking form panel HTML ----
  const panelHTML = `
<div class="bk-panel" id="bkPanel" aria-hidden="true">
  <div id="bkBody">
    <div class="fb-panel-head">
      <div>
        <h3>Book a Free Demo</h3>
        <p>Tee will reach out within 24 hours to schedule your session.</p>
      </div>
      <button class="fb-close" id="bkClose" aria-label="Close">&times;</button>
    </div>
    <form id="bkForm" novalidate>
      <div class="bk-field">
        <label for="bkParent">Parent&rsquo;s name <span class="req">*</span></label>
        <input type="text" id="bkParent" placeholder="e.g. Sarah Khan" autocomplete="name">
      </div>
      <div class="bk-field">
        <label for="bkStudent">Student&rsquo;s name <span class="req">*</span></label>
        <input type="text" id="bkStudent" placeholder="e.g. Zain Khan">
      </div>
      <div class="bk-field">
        <label for="bkPhone">WhatsApp / phone <span class="req">*</span></label>
        <input type="tel" id="bkPhone" placeholder="+92 300 1234567" autocomplete="tel">
      </div>
      <div class="bk-field">
        <label for="bkBoard">Board &amp; level <span class="req">*</span></label>
        <select id="bkBoard">
          <option value="" disabled selected>Select your level&hellip;</option>
          <option value="O Level">Cambridge O Level</option>
          <option value="IGCSE">Cambridge IGCSE</option>
          <option value="A Level">Cambridge A Level (AS / A2)</option>
        </select>
      </div>
      <div class="bk-field">
        <label>Subjects <span class="req">*</span></label>
        <div class="bk-checks">
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Mathematics"> Maths</label>
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Physics"> Physics</label>
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Chemistry"> Chemistry</label>
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Computer Science"> CS</label>
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Islamiyat"> Islamiyat</label>
          <label class="bk-check"><input type="checkbox" name="bkSubjects" value="Pakistan Studies"> Pak Studies</label>
        </div>
      </div>
      <div class="bk-field">
        <label for="bkMsg">Message <span class="bk-opt">(optional)</span></label>
        <textarea id="bkMsg" rows="3" placeholder="Any specific topics, learning gaps, or questions about lessons&hellip;"></textarea>
      </div>
      <div class="bk-err" id="bkErr" hidden></div>
      <button type="submit" class="bk-submit" id="bkSubmit">Request Free Demo &rarr;</button>
    </form>
  </div>
  <div class="bk-thanks" id="bkThanks" hidden>
    <span class="bk-thanks-icon">🎉</span>
    <h4>Demo request sent!</h4>
    <p>Tee will reach out via WhatsApp within 24 hours to set up your session.</p>
  </div>
</div>`;

  // ---- Inject both into the DOM ----
  const cw = document.createElement("div");
  cw.innerHTML = choiceHTML;
  document.body.appendChild(cw.firstElementChild);

  const pw = document.createElement("div");
  pw.innerHTML = panelHTML;
  document.body.appendChild(pw.firstElementChild);

  // ---- Choice modal logic ----
  const choice  = document.getElementById("bkChoice");
  const bkPanel = document.getElementById("bkPanel");

  window.openBooking = function () { openChoice(); };

  function openChoice() {
    choice.classList.add("open");
    choice.setAttribute("aria-hidden", "false");
  }
  function closeChoice() {
    choice.classList.remove("open");
    choice.setAttribute("aria-hidden", "true");
  }
  function openPanel() {
    closeChoice();
    bkPanel.classList.add("open");
    bkPanel.setAttribute("aria-hidden", "false");
  }
  function closePanel() {
    bkPanel.classList.remove("open");
    bkPanel.setAttribute("aria-hidden", "true");
    document.getElementById("bkBody").hidden = false;
    document.getElementById("bkThanks").hidden = true;
    document.getElementById("bkForm").reset();
    document.getElementById("bkErr").hidden = true;
    document.getElementById("bkForm").querySelectorAll(".bk-input-err")
      .forEach(el => el.classList.remove("bk-input-err"));
  }

  document.getElementById("bkChoiceClose").addEventListener("click", closeChoice);
  document.getElementById("bkChoiceBackdrop").addEventListener("click", closeChoice);
  document.getElementById("bkcFormBtn").addEventListener("click", openPanel);
  document.getElementById("bkcCalBtn").addEventListener("click", () => {
    closeChoice();
    function _openCal() {
      Calendly.initPopupWidget({
        url: 'https://calendly.com/nexgentutors6/30min',
        pageSettings: { backgroundColor: 'FBF3D9', primaryColor: 'F4A632', textColor: '293554' },
      });
    }
    if (window.Calendly) {
      _openCal();
    } else {
      // Lazy-load Calendly only when the user actually clicks the button
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = 'https://assets.calendly.com/assets/external/widget.css';
      document.head.appendChild(css);
      const js = document.createElement('script');
      js.src = 'https://assets.calendly.com/assets/external/widget.js';
      js.onload = _openCal;
      document.head.appendChild(js);
    }
  });

  document.getElementById("bkClose").addEventListener("click", closePanel);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeChoice(); closePanel(); }
  });

  // ---- Form submit ----
  document.getElementById("bkForm").addEventListener("submit", async e => {
    e.preventDefault();
    document.getElementById("bkForm").querySelectorAll(".bk-input-err")
      .forEach(el => el.classList.remove("bk-input-err"));
    document.getElementById("bkErr").hidden = true;

    const parent   = document.getElementById("bkParent").value.trim();
    const student  = document.getElementById("bkStudent").value.trim();
    const phone    = document.getElementById("bkPhone").value.trim();
    const board    = document.getElementById("bkBoard").value;
    const subjects = [...document.querySelectorAll('input[name="bkSubjects"]:checked')].map(c => c.value);

    const errs = [];
    if (!parent)  { errs.push("Parent's name is required.");         document.getElementById("bkParent").classList.add("bk-input-err"); }
    if (!student) { errs.push("Student's name is required.");        document.getElementById("bkStudent").classList.add("bk-input-err"); }
    if (!phone)   { errs.push("WhatsApp / phone is required.");      document.getElementById("bkPhone").classList.add("bk-input-err"); }
    if (!board)   { errs.push("Please select a board / level.");     document.getElementById("bkBoard").classList.add("bk-input-err"); }
    if (!subjects.length) errs.push("Please pick at least one subject.");

    if (errs.length) {
      document.getElementById("bkErr").innerHTML = errs.map(m => `<span>${m}</span>`).join("");
      document.getElementById("bkErr").hidden = false;
      return;
    }

    const submit = document.getElementById("bkSubmit");
    submit.disabled = true; submit.textContent = "Sending…";

    try {
      const res = await fetch("/api/demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parent_name: parent, student_name: student,
          contact: phone, grade: board, subjects,
          message: document.getElementById("bkMsg").value }),
      });
      const data = await res.json();
      if (res.ok && data.status === "success") {
        document.getElementById("bkBody").hidden = true;
        document.getElementById("bkThanks").hidden = false;
        setTimeout(closePanel, 4200);
      } else {
        document.getElementById("bkErr").innerHTML = `<span>${data.message || "Something went wrong. Please try again."}</span>`;
        document.getElementById("bkErr").hidden = false;
        submit.disabled = false; submit.textContent = "Request Free Demo →";
      }
    } catch (_) {
      document.getElementById("bkErr").innerHTML = "<span>Connection error — please reach out on WhatsApp instead.</span>";
      document.getElementById("bkErr").hidden = false;
      submit.disabled = false; submit.textContent = "Request Free Demo →";
    }
  });

  // ---- Intercept all booking triggers ----
  document.querySelectorAll('a[href="#contact"], a[href="index.html#contact"], .btn-gold, .book-demo-trigger').forEach(btn => {
    if (btn.getAttribute("href")?.startsWith("mailto:")) return;
    if (btn.getAttribute("href")?.startsWith("https://wa.me")) return;
    if (btn.classList.contains("wa-bubble")) return;
    btn.addEventListener("click", e => { e.preventDefault(); openChoice(); });
  });

  // ============ Subjects Horizontal Scroll Buttons Wiring ============
  document.querySelectorAll(".board-section").forEach((section) => {
    const grid = section.querySelector(".subject-grid");
    const prevBtn = section.querySelector(".scroll-btn.prev");
    const nextBtn = section.querySelector(".scroll-btn.next");
    if (!grid || !prevBtn || !nextBtn) return;

    prevBtn.addEventListener("click", () => {
      grid.scrollBy({ left: -320, behavior: "smooth" });
    });
    nextBtn.addEventListener("click", () => {
      grid.scrollBy({ left: 320, behavior: "smooth" });
    });

    const updateButtons = () => {
      const hasScroll = grid.scrollWidth > grid.clientWidth;
      if (!hasScroll) {
        prevBtn.style.display = "none";
        nextBtn.style.display = "none";
      } else {
        prevBtn.style.display = "";
        nextBtn.style.display = "";
        prevBtn.disabled = grid.scrollLeft <= 0;
        nextBtn.disabled = grid.scrollLeft + grid.clientWidth >= grid.scrollWidth - 1;
      }
    };

    grid.addEventListener("scroll", updateButtons);
    window.addEventListener("resize", updateButtons);
    // Initial check
    setTimeout(updateButtons, 100);
  });

  // ============ Feedback Widget ============
  (function () {
    const tabHTML = `
<button class="fb-tab-btn" id="fbTabBtn" aria-label="Give feedback">
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
  </svg>
  Feedback
</button>`;

    const panelHTML = `
<div class="fb-panel" id="fbPanel" aria-hidden="true">
  <div id="fbBody">
    <div class="fb-type-tabs">
      <button class="fb-type-tab active" data-type="feedback">Feedback</button>
      <button class="fb-type-tab" data-type="issue">Report an issue</button>
    </div>
    <div id="fbContent">
      <div class="fb-panel-head">
        <div>
          <h3 id="fbPanelTitle">We'd love your feedback</h3>
          <p id="fbPanelSub">Tell us what you'd like us to improve.</p>
        </div>
        <button class="fb-close" id="fbClose" aria-label="Close">×</button>
      </div>
      <div class="fb-stars" id="fbStars" role="group" aria-label="Rating">
        ${[1,2,3,4,5].map(n => `<span class="fb-star" data-val="${n}" role="button" tabindex="0" aria-label="${n} star">★</span>`).join("")}
      </div>
      <form id="fbForm">
        <div class="fb-field">
          <label for="fbMessage" id="fbMsgLabel">What should we improve?</label>
          <textarea id="fbMessage" rows="4" placeholder="Your thoughts — features you'd like, things that felt off, anything…" required></textarea>
        </div>
        <div class="fb-field">
          <label for="fbName">Your name <span style="font-weight:400;text-transform:none">(optional)</span></label>
          <input type="text" id="fbName" placeholder="e.g. Ahmed">
        </div>
        <button type="submit" class="fb-submit" id="fbSubmitBtn">Send feedback</button>
      </form>
    </div>
  </div>
  <div class="fb-thanks" id="fbThanks" hidden>
    <span class="fb-thanks-icon">🎉</span>
    <h4>Thank you!</h4>
    <p>Your feedback helps us build a better tool for Cambridge students.</p>
  </div>
</div>`;

    const tabWrap = document.createElement("div");
    tabWrap.className = "fb-tab";
    tabWrap.innerHTML = tabHTML;
    document.body.appendChild(tabWrap);

    const pWrap = document.createElement("div");
    pWrap.innerHTML = panelHTML;
    document.body.appendChild(pWrap.firstElementChild);

    const panel    = document.getElementById("fbPanel");
    const tabBtn   = document.getElementById("fbTabBtn");
    const closeBtn = document.getElementById("fbClose");
    const form     = document.getElementById("fbForm");
    const thanks   = document.getElementById("fbThanks");
    const body     = document.getElementById("fbBody");
    const titleEl  = document.getElementById("fbPanelTitle");
    const subEl    = document.getElementById("fbPanelSub");
    const starsEl  = document.getElementById("fbStars");
    const msgLabel = document.getElementById("fbMsgLabel");
    const msgArea  = document.getElementById("fbMessage");
    const submitBtn= document.getElementById("fbSubmitBtn");
    let rating = 0;
    let mode = "feedback";

    const modeConfig = {
      feedback: {
        title: "We'd love your feedback",
        sub: "Tell us what you'd like us to improve.",
        showStars: true,
        label: "What should we improve?",
        placeholder: "Your thoughts — features you'd like, things that felt off, anything…",
        submit: "Send feedback",
      },
      issue: {
        title: "Report an issue",
        sub: "Tell us what's broken or needs fixing.",
        showStars: false,
        label: "What went wrong?",
        placeholder: "Describe the issue — which page, what happened, what you expected…",
        submit: "Send report",
      },
    };

    function applyMode(m) {
      mode = m;
      const cfg = modeConfig[m];
      titleEl.textContent = cfg.title;
      subEl.textContent = cfg.sub;
      starsEl.style.display = cfg.showStars ? "" : "none";
      msgLabel.textContent = cfg.label;
      msgArea.placeholder = cfg.placeholder;
      submitBtn.textContent = cfg.submit;
      msgArea.value = "";
      document.querySelectorAll(".fb-type-tab").forEach(t =>
        t.classList.toggle("active", t.dataset.type === m));
    }

    document.querySelectorAll(".fb-type-tab").forEach(t =>
      t.addEventListener("click", () => applyMode(t.dataset.type)));

    function openPanel() {
      panel.classList.add("open");
      panel.setAttribute("aria-hidden", "false");
    }
    function closePanel() {
      panel.classList.remove("open");
      panel.setAttribute("aria-hidden", "true");
    }

    tabBtn.addEventListener("click", () =>
      panel.classList.contains("open") ? closePanel() : openPanel());
    closeBtn.addEventListener("click", closePanel);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && panel.classList.contains("open")) closePanel();
    });

    const stars = document.querySelectorAll(".fb-star");
    stars.forEach((s) => {
      s.addEventListener("click", () => {
        rating = +s.dataset.val;
        stars.forEach((x) => x.classList.toggle("lit", +x.dataset.val <= rating));
      });
      s.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); s.click(); }
      });
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg  = msgArea.value.trim();
      const name = document.getElementById("fbName").value.trim();
      if (!msg) return;
      submitBtn.disabled = true; submitBtn.textContent = "Sending…";
      try {
        await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            rating: (mode === "feedback" && rating) ? rating : null,
            message: msg,
            name: name || null,
            page: location.pathname.split("/").pop() || "index.html",
            type: mode,
          }),
        });
      } catch (_) { /* best-effort — still show thanks */ }
      body.hidden = true;
      thanks.hidden = false;
      setTimeout(closePanel, 3200);
    });
  })();
});

// ── Global "＋ Note" FAB ───────────────────────────────────────────────────────
// Injected on every authenticated page except /notes.html (which has its own).
// Other pages can set window.NoteContext = { linked_type, linked_id, linked_label }
// to have the modal pre-filled with a source reference.
(function initGlobalNoteFab() {
  const page = location.pathname.split('/').pop() || 'index.html';
  // Skip on pages that already have their own note UI or don't need it
  const SKIP = new Set(['notes.html', 'login.html', 'index.html', 'pricing.html',
                         'teachers.html', 'contact.html', 'terms.html', 'privacy.html',
                         'teacher-apply.html']);
  if (SKIP.has(page)) return;

  // Inject FAB button — notepad icon, stacked above chatbot owl
  const fab = document.createElement('button');
  fab.id = 'global-note-fab';
  fab.type = 'button';
  fab.title = 'Quick note (N)';
  fab.setAttribute('aria-label', 'Add a note');
  // Notepad/document icon — clearly distinct from the pen annotation button
  fab.innerHTML = `<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="8" y1="13" x2="16" y2="13"/>
    <line x1="8" y1="17" x2="13" y2="17"/>
  </svg>`;
  fab.style.cssText = `
    position:fixed; bottom:6rem; right:1.4rem; z-index:8000;
    width:44px; height:44px; border-radius:14px;
    background:#1B3A7A; color:#fff;
    border:none; cursor:pointer; display:flex; align-items:center; justify-content:center;
    box-shadow:0 4px 18px rgba(27,58,122,.4);
    transition:transform .18s, box-shadow .18s, background .15s;
  `;
  fab.addEventListener('mouseenter', () => {
    fab.style.transform = 'scale(1.08) translateY(-2px)';
    fab.style.boxShadow = '0 8px 26px rgba(27,58,122,.5)';
  });
  fab.addEventListener('mouseleave', () => {
    fab.style.transform = '';
    fab.style.boxShadow = '0 4px 18px rgba(27,58,122,.4)';
  });
  document.body.appendChild(fab);

  // Inject modal overlay (lightweight, separate from notes.html modal)
  const HTML = `
  <div id="gnf-overlay" style="
    position:fixed;inset:0;z-index:9100;pointer-events:none;
  ">
    <div id="gnf-backdrop" style="
      position:absolute;inset:0;background:rgba(10,6,26,.38);
      backdrop-filter:blur(2px);opacity:0;transition:opacity .22s;cursor:pointer;
    "></div>
    <div id="gnf-modal" style="
      position:absolute;top:0;right:0;bottom:0;width:min(460px,100vw);
      background:#fff;overflow:hidden;box-shadow:-6px 0 40px rgba(10,6,26,.18);
      display:flex;flex-direction:column;
      transform:translateX(100%);transition:transform .28s cubic-bezier(.34,1.0,.64,1);
    ">
      <div style="padding:.9rem 1.1rem .8rem;border-bottom:1px solid var(--line,#e0ddf0);
                  display:flex;align-items:center;justify-content:space-between;flex-shrink:0;">
        <b style="font-size:.92rem;color:var(--navy,#2d1b69)">Quick Note</b>
        <button id="gnf-close" type="button" style="
          width:28px;height:28px;border:none;background:var(--cream,#f4f2fb);
          border-radius:8px;cursor:pointer;color:var(--grey,#6b6b85);font-size:.95rem;
          display:flex;align-items:center;justify-content:center;">✕</button>
      </div>
      <div style="padding:.9rem 1.1rem;display:flex;flex-direction:column;gap:.6rem;overflow-y:auto;flex:1;">
        <div id="gnf-type-row" style="display:flex;gap:.4rem;">
          <button class="gnf-type" data-type="text" type="button" style="
            padding:.32rem .8rem;border-radius:20px;border:1.5px solid var(--navy,#2d1b69);
            font-size:.78rem;font-weight:700;cursor:pointer;
            background:var(--navy,#2d1b69);color:#fff;">📄 Text</button>
          <button class="gnf-type" data-type="sticky" type="button" style="
            padding:.32rem .8rem;border-radius:20px;border:1.5px solid var(--line,#e0ddf0);
            font-size:.78rem;font-weight:600;cursor:pointer;
            background:#fff;color:var(--grey,#6b6b85);">📌 Sticky</button>
        </div>
        <div id="gnf-colors" style="display:none;gap:.4rem;flex-wrap:wrap;">
          <button style="width:22px;height:22px;border-radius:50%;border:2px solid var(--navy);background:#FFF176;cursor:pointer" data-color="yellow"></button>
          <button style="width:22px;height:22px;border-radius:50%;border:2px solid transparent;background:#FFB3C8;cursor:pointer" data-color="pink"></button>
          <button style="width:22px;height:22px;border-radius:50%;border:2px solid transparent;background:#90CAF9;cursor:pointer" data-color="blue"></button>
          <button style="width:22px;height:22px;border-radius:50%;border:2px solid transparent;background:#A5D6A7;cursor:pointer" data-color="green"></button>
          <button style="width:22px;height:22px;border-radius:50%;border:2px solid transparent;background:#CE93D8;cursor:pointer" data-color="purple"></button>
        </div>
        <input id="gnf-title" type="text" placeholder="Title (optional)" maxlength="140" style="
          width:100%;padding:.5rem .7rem;border:1.5px solid var(--line,#e0ddf0);
          border-radius:10px;font-size:.86rem;font-family:inherit;
          background:#fff;color:var(--ink,#1a1a2e);box-sizing:border-box;">
        <textarea id="gnf-content" placeholder="• Key point&#10;• Something to remember…"
          maxlength="4000" style="
          width:100%;padding:.5rem .7rem;border:1.5px solid var(--line,#e0ddf0);
          border-radius:10px;font-size:.86rem;font-family:inherit;resize:vertical;
          min-height:110px;background:#fff;color:var(--ink,#1a1a2e);box-sizing:border-box;"></textarea>
        <span id="gnf-ctx-tag" style="display:none;font-size:.72rem;font-weight:600;
          padding:.2rem .6rem;border-radius:20px;background:var(--lav,#ede8ff);
          color:var(--navy,#2d1b69);width:fit-content;"></span>
      </div>
      <div style="padding:.75rem 1.1rem;border-top:1px solid var(--line,#e0ddf0);
                  display:flex;gap:.5rem;justify-content:flex-end;flex-shrink:0;">
        <button id="gnf-cancel" type="button" style="
          padding:.46rem 1rem;border-radius:10px;
          background:var(--cream,#f4f2fb);color:var(--ink,#1a1a2e);
          font-weight:600;font-size:.84rem;border:1.5px solid var(--line,#e0ddf0);cursor:pointer;">
          Cancel</button>
        <button id="gnf-save" type="button" style="
          padding:.46rem 1.2rem;border-radius:10px;
          background:var(--navy,#2d1b69);color:#fff;
          font-weight:700;font-size:.84rem;border:none;cursor:pointer;">
          Save Note</button>
      </div>
    </div>
  </div>`;

  document.body.insertAdjacentHTML('beforeend', HTML);

  const gnfOverlay = document.getElementById('gnf-overlay');
  const gnfModal   = document.getElementById('gnf-modal');
  const gnfClose   = document.getElementById('gnf-close');
  const gnfCancel  = document.getElementById('gnf-cancel');
  const gnfSave    = document.getElementById('gnf-save');
  const gnfTitle   = document.getElementById('gnf-title');
  const gnfContent = document.getElementById('gnf-content');
  const gnfColors   = document.getElementById('gnf-colors');
  const gnfCtxTag   = document.getElementById('gnf-ctx-tag');
  const gnfBackdrop = document.getElementById('gnf-backdrop');

  let gnfType = 'text', gnfColor = 'yellow';

  function setGnfType(t) {
    gnfType = t;
    document.querySelectorAll('.gnf-type').forEach(b => {
      const active = b.dataset.type === t;
      b.style.background = active ? 'var(--navy,#2d1b69)' : '#fff';
      b.style.color = active ? '#fff' : 'var(--grey,#6b6b85)';
      b.style.borderColor = active ? 'var(--navy,#2d1b69)' : 'var(--line,#e0ddf0)';
      b.style.fontWeight = active ? '700' : '600';
    });
    gnfColors.style.display = t === 'sticky' ? 'flex' : 'none';
  }

  function openGnf() {
    const ctx = window.NoteContext || null;
    gnfTitle.value = '';
    gnfContent.value = '';
    setGnfType('text');
    // Context badge
    if (ctx && ctx.linked_label) {
      const icons = {paper:'📑',flashcard_block:'🗂️',chapter:'📖',tutor_message:'🤖'};
      gnfCtxTag.textContent = (icons[ctx.linked_type] || '🔗') + ' ' + ctx.linked_label;
      gnfCtxTag.style.display = 'inline-block';
    } else {
      gnfCtxTag.style.display = 'none';
    }
    gnfOverlay.style.pointerEvents = 'all';
    gnfBackdrop.style.opacity = '1';
    gnfModal.style.transform = 'translateX(0)';
    setTimeout(() => gnfContent.focus(), 280);
  }

  function closeGnf() {
    gnfOverlay.style.pointerEvents = 'none';
    gnfBackdrop.style.opacity = '0';
    gnfModal.style.transform = 'translateX(100%)';
  }

  async function saveGnf() {
    const title   = gnfTitle.value.trim();
    const content = gnfContent.value.trim();
    if (!content && !title) { gnfContent.focus(); return; }
    gnfSave.disabled = true; gnfSave.textContent = 'Saving…';
    const ctx = window.NoteContext || {};
    try {
      const r = await fetch('/api/notes', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          type: gnfType,
          title: title || null,
          content: content || null,
          color: gnfType === 'sticky' ? gnfColor : null,
          linked_type: ctx.linked_type || null,
          linked_id:   String(ctx.linked_id || '') || null,
          linked_label: ctx.linked_label || null,
        }),
      });
      if (!r.ok) throw new Error();
      closeGnf();
      // Brief confirmation badge
      const badge = document.createElement('div');
      badge.textContent = '✅ Note saved';
      badge.style.cssText = `position:fixed;bottom:1.6rem;left:50%;transform:translateX(-50%);
        background:var(--navy,#2d1b69);color:#fff;border-radius:12px;
        padding:.6rem 1.2rem;font-size:.84rem;font-weight:600;z-index:9999;
        transition:opacity .4s;`;
      document.body.appendChild(badge);
      setTimeout(() => { badge.style.opacity='0'; setTimeout(()=>badge.remove(),400); }, 2200);
    } catch (_) {
      gnfSave.textContent = '❌ Failed';
      setTimeout(() => { gnfSave.disabled=false; gnfSave.textContent='Save Note'; }, 1500);
      return;
    }
    gnfSave.disabled = false; gnfSave.textContent = 'Save Note';
  }

  // Colour swatch click
  gnfColors.querySelectorAll('[data-color]').forEach(s => {
    s.addEventListener('click', () => {
      gnfColor = s.dataset.color;
      gnfColors.querySelectorAll('[data-color]').forEach(x => {
        x.style.borderColor = x === s ? 'var(--navy,#2d1b69)' : 'transparent';
      });
    });
  });

  // Type pill click
  document.querySelectorAll('.gnf-type').forEach(b => {
    b.addEventListener('click', () => setGnfType(b.dataset.type));
  });

  fab.addEventListener('click', openGnf);
  gnfClose.addEventListener('click', closeGnf);
  gnfCancel.addEventListener('click', closeGnf);
  gnfBackdrop.addEventListener('click', closeGnf);
  gnfSave.addEventListener('click', saveGnf);

  document.addEventListener('keydown', e => {
    if (gnfOverlay.style.pointerEvents === 'all') {
      if (e.key === 'Escape') closeGnf();
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') saveGnf();
    } else if (e.key === 'n' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
      openGnf();
    }
  });

  // Expose globally so other scripts can open the fab modal
  window.openGlobalNote = openGnf;
})();

// ── Load chatbot widget on all pages that include main.js ─────────────────────
(function () {
  var s = document.createElement('script');
  s.src = '/chatbot-widget.js?v=20260830a';   // absolute: pages also live at /papers/..., /blog/...
  s.defer = true;
  document.head.appendChild(s);
})();
