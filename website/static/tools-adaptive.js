/* PrepWithTee — Adaptive Formula Review (SRS).
 *
 * Spaced-repetition review of formula library entries.
 * State lives in localStorage under STORAGE_KEY.
 * The "Today's Mission" banner mounts into any element;
 * the full review session is a full-page overlay.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "pwt_ar_v1";
  var QUEUE_SIZE  = 10;

  // ── Date helpers ────────────────────────────────────────────────────────
  function todayStr() {
    return new Date().toISOString().slice(0, 10); // "2026-08-11"
  }
  function addDays(dateStr, n) {
    var d = new Date(dateStr + "T00:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function isPast(dateStr) {
    return dateStr <= todayStr();
  }

  // ── Formula key ──────────────────────────────────────────────────────────
  function slug(s) {
    return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }
  function fKey(syllabus, topic, name) {
    return slug(syllabus) + "/" + slug(topic) + "/" + slug(name);
  }

  // ── State persistence ────────────────────────────────────────────────────
  function loadState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return { reviews: {}, sessions: {} };
  }
  function saveState(state) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
  }

  // ── Build today's queue ──────────────────────────────────────────────────
  // Returns an array of {key, syllabus, topic, formula} objects.
  function buildQueue(syllabus, groups, state) {
    var today = todayStr();
    var sess = state.sessions[syllabus];
    // Reuse today's queue if the session was started today
    if (sess && sess.date === today) {
      return sess.queue;
    }

    var overdue = [], learning = [], fresh = [];
    groups.forEach(function (g) {
      g.formulas.forEach(function (f) {
        var k = fKey(syllabus, g.topic, f.name);
        var rec = state.reviews[k];
        var item = { key: k, syllabus: syllabus, topic: g.topic, formula: f };
        if (!rec) {
          fresh.push(item);
        } else if (isPast(rec.due)) {
          overdue.push(item);
        } else {
          learning.push(item);
        }
      });
    });

    // Sort overdue by most-overdue first; learning by lowest ease first
    overdue.sort(function (a, b) {
      return (state.reviews[a.key].due < state.reviews[b.key].due ? -1 : 1);
    });
    learning.sort(function (a, b) {
      return (state.reviews[a.key].ease || 2.5) - (state.reviews[b.key].ease || 2.5);
    });

    // Shuffle fresh for variety
    for (var i = fresh.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = fresh[i]; fresh[i] = fresh[j]; fresh[j] = tmp;
    }

    var queue = overdue.concat(learning).concat(fresh).slice(0, QUEUE_SIZE);

    // Save the queue for today so re-visits don't reshuffle mid-session
    if (!state.sessions) state.sessions = {};
    state.sessions[syllabus] = { date: today, queue: queue.map(function (x) { return x.key; }) };
    saveState(state);

    return queue;
  }

  // ── SM2-inspired rating ──────────────────────────────────────────────────
  // rating: "again" | "hard" | "good" | "easy"
  function applyRating(key, rating, state) {
    var rec = state.reviews[key] || { interval: 1, ease: 2.5, reps: 0 };
    switch (rating) {
      case "again":
        rec.interval = 1;
        rec.ease = Math.max(1.3, rec.ease - 0.2);
        rec.reps = 0;
        break;
      case "hard":
        rec.interval = Math.max(1, Math.ceil(rec.interval * 1.2));
        rec.ease = Math.max(1.3, rec.ease - 0.15);
        rec.reps++;
        break;
      case "good":
        rec.interval = Math.max(1, Math.ceil(rec.interval * rec.ease));
        rec.reps++;
        break;
      case "easy":
        rec.interval = Math.max(1, Math.ceil(rec.interval * rec.ease * 1.3));
        rec.ease = Math.min(2.8, rec.ease + 0.15);
        rec.reps++;
        break;
    }
    rec.due = addDays(todayStr(), rec.interval);
    rec.lastRating = rating;
    state.reviews[key] = rec;
    saveState(state);
  }

  // ── Mission summary ──────────────────────────────────────────────────────
  function getMissionSummary(syllabus, groups, state) {
    var today = todayStr();
    var overdue = 0, total = 0;
    groups.forEach(function (g) {
      g.formulas.forEach(function (f) {
        total++;
        var rec = state.reviews[fKey(syllabus, g.topic, f.name)];
        if (!rec || rec.due <= today) overdue++;
      });
    });

    var sess = state.sessions && state.sessions[syllabus];
    var doneSess = [];
    if (sess && sess.date === today) doneSess = sess.done || [];
    var queueSize = Math.min(QUEUE_SIZE, overdue + (total - (Object.keys(state.reviews).length)));

    var missionText;
    if (overdue === 0 && total > 0 && Object.keys(state.reviews).length >= total) {
      missionText = "No overdue formulas — strengthen weak topics";
    } else if (overdue > 0) {
      missionText = overdue + " formula" + (overdue !== 1 ? "s" : "") + " due for review";
    } else {
      missionText = "Start learning new formulas";
    }

    return {
      done: doneSess.length,
      total: Math.max(QUEUE_SIZE, 10),
      overdue: overdue,
      missionText: missionText,
      subText: "The queue mixes recent mistakes, new learning and useful practice."
    };
  }

  // ── Mission Banner ───────────────────────────────────────────────────────
  function buildMissionBanner(container, syllabus, groups, onLaunch) {
    if (!container || !syllabus || !groups) return;
    var state = loadState();
    var m = getMissionSummary(syllabus, groups, state);
    var pct = Math.round((m.done / QUEUE_SIZE) * 100);

    container.className = "ar-mission";
    container.innerHTML =
      '<div class="ar-mission-left">' +
        '<div class="ar-mission-check ' + (m.done >= QUEUE_SIZE ? "done" : "") + '">' +
          (m.done >= QUEUE_SIZE ? "✓" : "📅") +
        '</div>' +
        '<div class="ar-mission-text">' +
          '<p class="ar-mission-title">Today\'s Mission</p>' +
          '<p class="ar-mission-headline">' + esc(m.missionText) + '</p>' +
          '<p class="ar-mission-sub">' + esc(m.subText) + '</p>' +
        '</div>' +
      '</div>' +
      '<div class="ar-mission-right">' +
        '<div class="ar-mission-prog">' +
          '<div class="ar-mission-count">' + m.done + '/' + QUEUE_SIZE + '</div>' +
          '<div class="ar-mission-prog-bar-wrap">' +
            '<div class="ar-mission-prog-bar" style="width:' + pct + '%"></div>' +
          '</div>' +
          '<div class="ar-mission-prog-label">Reviews today</div>' +
        '</div>' +
        (m.done >= QUEUE_SIZE
          ? '<button class="ar-start-btn done" data-ar-launch>Done for today ✓</button>'
          : '<button class="ar-start-btn" data-ar-launch>Start Adaptive Review →</button>') +
      '</div>';

    container.querySelector("[data-ar-launch]").addEventListener("click", function () {
      onLaunch && onLaunch();
    });
  }

  // ── Escape helper (fallback if PWT not loaded yet) ───────────────────────
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Full review session overlay ──────────────────────────────────────────
  function launchSession(syllabus, allGroups, onClose) {
    var state = loadState();
    var allItems = [];
    // Build a flat lookup keyed by formula key
    var byKey = {};
    allGroups.forEach(function (g) {
      g.formulas.forEach(function (f) {
        var k = fKey(syllabus, g.topic, f.name);
        byKey[k] = { key: k, syllabus: syllabus, topic: g.topic, formula: f };
        allItems.push({ key: k, syllabus: syllabus, topic: g.topic, formula: f });
      });
    });

    // Get or build today's queue
    var queue = buildQueue(syllabus, allGroups, state);

    if (!queue.length) {
      queue = allItems.slice(0, QUEUE_SIZE);
    }

    // session tracking
    if (!state.sessions) state.sessions = {};
    if (!state.sessions[syllabus]) {
      state.sessions[syllabus] = { date: todayStr(), queue: queue.map(function (x) { return x.key || x; }), done: [] };
    }
    var sessData = state.sessions[syllabus];
    if (!sessData.done) sessData.done = [];

    var idx = 0;
    var revealed = false;

    // Remove unreviewed items that are already done today from the front
    // so returning mid-session continues where left off
    var remaining = queue.filter(function (item) {
      var k = (typeof item === "string") ? item : item.key;
      return sessData.done.indexOf(k) < 0;
    });

    // ── Build overlay ────────────────────────────────────────────────────
    var overlay = document.createElement("div");
    overlay.className = "ar-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML =
      '<div class="ar-session">' +
        '<div class="ar-session-hd">' +
          '<span class="ar-session-label">Adaptive Review</span>' +
          '<div class="ar-session-prog-wrap">' +
            '<div class="ar-session-prog-bar" data-ar-prog-bar></div>' +
          '</div>' +
          '<button class="ar-close-btn" data-ar-close aria-label="Close review">✕</button>' +
        '</div>' +
        '<div class="ar-session-body">' +
          '<div data-ar-card></div>' +
        '</div>' +
        '<div class="ar-session-ft">' +
          '<button class="ar-skip-btn" data-ar-skip>Skip for now</button>' +
          '<span class="ar-session-hint">Honest grading makes the schedule smarter.</span>' +
        '</div>' +
      '</div>';

    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";

    var cardEl = overlay.querySelector("[data-ar-card]");
    var progBar = overlay.querySelector("[data-ar-prog-bar]");

    function updateProg() {
      var done = sessData.done.length;
      var total = Math.max(queue.length, QUEUE_SIZE);
      var pct = Math.min(100, Math.round((done / total) * 100));
      progBar.style.width = pct + "%";
    }

    function close() {
      document.body.removeChild(overlay);
      document.body.style.overflow = "";
      onClose && onClose();
    }

    function showComplete() {
      cardEl.innerHTML =
        '<div class="ar-complete">' +
          '<div class="ar-complete-icon">🎉</div>' +
          '<h2>Session complete!</h2>' +
          '<p>You reviewed ' + sessData.done.length + ' formula' +
            (sessData.done.length !== 1 ? 's' : '') + ' today.</p>' +
          '<p class="ar-complete-sub">Come back tomorrow for your next review. Consistent practice beats cramming.</p>' +
          '<button class="ar-start-btn" data-ar-close-btn>Done</button>' +
        '</div>';
      overlay.querySelector("[data-ar-close-btn]").addEventListener("click", close);
      overlay.querySelector("[data-ar-skip]").style.display = "none";
    }

    function showCard(item) {
      var f = item.formula;
      revealed = false;

      var levelChip = f.given ? "Given" : "Must Memorise";
      var subjectName = allGroups.length ? getSyllabusLabel(syllabus) : syllabus.toUpperCase();

      cardEl.innerHTML =
        '<div class="ar-chips">' +
          '<span class="ar-chip">' + esc(subjectName) + '</span>' +
          '<span class="ar-chip">' + esc(item.topic) + '</span>' +
          '<span class="ar-chip">' + esc(levelChip) + '</span>' +
        '</div>' +
        '<p class="ar-card-prompt">Recall the formula for:</p>' +
        '<h2 class="ar-card-name">' + esc(f.name) + '</h2>' +
        '<div class="ar-card-front" data-front>' +
          '<button class="ar-reveal-btn" data-reveal>Reveal Formula</button>' +
        '</div>' +
        '<div class="ar-card-back" data-back hidden>' +
          '<div class="ar-card-formula">' + esc(f.expr) + '</div>' +
          (f.vars ? '<div class="ar-card-vars">' + renderVarChips(f.vars) + '</div>' : '') +
          (f.memory_cue ? '<div class="ar-tip tip-cue"><strong>Memory cue:</strong> ' + esc(f.memory_cue) + '</div>' : '') +
          (f.watch_out ? '<div class="ar-tip tip-warn"><strong>Watch out:</strong> ' + esc(f.watch_out) + '</div>' : '') +
          '<div class="ar-tip tip-si">Always convert to SI units before substituting (e.g. cm → m, g → kg, °C → K).</div>' +
          '<p class="ar-grade-prompt">How well did you recall it?</p>' +
          '<div class="ar-grade-btns">' +
            '<button class="ar-grade-btn grade-again" data-rate="again"><span class="ar-grade-label">Again</span><span class="ar-grade-sub">Forgot / Wrong</span></button>' +
            '<button class="ar-grade-btn grade-hard"  data-rate="hard"><span class="ar-grade-label">Hard</span><span class="ar-grade-sub">Needed help</span></button>' +
            '<button class="ar-grade-btn grade-good"  data-rate="good"><span class="ar-grade-label">Good</span><span class="ar-grade-sub">Correct with effort</span></button>' +
            '<button class="ar-grade-btn grade-easy"  data-rate="easy"><span class="ar-grade-label">Easy</span><span class="ar-grade-sub">Instant recall</span></button>' +
          '</div>' +
        '</div>';

      // Reveal
      cardEl.querySelector("[data-reveal]").addEventListener("click", function () {
        if (revealed) return;
        revealed = true;
        cardEl.querySelector("[data-front]").hidden = true;
        cardEl.querySelector("[data-back]").hidden = false;
      });

      // Grade
      cardEl.addEventListener("click", function handler(ev) {
        var btn = ev.target.closest("[data-rate]");
        if (!btn) return;
        var rating = btn.dataset.rate;
        applyRating(item.key, rating, state);
        if (sessData.done.indexOf(item.key) < 0) sessData.done.push(item.key);
        saveState(state);
        updateProg();
        cardEl.removeEventListener("click", handler);
        remaining = remaining.filter(function (x) {
          return (x.key || x) !== item.key;
        });
        showNext();
      });
    }

    function showNext() {
      if (!remaining.length) {
        showComplete();
        return;
      }
      var next = remaining[0];
      // Resolve key string back to item object if needed
      if (typeof next === "string") {
        next = byKey[next] || { key: next, syllabus: syllabus, topic: "—", formula: { name: next, expr: "—", given: false } };
      }
      showCard(next);
    }

    // Skip
    overlay.querySelector("[data-ar-skip]").addEventListener("click", function () {
      if (!remaining.length) { close(); return; }
      // Move current to end of remaining
      var cur = remaining.shift();
      remaining.push(cur);
      showNext();
    });

    // Close X
    overlay.querySelector("[data-ar-close]").addEventListener("click", close);

    // Keyboard: Escape to close, space/enter to reveal
    function onKey(ev) {
      if (ev.key === "Escape") { close(); document.removeEventListener("keydown", onKey); }
    }
    document.addEventListener("keydown", onKey);

    updateProg();
    showNext();
  }

  // ── Helpers ──────────────────────────────────────────────────────────────
  function getSyllabusLabel(code) {
    var map = {
      "9702": "Physics A Level", "9709": "Maths A Level",
      "0625": "Physics IGCSE",   "5054": "Physics O Level",
      "0580": "Maths IGCSE",     "4024": "Maths O Level",
      "2210": "CS IGCSE",        "0478": "CS O Level",
      "0620": "Chemistry IGCSE", "5070": "Chemistry O Level"
    };
    return map[code] || code;
  }

  // Convert "E field strength · Q charge · r distance" into styled chips
  function renderVarChips(vars) {
    return vars.split(/\s*·\s*/).map(function (part) {
      var m = part.match(/^(\S+)\s+(.+)$/);
      if (m) {
        return '<span class="ar-var-chip"><em>' + esc(m[1]) + '</em> ' + esc(m[2]) + '</span>';
      }
      return '<span class="ar-var-chip">' + esc(part) + '</span>';
    }).join("");
  }

  // ── Register on PWT ──────────────────────────────────────────────────────
  if (window.PWT) {
    window.PWT.AR = {
      buildMissionBanner: buildMissionBanner,
      launchSession: launchSession,
      loadState: loadState
    };
  }
})();
