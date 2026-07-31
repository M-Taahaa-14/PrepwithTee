/* Enhanced site behaviour: active nav, scroll-reveal with variants,
   staggered animations, count-up numbers, and parallax effects.
   Uses rect checks rather than IntersectionObserver for broad compatibility. */

// Mark the current page's nav link
const here = location.pathname.split("/").pop() || "index.html";
document.querySelectorAll(".nav-link").forEach((a) => {
  if (a.getAttribute("href").split("#")[0] === here) a.classList.add("active");
});

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
    if (window.Calendly) Calendly.initPopupWidget({
      url: 'https://calendly.com/nexgentutors6/30min',
      pageSettings: { backgroundColor: 'FBF3D9', primaryColor: 'F4A632', textColor: '293554' },
    });
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
