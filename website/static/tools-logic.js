/* PrepWithTee — number bases & logic (mountable widget).
 *
 * Covers the Data-representation and Boolean-logic topics that are guaranteed
 * marks and just as guaranteed to be dropped. Everything shows the WORKING,
 * because that is what the mark scheme rewards: place-value columns for a
 * conversion, carry rows for an addition, every intermediate column in a truth
 * table, and the invert-then-add-one steps for two's complement.
 *
 * Calculators are banned in every Computer Science paper (2210, 0478, 9618),
 * so this is for learning and checking — never a substitute for the method.
 *
 * Views: bases · two's complement · binary arithmetic · floating point (A2)
 *        · truth tables · gate simulator · practice
 */
(function () {
  "use strict";

  // ── Base conversion ─────────────────────────────────────────────────────
  function parseIn(text, base) {
    var t = String(text).trim().replace(/\s+/g, "").toUpperCase();
    if (!t) return null;
    var digits = "0123456789ABCDEF".slice(0, base);
    for (var i = 0; i < t.length; i++) {
      if (digits.indexOf(t[i]) < 0) {
        throw new Error("“" + t[i] + "” is not a valid digit in base " + base);
      }
    }
    var v = parseInt(t, base);
    if (!isFinite(v)) throw new Error("That number is too large");
    return v;
  }

  function toBase(v, base, pad) {
    var s = (v >>> 0).toString(base).toUpperCase();
    if (pad && base === 2) while (s.length % 8) s = "0" + s;
    return s;
  }

  // Cambridge writes binary in nibbles; ungrouped strings are where miscounts
  // happen, so every binary string this tool shows is grouped.
  function groupBits(s) {
    var out = [], t = s;
    while (t.length > 4) { out.unshift(t.slice(-4)); t = t.slice(0, -4); }
    out.unshift(t);
    return out.join(" ");
  }

  function placeValueTable(v) {
    var bin = toBase(v, 2, true), cols = bin.split(""), n = cols.length;
    var head = "", row = "", val = "";
    cols.forEach(function (b, i) {
      var pv = Math.pow(2, n - 1 - i);
      head += "<th>" + pv + "</th>";
      row += "<td>" + b + "</td>";
      val += '<td class="' + (b === "1" ? "pv-on" : "pv-off") + '">' +
             (b === "1" ? pv : "0") + "</td>";
    });
    return '<div class="lg-tbl-wrap"><table class="lg-pv">' +
      "<tr><th>Place value</th>" + head + "</tr>" +
      "<tr><th>Bit</th>" + row + "</tr>" +
      "<tr><th>Contributes</th>" + val + "</tr></table></div>" +
      '<p class="lg-sum">' + (cols.some(function (b) { return b === "1"; })
        ? cols.map(function (b, i) { return b === "1" ? Math.pow(2, n - 1 - i) : null; })
              .filter(Boolean).join(" + ")
        : "0") + " = <strong>" + v + "</strong></p>";
  }

  // ── Two's complement ────────────────────────────────────────────────────
  function twos(v, bits) {
    var max = Math.pow(2, bits - 1);
    if (v >= 0) {
      if (v > max - 1) return { err: v + " will not fit in " + bits + " bits (max " + (max - 1) + ")" };
      return { bits: toBase(v, 2).padStart(bits, "0"), steps: null };
    }
    if (v < -max) return { err: v + " will not fit in " + bits + " bits (min " + (-max) + ")" };
    var mag = toBase(-v, 2).padStart(bits, "0");
    var inv = flip(mag);
    var res = addBits(inv, "1".padStart(bits, "0"), bits).sum;
    return { bits: res, steps: { mag: mag, inv: inv } };
  }

  function flip(s) {
    return s.split("").map(function (b) { return b === "0" ? "1" : "0"; }).join("");
  }

  // Column addition, keeping the carry row — the row the mark scheme wants.
  function addBits(a, b, bits) {
    a = a.padStart(bits, "0"); b = b.padStart(bits, "0");
    var sum = "", carries = "", c = 0;
    for (var i = bits - 1; i >= 0; i--) {
      var x = +a[i], y = +b[i], t = x + y + c;
      sum = (t & 1) + sum;
      carries = (c ? "1" : " ") + carries;
      c = t > 1 ? 1 : 0;
    }
    return { sum: sum, carries: carries, carryOut: c };
  }

  function fromTwos(bitsStr) {
    var n = bitsStr.length;
    return bitsStr[0] === "1" ? parseInt(bitsStr, 2) - Math.pow(2, n) : parseInt(bitsStr, 2);
  }

  // ── Floating point (9618 A2) ────────────────────────────────────────────
  // Mantissa is a two's complement fraction with the point after the sign bit;
  // exponent is a two's complement integer. Normalised means the first two
  // bits differ: 0.1… for positive, 1.0… for negative.
  function toFloat(value, mBits, eBits) {
    if (value === 0) {
      return { mantissa: "0".repeat(mBits), exponent: "0".repeat(eBits),
               note: "Zero cannot be normalised — it is stored as all zeros." };
    }
    var eMin = -Math.pow(2, eBits - 1), eMax = Math.pow(2, eBits - 1) - 1;
    var exp = 0, m = value;
    // Drive the mantissa into [0.5, 1) for positives, [-1, -0.5) for negatives.
    if (value > 0) {
      while (m >= 1) { m /= 2; exp++; }
      while (m < 0.5) { m *= 2; exp--; }
    } else {
      while (m < -1) { m /= 2; exp++; }
      while (m >= -0.5) { m *= 2; exp--; }
    }
    if (exp < eMin || exp > eMax) {
      return { err: "Exponent " + exp + " does not fit in " + eBits +
        " bits (range " + eMin + " to " + eMax + ")" };
    }
    // Encode the fraction: multiply by 2^(mBits-1) and take two's complement.
    var scaled = Math.round(m * Math.pow(2, mBits - 1));
    if (scaled === Math.pow(2, mBits - 1)) { scaled /= 2; exp++; }   // rounding tipped it to 1.0
    var mant = scaled < 0
      ? (scaled + Math.pow(2, mBits)).toString(2).padStart(mBits, "0")
      : scaled.toString(2).padStart(mBits, "0");
    var e = exp < 0
      ? (exp + Math.pow(2, eBits)).toString(2).padStart(eBits, "0")
      : exp.toString(2).padStart(eBits, "0");
    return { mantissa: mant, exponent: e, expVal: exp, mantVal: m,
             normalised: mant[0] !== mant[1] };
  }

  function fromFloat(mant, e) {
    var mv = fromTwos(mant) / Math.pow(2, mant.length - 1);
    var ev = fromTwos(e);
    return { mantissa: mv, exponent: ev, value: mv * Math.pow(2, ev),
             normalised: mant[0] !== mant[1] };
  }

  // ── Boolean expressions ─────────────────────────────────────────────────
  function boolTokens(src) {
    var s = String(src).toUpperCase()
      .replace(/·|∧|&&|&/g, " AND ").replace(/\+|∨|\|\||\|/g, " OR ")
      .replace(/¬|!|~/g, " NOT ").replace(/⊕/g, " XOR ");
    var out = [], i = 0;
    var WORDS = ["NAND", "NOR", "XOR", "AND", "NOT", "OR"];
    while (i < s.length) {
      var c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      if (c === "(" || c === ")") { out.push({ t: c }); i++; continue; }
      var w = WORDS.find(function (k) { return s.startsWith(k, i); });
      if (w) { out.push({ t: "op", v: w }); i += w.length; continue; }
      if (/[A-Z]/.test(c)) { out.push({ t: "var", v: c }); i++; continue; }
      if (c === "0" || c === "1") { out.push({ t: "lit", v: c === "1" }); i++; continue; }
      throw new Error("Unexpected “" + c + "” in the expression");
    }
    return out;
  }

  // NOT binds tightest, then AND/NAND, then XOR, then OR/NOR.
  function parseBool(toks) {
    var pos = 0;
    function peek() { return toks[pos]; }
    function eat() { return toks[pos++]; }
    function primary() {
      var tk = peek();
      if (!tk) throw new Error("Expression ends too early");
      if (tk.t === "(") {
        eat();
        var e = orExpr();
        if (!peek() || peek().t !== ")") throw new Error("Missing a closing )");
        eat();
        return e;
      }
      if (tk.t === "op" && tk.v === "NOT") { eat(); return { op: "NOT", a: primary() }; }
      if (tk.t === "var") { eat(); return { v: tk.v }; }
      if (tk.t === "lit") { eat(); return { lit: tk.v }; }
      throw new Error("Expected a variable, not “" + (tk.v || tk.t) + "”");
    }
    function andExpr() {
      var l = primary();
      while (peek() && peek().t === "op" && (peek().v === "AND" || peek().v === "NAND")) {
        var op = eat().v; l = { op: op, a: l, b: primary() };
      }
      return l;
    }
    function xorExpr() {
      var l = andExpr();
      while (peek() && peek().t === "op" && peek().v === "XOR") { eat(); l = { op: "XOR", a: l, b: andExpr() }; }
      return l;
    }
    function orExpr() {
      var l = xorExpr();
      while (peek() && peek().t === "op" && (peek().v === "OR" || peek().v === "NOR")) {
        var op = eat().v; l = { op: op, a: l, b: xorExpr() };
      }
      return l;
    }
    var ast = orExpr();
    if (pos < toks.length) throw new Error("Unexpected “" + (toks[pos].v || toks[pos].t) + "” at the end");
    return ast;
  }

  function evalBool(node, env) {
    if (node.lit !== undefined) return node.lit;
    if (node.v !== undefined) return !!env[node.v];
    var a = evalBool(node.a, env);
    if (node.op === "NOT") return !a;
    var b = evalBool(node.b, env);
    switch (node.op) {
      case "AND": return a && b;
      case "OR": return a || b;
      case "NAND": return !(a && b);
      case "NOR": return !(a || b);
      case "XOR": return a !== b;
    }
    throw new Error("Unknown operator " + node.op);
  }

  function varsOf(node, set) {
    set = set || [];
    if (node.v !== undefined && set.indexOf(node.v) < 0) set.push(node.v);
    if (node.a) varsOf(node.a, set);
    if (node.b) varsOf(node.b, set);
    return set.sort();
  }
  function subExprs(node, out) {
    out = out || [];
    if (node.a) subExprs(node.a, out);
    if (node.b) subExprs(node.b, out);
    if (node.op) { var l = render(node); if (out.indexOf(l) < 0) out.push(l); }
    return out;
  }
  function render(node) {
    if (node.lit !== undefined) return node.lit ? "1" : "0";
    if (node.v !== undefined) return node.v;
    if (node.op === "NOT") return "NOT " + wrap(node.a);
    return wrap(node.a) + " " + node.op + " " + wrap(node.b);
  }
  function wrap(n) { return n.op && n.op !== "NOT" ? "(" + render(n) + ")" : render(n); }
  function findNode(node, label) {
    if (node.op && render(node) === label) return node;
    return (node.a && findNode(node.a, label)) || (node.b && findNode(node.b, label)) || null;
  }
  function rowsFor(vars) {
    var n = Math.pow(2, vars.length), rows = [];
    for (var i = 0; i < n; i++) {
      var env = {};
      // Count downwards so the table reads 000, 001, 010 … like the paper.
      vars.forEach(function (v, j) { env[v] = !!((i >> (vars.length - 1 - j)) & 1); });
      rows.push(env);
    }
    return rows;
  }

  // ── Gate diagram ────────────────────────────────────────────────────────
  // Laid out right-to-left from the output: depth sets the column, so the
  // picture reads the way a paper draws it.
  function gateSVG(ast, env, esc) {
    var GW = 54, GH = 34, COLW = 96, ROWH = 52, PAD = 14;
    var nodes = [], leaves = [];

    (function measure(n, depth) {
      n.__d = depth;
      if (n.v !== undefined || n.lit !== undefined) { leaves.push(n); return 1; }
      var h = measure(n.a, depth + 1) + (n.b ? measure(n.b, depth + 1) : 0);
      n.__h = h;
      nodes.push(n);
      return h;
    })(ast, 0);

    var maxD = 0;
    nodes.concat(leaves).forEach(function (n) { maxD = Math.max(maxD, n.__d); });

    var yCursor = 0;
    (function place(n) {
      if (n.v !== undefined || n.lit !== undefined) { n.__y = (yCursor++) * ROWH + ROWH / 2; return; }
      place(n.a);
      if (n.b) place(n.b);
      n.__y = n.b ? (n.a.__y + n.b.__y) / 2 : n.a.__y;
    })(ast);

    var W = (maxD + 1) * COLW + 90, H = yCursor * ROWH + PAD * 2;
    var X = function (n) { return PAD + (maxD - n.__d) * COLW; };
    var wires = "", shapes = "", labels = "";

    function val(n) { return evalBool(n, env); }
    function wire(x1, y1, x2, y2, on) {
      var mid = (x1 + x2) / 2;
      return '<path d="M' + x1 + ' ' + y1 + ' H' + mid + ' V' + y2 + ' H' + x2 + '" ' +
        'class="gs-wire' + (on ? " on" : "") + '"/>';
    }

    (function draw(n) {
      if (n.v !== undefined || n.lit !== undefined) {
        var on = val(n);
        var lx = X(n) + PAD;
        labels += '<g class="gs-input' + (on ? " on" : "") + '" data-var="' +
          (n.v || "") + '">' +
          '<circle cx="' + lx + '" cy="' + n.__y + '" r="13"/>' +
          '<text x="' + lx + '" y="' + (n.__y + 4) + '">' +
          esc(n.v !== undefined ? n.v : (n.lit ? "1" : "0")) + "</text></g>";
        n.__out = { x: lx + 13, y: n.__y };
        return;
      }
      draw(n.a);
      if (n.b) draw(n.b);

      var gx = X(n) + PAD + 18, gy = n.__y;
      var on = val(n);
      shapes += gateShape(n.op, gx, gy, GW, GH, on);
      n.__out = { x: gx + GW / 2 + (/N(AND|OR)|NOT/.test(n.op) ? 8 : 0), y: gy };

      var ins = n.b ? [n.a, n.b] : [n.a];
      ins.forEach(function (c, i) {
        var iy = n.b ? gy + (i === 0 ? -9 : 9) : gy;
        wires += wire(c.__out.x, c.__out.y, gx - GW / 2, iy, val(c));
      });
    })(ast);

    // output stub
    wires += '<path d="M' + ast.__out.x + ' ' + ast.__out.y + ' h26" class="gs-wire' +
      (val(ast) ? " on" : "") + '"/>';
    labels += '<text class="gs-out' + (val(ast) ? " on" : "") + '" x="' +
      (ast.__out.x + 32) + '" y="' + (ast.__out.y + 5) + '">' + (val(ast) ? "1" : "0") + "</text>";

    return '<svg class="gs-svg" viewBox="0 0 ' + (W + 20) + " " + H +
      '" preserveAspectRatio="xMinYMid meet">' + wires + shapes + labels + "</svg>";
  }

  function gateShape(op, cx, cy, w, h, on) {
    var l = cx - w / 2, r = cx + w / 2, t = cy - h / 2, b = cy + h / 2;
    var cls = "gs-gate" + (on ? " on" : "");
    var bubble = "";
    var body = "";
    var base = op.replace(/^N(AND|OR)$/, "$1");

    if (op === "NOT") {
      body = '<path class="' + cls + '" d="M' + l + ' ' + t + ' L' + l + ' ' + b +
             ' L' + r + ' ' + cy + " Z\"/>";
      bubble = '<circle class="' + cls + '" cx="' + (r + 5) + '" cy="' + cy + '" r="4.5"/>';
    } else if (base === "AND") {
      body = '<path class="' + cls + '" d="M' + l + ' ' + t + ' H' + (cx) +
             ' A' + (h / 2) + " " + (h / 2) + " 0 0 1 " + cx + " " + b +
             " H" + l + " Z\"/>";
    } else {
      // OR / NOR / XOR — curved back, pointed nose
      body = '<path class="' + cls + '" d="M' + l + ' ' + t +
             " Q" + (cx) + " " + t + " " + r + " " + cy +
             " Q" + (cx) + " " + b + " " + l + " " + b +
             " Q" + (l + 12) + " " + cy + " " + l + " " + t + " Z\"/>";
      if (op === "XOR") {
        body = '<path class="gs-xarc" d="M' + (l - 7) + ' ' + t +
               " Q" + (l + 5) + " " + cy + " " + (l - 7) + " " + b + "\"/>" + body;
      }
    }
    if (/^N(AND|OR)$/.test(op)) {
      bubble = '<circle class="' + cls + '" cx="' + (r + 5) + '" cy="' + cy + '" r="4.5"/>';
    }
    var label = '<text class="gs-label" x="' + (cx - 3) + '" y="' + (cy + 4) + '">' +
      (op === "NOT" ? "" : op) + "</text>";
    return body + bubble + label;
  }

  // ── Widget ──────────────────────────────────────────────────────────────
  function mount(root, opts) {
    var PWTx = window.PWT, esc = PWTx.esc;

    var VIEWS = [
      ["bases", "Bases"], ["twos", "Two’s complement"], ["arith", "Binary arithmetic"],
      ["float", "Floating point"], ["logic", "Truth tables"],
      ["gates", "Gate simulator"], ["practice", "Practice"]
    ];

    root.innerHTML =
      '<div class="fs-controls">' +
        '<div class="fs-filter lg-views" data-view role="group" aria-label="View">' +
          VIEWS.map(function (v, i) {
            return '<button data-v="' + v[0] + '"' + (i === 0 ? ' class="on"' : "") +
              ">" + v[1] + "</button>";
          }).join("") +
        "</div>" +
      "</div><div data-out></div>";

    var out = root.querySelector("[data-out]"), viewEl = root.querySelector("[data-view]");
    var view = "bases";

    viewEl.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-v]");
      if (!b) return;
      view = b.dataset.v;
      viewEl.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render_();
    });

    function render_() {
      ({ bases: renderBases, twos: renderTwos, arith: renderArith, float: renderFloat,
         logic: renderLogic, gates: renderGates, practice: renderPractice }[view])();
    }

    // ── Bases ─────────────────────────────────────────────────────────────
    function renderBases() {
      out.innerHTML =
        '<p class="cw-note">Type in any box — the others follow. Calculators are not ' +
        "allowed in any Computer Science paper, so work it out by hand first and use " +
        "this to check.</p>" +
        '<div class="lg-bases">' +
          ["Denary (base 10)|10", "Binary (base 2)|2", "Hexadecimal (base 16)|16",
           "Octal (base 8)|8"].map(function (spec) {
            var p = spec.split("|");
            return '<label class="lg-field"><span>' + p[0] + "</span>" +
              '<input class="fs-search" data-base="' + p[1] + '" spellcheck="false" autocomplete="off"></label>';
          }).join("") +
        '</div><div data-work class="lg-work"></div>';

      var inputs = [].slice.call(out.querySelectorAll("[data-base]"));
      var work = out.querySelector("[data-work]");
      inputs.forEach(function (inp) {
        inp.addEventListener("input", function () {
          var v;
          try { v = parseIn(inp.value, +inp.dataset.base); }
          catch (e) { work.innerHTML = '<p class="gp-err">' + esc(e.message) + "</p>"; return; }
          if (v === null) {
            inputs.forEach(function (o) { if (o !== inp) o.value = ""; });
            work.innerHTML = ""; return;
          }
          inputs.forEach(function (o) {
            if (o === inp) return;
            var b = +o.dataset.base;
            o.value = b === 2 ? groupBits(toBase(v, 2, true)) : toBase(v, b);
          });
          work.innerHTML = "<h3>Working</h3>" + placeValueTable(v) +
            '<p class="fs-vars">Hex groups the binary into nibbles of four: ' +
            esc(groupBits(toBase(v, 2, true))) + " → " + esc(toBase(v, 16)) + "</p>";
        });
      });
      inputs[0].value = "202";
      inputs[0].dispatchEvent(new Event("input"));
    }

    // ── Two's complement ──────────────────────────────────────────────────
    function renderTwos() {
      out.innerHTML =
        '<p class="cw-note">Negative binary, the syllabus way: write the positive value, ' +
        "invert every bit, then add one.</p>" +
        '<div class="lg-bases">' +
          '<label class="lg-field"><span>Denary value</span>' +
            '<input class="fs-search" data-v type="number" value="-53"></label>' +
          '<label class="lg-field"><span>Width</span>' +
            '<select class="tool-select" data-bits><option>8</option><option>16</option></select></label>' +
        '</div><div data-work class="lg-work"></div>';
      var vIn = out.querySelector("[data-v]"), bIn = out.querySelector("[data-bits]");
      var work = out.querySelector("[data-work]");
      function go() {
        var v = parseInt(vIn.value, 10), bits = +bIn.value;
        if (isNaN(v)) { work.innerHTML = ""; return; }
        var r = twos(v, bits);
        if (r.err) { work.innerHTML = '<p class="gp-err">' + esc(r.err) + "</p>"; return; }
        work.innerHTML = r.steps
          ? '<table class="lg-steps">' +
              "<tr><th>1. " + Math.abs(v) + " in binary</th><td><code>" + groupBits(r.steps.mag) + "</code></td></tr>" +
              "<tr><th>2. Invert every bit</th><td><code>" + groupBits(r.steps.inv) + "</code></td></tr>" +
              '<tr><th>3. Add one</th><td><code class="lg-ans">' + groupBits(r.bits) + "</code></td></tr></table>" +
              '<p class="fs-vars">The leftmost bit is 1, which is what marks it negative.</p>'
          : '<p class="lg-sum">Positive, so it is written normally: <code class="lg-ans">' +
            groupBits(r.bits) + "</code></p>";
      }
      vIn.addEventListener("input", go);
      bIn.addEventListener("change", go);
      go();
    }

    // ── Binary arithmetic ─────────────────────────────────────────────────
    function renderArith() {
      out.innerHTML =
        '<p class="cw-note">Addition is done in columns with the carry row shown. ' +
        "Subtraction is done the way the syllabus wants it — convert the second number " +
        "to two’s complement and <em>add</em>.</p>" +
        '<div class="lg-bases">' +
          '<label class="lg-field"><span>First value (denary)</span>' +
            '<input class="fs-search" data-a type="number" value="45"></label>' +
          '<label class="lg-field"><span>Operation</span>' +
            '<select class="tool-select" data-op><option value="add">Add (+)</option>' +
            '<option value="sub">Subtract (−)</option></select></label>' +
          '<label class="lg-field"><span>Second value (denary)</span>' +
            '<input class="fs-search" data-b type="number" value="23"></label>' +
          '<label class="lg-field"><span>Width</span>' +
            '<select class="tool-select" data-bits><option>8</option><option>16</option></select></label>' +
        '</div><div data-work class="lg-work"></div>';

      var aIn = out.querySelector("[data-a]"), bIn = out.querySelector("[data-b]");
      var opIn = out.querySelector("[data-op]"), wIn = out.querySelector("[data-bits]");
      var work = out.querySelector("[data-work]");

      function go() {
        var a = parseInt(aIn.value, 10), b = parseInt(bIn.value, 10), bits = +wIn.value;
        if (isNaN(a) || isNaN(b)) { work.innerHTML = ""; return; }
        var sub = opIn.value === "sub";
        var ta = twos(a, bits), tb = twos(sub ? -b : b, bits);
        if (ta.err || tb.err) {
          work.innerHTML = '<p class="gp-err">' + esc(ta.err || tb.err) + "</p>"; return;
        }
        var pre = "";
        if (sub) {
          var neg = twos(-b, bits);
          pre = "<h3>Step 1 — make the second number negative</h3>" +
            '<table class="lg-steps">' +
            "<tr><th>" + b + " in binary</th><td><code>" + groupBits(twos(Math.abs(b), bits).bits) + "</code></td></tr>" +
            (neg.steps ? "<tr><th>Invert every bit</th><td><code>" + groupBits(neg.steps.inv) + "</code></td></tr>" +
              '<tr><th>Add one → −' + b + '</th><td><code class="lg-ans">' + groupBits(neg.bits) + "</code></td></tr>" : "") +
            "</table>";
        }
        var r = addBits(ta.bits, tb.bits, bits);
        var val = fromTwos(r.sum);
        var expect = sub ? a - b : a + b;
        // Overflow: the true answer no longer fits, so the sign bit lies.
        var overflow = val !== expect;

        work.innerHTML = pre +
          "<h3>" + (sub ? "Step 2 — add" : "Column addition") + "</h3>" +
          '<div class="lg-tbl-wrap"><table class="lg-add">' +
            row("carry", r.carries, "") +
            row(String(a), ta.bits, "") +
            row((sub ? "+ (−" + b + ")" : "+ " + b), tb.bits, "") +
            row("=", r.sum, "lg-ans-row") +
          "</table></div>" +
          '<p class="lg-sum">' + a + (sub ? " − " : " + ") + b + " = <strong>" + val + "</strong>" +
          (r.carryOut ? ' <span class="fs-vars">(carry out of the final column is discarded)</span>' : "") +
          "</p>" +
          (overflow
            ? '<p class="gp-err">Overflow — the true answer (' + expect + ') does not fit in ' +
              bits + " bits, so the stored result is wrong. This is a standard exam trap.</p>"
            : "");
      }
      function row(label, bitsStr, cls) {
        return '<tr class="' + cls + '"><th>' + esc(label) + "</th>" +
          bitsStr.split("").map(function (b) {
            return "<td>" + (b === " " ? "&nbsp;" : b) + "</td>"; }).join("") + "</tr>";
      }
      [aIn, bIn].forEach(function (el) { el.addEventListener("input", go); });
      [opIn, wIn].forEach(function (el) { el.addEventListener("change", go); });
      go();
    }

    // ── Floating point ────────────────────────────────────────────────────
    function renderFloat() {
      out.innerHTML =
        '<p class="cw-note">A2 Computer Science (9618). The mantissa is a two’s complement ' +
        "<em>fraction</em> with the binary point just after the sign bit; the exponent is a " +
        "two’s complement integer. <strong>Normalised</strong> means the first two mantissa " +
        "bits differ — 0.1… for a positive number, 1.0… for a negative one.</p>" +
        '<div class="fs-filter" data-dir style="margin-bottom:14px">' +
          '<button data-d="to" class="on">Denary → floating point</button>' +
          '<button data-d="from">Floating point → denary</button>' +
        "</div>" +
        '<div class="lg-bases" data-fields></div>' +
        '<div data-work class="lg-work"></div>';

      var dir = "to";
      var fields = out.querySelector("[data-fields]"), work = out.querySelector("[data-work]");
      out.querySelector("[data-dir]").addEventListener("click", function (ev) {
        var b = ev.target.closest("button[data-d]");
        if (!b) return;
        dir = b.dataset.d;
        out.querySelectorAll("[data-dir] button").forEach(function (x) { x.classList.toggle("on", x === b); });
        build();
      });

      function build() {
        fields.innerHTML = dir === "to"
          ? '<label class="lg-field"><span>Denary value</span>' +
              '<input class="fs-search" data-v type="number" step="any" value="9.75"></label>' +
            '<label class="lg-field"><span>Mantissa bits</span>' +
              '<select class="tool-select" data-mb><option>8</option><option>12</option><option selected>16</option></select></label>' +
            '<label class="lg-field"><span>Exponent bits</span>' +
              '<select class="tool-select" data-eb><option selected>8</option><option>6</option><option>4</option></select></label>'
          : '<label class="lg-field"><span>Mantissa (binary)</span>' +
              '<input class="fs-search" data-m value="0100111000000000" spellcheck="false"></label>' +
            '<label class="lg-field"><span>Exponent (binary)</span>' +
              '<input class="fs-search" data-e value="00000100" spellcheck="false"></label>';
        fields.querySelectorAll("input,select").forEach(function (el) {
          el.addEventListener("input", go); el.addEventListener("change", go);
        });
        go();
      }

      function go() {
        if (dir === "to") {
          var v = parseFloat(fields.querySelector("[data-v]").value);
          var mb = +fields.querySelector("[data-mb]").value;
          var eb = +fields.querySelector("[data-eb]").value;
          if (isNaN(v)) { work.innerHTML = ""; return; }
          var r = toFloat(v, mb, eb);
          if (r.err) { work.innerHTML = '<p class="gp-err">' + esc(r.err) + "</p>"; return; }
          if (r.note) { work.innerHTML = '<p class="fs-vars">' + esc(r.note) + "</p>"; return; }
          var check = fromFloat(r.mantissa, r.exponent);
          work.innerHTML =
            '<table class="lg-steps">' +
              "<tr><th>Normalised as</th><td><code>" + trimNum(r.mantVal) +
                " × 2<sup>" + r.expVal + "</sup></code></td></tr>" +
              '<tr><th>Mantissa (' + mb + ' bits)</th><td><code class="lg-ans">' +
                groupBits(r.mantissa) + "</code></td></tr>" +
              '<tr><th>Exponent (' + eb + ' bits)</th><td><code class="lg-ans">' +
                groupBits(r.exponent) + "</code></td></tr>" +
              "<tr><th>Reads back as</th><td><code>" + trimNum(check.value) + "</code></td></tr>" +
            "</table>" +
            '<p class="' + (r.normalised ? "lg-sum" : "gp-err") + '">' +
              (r.normalised
                ? "Normalised ✓ — the first two mantissa bits (" + r.mantissa.slice(0, 2) +
                  ") differ, as they must."
                : "Not normalised — the first two mantissa bits are the same.") + "</p>" +
            (Math.abs(check.value - v) > 1e-9
              ? '<p class="fs-vars">Stored value differs from ' + trimNum(v) +
                " — that is rounding error, and a standard exam discussion point.</p>" : "");
        } else {
          var m = (fields.querySelector("[data-m]").value || "").replace(/\s+/g, "");
          var e = (fields.querySelector("[data-e]").value || "").replace(/\s+/g, "");
          if (!/^[01]+$/.test(m) || !/^[01]+$/.test(e)) {
            work.innerHTML = '<p class="gp-err">Mantissa and exponent must be binary (0s and 1s).</p>';
            return;
          }
          var f = fromFloat(m, e);
          work.innerHTML =
            '<table class="lg-steps">' +
              "<tr><th>Mantissa</th><td><code>" + groupBits(m) + "</code> = " + trimNum(f.mantissa) + "</td></tr>" +
              "<tr><th>Exponent</th><td><code>" + groupBits(e) + "</code> = " + f.exponent + "</td></tr>" +
              "<tr><th>Value</th><td><code class=\"lg-ans\">" + trimNum(f.mantissa) +
                " × 2<sup>" + f.exponent + "</sup> = " + trimNum(f.value) + "</code></td></tr>" +
            "</table>" +
            '<p class="' + (f.normalised ? "lg-sum" : "gp-err") + '">' +
              (f.normalised ? "Normalised ✓" :
               "Not normalised — the first two mantissa bits are the same, so this wastes precision.") +
            "</p>";
        }
      }
      function trimNum(v) { return String(Number(v.toPrecision(10))); }
      build();
    }

    // ── Truth tables ──────────────────────────────────────────────────────
    var LAST_EXPR = "A AND (NOT B OR C)";

    function exprBar(id, chips) {
      return '<div class="lg-bases"><label class="lg-field" style="flex:1 1 100%">' +
        "<span>Boolean expression</span>" +
        '<input class="fs-search" data-expr value="' + esc(LAST_EXPR) + '" spellcheck="false"></label></div>' +
        (chips ? '<div class="lg-chips" data-chips>' +
          ["A AND B", "A OR B", "NOT A", "A NAND B", "A NOR B", "A XOR B",
           "(A AND B) OR (NOT A AND C)"].map(function (e) {
            return '<button data-ex="' + esc(e) + '">' + esc(e) + "</button>"; }).join("") +
          "</div>" : "");
    }

    function renderLogic() {
      out.innerHTML =
        '<p class="cw-note">Write it the way the paper does — <code>A AND (NOT B OR C)</code>. ' +
        "Every intermediate column is shown, because that is where the marks are.</p>" +
        exprBar("logic", true) + '<div data-work class="lg-work"></div>';
      var exprEl = out.querySelector("[data-expr]"), work = out.querySelector("[data-work]");
      out.querySelector("[data-chips]").addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-ex]");
        if (!b) return;
        exprEl.value = b.dataset.ex; go();
      });
      exprEl.addEventListener("input", go);
      function go() {
        LAST_EXPR = exprEl.value;
        var ast;
        try { ast = parseBool(boolTokens(exprEl.value)); }
        catch (e) { work.innerHTML = '<p class="gp-err">' + esc(e.message) + "</p>"; return; }
        var vars = varsOf(ast);
        if (!vars.length) { work.innerHTML = '<p class="gp-err">Use at least one variable, like A.</p>'; return; }
        if (vars.length > 4) { work.innerHTML = '<p class="gp-err">Four variables is the most a paper asks for.</p>'; return; }
        var cols = subExprs(ast).filter(function (c) { return c !== render(ast); });
        var rows = rowsFor(vars).map(function (env) {
          return "<tr>" + vars.map(function (v) { return "<td>" + (env[v] ? 1 : 0) + "</td>"; }).join("") +
            cols.map(function (c) { return '<td class="lg-mid">' + (evalBool(findNode(ast, c), env) ? 1 : 0) + "</td>"; }).join("") +
            '<td class="' + (evalBool(ast, env) ? "pv-on" : "pv-off") + '">' + (evalBool(ast, env) ? 1 : 0) + "</td></tr>";
        }).join("");
        work.innerHTML =
          '<div class="lg-tbl-wrap"><table class="lg-truth"><thead><tr>' +
            vars.map(function (v) { return "<th>" + v + "</th>"; }).join("") +
            cols.map(function (c) { return '<th class="lg-mid">' + esc(c) + "</th>"; }).join("") +
            "<th>" + esc(render(ast)) + "</th></tr></thead><tbody>" + rows + "</tbody></table></div>" +
          '<p class="fs-vars">' + Math.pow(2, vars.length) + " rows for " + vars.length +
          " input" + (vars.length > 1 ? "s" : "") + " — always 2ⁿ, in this order.</p>";
      }
      go();
    }

    // ── Gate simulator ────────────────────────────────────────────────────
    function renderGates() {
      out.innerHTML =
        '<p class="cw-note">The same expression as a circuit. Click an input to toggle it ' +
        "between 0 and 1 and watch the signal travel — lit wires are carrying a 1.</p>" +
        exprBar("gates", true) +
        '<div class="gs-stage" data-stage></div>' +
        '<div class="gs-inputs" data-toggles></div>' +
        '<div data-work class="lg-work"></div>';

      var exprEl = out.querySelector("[data-expr]"), stage = out.querySelector("[data-stage]");
      var toggles = out.querySelector("[data-toggles]"), work = out.querySelector("[data-work]");
      var env = {};

      out.querySelector("[data-chips]").addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-ex]");
        if (!b) return;
        exprEl.value = b.dataset.ex; go(true);
      });
      exprEl.addEventListener("input", function () { go(true); });

      toggles.addEventListener("click", function (ev) {
        var b = ev.target.closest("[data-t]");
        if (!b) return;
        env[b.dataset.t] = !env[b.dataset.t];
        go(false);
      });
      stage.addEventListener("click", function (ev) {
        var g = ev.target.closest("[data-var]");
        if (!g || !g.dataset.var) return;
        env[g.dataset.var] = !env[g.dataset.var];
        go(false);
      });

      function go(reset) {
        LAST_EXPR = exprEl.value;
        var ast;
        try { ast = parseBool(boolTokens(exprEl.value)); }
        catch (e) {
          stage.innerHTML = ""; toggles.innerHTML = "";
          work.innerHTML = '<p class="gp-err">' + esc(e.message) + "</p>"; return;
        }
        var vars = varsOf(ast);
        if (!vars.length || vars.length > 4) {
          work.innerHTML = '<p class="gp-err">Use between one and four variables.</p>'; return;
        }
        if (reset) { env = {}; vars.forEach(function (v) { env[v] = false; }); }
        vars.forEach(function (v) { if (env[v] === undefined) env[v] = false; });

        stage.innerHTML = gateSVG(ast, env, esc);
        toggles.innerHTML = vars.map(function (v) {
          return '<button class="gs-toggle' + (env[v] ? " on" : "") + '" data-t="' + v + '">' +
            v + ' <span>' + (env[v] ? 1 : 0) + "</span></button>";
        }).join("");
        work.innerHTML = '<p class="lg-sum">Output of <code>' + esc(render(ast)) +
          "</code> is <strong>" + (evalBool(ast, env) ? 1 : 0) + "</strong> for these inputs.</p>";
      }
      go(true);
    }

    // ── Practice ──────────────────────────────────────────────────────────
    function renderPractice() {
      out.innerHTML =
        '<div class="fs-filter" data-mode style="margin-bottom:14px">' +
          '<button data-m="fill" class="on">Fill the truth table</button>' +
          '<button data-m="name">Truth table → expression</button>' +
        "</div><div data-q></div>";

      var mode = "fill", host = out.querySelector("[data-q]");
      out.querySelector("[data-mode]").addEventListener("click", function (ev) {
        var b = ev.target.closest("button[data-m]");
        if (!b) return;
        mode = b.dataset.m;
        out.querySelectorAll("[data-mode] button").forEach(function (x) { x.classList.toggle("on", x === b); });
        newQuestion();
      });

      var SHAPES = ["A AND B", "A OR B", "NOT A AND B", "A AND NOT B", "A XOR B",
        "A NAND B", "A NOR B", "(A AND B) OR C", "A AND (B OR C)",
        "NOT (A AND B)", "(A OR B) AND NOT C", "(A AND NOT B) OR (NOT A AND B)"];
      var current = null;

      function newQuestion() {
        var src = SHAPES[Math.floor(Math.random() * SHAPES.length)];
        current = { src: src, ast: parseBool(boolTokens(src)) };
        mode === "fill" ? drawFill() : drawName();
      }

      // ── Mode 1: Fill the truth table ──────────────────────────────────────
      function drawFill() {
        var ast = current.ast, vars = varsOf(ast), rows = rowsFor(vars);
        var cols = subExprs(ast).filter(function (c) { return c !== render(ast); });
        
        host.innerHTML =
          '<p class="cw-note">Work out the intermediate values and the final output for <code>' + esc(current.src) +
          '</code>. Click a cell to flip it between 0 and 1, then check. Filling in intermediate working columns helps you trace the logic step-by-step.</p>' +
          '<div class="lg-tbl-wrap"><table class="lg-truth"><thead><tr>' +
            vars.map(function (v) { return "<th>" + v + "</th>"; }).join("") +
            cols.map(function (c) { return '<th class="lg-mid">' + esc(c) + "</th>"; }).join("") +
            "<th>Output</th></tr></thead><tbody>" +
            rows.map(function (env, i) {
              var cellsHtml = vars.map(function (v) { return "<td>" + (env[v] ? 1 : 0) + "</td>"; }).join("");
              cellsHtml += cols.map(function (c, j) {
                return '<td class="lg-mid"><button class="pr-cell" data-row="' + i + '" data-col="col-' + j + '" data-val="0">0</button></td>';
              }).join("");
              cellsHtml += '<td><button class="pr-cell" data-row="' + i + '" data-col="out" data-val="0">0</button></td>';
              return "<tr>" + cellsHtml + "</tr>";
            }).join("") +
          "</tbody></table></div>" +
          '<div class="pr-actions"><button class="ps-run" data-check>Check</button>' +
          '<button class="calc-lock-btn" data-reveal style="color:var(--grey)">Show answer</button>' +
          '<button class="calc-lock-btn" data-new style="color:var(--grey)">New question</button></div>' +
          '<div data-fb></div>';

        host.querySelectorAll(".pr-cell").forEach(function (b) {
          b.addEventListener("click", function () {
            var v = b.dataset.val === "1" ? "0" : "1";
            b.dataset.val = v; b.textContent = v;
            b.classList.toggle("on", v === "1");
            b.classList.remove("right", "wrong");
          });
        });
        host.querySelector("[data-check]").addEventListener("click", function () {
          var right = 0;
          var cells = host.querySelectorAll(".pr-cell");
          cells.forEach(function (b) {
            var rowIdx = +b.dataset.row;
            var env = rows[rowIdx];
            var want;
            if (b.dataset.col === "out") {
              want = evalBool(ast, env) ? "1" : "0";
            } else {
              var colIdx = +b.dataset.col.split("-")[1];
              var colName = cols[colIdx];
              var node = findNode(ast, colName);
              want = evalBool(node, env) ? "1" : "0";
            }
            var ok = b.dataset.val === want;
            b.classList.toggle("right", ok);
            b.classList.toggle("wrong", !ok);
            if (ok) right++;
          });
          var total = cells.length;
          host.querySelector("[data-fb]").innerHTML =
            '<div class="' + (right === total ? "ps-clean" : "cw-note") + '">' +
            (right === total ? "✓ All " + total + " cells correct!"
              : right + " of " + total + " cells correct — check the red ones.") + "</div>";
        });
        host.querySelector("[data-reveal]").addEventListener("click", function () {
          host.querySelectorAll(".pr-cell").forEach(function (b) {
            var rowIdx = +b.dataset.row;
            var env = rows[rowIdx];
            var want;
            if (b.dataset.col === "out") {
              want = evalBool(ast, env) ? "1" : "0";
            } else {
              var colIdx = +b.dataset.col.split("-")[1];
              var colName = cols[colIdx];
              var node = findNode(ast, colName);
              want = evalBool(node, env) ? "1" : "0";
            }
            b.dataset.val = want; b.textContent = want;
            b.classList.toggle("on", want === "1");
            b.classList.add("right"); b.classList.remove("wrong");
          });
          host.querySelector("[data-fb]").innerHTML =
            '<div class="cw-note">Answer revealed — check how the intermediate values build up the final logic.</div>';
        });
        host.querySelector("[data-new]").addEventListener("click", newQuestion);
      }

      // ── Mode 2: Truth table → expression ─────────────────────────────────
      function drawName() {
        var ast = current.ast, vars = varsOf(ast), rows = rowsFor(vars);
        host.innerHTML =
          '<p class="cw-note">Here is the truth table. Write a Boolean expression that ' +
          "produces this output column — any equivalent form is accepted.</p>" +
          '<div class="lg-tbl-wrap"><table class="lg-truth"><thead><tr>' +
            vars.map(function (v) { return "<th>" + v + "</th>"; }).join("") +
            "<th>Output</th></tr></thead><tbody>" +
            rows.map(function (env) {
              return "<tr>" + vars.map(function (v) { return "<td>" + (env[v] ? 1 : 0) + "</td>"; }).join("") +
                '<td class="' + (evalBool(ast, env) ? "pv-on" : "pv-off") + '">' +
                (evalBool(ast, env) ? 1 : 0) + "</td></tr>";
            }).join("") +
          "</tbody></table></div>" +
          '<div class="lg-bases"><label class="lg-field" style="flex:1 1 100%">' +
            "<span>Your expression</span>" +
            '<input class="fs-search" data-ans placeholder="e.g. A AND NOT B" spellcheck="false"></label></div>' +
          '<div class="pr-actions"><button class="ps-run" data-check>Check</button>' +
          '<button class="calc-lock-btn" data-reveal style="color:var(--grey)">Reveal</button>' +
          '<button class="calc-lock-btn" data-new style="color:var(--grey)">New question</button></div>' +
          '<div data-fb></div>';

        var ansEl = host.querySelector("[data-ans]"), fb = host.querySelector("[data-fb]");
        host.querySelector("[data-check]").addEventListener("click", function () {
          var mine;
          try { mine = parseBool(boolTokens(ansEl.value)); }
          catch (e) { fb.innerHTML = '<p class="gp-err">' + esc(e.message) + "</p>"; return; }
          var myVars = varsOf(mine);
          var extra = myVars.filter(function (v) { return vars.indexOf(v) < 0; });
          if (extra.length) {
            fb.innerHTML = '<p class="gp-err">Your expression uses ' + extra.join(", ") +
              ", which is not in the table.</p>"; return;
          }
          var same = rows.every(function (env) { return evalBool(mine, env) === evalBool(ast, env); });
          fb.innerHTML = same
            ? '<div class="ps-clean">✓ Correct — equivalent to <code>' + esc(current.src) + "</code>.</div>"
            : '<div class="cw-note">Not quite. Compare your output column against the table row by row.</div>';
        });
        host.querySelector("[data-reveal]").addEventListener("click", function () {
          fb.innerHTML = '<div class="cw-note">One correct answer: <code>' + esc(current.src) + "</code></div>";
        });
        host.querySelector("[data-new]").addEventListener("click", newQuestion);
      }

      newQuestion();
    }






    render_();
    return function teardown() { root.innerHTML = ""; };
  }

  if (window.PWT) {
    window.PWT.register({ id: "logic", name: "Bases & logic", icon: "🔢", mount: mount });
  }
  window.PWTLogic = { parseBool: parseBool, boolTokens: boolTokens, evalBool: evalBool,
                      toFloat: toFloat, fromFloat: fromFloat, addBits: addBits,
                      twos: twos, fromTwos: fromTwos, varsOf: varsOf, render: render };
})();



