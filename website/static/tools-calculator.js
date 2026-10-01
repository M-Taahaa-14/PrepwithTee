/* PrepWithTee — scientific calculator (mountable widget), laid out and behaving
 * like a Casio fx-991ES: the key a student reaches for is where their own
 * calculator has it, and SHIFT (gold) / ALPHA (red) labels sit above the keys.
 *
 *   Natural display   fractions, roots, powers, log_a b, |x|, ∫, d/dx, Σ typed
 *                     into boxes; ◀ ▶ walk in and out of them, ▲ ▼ move
 *                     between top and bottom of a fraction
 *   Exact answers     5/6, 2√3, (1+√5)/2, π/4 - S⇔D flips to the decimal,
 *                     SHIFT = gives the decimal straight away
 *   Modes (MODE)      COMP, STAT (1-variable, y = a + bx), BASE-N, EQN
 *                     (2 and 3 unknowns, quadratic, cubic), TABLE
 *   SETUP (SHIFT MODE) MthIO / LineIO, Deg / Rad / Gra, Fix / Sci / Norm, a b/c
 *   Memory            M+ M− M, Ans, PreAns, STO / RCL into A-F, X, Y, M;
 *                     kept per account (/api/calc) or on the device for a guest
 *   Also              CALC, SOLVE, CONST (data-sheet values), CONV, FUNC
 *                     (GCD, LCM, Int, Intg, RanInt#), ENG, °′″, Pol / Rec,
 *                     replay (▲ on a finished answer), the exam-rules banner
 *
 * The maths lives in calc-engine.js (tools-core loads it first); this file is
 * only keys, screen and state.
 */
