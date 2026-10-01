/* PrepWithTee — the practice dock.
 *
 * Tools have to be reachable WHILE a student is working, not one navigation
 * away: leaving a half-finished revise session to look up a formula is how
 * sessions get abandoned. This puts every tool in a panel that slides over the
 * page, keeping the question on screen behind it.
 *
 * Managing it comes down to four decisions:
 *   - Lazy: no tool script is fetched until the student opens that tool, so a
 *     practice page costs one small script until it is actually used.
 *   - One instance: switching tools tears the previous one down (listeners,
 *     canvas, ResizeObserver) rather than stacking hidden copies.
 *   - Sticky: last tool, panel width and open state persist per student, so
 *     the calculator is where they left it on the next question.
 *   - Context-aware: the dock reads the syllabus the page is showing and
 *     pushes it into PWT.ctx, so opening the formula sheet over an 0625
 *     revision session lands on 0625 without being asked.
 *
 * Include on any page with:  <script src="tools-dock.js"></script>
 *
 * Paper viewers (booklets, papers by year, MCQ) include it through
 * ui.tools_dock(): <body data-syllabus="0625" data-dock="push">. There the
 * dock shows the tools that subject's exam needs (calculator + periodic
 * table for chemistry, bases + pseudocode for CS...), and on a wide screen
 * the paper moves over instead of being covered, so the question and the
 * calculator are side by side.
 */
