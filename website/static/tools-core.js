/* PrepWithTee — study tools core.
 *
 * Every tool is a widget that renders itself into a container, rather than a
 * script bound to one page's element IDs. That is what lets the same code run
 * as a full page (tools/calculator.html) AND inside the dock that floats over
 * revise/papers/tutor, without a second implementation drifting out of sync.
 *
 * A tool registers itself:
 *     PWT.register({ id, name, icon, mount(el, ctx) -> optional teardown fn })
 *
 * Pages opt in declaratively:  <div data-pwt-tool="calculator"></div>
 * The dock mounts on demand and lazy-loads the script the first time a tool is
 * opened, so a practice page only pays for what the student actually uses.
 */
(function (root) {
  "use strict";

  var registry = {};
  var loading = {};

  // Tool id -> script file(s), loaded in order. Kept here so the dock can
  // lazy-load without every page hard-coding a script tag for all six tools.
  var SOURCES = {
    calculator: ["calc-engine.js", "tools-calculator.js"],   // the maths engine first
    formulas: "tools-formulas.js",
    graph: ["math-expr.js", "tools-graph.js"],      // the safe expression parser first
    command: "tools-commandwords.js",
    periodic: "tools-periodic.js",
    logic: "tools-logic.js",
    pseudocode: "tools-pseudocode.js"
  };

  // Presentation metadata, used by the dock, the hub and the nav dropdown so
  // the three can never disagree about what a tool is called.
  var CATALOGUE = [
    { id: "calculator", name: "Calculator", icon: "🧮", tint: "lav",
      href: "calculator.html", blurb: "Scientific keypad that knows your syllabus" },
    { id: "formulas", name: "Formula sheets", icon: "📐", tint: "orange",
      href: "formulas.html", blurb: "Given in exam, or must memorise" },
    { id: "graph", name: "Graph plotter", icon: "📈", tint: "green",
      href: "graph.html", blurb: "Plot and trace curves" },
    { id: "graphs-guide", name: "Graph sketching guide", icon: "📐", tint: "pink",
      href: "graphs-guide.html", blurb: "Master shapes, sketching & asymptotes" },
    { id: "command", name: "Command words", icon: "💡", tint: "pink",
      href: "command-words.html", blurb: "What the examiner actually wants" },
    { id: "periodic", name: "Periodic table", icon: "⚗️", tint: "teal",
      href: "periodic-table.html", blurb: "The Cambridge data sheet" },
    { id: "logic", name: "Bases & logic", icon: "🔢", tint: "blue",
      href: "bases-logic.html", blurb: "Binary, hex and truth tables" },
    { id: "pseudocode", name: "Pseudocode runner", icon: "⌨️", tint: "lav",
      href: "pseudocode.html", blurb: "Run it, trace it, fix it" }
  ];

  var VERSION = "20261005a";

  // ── Small shared helpers ────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  // Data files are immutable per release, so one fetch per file per page load.
  var dataCache = {};
  function data(name) {
    if (!dataCache[name]) {
      dataCache[name] = fetch("/data/" + name + ".json?v=" + VERSION)
        .then(function (r) {
          if (!r.ok) throw new Error(name + ": HTTP " + r.status);
          return r.json();
        })
        .catch(function (err) {          // don't cache a failure forever
          delete dataCache[name];
          throw err;
        });
    }
    return dataCache[name];
  }

  // ── Shared subject context ──────────────────────────────────────────────
  // One answer to "which subject is this student on?", so the calculator's
  // exam rules and the formula sheet's default agree — and so a tool opened
  // over a practice page inherits what that page is about.
  var ctx = {
    syllabus: null,
    _subs: [],
    set: function (syl, opts) {
      if (!syl || syl === ctx.syllabus) return;
      ctx.syllabus = syl;
      if (!opts || opts.remember !== false) {
        try { localStorage.setItem("pwt_tool_syllabus", syl); } catch (e) {}
      }
      ctx._subs.forEach(function (fn) { try { fn(syl); } catch (e) {} });
    },
    onChange: function (fn) { ctx._subs.push(fn); return function () {
      ctx._subs = ctx._subs.filter(function (f) { return f !== fn; }); }; }
  };

  // Resolution order: explicit ?syllabus= > what the host page is showing >
  // last used > the student's first enrolment.
  function resolveContext() {
    var q = new URLSearchParams(location.search).get("syllabus");
    if (q) { ctx.set(q, { remember: false }); return; }

    var onPage = document.body && document.body.dataset.syllabus;
    if (onPage) { ctx.set(onPage, { remember: false }); return; }

    try {
      var saved = localStorage.getItem("pwt_tool_syllabus");
      if (saved) ctx.syllabus = saved;
    } catch (e) {}

    fetch("/api/enrollments", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var first = d && d.enrollments && d.enrollments[0];
        if (first && !ctx.syllabus) ctx.set(first.syllabus);
      })
      .catch(function () { /* signed out — whatever we have stands */ });
  }

  // ── Registry ────────────────────────────────────────────────────────────
  function register(tool) {
    if (!tool || !tool.id) throw new Error("a tool needs an id");
    registry[tool.id] = tool;
    document.dispatchEvent(new CustomEvent("pwt:tool-ready", { detail: tool.id }));
  }

  var scripts = {};
  function script(file) {
    if (!scripts[file]) {
      scripts[file] = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = "/" + file + "?v=" + VERSION;
        s.onload = resolve;
        s.onerror = function () { delete scripts[file]; reject(new Error("could not load " + file)); };
        document.head.appendChild(s);
      });
    }
    return scripts[file];
  }

  function load(id) {
    if (registry[id]) return Promise.resolve(registry[id]);
    if (!SOURCES[id]) return Promise.reject(new Error("unknown tool: " + id));
    if (!loading[id]) {
      var files = [].concat(SOURCES[id]);
      loading[id] = files.reduce(function (prev, file) {
        return prev.then(function () { return script(file); });
      }, Promise.resolve()).then(function () {
        if (!registry[id]) throw new Error(id + " loaded but did not register");
        return registry[id];
      }).catch(function (e) { delete loading[id]; throw e; });
    }
    return loading[id];
  }

  // Mount a tool into a container. Returns a promise for a teardown function,
  // so the dock can swap tools without leaking listeners or canvases.
  function mount(id, container, opts) {
    return load(id).then(function (tool) {
      container.innerHTML = "";
      // Drop the previous tool's marker class, or a container reused by the
      // dock ends up carrying every tool it has ever shown.
      Array.prototype.slice.call(container.classList).forEach(function (c) {
        if (c.indexOf("pwt-tool-") === 0) container.classList.remove(c);
      });
      container.classList.add("pwt-tool", "pwt-tool-" + id);
      var teardown = tool.mount(container, Object.assign({ ctx: ctx }, opts || {}));
      return typeof teardown === "function" ? teardown : function () {};
    }).catch(function (err) {
      container.innerHTML = '<div class="pwt-tool-err">Could not open this tool — ' +
        esc(err.message) + "</div>";
      return function () {};
    });
  }

  // Auto-mount anything declared in the page.
  function autoMount() {
    document.querySelectorAll("[data-pwt-tool]").forEach(function (node) {
      mount(node.dataset.pwtTool, node, { mode: node.dataset.pwtMode || "page" });
    });
  }

  root.PWT = {
    register: register, mount: mount, load: load,
    catalogue: CATALOGUE, ctx: ctx, data: data,
    esc: esc, el: el, version: VERSION
  };

  document.addEventListener("DOMContentLoaded", function () {
    resolveContext();
    autoMount();
  });
})(window);
