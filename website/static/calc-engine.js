/* PrepWithTee — calculator engine (no DOM). Modelled on the Casio fx-991ES.
 *
 * Input is a TREE, the way a natural-display calculator holds it: a sequence of
 * items, where an item is either a key token ("7", "+", "sin(", "²", "π", "A")
 * or a template with slots you type into ({k:"frac", n:[...], d:[...]}).
 * Editor keeps a cursor inside that tree (which sequence, which position), so
 * ◀ ▶ walk in and out of fractions and roots like the real thing.
 *
 * parse() turns a sequence into an AST (Casio precedence: implicit
 * multiplication binds tighter than × ÷, so 1÷2π = 1/(2π); (−)2² = −4);
 * evaluate() gives {v, ex}: the number, and whether it came only from exact
 * steps (rationals, π, √, special angles). exact() then finds the textbook form
 * of an exact result (5/6, 2√3, (1+√5)/2, 3π/4) - S⇔D flips to the decimal.
 *
 * Also: SOLVE (Newton, then a sign-change scan + bisection), ∫ (adaptive
 * Simpson), d/dx, Σ, statistics (1-variable + y = a + bx), equations
 * (2 and 3 unknowns, quadratic, cubic incl. complex roots), BASE-N (32-bit).
 *
 * Works in the browser (window.PWTCalcEngine) and in Node (tests/unit).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PWTCalcEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ── Errors (the Casio names, with a hint a student can act on) ────────────
  function CalcError(kind, hint) {
    var e = new Error(kind + (hint ? " — " + hint : ""));
    e.kind = kind; e.hint = hint || "";
    return e;
  }
  var SYNTAX = function (h) { return CalcError("Syntax ERROR", h); };
  var MATH = function (h) { return CalcError("Math ERROR", h); };
  var ARG = function (h) { return CalcError("Argument ERROR", h); };

  // ── Tokens ────────────────────────────────────────────────────────────────
  // Functions open their own bracket, like the real keys; the closing bracket
  // may be left off at the end.
  var FUNCS = {
    "sin(": 1, "cos(": 1, "tan(": 1, "sin⁻¹(": 1, "cos⁻¹(": 1, "tan⁻¹(": 1,
    "sinh(": 1, "cosh(": 1, "tanh(": 1, "sinh⁻¹(": 1, "cosh⁻¹(": 1, "tanh⁻¹(": 1,
    "log(": 2, "ln(": 1, "√(": 1, "∛(": 1, "Abs(": 1, "Int(": 1, "Intg(": 1, "Rnd(": 1,
    "root(": 2, "Pol(": 2, "Rec(": 2, "GCD(": 2, "LCM(": 2, "RanInt#(": 2,
    "∫(": 3, "d/dx(": 2, "Σ(": 3,
  };
  var POSTFIX = { "²": 1, "³": 1, "⁻¹": 1, "!": 1, "%": 1 };
  var VARS = ["A", "B", "C", "D", "E", "F", "X", "Y", "M"];
  // Cambridge data-sheet values (9702 / 5054 / 0625), so answers match the mark scheme.
  var CONSTS = {
    "g":  { v: 9.81, name: "acceleration of free fall", unit: "m s⁻²" },
    "c₀": { v: 3.00e8, name: "speed of light in free space", unit: "m s⁻¹" },
    "e₀": { v: 1.60e-19, name: "elementary charge", unit: "C" },
    "h":  { v: 6.63e-34, name: "Planck constant", unit: "J s" },
    "mₑ": { v: 9.11e-31, name: "rest mass of electron", unit: "kg" },
    "mₚ": { v: 1.67e-27, name: "rest mass of proton", unit: "kg" },
    "u":  { v: 1.66e-27, name: "unified atomic mass unit", unit: "kg" },
    "Nₐ": { v: 6.02e23, name: "Avogadro constant", unit: "mol⁻¹" },
    "R":  { v: 8.31, name: "molar gas constant", unit: "J K⁻¹ mol⁻¹" },
    "k":  { v: 1.38e-23, name: "Boltzmann constant", unit: "J K⁻¹" },
    "G":  { v: 6.67e-11, name: "gravitational constant", unit: "N m² kg⁻²" },
    "ε₀": { v: 8.85e-12, name: "permittivity of free space", unit: "F m⁻¹" },
    "σ":  { v: 5.67e-8, name: "Stefan–Boltzmann constant", unit: "W m⁻² K⁻⁴" },
    "Vₘ": { v: 24.0, name: "molar gas volume at r.t.p.", unit: "dm³ mol⁻¹" },
  };
  // CONV: a postfix that converts the value before it.
  var CONVS = {
    "km/h▸m/s": function (x) { return x / 3.6; },
    "m/s▸km/h": function (x) { return x * 3.6; },
    "°C▸K": function (x) { return x + 273; },
    "K▸°C": function (x) { return x - 273; },
    "°C▸°F": function (x) { return x * 9 / 5 + 32; },
    "°F▸°C": function (x) { return (x - 32) * 5 / 9; },
    "kWh▸J": function (x) { return x * 3.6e6; },
    "J▸kWh": function (x) { return x / 3.6e6; },
    "eV▸J": function (x) { return x * 1.60e-19; },
    "J▸eV": function (x) { return x / 1.60e-19; },
    "cm³▸dm³": function (x) { return x / 1000; },
    "dm³▸cm³": function (x) { return x * 1000; },
    "mmHg▸Pa": function (x) { return x * 133.322; },
    "atm▸Pa": function (x) { return x * 101325; },
  };
  var SLOTS = {
    frac: ["n", "d"], mixed: ["w", "n", "d"], sqrt: ["a"], root: ["n", "a"], pow: ["e"],
    logab: ["b", "a"], abs: ["a"], integ: ["f", "lo", "hi"], deriv: ["f", "at"], sum: ["f", "lo", "hi"],
  };
  var isTpl = function (it) { return it && typeof it === "object"; };
  var isDigit = function (s) { return typeof s === "string" && /^[0-9.]$/.test(s); };

  function template(k, fill) {
    var t = { k: k };
    SLOTS[k].forEach(function (s) { t[s] = (fill && fill[s]) ? fill[s].slice() : []; });
    return t;
  }

  function clone(seq) {
    return seq.map(function (it) {
      if (!isTpl(it)) return it;
      var t = { k: it.k };
      SLOTS[it.k].forEach(function (s) { t[s] = clone(it[s]); });
      return t;
    });
  }

  // ── Editor: the tree + a cursor ───────────────────────────────────────────
  // cur.path = [[itemIndex, slotName], ...] from the root sequence down to the
  // sequence the cursor is in; cur.i = the insertion point in that sequence.
  function Editor(seq) {
    this.root = seq ? clone(seq) : [];
    this.cur = { path: [], i: this.root.length };
  }
  Editor.prototype.seqAt = function (path) {
    var s = this.root;
    for (var j = 0; j < path.length; j++) s = s[path[j][0]][path[j][1]];
    return s;
  };
  Editor.prototype.seq = function () { return this.seqAt(this.cur.path); };
  Editor.prototype.empty = function () { return this.root.length === 0; };
  Editor.prototype.clear = function () { this.root = []; this.cur = { path: [], i: 0 }; };
  Editor.prototype.set = function (seq) { this.root = clone(seq); this.cur = { path: [], i: this.root.length }; };
  Editor.prototype.home = function () { this.cur = { path: [], i: 0 }; };
  Editor.prototype.end = function () { this.cur = { path: [], i: this.root.length }; };

  Editor.prototype.insert = function (tok) {
    var s = this.seq();
    s.splice(this.cur.i, 0, tok);
    this.cur.i++;
  };

  /** The run of items just before the cursor that forms one operand: a number,
   *  a bracketed group, a variable/constant, a template, with any postfixes. */
  Editor.prototype._operandBefore = function () {
    var s = this.seq(), j = this.cur.i;
    var start = j;
    while (start > 0 && (POSTFIX[s[start - 1]] || (isTpl(s[start - 1]) && s[start - 1].k === "pow"))) start--;
    if (start === 0) return j === start ? 0 : j - start;
    var it = s[start - 1];
    if (isDigit(it) || it === "E") {
      while (start > 0 && (isDigit(s[start - 1]) || s[start - 1] === "E" ||
             (s[start - 1] === "−" && s[start - 2] === "E"))) start--;
    } else if (it === ")") {
      var depth = 0;
      for (var k = start - 1; k >= 0; k--) {
        if (s[k] === ")") depth++;
        else if (s[k] === "(" || (typeof s[k] === "string" && FUNCS[s[k]])) {
          depth--;
          if (depth === 0) { start = k; break; }
        }
      }
      if (depth !== 0) return 0;
    } else if (isTpl(it) || VARS.indexOf(it) >= 0 || CONSTS[it] || it === "π" || it === "e" || it === "Ans") {
      start--;
    } else return 0;
    return j - start;
  };

  /** Insert a template. absorb: the operand before the cursor becomes the first
   *  slot (2 then ■/□ -> 2 over an empty denominator). */
  Editor.prototype.insertTemplate = function (k, fill, absorb) {
    var t = template(k, fill);
    var s = this.seq();
    var slots = SLOTS[k];
    if (absorb) {
      var n = this._operandBefore();
      if (n > 0) {
        t[slots[0]] = s.splice(this.cur.i - n, n);
        this.cur.i -= n;
      }
    }
    s.splice(this.cur.i, 0, t);
    // cursor into the first empty slot (or after the template if all are full)
    var idx = this.cur.i;
    for (var q = 0; q < slots.length; q++) {
      if (!t[slots[q]].length) {
        this.cur = { path: this.cur.path.concat([[idx, slots[q]]]), i: 0 };
        return;
      }
    }
    this.cur.i = idx + 1;
  };

  Editor.prototype.right = function () {
    var s = this.seq(), c = this.cur;
    if (c.i < s.length) {
      var it = s[c.i];
      if (isTpl(it)) { this.cur = { path: c.path.concat([[c.i, SLOTS[it.k][0]]]), i: 0 }; return; }
      c.i++; return;
    }
    if (!c.path.length) { this.home(); return; }            // wrap round, as on the calculator
    var last = c.path[c.path.length - 1], parentPath = c.path.slice(0, -1);
    var tpl = this.seqAt(parentPath)[last[0]], slots = SLOTS[tpl.k];
    var n = slots.indexOf(last[1]);
    if (n < slots.length - 1) this.cur = { path: parentPath.concat([[last[0], slots[n + 1]]]), i: 0 };
    else this.cur = { path: parentPath, i: last[0] + 1 };
  };

  Editor.prototype.left = function () {
    var s = this.seq(), c = this.cur;
    if (c.i > 0) {
      var it = s[c.i - 1];
      if (isTpl(it)) {
        var sl = SLOTS[it.k], lastSlot = sl[sl.length - 1];
        this.cur = { path: c.path.concat([[c.i - 1, lastSlot]]), i: it[lastSlot].length };
        return;
      }
      c.i--; return;
    }
    if (!c.path.length) { this.end(); return; }
    var last = c.path[c.path.length - 1], parentPath = c.path.slice(0, -1);
    var tpl = this.seqAt(parentPath)[last[0]], slots = SLOTS[tpl.k];
    var n = slots.indexOf(last[1]);
    if (n > 0) this.cur = { path: parentPath.concat([[last[0], slots[n - 1]]]), i: tpl[slots[n - 1]].length };
    else this.cur = { path: parentPath, i: last[0] };
  };

  /** ▲ / ▼ inside a fraction (numerator <-> denominator). false = nothing to do. */
  Editor.prototype.vertical = function (dir) {
    for (var j = this.cur.path.length - 1; j >= 0; j--) {
      var p = this.cur.path.slice(0, j), step = this.cur.path[j];
      var tpl = this.seqAt(p)[step[0]];
      if (tpl.k === "frac" || tpl.k === "mixed") {
        var to = dir < 0 ? "n" : "d";
        if (step[1] === to) return false;
        if (step[1] === "w") continue;
        this.cur = { path: p.concat([[step[0], to]]), i: Math.min(this.cur.i, tpl[to].length) };
        return true;
      }
    }
    return false;
  };

  Editor.prototype.del = function () {
    var s = this.seq(), c = this.cur;
    if (c.i > 0) {
      var it = s[c.i - 1];
      if (isTpl(it) && SLOTS[it.k].some(function (k) { return it[k].length; })) {
        this.left();                                           // step inside; DEL again deletes there
        return;
      }
      s.splice(c.i - 1, 1);
      c.i--;
      return;
    }
    if (!c.path.length) return;
    // at the start of a slot: remove the template, keep what was typed in it
    var last = c.path[c.path.length - 1], parentPath = c.path.slice(0, -1);
    var ps = this.seqAt(parentPath), tpl = ps[last[0]];
    var keep = [];
    SLOTS[tpl.k].forEach(function (k) { keep = keep.concat(tpl[k]); });
    ps.splice.apply(ps, [last[0], 1].concat(keep));
    this.cur = { path: parentPath, i: last[0] };
  };

  // ── Linear text (history, LineIO display, pasting) ────────────────────────
  var SIMPLE = /^[0-9.]+$/;
  function lin(seq) {
    var out = "";
    seq.forEach(function (it, i) {
      if (!isTpl(it)) {
        if (it === "E") out += "×10^";
        else if (CONVS[it]) out += " " + it;
        else out += it;
        return;
      }
      var p = function (s) { var t = lin(s); return SIMPLE.test(t) || /^[A-Z]$/.test(t) ? t : "(" + t + ")"; };
      var alone = seq.length === 1;
      switch (it.k) {
        case "frac": out += (alone ? "" : "(") + p(it.n) + "/" + p(it.d) + (alone ? "" : ")"); break;
        case "mixed": out += "(" + lin(it.w) + "+" + p(it.n) + "/" + p(it.d) + ")"; break;
        case "sqrt": out += "√(" + lin(it.a) + ")"; break;
        case "root": out += "root(" + lin(it.n) + "," + lin(it.a) + ")"; break;
        case "pow": out += "^" + p(it.e); break;
        case "logab": out += "log(" + lin(it.b) + "," + lin(it.a) + ")"; break;
        case "abs": out += "Abs(" + lin(it.a) + ")"; break;
        case "integ": out += "∫(" + lin(it.f) + "," + lin(it.lo) + "," + lin(it.hi) + ")"; break;
        case "deriv": out += "d/dx(" + lin(it.f) + "," + lin(it.at) + ")"; break;
        case "sum": out += "Σ(" + lin(it.f) + "," + lin(it.lo) + "," + lin(it.hi) + ")"; break;
      }
      void i;
    });
    return out;
  }

  var TEXT_TOKENS = Object.keys(FUNCS).concat(Object.keys(POSTFIX), Object.keys(CONSTS), Object.keys(CONVS),
    ["×10^", "Ans", "PreAns", "Ran#", "nPr", "nCr", "π", "e", "+", "−", "×", "÷", "(", ")", ",", "^", "="])
    .concat(VARS).sort(function (a, b) { return b.length - a.length; });

  /** Text -> a flat sequence (no templates). Accepts what lin() writes, plus
   *  keyboard spellings: * / - sqrt pi. */
  function fromText(src) {
    var s = String(src).replace(/\*/g, "×").replace(/\//g, "÷").replace(/-/g, "−")
      .replace(/sqrt\(/g, "√(").replace(/pi/g, "π").replace(/asin\(/g, "sin⁻¹(")
      .replace(/acos\(/g, "cos⁻¹(").replace(/atan\(/g, "tan⁻¹(").replace(/\s+/g, "");
    // d÷dx( came from the "/" rewrite
    s = s.replace(/d÷dx\(/g, "d/dx(").replace(/km÷h▸m÷s/g, "km/h▸m/s").replace(/m÷s▸km÷h/g, "m/s▸km/h");
    var out = [], i = 0;
    while (i < s.length) {
      if (/[0-9.]/.test(s[i])) { out.push(s[i]); i++; continue; }
      var hit = null;
      for (var k = 0; k < TEXT_TOKENS.length; k++) if (s.startsWith(TEXT_TOKENS[k], i)) { hit = TEXT_TOKENS[k]; break; }
      if (!hit) throw SYNTAX("I can't read “" + s[i] + "”");
      out.push(hit === "×10^" ? "E" : hit);
      i += hit.length;
    }
    return out;
  }

  // ── Parser: sequence -> AST ────────────────────────────────────────────────
  // AST nodes: {t:"num", v, ex} {t:"var", n} {t:"const", n} {t:"ans"} {t:"ran"}
  // {t:"neg", a} {t:"bin", op, a, b} {t:"post", op, a} {t:"fn", f, args}
  // {t:"tpl", k, ...} {t:"eq", a, b}
  function Parser(seq) { this.s = seq; this.i = 0; }
  Parser.prototype.peek = function () { return this.s[this.i]; };
  Parser.prototype.next = function () { return this.s[this.i++]; };
  Parser.prototype.done = function () { return this.i >= this.s.length; };

  function parse(seq) {
    var p = new Parser(seq);
    if (p.done()) throw SYNTAX("Type a calculation first");
    var a = p.expr();
    if (p.peek() === "=") { p.next(); var b = p.expr(); a = { t: "eq", a: a, b: b }; }
    if (!p.done()) {
      var bad = p.peek();
      throw SYNTAX(bad === ")" ? "There is a ) without a matching (" : "Something is out of place near “" + (isTpl(bad) ? "…" : bad) + "”");
    }
    return a;
  }

  Parser.prototype.expr = function () {
    var a = this.term();
    for (;;) {
      var t = this.peek();
      if (t === "+" || t === "−") { this.next(); a = { t: "bin", op: t, a: a, b: this.term() }; }
      else return a;
    }
  };
  Parser.prototype.term = function () {
    var a = this.perm();
    for (;;) {
      var t = this.peek();
      if (t === "×" || t === "÷") { this.next(); a = { t: "bin", op: t, a: a, b: this.perm() }; }
      else return a;
    }
  };
  Parser.prototype.perm = function () {
    var a = this.implicit();
    for (;;) {
      var t = this.peek();
      if (t === "nPr" || t === "nCr") { this.next(); a = { t: "bin", op: t, a: a, b: this.implicit() }; }
      else return a;
    }
  };
  var startsAtom = function (t) {
    return t !== undefined && ((isTpl(t) && t.k !== "pow") || isDigit(t) || t === "(" || FUNCS[t] ||
      VARS.indexOf(t) >= 0 || CONSTS[t] || t === "π" || t === "e" || t === "Ans" || t === "PreAns" || t === "Ran#");
  };
  Parser.prototype.implicit = function () {
    var a = this.unary();
    while (startsAtom(this.peek())) a = { t: "bin", op: "·", a: a, b: this.unary() };
    return a;
  };
  Parser.prototype.unary = function () {
    var t = this.peek();
    if (t === "−") { this.next(); return { t: "neg", a: this.unary() }; }
    if (t === "+") { this.next(); return this.unary(); }
    return this.power();
  };
  Parser.prototype.power = function () {
    var a = this.postfix(this.atom());
    for (;;) {
      var t = this.peek();
      if (isTpl(t) && t.k === "pow") { this.next(); a = this.postfix({ t: "bin", op: "^", a: a, b: sub(t.e) }); }
      else if (t === "^") {
        this.next();
        var neg = false;
        if (this.peek() === "−") { this.next(); neg = true; }
        var b = this.power();                                  // right-assoc: 2^3^2 = 2^9
        a = { t: "bin", op: "^", a: a, b: neg ? { t: "neg", a: b } : b };
      } else return a;
    }
  };
  Parser.prototype.postfix = function (a) {
    for (;;) {
      var t = this.peek();
      if (POSTFIX[t] || CONVS[t]) { this.next(); a = { t: "post", op: t, a: a }; }
      else return a;
    }
  };
  Parser.prototype.number = function () {
    var txt = "";
    while (isDigit(this.peek())) txt += this.next();
    if (this.peek() === "E") {
      this.next();
      var sign = "";
      if (this.peek() === "−") { this.next(); sign = "-"; }
      var ex = "";
      while (/^[0-9]$/.test(this.peek() || "")) ex += this.next();
      if (!ex) throw SYNTAX("×10ˣ needs a power after it");
      if (!txt) txt = "1";
      txt += "e" + sign + ex;
    }
    if ((txt.match(/\./g) || []).length > 1) throw SYNTAX("A number has two decimal points");
    if (txt === "." ) throw SYNTAX("A decimal point on its own");
    return { t: "num", v: parseFloat(txt), ex: true };
  };
  Parser.prototype.args = function (n) {
    var list = [this.expr()];
    while (this.peek() === ",") { this.next(); list.push(this.expr()); }
    if (this.peek() === ")") this.next();
    else if (!this.done()) throw SYNTAX("Missing )");
    if (n && list.length > n) throw SYNTAX("Too many values in the brackets");
    return list;
  };
  Parser.prototype.atom = function () {
    var t = this.peek();
    if (t === undefined) throw SYNTAX("The calculation stops too early");
    if (isDigit(t) || t === "E") return this.number();
    if (t === "(") {
      this.next();
      var e = this.expr();
      if (this.peek() === ")") this.next();
      else if (!this.done()) throw SYNTAX("Missing )");
      return e;
    }
    if (FUNCS[t]) {
      this.next();
      var args = this.args(FUNCS[t]);
      if (t === "log(" && args.length === 2) return { t: "tpl", k: "logab", b: args[0], a: args[1] };
      if (t !== "log(" && args.length !== FUNCS[t]) throw SYNTAX(t.slice(0, -1) + " needs " + FUNCS[t] + " value" + (FUNCS[t] > 1 ? "s" : ""));
      return { t: "fn", f: t.slice(0, -1), args: args };
    }
    if (isTpl(t)) {
      this.next();
      var o = { t: "tpl", k: t.k };
      SLOTS[t.k].forEach(function (s) { o[s] = t[s].length ? sub(t[s]) : null; });
      return o;
    }
    this.next();
    if (VARS.indexOf(t) >= 0) return { t: "var", n: t };
    if (CONSTS[t]) return { t: "num", v: CONSTS[t].v, ex: false };
    if (t === "π") return { t: "pi" };
    if (t === "e") return { t: "num", v: Math.E, ex: false };
    if (t === "Ans") return { t: "ans" };
    if (t === "PreAns") return { t: "preans" };
    if (t === "Ran#") return { t: "ran" };
    throw SYNTAX(t === ")" ? "There is a ) without a matching (" : "“" + t + "” can't go there");
  };
  function sub(seq) {
    var p = new Parser(seq);
    if (p.done()) throw SYNTAX("A box is still empty");
    var a = p.expr();
    if (!p.done()) throw SYNTAX("Something is out of place inside a box");
    return a;
  }

  // ── Evaluation ────────────────────────────────────────────────────────────
  var EPS = 1e-9;
  var isInt = function (x) { return Math.abs(x - Math.round(x)) < 1e-9 * Math.max(1, Math.abs(x)); };
  function V(v, ex) {
    if (typeof v !== "number" || isNaN(v)) throw MATH("The answer is not a real number");
    if (!isFinite(v)) throw MATH("The answer is too big (or you divided by 0)");
    return { v: Math.abs(v) < 1e-15 ? 0 : v, ex: !!ex };
  }
  function toRad(x, unit) { return unit === "rad" ? x : unit === "gra" ? x * Math.PI / 200 : x * Math.PI / 180; }
  function fromRad(x, unit) { return unit === "rad" ? x : unit === "gra" ? x * 200 / Math.PI : x * 180 / Math.PI; }
  /** Is this angle a multiple of 15° (π/12)? Then sin/cos/tan have exact values. */
  function specialAngle(x, unit) {
    var deg = unit === "rad" ? x * 180 / Math.PI : unit === "gra" ? x * 0.9 : x;
    return isInt(deg / 15);
  }
  function fact(n) {
    if (n < 0 || !isInt(n)) throw MATH("x! needs a whole number ≥ 0");
    n = Math.round(n);
    if (n > 170) throw MATH("Too big for the calculator");
    var r = 1;
    for (var i = 2; i <= n; i++) r *= i;
    return r;
  }
  function nCr(n, r) {
    if (!isInt(n) || !isInt(r) || n < 0 || r < 0 || r > n) throw MATH("nCr needs whole numbers with r ≤ n");
    n = Math.round(n); r = Math.round(r);
    r = Math.min(r, n - r);
    var out = 1;
    for (var i = 1; i <= r; i++) out = out * (n - r + i) / i;
    return Math.round(out);
  }
  function nPr(n, r) {
    if (!isInt(n) || !isInt(r) || n < 0 || r < 0 || r > n) throw MATH("nPr needs whole numbers with r ≤ n");
    var out = 1;
    for (var i = 0; i < Math.round(r); i++) out *= Math.round(n) - i;
    return out;
  }
  function gcd(a, b) {
    a = Math.abs(Math.round(a)); b = Math.abs(Math.round(b));
    while (b) { var t = a % b; a = b; b = t; }
    return a;
  }

  function evaluate(node, env) {
    env = env || {};
    var unit = env.angle || "deg";
    var ev = function (n) { return evaluate(n, env); };
    switch (node.t) {
      case "num": return V(node.v, node.ex);
      case "pi": return V(Math.PI, true);
      case "var": {
        var val = (env.vars || {})[node.n];
        val = val == null ? 0 : val;
        return V(val, typeof val === "number" && fraction(val, 10000) !== null);
      }
      case "ans": return V(env.ans ? env.ans.v : 0, env.ans ? env.ans.ex : true);
      case "preans": return V(env.preAns ? env.preAns.v : 0, env.preAns ? env.preAns.ex : true);
      case "ran": return V(Math.round(Math.random() * 1000) / 1000, false);
      case "neg": { var a0 = ev(node.a); return V(-a0.v, a0.ex); }
      case "eq": {                                              // L − R (SOLVE finds where it is 0)
        var l = ev(node.a), r = ev(node.b);
        return V(l.v - r.v, l.ex && r.ex);
      }
      case "post": {
        var x = ev(node.a);
        switch (node.op) {
          case "²": return V(x.v * x.v, x.ex);
          case "³": return V(x.v * x.v * x.v, x.ex);
          case "⁻¹": if (x.v === 0) throw MATH("1 ÷ 0"); return V(1 / x.v, x.ex);
          case "!": return V(fact(x.v), x.ex);
          case "%": return V(x.v / 100, x.ex);
        }
        if (CONVS[node.op]) return V(CONVS[node.op](x.v), false);
        throw SYNTAX();
      }
      case "bin": {
        var A = ev(node.a), B = ev(node.b), ex = A.ex && B.ex;
        switch (node.op) {
          case "+": return V(A.v + B.v, ex);
          case "−": return V(A.v - B.v, ex);
          case "×": case "·": return V(A.v * B.v, ex);
          case "÷": if (B.v === 0) throw MATH("You can't divide by 0"); return V(A.v / B.v, ex);
          case "nPr": return V(nPr(A.v, B.v), ex);
          case "nCr": return V(nCr(A.v, B.v), ex);
          case "^": {
            if (A.v < 0 && !isInt(B.v)) {
              // (−8)^(1/3) = −2: an odd root of a negative number is real
              var inv = 1 / B.v;
              if (isInt(inv) && Math.round(inv) % 2 !== 0) return V(-Math.pow(-A.v, B.v), false);
              throw MATH("A negative number to a fractional power");
            }
            if (A.v === 0 && B.v < 0) throw MATH("0 to a negative power");
            return V(Math.pow(A.v, B.v), ex && (isInt(B.v) || (isInt(2 * B.v) && A.v >= 0)));
          }
        }
        throw SYNTAX();
      }
      case "fn": return evalFn(node, env, ev, unit);
      case "tpl": return evalTpl(node, env, ev);
    }
    throw SYNTAX();
  }

  function evalFn(node, env, ev, unit) {
    var f = node.f, args = node.args;
    if (f === "∫") return integrate(args[0], ev(args[1]).v, ev(args[2]).v, env);
    if (f === "d/dx") return derivative(args[0], ev(args[1]).v, env);
    if (f === "Σ") return sigma(args[0], ev(args[1]).v, ev(args[2]).v, env);
    var vals = args.map(ev), x = vals[0], v = x.v;
    switch (f) {
      case "sin": case "cos": case "tan": {
        var sp = x.ex && specialAngle(v, unit), rad = toRad(v, unit);
        if (f === "tan" && sp && isInt((unit === "rad" ? v * 180 / Math.PI : unit === "gra" ? v * 0.9 : v) / 90) &&
            Math.round((unit === "rad" ? v * 180 / Math.PI : unit === "gra" ? v * 0.9 : v) / 90) % 2 !== 0) {
          throw MATH("tan 90° is undefined");
        }
        var r = f === "sin" ? Math.sin(rad) : f === "cos" ? Math.cos(rad) : Math.tan(rad);
        if (sp) r = snapSpecial(r);
        return V(r, sp);
      }
      case "sin⁻¹": case "cos⁻¹": {
        if (v < -1 - EPS || v > 1 + EPS) throw MATH(f + " needs a value from −1 to 1");
        var c = Math.max(-1, Math.min(1, v));
        var ang = fromRad(f === "sin⁻¹" ? Math.asin(c) : Math.acos(c), unit);
        return V(ang, x.ex && specialAngle(ang, unit));
      }
      case "tan⁻¹": { var t = fromRad(Math.atan(v), unit); return V(t, x.ex && specialAngle(t, unit)); }
      case "sinh": return V(Math.sinh(v));
      case "cosh": return V(Math.cosh(v));
      case "tanh": return V(Math.tanh(v));
      case "sinh⁻¹": return V(Math.asinh(v));
      case "cosh⁻¹": if (v < 1) throw MATH("cosh⁻¹ needs a value ≥ 1"); return V(Math.acosh(v));
      case "tanh⁻¹": if (Math.abs(v) >= 1) throw MATH("tanh⁻¹ needs a value between −1 and 1"); return V(Math.atanh(v));
      case "log": { if (v <= 0) throw MATH("log needs a positive number"); var lg = Math.log10(v); return V(lg, x.ex && isInt(lg)); }
      case "ln": { if (v <= 0) throw MATH("ln needs a positive number"); return V(Math.log(v), false); }
      case "√": if (v < 0) throw MATH("√ of a negative number"); return V(Math.sqrt(v), x.ex);
      case "∛": return V(Math.cbrt(v), x.ex);
      case "root": {
        var n = v, a = vals[1].v;
        if (n === 0) throw MATH("A 0th root");
        if (a < 0) {
          if (!isInt(n) || Math.round(n) % 2 === 0) throw MATH("An even root of a negative number");
          return V(-Math.pow(-a, 1 / n), false);
        }
        var rr = Math.pow(a, 1 / n);
        if (isInt(rr)) rr = Math.round(rr);
        return V(rr, x.ex && vals[1].ex && isInt(rr));
      }
      case "Abs": return V(Math.abs(v), x.ex);
      case "Int": return V(Math.trunc(v), x.ex);
      case "Intg": return V(Math.floor(v), x.ex);
      case "Rnd": return V(Number(formatDecimal(v, env.setup || {}).plain), x.ex);
      case "GCD": return V(gcd(v, vals[1].v), true);
      case "LCM": { var g = gcd(v, vals[1].v); return V(g ? Math.abs(Math.round(v) * Math.round(vals[1].v)) / g : 0, true); }
      case "RanInt#": {
        var lo = Math.ceil(Math.min(v, vals[1].v)), hi = Math.floor(Math.max(v, vals[1].v));
        return V(lo + Math.floor(Math.random() * (hi - lo + 1)), true);
      }
      case "Pol": {                                             // (x, y) -> r, θ  (θ into Y, r into X)
        var rp = Math.hypot(v, vals[1].v), th = fromRad(Math.atan2(vals[1].v, v), unit);
        if (env.onPair) env.onPair({ X: rp, Y: th, labels: ["r", "θ"] });
        return V(rp, false);
      }
      case "Rec": {                                             // (r, θ) -> x, y
        var ang2 = toRad(vals[1].v, unit), xx = v * Math.cos(ang2), yy = v * Math.sin(ang2);
        if (env.onPair) env.onPair({ X: xx, Y: yy, labels: ["X", "Y"] });
        return V(xx, false);
      }
    }
    throw SYNTAX("Unknown function " + f);
  }

  function snapSpecial(r) {
    var KNOWN = [0, 0.5, Math.sqrt(2) / 2, Math.sqrt(3) / 2, 1, Math.sqrt(3), Math.sqrt(3) / 3,
                 2 - Math.sqrt(3), 2 + Math.sqrt(3), (Math.sqrt(6) - Math.sqrt(2)) / 4, (Math.sqrt(6) + Math.sqrt(2)) / 4];
    for (var i = 0; i < KNOWN.length; i++) {
      if (Math.abs(Math.abs(r) - KNOWN[i]) < 1e-12) return r < 0 ? -KNOWN[i] : KNOWN[i];
    }
    return r;
  }

  function evalTpl(n, env, ev) {
    var need = function (x, what) { if (!x) throw SYNTAX("The " + what + " box is empty"); return ev(x); };
    switch (n.k) {
      case "frac": {
        var a = need(n.n, "top"), b = need(n.d, "bottom");
        if (b.v === 0) throw MATH("The bottom of a fraction is 0");
        return V(a.v / b.v, a.ex && b.ex);
      }
      case "mixed": {
        var w = need(n.w, "whole number"), p = need(n.n, "top"), q = need(n.d, "bottom");
        if (q.v === 0) throw MATH("The bottom of a fraction is 0");
        var sgn = w.v < 0 ? -1 : 1;
        return V(w.v + sgn * p.v / q.v, w.ex && p.ex && q.ex);
      }
      case "sqrt": { var s = need(n.a, "√"); if (s.v < 0) throw MATH("√ of a negative number"); return V(Math.sqrt(s.v), s.ex); }
      case "root": return evalFn({ f: "root", args: [n.n || { t: "num", v: 2, ex: true }, n.a || { t: "num", v: NaN }] }, env, ev, env.angle);
      case "logab": {
        var base = need(n.b, "base"), arg = need(n.a, "log");
        if (base.v <= 0 || base.v === 1 || arg.v <= 0) throw MATH("log needs a positive base (not 1) and a positive number");
        var r = Math.log(arg.v) / Math.log(base.v);
        if (isInt(r)) r = Math.round(r);
        return V(r, base.ex && arg.ex && isInt(r));
      }
      case "abs": { var x = need(n.a, "Abs"); return V(Math.abs(x.v), x.ex); }
      case "integ":
        if (!n.f) throw SYNTAX("Type what to integrate");
        return integrate(n.f, need(n.lo, "lower limit").v, need(n.hi, "upper limit").v, env);
      case "deriv":
        if (!n.f) throw SYNTAX("Type what to differentiate");
        return derivative(n.f, need(n.at, "x =").v, env);
      case "sum":
        if (!n.f) throw SYNTAX("Type what to add up");
        return sigma(n.f, need(n.lo, "start").v, need(n.hi, "end").v, env);
    }
    throw SYNTAX();
  }

  /** f(X) with X set, for ∫ d/dx Σ SOLVE TABLE. */
  function withX(ast, env) {
    return function (x) {
      var vars = Object.assign({}, env.vars || {}, { X: x });
      return evaluate(ast, Object.assign({}, env, { vars: vars })).v;
    };
  }

  function integrate(ast, a, b, env) {
    var f = withX(ast, env);
    if (a === b) return V(0, true);
    var simpson = function (fa, fm, fb, x0, x1) { return (x1 - x0) / 6 * (fa + 4 * fm + fb); };
    var calls = 0;
    function adapt(x0, x1, fa, fm, fb, whole, eps, depth) {
      var m = (x0 + x1) / 2, lm = (x0 + m) / 2, rm = (m + x1) / 2;
      var flm = f(lm), frm = f(rm);
      calls += 2;
      var left = simpson(fa, flm, fm, x0, m), right = simpson(fm, frm, fb, m, x1);
      if (depth > 40 || calls > 200000 || Math.abs(left + right - whole) <= 15 * eps) {
        return left + right + (left + right - whole) / 15;
      }
      return adapt(x0, m, fa, flm, fm, left, eps / 2, depth + 1) + adapt(m, x1, fm, frm, fb, right, eps / 2, depth + 1);
    }
    var fa = f(a), fb = f(b), fm = f((a + b) / 2);
    var r = adapt(a, b, fa, fm, fb, simpson(fa, fm, fb, a, b), 1e-10, 0);
    if (Math.abs(r - Math.round(r)) < 1e-9) r = Math.round(r);
    return V(r, false);
  }

  function derivative(ast, x, env) {
    var f = withX(ast, env);
    var h = 1e-3 * Math.max(1, Math.abs(x));
    // Richardson extrapolation of the central difference
    var d1 = (f(x + h) - f(x - h)) / (2 * h), d2 = (f(x + h / 2) - f(x - h / 2)) / h;
    var d = (4 * d2 - d1) / 3;
    if (Math.abs(d - Math.round(d)) < 1e-7) d = Math.round(d);
    return V(d, false);
  }

  function sigma(ast, a, b, env) {
    if (!isInt(a) || !isInt(b) || b < a) throw MATH("Σ runs from a whole number up to a bigger one");
    if (b - a > 1e6) throw MATH("Too many terms");
    var tot = 0, ex = true;
    for (var k = Math.round(a); k <= Math.round(b); k++) {
      var vars = Object.assign({}, env.vars || {}, { X: k });
      var r = evaluate(ast, Object.assign({}, env, { vars: vars }));
      tot += r.v; ex = ex && r.ex;
    }
    return V(tot, ex);
  }

  /** SOLVE: X such that f(X) = 0 (an equation L = R is solved as L − R = 0). */
  function solve(ast, guess, env) {
    var f = withX(ast, env);
    var safe = function (x) { try { var y = f(x); return isFinite(y) ? y : NaN; } catch (e) { return NaN; } };
    var x = isFinite(guess) ? guess : 0;
    for (var it = 0; it < 80; it++) {                         // Newton
      var y = safe(x);
      if (isNaN(y)) break;
      if (Math.abs(y) < 1e-13) return done(x);
      var h = 1e-6 * Math.max(1, Math.abs(x));
      var d = (safe(x + h) - safe(x - h)) / (2 * h);
      if (!d || isNaN(d)) break;
      var nx = x - y / d;
      if (Math.abs(nx - x) < 1e-13 * Math.max(1, Math.abs(x))) { x = nx; if (Math.abs(safe(x)) < 1e-8) return done(x); break; }
      x = nx;
    }
    // a sign change near the guess, widening out; then bisection
    var g = isFinite(guess) ? guess : 0;
    var spans = [1, 10, 100, 1000, 1e5];
    for (var s = 0; s < spans.length; s++) {
      var steps = 400, lo = g - spans[s], w = 2 * spans[s] / steps, prevX = lo, prevY = safe(lo);
      for (var k = 1; k <= steps; k++) {
        var cx = lo + k * w, cy = safe(cx);
        if (!isNaN(prevY) && !isNaN(cy) && prevY * cy <= 0) return done(bisect(safe, prevX, cx));
        prevX = cx; prevY = cy;
      }
    }
    throw CalcError("Can't Solve", "Try a different starting value for X");
    function done(root) {
      if (Math.abs(root - Math.round(root)) < 1e-9) root = Math.round(root);
      var lr = safe(root);
      return { x: root, lr: Math.abs(lr) < 1e-12 ? 0 : lr };
    }
  }
  function bisect(f, a, b) {
    var fa = f(a);
    for (var i = 0; i < 200; i++) {
      var m = (a + b) / 2, fm = f(m);
      if (fm === 0 || (b - a) / 2 < 1e-15 * Math.max(1, Math.abs(m))) return m;
      if (fa * fm < 0) b = m; else { a = m; fa = fm; }
    }
    return (a + b) / 2;
  }

  // ── Exact forms ───────────────────────────────────────────────────────────
  /** p/q within tolerance with q <= maxDen, or null. Continued fractions. */
  function fraction(x, maxDen, tol) {
    maxDen = maxDen || 1e6;
    tol = tol || 1e-10;
    if (!isFinite(x)) return null;
    var sign = x < 0 ? -1 : 1, v = Math.abs(x);
    var h0 = 0, h1 = 1, k0 = 1, k1 = 0, r = v;
    for (var i = 0; i < 40; i++) {
      var a = Math.floor(r);
      var h2 = a * h1 + h0, k2 = a * k1 + k0;
      if (k2 > maxDen) break;
      h0 = h1; h1 = h2; k0 = k1; k1 = k2;
      if (Math.abs(v - h1 / k1) <= tol * Math.max(1, v)) return { n: sign * h1, d: k1 };
      if (r - a < 1e-15) break;
      r = 1 / (r - a);
    }
    return null;
  }
  function squareFree(n) {                                     // n = k² m -> [k, m]
    var k = 1, m = n;
    for (var p = 2; p * p <= m; p++) while (m % (p * p) === 0) { m /= p * p; k *= p; }
    return [k, m];
  }
  var SQFREE = [];
  for (var sq = 2; sq < 200; sq++) if (squareFree(sq)[0] === 1) SQFREE.push(sq);

  /** The textbook form of an exact result, or null (then show a decimal).
   *  {k:"int"} {k:"frac", n, d} {k:"surd", a, b, c} = a√b / c
   *  {k:"surd2", p, q, b, d} = (p + q√b) / d   {k:"pi", n, d} = nπ / d */
  function exact(v, ex) {
    if (!ex || !isFinite(v)) return null;
    if (Math.abs(v) < 1e-15) return { k: "int", n: 0 };
    if (isInt(v) && Math.abs(v) < 1e15) return { k: "int", n: Math.round(v) };
    // Doubles from exact steps are off by ~1e-16; an irrational is at least
    // ~1e-11 away from any fraction with a 5-digit denominator.
    var fr = fraction(v, 1e5, 1e-13);
    if (fr && String(Math.abs(fr.n)).length + String(fr.d).length <= 10) return { k: "frac", n: fr.n, d: fr.d };
    if (fr) return null;                                       // rational but too long: decimal, as on Casio
    var sq = fraction(v * v, 1e5, 1e-12);
    if (sq && sq.n > 0) {
      var kk = squareFree(sq.n * sq.d), c = sq.d, a = kk[0], g = gcd(a, c);
      if (kk[1] > 1 && kk[1] < 1e6) return { k: "surd", a: (v < 0 ? -1 : 1) * a / g, b: kk[1], c: c / g };
    }
    var pi = fraction(v / Math.PI, 1000, 1e-12);
    if (pi && Math.abs(pi.n) < 1000) return { k: "pi", n: pi.n, d: pi.d };
    for (var d = 1; d <= 60; d++) {                            // (p + q√b)/d
      for (var s = 0; s < SQFREE.length; s++) {
        var b = SQFREE[s], rb = Math.sqrt(b);
        for (var q = -60; q <= 60; q++) {
          if (!q) continue;
          var p = v * d - q * rb;
          if (Math.abs(p - Math.round(p)) < 1e-8 && Math.abs(Math.round(p)) <= 1000) {
            p = Math.round(p);
            var gg = gcd(gcd(p, q), d);
            if (gg > 1) continue;                               // reducible: a smaller d matched first
            if (Math.abs((p + q * rb) / d - v) < 1e-11 * Math.max(1, Math.abs(v))) return { k: "surd2", p: p, q: q, b: b, d: d };
          }
        }
      }
    }
    return null;
  }

  /** a b/c (mixed number) from an improper fraction. */
  function mixed(fr) {
    var sign = fr.n < 0 ? -1 : 1, n = Math.abs(fr.n);
    return { sign: sign, w: Math.floor(n / fr.d), n: n % fr.d, d: fr.d };
  }

  function exactText(r) {
    if (!r) return null;
    var sgn = function (x) { return x < 0 ? "−" : ""; };
    switch (r.k) {
      case "int": return sgn(r.n) + Math.abs(r.n);
      case "frac": return sgn(r.n) + Math.abs(r.n) + "/" + r.d;
      case "surd": return sgn(r.a) + (Math.abs(r.a) === 1 ? "" : Math.abs(r.a)) + "√" + r.b + (r.c === 1 ? "" : "/" + r.c);
      case "surd2": {
        var top = (r.p ? r.p + (r.q < 0 ? "−" : "+") : (r.q < 0 ? "−" : "")) + (Math.abs(r.q) === 1 ? "" : Math.abs(r.q)) + "√" + r.b;
        return (r.d === 1 ? top : "(" + top + ")/" + r.d).replace(/^-/, "−");
      }
      case "pi": return sgn(r.n) + (Math.abs(r.n) === 1 ? "" : Math.abs(r.n)) + "π" + (r.d === 1 ? "" : "/" + r.d);
    }
    return null;
  }

  // ── Decimal display: Norm 1/2, Fix n, Sci n, ENG ──────────────────────────
  /** {mant, exp|null, plain}: mant×10^exp, as the display shows it. */
  function formatDecimal(v, setup) {
    setup = setup || {};
    var f = setup.fmt || "norm", n = setup.digits != null ? setup.digits : 1;
    if (v === 0) return { mant: f === "fix" ? (0).toFixed(n) : "0", exp: null, plain: "0" };
    var a = Math.abs(v), e10 = Math.floor(Math.log10(a));
    if (f === "fix") {
      if (a >= 1e10) return sciOut(v, 10);
      var fx = v.toFixed(n);
      return { mant: fx, exp: null, plain: fx };
    }
    if (f === "sci") return sciOut(v, n || 10);
    var small = n === 2 ? 1e-9 : 0.01;
    if (a >= 1e10 || a < small) return sciOut(v, 10);
    var t = Number(v.toPrecision(10));
    if (Math.abs(t) >= 1e10) return sciOut(v, 10);
    var s = String(t);
    if (/e/.test(s)) s = t.toFixed(Math.max(0, 9 - e10));
    return { mant: s, exp: null, plain: s };
    function sciOut(x, sig) {
      var m = x.toExponential(sig - 1).split("e");
      var mant = setup.fmt === "sci" ? m[0] : String(Number(m[0]));
      return { mant: mant, exp: Number(m[1]), plain: mant + "e" + m[1] };
    }
  }
  /** ENG: the exponent a multiple of 3; step moves it by 3 (◀ ENG / ENG ▶). */
  function formatEng(v, shift) {
    if (v === 0) return { mant: "0", exp: 0, plain: "0" };
    var e = Math.floor(Math.log10(Math.abs(v)));
    e = Math.floor(e / 3) * 3 + 3 * (shift || 0);
    var m = Number((v / Math.pow(10, e)).toPrecision(10));
    return { mant: String(m), exp: e, plain: m + "e" + e };
  }
  function dms(v) {
    var sign = v < 0 ? "−" : "", a = Math.abs(v);
    var d = Math.floor(a), mf = (a - d) * 60, m = Math.floor(mf + 1e-9), s = (mf - m) * 60;
    s = Math.round(s * 100) / 100;
    if (s >= 60) { s -= 60; m++; }
    if (m >= 60) { m -= 60; d++; }
    return sign + d + "°" + m + "′" + s + "″";
  }

  // ── Statistics ────────────────────────────────────────────────────────────
  function expand(rows, key) {
    var out = [];
    rows.forEach(function (r) {
      var f = r.f == null ? 1 : r.f;
      if (f < 0 || !isInt(f)) throw MATH("Frequencies must be whole numbers");
      for (var i = 0; i < f; i++) out.push(r[key]);
    });
    return out;
  }
  function median(sorted) {
    var n = sorted.length;
    return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
  }
  function stats1(rows) {
    var xs = expand(rows.filter(function (r) { return r.x != null; }), "x");
    var n = xs.length;
    if (!n) throw MATH("Enter some data first");
    var sum = 0, sum2 = 0;
    xs.forEach(function (x) { sum += x; sum2 += x * x; });
    var mean = sum / n;
    var ss = xs.reduce(function (t, x) { return t + (x - mean) * (x - mean); }, 0);
    var s = xs.slice().sort(function (a, b) { return a - b; });
    var half = Math.floor(n / 2);
    return {
      n: n, sumx: sum, sumx2: sum2, mean: mean,
      sigma: Math.sqrt(ss / n), s: n > 1 ? Math.sqrt(ss / (n - 1)) : NaN,
      min: s[0], max: s[n - 1], median: median(s),
      q1: n > 1 ? median(s.slice(0, half)) : s[0],
      q3: n > 1 ? median(s.slice(n % 2 ? half + 1 : half)) : s[0],
    };
  }
  function stats2(rows) {
    var pts = [];
    rows.forEach(function (r) {
      if (r.x == null || r.y == null) return;
      var f = r.f == null ? 1 : r.f;
      for (var i = 0; i < f; i++) pts.push([r.x, r.y]);
    });
    var n = pts.length;
    if (n < 2) throw MATH("Enter at least two (x, y) pairs");
    var sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    pts.forEach(function (p) { sx += p[0]; sy += p[1]; sxx += p[0] * p[0]; syy += p[1] * p[1]; sxy += p[0] * p[1]; });
    var mx = sx / n, my = sy / n, Sxx = sxx - n * mx * mx, Syy = syy - n * my * my, Sxy = sxy - n * mx * my;
    if (Sxx === 0) throw MATH("All the x values are the same");
    var b = Sxy / Sxx, a = my - b * mx;
    return {
      n: n, sumx: sx, sumy: sy, sumx2: sxx, sumy2: syy, sumxy: sxy, meanx: mx, meany: my,
      sigmax: Math.sqrt(Sxx / n), sigmay: Math.sqrt(Syy / n),
      sx: Math.sqrt(Sxx / (n - 1)), sy: Math.sqrt(Syy / (n - 1)),
      a: a, b: b, r: Syy === 0 ? NaN : Sxy / Math.sqrt(Sxx * Syy),
    };
  }

  // ── Equations ─────────────────────────────────────────────────────────────
  /** A x = b by Gaussian elimination with partial pivoting. */
  function linear(m) {                                          // rows [a1..an, c]
    var n = m.length, A = m.map(function (r) { return r.slice(); });
    for (var c = 0; c < n; c++) {
      var piv = c;
      for (var r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
      if (Math.abs(A[piv][c]) < 1e-12) throw CalcError("No unique solution", "The equations are parallel or the same line");
      var t = A[c]; A[c] = A[piv]; A[piv] = t;
      for (var r2 = 0; r2 < n; r2++) {
        if (r2 === c) continue;
        var k = A[r2][c] / A[c][c];
        for (var j = c; j <= n; j++) A[r2][j] -= k * A[c][j];
      }
    }
    return A.map(function (row, i) { var x = row[n] / row[i]; return Math.abs(x) < 1e-13 ? 0 : x; });
  }
  function quadratic(a, b, c) {
    if (a === 0) throw MATH("a can't be 0 in a quadratic");
    var D = b * b - 4 * a * c, vx = -b / (2 * a), vy = c - b * b / (4 * a);
    var roots;
    if (Math.abs(D) < 1e-14 * Math.max(1, b * b)) roots = [{ re: vx, im: 0 }];
    else if (D > 0) {
      var q = -0.5 * (b + (b >= 0 ? 1 : -1) * Math.sqrt(D));       // no cancellation
      var r1 = q / a, r2 = c / q;
      roots = [{ re: Math.max(r1, r2), im: 0 }, { re: Math.min(r1, r2), im: 0 }];
    } else {
      var im = Math.sqrt(-D) / (2 * Math.abs(a));
      roots = [{ re: vx, im: im }, { re: vx, im: -im }];
    }
    return { roots: roots, disc: D, vertex: { x: vx, y: vy }, min: a > 0 };
  }
  function cubic(a, b, c, d) {
    if (a === 0) throw MATH("a can't be 0 in a cubic");
    // Durand-Kerner on the monic polynomial
    var p = [b / a, c / a, d / a];
    var f = function (z) {                                    // z^3 + p0 z^2 + p1 z + p2 (complex)
      var z2 = cmul(z, z), z3 = cmul(z2, z);
      return cadd(cadd(z3, cscale(z2, p[0])), cadd(cscale(z, p[1]), { re: p[2], im: 0 }));
    };
    var R = [{ re: 0.4, im: 0.9 }, { re: -0.65, im: 0.72 }, { re: 0.3, im: -1.1 }];
    for (var it = 0; it < 500; it++) {
      var moved = 0;
      for (var i = 0; i < 3; i++) {
        var den = { re: 1, im: 0 };
        for (var j = 0; j < 3; j++) if (j !== i) den = cmul(den, csub(R[i], R[j]));
        var step = cdiv(f(R[i]), den);
        R[i] = csub(R[i], step);
        moved = Math.max(moved, Math.hypot(step.re, step.im));
      }
      if (moved < 1e-15) break;
    }
    // polish real-looking roots and tidy
    R = R.map(function (z) {
      if (Math.abs(z.im) < 1e-7) {
        var x = z.re;
        for (var k = 0; k < 20; k++) {
          var fx = ((x + p[0]) * x + p[1]) * x + p[2], dfx = (3 * x + 2 * p[0]) * x + p[1];
          if (!dfx) break;
          x -= fx / dfx;
        }
        return { re: snap(x), im: 0 };
      }
      return { re: snap(z.re), im: snap(z.im) };
    });
    R.sort(function (u, v) { return (u.im !== 0) - (v.im !== 0) || v.re - u.re || v.im - u.im; });
    return { roots: R };
  }
  function snap(x) { return Math.abs(x - Math.round(x)) < 1e-9 ? Math.round(x) : Math.abs(x) < 1e-12 ? 0 : x; }
  function cadd(a, b) { return { re: a.re + b.re, im: a.im + b.im }; }
  function csub(a, b) { return { re: a.re - b.re, im: a.im - b.im }; }
  function cmul(a, b) { return { re: a.re * b.re - a.im * b.im, im: a.re * b.im + a.im * b.re }; }
  function cscale(a, k) { return { re: a.re * k, im: a.im * k }; }
  function cdiv(a, b) { var d = b.re * b.re + b.im * b.im; return { re: (a.re * b.re + a.im * b.im) / d, im: (a.im * b.re - a.re * b.im) / d }; }

  // ── BASE-N (32-bit two's complement, like the calculator) ─────────────────
  var BASES = { DEC: 10, HEX: 16, BIN: 2, OCT: 8 };
  function toBase(v, base) {
    var n = Math.trunc(v);
    if (base === "DEC") return String(n | 0);
    var u = (n | 0) >>> 0;
    var s = u.toString(BASES[base]).toUpperCase();
    return s;
  }
  /** Evaluate a BASE-N line: integers in `base`, + − × ÷ (whole-number
   *  division), and / or / xor / xnor / Not( / Neg(, brackets. */
  function evalBase(text, base) {
    var radix = BASES[base];
    var s = String(text).replace(/\s+/g, " ").trim();
    var toks = [], i = 0;
    var WORDS = ["xnor", "xor", "and", "or", "Not(", "Neg(", "d", "h", "b", "o"];
    while (i < s.length) {
      var ch = s[i];
      if (ch === " ") { i++; continue; }
      var w = null;
      for (var k = 0; k < WORDS.length; k++) {
        var W = WORDS[k];
        if (s.startsWith(W, i) && (W.length > 1 || /[0-9A-F]/i.test(s[i + 1] || ""))) {
          // a one-letter prefix (d/h/b/o) only counts before digits
          if (W.length === 1 && /[0-9A-F]/.test(ch)) continue;
          w = W; break;
        }
      }
      if (w && w.length > 1) { toks.push(w); i += w.length; continue; }
      var r = radix;
      if (w) { r = { d: 10, h: 16, b: 2, o: 8 }[w]; i++; }
      var digits = "";
      while (i < s.length && /[0-9A-Fa-f]/.test(s[i])) digits += s[i++];
      if (digits) {
        var val = parseInt(digits, r);
        if (isNaN(val) || digits.toUpperCase().split("").some(function (d) { return parseInt(d, 16) >= r; })) {
          throw SYNTAX("“" + digits + "” is not a " + ({ 10: "decimal", 16: "hex", 2: "binary", 8: "octal" })[r] + " number");
        }
        toks.push(val | 0);
        continue;
      }
      if ("+−×÷()-*/".indexOf(ch) >= 0) { toks.push({ "-": "−", "*": "×", "/": "÷" }[ch] || ch); i++; continue; }
      throw SYNTAX("“" + ch + "” can't be used in BASE-N");
    }
    var p = 0;
    var peek = function () { return toks[p]; };
    function orx() {
      var a = andx();
      while (peek() === "or" || peek() === "xor" || peek() === "xnor") {
        var op = toks[p++], b = andx();
        a = op === "or" ? a | b : op === "xor" ? a ^ b : ~(a ^ b);
      }
      return a | 0;
    }
    function andx() { var a = add(); while (peek() === "and") { p++; a = a & add(); } return a | 0; }
    function add() {
      var a = mul();
      while (peek() === "+" || peek() === "−") { var op = toks[p++]; var b = mul(); a = op === "+" ? a + b : a - b; }
      return a | 0;
    }
    function mul() {
      var a = un();
      while (peek() === "×" || peek() === "÷") {
        var op = toks[p++], b = un();
        if (op === "÷" && b === 0) throw MATH("You can't divide by 0");
        a = op === "×" ? Math.imul(a, b) : Math.trunc(a / b);
      }
      return a | 0;
    }
    function un() {
      var t = peek();
      if (t === "−") { p++; return -un() | 0; }
      if (t === "Not(" || t === "Neg(") {
        p++;
        var v = orx();
        if (peek() === ")") p++;
        return t === "Not(" ? ~v : -v | 0;
      }
      if (t === "(") { p++; var e = orx(); if (peek() === ")") p++; return e; }
      if (typeof t === "number") { p++; return t; }
      throw SYNTAX("The calculation stops too early");
    }
    if (!toks.length) throw SYNTAX("Type a calculation first");
    var out = orx();
    if (p < toks.length) throw SYNTAX("Something is out of place");
    return out;
  }

  // ── Convenience for tests / the history panel ─────────────────────────────
  /** Evaluate a text expression (or a tree) in one go. */
  function calc(src, env) {
    var seq = Array.isArray(src) ? src : fromText(src);
    var r = evaluate(parse(seq), env || {});
    return { v: r.v, ex: r.ex, exact: exact(r.v, r.ex), text: exactText(exact(r.v, r.ex)) };
  }

  return {
    Editor: Editor, template: template, clone: clone, SLOTS: SLOTS, isTpl: isTpl,
    FUNCS: FUNCS, POSTFIX: POSTFIX, VARS: VARS, CONSTS: CONSTS, CONVS: CONVS,
    parse: parse, evaluate: evaluate, solve: solve, fromText: fromText, toText: lin,
    exact: exact, exactText: exactText, mixed: mixed, fraction: fraction,
    formatDecimal: formatDecimal, formatEng: formatEng, dms: dms,
    stats1: stats1, stats2: stats2, linear: linear, quadratic: quadratic, cubic: cubic,
    evalBase: evalBase, toBase: toBase, calc: calc, CalcError: CalcError,
  };
});