(function () {
  "use strict";

  var KEY_TOOL = "pwt_dock_tool", KEY_OPEN = "pwt_dock_open", KEY_W = "pwt_dock_w";
  var MIN_W = 320, MAX_W = 760;
  // The tools a paper in each subject is sat with, most used first.
  var SUBJECT_KIND = { "4024": "maths", "0580": "maths", "9709": "maths", "5054": "physics", "0625": "physics",
    "9702": "physics", "5070": "chemistry", "0620": "chemistry", "9701": "chemistry", "2210": "cs", "0478": "cs",
    "9618": "cs" };
  var SUBJECT_TOOLS = {
    maths: ["calculator", "graph", "formulas", "command"],
    physics: ["calculator", "formulas", "graph", "command"],
    chemistry: ["calculator", "periodic", "formulas", "command"],
    cs: ["logic", "pseudocode", "calculator", "command"],
  };
  var PUSH_MIN = 1100;                     // below this the panel overlays the page

  function store(k, v) { try { v === undefined ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  function build() {
    var PWTx = window.PWT;
    if (!PWTx) return;                       // core did not load; fail quiet
    if (document.querySelector(".pwt-dock")) return;

    // Ensure tools.css is loaded dynamically
    if (!document.querySelector('link[href*="tools.css"]')) {
      var link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/tools.css?v=" + (PWTx.version || "20260827");
      document.head.appendChild(link);
    }

    var all = PWTx.catalogue.filter(function (t) { return t.id !== "graphs-guide"; });
    var pageSyl = document.body.dataset.syllabus || "";
    var wanted = SUBJECT_TOOLS[SUBJECT_KIND[pageSyl]];
    var tools = wanted ? wanted.map(function (id) { return all.find(function (t) { return t.id === id; }); }).filter(Boolean) : all;
    var push = document.body.dataset.dock === "push";
    var current = read(KEY_TOOL) || tools[0].id;
    if (!tools.some(function (t) { return t.id === current; })) current = tools[0].id;

    var dock = document.createElement("div");
    dock.className = "pwt-dock";
    // A vertical tab on the right edge, stacked directly above the feedback
    // tab so the two read as one column of side actions — and, crucially, well
    // clear of the chat launcher parked in the bottom-right corner.
    dock.innerHTML =
      '<button class="pwt-fab" data-fab aria-expanded="false" aria-controls="pwt-dock-panel">' +
        '<svg class="pwt-fab-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
          '<path d="M14.7 6.3a4 4 0 0 0 5.3 5.3l-8.4 8.4a2.1 2.1 0 0 1-3-3l8.4-8.4Z" ' +
            'stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>' +
          '<path d="M3.5 3.5 8 8M6 3.5 3.5 6M9.5 12.5 6.5 9.5" ' +
            'stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>' +
        "</svg>" +
        '<span class="pwt-fab-label">Tools</span>' +
      "</button>" +
      '<div class="pwt-coach" data-coach hidden>' +
        '<span class="pwt-coach-arrows" aria-hidden="true"><i></i><i></i><i></i></span>' +
        '<span class="pwt-coach-text">Open me — calculator, formulas and more, ' +
          "without leaving this page.</span>" +
        '<button class="pwt-coach-x" data-coach-x aria-label="Dismiss">×</button>' +
      "</div>" +
      '<section class="pwt-panel" id="pwt-dock-panel" role="dialog" aria-label="Study tools" hidden>' +
        '<div class="pwt-grip" data-grip title="Drag to resize"></div>' +
        '<header class="pwt-panel-head">' +
          '<div class="pwt-tabs" role="tablist">' +
            tools.map(function (t) {
              return '<button role="tab" class="pwt-tab" data-tool="' + t.id + '" ' +
                'title="' + PWTx.esc(t.name) + '" aria-selected="false">' +
                '<span class="pwt-tab-icon">' + t.icon + "</span>" +
                '<span class="pwt-tab-name">' + PWTx.esc(t.name) + "</span></button>";
            }).join("") +
          "</div>" +
          '<div class="pwt-panel-actions">' +
            '<a class="pwt-pop" data-pop target="_blank" rel="noopener" title="Open in a new tab">↗</a>' +
            '<button class="pwt-close" data-close title="Close (Esc)">×</button>' +
          "</div>" +
        "</header>" +
        '<div class="pwt-panel-body" data-body></div>' +
      "</section>";
    document.body.appendChild(dock);

    var panel = dock.querySelector(".pwt-panel");
    var body = dock.querySelector("[data-body]");
    var fab = dock.querySelector("[data-fab]");
    var popLink = dock.querySelector("[data-pop]");
    var teardown = null;

    var w = parseInt(read(KEY_W), 10);
    if (w >= MIN_W && w <= MAX_W) panel.style.width = w + "px";

    function setTool(id) {
      if (teardown) { try { teardown(); } catch (e) {} teardown = null; }
      current = id;
      store(KEY_TOOL, id);
      dock.querySelectorAll(".pwt-tab").forEach(function (t) {
        var on = t.dataset.tool === id;
        t.classList.toggle("on", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      var meta = tools.find(function (t) { return t.id === id; });
      popLink.href = "/" + (meta ? meta.href : "tools.html");
      body.innerHTML = '<p class="pwt-loading">Opening ' +
        (meta ? PWTx.esc(meta.name.toLowerCase()) : "tool") + "…</p>";
      PWTx.mount(id, body, { mode: "dock" }).then(function (fn) { teardown = fn; });
    }

    function open(id) {
      panel.hidden = false;
      // Force a reflow so the transition has a start state to animate from.
      // requestAnimationFrame would be the tidier way, but it is throttled to
      // a standstill in a background or hidden tab — the panel then stays
      // parked off-screen with no way back.
      void panel.offsetWidth;
      dock.classList.add("open");
      fab.setAttribute("aria-expanded", "true");
      store(KEY_OPEN, "1");
      layout();
      var cm = dock.querySelector("[data-coach]");
      if (cm && !cm.hidden) { cm.hidden = true; store("pwt_dock_coached", "1"); }
      if (id !== current || !teardown) setTool(id || current);
    }

    function close() {
      dock.classList.remove("open");
      fab.setAttribute("aria-expanded", "false");
      store(KEY_OPEN, undefined);
      layout();
      // Keep the tool mounted through the slide-out so it does not flicker,
      // then hide it from assistive tech once it is off screen.
      setTimeout(function () { if (!dock.classList.contains("open")) panel.hidden = true; }, 240);
    }

    fab.addEventListener("click", function () {
      dock.classList.contains("open") ? close() : open();
    });
    dock.querySelector("[data-close]").addEventListener("click", close);
    dock.querySelector(".pwt-tabs").addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-tool]");
      if (!b) return;
      dock.classList.contains("open") && b.dataset.tool === current ? close() : open(b.dataset.tool);
    });

    document.addEventListener("keydown", function (ev) {
      // Esc inside a tool belongs to the tool (the calculator's AC); outside it closes the dock
      if (ev.key === "Escape" && dock.classList.contains("open")) {
        if (!panel.contains(document.activeElement)) close();
        return;
      }
      // Alt+T toggles, so it never collides with a student typing an answer.
      if (ev.altKey && (ev.key === "t" || ev.key === "T")) {
        ev.preventDefault();
        dock.classList.contains("open") ? close() : open();
      }
    });

    // ── Resize ────────────────────────────────────────────────────────────
    var grip = dock.querySelector("[data-grip]"), dragging = null;
    grip.addEventListener("mousedown", function (ev) {
      dragging = { x: ev.clientX, w: panel.getBoundingClientRect().width };
      document.body.classList.add("pwt-resizing");
      ev.preventDefault();
    });
    window.addEventListener("mousemove", function (ev) {
      if (!dragging) return;
      var next = Math.min(MAX_W, Math.max(MIN_W, dragging.w + (dragging.x - ev.clientX)));
      panel.style.width = next + "px";
    });
    window.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = null;
      document.body.classList.remove("pwt-resizing");
      store(KEY_W, String(Math.round(panel.getBoundingClientRect().width)));
      layout();
    });

    // ── Side by side (paper viewers) ─────────────────────────────────────
    // The page gives up the panel's width; a resize event makes the PDF
    // viewer fit its pages to the narrower column.
    var laidOut = null;
    function layout() {
      var isOpen = dock.classList.contains("open");
      document.body.classList.toggle("pwt-dock-open", isOpen);
      document.body.style.setProperty("--pwt-dock-w", (Math.round(panel.getBoundingClientRect().width) || 440) + "px");
      if (!push) return;
      var on = dock.classList.contains("open") && window.innerWidth >= PUSH_MIN;
      var w = Math.round(panel.getBoundingClientRect().width) || 440;
      var key = on ? w : 0;
      if (key === laidOut) return;
      laidOut = key;
      document.body.classList.toggle("pwt-docked", on);
      document.body.style.setProperty("--pwt-dock-w", w + "px");
      setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 260);
    }
    window.addEventListener("resize", function () {
      if (push && !dragging) {
        var on = dock.classList.contains("open") && window.innerWidth >= PUSH_MIN;
        if (on !== document.body.classList.contains("pwt-docked")) layout();
      }
    });

    // ── Page context ──────────────────────────────────────────────────────
    // Practice pages advertise what the student is working on; the dock feeds
    // it to the tools so they open on the right subject.
    function syncContext() {
      var syl = document.body.dataset.syllabus ||
        (document.querySelector("[data-active-syllabus]") || {}).dataset?.activeSyllabus;
      if (syl) PWTx.ctx.set(syl, { remember: false });
    }
    syncContext();
    // The revise/papers pages switch subject without navigating, so watch.
    if (window.MutationObserver && document.body) {
      new MutationObserver(syncContext).observe(document.body, {
        attributes: true, attributeFilter: ["data-syllabus"]
      });
    }

    // ── First-visit coach mark ────────────────────────────────────────────
    // The tab is easy to miss on a busy page, so point at it once. Dismissed
    // permanently by the × or by opening the dock — never nagged again.
    var coach = dock.querySelector("[data-coach]");
    var KEY_COACH = "pwt_dock_coached";
    function hideCoach(permanent) {
      coach.hidden = true;
      fab.classList.remove("nudge");
      if (permanent) store(KEY_COACH, "1");
    }
    dock.querySelector("[data-coach-x]").addEventListener("click", function (ev) {
      ev.stopPropagation();
      hideCoach(true);
    });
    coach.addEventListener("click", function () { hideCoach(true); open(); });
    if (!read(KEY_COACH) && read(KEY_OPEN) !== "1") {
      setTimeout(function () {
        if (!dock.classList.contains("open")) { coach.hidden = false; fab.classList.add("nudge"); }
      }, 2200);
      setTimeout(function () { hideCoach(false); }, 15000);
    }

    setTool(current);
    if (read(KEY_OPEN) === "1" && window.innerWidth > 900) open(current);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else build();
})();
