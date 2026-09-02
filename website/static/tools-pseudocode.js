/* PrepWithTee — Cambridge pseudocode runner (mountable widget).
 *
 * Cambridge pseudocode is a FIXED dialect, published in the 9618/0478/2210
 * guides, which means it can genuinely be executed rather than eyeballed. That
 * is the point of this tool: a student writes the algorithm the exam expects,
 * runs it, and finds out whether it actually works — plus a trace table, which
 * is itself a guaranteed exam question.
 *
 * Three layers:
 *   1. lex/parse/interpret  — real execution, with a step cap so a runaway
 *      loop reports itself instead of hanging the tab.
 *   2. diagnostics          — errors carry a line number AND a suggested fix,
 *      because "unexpected token" teaches nobody anything.
 *   3. review               — style notes for the things examiners deduct for
 *      even when the logic runs.
 */
(function () {
  "use strict";

  var MAX_STEPS = 200000;
  var KEYWORDS = ["DECLARE", "CONSTANT", "IF", "THEN", "ELSE", "ENDIF", "CASE",
    "OF", "OTHERWISE", "ENDCASE", "FOR", "TO", "STEP", "NEXT", "WHILE", "DO",
    "ENDWHILE", "REPEAT", "UNTIL", "PROCEDURE", "ENDPROCEDURE", "CALL",
    "FUNCTION", "RETURNS", "RETURN", "ENDFUNCTION", "INPUT", "OUTPUT", "ARRAY",
    "AND", "OR", "NOT", "DIV", "MOD", "TRUE", "FALSE", "BYREF", "BYVAL"];
  var TYPES = ["INTEGER", "REAL", "CHAR", "STRING", "BOOLEAN", "DATE"];

  function PErr(msg, line, fix) {
    var e = new Error(msg);
    e.line = line; e.fix = fix; e.pseudo = true;
    return e;
  }

  // ── Lexer ───────────────────────────────────────────────────────────────
  function lex(src) {
    var toks = [], lines = src.split(/\r?\n/);
    lines.forEach(function (raw, li) {
      var line = li + 1;
      var s = raw.replace(/\/\/.*$/, "");        // comments
      var i = 0;
      while (i < s.length) {
        var c = s[i];
        if (/\s/.test(c)) { i++; continue; }

        // Assignment arrow: <- or ← . Must be tested before "<".
        if (s.startsWith("<-", i) || c === "←") {
          toks.push({ t: "assign", line: line });
          i += (c === "←" ? 1 : 2);
          continue;
        }
        if (s.startsWith("<=", i) || s.startsWith(">=", i) || s.startsWith("<>", i)) {
          toks.push({ t: "op", v: s.substr(i, 2), line: line }); i += 2; continue;
        }
        if (s.startsWith("==", i)) {
          // Flag rather than silently accept: "==" is a C/Python habit.
          toks.push({ t: "op", v: "==", line: line, bad: "==" }); i += 2; continue;
        }
        if (s.startsWith(":=", i)) {
          toks.push({ t: "assign", line: line, bad: ":=" }); i += 2; continue;
        }
        if ('+-*/()[],:=<>&'.indexOf(c) >= 0) {
          toks.push({ t: "op", v: c, line: line }); i++; continue;
        }
        if (c === '"') {
          var j = i + 1, str = "";
          while (j < s.length && s[j] !== '"') str += s[j++];
          if (j >= s.length) {
            throw PErr("String is missing its closing quote", line,
                       'Add a " at the end of the text.');
          }
          toks.push({ t: "str", v: str, line: line }); i = j + 1; continue;
        }
        if (c === "'") {
          var k = i + 1, ch = "";
          while (k < s.length && s[k] !== "'") ch += s[k++];
          toks.push({ t: "str", v: ch, line: line, isChar: true }); i = k + 1; continue;
        }
        if (/[0-9]/.test(c)) {
          var num = "";
          while (i < s.length && /[0-9.]/.test(s[i])) num += s[i++];
          toks.push({ t: "num", v: parseFloat(num), line: line }); continue;
        }
        if (/[A-Za-z_]/.test(c)) {
          var w = "";
          while (i < s.length && /[A-Za-z0-9_]/.test(s[i])) w += s[i++];
          var up = w.toUpperCase();
          if (KEYWORDS.indexOf(up) >= 0 || TYPES.indexOf(up) >= 0) {
            toks.push({ t: "kw", v: up, line: line, raw: w });
          } else {
            toks.push({ t: "id", v: w, line: line });
          }
          continue;
        }
        throw PErr("Unexpected character “" + c + "”", line,
                   "Remove it — Cambridge pseudocode does not use this symbol.");
      }
      toks.push({ t: "nl", line: line });
    });
    toks.push({ t: "eof", line: lines.length });
    return toks;
  }

  // ── Parser ──────────────────────────────────────────────────────────────
  function parse(toks) {
    var p = 0;
    var notes = [];

    function peek(o) { return toks[p + (o || 0)]; }
    function at(t, v) {
      var tk = peek();
      return tk.t === t && (v === undefined || tk.v === v);
    }
    function atKw(v) { return at("kw", v); }
    function next() { return toks[p++]; }
    function skipNl() { while (at("nl")) p++; }
    function expect(t, v, what, fix) {
      if (!at(t, v)) {
        var tk = peek();
        throw PErr("Expected " + (what || v || t) + " but found “" +
          (tk.v !== undefined ? tk.v : tk.t) + "”", tk.line, fix);
      }
      return next();
    }
    function endOfLine() {
      if (at("nl") || at("eof")) { if (at("nl")) next(); return; }
      var tk = peek();
      throw PErr("Unexpected “" + (tk.v !== undefined ? tk.v : tk.t) +
        "” at the end of the statement", tk.line,
        "Each statement goes on its own line.");
    }

    // expressions ---------------------------------------------------------
    function primary() {
      var tk = peek();
      if (tk.t === "num") { next(); return { k: "num", v: tk.v }; }
      if (tk.t === "str") { next(); return { k: "str", v: tk.v }; }
      if (atKw("TRUE")) { next(); return { k: "bool", v: true }; }
      if (atKw("FALSE")) { next(); return { k: "bool", v: false }; }
      if (atKw("NOT")) { next(); return { k: "not", a: primary() }; }
      if (at("op", "-")) { next(); return { k: "neg", a: primary() }; }
      if (at("op", "(")) {
        next();
        var e = expr();
        expect("op", ")", "a closing )", "Every ( needs a matching ).");
        return e;
      }
      if (tk.t === "id") {
        next();
        if (at("op", "(")) {                       // function call
          next();
          var args = [];
          if (!at("op", ")")) {
            args.push(expr());
            while (at("op", ",")) { next(); args.push(expr()); }
          }
          expect("op", ")", "a closing )");
          return { k: "call", name: tk.v, args: args, line: tk.line };
        }
        if (at("op", "[")) {                       // array index
          next();
          var idx = expr();
          expect("op", "]", "a closing ]", "Array subscripts use square brackets.");
          return { k: "index", name: tk.v, idx: idx, line: tk.line };
        }
        return { k: "var", name: tk.v, line: tk.line };
      }
      throw PErr("Expected a value but found “" + (tk.v !== undefined ? tk.v : tk.t) + "”",
        tk.line, "Check for a missing operand or an extra operator.");
    }

    var BIN = [
      [["OR"]], [["AND"]],
      [["=", "<>", "<", ">", "<=", ">=", "=="]],
      [["+", "-", "&"]], [["*", "/", "DIV", "MOD"]]
    ];
    function binLevel(l) {
      if (l >= BIN.length) return primary();
      var ops = BIN[l][0];
      var left = binLevel(l + 1);
      for (;;) {
        var tk = peek();
        var isOp = (tk.t === "op" && ops.indexOf(tk.v) >= 0) ||
                   (tk.t === "kw" && ops.indexOf(tk.v) >= 0);
        if (!isOp) return left;
        if (tk.bad === "==") {
          notes.push({ line: tk.line, kind: "error",
            msg: "“==” is not Cambridge pseudocode.",
            fix: "Use a single = to compare values." });
        }
        next();
        left = { k: "bin", op: tk.v === "==" ? "=" : tk.v, a: left, b: binLevel(l + 1), line: tk.line };
      }
    }
    function expr() { return binLevel(0); }

    // statements ----------------------------------------------------------
    function block(enders) {
      var out = [];
      for (;;) {
        skipNl();
        if (at("eof")) return out;
        var tk = peek();
        if (tk.t === "kw" && enders.indexOf(tk.v) >= 0) return out;
        out.push(statement());
      }
    }

    function statement() {
      var tk = peek();
      var line = tk.line;

      if (atKw("DECLARE")) {
        next();
        var name = expect("id", undefined, "a variable name").v;
        expect("op", ":", "a colon", "The form is: DECLARE Name : TYPE");
        if (atKw("ARRAY")) {
          next();
          expect("op", "[", "[");
          var lo = expr();
          expect("op", ":", "a colon", "Array bounds are written [lower:upper].");
          var hi = expr();
          expect("op", "]", "]");
          expect("kw", "OF", "OF");
          var aty = next();
          endOfLine();
          return { k: "declArr", name: name, lo: lo, hi: hi, type: aty.v, line: line };
        }
        var ty = next();
        if (TYPES.indexOf(ty.v) < 0) {
          notes.push({ line: line, kind: "warn",
            msg: "“" + (ty.v || ty.raw) + "” is not one of the Cambridge data types.",
            fix: "Use INTEGER, REAL, CHAR, STRING, BOOLEAN or DATE." });
        }
        endOfLine();
        return { k: "decl", name: name, type: ty.v, line: line };
      }

      if (atKw("CONSTANT")) {
        next();
        var cn = expect("id", undefined, "a name").v;
        expect("op", "=", "=", "Constants use = , not the assignment arrow.");
        var cv = expr();
        endOfLine();
        return { k: "const", name: cn, val: cv, line: line };
      }

      if (atKw("INPUT")) {
        next();
        var target = lvalue();
        endOfLine();
        return { k: "input", target: target, line: line };
      }

      if (atKw("OUTPUT")) {
        next();
        var parts = [expr()];
        while (at("op", ",")) { next(); parts.push(expr()); }
        endOfLine();
        return { k: "output", parts: parts, line: line };
      }

      if (atKw("IF")) {
        next();
        var cond = expr();
        skipNl();
        if (atKw("THEN")) next();
        else notes.push({ line: line, kind: "warn", msg: "IF without THEN.",
                          fix: "Write: IF condition THEN" });
        var thenB = block(["ELSE", "ENDIF"]);
        var elseB = null;
        if (atKw("ELSE")) { next(); elseB = block(["ENDIF"]); }
        if (!atKw("ENDIF")) {
          throw PErr("This IF is never closed", line,
            "Add ENDIF on its own line after the last statement of the IF.");
        }
        next(); endOfLine();
        return { k: "if", cond: cond, then: thenB, else: elseB, line: line };
      }

      if (atKw("CASE")) {
        next();
        expect("kw", "OF", "OF", "The form is: CASE OF Identifier");
        var subj = expr();
        skipNl();
        var arms = [], other = null;
        for (;;) {
          skipNl();
          if (atKw("ENDCASE") || at("eof")) break;
          if (atKw("OTHERWISE")) {
            next();
            if (at("op", ":")) next();
            other = block(["ENDCASE"]);
            continue;
          }
          var val = expr();
          expect("op", ":", "a colon", "Each CASE value is followed by a colon.");
          var body = [statement()];
          arms.push({ val: val, body: body });
        }
        if (!atKw("ENDCASE")) throw PErr("This CASE is never closed", line, "Add ENDCASE.");
        next(); endOfLine();
        return { k: "case", subj: subj, arms: arms, other: other, line: line };
      }

      if (atKw("FOR")) {
        next();
        var v = expect("id", undefined, "a loop variable").v;
        if (at("assign")) next();
        else if (at("op", "=")) {
          next();
          notes.push({ line: line, kind: "error", msg: "FOR uses the assignment arrow.",
                       fix: "Write: FOR " + v + " ← 1 TO 10" });
        } else expect("assign", undefined, "←");
        var from = expr();
        expect("kw", "TO", "TO");
        var to = expr();
        var step = null;
        if (atKw("STEP")) { next(); step = expr(); }
        var body = block(["NEXT"]);
        if (!atKw("NEXT")) throw PErr("This FOR loop is never closed", line,
          "Add NEXT " + v + " after the loop body.");
        next();
        if (at("id")) {
          var nv = next();
          if (nv.v !== v) {
            notes.push({ line: nv.line, kind: "warn",
              msg: "NEXT " + nv.v + " does not match FOR " + v + ".",
              fix: "Write NEXT " + v + "." });
          }
        }
        endOfLine();
        return { k: "for", v: v, from: from, to: to, step: step, body: body, line: line };
      }

      if (atKw("WHILE")) {
        next();
        var wc = expr();
        if (atKw("DO")) next();
        var wb = block(["ENDWHILE"]);
        if (!atKw("ENDWHILE")) throw PErr("This WHILE is never closed", line, "Add ENDWHILE.");
        next(); endOfLine();
        return { k: "while", cond: wc, body: wb, line: line };
      }

      if (atKw("REPEAT")) {
        next();
        var rb = block(["UNTIL"]);
        if (!atKw("UNTIL")) throw PErr("This REPEAT has no UNTIL", line,
          "Close it with: UNTIL condition");
        next();
        var rc = expr();
        endOfLine();
        return { k: "repeat", body: rb, cond: rc, line: line };
      }

      if (atKw("PROCEDURE") || atKw("FUNCTION")) {
        var isFn = peek().v === "FUNCTION";
        next();
        var pname = expect("id", undefined, "a name").v;
        var params = [];
        if (at("op", "(")) {
          next();
          while (!at("op", ")")) {
            if (atKw("BYREF") || atKw("BYVAL")) next();
            var pn = expect("id", undefined, "a parameter name").v;
            if (at("op", ":")) { next(); next(); }
            params.push(pn);
            if (at("op", ",")) next();
          }
          next();
        }
        if (isFn) {
          if (atKw("RETURNS")) { next(); next(); }
          else notes.push({ line: line, kind: "warn", msg: "FUNCTION without RETURNS.",
                            fix: "Write: FUNCTION " + pname + "(...) RETURNS INTEGER" });
        }
        var pbody = block([isFn ? "ENDFUNCTION" : "ENDPROCEDURE"]);
        if (!atKw(isFn ? "ENDFUNCTION" : "ENDPROCEDURE")) {
          throw PErr("This " + (isFn ? "FUNCTION" : "PROCEDURE") + " is never closed", line,
            "Add END" + (isFn ? "FUNCTION" : "PROCEDURE") + ".");
        }
        next(); endOfLine();
        return { k: "def", name: pname, params: params, body: pbody, isFn: isFn, line: line };
      }

      if (atKw("CALL")) {
        next();
        var cname = expect("id", undefined, "a procedure name").v;
        var cargs = [];
        if (at("op", "(")) {
          next();
          if (!at("op", ")")) {
            cargs.push(expr());
            while (at("op", ",")) { next(); cargs.push(expr()); }
          }
          expect("op", ")", ")");
        }
        endOfLine();
        return { k: "call", name: cname, args: cargs, line: line };
      }

      if (atKw("RETURN")) {
        next();
        var rv = (at("nl") || at("eof")) ? null : expr();
        endOfLine();
        return { k: "return", val: rv, line: line };
      }

      // assignment
      if (tk.t === "id") {
        // A bare `name(...)` on its own line is almost always a habit from
        // another language. Say which one, rather than "unexpected token".
        if (peek(1) && peek(1).t === "op" && peek(1).v === "(") {
          var PY = { print: 'OUTPUT "text", variable', input: "INPUT Variable",
                     len: "LENGTH(x)", str: "NUM_TO_STRING(x)", int: "STRING_TO_NUM(x)",
                     range: "FOR I ← 1 TO n" };
          var low = String(tk.v).toLowerCase();
          if (PY[low]) {
            throw PErr("“" + tk.v + "(…)” is Python, not Cambridge pseudocode", line,
              "Use " + PY[low] + " instead.");
          }
          throw PErr("A procedure is called with CALL", line,
            "Write: CALL " + tk.v + "(…)");
        }
        var lv = lvalue();
        if (at("assign")) {
          if (peek().bad === ":=") {
            notes.push({ line: line, kind: "error", msg: "“:=” is Pascal, not Cambridge.",
              fix: "Use the assignment arrow ← (type it as <-)." });
          }
          next();
          var val = expr();
          endOfLine();
          return { k: "set", target: lv, val: val, line: line };
        }
        if (at("op", "=")) {
          throw PErr("“=” compares; it does not assign", line,
            "Use ← to assign: " + (lv.name || "x") + " ← value   (type it as <-)");
        }
        throw PErr("This line does nothing", line,
          "Did you mean to assign with ← , or CALL a procedure?");
      }

      throw PErr("Unexpected “" + (tk.v !== undefined ? tk.v : tk.t) + "”", line,
        lowerCaseHint(tk));
    }

    function lowerCaseHint(tk) {
      if (tk.t === "id" && KEYWORDS.indexOf(String(tk.v).toUpperCase()) >= 0) {
        return "Cambridge keywords are written in CAPITALS: " +
               String(tk.v).toUpperCase() + ".";
      }
      return "Check the spelling of the keyword.";
    }

    function lvalue() {
      var id = expect("id", undefined, "a variable name");
      if (at("op", "[")) {
        next();
        var idx = expr();
        expect("op", "]", "]");
        return { k: "index", name: id.v, idx: idx, line: id.line };
      }
      return { k: "var", name: id.v, line: id.line };
    }

    var prog = block([]);
    return { body: prog, notes: notes };
  }

  // ── Interpreter ─────────────────────────────────────────────────────────
  function run(ast, inputs) {
    var globals = Object.create(null);
    var funcs = Object.create(null);
    var output = [], trace = [], watched = [];
    var steps = 0;
    var inQueue = inputs.slice();
    var runtimeNotes = [];

    function tick(line) {
      if (++steps > MAX_STEPS) {
        throw PErr("Stopped after " + MAX_STEPS.toLocaleString() +
          " steps — this looks like an endless loop", line,
          "Check that the loop variable actually changes, and that the " +
          "condition can become FALSE.");
      }
    }

    // Hoist definitions, so a PROCEDURE can be called before it is written.
    (function hoist(stmts) {
      stmts.forEach(function (s) { if (s.k === "def") funcs[s.name.toUpperCase()] = s; });
    })(ast.body);

    function snapshot(scope, line) {
      var row = { line: line };
      watched.forEach(function (n) {
        var v = scope[n] !== undefined ? scope[n] : globals[n];
        row[n] = v === undefined ? "" : fmt(v);
      });
      // Only record when something actually changed — a trace table of
      // identical rows is noise.
      var last = trace[trace.length - 1];
      if (last) {
        var same = watched.every(function (n) { return last[n] === row[n]; });
        if (same) return;
      }
      trace.push(row);
      if (trace.length > 400) trace.shift();
    }

    function fmt(v) {
      if (v === null || v === undefined) return "";
      if (typeof v === "boolean") return v ? "TRUE" : "FALSE";
      if (Array.isArray(v)) return "[…]";
      if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(6)));
      return String(v);
    }

    function lookup(scope, name, line) {
      if (name in scope) return scope[name];
      if (name in globals) return globals[name];
      throw PErr("“" + name + "” has not been declared", line,
        "Add: DECLARE " + name + " : INTEGER   (or the right type) before using it.");
    }

    function assign(scope, name, val) {
      if (name in scope) scope[name] = val;
      else globals[name] = val;
    }

    var BUILTINS = {
      LENGTH: function (a) { return String(a[0]).length; },
      UCASE: function (a) { return String(a[0]).toUpperCase(); },
      LCASE: function (a) { return String(a[0]).toLowerCase(); },
      SUBSTRING: function (a) { return String(a[0]).substr(a[1] - 1, a[2]); },
      ROUND: function (a) { var p = Math.pow(10, a[1] || 0); return Math.round(a[0] * p) / p; },
      INT: function (a) { return Math.trunc(a[0]); },
      RANDOM: function () { return Math.random(); },
      DIV: function (a) { return Math.trunc(a[0] / a[1]); },
      MOD: function (a) { return a[0] % a[1]; },
      NUM_TO_STRING: function (a) { return String(a[0]); },
      STRING_TO_NUM: function (a) { return parseFloat(a[0]); }
    };

    function evaluate(n, scope) {
      switch (n.k) {
        case "num": case "str": case "bool": return n.v;
        case "neg": return -evaluate(n.a, scope);
        case "not": return !truthy(evaluate(n.a, scope), n);
        case "var": return lookup(scope, n.name, n.line);
        case "index": {
          var arr = lookup(scope, n.name, n.line);
          if (!arr || !arr.__arr) {
            throw PErr("“" + n.name + "” is not an array", n.line,
              "Declare it as: DECLARE " + n.name + " : ARRAY[1:10] OF INTEGER");
          }
          var i = evaluate(n.idx, scope);
          if (i < arr.lo || i > arr.hi) {
            throw PErr("Index " + i + " is outside " + n.name + "[" + arr.lo + ":" + arr.hi + "]",
              n.line, "Cambridge arrays usually start at 1, not 0 — check your loop bounds.");
          }
          return arr.data[i];
        }
        case "call": {
          var key = n.name.toUpperCase();
          if (BUILTINS[key]) return BUILTINS[key](n.args.map(function (a) { return evaluate(a, scope); }));
          var fn = funcs[key];
          if (!fn) {
            throw PErr("“" + n.name + "” is not defined", n.line,
              "Define it with FUNCTION " + n.name + "(...) RETURNS <type>, or check the spelling.");
          }
          return callUser(fn, n.args.map(function (a) { return evaluate(a, scope); }), n.line);
        }
        case "bin": {
          var a = evaluate(n.a, scope);
          if (n.op === "AND") return truthy(a, n) && truthy(evaluate(n.b, scope), n);
          if (n.op === "OR") return truthy(a, n) || truthy(evaluate(n.b, scope), n);
          var b = evaluate(n.b, scope);
          switch (n.op) {
            case "+": return (typeof a === "string" || typeof b === "string") ? String(a) + String(b) : a + b;
            case "&": return String(a) + String(b);
            case "-": return a - b;
            case "*": return a * b;
            case "/":
              if (b === 0) throw PErr("Division by zero", n.line, "Guard it with an IF before dividing.");
              return a / b;
            case "DIV":
              if (b === 0) throw PErr("Division by zero", n.line, "Guard it with an IF before dividing.");
              return Math.trunc(a / b);
            case "MOD":
              if (b === 0) throw PErr("MOD by zero", n.line, "Guard it with an IF.");
              return a % b;
            case "=": return a === b;
            case "<>": return a !== b;
            case "<": return a < b;
            case ">": return a > b;
            case "<=": return a <= b;
            case ">=": return a >= b;
          }
          throw PErr("Unknown operator " + n.op, n.line);
        }
      }
      throw PErr("Cannot evaluate this expression", n.line);
    }

    function truthy(v, n) {
      if (typeof v === "boolean") return v;
      runtimeNotes.push({ line: n.line, kind: "warn",
        msg: "A condition here is a " + (typeof v) + ", not TRUE/FALSE.",
        fix: "Compare it: e.g. IF count > 0 THEN" });
      return !!v;
    }

    function callUser(fn, args, line) {
      var scope = Object.create(null);
      fn.params.forEach(function (p, i) { scope[p] = args[i]; });
      try {
        exec(fn.body, scope);
      } catch (e) {
        if (e && e.__return) return e.value;
        throw e;
      }
      if (fn.isFn) {
        runtimeNotes.push({ line: line, kind: "warn",
          msg: "FUNCTION " + fn.name + " finished without RETURN.",
          fix: "Every path through a FUNCTION must RETURN a value." });
      }
      return undefined;
    }

    function exec(stmts, scope) {
      for (var si = 0; si < stmts.length; si++) {
        var s = stmts[si];
        tick(s.line);
        switch (s.k) {
          case "decl":
            assign(scope, s.name, s.type === "STRING" ? "" :
              s.type === "BOOLEAN" ? false : 0);
            if (watched.indexOf(s.name) < 0) watched.push(s.name);
            break;
          case "declArr": {
            var lo = evaluate(s.lo, scope), hi = evaluate(s.hi, scope);
            var data = {};
            for (var q = lo; q <= hi; q++) data[q] = 0;
            assign(scope, s.name, { __arr: true, lo: lo, hi: hi, data: data });
            break;
          }
          case "const":
            assign(scope, s.name, evaluate(s.val, scope));
            break;
          case "set": {
            var v = evaluate(s.val, scope);
            if (s.target.k === "var") {
              assign(scope, s.target.name, v);
              if (watched.indexOf(s.target.name) < 0) watched.push(s.target.name);
            } else {
              var arr = lookup(scope, s.target.name, s.line);
              if (!arr || !arr.__arr) {
                throw PErr("“" + s.target.name + "” is not an array", s.line,
                  "Declare it as ARRAY[1:n] OF <type> first.");
              }
              var idx = evaluate(s.target.idx, scope);
              if (idx < arr.lo || idx > arr.hi) {
                throw PErr("Index " + idx + " is outside " + s.target.name +
                  "[" + arr.lo + ":" + arr.hi + "]", s.line,
                  "Cambridge arrays usually start at 1 — check the loop bounds.");
              }
              arr.data[idx] = v;
            }
            snapshot(scope, s.line);
            break;
          }
          case "input": {
            var raw = inQueue.length ? inQueue.shift() : "";
            if (!inQueue.length && raw === "") {
              runtimeNotes.push({ line: s.line, kind: "warn",
                msg: "INPUT ran out of supplied values.",
                fix: "Add another line to the Input box on the left." });
            }
            var val = raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw;
            if (s.target.k === "var") {
              assign(scope, s.target.name, val);
              if (watched.indexOf(s.target.name) < 0) watched.push(s.target.name);
            } else {
              var a2 = lookup(scope, s.target.name, s.line);
              a2.data[evaluate(s.target.idx, scope)] = val;
            }
            snapshot(scope, s.line);
            break;
          }
          case "output":
            output.push(s.parts.map(function (e) { return fmt(evaluate(e, scope)); }).join(""));
            break;
          case "if":
            if (truthy(evaluate(s.cond, scope), s)) exec(s.then, scope);
            else if (s.else) exec(s.else, scope);
            break;
          case "case": {
            var subj = evaluate(s.subj, scope), hit = false;
            for (var ai = 0; ai < s.arms.length; ai++) {
              if (evaluate(s.arms[ai].val, scope) === subj) {
                exec(s.arms[ai].body, scope); hit = true; break;
              }
            }
            if (!hit && s.other) exec(s.other, scope);
            break;
          }
          case "for": {
            var from = evaluate(s.from, scope), to = evaluate(s.to, scope);
            var step = s.step ? evaluate(s.step, scope) : 1;
            if (step === 0) throw PErr("STEP 0 never ends", s.line, "Use a non-zero STEP.");
            if (watched.indexOf(s.v) < 0) watched.push(s.v);
            if ((step > 0 && from > to) || (step < 0 && from < to)) {
              runtimeNotes.push({ line: s.line, kind: "warn",
                msg: "This FOR loop never runs (" + from + " to " + to + " STEP " + step + ").",
                fix: "Check the start and end values, or the sign of STEP." });
            }
            for (var iv = from; step > 0 ? iv <= to : iv >= to; iv += step) {
              assign(scope, s.v, iv);
              snapshot(scope, s.line);
              tick(s.line);
              exec(s.body, scope);
            }
            break;
          }
          case "while": {
            var guard = 0;
            while (truthy(evaluate(s.cond, scope), s)) {
              tick(s.line);
              exec(s.body, scope);
              snapshot(scope, s.line);
              guard++;
            }
            if (guard === 0) {
              runtimeNotes.push({ line: s.line, kind: "info",
                msg: "This WHILE loop never ran — its condition was FALSE to begin with.",
                fix: "If it should always run once, REPEAT … UNTIL is the right choice." });
            }
            break;
          }
          case "repeat":
            do {
              tick(s.line);
              exec(s.body, scope);
              snapshot(scope, s.line);
            } while (!truthy(evaluate(s.cond, scope), s));
            break;
          case "def":
            funcs[s.name.toUpperCase()] = s;
            break;
          case "call": {
            var fk = s.name.toUpperCase();
            if (BUILTINS[fk]) { BUILTINS[fk](s.args.map(function (a) { return evaluate(a, scope); })); break; }
            var f = funcs[fk];
            if (!f) {
              throw PErr("Procedure “" + s.name + "” is not defined", s.line,
                "Define it with PROCEDURE " + s.name + " … ENDPROCEDURE, or check the spelling.");
            }
            callUser(f, s.args.map(function (a) { return evaluate(a, scope); }), s.line);
            break;
          }
          case "return": {
            var e = new Error("return");
            e.__return = true;
            e.value = s.val ? evaluate(s.val, scope) : undefined;
            throw e;
          }
        }
      }
    }

    exec(ast.body, globals);
    return { output: output, trace: trace, watched: watched, notes: runtimeNotes, steps: steps };
  }

  // ── Static review: things that run but lose marks ───────────────────────
  // Split in two on purpose. The source pass needs no AST, so it still runs
  // when parsing fails — otherwise a student with three mistakes only ever
  // sees the first one, fixes it, and gets ambushed by the next.
  function reviewSource(src) {
    var notes = [];
    var lines = src.split(/\r?\n/);

    lines.forEach(function (l, i) {
      var line = i + 1, t = l.trim();
      if (!t) return;
      // Only suggest capitalising words that ARE Cambridge keywords. Telling a
      // student to write "PRINT" would be worse advice than the lower-case
      // version — print is not in the dialect at all, and the Python check
      // below gives the right answer for it.
      var first = t.split(/[\s(]/)[0];
      if (/^\s*(input|if|for|while|return|else|output|repeat|until|case|declare|call|procedure|function)\b/i.test(l) &&
          !/^\s*[A-Z]/.test(t)) {
        notes.push({ line: line, kind: "warn",
          msg: "Keywords must be in CAPITALS in Cambridge pseudocode.",
          fix: "Write " + first.toUpperCase() + " instead of " + first + "." });
      }
      if (/\bprint\s*\(/i.test(l)) {
        notes.push({ line: line, kind: "error", msg: "print() is Python.",
          fix: 'Use OUTPUT "text", variable' });
      }
      if (/:\s*$/.test(t) && !/\bCASE\b|\bOTHERWISE\b/i.test(t)) {
        notes.push({ line: line, kind: "warn",
          msg: "A trailing colon is Python style.",
          fix: "Cambridge uses THEN / DO and a matching END… instead." });
      }
      if (/\bendif\b|\bendwhile\b/i.test(t) && !/^(ENDIF|ENDWHILE)/.test(t)) {
        notes.push({ line: line, kind: "warn", msg: "Closing keyword should be capitalised.",
          fix: "Write ENDIF / ENDWHILE." });
      }
    });

    return notes;
  }

  function reviewAst(src, ast) {
    var notes = [];
    var lines = src.split(/\r?\n/);
    var declared = [];
    (function walk(sts) {
      sts.forEach(function (s) {
        if (s.k === "decl" || s.k === "declArr") declared.push(s.name);
        ["then", "else", "body"].forEach(function (key) {
          if (Array.isArray(s[key])) walk(s[key]);
        });
        if (s.arms) s.arms.forEach(function (a) { walk(a.body); });
        if (Array.isArray(s.other)) walk(s.other);
      });
    })(ast.body);

    if (!declared.length && ast.body.length > 2) {
      notes.push({ line: 1, kind: "info",
        msg: "Nothing is DECLAREd.",
        fix: "Examiners expect DECLARE Name : TYPE for every variable — it is often a mark." });
    }
    if (!/\/\//.test(src) && lines.length > 12) {
      notes.push({ line: 1, kind: "info", msg: "No comments.",
        fix: "A // comment on each section shows intent and is cheap to write." });
    }
    return notes;
  }

  // ── Requirement extraction ───────────────────────────────────────────────
  // Pattern-matches a Cambridge exam question to produce a checklist of things
  // the student's code needs to demonstrate. Everything is client-side and
  // heuristic — it is a revision tool, not a mark scheme.

  var REQ_PATTERNS = [
    // I/O
    { id: "input",     label: "Read input from the user",
      question: /\b(input|enter|read|accept|ask|prompt|type in)\b/i,
      code: function (src) { return /\bINPUT\b/.test(src); } },
    { id: "output",    label: "Display / output a result",
      question: /\b(output|display|print|show|write|report)\b/i,
      code: function (src) { return /\bOUTPUT\b/.test(src); } },
    // Variables & types
    { id: "declare",   label: "Declare variables with DECLARE",
      question: /\b(variable|store|declare|integer|real|string|boolean|character)\b/i,
      code: function (src) { return /\bDECLARE\b/.test(src); } },
    // Arithmetic & aggregates
    { id: "total",     label: "Calculate a running total",
      question: /\b(total|sum|add up|accumulate)\b/i,
      code: function (src) { return /\bTotal\b|\bSum\b|total\s*<-|sum\s*<-/i.test(src); } },
    { id: "average",   label: "Calculate an average / mean",
      question: /\b(average|mean|avg)\b/i,
      code: function (src) { return /\bAverage\b|\bMean\b|average\s*<-|mean\s*<-/i.test(src); } },
    { id: "count",     label: "Keep a count",
      question: /\b(count|counter|number of|how many|tally)\b/i,
      code: function (src) { return /\bCount\b|count\s*<-|counter\s*<-/i.test(src); } },
    { id: "max",       label: "Find the highest / maximum value",
      question: /\b(highest|maximum|largest|greatest|max)\b/i,
      code: function (src) { return /\bLargest\b|\bMax\b|\bHighest\b|largest\s*<-|max\s*<-/i.test(src); } },
    { id: "min",       label: "Find the lowest / minimum value",
      question: /\b(lowest|minimum|smallest|min)\b/i,
      code: function (src) { return /\bSmallest\b|\bMin\b|\bLowest\b|smallest\s*<-|min\s*<-/i.test(src); } },
    // Control flow
    { id: "if",        label: "Use a conditional (IF … THEN … ENDIF)",
      question: /\b(if|condition|check|test|when|depends|only if|otherwise|else)\b/i,
      code: function (src) { return /\bIF\b/.test(src) && /\bENDIF\b/.test(src); } },
    { id: "for",       label: "Use a FOR … NEXT counted loop",
      question: /\b(for each|for every|n times|repeat n|fixed number|times|iteration)\b/i,
      code: function (src) { return /\bFOR\b/.test(src) && /\bNEXT\b/.test(src); } },
    { id: "while",     label: "Use a WHILE … ENDWHILE loop",
      question: /\b(while|as long as|until the user|loop until stopped)\b/i,
      code: function (src) { return /\bWHILE\b/.test(src) && /\bENDWHILE\b/.test(src); } },
    { id: "repeat",    label: "Use a REPEAT … UNTIL loop",
      question: /\b(repeat|until valid|until correct|keep asking|re-enter|do.+until)\b/i,
      code: function (src) { return /\bREPEAT\b/.test(src) && /\bUNTIL\b/.test(src); } },
    // Validation
    { id: "validate",  label: "Validate / reject out-of-range input",
      question: /\b(valid|validat|range|between|reject|not accept|must be|only accept)\b/i,
      code: function (src) {
        return (/\bREPEAT\b/.test(src) && /\bUNTIL\b/.test(src)) ||
               (/\bWHILE\b/.test(src) && /<>|<|>|<=|>=/.test(src));
      } },
    // Arrays
    { id: "array",     label: "Use an array to store multiple values",
      question: /\b(array|list|collection|series of|several values|multiple values|set of)\b/i,
      code: function (src) { return /\bARRAY\b/.test(src) || /\[\d/.test(src); } },
    // Procedures / functions
    { id: "procedure", label: "Define and call a PROCEDURE",
      question: /\b(procedure|subroutine|module|sub-program|sub-routine)\b/i,
      code: function (src) { return /\bPROCEDURE\b/.test(src) && /\bENDPROCEDURE\b/.test(src); } },
    { id: "function",  label: "Define and call a FUNCTION that returns a value",
      question: /\b(function|returns|return a|return the|a value back)\b/i,
      code: function (src) { return /\bFUNCTION\b/.test(src) && /\bRETURN\b/.test(src); } },
    // Search / sort
    { id: "search",    label: "Search through a collection",
      question: /\b(search|find|look for|locate|check if.+in|linear search|binary search)\b/i,
      code: function (src) { return /\bFOR\b.*\bIF\b|\bWHILE\b.*\bIF\b/s.test(src) || /Found|found\s*<-/i.test(src); } },
    { id: "sort",      label: "Sort values into order",
      question: /\b(sort|order|ascending|descending|arrange|bubble sort)\b/i,
      code: function (src) { return /Swap|swap\s*<-|Temp\s*<-|temp\s*<-/i.test(src) && /\bFOR\b/.test(src); } },
    // String ops
    { id: "string",    label: "Process / manipulate a string",
      question: /\b(string|character|text|letter|word|substring|upper|lower|length|concatenat)\b/i,
      code: function (src) { return /LENGTH|UCASE|LCASE|SUBSTRING|&|NUM_TO_STRING|STRING_TO_NUM/i.test(src); } },
    // Comments
    { id: "comment",   label: "Include comments explaining the code",
      question: /\b(comment|explain|document|annotate|describe)\b/i,
      code: function (src) { return /\/\//.test(src); } }
  ];

  function extractRequirements(questionText) {
    return REQ_PATTERNS.filter(function (r) { return r.question.test(questionText); });
  }

  function checkRequirements(reqs, src) {
    return reqs.map(function (r) {
      return { req: r, done: r.code(src) };
    });
  }

  var SAMPLES = {
    "Average of 10 numbers":
      "// Reads 10 numbers and reports the average\n" +
      "DECLARE Count : INTEGER\nDECLARE Number : INTEGER\nDECLARE Total : INTEGER\n" +
      "DECLARE Average : REAL\n\nTotal <- 0\n\nFOR Count <- 1 TO 10\n" +
      "    INPUT Number\n    Total <- Total + Number\nNEXT Count\n\n" +
      "Average <- Total / 10\nOUTPUT \"Average is \", Average\n",
    "Largest in an array":
      "DECLARE Values : ARRAY[1:5] OF INTEGER\nDECLARE Index : INTEGER\n" +
      "DECLARE Largest : INTEGER\n\nFOR Index <- 1 TO 5\n    INPUT Values[Index]\nNEXT Index\n\n" +
      "Largest <- Values[1]\nFOR Index <- 2 TO 5\n    IF Values[Index] > Largest THEN\n" +
      "        Largest <- Values[Index]\n    ENDIF\nNEXT Index\n\n" +
      "OUTPUT \"Largest is \", Largest\n",
    "Validation with REPEAT":
      "DECLARE Mark : INTEGER\n\nREPEAT\n    OUTPUT \"Enter a mark 0-100\"\n" +
      "    INPUT Mark\nUNTIL Mark >= 0 AND Mark <= 100\n\n" +
      "OUTPUT \"Accepted: \", Mark\n",
    "Procedure and function":
      "FUNCTION Square(N : INTEGER) RETURNS INTEGER\n    RETURN N * N\nENDFUNCTION\n\n" +
      "PROCEDURE ShowSquares(Limit : INTEGER)\n    DECLARE I : INTEGER\n" +
      "    FOR I <- 1 TO Limit\n        OUTPUT I, \" squared is \", Square(I)\n" +
      "    NEXT I\nENDPROCEDURE\n\nCALL ShowSquares(5)\n",
    "Deliberately broken":
      "// Every mistake here is one students really make\n" +
      "count = 0\nfor i = 1 to 5\n    print(i)\n" +
      "Total <- Total + Values[0]\n"
  };

  // ── Widget ──────────────────────────────────────────────────────────────
  function mount(root, opts) {
    var PWTx = window.PWT, esc = PWTx.esc;
    var compact = opts && opts.mode === "dock";

    root.innerHTML =
      '<div class="ps-wrap' + (compact ? " compact" : "") + '">' +
        '<div class="ps-left">' +

          // ── Question box at the TOP ────────────────────────────────────────
          '<div class="ps-question-box" data-qbox>' +
            '<button class="ps-qtoggle open" data-qtoggle>📋 Exam question <span class="ps-qtoggle-hint">paste here first</span></button>' +
            '<div class="ps-qdrop" data-qdrop>' +
              '<div class="ps-qguide">' +
                '<p><strong>How to use:</strong> Paste the full exam question below, then write your pseudocode in the editor. ' +
                'The <em>Requirements</em> tab tracks your progress automatically as you type.</p>' +
                '<details class="ps-qdetails">' +
                  '<summary>What counts as a requirement?</summary>' +
                  '<ul>' +
                    '<li><strong>Input / output</strong> — any question asking you to read or display values</li>' +
                    '<li><strong>Loops</strong> — keywords like "repeat", "10 times", "for each", "while", "until valid"</li>' +
                    '<li><strong>Conditions</strong> — "if", "check", "only if", "otherwise", "depends on"</li>' +
                    '<li><strong>Totals / averages / counts / max / min</strong> — any aggregate calculation</li>' +
                    '<li><strong>Arrays</strong> — "store", "list", "array", "set of values"</li>' +
                    '<li><strong>Validation</strong> — "valid", "between", "reject", "must be", "re-enter"</li>' +
                    '<li><strong>Procedures / functions</strong> — "procedure", "subroutine", "return a value"</li>' +
                    '<li><strong>Search / sort</strong> — "find", "search", "ascending", "descending"</li>' +
                  '</ul>' +
                  '<p class="ps-qhint">Tip: paste the <em>whole</em> question, not just bullet points — the wording matters for detection.</p>' +
                '</details>' +
              '</div>' +
              '<textarea class="fs-search ps-qtext" data-qtext rows="7" ' +
                'placeholder="e.g. Write a pseudocode program that reads 10 integers from the user, validates that each is between 0 and 100, calculates the total and average, and outputs both results." ' +
                'spellcheck="false"></textarea>' +
              '<p class="ps-qhint">Requirements update live as you code — no need to run first.</p>' +
            '</div>' +
          '</div>' +

          // ── Toolbar ────────────────────────────────────────────────────────
          '<div class="ps-toolbar">' +
            '<button class="ps-run" data-run>▶ Run</button>' +
            '<select class="tool-select" data-sample>' +
              '<option value="">Load an example…</option>' +
              Object.keys(SAMPLES).map(function (k) {
                return '<option>' + esc(k) + "</option>"; }).join("") +
            "</select>" +
            '<button class="calc-lock-btn" data-clear style="color:var(--grey)">Clear</button>' +
          "</div>" +
          '<div class="ps-editor">' +
            '<div class="ps-gutter" data-gutter>1</div>' +
            '<textarea class="ps-code" data-code spellcheck="false" ' +
              'autocomplete="off" autocapitalize="off" wrap="off"></textarea>' +
          "</div>" +
          '<label class="ps-inputs"><span>INPUT values — one per line</span>' +
            '<textarea class="fs-search" data-inputs rows="3" spellcheck="false"></textarea>' +
          "</label>" +
        "</div>" +
        '<div class="ps-right">' +
          '<div class="fs-filter ps-tabs" data-panes role="group">' +
            '<button data-p="out" class="on">Output</button>' +
            '<button data-p="diag">Errors <span class="ps-badge" data-badge hidden>0</span></button>' +
            '<button data-p="trace">Trace table</button>' +
            '<button data-p="quest">Requirements</button>' +
          "</div>" +
          '<div class="ps-pane" data-pane></div>' +
        "</div>" +
      "</div>";

    var $ = function (s) { return root.querySelector(s); };
    var codeEl = $("[data-code]"), gutter = $("[data-gutter]"), pane = $("[data-pane]");
    var inputsEl = $("[data-inputs]"), badge = $("[data-badge]");
    var paneTabs = $("[data-panes]");
    var activePane = "out";
    var last = { output: [], diag: [], trace: [], watched: [] };
    var activeReqs = [];   // requirement objects currently derived from the question

    function syncGutter() {
      var n = codeEl.value.split("\n").length;
      var html = "";
      for (var i = 1; i <= n; i++) html += i + "\n";
      gutter.textContent = html;
      gutter.scrollTop = codeEl.scrollTop;
    }
    // (input listener for gutter sync + requirements is added below)
    codeEl.addEventListener("scroll", function () { gutter.scrollTop = codeEl.scrollTop; });

    // Tab indents rather than escaping the editor — this is a code box.
    codeEl.addEventListener("keydown", function (ev) {
      if (ev.key !== "Tab") return;
      ev.preventDefault();
      var s = codeEl.selectionStart, e = codeEl.selectionEnd;
      codeEl.value = codeEl.value.slice(0, s) + "    " + codeEl.value.slice(e);
      codeEl.selectionStart = codeEl.selectionEnd = s + 4;
      syncGutter();
    });

    $("[data-sample]").addEventListener("change", function (ev) {
      var k = ev.target.value;
      if (!k) return;
      codeEl.value = SAMPLES[k];
      inputsEl.value = k === "Average of 10 numbers" ? "4\n8\n15\n16\n23\n42\n7\n11\n9\n5"
        : k === "Largest in an array" ? "12\n45\n7\n89\n33"
        : k === "Validation with REPEAT" ? "150\n-3\n72" : "";
      syncGutter();
      doRun();
      ev.target.value = "";
    });

    $("[data-clear]").addEventListener("click", function () {
      codeEl.value = ""; inputsEl.value = ""; syncGutter();
      last = { output: [], diag: [], trace: [], watched: [] };
      draw();
    });

    paneTabs.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-p]");
      if (!b) return;
      activePane = b.dataset.p;
      paneTabs.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      draw();
    });

    $("[data-run]").addEventListener("click", doRun);
    codeEl.addEventListener("keydown", function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") { ev.preventDefault(); doRun(); }
    });

    // ── Question box toggle ────────────────────────────────────────────────
    $("[data-qtoggle]").addEventListener("click", function () {
      var drop = $("[data-qdrop]");
      var hidden = drop.hidden;
      drop.hidden = !hidden;
      $("[data-qtoggle]").classList.toggle("open", !hidden === false ? false : true);
    });

    // Re-extract requirements whenever the question text changes.
    $("[data-qtext]").addEventListener("input", function () {
      activeReqs = extractRequirements($("[data-qtext]").value);
      if (activePane === "quest") draw();
      updateQuestBadge();
    });

    // Also update progress whenever code changes (without running).
    codeEl.addEventListener("input", function () {
      syncGutter();
      if (activeReqs.length && activePane === "quest") draw();
      updateQuestBadge();
    });

    function updateQuestBadge() {
      var questBtn = paneTabs.querySelector('[data-p="quest"]');
      if (!questBtn) return;
      if (!activeReqs.length) { questBtn.dataset.qcount = ""; return; }
      var done = checkRequirements(activeReqs, codeEl.value).filter(function (r) { return r.done; }).length;
      questBtn.dataset.qcount = done + "/" + activeReqs.length;
    }

    function doRun() {
      var src = codeEl.value;
      last = { output: [], diag: [], trace: [], watched: [] };
      if (!src.trim()) { draw(); return; }

      // The source review runs first and unconditionally, so every style
      // problem is listed even if the parser gives up on line 2.
      last.diag = last.diag.concat(reviewSource(src));

      var ast = null;
      try {
        ast = parse(lex(src));
        last.diag = last.diag.concat(ast.notes);
      } catch (e) {
        last.diag.push({ line: e.line, kind: "error", msg: e.message, fix: e.fix });
        last.diag.sort(function (a, b) { return (a.line || 0) - (b.line || 0); });
        activePane = "diag";
        draw();
        return;
      }

      last.diag = last.diag.concat(reviewAst(src, ast));
      last.diag.sort(function (a, b) { return (a.line || 0) - (b.line || 0); });

      try {
        var r = run(ast, inputsEl.value.split(/\r?\n/).filter(function (x, i, a) {
          return !(x === "" && i === a.length - 1);
        }));
        last.output = r.output;
        last.trace = r.trace;
        last.watched = r.watched;
        last.diag = last.diag.concat(r.notes);
        last.steps = r.steps;
      } catch (e) {
        if (e && e.pseudo) last.diag.push({ line: e.line, kind: "error", msg: e.message, fix: e.fix });
        else last.diag.push({ line: null, kind: "error", msg: e.message, fix: null });
        activePane = "diag";
      }
      draw();
    }

    function draw() {
      var errs = last.diag.filter(function (d) { return d.kind === "error"; }).length;
      badge.hidden = last.diag.length === 0;
      badge.textContent = last.diag.length;
      badge.className = "ps-badge" + (errs ? " bad" : "");

      // ── Requirements pane ─────────────────────────────────────────────────
      if (activePane === "quest") {
        var qtext = $("[data-qtext]").value.trim();
        if (!qtext) {
          pane.innerHTML =
            '<div class="ps-quest-empty">' +
              '<p class="fs-vars">Paste an exam question into the <strong>📋 Paste exam question</strong> box ' +
              'on the left — requirements will be extracted automatically.</p>' +
              '<p class="fs-vars" style="margin-top:8px">Example: <em>&ldquo;Write a pseudocode program that ' +
              'reads 10 integers from the user, calculates the total and average, and outputs the result.&rdquo;</em></p>' +
            '</div>';
          return;
        }
        if (!activeReqs.length) {
          pane.innerHTML = '<p class="fs-vars">No specific requirements could be detected — try rephrasing or check the question wording.</p>';
          return;
        }
        var src = codeEl.value;
        var checked = checkRequirements(activeReqs, src);
        var doneCount = checked.filter(function (r) { return r.done; }).length;
        var total = checked.length;
        var pct = Math.round((doneCount / total) * 100);
        var barColour = pct === 100 ? "var(--green,#4ade80)" : pct >= 60 ? "var(--accent)" : "var(--warn,#f59e0b)";

        pane.innerHTML =
          '<div class="ps-quest-header">' +
            '<div class="ps-quest-prog-wrap">' +
              '<div class="ps-quest-prog-bar" style="width:' + pct + '%;background:' + barColour + '"></div>' +
            '</div>' +
            '<p class="ps-quest-count">' + doneCount + ' of ' + total + ' requirement' + (total !== 1 ? 's' : '') + ' met' +
              (pct === 100 ? ' ✓ All done!' : '') + '</p>' +
          '</div>' +
          '<ul class="ps-quest-list">' +
            checked.map(function (item) {
              return '<li class="ps-quest-item ' + (item.done ? 'done' : 'todo') + '">' +
                '<span class="ps-quest-tick">' + (item.done ? '✓' : '○') + '</span>' +
                '<span class="ps-quest-label">' + esc(item.req.label) + '</span>' +
                '</li>';
            }).join('') +
          '</ul>' +
          '<p class="ps-qhint" style="margin-top:12px">Requirements update as you type — no need to run the code.</p>';
        return;
      }

      if (activePane === "out") {
        pane.innerHTML = last.output.length
          ? '<pre class="ps-out">' + last.output.map(esc).join("\n") + "</pre>" +
            (last.steps ? '<p class="fs-vars">Ran in ' + last.steps.toLocaleString() + " steps.</p>" : "")
          : '<p class="fs-vars">Nothing output yet — press <strong>Run</strong> (or Ctrl+Enter).</p>';
        return;
      }

      if (activePane === "diag") {
        if (!last.diag.length) {
          pane.innerHTML = '<div class="ps-clean">✓ No problems found. ' +
            "Logic runs and the style matches the Cambridge guide.</div>";
          return;
        }
        pane.innerHTML = last.diag.map(function (d) {
          return '<div class="ps-diag ' + d.kind + '">' +
            '<div class="ps-diag-head">' +
              (d.line ? '<button class="ps-diag-line" data-goto="' + d.line + '">line ' + d.line + "</button>" : "") +
              '<span class="ps-diag-kind">' + d.kind + "</span>" +
            "</div>" +
            '<p class="ps-diag-msg">' + esc(d.msg) + "</p>" +
            (d.fix ? '<p class="ps-diag-fix"><strong>Try:</strong> ' + esc(d.fix) + "</p>" : "") +
            "</div>";
        }).join("");
        return;
      }

      if (!last.trace.length) {
        pane.innerHTML = '<p class="fs-vars">Run something with variables to see the trace table.</p>';
        return;
      }
      var cols = last.watched;
      pane.innerHTML =
        '<div class="lg-tbl-wrap"><table class="lg-truth ps-trace"><thead><tr><th>Line</th>' +
          cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") +
        "</tr></thead><tbody>" +
        last.trace.map(function (r) {
          return "<tr><td>" + r.line + "</td>" +
            cols.map(function (c) { return "<td>" + esc(r[c] === undefined ? "" : r[c]) + "</td>"; }).join("") +
            "</tr>";
        }).join("") + "</tbody></table></div>" +
        '<p class="fs-vars">A row is recorded whenever a value changes — the same ' +
        "way you would fill one in by hand.</p>";
    }

    pane.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-goto]");
      if (!b) return;
      // Put the caret on the offending line so the fix is one keystroke away.
      var ln = +b.dataset.goto;
      var pos = codeEl.value.split("\n").slice(0, ln - 1).join("\n").length + (ln > 1 ? 1 : 0);
      codeEl.focus();
      codeEl.setSelectionRange(pos, pos + (codeEl.value.split("\n")[ln - 1] || "").length);
    });

    codeEl.value = SAMPLES["Average of 10 numbers"];
    inputsEl.value = "4\n8\n15\n16\n23\n42\n7\n11\n9\n5";
    syncGutter();
    doRun();

    return function teardown() { root.innerHTML = ""; };
  }

  if (window.PWT) {
    window.PWT.register({ id: "pseudocode", name: "Pseudocode runner", icon: "⌨️", mount: mount });
  }
  window.PWTPseudo = { lex: lex, parse: parse, run: run,
    reviewSource: reviewSource, reviewAst: reviewAst };
})();
