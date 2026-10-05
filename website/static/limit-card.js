/* limit-card.js — the card a student sees when a free-plan limit runs out.
 *
 * Loaded on every page from partials/nav.html (and on the header-less shells).
 * It wraps window.fetch: any same-origin /api/ response that is 403/429 with
 * detail.code "quota_exceeded" or "upgrade_required" opens the card, so every
 * feature that runs out (topical papers, mock tests, worked solutions, hints,
 * follow-ups, AI quizzes...) gets the same, prominent treatment without each
 * page wiring it up. Pages may also call PWTLimit.show(detail) or render the
 * small inline version with PWTLimit.inline(el, detail).
 *
 * The card: what ran out (meter + reset date), the free 7-day trial when the
 * student can still have one (POST /api/me/trial - once per account), and the
 * plans with prices and what they add. Data: GET /api/me/offer (upgrade.py).
 */
(function () {
  "use strict";
  if (window.PWTLimit) return;

  var V = "20261005a";
  var CODES = { quota_exceeded: 1, upgrade_required: 1 };
  var openEl = null, closedAt = 0, lastFocus = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function css() {
    if (document.querySelector('link[href*="/limit-card.css"]')) return;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "/limit-card.css?v=" + V;
    document.head.appendChild(l);
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return "";
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  }
  function money(n) { return "PKR " + Number(n).toLocaleString("en-US"); }

  // ── Watch every API response ──────────────────────────────────────────────
  var orig = window.fetch;
  if (orig) {
    window.fetch = function (input, init) {
      var p = orig.apply(this, arguments);
      p.then(function (res) {
        if (res.status !== 403 && res.status !== 429) return;
        var url = typeof input === "string" ? input : (input && input.url) || "";
        var u;
        try { u = new URL(url, location.href); } catch (e) { return; }
        if (u.origin !== location.origin || u.pathname.indexOf("/api/") !== 0) return;
        if (/^\/api\/(me\/(offer|trial)|admin\/)/.test(u.pathname)) return;
        res.clone().json().then(function (d) {
          var det = d && d.detail;
          if (det && typeof det === "object" && CODES[det.code]) show(det);
        }).catch(function () {});
      }).catch(function () {});
      return p;
    };
  }

  // ── Words ─────────────────────────────────────────────────────────────────
  function headline(det, off) {
    var f = (off && off.feature) || {};
    var name = f.name || "this feature";
    var limit = det.limit != null ? det.limit : off && off.limit;
    if (det.code === "quota_exceeded") {
      if (det.trial || (off && off.trial)) return "You've used your trial's " + (limit != null ? limit + " " : "") + name;
      return "You've used all " + (limit != null ? limit + " " : "your ") + "free " + name + " this month";
    }
    if (det.event_type === "ai_explain" && off && off.plan === "free") return "You've used your free worked solution";
    if (det.trial) return "Your trial's " + name + " are used up";
    return "Unlock " + name + " on every question";
  }

  // ── The modal ─────────────────────────────────────────────────────────────
  function show(det) {
    det = det || {};
    if (openEl || Date.now() - closedAt < 2500) return;
    var role = document.documentElement.dataset.role || "";
    if (role === "teacher" || role === "admin") return;
    css();
    lastFocus = document.activeElement;
    var wrap = document.createElement("div");
    wrap.className = "lc-wrap";
    wrap.innerHTML =
      '<div class="lc-back" data-lc-close></div>' +
      '<section class="lc-card" role="dialog" aria-modal="true" aria-labelledby="lc-title" aria-describedby="lc-sub">' +
        '<button type="button" class="lc-x" data-lc-close aria-label="Close">×</button>' +
        '<header class="lc-hero">' +
          '<span class="lc-icon" aria-hidden="true" data-lc-icon>✨</span>' +
          '<p class="lc-eyebrow">Free plan limit reached</p>' +
          '<h2 id="lc-title" data-lc-title>' + esc(headline(det, null)) + "</h2>" +
          '<p class="lc-sub" id="lc-sub">' + esc(det.message || "") + "</p>" +
          '<div class="lc-meter-wrap" data-lc-meter hidden><div class="lc-meter"><i></i></div><p class="lc-meta"></p></div>' +
        "</header>" +
        '<div class="lc-body" data-lc-body><p class="lc-loading" role="status"><span class="lc-spin" aria-hidden="true"></span>Finding your options…</p></div>' +
        '<footer class="lc-foot"><button type="button" class="lc-later" data-lc-close>Maybe later</button>' +
          '<a class="lc-all" href="/pricing.html#plans">Compare every plan →</a></footer>' +
      "</section>";
    document.body.appendChild(wrap);
    openEl = wrap;
    document.documentElement.classList.add("lc-lock");
    requestAnimationFrame(function () { wrap.classList.add("is-open"); });
    wrap.addEventListener("click", function (e) {
      if (e.target.closest("[data-lc-close]")) close();
      var t = e.target.closest("[data-lc-trial]");
      if (t) startTrial(t);
      if (e.target.closest("[data-lc-reload]")) location.reload();
    });
    document.addEventListener("keydown", onKey, true);
    wrap.addEventListener("keydown", function (e) {
      if (e.key !== "Tab") return;
      var f = [].filter.call(wrap.querySelectorAll("button, a[href]"), function (x) { return x.offsetParent !== null; });
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
    wrap.querySelector(".lc-x").focus();

    var q = "/api/me/offer?event=" + encodeURIComponent(det.event_type || "");
    orig.call(window, q, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (off) { if (openEl === wrap) fill(wrap, det, off); })
      .catch(function () { if (openEl === wrap) fill(wrap, det, null); });
  }

  function fill(wrap, det, off) {
    var body = wrap.querySelector("[data-lc-body]");
    if (off) {
      wrap.querySelector("[data-lc-icon]").textContent = (off.feature && off.feature.icon) || "✨";
      wrap.querySelector("[data-lc-title]").textContent = headline(det, off);
      if (off.trial) wrap.querySelector(".lc-eyebrow").textContent = "Trial allowance used";
      else if (det.code === "upgrade_required") wrap.querySelector(".lc-eyebrow").textContent = "Included with a plan";
      var used = det.used != null ? det.used : off.used, limit = det.limit != null ? det.limit : off.limit;
      if (limit) {
        var m = wrap.querySelector("[data-lc-meter]");
        m.hidden = false;
        m.querySelector("i").style.width = Math.min(100, Math.round(100 * (used || 0) / limit)) + "%";
        m.querySelector(".lc-meta").innerHTML = "<b>" + (used || 0) + " / " + limit + "</b> used" +
          (off.resets_on && !off.trial ? " · your free allowance resets on <b>" + esc(fmtDate(off.resets_on)) + "</b>" : "") +
          (off.trial && off.trial_days_left != null ? " · trial ends in <b>" + off.trial_days_left + " day" + (off.trial_days_left === 1 ? "" : "s") + "</b>" : "");
      }
    }
    var html = "";
    if (off && off.trial_eligible) {
      html +=
        '<section class="lc-trial">' +
          '<div class="lc-trial-text">' +
            '<p class="lc-trial-kicker">🎁 Free for ' + off.trial_days + " days</p>" +
            "<h3>Try " + esc(off.trial_plan) + " - no payment</h3>" +
            "<p>Every subject unlocked. It switches back to Free on its own, nothing to cancel.</p>" +
            '<ul class="lc-incl">' + off.trial_includes.map(function (x) {
              return "<li><span aria-hidden=\"true\">" + x.icon + "</span>" + (x.count != null ? "<b>" + x.count + "</b> " : "") + esc(x.label) + "</li>";
            }).join("") + "</ul>" +
          "</div>" +
          '<button type="button" class="lc-btn lc-btn-trial" data-lc-trial>Start my free ' + off.trial_days + "-day trial →</button>" +
          '<p class="lc-err" role="alert" hidden></p>' +
        "</section>";
    }
    var plans = (off && off.plans) || [];
    if (plans.length) {
      html += "<h3 class=\"lc-h\">" + (off && off.trial_eligible ? "Or go unlimited now" : "Keep going with a plan") + "</h3>" +
        '<div class="lc-plans">' + plans.map(function (p) {
          return '<a class="lc-plan' + (p.best ? " is-best" : "") + '" href="' + esc(p.url) + '">' +
            (p.best ? '<span class="lc-badge">Most popular</span>' : "") +
            "<b>" + esc(p.label) + '</b><span class="lc-price">' + money(p.price) + "<small>/month</small></span>" +
            "<ul>" + p.perks.map(function (k) { return "<li>" + esc(k) + "</li>"; }).join("") + "</ul>" +
            '<span class="lc-plan-cta">Choose ' + esc(p.label) + " →</span></a>";
        }).join("") + "</div>";
    } else if (!off) {
      html += '<p class="lc-fallback">See what each plan includes on the <a href="/pricing.html#plans">pricing page</a>.</p>';
    }
    body.innerHTML = html;
    var first = body.querySelector("[data-lc-trial], .lc-plan");
    if (first) first.focus();
  }

  function startTrial(btn) {
    var box = btn.closest(".lc-trial");
    var err = box.querySelector(".lc-err");
    btn.disabled = true;
    btn.textContent = "Starting your trial…";
    orig.call(window, "/api/me/trial", { method: "POST", credentials: "same-origin",
                                         headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) throw new Error((x.d.detail && (x.d.detail.message || x.d.detail)) || "Couldn't start the trial.");
        var card = openEl.querySelector(".lc-card");
        card.classList.add("is-done");
        card.querySelector(".lc-hero").innerHTML =
          '<span class="lc-icon" aria-hidden="true">🎉</span><p class="lc-eyebrow">Trial started</p>' +
          '<h2 id="lc-title">You have ' + esc(x.d.plan_label) + " for " + x.d.days + " days</h2>" +
          '<p class="lc-sub" id="lc-sub">Everything is unlocked until <b>' + esc(fmtDate(x.d.expires_at)) +
          "</b>. After that you're back on Free automatically - nothing to cancel.</p>";
        card.querySelector("[data-lc-body]").innerHTML =
          '<button type="button" class="lc-btn lc-btn-trial" data-lc-reload>Carry on where I was →</button>';
        card.querySelector(".lc-foot").hidden = true;
        card.querySelector("[data-lc-reload]").focus();
        try { window.dispatchEvent(new CustomEvent("pwt:plan-changed", { detail: x.d })); } catch (e) {}
      })
      .catch(function (e) {
        btn.disabled = false;
        btn.textContent = "Start my free trial →";
        err.hidden = false;
        err.textContent = e.message;
      });
  }

  // Escape closes the card wherever focus is (capture: before the page's own keys).
  function onKey(e) {
    if (e.key !== "Escape" || !openEl) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    close();
  }

  function close() {
    if (!openEl) return;
    document.removeEventListener("keydown", onKey, true);
    openEl.remove();
    openEl = null;
    closedAt = Date.now();
    document.documentElement.classList.remove("lc-lock");
    if (lastFocus && lastFocus !== document.body && lastFocus.focus) lastFocus.focus();
  }

  /** A small in-page version (e.g. under the builder's Build button). */
  function inline(el, det) {
    if (!el) return;
    css();
    det = det || {};
    el.innerHTML =
      '<div class="lc-inline" role="alert"><span class="lc-inline-icon" aria-hidden="true">🔒</span>' +
      "<div><b>" + esc(headline(det, null)) + "</b><p>" + esc(det.message || "") + "</p>" +
      '<button type="button" class="lc-btn lc-btn-sm" data-lc-open>See your options →</button></div></div>';
    el.hidden = false;
    el.querySelector("[data-lc-open]").addEventListener("click", function () { closedAt = 0; show(det); });
  }

  window.PWTLimit = { show: function (d) { closedAt = 0; show(d); }, inline: inline, close: close };
})();
