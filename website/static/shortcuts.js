/* shortcuts.js — keyboard shortcuts on every page, and the panel that lists them.
 *
 * Loaded from partials/nav.html, so static pages (stamped by sync_nav.py), the
 * server-rendered pages (blog._nav) and the paper viewers all get it.
 *
 *   ?            this panel (also the keyboard button in the header)
 *   G then key   go to a page (G D = dashboard, G M = MCQ ...)
 *   Alt + key    tools over the current page: calculator, graph, formula sheet,
 *                tools panel, pen / highlighter / eraser
 *
 * Single-key shortcuts (?, G ...) can be switched off in the panel (WCAG 2.1.4);
 * the Alt ones stay. Keys are matched by e.code for Alt combos, because on a Mac
 * Option+C types "ç". The pen goes through window.pwtInk (annotate.js), the
 * tools through window.pwtDock (tools-dock.js) - loaded on demand when a page
 * has no dock of its own.
 * Pages can add their own rows: window.pwtShortcuts.register("Group", [{keys, label, run?}]).
 */
(function () {
  "use strict";
  if (window.pwtShortcuts) return;

  var V = "20261005b";
  var TOOLS_V = "20261005a";   // = ui.TOOLS_V
  var KEY_OFF = "pwt-keys-single-off";
  var KEY_TIP = "pwt-keys-tip";
  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  var ALT = isMac ? "⌥" : "Alt";
  var MOD = isMac ? "⌘" : "Ctrl";

  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function store(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function singleOn() { return read(KEY_OFF) !== "1"; }

  // ── Pages (G then letter) ─────────────────────────────────────────────────
  var PAGES = [
    { k: "h", label: "Home", href: "/", icon: "🏠" },
    { k: "d", label: "Dashboard", href: "/dashboard.html", icon: "📊" },
    { k: "p", label: "Past papers hub", href: "/papers", icon: "🧭" },
    { k: "t", label: "Topical papers", href: "/papers/topical", icon: "📑" },
    { k: "y", label: "Papers by year", href: "/yearly", icon: "📅" },
    { k: "m", label: "MCQ practice", href: "/mcq", icon: "⚡" },
    { k: "x", label: "Mock tests", href: "/papers/mock-tests", icon: "🧪" },
    { k: "b", label: "My papers", href: "/my-papers", icon: "🗂️" },
    { k: "n", label: "Revision notes", href: "/notes", icon: "📘" },
    { k: "r", label: "Resources", href: "/resources", icon: "📂" },
    { k: "f", label: "Flashcards", href: "/flashcards.html", icon: "🃏" },
    { k: "a", label: "AI Tutor", href: "/tutor.html", icon: "🤖" },
    { k: "s", label: "Photo Solver", href: "/solver", icon: "📷" },
    { k: "w", label: "Homework", href: "/homework.html", icon: "📝" },
    { k: "c", label: "Calendar", href: "/calendar.html", icon: "🗓️" },
    { k: "l", label: "All study tools", href: "/tools.html", icon: "🧰" },
    { k: "o", label: "My profile", href: "/profile.html", icon: "👤" },
  ];

  // ── Tools (Alt + letter) ──────────────────────────────────────────────────
  var TOOLS = [
    { code: "KeyC", key: "C", label: "Calculator", icon: "🧮", run: function () { tool("calculator"); } },
    { code: "KeyG", key: "G", label: "Graph plotter", icon: "📈", run: function () { tool("graph"); } },
    { code: "KeyS", key: "S", label: "Formula sheet", icon: "📐", run: function () { tool("formulas"); } },
    { code: "KeyT", key: "T", label: "Open / close the tools panel", icon: "🧰", run: function () { tool(null); } },
    { code: "KeyP", key: "P", label: "Pen (press again to put it down)", icon: "✏️", run: function () { ink("pen"); } },
    { code: "KeyH", key: "H", label: "Highlighter", icon: "🖍️", run: function () { ink("marker"); } },
    { code: "KeyX", key: "X", label: "Eraser", icon: "🧽", run: function () { ink("eraser"); } },
  ];

  var extra = [];          // rows pages register

  // ── Toast ─────────────────────────────────────────────────────────────────
  var toastEl = null, toastT = 0;
  function toast(html, ms) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "ks-toast";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.innerHTML = html;
    toastEl.classList.add("is-on");
    clearTimeout(toastT);
    toastT = setTimeout(function () { toastEl.classList.remove("is-on"); }, ms || 2200);
  }

  // ── Tools dock ────────────────────────────────────────────────────────────
  function loadScript(src) {
    return new Promise(function (ok, bad) {
      var s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = bad;
      document.head.appendChild(s);
    });
  }
  var dockReady = null;
  function ensureDock() {
    if (window.pwtDock) return Promise.resolve(window.pwtDock);
    if (!dockReady) {
      dockReady = (window.PWT ? Promise.resolve() : loadScript("/tools-core.js?v=" + TOOLS_V))
        .then(function () { return document.querySelector(".pwt-dock") ? null : loadScript("/tools-dock.js?v=" + TOOLS_V); })
        .then(function () {
          if (!window.pwtDock) throw new Error("no dock");
          return window.pwtDock;
        });
      dockReady.catch(function () { dockReady = null; });
    }
    return dockReady;
  }
  function tool(id) {
    ensureDock().then(function (d) {
      if (id == null) d.toggle();
      else if (d.isOpen() && d.current() === id) d.close();
      else d.open(id);
    }).catch(function () {
      // No dock could load here: the tool's own page is the next best thing.
      location.href = "/" + (id || "tools") + ".html";
    });
  }

  // ── Ink (annotate.js) ─────────────────────────────────────────────────────
  var INK_NAMES = { pen: "Pen", marker: "Highlighter", eraser: "Eraser" };
  function ink(name) {
    var a = window.pwtInk;
    if (!a) { toast("The pen isn't available on this page."); return; }
    if (a.tool === name && a.el && !a.el.hidden) {
      a.setTool("pointer");
      a.setOpen(false);
      toast("<b>" + INK_NAMES[name] + "</b> put down");
      return;
    }
    a.setOpen(true);
    a.setTool(name);
    toast("<b>" + INK_NAMES[name] + "</b> on · <kbd>Esc</kbd> to stop");
  }

  // ── Context: what this page adds ──────────────────────────────────────────
  function contextGroups() {
    var out = [];
    if (document.getElementById("mq")) {
      out.push({ title: "This MCQ session", items: [
        { keys: [["A"], ["B"], ["C"], ["D"]], or: true, label: "Choose an answer (or 1 – 4)" },
        { keys: [["←"], ["→"]], or: true, label: "Previous / next question" },
        { keys: [["Enter"]], label: "Next question (one-by-one view)" },
        { keys: [["F"]], label: "Flag the question" },
        { keys: [["Esc"]], label: "Close a panel or the answer sheet" },
      ] });
    }
    if (document.getElementById("vw") || document.getElementById("mq")) {
      out.push({ title: "This paper", items: [
        { keys: [[MOD, "+"], [MOD, "−"]], or: true, label: "Zoom the paper in / out" },
        { keys: [["Shift", "D"]], label: "White / dark paper" },
      ] });
    }
    if (window.pwtInk) {
      out.push({ title: "While the pen bar is open", items: [
        { keys: [["P"]], label: "Pen" }, { keys: [["H"]], label: "Highlighter" },
        { keys: [["E"]], label: "Eraser" }, { keys: [["T"]], label: "Text box" },
        { keys: [["S"]], label: "Select" }, { keys: [["L"]], label: "Lasso" },
        { keys: [["K"]], label: "Laser pointer" }, { keys: [["V"]], label: "Pointer (stop drawing)" },
        { keys: [[MOD, "Z"]], label: "Undo" }, { keys: [[MOD, "Y"]], label: "Redo" },
        { keys: [["Delete"]], label: "Delete what's selected" },
      ] });
    }
    if (document.querySelector(".pwt-dock") || window.pwtDock) {
      out.push({ title: "Calculator (click it first)", items: [
        { keys: [["0 – 9"]], label: "Digits" }, { keys: [["/"]], label: "Fraction" },
        { keys: [["^"]], label: "Power" }, { keys: [["Enter"]], label: "=" },
        { keys: [["Esc"]], label: "AC (clear)" },
      ] });
    }
    return out.concat(extra);
  }

  // ── The panel ─────────────────────────────────────────────────────────────
  var dlg = null, lastFocus = null;

  function kbd(combo) {
    return combo.map(function (k) { return "<kbd>" + esc(k) + "</kbd>"; }).join('<span class="ks-plus">+</span>');
  }
  function keysHtml(item) {
    if (item.then) return kbd(item.keys[0]) + '<span class="ks-then">then</span>' + kbd(item.keys[1]);
    return item.keys.map(kbd).join(item.or ? '<span class="ks-or">/</span>' : " ");
  }
  function row(item, i, g) {
    var tag = item.run || item.href ? "button" : "div";
    var attrs = tag === "button" ? ' type="button" data-ks-run="' + g + ":" + i + '"' : "";
    return "<" + tag + ' class="ks-row' + (tag === "button" ? " is-action" : "") + '"' + attrs +
      ' data-ks-q="' + esc((item.label + " " + (item.keys || []).flat().join(" ")).toLowerCase()) + '">' +
      (item.icon ? '<span class="ks-ico" aria-hidden="true">' + item.icon + "</span>" : "") +
      '<span class="ks-label">' + esc(item.label) + '</span><span class="ks-keys">' + keysHtml(item) + "</span></" + tag + ">";
  }

  function groups() {
    var single = singleOn();
    var g = [
      { title: "Anywhere", tone: "lav", items: [
        { keys: [["?"]], label: "Show these shortcuts", single: true },
        { keys: [[MOD, "K"], ["/"]], or: true, label: "Search the whole site", icon: "🔍",
          run: function () { window.pwtOpenSearch && window.pwtOpenSearch(); } },
        { keys: [["N"]], label: "Quick note", icon: "🗒️", single: true,
          run: window.openGlobalNote ? function () { window.openGlobalNote(); } : null },
        { keys: [["Esc"]], label: "Close a panel, menu or tool" },
      ] },
      { title: "Tools on this page", tone: "teal", items: TOOLS.map(function (t) {
        return { keys: [[ALT, t.key]], label: t.label, icon: t.icon, run: t.run };
      }) },
      { title: "Go to a page", tone: "orange", wide: true, sub: "Press G, let go, then the letter", items: PAGES.map(function (p) {
        return { keys: [["G"], [p.k.toUpperCase()]], then: true, label: p.label, icon: p.icon, href: p.href, single: true };
      }) },
    ].concat(contextGroups().map(function (c) { return Object.assign({ tone: "blue" }, c); }));
    g.forEach(function (grp) {
      grp.items.forEach(function (it) { if (it.single && !single) it.off = true; });
    });
    return g;
  }

  var current = [];
  function render() {
    current = groups();
    var single = singleOn();
    dlg.querySelector(".ks-body").innerHTML = current.map(function (grp, gi) {
      return '<section class="ks-group' + (grp.wide ? " is-wide" : "") + '" data-tone="' + grp.tone + '"><h3>' + esc(grp.title) +
        (grp.sub ? "<small>" + esc(grp.sub) + "</small>" : "") + "</h3>" +
        (grp.title === "Go to a page" && !single ? '<p class="ks-off-note">Single-key shortcuts are off.</p>' : "") +
        '<div class="ks-rows">' + grp.items.map(function (it, i) {
          var html = row(it, i, gi);
          return it.off ? html.replace('class="ks-row', 'class="ks-row is-off') : html;
        }).join("") + "</div></section>";
    }).join("") + '<p class="ks-empty" hidden>No shortcut matches that.</p>';
    dlg.querySelector("[data-ks-single]").checked = single;
    filter();
  }

  function filter() {
    var q = (dlg.querySelector("[data-ks-filter]").value || "").trim().toLowerCase();
    var any = false;
    dlg.querySelectorAll(".ks-group").forEach(function (sec) {
      var shown = 0;
      sec.querySelectorAll(".ks-row").forEach(function (r) {
        var hit = !q || r.dataset.ksQ.indexOf(q) >= 0;
        r.hidden = !hit;
        shown += hit ? 1 : 0;
      });
      sec.hidden = !shown;
      any = any || shown > 0;
    });
    dlg.querySelector(".ks-empty").hidden = any;
  }

  function build() {
    dlg = document.createElement("div");
    dlg.className = "ks-wrap";
    dlg.hidden = true;
    dlg.innerHTML =
      '<div class="ks-back" data-ks-close></div>' +
      '<section class="ks-dlg" role="dialog" aria-modal="true" aria-labelledby="ks-title">' +
        '<header class="ks-head">' +
          '<span class="ks-badge" aria-hidden="true">⌨️</span>' +
          '<div><h2 id="ks-title">Keyboard shortcuts</h2>' +
          "<p>Work faster without the mouse. Click any row to do it now.</p></div>" +
          '<button type="button" class="ks-x" data-ks-close aria-label="Close">×</button>' +
        "</header>" +
        '<div class="ks-tools">' +
          '<label class="ks-filter"><span aria-hidden="true">🔍</span>' +
            '<input type="search" data-ks-filter placeholder="Find a shortcut… (e.g. calculator)" aria-label="Find a shortcut" autocomplete="off"></label>' +
          '<label class="ks-switch"><input type="checkbox" data-ks-single>' +
            '<span class="ks-track" aria-hidden="true"><i></i></span>' +
            "<span>Single-key shortcuts<small>? · G then a letter · N</small></span></label>" +
        "</div>" +
        '<div class="ks-body"></div>' +
        '<footer class="ks-foot">Tip: press <kbd>?</kbd> on any page to open this. ' +
          "Shortcuts don't fire while you're typing in a box.</footer>" +
      "</section>";
    document.body.appendChild(dlg);

    dlg.addEventListener("click", function (e) {
      if (e.target.closest("[data-ks-close]")) { close(); return; }
      var b = e.target.closest("[data-ks-run]");
      if (!b) return;
      var p = b.dataset.ksRun.split(":");
      var it = current[+p[0]].items[+p[1]];
      close();
      if (it.href) location.href = it.href;
      else if (it.run) it.run();
    });
    dlg.querySelector("[data-ks-filter]").addEventListener("input", filter);
    dlg.querySelector("[data-ks-single]").addEventListener("change", function (e) {
      store(KEY_OFF, e.target.checked ? null : "1");
      render();
      toast(e.target.checked ? "Single-key shortcuts <b>on</b>" : "Single-key shortcuts <b>off</b> · Alt ones still work");
    });
    dlg.addEventListener("keydown", function (e) {
      e.stopPropagation();
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key !== "Tab") return;
      var f = [].filter.call(dlg.querySelectorAll("button, input, [href]"), function (x) { return x.offsetParent !== null; });
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  function open() {
    loadCss();
    if (!dlg) build();
    lastFocus = document.activeElement;
    dlg.querySelector("[data-ks-filter]").value = "";
    render();
    dlg.hidden = false;
    document.documentElement.classList.add("ks-lock");
    requestAnimationFrame(function () { dlg.classList.add("is-open"); });
    dlg.querySelector("[data-ks-filter]").focus();
    store(KEY_TIP, "1");
  }
  function close() {
    if (!dlg || dlg.hidden) return;
    dlg.classList.remove("is-open");
    dlg.hidden = true;
    document.documentElement.classList.remove("ks-lock");
    // Never leave focus on a control inside the hidden panel (keys would count as typing).
    if (dlg.contains(document.activeElement)) document.activeElement.blur();
    if (lastFocus && lastFocus !== document.body && lastFocus.focus) lastFocus.focus();
  }
  function isOpen() { return dlg && !dlg.hidden; }

  // ── Keys ──────────────────────────────────────────────────────────────────
  var pending = 0, hintEl = null;
  function typing(t) {
    return !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  }
  function showHint() {
    if (!hintEl) {
      hintEl = document.createElement("div");
      hintEl.className = "ks-hint";
      hintEl.setAttribute("role", "status");
      hintEl.innerHTML = '<b>Go to…</b><span class="ks-hint-list">' + PAGES.map(function (p) {
        return "<span><kbd>" + p.k.toUpperCase() + "</kbd>" + esc(p.label) + "</span>";
      }).join("") + "</span>";
      document.body.appendChild(hintEl);
    }
    hintEl.classList.add("is-on");
  }
  function endChord() {
    clearTimeout(pending);
    pending = 0;
    if (hintEl) hintEl.classList.remove("is-on");
  }

  // Capture phase on window: runs before the pages' own document listeners, so
  // the second key of "G M" never also answers an MCQ with M... or D.
  window.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.isComposing) return;
    if (isOpen()) return;                             // the panel handles its own keys
    var t = e.target;
    if (pending) {
      if (e.key === "Shift" || e.key === "Control" || e.key === "Alt" || e.key === "Meta") return;
      var p = !e.ctrlKey && !e.metaKey && !e.altKey &&
        PAGES.find(function (x) { return x.k === (e.key || "").toLowerCase(); });
      endChord();
      e.preventDefault();
      e.stopImmediatePropagation();
      if (p) { toast("Opening <b>" + esc(p.label) + "</b>…", 4000); location.href = p.href; }
      return;
    }
    if (typing(t)) return;
    // Alt + letter: tools and ink
    if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      var tl = TOOLS.find(function (x) { return x.code === e.code; });
      if (!tl) return;
      if (tl.code === "KeyT" && document.querySelector(".pwt-dock") && window.pwtDock) return;  // the dock has its own Alt+T
      if (t && t.closest && t.closest(".pwt-dock") && tl.code !== "KeyC" && tl.code !== "KeyG" && tl.code !== "KeyS") return;
      e.preventDefault();
      e.stopImmediatePropagation();
      tl.run();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || !singleOn()) return;
    if (t && t.closest && t.closest(".pwt-dock, .an-tb, .ink-fly, [role=dialog]")) return;
    if (e.key === "?") {
      e.preventDefault();
      e.stopImmediatePropagation();
      open();
    } else if (e.key === "g" || e.key === "G") {
      if (e.shiftKey) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      pending = setTimeout(endChord, 2500);
      showHint();
    }
  }, true);

  // ── Header button + first-visit tip ───────────────────────────────────────
  var cssDone = false;
  function loadCss() {
    if (cssDone || document.querySelector('link[href*="/shortcuts.css"]')) { cssDone = true; return; }
    cssDone = true;
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "/shortcuts.css?v=" + V;
    document.head.appendChild(l);
  }

  var BTN_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="6" width="19" height="12" rx="2.5"/>' +
    '<path d="M6 9.5h.01M9.3 9.5h.01M12.6 9.5h.01M15.9 9.5h.01M18.2 9.5h.01M6 12.5h.01M18.2 12.5h.01M9 15h6"/></svg>';

  function mountButton() {
    if (document.querySelector("[data-shortcuts]")) return;
    var end = document.querySelector(".site-header .header-end");
    var b = document.createElement("button");
    b.type = "button";
    if (!end) {
      // App shells without the site header (messages, dashboards, revise): a small corner button.
      if (document.body.hasAttribute("data-no-shortcut-button")) return;
      b.className = "ks-fab";
      b.setAttribute("data-shortcuts", "");
      b.setAttribute("aria-label", "Keyboard shortcuts");
      b.title = "Keyboard shortcuts (?)";
      b.innerHTML = BTN_SVG;
      document.body.appendChild(b);
      return;
    }
    b.className = "nav-search nav-keys";
    b.setAttribute("data-shortcuts", "");
    b.setAttribute("aria-label", "Keyboard shortcuts");
    b.title = "Keyboard shortcuts (?)";
    b.innerHTML = BTN_SVG;
    var search = end.querySelector("[data-site-search]");
    end.insertBefore(b, search ? search.nextSibling : end.firstChild);
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-shortcuts]");
    if (!b) return;
    e.preventDefault();
    open();
  });

  function start() {
    loadCss();
    mountButton();
    // One gentle tip, once, for keyboard-and-mouse visitors.
    if (!read(KEY_TIP) && window.matchMedia && matchMedia("(pointer: fine) and (min-width: 900px)").matches) {
      setTimeout(function () {
        if (read(KEY_TIP) || isOpen()) return;
        store(KEY_TIP, "1");
        toast('Tip: press <kbd>?</kbd> for keyboard shortcuts — <kbd>' + ALT + "</kbd>+<kbd>C</kbd> opens the calculator", 6500);
      }, 5000);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  window.pwtShortcuts = {
    open: open, close: close, toast: toast,
    register: function (title, items) { extra.push({ title: title, items: items || [] }); },
  };
})();
