/* math-expr.js — a small, safe maths expression parser for PrepWithTee tools.
 *
 *   PWTMath.compile("2sin^2 x + |x-1|")      -> function (env) { ... }  env = {x, y}
 *   PWTMath.evaluate("log_2(8)")             -> 3
 *   PWTMath.relation("x^2 + y^2 = 25")       -> {kind: "implicit", F(x, y)}
 *
 * Tokenizer + precedence-climbing (Pratt) parser -> AST -> closures. The typed
 * text is never run as JavaScript, so an expression can only do maths.
 *
 * Reads the way students write:
 *   implicit multiplication   2x   3(x+1)   x(x+1)   (x+1)(x-1)   2pi   2sin x
 *   functions without ()      sin x   sin 2x   sin x cos x   sin x/2 = sin(x)/2
 *   powers of functions       sin^2 x = (sin x)^2      sin^-1 x = arcsin x
 *   unary minus below powers  -x^2 = -(x^2)      2^-1 = 0.5      x^2^3 = x^8
 *   |x|, √x, ∛x, π, e, x², x³, ×, ÷, −, n!, log_2(x), log_{10} x, ln x
 * Errors are sentences a student can act on: "Missing ')' to close 'sin('".
 */
(function (root) {
  "use strict";

  var FUNCS = {
    sin: Math.sin, cos: Math.cos, tan: Math.tan,
    asin: Math.asin, acos: Math.acos, atan: Math.atan,
    arcsin: Math.asin, arccos: Math.acos, arctan: Math.atan,
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    sec: function (v) { return 1 / Math.cos(v); },
    csc: function (v) { return 1 / Math.sin(v); },
    cosec: function (v) { return 1 / Math.sin(v); },
    cot: function (v) { return 1 / Math.tan(v); },
    sqrt: Math.sqrt, cbrt: Math.cbrt, abs: Math.abs,
    ln: Math.log, log: Math.log10, exp: Math.exp,
    floor: Math.floor, ceil: Math.ceil, round: Math.round, sign: Math.sign,
    min: Math.min, max: Math.max,
  };
  var TRIG = { sin: 1, cos: 1, tan: 1, sec: 1, csc: 1, cosec: 1, cot: 1 };
  var INVERSE = { sin: "asin", cos: "acos", tan: "atan" };
  var ARC = { asin: 1, acos: 1, atan: 1, arcsin: 1, arccos: 1, arctan: 1 };
  var CONSTS = { pi: Math.PI, e: Math.E };
  var VARS = { x: 1, y: 1 };
  // Longest-first, so "exp" beats "e", "sinh" beats "sin", "cosec" beats "cos".
  var NAMES = Object.keys(FUNCS).concat(Object.keys(CONSTS), Object.keys(VARS))
    .sort(function (a, b) { return b.length - a.length; });

  function MathError(message, pos) {
    this.message = message;
    this.pos = pos;
  }
  MathError.prototype = Object.create(Error.prototype);
  MathError.prototype.name = "MathError";

  // ── Tokenizer ────────────────────────────────────────────────────────────
  var SUP = { "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
              "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-" };
  var OPS = { "+": "+", "-": "-", "−": "-", "–": "-", "*": "*", "×": "*", "·": "*",
              "⋅": "*", "/": "/", "÷": "/", "^": "^", "(": "(", ")": ")", "[": "(",
              "]": ")", "{": "(", "}": ")", ",": ",", "|": "|", "!": "!", "=": "=",
              "<": "<", ">": ">", "≤": "<", "≥": ">", "_": "_" };

  function tokenize(src) {
    var out = [], i = 0, n = src.length;
    while (i < n) {
      var c = src[i];
      if (/\s/.test(c)) { i++; continue; }
      var start = i;
      if (/[0-9.]/.test(c)) {
        var m = /^(\d+\.?\d*|\.\d+)/.exec(src.slice(i));
        if (!m) throw new MathError("A lone '.' isn't a number", i);
        out.push({ t: "num", v: parseFloat(m[1]), s: m[1], p: start });
        i += m[1].length;
        continue;
      }
      if (c === "*" && src[i + 1] === "*") { out.push({ t: "op", v: "^", s: "**", p: i }); i += 2; continue; }
      if (SUP[c] !== undefined) {           // x²  x⁻¹  -> ^ 2, ^ -1
        var digits = "";
        while (i < n && SUP[src[i]] !== undefined) digits += SUP[src[i++]];
        out.push({ t: "op", v: "^", s: "^", p: start });
        if (digits[0] === "-") { out.push({ t: "op", v: "-", s: "-", p: start }); digits = digits.slice(1); }
        if (!digits) throw new MathError("A superscript minus needs a number after it", start);
        out.push({ t: "num", v: parseFloat(digits), s: digits, p: start });
        continue;
      }
      if (c === "π") { out.push({ t: "const", v: "pi", s: "π", p: i++ }); continue; }
      if (c === "√") { out.push({ t: "func", v: "sqrt", s: "√", p: i++ }); continue; }
      if (c === "∛") { out.push({ t: "func", v: "cbrt", s: "∛", p: i++ }); continue; }
      if (OPS[c] !== undefined) { out.push({ t: "op", v: OPS[c], s: c, p: i++ }); continue; }
      if (/[a-zA-Z]/.test(c)) {
        var word = /^[a-zA-Z]+/.exec(src.slice(i))[0];
        var j = 0, low = word.toLowerCase();
        while (j < word.length) {
          var hit = null;
          for (var k = 0; k < NAMES.length; k++) {
            if (low.startsWith(NAMES[k], j)) { hit = NAMES[k]; break; }
          }
          if (!hit) {
            var bad = word.slice(j);
            throw new MathError(
              /^[a-z]$/i.test(word[j]) && word.length - j === 1
                ? "'" + word[j] + "' isn't something I can plot — use x" + (VARS.y ? " (and y)" : "")
                : "I don't know '" + bad + "'", i + j);
          }
          out.push({ t: FUNCS[hit] ? "func" : CONSTS[hit] !== undefined ? "const" : "var",
                     v: hit, s: word.substr(j, hit.length), p: i + j });
          j += hit.length;
        }
        i += word.length;
        continue;
      }
      throw new MathError("I can't read '" + c + "'", i);
    }
    out.push({ t: "end", s: "end", p: n });
    return out;
  }

  // ── Parser ───────────────────────────────────────────────────────────────
  // Binding powers: + - 10 · * / and implicit 20 · unary minus 25 · ^ 30 · ! 40
  function Parser(tokens) {
    this.tk = tokens;
    this.i = 0;
    this.abs = 0;              // how many |...| we are inside
    this.open = [];            // brackets still open, for 'Missing )' messages
  }
  var P = Parser.prototype;
  P.peek = function () { return this.tk[this.i]; };
  P.next = function () { return this.tk[this.i++]; };
  P.is = function (v) { var t = this.peek(); return t.t === "op" && t.v === v; };
  P.expect = function (v, opener) {
    if (this.is(v)) return this.next();
    var t = this.peek();
    if (v === ")") {
      throw new MathError("Missing ')' to close '" + opener + "'", t.p);
    }
    if (v === "|") throw new MathError("Missing '|' to close the absolute value", t.p);
    throw new MathError("Expected '" + v + "'", t.p);
  };

  // Can this token start a new factor (for implicit multiplication)?
  P.startsFactor = function (t, tight) {
    if (t.t === "num" || t.t === "const" || t.t === "var") return true;
    if (t.t === "func") return !tight;
    if (t.t === "op" && t.v === "(") return true;
    if (t.t === "op" && t.v === "|") return this.abs === 0;
    return false;
  };

  P.expr = function (rbp) {
    var left = this.prefix();
    for (;;) {
      var t = this.peek();
      if (t.t === "op" && (t.v === "+" || t.v === "-")) {
        if (rbp >= 10) break;
        this.next();
        left = { k: t.v, a: left, b: this.expr(10) };
      } else if (t.t === "op" && (t.v === "*" || t.v === "/")) {
        if (rbp >= 20) break;
        this.next();
        left = { k: t.v, a: left, b: this.expr(20) };
      } else if (this.startsFactor(t, false)) {
        if (rbp >= 20) break;
        left = { k: "*", a: left, b: this.expr(20) };
      } else break;
    }
    return left;
  };

  // prefix: [-+]* power
  P.prefix = function () {
    var t = this.peek();
    if (t.t === "op" && (t.v === "-" || t.v === "+")) {
      this.next();
      var arg = this.unaryOperand();
      return t.v === "-" ? { k: "neg", a: arg } : arg;
    }
    return this.power();
  };

  // What a unary minus applies to: powers bind tighter (-x^2 = -(x^2)), and a
  // following implicit product stays with it (-2x = -(2x)).
  P.unaryOperand = function () {
    var left = this.prefix();
    while (this.startsFactor(this.peek(), false)) left = { k: "*", a: left, b: this.power() };
    return left;
  };

  // power: postfix ( ^ prefix )?   right-associative
  P.power = function () {
    var base = this.postfix();
    if (this.is("^")) {
      var hat = this.next();
      if (this.peek().t === "end") throw new MathError("'^' needs a power after it", hat.p);
      return { k: "^", a: base, b: this.prefixNoImplicit() };
    }
    return base;
  };

  // The exponent: x^2y is (x^2)·y, x^-1 is fine, x^2^3 is x^(2^3).
  P.prefixNoImplicit = function () {
    var t = this.peek();
    if (t.t === "op" && (t.v === "-" || t.v === "+")) {
      this.next();
      var a = this.prefixNoImplicit();
      return t.v === "-" ? { k: "neg", a: a } : a;
    }
    return this.power();
  };

  P.postfix = function () {
    var node = this.primary();
    while (this.is("!")) { this.next(); node = { k: "!", a: node }; }
    return node;
  };

  P.primary = function () {
    var t = this.next();
    if (t.t === "num") return { k: "num", v: t.v };
    if (t.t === "const") return { k: "num", v: CONSTS[t.v] };
    if (t.t === "var") return { k: "var", v: t.v };
    if (t.t === "func") return this.call(t);
    if (t.t === "op" && t.v === "(") {
      if (this.is(")")) throw new MathError("Empty brackets '()'", t.p);
      this.open.push("(");
      var inner = this.expr(0);
      this.expect(")", "(");
      this.open.pop();
      return inner;
    }
    if (t.t === "op" && t.v === "|") {
      this.abs++;
      if (this.is("|")) throw new MathError("Empty '| |'", t.p);
      var body = this.expr(0);
      this.abs--;
      this.expect("|");
      return { k: "fn", f: "abs", args: [body] };
    }
    if (t.t === "end") {
      if (this.open.length) throw new MathError("Missing ')' to close '" + this.open[this.open.length - 1] + "'", t.p);
      throw new MathError("The expression ends too early", t.p);
    }
    if (t.t === "op" && t.v === ")") throw new MathError("There's a ')' with no '(' before it", t.p);
    if (t.t === "op" && t.v === "=") throw new MathError("Something is missing before '='", t.p);
    throw new MathError("Unexpected '" + t.s + "'", t.p);
  };

  P.call = function (t) {
    var name = t.v, powerOf = null, base = null;
    // log_2(x)  log_{10} x
    if (name === "log" && this.is("_")) {
      this.next();
      var b = this.peek();
      if (b.t === "num") { this.next(); base = { k: "num", v: b.v }; }
      else if (b.t === "op" && b.v === "(") { this.next(); base = this.expr(0); this.expect(")", "log_("); }
      else throw new MathError("Write the base after 'log_', e.g. log_2(x)", b.p);
    }
    // sin^2 x  and  sin^-1 x
    if (this.is("^") && t.v !== "sqrt") {
      var hat = this.next();
      var neg = false;
      if (this.is("-")) { this.next(); neg = true; }
      var e = this.peek();
      if (e.t !== "num") throw new MathError("After '" + t.s + "^' put a number, e.g. " + t.s + "^2 x", hat.p);
      this.next();
      if (neg && e.v === 1 && INVERSE[name]) name = INVERSE[name];
      else powerOf = neg ? -e.v : e.v;
    }
    var args;
    if (this.is("(")) {
      var open = this.next();
      if (this.is(")")) throw new MathError("'" + t.s + "()' needs something inside", open.p);
      this.open.push(t.s + "(");
      args = [this.expr(0)];
      while (this.is(",")) { this.next(); args.push(this.expr(0)); }
      this.expect(")", t.s + "(");
      this.open.pop();
    } else {
      // No brackets: the argument is the next tight product - sin 2x, sin x^2 -
      // stopping at + - * / and at another function (sin x cos x).
      var nt = this.peek();
      if (nt.t === "end" || (nt.t === "op" && !(nt.v === "-" || nt.v === "|" || nt.v === "+")))
        throw new MathError("'" + t.s + "' needs something after it, e.g. " + t.s + "(x)", nt.p);
      var arg = this.prefixTight();
      while (this.startsFactor(this.peek(), true)) arg = { k: "*", a: arg, b: this.power() };
      args = [arg];
    }
    var min = name === "min" || name === "max" ? 1 : 1;
    if (args.length < min || (args.length > 1 && name !== "min" && name !== "max"))
      throw new MathError("'" + t.s + "' takes one value", t.p);
    var node = base ? { k: "logb", base: base, a: args[0] } : { k: "fn", f: name, args: args };
    return powerOf === null ? node : { k: "^", a: node, b: { k: "num", v: powerOf } };
  };

  P.prefixTight = function () {
    var t = this.peek();
    if (t.t === "op" && (t.v === "-" || t.v === "+")) {
      this.next();
      var a = this.prefixTight();
      return t.v === "-" ? { k: "neg", a: a } : a;
    }
    return this.power();
  };

  function parse(src) {
    if (!String(src || "").trim()) throw new MathError("Type an expression", 0);
    var p = new Parser(tokenize(String(src)));
    var ast = p.expr(0);
    var t = p.peek();
    if (t.t !== "end") {
      if (t.t === "op" && t.v === ")") throw new MathError("There's a ')' with no '(' before it", t.p);
      if (t.t === "op" && t.v === "|") throw new MathError("There's a '|' with nothing to close", t.p);
      if (t.t === "op" && t.v === ",") throw new MathError("A ',' only goes inside min(…) or max(…)", t.p);
      throw new MathError("Unexpected '" + t.s + "'", t.p);
    }
    return ast;
  }

  // ── Evaluator (AST -> closures) ─────────────────────────────────────────
  function fact(n) {
    if (n < 0 || n !== Math.floor(n)) return NaN;
    if (n > 170) return Infinity;
    var r = 1;
    for (var i = 2; i <= n; i++) r *= i;
    return r;
  }

  function pow(a, b) {
    // Odd roots of negatives: (-8)^(1/3) = -2, as a student expects.
    if (a < 0 && b !== Math.floor(b)) {
      var inv = 1 / b;
      if (Math.abs(inv - Math.round(inv)) < 1e-9 && Math.round(inv) % 2 !== 0) return -Math.pow(-a, b);
    }
    return Math.pow(a, b);
  }

  function build(node, opt) {
    var deg = opt && opt.angle === "deg";
    switch (node.k) {
      case "num": { var v = node.v; return function () { return v; }; }
      case "var": { var name = node.v; return function (env) { return env[name]; }; }
      case "neg": { var a = build(node.a, opt); return function (env) { return -a(env); }; }
      case "!": { var f1 = build(node.a, opt); return function (env) { return fact(f1(env)); }; }
      case "+": case "-": case "*": case "/": case "^": {
        var l = build(node.a, opt), r = build(node.b, opt);
        switch (node.k) {
          case "+": return function (env) { return l(env) + r(env); };
          case "-": return function (env) { return l(env) - r(env); };
          case "*": return function (env) { return l(env) * r(env); };
          case "/": return function (env) { return l(env) / r(env); };
          default: return function (env) { return pow(l(env), r(env)); };
        }
      }
      case "logb": {
        var bse = build(node.base, opt), arg = build(node.a, opt);
        return function (env) { return Math.log(arg(env)) / Math.log(bse(env)); };
      }
      case "fn": {
        var fn = FUNCS[node.f], args = node.args.map(function (n) { return build(n, opt); });
        var toRad = deg && TRIG[node.f], toDeg = deg && ARC[node.f];
        if (args.length === 1) {
          var a1 = args[0];
          return function (env) {
            var x = a1(env);
            var y = fn(toRad ? x * Math.PI / 180 : x);
            return toDeg ? y * 180 / Math.PI : y;
          };
        }
        return function (env) { return fn.apply(null, args.map(function (g) { return g(env); })); };
      }
    }
    throw new MathError("Can't evaluate that", 0);
  }

  function uses(node, name) {
    if (!node || typeof node !== "object") return false;
    if (node.k === "var") return node.v === name;
    return ["a", "b", "base"].some(function (k) { return uses(node[k], name); })
      || (node.args || []).some(function (n) { return uses(n, name); });
  }

  function compile(src, opt) {
    var ast = parse(src);
    var f = build(ast, opt);
    var out = function (env) {
      var v = f(env || {});
      return typeof v === "number" ? v : NaN;
    };
    out.ast = ast;
    out.uses = function (name) { return uses(ast, name); };
    return out;
  }

  function evaluate(src, env, opt) { return compile(src, opt)(env || {}); }

  // ── Relations for the graph plotter ─────────────────────────────────────
  //   "x^2-4", "y = 2x+1", "f(x) = ..."   -> explicit   y = f(x)
  //   "x = 3"                             -> vertical   x = k
  //   "x^2 + y^2 = 25", "x = y^2"          -> implicit   F(x, y) = 0
  function relation(src, opt) {
    var s = String(src || "").trim();
    if (!s) throw new MathError("Type an expression", 0);
    var ineq = /[<>≤≥]/.exec(s);
    if (ineq) throw new MathError("Inequalities (<, >) are coming soon — use '=' for now", ineq.index);
    var named = /^\s*[a-zA-Z]\s*\(\s*x\s*\)\s*=/.exec(s);       // f(x) = ...
    if (named) s = s.slice(named[0].length);
    var parts = s.split("=");
    if (parts.length > 2) throw new MathError("Only one '=' please", s.lastIndexOf("="));
    if (parts.length === 1) {
      var f = compile(s, opt);
      if (f.uses("y")) throw new MathError("There's a y here — add '= …' to plot it as an equation", s.indexOf("y"));
      return { kind: "explicit", f: function (x) { return f({ x: x }); } };
    }
    var lhs = parts[0].trim(), rhs = parts[1].trim();
    if (!lhs) throw new MathError("Something is missing before '='", 0);
    if (!rhs) throw new MathError("Something is missing after '='", s.length);
    var L = compile(lhs, opt), R;
    try { R = compile(rhs, opt); }
    catch (e) { if (e instanceof MathError) e.pos += parts[0].length + 1; throw e; }
    if (/^y$/i.test(lhs) && !R.uses("y")) return { kind: "explicit", f: function (x) { return R({ x: x }); } };
    if (/^y$/i.test(rhs) && !L.uses("y")) return { kind: "explicit", f: function (x) { return L({ x: x }); } };
    if (/^x$/i.test(lhs) && !R.uses("x") && !R.uses("y")) return { kind: "vertical", x: R({}) };
    if (/^x$/i.test(rhs) && !L.uses("x") && !L.uses("y")) return { kind: "vertical", x: L({}) };
    if (!L.uses("y") && !R.uses("y") && !L.uses("x") && !R.uses("x"))
      throw new MathError("Put x or y in the equation to draw something", 0);
    return { kind: "implicit", F: function (x, y) { var e = { x: x, y: y }; return L(e) - R(e); } };
  }

  var api = { parse: parse, compile: compile, evaluate: evaluate, relation: relation,
              tokenize: tokenize, MathError: MathError };
  root.PWTMath = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