(function () {
  "use strict";
  var E = window.PWTCalcEngine;

  // ── Exam rules, taken from the official syllabus PDFs in taxonomy/ ───────
  var CALC_RULES = {
    "4024": { papers: [1], note: "Paper 1 is non-calculator. Paper 2 allows a scientific calculator." },
    "0580": { papers: [1, 2], note: "Papers 1 and 2 are non-calculator. Papers 3 and 4 allow a scientific calculator." },
    "2210": { papers: "all", note: "Calculators are not permitted in any Computer Science paper." },
    "0478": { papers: "all", note: "Calculators are not permitted in any Computer Science paper." },
    "9618": { papers: "all", note: "Calculators must not be used in any paper." },
    "0625": { papers: [], note: "Calculators may be used in all parts of the examination." },
    "5054": { papers: [], note: "Calculators may be used in all parts of the examination." },
    "0620": { papers: [], note: "Calculators may be used in all parts of the examination." },
    "5070": { papers: [], note: "Calculators may be used in all parts of the examination." },
    "9709": { papers: [], note: "A scientific calculator is expected in all papers." },
    "9702": { papers: [], note: "A scientific calculator is expected in all papers." }
  };
  var SUBJECT_NAMES = {
    "4024": "O Level Mathematics D", "0580": "IGCSE Mathematics",
    "5054": "O Level Physics", "0625": "IGCSE Physics",
    "2210": "O Level Computer Science", "0478": "IGCSE Computer Science",
    "5070": "O Level Chemistry", "0620": "IGCSE Chemistry",
    "9709": "A Level Mathematics", "9702": "A Level Physics",
    "9618": "A Level Computer Science"
  };
  var BOARD_GROUPS = [
    { level: "O Level", codes: ["4024", "5054", "5070", "2210"] },
    { level: "IGCSE",   codes: ["0580", "0625", "0620", "0478"] },
    { level: "A Level", codes: ["9709", "9702", "9618"] }
  ];
  var SHORT_NAMES = {
    "4024": "Maths D", "5054": "Physics", "5070": "Chemistry", "2210": "CS",
    "0580": "Maths",   "0625": "Physics", "0620": "Chemistry", "0478": "CS",
    "9709": "Maths",   "9702": "Physics", "9618": "CS"
  };
  function boardForCode(code) {
    for (var i = 0; i < BOARD_GROUPS.length; i++) if (BOARD_GROUPS[i].codes.indexOf(code) >= 0) return BOARD_GROUPS[i].level;
    return BOARD_GROUPS[0].level;
  }

  // ── Keys: [id, main, shift, alpha, class] — the fx-991ES layout ──────────
  var TOP = [
    ["shift", "SHIFT", "", "", "cx-k-shift"], ["alpha", "ALPHA", "", "", "cx-k-alpha"],
    null,
    ["mode", "MODE", "SETUP", "", "cx-k-sm"], ["on", "ON", "", "", "cx-k-sm"],
    ["calc", "CALC", "SOLVE", "=", "cx-k-sm"], ["integ", "∫□", "d/dx", ":", "cx-k-sm"],
    null,
    ["inv", "x⁻¹", "x!", "", "cx-k-sm"], ["logab", "log□□", "Σ", "", "cx-k-sm"]
  ];
  var FN = [
    ["frac", "▭⁄▭", "▭▭⁄▭", ""], ["sqrt", "√▭", "∛▭", ""], ["sq", "x²", "x³", ""],
    ["pow", "x▭", "▭√▭", ""], ["log", "log", "10▭", ""], ["ln", "ln", "e▭", ""],
    ["neg", "(−)", "∠", "A"], ["dms", "°′″", "←", "B"], ["hyp", "hyp", "Abs", "C"],
    ["sin", "sin", "sin⁻¹", "D"], ["cos", "cos", "cos⁻¹", "E"], ["tan", "tan", "tan⁻¹", "F"],
    ["rcl", "RCL", "STO", ""], ["eng", "ENG", "←", ""], ["lp", "(", "%", ""],
    ["rp", ")", ",", "X"], ["sd", "S⇔D", "a b/c⇔d/c", "Y"], ["mplus", "M+", "M−", "M"]
  ];
  var NUM = [
    ["7", "7", "CONST", ""], ["8", "8", "CONV", ""], ["9", "9", "CLR", ""], ["del", "DEL", "INS", "", "cx-k-del"], ["ac", "AC", "OFF", "", "cx-k-ac"],
    ["4", "4", "MATRIX", ""], ["5", "5", "VECTOR", ""], ["6", "6", "FUNC", ""], ["mul", "×", "nPr", ""], ["div", "÷", "nCr", ""],
    ["1", "1", "STAT", ""], ["2", "2", "CMPLX", ""], ["3", "3", "BASE", ""], ["add", "+", "Pol", ""], ["sub", "−", "Rec", ""],
    ["0", "0", "Rnd", ""], ["dot", ".", "Ran#", "RanInt"], ["exp", "×10ˣ", "π", "e"], ["ans", "Ans", "PreAns", ""], ["eq", "=", "≈", "", "cx-k-eq"]
  ];
  // BASE-N relabels a few keys, like the real calculator
  var BASE_LABEL = { sq: "DEC", pow: "HEX", log: "BIN", ln: "OCT", neg: "A", dms: "B", hyp: "C", sin: "D", cos: "E", tan: "F" };
  var NAMES = {                                                   // spoken names for screen readers
    shift: "Shift", alpha: "Alpha", mode: "Mode", on: "On", calc: "Calc", integ: "Integral", inv: "x inverse",
    logab: "log base a of b", frac: "Fraction", sqrt: "Square root", sq: "x squared", pow: "Power",
    log: "log", ln: "ln", neg: "Negative", dms: "Degrees minutes seconds", hyp: "Hyperbolic", sin: "sine",
    cos: "cosine", tan: "tangent", rcl: "Recall", eng: "Engineering", lp: "Open bracket", rp: "Close bracket",
    sd: "Standard to decimal", mplus: "M plus", del: "Delete", ac: "All clear", mul: "times", div: "divide",
    add: "plus", sub: "minus", dot: "point", exp: "times ten to the", ans: "Answer", eq: "equals",
    up: "Up", down: "Down", left: "Left", right: "Right"
  };

  function keyHTML(k) {
    if (!k) return "";
    var cls = "cx-k" + (k[4] ? " " + k[4] : /^[0-9]$/.test(k[0]) || k[0] === "dot" ? " cx-k-num" : "");
    return '<button type="button" class="' + cls + '" data-key="' + k[0] + '" aria-label="' + (NAMES[k[0]] || k[1]) + '">' +
      '<span class="cx-lab">' + (k[2] ? '<i class="cx-sh">' + k[2] + "</i>" : "") + (k[3] ? '<i class="cx-al">' + k[3] + "</i>" : "") + "</span>" +
      '<b class="cx-main">' + k[1] + "</b></button>";
  }

  var MODE_MENU = [["COMP", "1"], ["CMPLX", "2"], ["STAT", "3"], ["BASE-N", "4"], ["EQN", "5"],
                   ["MATRIX", "6"], ["TABLE", "7"], ["VECTOR", "8"]];
  var NOT_HERE = "Not on the O Level / IGCSE / A Level syllabuses, so it is left out.";

  // ── Persistence: the account (/api/calc) or, for a guest, localStorage ────
  var GUEST_KEY = "pwt-calc", SETUP_KEY = "pwt-calc-setup";
  function readJSON(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } }
  function writeJSON(k, d) { try { localStorage.setItem(k, JSON.stringify(d)); } catch (e) { /* private mode */ } }
  function req(method, url, body) {
    return fetch(url, { method: method, credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined });
  }
  function Store() {
    var self = { signedIn: false }, timer = null, history = [];
    function snapshot(st) { return { mem: st.mem, ans: st.ans.v, deg: st.setup.angle === "deg", vars: st.vars, history: history }; }
    self.load = function (apply) {
      var guest = readJSON(GUEST_KEY);
      if (guest) { history = guest.history || []; apply(guest); }
      req("GET", "/api/calc").then(function (r) {
        if (!r.ok) throw new Error("guest");
        self.signedIn = true;
        if (guest && ((guest.history && guest.history.length) || guest.mem || Object.keys(guest.vars || {}).length)) {
          return req("POST", "/api/calc/merge", guest).then(function (m) {
            if (m.ok) { try { localStorage.removeItem(GUEST_KEY); } catch (e) { /* ignore */ } }
            return m.ok ? m.json() : r.json();
          });
        }
        return r.json();
      }).then(function (acc) { history = acc.history || []; apply(acc); })
        .catch(function () { apply(guest || {}); });
    };
    self.add = function (entry, st) {
      history = [entry].concat(history).slice(0, 200);
      if (self.signedIn) {
        req("POST", "/api/calc/history", { q: entry.q.slice(0, 300), a: entry.a.slice(0, 300), t: entry.t }).catch(function () {});
        self.save(st);
      } else writeJSON(GUEST_KEY, snapshot(st));
    };
    self.save = function (st) {
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (self.signedIn) {
          req("PUT", "/api/calc/state", { mem: st.mem, ans: st.ans.v, deg: st.setup.angle === "deg", vars: st.vars })
            .catch(function () {});
        } else writeJSON(GUEST_KEY, snapshot(st));
      }, 300);
    };
    self.clear = function (st) {
      history = [];
      if (self.signedIn) req("DELETE", "/api/calc/history").catch(function () {});
      else writeJSON(GUEST_KEY, snapshot(st));
    };
    self.history = function () { return history; };
    return self;
  }

  // ── Rendering helpers ─────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var CUR = '<span class="cx-cur" aria-hidden="true"></span>';
  var TOKEN_VIEW = {
    "×": " × ", "÷": " ÷ ", "+": " + ", "−": "−", "nPr": "<i>P</i>", "nCr": "<i>C</i>", "E": "<span class=cx-e>E</span>",
    "²": "<sup>2</sup>", "³": "<sup>3</sup>", "⁻¹": "<sup>−1</sup>", "=": " = ",
  };

  /** A sequence as natural-display HTML; the cursor drawn where it is. */
  function renderSeq(seq, cur, linear, path) {
    path = path || [];
    var here = cur && samePath(cur.path, path);
    var html = "";
    if (!seq.length && !here && path.length) return '<span class="cx-slot"></span>';
    for (var i = 0; i <= seq.length; i++) {
      if (here && cur.i === i) html += CUR;
      if (i === seq.length) break;
      var it = seq[i];
      if (!E.isTpl(it)) {
        if (TOKEN_VIEW[it]) {
          // a leading or post-operator − is a sign, no spaces
          html += (it === "−" && (i === 0 || /^[+−×÷(,=]$|\($/.test(seq[i - 1] || ""))) ? "−" :
                  it === "−" ? " − " : TOKEN_VIEW[it];
        } else if (E.CONVS[it]) html += '<span class="cx-conv">▸' + esc(it.split("▸")[1]) + "</span>";
        else if (E.CONSTS[it]) html += '<i class="cx-const">' + esc(it) + "</i>";
        else if (/^[A-FXYM]$/.test(it)) html += '<span class="cx-var">' + it + "</span>";
        else html += esc(it);
        continue;
      }
      var s = function (slot) { return renderSeq(it[slot], cur, linear, path.concat([[i, slot]])); };
      if (linear) { html += linearTpl(it, s); continue; }
      switch (it.k) {
        case "frac": html += '<span class="cx-frac"><span>' + s("n") + "</span><span>" + s("d") + "</span></span>"; break;
        case "mixed": html += s("w") + '<span class="cx-frac"><span>' + s("n") + "</span><span>" + s("d") + "</span></span>"; break;
        case "sqrt": html += '<span class="cx-sqrt"><span class="cx-rad">√</span><span class="cx-under">' + s("a") + "</span></span>"; break;
        case "root": html += '<span class="cx-idx">' + s("n") + '</span><span class="cx-sqrt"><span class="cx-rad">√</span><span class="cx-under">' + s("a") + "</span></span>"; break;
        case "pow": html += '<sup class="cx-pow">' + s("e") + "</sup>"; break;
        case "logab": html += "log<sub>" + s("b") + "</sub>(" + s("a") + ")"; break;
        case "abs": html += '<span class="cx-abs">' + s("a") + "</span>"; break;
        case "integ": html += '<span class="cx-big"><span class="cx-lim"><sup>' + s("hi") + "</sup><sub>" + s("lo") + '</sub></span>∫</span>' + s("f") + '<i class="cx-dx">dx</i>'; break;
        case "deriv": html += '<span class="cx-frac cx-ddx"><span>d</span><span>dx</span></span>(' + s("f") + ')<span class="cx-at">|<sub>x=' + s("at") + "</sub></span>"; break;
        case "sum": html += '<span class="cx-big"><span class="cx-lim"><sup>' + s("hi") + "</sup><sub>x=" + s("lo") + "</sub></span>Σ</span>(" + s("f") + ")"; break;
      }
    }
    return html;
  }
  function linearTpl(it, s) {
    switch (it.k) {
      case "frac": return "(" + s("n") + ")⌟(" + s("d") + ")";
      case "mixed": return s("w") + "⌟" + s("n") + "⌟" + s("d");
      case "sqrt": return "√(" + s("a") + ")";
      case "root": return "(" + s("n") + ")√(" + s("a") + ")";
      case "pow": return "^(" + s("e") + ")";
      case "logab": return "log(" + s("b") + "," + s("a") + ")";
      case "abs": return "Abs(" + s("a") + ")";
      case "integ": return "∫(" + s("f") + "," + s("lo") + "," + s("hi") + ")";
      case "deriv": return "d/dx(" + s("f") + "," + s("at") + ")";
      case "sum": return "Σ(" + s("f") + "," + s("lo") + "," + s("hi") + ")";
    }
    return "";
  }
  function samePath(a, b) {
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i++) if (a[i][0] !== b[i][0] || a[i][1] !== b[i][1]) return false;
    return true;
  }

  function fracHTML(top, bottom) { return '<span class="cx-frac"><span>' + top + "</span><span>" + bottom + "</span></span>"; }
  function neg(x) { return x < 0 ? "−" : ""; }
  /** An exact form as display HTML. */
  function exactHTML(r, mixedFrac) {
    var surd = function (a, b) { return (Math.abs(a) === 1 ? "" : Math.abs(a)) + '<span class="cx-sqrt"><span class="cx-rad">√</span><span class="cx-under">' + b + "</span></span>"; };
    switch (r.k) {
      case "int": return neg(r.n) + Math.abs(r.n);
      case "frac":
        if (mixedFrac && Math.abs(r.n) > r.d) {
          var m = E.mixed(r);
          return (m.sign < 0 ? "−" : "") + m.w + fracHTML(m.n, m.d);
        }
        return neg(r.n) + fracHTML(Math.abs(r.n), r.d);
      case "surd": return r.c === 1 ? neg(r.a) + surd(r.a, r.b) : neg(r.a) + fracHTML(surd(r.a, r.b), r.c);
      case "surd2": {
        var top = (r.p ? neg(r.p) + Math.abs(r.p) + (r.q < 0 ? " − " : " + ") : neg(r.q)) + surd(r.q, r.b);
        return r.d === 1 ? top : fracHTML(top, r.d);
      }
      case "pi": {
        var t = (Math.abs(r.n) === 1 ? "" : Math.abs(r.n)) + "π";
        return neg(r.n) + (r.d === 1 ? t : fracHTML(t, r.d));
      }
    }
    return "";
  }
  function decHTML(f) {
    var m = f.mant.replace(/^-/, "−");
    return f.exp == null ? m : m + '<span class="cx-x10">×10<sup>' + String(f.exp).replace(/^-/, "−") + "</sup></span>";
  }
  function decText(f) { return f.mant.replace(/^-/, "−") + (f.exp == null ? "" : "×10^" + f.exp); }

  // ── Widget ──────────────────────────────────────────────────────────────
  function mount(root, opts) {
    var PWTx = window.PWT;
    var compact = opts && opts.mode === "dock";
    var ctx = (opts && opts.ctx) || { syllabus: null, onChange: function () { return function () {}; } };
    var initCode = ctx.syllabus || null;
    var initBoard = initCode ? boardForCode(initCode) : BOARD_GROUPS[0].level;

    root.innerHTML =
      (compact ? "" :
        '<div class="fs-board-tabs calc-board-tabs" data-calc-boards></div>' +
        '<div class="fs-subject-tabs calc-subject-tabs" data-calc-subjects></div>') +
      '<div class="calc-banner" data-banner hidden></div>' +
      '<div class="calc-layout' + (compact ? " compact" : "") + '">' +
        '<div class="cx-wrap">' +
          '<div class="cx-device" tabindex="0" data-device aria-label="Scientific calculator. Type on your keyboard or tap the keys.">' +
            '<div class="cx-brand"><span class="cx-logo">PrepWithTee</span><span class="cx-model">fx-991 · natural display</span>' +
              '<span class="cx-solar" aria-hidden="true"><i></i><i></i><i></i><i></i></span></div>' +
            '<div class="cx-lcd" data-lcd>' +
              '<div class="cx-status" data-status></div>' +
              '<div class="cx-screen" data-screen aria-live="polite"></div>' +
            "</div>" +
            '<div class="cx-top">' +
              TOP.slice(0, 2).map(keyHTML).join("") +
              '<div class="cx-pad" role="group" aria-label="Cursor">' +
                '<button type="button" class="cx-pad-b cx-pad-up" data-key="up" aria-label="Up">▲</button>' +
                '<button type="button" class="cx-pad-b cx-pad-left" data-key="left" aria-label="Left">◀</button>' +
                '<span class="cx-pad-c" aria-hidden="true">REPLAY</span>' +
                '<button type="button" class="cx-pad-b cx-pad-right" data-key="right" aria-label="Right">▶</button>' +
                '<button type="button" class="cx-pad-b cx-pad-down" data-key="down" aria-label="Down">▼</button>' +
              "</div>" +
              TOP.slice(3, 5).map(keyHTML).join("") +
              TOP.slice(5, 7).map(keyHTML).join("") +
              TOP.slice(8, 10).map(keyHTML).join("") +
            "</div>" +
            '<div class="cx-fn" data-keys>' + FN.map(keyHTML).join("") + "</div>" +
            '<div class="cx-num">' + NUM.map(keyHTML).join("") + "</div>" +
          "</div>" +
          '<div class="calc-vars" data-vars></div>' +
          '<details class="cx-help"' + (compact ? "" : " open") + '><summary>Keyboard shortcuts</summary>' +
            '<dl><dt>0–9 . + − * /</dt><dd>numbers and operators (<b>/</b> makes a fraction)</dd>' +
            '<dt>^ ( ) , ! %</dt><dd>power, brackets, comma, factorial, percent</dd>' +
            '<dt>s c t</dt><dd>sin cos tan · <b>l</b> log · <b>n</b> ln · <b>r</b> √ · <b>p</b> π</dd>' +
            '<dt>x y m, A–F</dt><dd>variables X, Y, M, A–F (Shift+letter)</dd>' +
            '<dt>Enter / =</dt><dd>answer · <b>Backspace</b> DEL · <b>Esc</b> AC</dd>' +
            '<dt>← → ↑ ↓</dt><dd>move the cursor · ↑ on an answer replays</dd></dl></details>' +
        "</div>" +
        (compact ? "" :
        '<aside class="calc-side"><div class="calc-side-head"><h3>History</h3>' +
        '<span class="calc-sync" data-sync></span>' +
        '<button type="button" class="calc-clear" data-clear hidden>Clear</button></div>' +
        '<div class="calc-hist" data-history></div></aside>') +
      "</div>";

    var $ = function (sel) { return root.querySelector(sel); };
    var device = $("[data-device]"), screen = $("[data-screen]"), statusEl = $("[data-status]");
    var histEl = $("[data-history]"), banner = $("[data-banner]");
    var varsEl = $("[data-vars]"), clearBtn = $("[data-clear]"), syncEl = $("[data-sync]");

    var savedSetup = readJSON(SETUP_KEY) || {};
    var st = {
      mode: "COMP", shift: false, alpha: false, hyp: false, pending: null,
      ed: new E.Editor(), shown: null, exactView: true, mixedView: false, eng: null, dms: false,
      ans: { v: 0, ex: true }, preAns: { v: 0, ex: true }, mem: 0, vars: {},
      setup: Object.assign({ angle: "deg", fmt: "norm", digits: 1, io: "math", mixed: false }, savedSetup),
      menu: null, prompt: null, flash: null, replay: [], rIdx: -1, locked: false,
      stat: { type: "1", rows: [{}], sel: { r: 0, c: 0 }, buf: "", view: "data", est: "" },
      eqn: { type: null, coef: [], sel: { r: 0, c: 0 }, buf: "", view: "coef", sols: null },
      table: { f: null, start: 1, end: 5, step: 1, rows: null, top: 0 },
      base: "DEC", baseRes: null
    };
    st.mixedView = !!st.setup.mixed;

    var store = Store();
    store.load(function (saved) {
      st.mem = saved.mem || 0;
      st.ans = { v: saved.ans || 0, ex: true };
      st.vars = saved.vars || {};
      if (saved.deg === false && st.setup.angle === "deg") st.setup.angle = "rad";
      if (saved.deg === true && st.setup.angle === "rad" && !savedSetup.angle) st.setup.angle = "deg";
      drawHistory(); draw();
      if (syncEl) syncEl.textContent = store.signedIn ? "Saved to your account" : "Saved on this device";
    });
    var saveSetup = function () { writeJSON(SETUP_KEY, st.setup); store.save(st); };
    var env = function (extra) {
      // M is the memory (M+ / M−), not a separate variable
      var vars = Object.assign({}, st.vars, { M: st.mem });
      return Object.assign({ angle: st.setup.angle, vars: vars, ans: st.ans, preAns: st.preAns, setup: st.setup }, extra || {});
    };

    // ── the screen ──────────────────────────────────────────────────────────
    function status() {
      var ang = { deg: "D", rad: "R", gra: "G" }[st.setup.angle];
      var bits = [
        st.shift ? '<b class="cx-s-sh">S</b>' : "", st.alpha ? '<b class="cx-s-al">A</b>' : "",
        st.mem ? "<b>M</b>" : "", st.pending === "sto" ? "<b>STO</b>" : "", st.pending === "rcl" ? "<b>RCL</b>" : "",
        st.hyp ? "<b>hyp</b>" : "",
        st.mode === "BASE" ? "<b>" + st.base.slice(0, 3) + "</b>" : "<b>" + ang + "</b>",
        st.setup.io === "math" ? "<b>Math</b>" : "", st.setup.fmt === "fix" ? "<b>FIX</b>" : st.setup.fmt === "sci" ? "<b>SCI</b>" : "",
        { COMP: "", STAT: "<b>STAT</b>", EQN: "<b>EQN</b>", TABLE: "<b>TABLE</b>", BASE: "" }[st.mode]
      ];
      statusEl.innerHTML = bits.filter(Boolean).join("");
    }

    function resultHTML(r) {
      if (r.err) return '<div class="cx-err"><b>' + esc(r.err.kind || "ERROR") + "</b>" +
        (r.err.hint ? "<span>" + esc(r.err.hint) + "</span>" : "") + "<small>[AC] Cancel · [◀][▶] Goto</small></div>";
      if (r.solve) return '<div class="cx-res cx-res-list"><div><span>X =</span><b>' + numHTML(r.solve.x, false) + "</b></div>" +
        "<div><span>L−R =</span><b>" + numHTML(r.solve.lr, false) + "</b></div></div>";
      if (r.pair) return '<div class="cx-res cx-res-list"><div><span>' + r.pair.labels[0] + " =</span><b>" + numHTML(r.pair.X) + "</b></div>" +
        "<div><span>" + r.pair.labels[1] + " =</span><b>" + numHTML(r.pair.Y) + "</b></div></div>";
      if (r.base != null) return '<div class="cx-res">' + esc(E.toBase(r.base, st.base)) + "</div>" +
        '<div class="cx-bases">' + ["DEC", "HEX", "BIN", "OCT"].map(function (b) {
          return "<span" + (b === st.base ? ' class="on"' : "") + "><i>" + b + "</i>" + esc(E.toBase(r.base, b)) + "</span>";
        }).join("") + "</div>";
      return '<div class="cx-res">' + valueHTML(r) + "</div>";
    }
    function numHTML(v, allowExact) {
      if (allowExact !== false) {
        var ex = E.exact(v, true);
        if (ex) return exactHTML(ex, st.mixedView);
      }
      return decHTML(E.formatDecimal(v, st.setup));
    }
    function valueHTML(r) {
      if (st.dms) return esc(E.dms(r.v));
      if (st.eng != null) return decHTML(E.formatEng(r.v, st.eng));
      if (r.exact && st.exactView && st.setup.io === "math") return exactHTML(r.exact, st.mixedView);
      return decHTML(E.formatDecimal(r.v, st.setup));
    }
    function valueText(r) {
      if (r.solve) return "X = " + decText(E.formatDecimal(r.solve.x, st.setup));
      if (r.base != null) return E.toBase(r.base, st.base) + " (" + st.base + ")";
      if (r.exact && st.exactView && st.setup.io === "math") {
        var t = E.exactText(r.exact);
        if (st.mixedView && r.exact.k === "frac" && Math.abs(r.exact.n) > r.exact.d) {
          var m = E.mixed(r.exact);
          t = (m.sign < 0 ? "−" : "") + m.w + " " + m.n + "/" + m.d;
        }
        return t;
      }
      return decText(E.formatDecimal(r.v, st.setup));
    }

    function inputHTML(ed, withCursor) {
      return '<div class="cx-in' + (st.setup.io === "line" ? " cx-line" : "") + '">' +
        renderSeq(ed.root, withCursor ? ed.cur : null, st.setup.io === "line") + "</div>";
    }

    function draw() {
      status();
      var html = "";
      if (st.flash) html = '<div class="cx-note">' + st.flash + "</div>";
      else if (st.menu) html = menuHTML();
      else if (st.prompt) html = '<div class="cx-prompt"><p>' + st.prompt.title + "</p>" +
        '<div class="cx-prow"><span>' + st.prompt.label + "</span>" + inputHTML(st.prompt.ed, true) + "</div>" +
        (st.prompt.hint ? "<small>" + st.prompt.hint + "</small>" : "") + "</div>";
      else if (st.mode === "STAT") html = statHTML();
      else if (st.mode === "EQN") html = eqnHTML();
      else if (st.mode === "TABLE" && st.table.rows) html = tableHTML();
      else {
        if (st.mode === "TABLE") html = '<p class="cx-cap">f(X) =</p>';
        html += inputHTML(st.ed, !st.shown || st.shown.err);
        if (st.shown) html += resultHTML(st.shown);
      }
      screen.innerHTML = html;
      var c = screen.querySelector(".cx-cur");
      if (c && c.scrollIntoView) {
        var box = c.closest(".cx-in");
        if (box) {
          var cl = c.offsetLeft, w = box.clientWidth;
          if (cl < box.scrollLeft + 8) box.scrollLeft = Math.max(0, cl - 16);
          else if (cl > box.scrollLeft + w - 8) box.scrollLeft = cl - w + 24;
        }
      }
      var sel = screen.querySelector(".cx-cell.on");
      if (sel) sel.scrollIntoView({ block: "nearest" });
      device.classList.toggle("is-shift", st.shift);
      device.classList.toggle("is-alpha", st.alpha);
      device.classList.toggle("is-base", st.mode === "BASE");
      device.classList.toggle("is-locked", st.locked);
      device.querySelectorAll("[data-key]").forEach(function (b) {
        var k = b.dataset.key, main = b.querySelector(".cx-main");
        if (!main) return;
        if (!b.dataset.orig) b.dataset.orig = main.innerHTML;
        main.innerHTML = st.mode === "BASE" && BASE_LABEL[k] ? BASE_LABEL[k] : b.dataset.orig;
      });
      drawVars();
    }

    // ── menus ───────────────────────────────────────────────────────────────
    function menuHTML() {
      var m = st.menu;
      return '<div class="cx-menu"><p>' + m.title + '</p><ol class="cx-menu-grid' + (m.cols === 1 ? " one" : "") + '">' +
        m.items.map(function (it, i) {
          return '<li><button type="button" data-menu="' + i + '"' + (it.off ? ' class="off"' : "") + ">" +
            "<b>" + (it.key || i + 1) + ":</b>" + it.label + "</button></li>";
        }).join("") + "</ol>" + (m.foot ? "<small>" + m.foot + "</small>" : "") + "</div>";
    }
    function openMenu(m) { st.menu = m; st.shift = st.alpha = false; draw(); }
    function pickMenu(i) {
      var it = st.menu && st.menu.items[i];
      if (!it) return;
      var m = st.menu;
      st.menu = null;
      if (it.off) return flash(it.off);
      it.act(m);
      draw();
    }
    function flash(msg) {
      st.flash = msg;
      draw();
      clearTimeout(flash.t);
      flash.t = setTimeout(function () { st.flash = null; draw(); }, 2200);
    }

    function modeMenu() {
      openMenu({ title: "Mode", items: MODE_MENU.map(function (x) {
        var id = x[0] === "BASE-N" ? "BASE" : x[0];
        return { label: x[0], off: /CMPLX|MATRIX|VECTOR/.test(x[0]) ? NOT_HERE : null, act: function () { setMode(id); } };
      }) });
    }
    function setMode(m) {
      st.mode = m; st.shown = null; st.ed.clear(); st.prompt = null; st.hyp = false;
      if (m === "STAT") openMenu({ title: "Statistics", cols: 1, items: [
        { label: "1-VAR (one list)", act: function () { st.stat = { type: "1", rows: [{}], sel: { r: 0, c: 0 }, buf: "", view: "data", est: "" }; } },
        { label: "A+BX (y = a + bx)", act: function () { st.stat = { type: "AB", rows: [{}], sel: { r: 0, c: 0 }, buf: "", view: "data", est: "" }; } }
      ] });
      if (m === "EQN") eqnMenu();
      if (m === "TABLE") st.table = { f: null, start: 1, end: 5, step: 1, rows: null, top: 0 };
      if (m === "BASE") { st.base = "DEC"; }
    }
    function setupMenu() {
      openMenu({ title: "Setup", items: [
        { label: "MthIO", act: function () { st.setup.io = "math"; saveSetup(); } },
        { label: "LineIO", act: function () { st.setup.io = "line"; saveSetup(); } },
        { label: "Deg", act: function () { st.setup.angle = "deg"; saveSetup(); } },
        { label: "Rad", act: function () { st.setup.angle = "rad"; saveSetup(); } },
        { label: "Gra", act: function () { st.setup.angle = "gra"; saveSetup(); } },
        { label: "Fix", act: function () { digitsMenu("fix", "Fix 0~9?", 10); } },
        { label: "Sci", act: function () { digitsMenu("sci", "Sci 0~9? (0 = 10 digits)", 10); } },
        { label: "Norm", act: function () { digitsMenu("norm", "Norm 1~2?", 2, 1); } },
        { label: st.setup.mixed ? "d/c (improper)" : "ab/c (mixed)", key: "9", act: function () {
          st.setup.mixed = !st.setup.mixed; st.mixedView = st.setup.mixed; saveSetup(); } }
      ] });
    }
    function digitsMenu(fmt, title, n, from) {
      from = from || 0;
      var items = [];
      for (var d = from; d < from + n; d++) (function (d) {
        items.push({ label: String(d), key: String(d), act: function () { st.setup.fmt = fmt; st.setup.digits = d; saveSetup(); } });
      })(d);
      openMenu({ title: title, items: items });
    }
    function constMenu() {
      var names = Object.keys(E.CONSTS);
      openMenu({ title: "CONST — Cambridge data-sheet values", cols: 1, items: names.map(function (n, i) {
        var c = E.CONSTS[n];
        return { key: String(i + 1).padStart(2, "0"), label: '<i class="cx-const">' + n + "</i> " + esc(c.name) +
          " <small>" + esc(E.formatDecimal(c.v, {}).plain.replace("e", "×10^")) + " " + esc(c.unit) + "</small>",
          act: function () { insertTok(n); } };
      }), foot: "Tap one, or type its number" });
    }
    function convMenu() {
      var names = Object.keys(E.CONVS);
      openMenu({ title: "CONV — converts the value before it", cols: 1, items: names.map(function (n, i) {
        return { key: String(i + 1).padStart(2, "0"), label: esc(n.replace("▸", " ▸ ")), act: function () { insertTok(n); } };
      }) });
    }
    function funcMenu() {
      openMenu({ title: "FUNC", items: [
        { label: "GCD(", act: function () { insertTok("GCD("); } },
        { label: "LCM(", act: function () { insertTok("LCM("); } },
        { label: "Int(", act: function () { insertTok("Int("); } },
        { label: "Intg(", act: function () { insertTok("Intg("); } },
        { label: "RanInt#(", act: function () { insertTok("RanInt#("); } },
        { label: "Rnd(", act: function () { insertTok("Rnd("); } },
        { label: "PreAns", act: function () { insertTok("PreAns"); } },
        { label: "°′″ of Ans", act: function () { st.shown = { v: st.ans.v, ex: false }; st.dms = true; } }
      ] });
    }
    function clrMenu() {
      openMenu({ title: "Clear?", items: [
        { label: "Setup", act: function () { st.setup = { angle: "deg", fmt: "norm", digits: 1, io: "math", mixed: false }; st.mixedView = false; saveSetup(); flash("Setup reset"); } },
        { label: "Memory", act: function () { st.vars = {}; st.mem = 0; st.ans = { v: 0, ex: true }; store.save(st); flash("Variables, M and Ans cleared"); } },
        { label: "All", act: function () { st.vars = {}; st.mem = 0; st.ans = { v: 0, ex: true }; st.setup = { angle: "deg", fmt: "norm", digits: 1, io: "math", mixed: false }; st.mixedView = false; saveSetup(); setMode("COMP"); flash("Reset all"); } }
      ] });
    }
    function baseLogicMenu() {
      openMenu({ title: "Logic", items: ["and", "or", "xor", "xnor", "Not(", "Neg(", "d", "h", "b", "o"].map(function (w) {
        return { label: w, act: function () { insertTok(w); } };
      }) });
    }
    function eqnMenu() {
      openMenu({ title: "Equations", cols: 1, items: [
        { label: "a<sub>n</sub>X + b<sub>n</sub>Y = c<sub>n</sub>", act: function () { eqnStart(1); } },
        { label: "a<sub>n</sub>X + b<sub>n</sub>Y + c<sub>n</sub>Z = d<sub>n</sub>", act: function () { eqnStart(2); } },
        { label: "aX² + bX + c = 0", act: function () { eqnStart(3); } },
        { label: "aX³ + bX² + cX + d = 0", act: function () { eqnStart(4); } }
      ] });
    }

    // ── COMP: typing, =, results ────────────────────────────────────────────
    function activeEd() { return st.prompt ? st.prompt.ed : st.ed; }
    function startTyping(continueFromAns) {
      if (!st.shown || st.prompt) return;
      var wasErr = st.shown.err;
      st.rIdx = -1;
      st.shown = null; st.eng = null; st.dms = false; st.exactView = true;
      if (wasErr) return;                                     // an error: keep editing the same line
      st.ed.clear();
      if (continueFromAns) st.ed.insert("Ans");
    }
    function insertTok(tok) {
      if (!st.shown) st.rIdx = -1;
      if (st.mode === "STAT" || st.mode === "EQN") return cellType(tok);
      var continueOp = /^[+−×÷]$|^[²³!%]$|^⁻¹$|^nPr$|^nCr$/.test(tok) || E.CONVS[tok];
      startTyping(continueOp && st.shown && !st.shown.err);
      activeEd().insert(tok);
    }
    function insertTpl(k, fill, absorb) {
      if (st.mode === "STAT" || st.mode === "EQN" || st.mode === "BASE") return;
      startTyping(k === "pow" && st.shown && !st.shown.err);
      activeEd().insertTemplate(k, fill, absorb);
    }

    function evaluateNow(forceDecimal) {
      if (st.mode === "BASE") return evalBase();
      if (st.ed.empty() && !st.shown) return;
      if (st.shown && !st.shown.err) {                          // = again: repeat the last calculation with the new Ans
        if (st.replay.length) st.ed.set(st.replay[0]);
      }
      try {
        var ast = E.parse(st.ed.root);
        if (ast.t === "eq") throw E.CalcError("Syntax ERROR", "Use SHIFT SOLVE to solve an equation");
        var pair = null;
        var r = E.evaluate(ast, env({ onPair: function (p) { pair = p; } }));
        var ex = E.exact(r.v, r.ex);
        st.preAns = st.ans;
        st.ans = { v: r.v, ex: r.ex };
        st.shown = { v: r.v, ex: r.ex, exact: ex, pair: pair };
        if (pair) { st.vars.X = pair.X; st.vars.Y = pair.Y; }
        st.exactView = !forceDecimal; st.eng = null; st.dms = false;
        remember();
        var entry = { q: E.toText(st.ed.root), a: valueText(st.shown), t: Date.now() };
        store.add(entry, st);
        drawHistory();
      } catch (err) {
        st.shown = { err: err.kind ? err : E.CalcError("Syntax ERROR", err.message) };
      }
    }
    function remember() {
      var copy = E.clone(st.ed.root);
      if (!st.replay.length || E.toText(st.replay[0]) !== E.toText(copy)) st.replay.unshift(copy);
      st.replay.length = Math.min(st.replay.length, 40);
      st.rIdx = 0;
    }

    function evalBase() {
      if (st.ed.empty()) return;
      try {
        var v = E.evalBase(st.ed.root.join(""), st.base);
        st.preAns = st.ans; st.ans = { v: v, ex: true };
        st.shown = { v: v, base: v };
        remember();
        store.add({ q: st.ed.root.join("") + " (" + st.base + ")", a: E.toBase(v, st.base) + " (" + st.base + ")", t: Date.now() }, st);
        drawHistory();
      } catch (err) { st.shown = { err: err.kind ? err : E.CalcError("Syntax ERROR", err.message) }; }
    }

    // CALC: ask for each variable, then evaluate
    function varsIn(seq, acc) {
      acc = acc || [];
      seq.forEach(function (it) {
        if (E.isTpl(it)) E.SLOTS[it.k].forEach(function (s) { varsIn(it[s], acc); });
        else if (/^[A-FXYM]$/.test(it) && acc.indexOf(it) < 0) acc.push(it);
      });
      return acc;
    }
    function startCalc() {
      if (st.mode !== "COMP" || st.ed.empty()) return flash("Type an expression with variables first, e.g. 3X+2");
      var names = varsIn(st.ed.root);
      if (!names.length) { evaluateNow(); return; }
      st.shown = null;
      var i = 0;
      (function ask() {
        var n = names[i];
        st.prompt = { title: "CALC — " + E.toText(st.ed.root), label: n + " =", ed: editorFor((n === "M" ? st.mem : st.vars[n]) || 0),
          hint: "= to accept · AC to stop", onEnter: function (v) {
            if (n === "M") st.mem = v; else st.vars[n] = v;
            store.save(st);
            i++;
            if (i < names.length) ask();
            else {
              st.prompt = null;
              var src = E.clone(st.ed.root);
              try {
                var ast = E.parse(src);
                var r = E.evaluate(ast.t === "eq" ? ast.a : ast, env());
                st.preAns = st.ans; st.ans = { v: r.v, ex: r.ex };
                st.shown = { v: r.v, ex: r.ex, exact: E.exact(r.v, r.ex) };
                st.exactView = true;
                store.add({ q: E.toText(src) + "  [" + names.map(function (x) { return x + "=" + fmtPlain(st.vars[x]); }).join(", ") + "]",
                            a: valueText(st.shown), t: Date.now() }, st);
                drawHistory();
              } catch (err) { st.shown = { err: err }; }
            }
          } };
      })();
    }
    function startSolve() {
      if (st.mode !== "COMP" || st.ed.empty()) return flash("Type an equation in X first, e.g. X²−5X+6 = 0 (ALPHA CALC gives =)");
      var ast;
      try { ast = E.parse(st.ed.root); } catch (err) { st.shown = { err: err }; return; }
      st.shown = null;
      st.prompt = { title: "SOLVE — " + E.toText(st.ed.root), label: "X =", ed: editorFor(st.vars.X || 0),
        hint: "Starting value for X · = to solve", onEnter: function (guess) {
          st.prompt = null;
          try {
            var r = E.solve(ast, guess, env());
            st.vars.X = r.x; store.save(st);
            st.preAns = st.ans; st.ans = { v: r.x, ex: false };
            st.shown = { v: r.x, solve: r };
            store.add({ q: E.toText(st.ed.root), a: "X = " + fmtPlain(r.x), t: Date.now() }, st);
            drawHistory();
          } catch (err) { st.shown = { err: err }; }
        } };
    }
    function editorFor(v) {
      var ed = new E.Editor();
      if (v) String(fmtPlain(v)).replace("×10^", "E").split("").forEach(function (c) { ed.insert(c === "-" ? "−" : c); });
      return ed;
    }
    function fmtPlain(v) { return decText(E.formatDecimal(v, {})); }
    function promptEnter() {
      var p = st.prompt;
      try {
        var v = p.ed.empty() ? 0 : E.evaluate(E.parse(p.ed.root), env()).v;
        p.onEnter(v);
      } catch (err) { p.hint = '<span class="cx-bad">' + esc(err.message) + "</span>"; }
    }

    // ── STAT ────────────────────────────────────────────────────────────────
    function statCols() { return st.stat.type === "AB" ? ["x", "y", "f"] : ["x", "f"]; }
    function statHTML() {
      var S = st.stat;
      var tabs = '<div class="cx-tabs"><button data-soft="data" class="' + (S.view === "data" ? "on" : "") + '">Data</button>' +
        '<button data-soft="res" class="' + (S.view === "res" ? "on" : "") + '">Results</button>' +
        '<button data-soft="type">' + (S.type === "AB" ? "y=a+bx" : "1-VAR") + '</button><button data-soft="wipe">Clear data</button></div>';
      if (S.view === "res") {
        var out;
        try {
          if (S.type === "AB") {
            var r = E.stats2(S.rows);
            out = [["n", r.n], ["x̄", r.meanx], ["ȳ", r.meany], ["σx", r.sigmax], ["sx", r.sx], ["σy", r.sigmay], ["sy", r.sy],
                   ["Σx", r.sumx], ["Σy", r.sumy], ["Σx²", r.sumx2], ["Σxy", r.sumxy], ["a", r.a], ["b", r.b], ["r", r.r]];
            var est = "";
            if (S.est !== "") {
              var xv = Number(S.est);
              est = '<div class="cx-est">ŷ at x = ' + esc(S.est) + " → <b>" + decHTML(E.formatDecimal(r.a + r.b * xv, st.setup)) + "</b></div>";
            }
            return tabs + statList(out) + '<div class="cx-est-in">Estimate ŷ: type x, then = ' +
              '<span class="cx-cell on">' + (esc(S.buf) || "…") + "</span></div>" + est;
          }
          var s1 = E.stats1(S.rows);
          out = [["n", s1.n], ["x̄", s1.mean], ["σx", s1.sigma], ["sx", s1.s], ["Σx", s1.sumx], ["Σx²", s1.sumx2],
                 ["min", s1.min], ["Q1", s1.q1], ["med", s1.median], ["Q3", s1.q3], ["max", s1.max]];
          return tabs + statList(out);
        } catch (err) { return tabs + '<div class="cx-err"><b>' + esc(err.kind || "ERROR") + "</b><span>" + esc(err.hint || err.message) + "</span></div>"; }
      }
      var cols = statCols();
      return tabs + '<table class="cx-grid"><thead><tr><th></th>' + cols.map(function (c) { return "<th>" + (c === "f" ? "FREQ" : c) + "</th>"; }).join("") +
        "</tr></thead><tbody>" + S.rows.map(function (row, r) {
          return "<tr><th>" + (r + 1) + "</th>" + cols.map(function (c, ci) {
            var on = S.sel.r === r && S.sel.c === ci;
            var v = on && S.buf !== "" ? esc(S.buf) + CUR : row[c] != null ? esc(fmtPlain(row[c])) : (c === "f" && row.x != null ? "1" : "");
            return '<td class="cx-cell' + (on ? " on" : "") + '" data-cell="' + r + "," + ci + '">' + v + "</td>";
          }).join("") + "</tr>";
        }).join("") + "</tbody></table><small>Type a value, = to enter it · ▲▼◀▶ move · DEL on an empty cell removes the row</small>";
    }
    function statList(rows) {
      return '<dl class="cx-stats">' + rows.map(function (x) {
        return "<div><dt>" + x[0] + "</dt><dd>" + (isFinite(x[1]) ? decHTML(E.formatDecimal(x[1], st.setup)) : "—") + "</dd></div>";
      }).join("") + "</dl>";
    }

    // ── EQN ─────────────────────────────────────────────────────────────────
    var EQN_SHAPE = { 1: [2, ["a", "b", "c"]], 2: [3, ["a", "b", "c", "d"]], 3: [1, ["a", "b", "c"]], 4: [1, ["a", "b", "c", "d"]] };
    function eqnStart(type) {
      var sh = EQN_SHAPE[type];
      st.eqn = { type: type, coef: [], sel: { r: 0, c: 0 }, buf: "", view: "coef", sols: null };
      for (var r = 0; r < sh[0]; r++) { st.eqn.coef.push(sh[1].map(function () { return 0; })); }
    }
    function eqnHTML() {
      var Q = st.eqn;
      if (!Q.type) return '<p class="cx-cap">Press MODE to pick an equation type</p>';
      var sh = EQN_SHAPE[Q.type];
      if (Q.view === "sol") return solHTML();
      return '<p class="cx-cap">' + ["", "aX + bY = c", "aX + bY + cZ = d", "aX² + bX + c = 0", "aX³ + bX² + cX + d = 0"][Q.type] + "</p>" +
        '<table class="cx-grid"><thead><tr><th></th>' + sh[1].map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead><tbody>" +
        Q.coef.map(function (row, r) {
          return "<tr><th>" + (r + 1) + "</th>" + row.map(function (v, c) {
            var on = Q.sel.r === r && Q.sel.c === c;
            return '<td class="cx-cell' + (on ? " on" : "") + '" data-cell="' + r + "," + c + '">' +
              (on && Q.buf !== "" ? esc(Q.buf) + CUR : esc(fmtPlain(v))) + "</td>";
          }).join("") + "</tr>";
        }).join("") + "</tbody></table><small>Type each value, = to enter it · = on a filled table solves</small>";
    }
    function eqnSolve() {
      var Q = st.eqn;
      try {
        if (Q.type === 1 || Q.type === 2) {
          var xs = E.linear(Q.coef);
          Q.sols = xs.map(function (x, i) { return { label: "XYZ"[i], v: x }; });
        } else if (Q.type === 3) {
          var q = E.quadratic(Q.coef[0][0], Q.coef[0][1], Q.coef[0][2]);
          Q.sols = q.roots.map(function (z, i) { return { label: "X" + (q.roots.length > 1 ? i + 1 : ""), z: z }; });
          Q.sols.push({ label: "X-value " + (q.min ? "min" : "max"), v: q.vertex.x });
          Q.sols.push({ label: "Y-value " + (q.min ? "min" : "max"), v: q.vertex.y });
        } else {
          var cu = E.cubic(Q.coef[0][0], Q.coef[0][1], Q.coef[0][2], Q.coef[0][3]);
          Q.sols = cu.roots.map(function (z, i) { return { label: "X" + (i + 1), z: z }; });
        }
        Q.view = "sol";
        store.add({ q: "EQN " + ["", "2 unknowns", "3 unknowns", "quadratic", "cubic"][Q.type] + ": " +
          Q.coef.map(function (r) { return r.map(fmtPlain).join(", "); }).join(" | "),
          a: Q.sols.slice(0, 3).map(function (s) { return s.label + "=" + (s.z ? complexText(s.z) : fmtPlain(s.v)); }).join("  "), t: Date.now() }, st);
        drawHistory();
      } catch (err) { flash(esc(err.message)); }
    }
    function complexText(z) {
      var re = fmtPlain(z.re);
      if (!z.im) return re;
      return (z.re ? re + (z.im < 0 ? " − " : " + ") : (z.im < 0 ? "−" : "")) + fmtPlain(Math.abs(z.im)) + "i";
    }
    function solHTML() {
      return '<p class="cx-cap">Solutions <small>(AC to change the numbers)</small></p><dl class="cx-stats cx-sols">' + st.eqn.sols.map(function (s) {
        var val = s.z ? (s.z.im ? esc(complexText(s.z)) : numHTML(s.z.re)) : numHTML(s.v);
        return "<div><dt>" + s.label + " =</dt><dd>" + val + "</dd></div>";
      }).join("") + "</dl>";
    }

    // ── cells (STAT / EQN) ──────────────────────────────────────────────────
    function grid() { return st.mode === "STAT" ? st.stat : st.eqn; }
    function gridSize() {
      if (st.mode === "STAT") return { rows: st.stat.rows.length, cols: statCols().length };
      return { rows: st.eqn.coef.length, cols: st.eqn.coef[0].length };
    }
    function cellType(tok) {
      var G = grid();
      if (st.mode === "STAT" && st.stat.view === "res") {
        if (st.stat.type !== "AB") return;
      } else if (st.mode === "EQN" && (!st.eqn.type || st.eqn.view === "sol")) return;
      var map = { "−": "-", "E": "e", "π": "π", "Ans": "Ans" };
      G.buf += map[tok] || tok;
    }
    function cellValue(buf) {
      var seq = E.fromText(buf.replace(/e/g, "E").replace(/-/g, "−"));
      return E.evaluate(E.parse(seq), env()).v;
    }
    function cellEnter() {
      var G = grid();
      if (st.mode === "STAT" && G.view === "res") {
        if (G.type === "AB") { G.est = G.buf === "" ? "" : String(cellValue(G.buf)); G.buf = ""; }
        return;
      }
      if (st.mode === "EQN" && G.view === "sol") return;
      if (st.mode === "EQN" && G.buf === "") return eqnSolve();
      if (G.buf !== "") {
        var v;
        try { v = cellValue(G.buf); } catch (err) { return flash(esc(err.message)); }
        G.buf = "";
        if (st.mode === "STAT") {
          var row = G.rows[G.sel.r];
          row[statCols()[G.sel.c]] = v;
          if (G.sel.r === G.rows.length - 1 && row.x != null) G.rows.push({});
          G.sel.r = Math.min(G.sel.r + 1, G.rows.length - 1);
        } else {
          G.coef[G.sel.r][G.sel.c] = v;
          var size = gridSize();
          if (G.sel.c < size.cols - 1) G.sel.c++;
          else if (G.sel.r < size.rows - 1) { G.sel.r++; G.sel.c = 0; }
        }
      } else if (st.mode === "STAT") G.sel.r = Math.min(G.sel.r + 1, G.rows.length - 1);
    }
    function cellMove(dr, dc) {
      var G = grid(), size = gridSize();
      if (G.buf !== "") cellEnter();
      G.sel.r = Math.max(0, Math.min(size.rows - 1, G.sel.r + dr));
      G.sel.c = Math.max(0, Math.min(size.cols - 1, G.sel.c + dc));
    }
    function cellDel() {
      var G = grid();
      if (G.buf !== "") { G.buf = G.buf.slice(0, -1); return; }
      if (st.mode === "STAT" && G.view === "data" && G.rows.length > 1) {
        G.rows.splice(G.sel.r, 1);
        G.sel.r = Math.min(G.sel.r, G.rows.length - 1);
      }
    }

    // ── TABLE ───────────────────────────────────────────────────────────────
    function tableStart() {
      if (st.ed.empty()) return flash("Type f(X) first, e.g. X²−2X");
      var f;
      try { f = E.parse(st.ed.root); } catch (err) { st.shown = { err: err }; return; }
      var T = st.table;
      T.f = f; T.src = E.toText(st.ed.root);
      var steps = [["Start?", "start"], ["End?", "end"], ["Step?", "step"]], i = 0;
      (function ask() {
        var s = steps[i];
        st.prompt = { title: "TABLE — f(X) = " + T.src, label: s[0], ed: editorFor(T[s[1]]), onEnter: function (v) {
          T[s[1]] = v;
          i++;
          if (i < steps.length) return ask();
          st.prompt = null;
          if (!(T.step > 0) || T.end < T.start) return flash("Start ≤ End and a positive Step, please");
          var n = Math.floor((T.end - T.start) / T.step + 1e-9) + 1;
          if (n > 45) return flash("That is " + n + " rows — the table holds 45. Use a bigger step.");
          T.rows = [];
          for (var k = 0; k < n; k++) {
            var x = T.start + k * T.step, y;
            try { y = E.evaluate(T.f, env({ vars: Object.assign({}, st.vars, { X: x }) })).v; } catch (err) { y = null; }
            T.rows.push([x, y]);
          }
          T.top = 0;
        } };
      })();
    }
    function tableHTML() {
      var T = st.table;
      return '<p class="cx-cap">f(X) = ' + esc(T.src) + ' <small>(AC to change f)</small></p><table class="cx-grid cx-table"><thead><tr><th></th><th>X</th><th>f(X)</th></tr></thead><tbody>' +
        T.rows.map(function (r, i) {
          return "<tr><th>" + (i + 1) + "</th><td>" + esc(fmtPlain(r[0])) + "</td><td>" + (r[1] == null ? "ERROR" : decHTML(E.formatDecimal(r[1], st.setup))) + "</td></tr>";
        }).join("") + "</tbody></table>";
    }

    // ── the keys ────────────────────────────────────────────────────────────
    var DIGIT = { "0": 1, "1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1, "9": 1 };
    var VAR_KEYS = { neg: "A", dms: "B", hyp: "C", sin: "D", cos: "E", tan: "F", rp: "X", sd: "Y", mplus: "M" };

    function press(key) {
      if (st.locked && key !== "ac" && key !== "on") return;
      if (st.flash) { st.flash = null; clearTimeout(flash.t); }
      var sh = st.shift, al = st.alpha;
      if (key === "shift") { st.shift = !st.shift; st.alpha = false; return draw(); }
      if (key === "alpha") { st.alpha = !st.alpha; st.shift = false; return draw(); }
      st.shift = st.alpha = false;

      // a menu takes digits (and AC to close)
      if (st.menu) {
        if (key === "ac" || key === "on") { st.menu = null; return draw(); }
        if (DIGIT[key]) {
          var idx = st.menu.items.findIndex(function (it, i) { return (it.key || String(i + 1)) === key; });
          if (idx < 0 && st.menu.items.length > 9) {
            // two-digit codes (CONST 01-14): collect the first digit
            st.menu.typed = (st.menu.typed || "") + key;
            idx = st.menu.items.findIndex(function (it) { return it.key === st.menu.typed; });
            if (idx < 0) { if (st.menu.typed.length >= 2) st.menu.typed = ""; return draw(); }
          }
          return pickMenu(idx);
        }
        if (key === "mode" && !sh) { st.menu = null; return draw(); }
        return draw();
      }

      // STO / RCL waiting for a variable key
      if (st.pending) {
        var vk = VAR_KEYS[key];
        var p = st.pending;
        st.pending = null;
        if (vk) {
          if (p === "sto") {
            var val = storeValue();
            if (val != null) { if (vk === "M") st.mem = val; else st.vars[vk] = val; store.save(st); st.shown = { v: val, ex: true, exact: E.exact(val, true), stored: vk }; flash(vk + " = " + esc(fmtPlain(val))); }
          } else {
            var cur = (vk === "M" ? st.mem : st.vars[vk]) || 0;
            st.shown = { v: cur, ex: true, exact: E.exact(cur, E.fraction(cur, 1e5, 1e-13) !== null) };
            st.ed.set([vk]);
          }
          return draw();
        }
        if (key === "ac") return draw();
      }

      if (st.prompt) {
        if (key === "ac" || key === "on") { st.prompt = null; return draw(); }
        if (key === "eq") { promptEnter(); return draw(); }
        if (key === "calc" || key === "integ" || key === "logab") return draw();
      }

      if (key === "on") { st.menu = st.prompt = null; st.shown = null; st.ed.clear(); st.hyp = false; return draw(); }
      if (key === "mode") { sh ? setupMenu() : modeMenu(); return; }

      // mode-specific key handling
      if (st.mode === "STAT" || st.mode === "EQN") { if (gridKey(key, sh, al)) return draw(); }
      if (st.mode === "BASE" && !st.prompt) { if (baseKey(key, sh, al)) return draw(); }
      if (st.mode === "TABLE" && st.table.rows && !st.prompt) {
        if (key === "ac") { st.table.rows = null; return draw(); }
        return draw();
      }

      // ALPHA layer
      if (al) {
        if (VAR_KEYS[key]) { insertTok(VAR_KEYS[key]); return draw(); }
        if (key === "calc") { insertTok("="); return draw(); }
        if (key === "exp") { insertTok("e"); return draw(); }
        if (key === "dot") { insertTok("RanInt#("); return draw(); }
      }
      if (sh) { if (shiftKey(key)) return draw(); }
      mainKey(key);
      draw();
    }

    function storeValue() {
      if (st.shown && !st.shown.err && st.shown.v != null) return st.shown.v;
      if (!st.ed.empty()) {
        try { var r = E.evaluate(E.parse(st.ed.root), env()); return r.v; } catch (err) { st.shown = { err: err }; return null; }
      }
      return st.ans.v;
    }

    function shiftKey(key) {
      var T = function (k, fill, absorb) { insertTpl(k, fill, absorb); return true; };
      var I = function (t) { insertTok(t); return true; };
      switch (key) {
        case "calc": startSolve(); return true;
        case "integ": return T("deriv");
        case "inv": return I("!");
        case "logab": return T("sum");
        case "frac": return T("mixed", null, true);
        case "sqrt": return T("root", { n: ["3"] });
        case "sq": return I("³");
        case "pow": return T("root");
        case "log": startTyping(false); activeEd().insert("1"); activeEd().insert("0"); activeEd().insertTemplate("pow"); return true;
        case "ln": startTyping(false); activeEd().insert("e"); activeEd().insertTemplate("pow"); return true;
        case "neg": flash("∠ (polar form) is for complex numbers — " + NOT_HERE); return true;
        case "dms": if (st.shown && !st.shown.err) { st.dms = false; } return true;
        case "hyp": return T("abs");
        case "sin": return I(st.hyp ? (st.hyp = false, "sinh⁻¹(") : "sin⁻¹(");
        case "cos": return I(st.hyp ? (st.hyp = false, "cosh⁻¹(") : "cos⁻¹(");
        case "tan": return I(st.hyp ? (st.hyp = false, "tanh⁻¹(") : "tan⁻¹(");
        case "rcl": st.pending = "sto"; return true;
        case "eng": if (st.shown && !st.shown.err && st.shown.base == null) { st.dms = false; st.eng = st.eng == null ? 0 : st.eng - 1; } return true;
        case "lp": return I("%");
        case "rp": return I(",");
        case "sd": if (st.shown && st.shown.exact && st.shown.exact.k === "frac") { st.mixedView = !st.mixedView; st.exactView = true; } return true;
        case "mplus": return memAdd(-1);
        case "7": constMenu(); return true;
        case "8": convMenu(); return true;
        case "9": clrMenu(); return true;
        case "del": return true;                                  // INS: the editor always inserts
        case "ac": st.shown = null; st.ed.clear(); return true;   // OFF: clears the screen here
        case "4": case "5": case "2": flash(({ 4: "MATRIX", 5: "VECTOR", 2: "CMPLX" })[key] + " — " + NOT_HERE); return true;
        case "6": funcMenu(); return true;
        case "1": if (st.mode === "STAT") { st.stat.view = st.stat.view === "res" ? "data" : "res"; } else flash("Press MODE 3 for statistics"); return true;
        case "3": if (st.mode === "BASE") baseLogicMenu(); else flash("Press MODE 4 for BASE-N"); return true;
        case "mul": return I("nPr");
        case "div": return I("nCr");
        case "add": return I("Pol(");
        case "sub": return I("Rec(");
        case "0": return I("Rnd(");
        case "dot": return I("Ran#");
        case "exp": return I("π");
        case "ans": return I("PreAns");
        case "eq": evaluateNow(true); return true;
      }
      return false;
    }

    function mainKey(key) {
      if (DIGIT[key]) {
        if (st.mode === "TABLE" && st.table.rows) return;
        insertTok(key); return;
      }
      switch (key) {
        case "dot": return insertTok(".");
        case "exp": return insertTok("E");
        case "add": return insertTok("+");
        case "sub": return insertTok("−");
        case "mul": return insertTok("×");
        case "div": return insertTok("÷");
        case "neg": startTyping(false); return activeEd().insert("−");
        case "lp": return insertTok("(");
        case "rp": return insertTok(")");
        case "ans": return insertTok("Ans");
        case "sq": return insertTok("²");
        case "inv": return insertTok("⁻¹");
        case "frac": return insertTpl("frac", null, true);
        case "sqrt": return insertTpl("sqrt");
        case "pow": return insertTpl("pow");
        case "logab": return insertTpl("logab");
        case "integ": return insertTpl("integ");
        case "log": return insertTok("log(");
        case "ln": return insertTok("ln(");
        case "hyp": st.hyp = !st.hyp; return;
        case "sin": case "cos": case "tan": {
          var h = st.hyp; st.hyp = false;
          return insertTok(key + (h ? "h" : "") + "(");
        }
        case "dms":
          if (st.shown && !st.shown.err && st.shown.base == null) { st.dms = !st.dms; st.eng = null; }
          return;
        case "rcl": st.pending = "rcl"; return;
        case "eng":
          if (st.shown && !st.shown.err && st.shown.base == null) { st.dms = false; st.eng = st.eng == null ? 0 : st.eng + 1; }
          return;
        case "sd":
          if (st.shown && !st.shown.err) {
            if (st.eng != null || st.dms) { st.eng = null; st.dms = false; return; }
            st.exactView = !st.exactView;
          }
          return;
        case "mplus": return memAdd(1);
        case "calc":
          if (st.mode === "TABLE") return tableStart();
          return startCalc();
        case "del": return del();
        case "ac": st.shown = null; st.ed.clear(); st.hyp = false; st.dms = false; st.eng = null; return;
        case "eq":
          if (st.mode === "TABLE") return tableStart();
          return evaluateNow(false);
        case "left": case "right": return arrow(key);
        case "up": case "down": return vertical(key === "up" ? -1 : 1);
      }
    }

    function memAdd(sign) {
      var v = storeValue();
      if (v == null) return true;
      if (!st.shown && !st.ed.empty()) {                      // like the real thing: M+ also shows the answer
        evaluateNow(false);
        if (st.shown && st.shown.err) return true;
        v = st.shown.v;
      }
      st.mem += sign * v;
      store.save(st);
      flash("M = " + esc(fmtPlain(st.mem)));
      return true;
    }
    function del() {
      var ed = activeEd();
      if (st.shown && !st.prompt) {                           // DEL on an answer: edit the calculation
        st.shown = null; st.eng = null; st.dms = false;
        ed.end();
        return;
      }
      ed.del();
    }
    function arrow(key) {
      var ed = activeEd();
      if (st.shown && !st.prompt) {
        st.shown = null; st.eng = null; st.dms = false;
        if (key === "left") ed.end(); else ed.home();
        return;
      }
      if (key === "left") ed.left(); else ed.right();
    }
    function vertical(dir) {
      var ed = activeEd();
      if (!st.shown && !st.prompt && ed.vertical(dir)) return;
      if (st.prompt) return;
      // replay: ▲ steps back through earlier calculations (never over half-typed work)
      if (!st.replay.length || !(st.shown || ed.empty() || st.rIdx >= 0)) return;
      if (st.shown || ed.empty()) st.rIdx = -1;
      var n = st.rIdx + (dir < 0 ? 1 : -1);
      if (n < 0 || n >= st.replay.length) return;
      st.rIdx = n;
      st.shown = null;
      ed.set(st.replay[n]);
    }

    function gridKey(key, sh, al) {
      if (st.mode === "EQN" && !st.eqn.type) { if (key === "ac") { eqnMenu(); return true; } return false; }
      var G = grid();
      if (sh && key === "1" && st.mode === "STAT") { G.view = G.view === "res" ? "data" : "res"; return true; }
      if (sh || al) {
        if (sh && key === "exp") { cellType("π"); return true; }
        if (sh && key === "mode") return false;
        return true;
      }
      if (DIGIT[key]) { cellType(key); return true; }
      switch (key) {
        case "dot": cellType("."); return true;
        case "neg": case "sub": cellType("−"); return true;
        case "exp": cellType("E"); return true;
        case "add": cellType("+"); return true;
        case "mul": cellType("×"); return true;
        case "div": cellType("÷"); return true;
        case "lp": cellType("("); return true;
        case "rp": cellType(")"); return true;
        case "ans": cellType("Ans"); return true;
        case "eq": cellEnter(); return true;
        case "del": cellDel(); return true;
        case "ac":
          if (G.buf !== "") { G.buf = ""; return true; }
          if (st.mode === "STAT") G.view = G.view === "res" ? "data" : "res";
          else if (G.view === "sol") G.view = "coef";
          return true;
        case "up": if (st.mode === "EQN" && G.view === "sol") return true; cellMove(-1, 0); return true;
        case "down": if (st.mode === "EQN" && G.view === "sol") return true; cellMove(1, 0); return true;
        case "left": cellMove(0, -1); return true;
        case "right": cellMove(0, 1); return true;
      }
      return true;
    }

    function baseKey(key, sh, al) {
      var BASEMAP = { sq: "DEC", pow: "HEX", log: "BIN", ln: "OCT" };
      if (!sh && !al && BASEMAP[key]) {
        st.base = BASEMAP[key];
        if (st.shown && st.shown.base != null) st.shown = { v: st.shown.v, base: st.shown.v };
        return true;
      }
      var HEXK = { neg: "A", dms: "B", hyp: "C", sin: "D", cos: "E", tan: "F" };
      if (!sh && !al && HEXK[key]) {
        if (st.base !== "HEX") { flash("A–F are hex digits: press x^ (HEX) first"); return true; }
        insertTok(HEXK[key]); return true;
      }
      if (sh && key === "3") { baseLogicMenu(); return true; }
      if (!sh && !al && DIGIT[key]) {
        var ok = { DEC: /[0-9]/, HEX: /[0-9]/, OCT: /[0-7]/, BIN: /[01]/ }[st.base];
        if (!ok.test(key)) { flash(key + " is not a " + st.base.toLowerCase() + " digit"); return true; }
        insertTok(key); return true;
      }
      if (!sh && !al && (key === "dot" || key === "exp" || key === "frac" || key === "sqrt" || key === "sin" ||
          key === "inv" || key === "logab" || key === "integ")) { flash("Whole numbers only in BASE-N"); return true; }
      return false;
    }

    // ── key input: pointer, keyboard ────────────────────────────────────────
    function onPointer(ev) {
      var menuBtn = ev.target.closest("[data-menu]");
      if (menuBtn) { pickMenu(+menuBtn.dataset.menu); return; }
      var soft = ev.target.closest("[data-soft]");
      if (soft) { softKey(soft.dataset.soft); return; }
      var cell = ev.target.closest("[data-cell]");
      if (cell) {
        var G = grid(), rc = cell.dataset.cell.split(",");
        if (G.buf !== "") cellEnter();
        G.sel = { r: +rc[0], c: +rc[1] };
        draw();
        return;
      }
      var b = ev.target.closest("[data-key]");
      if (!b) return;
      device.focus({ preventScroll: true });
      press(b.dataset.key);
    }
    function softKey(k) {
      var S = st.stat;
      if (k === "data") S.view = "data";
      else if (k === "res") { if (S.buf !== "") cellEnter(); S.view = "res"; }
      else if (k === "type") {
        S.type = S.type === "AB" ? "1" : "AB";
        S.sel.c = Math.min(S.sel.c, statCols().length - 1);
      } else if (k === "wipe" && confirm("Clear all the data?")) { S.rows = [{}]; S.sel = { r: 0, c: 0 }; S.buf = ""; S.est = ""; }
      draw();
    }
    device.addEventListener("click", onPointer);
    // keep the page from scrolling / selecting when the keys are tapped fast
    device.addEventListener("mousedown", function (ev) { if (ev.target.closest("[data-key]")) ev.preventDefault(); });

    var KB = {
      "0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
      ".": "dot", "+": "add", "-": "sub", "*": "mul", "(": "lp", ")": "rp", "Enter": "eq", "=": "eq",
      "Backspace": "del", "Delete": "del", "Escape": "ac", "ArrowLeft": "left", "ArrowRight": "right",
      "ArrowUp": "up", "ArrowDown": "down", "^": "pow", "/": "frac"
    };
    var KB_TOK = { "!": "!", "%": "%", ",": ",", "s": "sin(", "c": "cos(", "t": "tan(", "l": "log(", "n": "ln(",
                   "p": "π", "e": "e", "x": "X", "y": "Y", "m": "M", "A": "A", "B": "B", "C": "C", "D": "D", "E": "E", "F": "F",
                   "X": "X", "Y": "Y", "M": "M" };
    function onKeydown(ev) {
      var t = ev.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
      // in the dock (over a paper), only while the calculator has focus - the
      // annotation tools and the page have their own keys
      if (compact && !device.contains(document.activeElement)) return;
      if (!compact && !root.isConnected) return;
      var k = ev.key;
      if (KB[k]) {
        ev.preventDefault();
        if (k === "Escape" && (st.menu || st.prompt)) return press("ac");
        return press(KB[k]);
      }
      if (st.mode === "BASE" && /^[a-fA-F]$/.test(k)) { ev.preventDefault(); if (st.base === "HEX") insertTok(k.toUpperCase()); return draw(); }
      if (k === "r" && st.mode !== "BASE") { ev.preventDefault(); return press("sqrt"); }
      if (KB_TOK[k] && st.mode !== "BASE" && !st.menu) {
        ev.preventDefault();
        if (st.pending && /^[A-FXYM]$/.test(KB_TOK[k])) {
          var back = { A: "neg", B: "dms", C: "hyp", D: "sin", E: "cos", F: "tan", X: "rp", Y: "sd", M: "mplus" }[KB_TOK[k]];
          return press(back);
        }
        insertTok(KB_TOK[k]);
        return draw();
      }
    }
    document.addEventListener("keydown", onKeydown);
    if (compact) setTimeout(function () { if (root.isConnected) device.focus({ preventScroll: true }); }, 60);

    // ── variables strip (tap to use; STO then tap to store) ─────────────────
    function drawVars() {
      if (!varsEl) return;
      varsEl.innerHTML = '<button type="button" class="calc-sto' + (st.pending === "sto" ? " on" : "") +
        '" data-sto title="Store the answer in a variable (SHIFT RCL)">STO</button>' +
        ["A", "B", "C", "D", "E", "F", "X", "Y", "M"].map(function (n) {
          var v = n === "M" ? st.mem : st.vars[n];
          var has = v != null && v !== 0;
          return '<button type="button" class="calc-var' + (has ? " has" : "") + '" data-var="' + n +
            '" title="' + (st.pending === "sto" ? "Store in " + n : n + " = " + (has ? esc(fmtPlain(v)) : "0")) +
            '"><b>' + n + "</b><span>" + (has ? esc(E.formatDecimal(v, {}).mant.slice(0, 7) + (E.formatDecimal(v, {}).exp != null ? "e" + E.formatDecimal(v, {}).exp : "")) : "0") + "</span></button>";
        }).join("");
    }
    function onVars(ev) {
      if (ev.target.closest("[data-sto]")) { st.pending = st.pending === "sto" ? null : "sto"; draw(); return; }
      var b = ev.target.closest("[data-var]");
      if (!b || st.locked) return;
      var n = b.dataset.var;
      var back = { A: "neg", B: "dms", C: "hyp", D: "sin", E: "cos", F: "tan", X: "rp", Y: "sd", M: "mplus" }[n];
      if (st.pending === "sto") { press(back); return; }
      insertTok(n);
      draw();
      device.focus({ preventScroll: true });
    }
    if (varsEl) varsEl.addEventListener("click", onVars);

    // ── history ─────────────────────────────────────────────────────────────
    function drawHistory() {
      if (!histEl) return;
      var history = store.history();
      if (clearBtn) clearBtn.hidden = !history.length;
      if (!history.length) {
        histEl.innerHTML = '<p class="calc-hist-empty">Every = you press is kept here, newest first. ' +
          "Tap an answer to use it again, or ↺ to edit the calculation.</p>";
        return;
      }
      histEl.innerHTML = history.map(function (h, i) {
        return '<div class="calc-hist-row">' +
          '<button type="button" class="calc-hist-use" data-hist="' + i + '" title="Use this answer">' +
          '<span class="calc-hist-q">' + esc(h.q) + "</span>" +
          '<span class="calc-hist-a">= ' + esc(h.a) + "</span></button>" +
          '<button type="button" class="calc-hist-edit" data-hist-q="' + i + '" title="Edit this calculation" ' +
          'aria-label="Edit this calculation">↺</button></div>';
      }).join("");
    }
    function onHist(ev) {
      var history = store.history();
      var edit = ev.target.closest("[data-hist-q]");
      if (edit) {
        var q = history[+edit.dataset.histQ].q.replace(/\s+\[.*\]$/, "");
        try {
          if (st.mode !== "COMP") setMode("COMP");
          st.ed.set(E.fromText(q));
          st.shown = null;
        } catch (err) { flash("That one can't be edited here — " + esc(err.message)); }
        draw(); device.focus({ preventScroll: true });
        return;
      }
      var row = ev.target.closest("[data-hist]");
      if (!row) return;
      var a = history[+row.dataset.hist].a.replace(/^X = /, "");
      try {
        var seq = E.fromText(a.replace(/\s+/g, "").replace(/(\d)\s*(\d+)\/(\d+)$/, "$1+$2/$3"));
        startTyping(false);
        insertSeq(seq);
      } catch (err) { flash("That answer can't be pasted in"); }
      draw(); device.focus({ preventScroll: true });
    }
    function insertSeq(seq) {
      var ed = activeEd();
      var wrap = seq.length > 1 && seq.some(function (t) { return /^[+−×÷]$/.test(t); });
      if (wrap) ed.insert("(");
      seq.forEach(function (t) { ed.insert(t); });
      if (wrap) ed.insert(")");
    }
    if (histEl) histEl.addEventListener("click", onHist);
    function onClear() {
      if (!store.history().length || !confirm("Clear your calculator history?")) return;
      store.clear(st);
      drawHistory();
    }
    if (clearBtn) clearBtn.addEventListener("click", onClear);

    // ── syllabus rules ──────────────────────────────────────────────────────
    function showRule(syl) {
      var rule = CALC_RULES[syl];
      if (!rule) { banner.hidden = true; return; }
      var banned = rule.papers === "all" || (rule.papers && rule.papers.length);
      banner.hidden = false;
      banner.className = "calc-banner " + (banned ? "warn" : "ok");
      banner.innerHTML = '<div class="calc-banner-body"><strong>' + esc(SUBJECT_NAMES[syl] || syl) + "</strong> — " + esc(rule.note) + "</div>" +
        (banned ? '<button class="calc-lock-btn" data-lock>' + (st.locked ? "Unlock calculator" : "Practise without it") + "</button>" : "");
      var lock = banner.querySelector("[data-lock]");
      if (lock) lock.addEventListener("click", function () {
        st.locked = !st.locked;
        lock.textContent = st.locked ? "Unlock calculator" : "Practise without it";
        if (st.locked) st.flash = "Locked — this paper is non-calculator.";
        else st.flash = null;
        draw();
      });
    }

    var boardsEl = $("[data-calc-boards]"), subjectsEl = $("[data-calc-subjects]");
    var activeBoard = initBoard, activeCode = initCode;
    function renderBoardTabs() {
      if (!boardsEl) return;
      boardsEl.innerHTML = BOARD_GROUPS.map(function (bg) {
        return '<button class="fs-tab-btn' + (bg.level === activeBoard ? " on" : "") + '" data-clevel="' + bg.level + '">' + bg.level + "</button>";
      }).join("");
    }
    function renderSubjectTabs() {
      if (!subjectsEl) return;
      var bg = BOARD_GROUPS.filter(function (b) { return b.level === activeBoard; })[0];
      if (!bg) return;
      subjectsEl.innerHTML = '<button class="fs-subtab-btn' + (!activeCode ? " on" : "") + '" data-ccode="">All subjects</button>' +
        bg.codes.map(function (c) {
          return '<button class="fs-subtab-btn' + (c === activeCode ? " on" : "") + '" data-ccode="' + c + '">' +
            SHORT_NAMES[c] + ' <span class="fs-code-badge">' + c + "</span></button>";
        }).join("");
    }
    if (boardsEl) {
      renderBoardTabs(); renderSubjectTabs();
      boardsEl.addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-clevel]");
        if (!b) return;
        activeBoard = b.dataset.clevel; activeCode = null;
        renderBoardTabs(); renderSubjectTabs(); showRule("");
      });
      subjectsEl.addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-ccode]");
        if (!b) return;
        activeCode = b.dataset.ccode || null;
        renderSubjectTabs();
        if (ctx.set) ctx.set(activeCode || "");
        showRule(activeCode || "");
      });
    }
    if (activeCode) showRule(activeCode);
    var off = ctx.onChange ? ctx.onChange(function (syl) {
      if (syl && syl !== activeCode) {
        activeBoard = boardForCode(syl); activeCode = syl;
        renderBoardTabs(); renderSubjectTabs(); showRule(syl);
      }
    }) : function () {};

    drawHistory();
    draw();

    return function teardown() {
      document.removeEventListener("keydown", onKeydown);
      device.removeEventListener("click", onPointer);
      if (histEl) histEl.removeEventListener("click", onHist);
      if (clearBtn) clearBtn.removeEventListener("click", onClear);
      if (varsEl) varsEl.removeEventListener("click", onVars);
      clearTimeout(flash.t);
      off();
      root.innerHTML = "";
    };
  }

  if (window.PWT) window.PWT.register({ id: "calculator", name: "Calculator", icon: "🧮", mount: mount });
  // Kept for the tests and for anything that wants the engine on its own.
  window.PWTCalc = {
    calculate: function (src) { return E.calc(src, {}).v; },
    format: function (v) { return E.formatDecimal(v, {}).plain; }
  };
})();
