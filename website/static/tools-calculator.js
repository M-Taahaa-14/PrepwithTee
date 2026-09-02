/* PrepWithTee — scientific calculator (mountable widget).
 *
 * Two things make this different from any calculator in another browser tab:
 *   1. It knows the calculator rules of the student's syllabus. 4024 Paper 1,
 *      0580 Papers 1-2 and every Computer Science paper are non-calculator, so
 *      it says so and offers to lock itself rather than teach a bad habit.
 *   2. It renders itself into any container, so the same code is the
 *      calculator page and the calculator inside the practice dock.
 *
 * Expressions go through tokenise -> shunting-yard -> RPN. eval() is never
 * used: input arrives from the URL as well as the keypad, and a parser this
 * small is worth owning outright.
 */
(function () {
  "use strict";

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

  // ── Engine ──────────────────────────────────────────────────────────────
  var FUNCS = { sin: 1, cos: 1, tan: 1, "sin⁻¹": 1, "cos⁻¹": 1, "tan⁻¹": 1,
                log: 1, ln: 1, "√": 1, abs: 1, exp: 1 };
  var FUNC_NAMES = Object.keys(FUNCS).sort(function (a, b) { return b.length - a.length; });
  var OPS = { "+": { prec: 1, assoc: "L" }, "−": { prec: 1, assoc: "L" },
              "×": { prec: 2, assoc: "L" }, "÷": { prec: 2, assoc: "L" },
              "^": { prec: 4, assoc: "R" } };

  function tokenize(src) {
    var out = [], i = 0;
    var s = String(src).replace(/\*/g, "×").replace(/\//g, "÷")
      .replace(/-/g, "−").replace(/\s+/g, "");
    while (i < s.length) {
      var c = s[i];
      if (/[0-9.]/.test(c)) {
        var num = "";
        while (i < s.length && /[0-9.]/.test(s[i])) num += s[i++];
        if ((num.match(/\./g) || []).length > 1) throw new Error("Malformed number");
        out.push({ t: "num", v: parseFloat(num) });
        continue;
      }
      if (c === "π") { out.push({ t: "num", v: Math.PI }); i++; continue; }
      if (c === "e") { out.push({ t: "num", v: Math.E }); i++; continue; }
      var matched = null;
      for (var f = 0; f < FUNC_NAMES.length; f++) {
        if (s.startsWith(FUNC_NAMES[f], i)) { matched = FUNC_NAMES[f]; break; }
      }
      if (matched) { out.push({ t: "func", v: matched }); i += matched.length; continue; }
      if (OPS[c]) { out.push({ t: "op", v: c }); i++; continue; }
      if (c === "(" || c === ")") { out.push({ t: c }); i++; continue; }
      if (c === "!") { out.push({ t: "fact" }); i++; continue; }
      if (c === "%") { out.push({ t: "pct" }); i++; continue; }
      throw new Error("Unexpected character “" + c + "”");
    }
    return insertImplicitMultiply(markUnary(out));
  }

  function markUnary(toks) {
    var out = [];
    for (var i = 0; i < toks.length; i++) {
      var tk = toks[i], prev = out[out.length - 1];
      var unary = tk.t === "op" && tk.v === "−" &&
        (!prev || prev.t === "op" || prev.t === "(" || prev.t === "func");
      out.push(unary ? { t: "op", v: "neg" } : tk);
    }
    return out;
  }

  function insertImplicitMultiply(toks) {
    var out = [];
    for (var i = 0; i < toks.length; i++) {
      var a = toks[i], b = toks[i + 1];
      out.push(a);
      if (!b) continue;
      var endsValue = a.t === "num" || a.t === ")" || a.t === "fact" || a.t === "pct";
      var startsValue = b.t === "num" || b.t === "(" || b.t === "func";
      if (endsValue && startsValue) out.push({ t: "op", v: "×" });
    }
    return out;
  }

  function toRPN(toks) {
    var out = [], stack = [], UNARY = { prec: 5, assoc: "R" };
    toks.forEach(function (tk) {
      if (tk.t === "num" || tk.t === "fact" || tk.t === "pct") { out.push(tk); return; }
      if (tk.t === "func") { stack.push(tk); return; }
      if (tk.t === "op") {
        var o1 = tk.v === "neg" ? UNARY : OPS[tk.v];
        while (stack.length) {
          var top = stack[stack.length - 1];
          if (top.t === "func") { out.push(stack.pop()); continue; }
          if (top.t !== "op") break;
          var o2 = top.v === "neg" ? UNARY : OPS[top.v];
          if ((o1.assoc === "L" && o1.prec <= o2.prec) ||
              (o1.assoc === "R" && o1.prec < o2.prec)) out.push(stack.pop());
          else break;
        }
        stack.push(tk); return;
      }
      if (tk.t === "(") { stack.push(tk); return; }
      if (tk.t === ")") {
        while (stack.length && stack[stack.length - 1].t !== "(") out.push(stack.pop());
        if (!stack.length) throw new Error("Unmatched )");
        stack.pop();
        if (stack.length && stack[stack.length - 1].t === "func") out.push(stack.pop());
      }
    });
    while (stack.length) {
      var t = stack.pop();
      if (t.t === "(") throw new Error("Unmatched (");
      out.push(t);
    }
    return out;
  }

  function factorial(n) {
    if (n < 0 || Math.floor(n) !== n) throw new Error("Factorial needs a whole number ≥ 0");
    if (n > 170) throw new Error("Too large");
    var r = 1;
    for (var i = 2; i <= n; i++) r *= i;
    return r;
  }

  function pop(st) {
    if (!st.length) throw new Error("Incomplete expression");
    return st.pop();
  }

  function evalRPN(rpn, deg) {
    var st = [];
    var toRad = function (x) { return deg ? x * Math.PI / 180 : x; };
    var fromRad = function (x) { return deg ? x * 180 / Math.PI : x; };
    rpn.forEach(function (tk) {
      if (tk.t === "num") { st.push(tk.v); return; }
      if (tk.t === "fact") { st.push(factorial(pop(st))); return; }
      if (tk.t === "pct") { st.push(pop(st) / 100); return; }
      if (tk.t === "func") {
        var x = pop(st), r;
        switch (tk.v) {
          case "sin": r = Math.sin(toRad(x)); break;
          case "cos": r = Math.cos(toRad(x)); break;
          case "tan": r = Math.tan(toRad(x)); break;
          case "sin⁻¹": r = fromRad(Math.asin(x)); break;
          case "cos⁻¹": r = fromRad(Math.acos(x)); break;
          case "tan⁻¹": r = fromRad(Math.atan(x)); break;
          case "log": r = Math.log10(x); break;
          case "ln": r = Math.log(x); break;
          case "√": if (x < 0) throw new Error("√ of a negative number"); r = Math.sqrt(x); break;
          case "abs": r = Math.abs(x); break;
          case "exp": r = Math.exp(x); break;
          default: throw new Error("Unknown function");
        }
        if (Math.abs(r) < 1e-12) r = 0;   // tan 180 reads 0, not scientific dust
        st.push(r); return;
      }
      if (tk.t === "op") {
        if (tk.v === "neg") { st.push(-pop(st)); return; }
        var b = pop(st), a = pop(st);
        switch (tk.v) {
          case "+": st.push(a + b); break;
          case "−": st.push(a - b); break;
          case "×": st.push(a * b); break;
          case "÷":
            if (b === 0) throw new Error("Cannot divide by zero");
            st.push(a / b); break;
          case "^": st.push(Math.pow(a, b)); break;
        }
      }
    });
    if (st.length !== 1) throw new Error("Incomplete expression");
    return st[0];
  }

  function calculate(src, deg) {
    var v = evalRPN(toRPN(tokenize(src)), deg);
    if (!isFinite(v)) throw new Error("Result is not a finite number");
    return v;
  }

  function fmt(v, sf) {
    if (v === 0) return "0";
    var abs = Math.abs(v);
    if (abs >= 1e10 || abs < 1e-6) {
      return v.toExponential(Math.max(0, (sf || 3) - 1)).replace("e", " × 10^");
    }
    var r = Number(v.toPrecision(12));
    if (Number.isInteger(r)) return String(r);
    return String(Number(r.toPrecision(sf || 10)));
  }

  // ── Markup ──────────────────────────────────────────────────────────────
  var KEYPAD = [
    [["shift", "SHIFT", "k-fn"], ["mode", "DRG", "k-fn k-mode"], ["M+", "M+", "k-fn"],
     ["MR", "MR", "k-fn"], ["MC", "MC", "k-fn"]],
    [["sin(", "sin", "k-fn", "sin⁻¹(", "sin⁻¹"], ["cos(", "cos", "k-fn", "cos⁻¹(", "cos⁻¹"],
     ["tan(", "tan", "k-fn", "tan⁻¹(", "tan⁻¹"], ["(", "(", "k-op"], [")", ")", "k-op"]],
    [["^2", "x²", "k-fn", "^3", "x³"], ["^", "x^y", "k-fn"], ["√(", "√", "k-fn"],
     ["log(", "log", "k-fn", "exp(", "eˣ"], ["ln(", "ln", "k-fn"]],
    [["7", "7"], ["8", "8"], ["9", "9"], ["DEL", "DEL", "k-clear"], ["AC", "AC", "k-clear"]],
    [["4", "4"], ["5", "5"], ["6", "6"], ["×", "×", "k-op"], ["÷", "÷", "k-op"]],
    [["1", "1"], ["2", "2"], ["3", "3"], ["+", "+", "k-op"], ["−", "−", "k-op"]],
    [["0", "0"], [".", "."], ["π", "π", "k-fn", "!", "n!"],
     ["Ans", "Ans", "k-fn", "%", "%"], ["=", "=", "k-eq"]]
  ];

  function keypadHTML() {
    return KEYPAD.map(function (row) {
      return row.map(function (k) {
        var key = k[0], label = k[1], cls = k[2] || "";
        var sk = k[3], slabel = k[4];
        var inner = sk
          ? '<span class="main">' + label + '</span><span class="alt">' + slabel + "</span>"
          : label;
        return '<button class="' + cls + '" data-k="' + key.replace(/"/g, "&quot;") + '"' +
          (sk ? ' data-shift="' + sk.replace(/"/g, "&quot;") + '"' : "") + ">" + inner + "</button>";
      }).join("");
    }).join("");
  }

  // Board → subjects map (determines which tabs appear)
  var BOARD_GROUPS = [
    { level: "O Level", codes: ["4024", "5054", "5070", "2210"] },
    { level: "IGCSE",   codes: ["0580", "0625", "0620", "0478"] },
    { level: "A Level", codes: ["9709", "9702", "9618"] }
  ];

  // Short name without the board prefix
  var SHORT_NAMES = {
    "4024": "Maths D", "5054": "Physics", "5070": "Chemistry", "2210": "CS",
    "0580": "Maths",   "0625": "Physics", "0620": "Chemistry", "0478": "CS",
    "9709": "Maths",   "9702": "Physics", "9618": "CS"
  };

  function boardForCode(code) {
    for (var i = 0; i < BOARD_GROUPS.length; i++) {
      if (BOARD_GROUPS[i].codes.indexOf(code) >= 0) return BOARD_GROUPS[i].level;
    }
    return BOARD_GROUPS[0].level;
  }

  // ── Widget ──────────────────────────────────────────────────────────────
  function mount(root, opts) {
    var PWTx = window.PWT;
    var compact = opts && opts.mode === "dock";
    var ctx = (opts && opts.ctx) || { syllabus: null, onChange: function () { return function () {}; } };

    // Resolve initial board/code
    var initCode  = ctx.syllabus || null;
    var initBoard = initCode ? boardForCode(initCode) : BOARD_GROUPS[0].level;

    root.innerHTML =
      (compact ? "" :
        '<div class="fs-board-tabs calc-board-tabs" data-calc-boards></div>' +
        '<div class="fs-subject-tabs calc-subject-tabs" data-calc-subjects></div>') +
      '<div class="calc-banner" data-banner hidden></div>' +
      '<div class="calc-layout' + (compact ? " compact" : "") + '">' +
        '<div class="calc-body">' +
          '<div class="calc-screen">' +
            '<div class="calc-flags"><span data-mode>DEG</span>' +
              '<span class="calc-flag-m" data-mem hidden>M</span></div>' +
            '<div class="calc-expr" data-expr>0</div>' +
            '<div class="calc-result" data-result></div>' +
          "</div>" +
          '<div class="calc-keys" data-keys>' + keypadHTML() + "</div>" +
        "</div>" +
        (compact ? "" :
        '<aside class="calc-side"><h3>Working</h3><div data-history></div></aside>') +
      "</div>";

    var $ = function (sel) { return root.querySelector(sel); };
    var expr = $("[data-expr]"), resultEl = $("[data-result]"), keys = $("[data-keys]");
    var histEl = $("[data-history]"), banner = $("[data-banner]");
    var modeEl = $("[data-mode]"), memEl = $("[data-mem]");

    var state = { input: "", ans: 0, mem: 0, deg: true, shift: false,
                  locked: false, justEqualled: false };
    var history = [];

    function esc(s) { return PWTx ? PWTx.esc(s) : String(s); }

    function render() {
      expr.textContent = state.input || "0";
      expr.scrollLeft = expr.scrollWidth;
      modeEl.textContent = state.deg ? "DEG" : "RAD";
      memEl.hidden = state.mem === 0;
      keys.classList.toggle("shifted", state.shift);
      keys.classList.toggle("locked", state.locked);
    }

    function preview() {
      if (!state.input.trim()) { resultEl.textContent = ""; resultEl.className = "calc-result"; return; }
      try {
        resultEl.textContent = "= " + fmt(calculate(state.input, state.deg));
        resultEl.className = "calc-result";
      } catch (e) { resultEl.textContent = ""; resultEl.className = "calc-result"; }
    }

    function drawHistory() {
      if (!histEl) return;
      if (!history.length) {
        histEl.innerHTML = '<p class="calc-hist-empty">Your working shows up here.</p>';
        return;
      }
      histEl.innerHTML = history.map(function (h, i) {
        return '<button class="calc-hist-row" data-hist="' + i + '">' +
          '<span class="calc-hist-q">' + esc(h.q) + "</span>" +
          '<span class="calc-hist-a">= ' + esc(h.a) + "</span></button>";
      }).join("");
    }

    function commit() {
      if (!state.input.trim()) return;
      try {
        var v = calculate(state.input, state.deg);
        state.ans = v;
        history.unshift({ q: state.input, a: fmt(v) });
        if (history.length > 12) history.pop();
        drawHistory();
        resultEl.textContent = "= " + fmt(v);
        resultEl.className = "calc-result ok";
        // The answer stays on the entry line, the way real hardware behaves:
        // an operator next continues from it, a digit next starts a new sum.
        state.input = fmt(v);
        state.justEqualled = true;
      } catch (err) {
        resultEl.textContent = err.message;
        resultEl.className = "calc-result err";
      }
    }

    function press(k) {
      if (state.locked) return;
      if (state.justEqualled) {
        state.justEqualled = false;
        var fresh = /^[0-9.]$/.test(k) || k === "(" || k === "π" ||
                    /\($/.test(k) || k === "Ans" || k === "MR";
        if (fresh) { state.input = ""; resultEl.textContent = ""; }
      }
      switch (k) {
        case "AC": state.input = ""; resultEl.textContent = ""; break;
        case "DEL": state.input = state.input.slice(0, -1); break;
        case "=": commit(); render(); return;
        case "shift": state.shift = !state.shift; render(); return;
        case "mode": state.deg = !state.deg; preview(); render(); return;
        case "Ans": state.input += fmt(state.ans); break;
        case "M+": try { state.mem += calculate(state.input || "0", state.deg); } catch (e) {} break;
        case "MR": state.input += fmt(state.mem); break;
        case "MC": state.mem = 0; break;
        default: state.input += k;
      }
      if (state.shift && k !== "shift") state.shift = false;
      preview(); render();
    }

    function onKeys(ev) {
      var btn = ev.target.closest("button[data-k]");
      if (!btn) return;
      press((state.shift && btn.dataset.shift) ? btn.dataset.shift : btn.dataset.k);
    }
    keys.addEventListener("click", onKeys);

    function onHist(ev) {
      var row = ev.target.closest("[data-hist]");
      if (!row) return;
      state.input += history[+row.dataset.hist].a;
      preview(); render();
    }
    if (histEl) histEl.addEventListener("click", onHist);

    // Physical keyboard. Scoped so a calculator inside the dock does not eat
    // keystrokes meant for the page behind it.
    function onKeydown(ev) {
      var t = ev.target;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
      if (compact && !root.closest(".pwt-dock.open")) return;
      var k = ev.key;
      if (/^[0-9.]$/.test(k)) return press(k);
      if (k === "+") return press("+");
      if (k === "-") return press("−");
      if (k === "*") return press("×");
      if (k === "/") { ev.preventDefault(); return press("÷"); }
      if (k === "^") return press("^");
      if (k === "(" || k === ")") return press(k);
      if (k === "Enter" || k === "=") { ev.preventDefault(); return press("="); }
      if (k === "Backspace") { ev.preventDefault(); return press("DEL"); }
      if (k === "Escape" && !compact) return press("AC");
    }
    document.addEventListener("keydown", onKeydown);

    // ── Syllabus rules ────────────────────────────────────────────────────
    function showRule(syl) {
      var rule = CALC_RULES[syl];
      if (!rule) { banner.hidden = true; return; }
      var banned = rule.papers === "all" || (rule.papers && rule.papers.length);
      banner.hidden = false;
      banner.className = "calc-banner " + (banned ? "warn" : "ok");
      banner.innerHTML =
        '<div class="calc-banner-body"><strong>' + esc(SUBJECT_NAMES[syl] || syl) +
        "</strong> — " + esc(rule.note) + "</div>" +
        (banned ? '<button class="calc-lock-btn" data-lock>Practise without it</button>' : "");
      var lock = banner.querySelector("[data-lock]");
      if (lock) lock.addEventListener("click", function () {
        state.locked = !state.locked;
        lock.textContent = state.locked ? "Unlock calculator" : "Practise without it";
        resultEl.textContent = state.locked ? "Locked — this paper is non-calculator." : "";
        resultEl.className = "calc-result" + (state.locked ? " err" : "");
        render();
      });
    }

    // ── Board / subject tabs ──────────────────────────────────────────────
    var boardsEl   = $("[data-calc-boards]");
    var subjectsEl = $("[data-calc-subjects]");
    var activeBoard = initBoard;
    var activeCode  = initCode;

    function renderBoardTabs() {
      if (!boardsEl) return;
      boardsEl.innerHTML = BOARD_GROUPS.map(function (bg) {
        return '<button class="fs-tab-btn' + (bg.level === activeBoard ? " on" : "") + '" data-clevel="' + bg.level + '">' + bg.level + '</button>';
      }).join("");
    }

    function renderSubjectTabs() {
      if (!subjectsEl) return;
      var bg = BOARD_GROUPS.filter(function (b) { return b.level === activeBoard; })[0];
      if (!bg) return;
      subjectsEl.innerHTML =
        '<button class="fs-subtab-btn' + (!activeCode ? " on" : "") + '" data-ccode="">All subjects</button>' +
        bg.codes.map(function (c) {
          return '<button class="fs-subtab-btn' + (c === activeCode ? " on" : "") + '" data-ccode="' + c + '">' +
            SHORT_NAMES[c] + ' <span class="fs-code-badge">' + c + '</span></button>';
        }).join("");
    }

    function selectCode(code) {
      activeCode = code || null;
      renderSubjectTabs();
      if (ctx.set) ctx.set(code || "");
      showRule(code || "");
    }

    if (boardsEl) {
      renderBoardTabs();
      renderSubjectTabs();
      if (activeCode) showRule(activeCode);

      boardsEl.addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-clevel]");
        if (!b) return;
        activeBoard = b.dataset.clevel;
        activeCode = null;
        renderBoardTabs();
        renderSubjectTabs();
        showRule("");
      });

      subjectsEl.addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-ccode]");
        if (!b) return;
        selectCode(b.dataset.ccode);
      });
    }

    var off = ctx.onChange ? ctx.onChange(function (syl) {
      if (syl && syl !== activeCode) {
        activeBoard = boardForCode(syl);
        activeCode = syl;
        renderBoardTabs();
        renderSubjectTabs();
        showRule(syl);
      }
    }) : function () {};

    drawHistory();
    render();

    return function teardown() {
      document.removeEventListener("keydown", onKeydown);
      keys.removeEventListener("click", onKeys);
      if (histEl) histEl.removeEventListener("click", onHist);
      off();
      root.innerHTML = "";
    };
  }

  if (window.PWT) {
    window.PWT.register({ id: "calculator", name: "Calculator", icon: "🧮", mount: mount });
  }
  // Kept for the tests and for anything that wants the engine on its own.
  window.PWTCalc = { calculate: calculate, format: fmt };
})();
