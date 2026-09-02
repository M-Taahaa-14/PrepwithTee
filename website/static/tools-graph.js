/* PrepWithTee — Graph Plotter v2
 *
 * Desmos-style: accepts y=f(x), plain f(x), x=k vertical lines.
 * Math keyboard, window controls, touch support, multiple curves.
 * Sandboxed via Function() — no PWTCalc dependency.
 */
(function () {
  "use strict";

  // ── Palette & presets ──────────────────────────────────────────────────────
  var COLOURS = ["#6366f1","#22c55e","#ef4444","#f59e0b","#06b6d4","#a855f7","#f43f5e"];

  var PRESETS = [
    { l:"x²−4",    e:"x^2-4" },
    { l:"x³−3x",   e:"x^3-3x" },
    { l:"sin(x)",  e:"sin(x)" },
    { l:"cos(x)",  e:"cos(x)" },
    { l:"1/x",     e:"1/x" },
    { l:"eˣ",      e:"e^x" },
    { l:"ln(x)",   e:"ln(x)" },
    { l:"√x",      e:"sqrt(x)" },
    { l:"2x+1",    e:"2x+1" },
    { l:"|x|",     e:"abs(x)" },
    { l:"tan(x)",  e:"tan(x)" },
    { l:"x²+y²=r", e:"sqrt(25-x^2)" },
  ];

  var KB_ROWS = [
    [["x","x"],["^","^"],["(","("],[")",")"],["⌫","DEL"]],
    [["sin","sin("],["cos","cos("],["tan","tan("],["√","sqrt("],["π","pi"]],
    [["ln","ln("],["log","log10("],["abs","abs("],["e","e"],["÷","÷"]],
    [["+","+"],["−","-"],["×","*"],["=","="],["Enter","ENTER"]],
  ];

  // ── Safe math scope ────────────────────────────────────────────────────────
  // Only these names are accessible inside user expressions; window/document etc are hidden.
  var SK = ["PI","E","sin","cos","tan","asin","acos","atan","atan2",
            "sinh","cosh","tanh","sqrt","cbrt","abs","log","log2","log10",
            "exp","pow","ceil","floor","round","min","max","sign","hypot",
            "ln","pi","euler","inf","Infinity"];
  var SV = [Math.PI,Math.E,Math.sin,Math.cos,Math.tan,Math.asin,Math.acos,
            Math.atan,Math.atan2,Math.sinh,Math.cosh,Math.tanh,Math.sqrt,
            Math.cbrt,Math.abs,Math.log,Math.log2,Math.log10,Math.exp,
            Math.pow,Math.ceil,Math.floor,Math.round,Math.min,Math.max,
            Math.sign,Math.hypot,
            Math.log,  // ln alias
            Math.PI,   // pi alias
            Math.E,    // euler (internal name for e)
            Infinity,Infinity];

  // ── Expression parser ──────────────────────────────────────────────────────
  function preprocess(src) {
    return src.trim()
      .replace(/\s+/g,"")
      .replace(/²/g,"^2").replace(/³/g,"^3")
      .replace(/\bln\b/gi,"log")                     // natural log
      .replace(/\bpi\b/gi,"PI").replace(/π/g,"PI")   // pi constant
      .replace(/\be\b/g,"euler")                     // Euler's number (standalone)
      .replace(/÷/g,"/").replace(/×/g,"*")
      .replace(/\^/g,"**")
      // implicit multiplication: 2x, 2( ,  2sqrt → 2*sqrt
      .replace(/(\d)\s*([a-zA-Z_])/g,"$1*$2")
      .replace(/(\d)\s*\(/g,"$1*(")
      // )( → )*( ,  )x → )*x
      .replace(/\)\s*\(/g,")*(")
      .replace(/\)\s*([a-zA-Z_x])/g,")*$1");
  }

  function compile(raw) {
    var src = raw.trim();

    // Vertical line: x = k
    var vm = /^x\s*=\s*(.+)$/i.exec(src);
    if (vm) {
      var k = evalConst(vm[1]);
      if (isFinite(k)) return { type:"vertical", x:k };
    }

    // Strip "y = " or "f(x) = "
    src = src.replace(/^[yY]\s*=\s*/,"").replace(/^[a-zA-Z]\s*\([xX]\)\s*=\s*/,"");

    var js = preprocess(src);
    var body = "return (" + js + ");";
    var fn;
    try {
      fn = new Function(...SK, "x", body);
      fn(...SV, 1);  // probe — surfaces syntax errors
    } catch(err) {
      throw new Error(String(err.message)
        .replace(/^.*?(SyntaxError|ReferenceError|TypeError)[:\s]*/i,"")
        .replace(/\(anonymous\)/g,"")
        .trim() || "Invalid expression");
    }

    return {
      type: "explicit",
      fn: function(x) {
        try { var r = fn(...SV, x); return typeof r === "number" ? r : NaN; }
        catch(e) { return NaN; }
      }
    };
  }

  function evalConst(expr) {
    var js = preprocess(expr);
    try { return new Function(...SK, "return (" + js + ");")(...SV); }
    catch(e) { return NaN; }
  }

  // ── Rendering helpers ──────────────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
      .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  }

  function niceStep(range, n) {
    var raw = range / n;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var r = raw / mag;
    return (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag;
  }

  function fmt(v) {
    if (!isFinite(v)) return "—";
    if (Math.abs(v) < 1e-9) return "0";
    var s = Number(v.toPrecision(5));
    return String(s);
  }

  // ── mount ──────────────────────────────────────────────────────────────────
  function mount(root, opts) {
    var compact = opts && opts.mode === "dock";

    root.innerHTML =
      '<div class="gp2-wrap' + (compact ? " gp2-compact" : "") + '">' +
        '<div class="gp2-panel">' +
          '<div class="gp2-exprs" data-exprs></div>' +
          '<button class="gp2-add-btn" data-add>+ Add expression</button>' +
          '<div class="gp2-kb-bar">' +
            '<button class="gp2-kb-toggle" data-kb-toggle>⌨ Keyboard</button>' +
            '<button class="gp2-kb-toggle" data-clear-all>✕ Clear all</button>' +
          '</div>' +
          '<div class="gp2-kb" data-kb hidden>' +
            KB_ROWS.map(function(row) {
              return '<div class="gp2-kb-row">' +
                row.map(function(k) {
                  return '<button class="gp2-kb-btn" data-ins="' + esc(k[1]) + '">' + esc(k[0]) + '</button>';
                }).join("") +
              '</div>';
            }).join("") +
          '</div>' +
          '<div class="gp2-presets-wrap">' +
            '<p class="gp2-label">Quick examples</p>' +
            '<div class="gp2-presets">' +
              PRESETS.map(function(p) {
                return '<button class="gp2-preset-btn" data-preset="' + esc(p.e) + '">' + esc(p.l) + '</button>';
              }).join("") +
            '</div>' +
          '</div>' +
          '<div class="gp2-readout" data-readout></div>' +
          '<details class="gp2-window-details">' +
            '<summary>Window / range</summary>' +
            '<div class="gp2-window-grid">' +
              '<label>x min<input type="number" data-win="xmin" value="-10" step="any"></label>' +
              '<label>x max<input type="number" data-win="xmax" value="10" step="any"></label>' +
              '<label>y min<input type="number" data-win="ymin" value="-10" step="any"></label>' +
              '<label>y max<input type="number" data-win="ymax" value="10" step="any"></label>' +
            '</div>' +
          '</details>' +
          '<div class="gp2-options-panel">' +
            '<p class="gp2-label">Graph Options</p>' +
            '<div class="gp2-options-grid">' +
              '<label class="gp2-opt-label">' +
                '<input type="checkbox" data-opt="grid" checked>' +
                'Show gridlines' +
              '</label>' +
              '<label class="gp2-opt-label">' +
                '<input type="checkbox" data-opt="labels" checked>' +
                'Show axis labels' +
              '</label>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="gp2-canvas-wrap">' +
          '<canvas data-canvas></canvas>' +
          '<div class="gp2-controls">' +
            '<button data-zoom="in"  title="Zoom in">+</button>' +
            '<button data-zoom="out" title="Zoom out">−</button>' +
            '<button data-zoom="reset" title="Reset to default view (-10 to 10)">⟲</button>' +
          '</div>' +
          '<div class="gp2-coord" data-coord></div>' +
          '<p class="gp2-hint">Drag · scroll to zoom · hover to trace</p>' +
        '</div>' +
      '</div>';

    var $ = function(s) { return root.querySelector(s); };
    var canvas   = $("[data-canvas]");
    var exprsEl  = $("[data-exprs]");
    var readout  = $("[data-readout]");
    var coordEl  = $("[data-coord]");
    var ctx      = canvas.getContext("2d");

    var view  = { xmin:-10, xmax:10, ymin:-10, ymax:10 };
    var curves = [{ expr:"x^2-4", compiled:null, err:null, visible:true, ci:0 }];
    var options = { grid: true, labels: true };
    var trace  = null;
    var focused = null; // active input element for keyboard

    // coordinate helpers
    var W    = function() { return canvas.clientWidth; };
    var H    = function() { return canvas.clientHeight; };
    var toX  = function(x) { return (x - view.xmin) / (view.xmax - view.xmin) * W(); };
    var toY  = function(y) { return H() - (y - view.ymin) / (view.ymax - view.ymin) * H(); };
    var frX  = function(px) { return view.xmin + px / W() * (view.xmax - view.xmin); };
    var frY  = function(py) { return view.ymin + (H() - py) / H() * (view.ymax - view.ymin); };

    // ── recompile ────────────────────────────────────────────────────────────
    function recompile() {
      curves.forEach(function(c) {
        if (!c.expr.trim()) { c.compiled = null; c.err = null; return; }
        try { c.compiled = compile(c.expr); c.err = null; }
        catch(e) { c.compiled = null; c.err = e.message || "Invalid"; }
      });
    }

    // ── render expression list ───────────────────────────────────────────────
    function drawExprs() {
      exprsEl.innerHTML = curves.map(function(c, i) {
        var col = COLOURS[c.ci % COLOURS.length];
        return '<div class="gp2-expr' + (c.err ? " gp2-bad" : "") + (c.visible ? "" : " gp2-hidden") + '" data-i="' + i + '">' +
          '<button class="gp2-swatch" data-swatch="' + i + '" style="background:' + col + '" title="Change colour"></button>' +
          '<div class="gp2-iw">' +
            '<input class="gp2-inp" data-curve="' + i + '" value="' + esc(c.expr) + '"' +
              ' placeholder="e.g. sin(x),  x^2+1,  x=3,  y=2x-1"' +
              ' spellcheck="false" autocomplete="off" autocorrect="off">' +
            (c.err ? '<span class="gp2-errtxt">' + esc(c.err) + '</span>' : '') +
          '</div>' +
          '<button class="gp2-eye" data-eye="' + i + '" title="' + (c.visible ? "Hide" : "Show") + '">' + (c.visible ? "👁" : "🚫") + '</button>' +
          '<button class="gp2-del" data-del="' + i + '" title="Remove">🗑️</button>' +
        '</div>';
      }).join("");
    }

    // ── draw canvas ──────────────────────────────────────────────────────────
    function draw() {
      var w = W(), h = H();
      if (!w || !h) return;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, w, h);

      var sx = niceStep(view.xmax - view.xmin, 10);
      var sy = niceStep(view.ymax - view.ymin, 8);

      // minor grid
      if (options.grid) {
        ctx.lineWidth = 1;
        ctx.strokeStyle = "#f0ece4";
        ctx.beginPath();
        var gx = Math.ceil(view.xmin / sx) * sx;
        for (; gx <= view.xmax + sx * 0.001; gx += sx) {
          var px = Math.round(toX(gx)) + 0.5;
          ctx.moveTo(px, 0); ctx.lineTo(px, h);
        }
        var gy = Math.ceil(view.ymin / sy) * sy;
        for (; gy <= view.ymax + sy * 0.001; gy += sy) {
          var py = Math.round(toY(gy)) + 0.5;
          ctx.moveTo(0, py); ctx.lineTo(w, py);
        }
        ctx.stroke();
      }

      // axes
      ctx.strokeStyle = "#c0b8d0";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      if (view.ymin <= 0 && view.ymax >= 0) {
        var ay = Math.round(toY(0)) + 0.5;
        ctx.moveTo(0, ay); ctx.lineTo(w, ay);
      }
      if (view.xmin <= 0 && view.xmax >= 0) {
        var ax = Math.round(toX(0)) + 0.5;
        ctx.moveTo(ax, 0); ctx.lineTo(ax, h);
      }
      ctx.stroke();

      // axis labels
      if (options.labels) {
        ctx.fillStyle = "#7a7490";
        ctx.font = "11px system-ui,sans-serif";
        ctx.direction = "ltr";
        var y0lbl = Math.min(Math.max(toY(0), 5), h - 20);
        ctx.textAlign = "center"; ctx.textBaseline = "top";
        gx = Math.ceil(view.xmin / sx) * sx;
        for (; gx <= view.xmax; gx += sx) {
          if (Math.abs(gx) < sx / 1000) continue;
          var lx = toX(gx);
          if (lx < 10 || lx > w - 15) continue;
          ctx.fillText(fmt(gx), Math.round(lx), y0lbl + 3);
        }
        var x0lbl = Math.min(Math.max(toX(0), 26), w - 10);
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        gy = Math.ceil(view.ymin / sy) * sy;
        for (; gy <= view.ymax; gy += sy) {
          if (Math.abs(gy) < sy / 1000) continue;
          var ly = toY(gy);
          if (ly < 10 || ly > h - 12) continue;
          ctx.fillText(fmt(gy), x0lbl - 4, Math.round(ly));
        }
      }

      // curves
      var yRange = view.ymax - view.ymin;
      curves.forEach(function(c, i) {
        if (!c.compiled || !c.visible) return;
        var col = COLOURS[c.ci % COLOURS.length];
        ctx.strokeStyle = col;
        ctx.lineWidth = 2.5;
        ctx.lineJoin = "round";

        if (c.compiled.type === "vertical") {
          var vx = toX(c.compiled.x);
          if (vx >= -2 && vx <= w + 2) {
            ctx.setLineDash([8, 5]);
            ctx.beginPath();
            ctx.moveTo(Math.round(vx) + 0.5, 0);
            ctx.lineTo(Math.round(vx) + 0.5, h);
            ctx.stroke();
            ctx.setLineDash([]);
          }
          return;
        }

        ctx.beginPath();
        var pen = false, prevY = null;
        for (var pxi = 0; pxi <= w; pxi++) {
          var xv = frX(pxi);
          var yv = c.compiled.fn(xv);
          if (!isFinite(yv)) { pen = false; prevY = null; continue; }
          var pyv = toY(yv);
          if (pen && prevY !== null && Math.abs(yv - prevY) > yRange * 2) pen = false;
          if (pen) ctx.lineTo(pxi, pyv); else ctx.moveTo(pxi, pyv);
          pen = true; prevY = yv;
        }
        ctx.stroke();
      });

      // trace
      if (trace) {
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = "rgba(100,80,180,.18)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(toX(trace.x), 0); ctx.lineTo(toX(trace.x), h);
        ctx.stroke();
        ctx.setLineDash([]);

        curves.forEach(function(c) {
          if (!c.compiled || !c.visible || c.compiled.type !== "explicit") return;
          var yv = c.compiled.fn(trace.x);
          if (!isFinite(yv)) return;
          var py = toY(yv);
          if (py < -12 || py > h + 12) return;
          var col = COLOURS[c.ci % COLOURS.length];
          ctx.fillStyle = "#fff";
          ctx.beginPath(); ctx.arc(toX(trace.x), py, 6, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = col;
          ctx.strokeStyle = col; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(toX(trace.x), py, 4, 0, Math.PI * 2);
          ctx.fill(); ctx.stroke();
        });
      }
    }

    // ── resize ───────────────────────────────────────────────────────────────
    function resize() {
      var dpr = window.devicePixelRatio || 1;
      var wrap = canvas.parentElement;
      var cw = wrap.getBoundingClientRect().width;
      var ch = compact ? 260 : Math.max(350, Math.min(600, cw * 0.72));
      canvas.width  = Math.round(cw * dpr);
      canvas.height = Math.round(ch * dpr);
      canvas.style.width  = cw + "px";
      canvas.style.height = ch + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }

    // ── analysis readout ─────────────────────────────────────────────────────
    function showReadout() {
      if (trace) {
        var rows = curves.filter(function(c) {
          return c.compiled && c.visible && c.compiled.type === "explicit";
        }).map(function(c) {
          var yv = c.compiled.fn(trace.x);
          return '<div class="gp2-trace-row"><span class="gp2-dot" style="background:' +
            COLOURS[c.ci % COLOURS.length] + '"></span>y = ' +
            (isFinite(yv) ? fmt(yv) : '<em>undefined</em>') + '</div>';
        }).join("");
        readout.innerHTML = '<div class="gp2-trace-box"><strong>x = ' + fmt(trace.x) + '</strong>' + rows + '</div>';
        return;
      }
      var parts = [];
      curves.forEach(function(c) {
        if (!c.compiled || !c.visible || c.compiled.type !== "explicit") return;
        var fn = c.compiled.fn;
        var roots = [], turns = [];
        var N = 1000, span = view.xmax - view.xmin, EPS = span / N / 100;
        var prev = fn(view.xmin), ps = null;

        function addRoot(x) {
          if (roots.length >= 8 || roots.some(function(r) { return Math.abs(r - x) < span / 200; })) return;
          roots.push(x);
        }

        if (isFinite(prev) && Math.abs(prev) < EPS) addRoot(view.xmin);
        for (var k = 1; k <= N; k++) {
          var xv = view.xmin + span * k / N;
          var yv = fn(xv), xp = view.xmin + span * (k - 1) / N;
          if (isFinite(yv) && isFinite(prev)) {
            if (Math.abs(yv) < EPS) addRoot(xv);
            else if (prev * yv < 0) {
              var a = xp, b = xv;
              for (var it = 0; it < 50; it++) {
                var m = (a + b) / 2;
                (fn(a) < 0 === fn(m) < 0) ? (a = m) : (b = m);
              }
              addRoot((a + b) / 2);
            }
            var slope = yv - prev;
            if (ps !== null && ((ps < 0 && slope > 0) || (ps > 0 && slope < 0)) && turns.length < 5)
              turns.push({ x: xp, y: prev });
            ps = slope;
          }
          prev = yv;
        }
        roots.sort(function(a, b) { return a - b; });
        if (!roots.length && !turns.length) return;
        parts.push(
          '<div class="gp2-facts-card">' +
            '<span class="gp2-dot" style="background:' + COLOURS[c.ci % COLOURS.length] + '; margin-top: 4px;"></span>' +
            '<div>' +
              '<div style="font-weight: 700; color: var(--purple); font-size: 0.85rem; margin-bottom: 4px;">' + esc(c.expr) + '</div>' +
              (roots.length ? '<div style="margin-bottom: 2px;"><b>Roots:</b> ' + roots.map(fmt).join(', ') + '</div>' : '') +
              (turns.length ? '<div><b>Turning points:</b> ' + turns.map(function(t) {
                return '(' + fmt(t.x) + ', ' + fmt(t.y) + ')';
              }).join(', ') + '</div>' : '') +
            '</div>' +
          '</div>');
      });
      readout.innerHTML = parts.length
        ? '<p class="gp2-fact-head">Roots &amp; turning points in view</p>' + parts.join("")
        : '<p class="gp2-hint-text">Hover to trace a point — roots &amp; turning points appear here.</p>';
    }

    // ── zoom/pan helpers ─────────────────────────────────────────────────────
    function scaleView(f, cx, cy) {
      cx = cx !== undefined ? cx : (view.xmin + view.xmax) / 2;
      cy = cy !== undefined ? cy : (view.ymin + view.ymax) / 2;
      view = {
        xmin: cx + (view.xmin - cx) * f, xmax: cx + (view.xmax - cx) * f,
        ymin: cy + (view.ymin - cy) * f, ymax: cy + (view.ymax - cy) * f,
      };
    }
    function syncWindowInputs() {
      root.querySelectorAll("[data-win]").forEach(function(inp) {
        inp.value = Number(view[inp.dataset.win].toPrecision(6));
      });
    }

    // ── event wiring ─────────────────────────────────────────────────────────

    // Expression inputs
    exprsEl.addEventListener("focusin", function(ev) {
      var inp = ev.target.closest(".gp2-inp");
      if (inp) focused = inp;
    });

    exprsEl.addEventListener("keydown", function(ev) {
      var inp = ev.target.closest(".gp2-inp");
      if (inp && ev.key === "Enter") {
        ev.preventDefault();
        $("[data-add]").click();
      }
    });

    exprsEl.addEventListener("input", function(ev) {
      var inp = ev.target.closest("[data-curve]");
      if (!inp) return;
      var i = +inp.dataset.curve;
      curves[i].expr = inp.value;
      recompile();
      var c = curves[i];
      var wrap = inp.closest(".gp2-expr");
      wrap.classList.toggle("gp2-bad", !!c.err);
      var errEl = inp.closest(".gp2-iw").querySelector(".gp2-errtxt");
      if (c.err && !errEl) drawExprs();
      else if (!c.err && errEl) errEl.remove();
      draw(); showReadout();
    });

    exprsEl.addEventListener("click", function(ev) {
      var del = ev.target.closest("[data-del]");
      if (del) {
        var idx = +del.dataset.del;
        if (curves.length > 1) {
          curves.splice(idx, 1);
        } else {
          curves[0] = { expr:"", compiled:null, err:null, visible:true, ci:0 };
        }
        recompile(); drawExprs(); draw(); showReadout();
        return;
      }
      var eye = ev.target.closest("[data-eye]");
      if (eye) {
        var ei = +eye.dataset.eye;
        curves[ei].visible = !curves[ei].visible;
        drawExprs(); draw(); showReadout();
        return;
      }
      var sw = ev.target.closest("[data-swatch]");
      if (sw) {
        var si = +sw.dataset.swatch;
        curves[si].ci = (curves[si].ci + 1) % COLOURS.length;
        drawExprs(); draw();
      }
    });

    // Add expression
    $("[data-add]").addEventListener("click", function() {
      if (curves.length >= 7) return;
      curves.push({ expr:"", compiled:null, err:null, visible:true, ci: curves.length % COLOURS.length });
      drawExprs();
      var last = exprsEl.querySelector("[data-curve=\"" + (curves.length - 1) + "\"]");
      if (last) last.focus();
    });

    // Clear all
    $("[data-clear-all]").addEventListener("click", function() {
      curves = [{ expr:"", compiled:null, err:null, visible:true, ci:0 }];
      drawExprs(); draw(); showReadout();
    });

    // Math keyboard toggle
    $("[data-kb-toggle]").addEventListener("click", function() {
      var kb = $("[data-kb]");
      kb.hidden = !kb.hidden;
    });

    // Math keyboard input
    $("[data-kb]").addEventListener("click", function(ev) {
      var btn = ev.target.closest("[data-ins]");
      if (!btn) return;
      var ins = btn.dataset.ins;

      // Focus the last expression input if nothing focused
      if (!focused || !exprsEl.contains(focused)) {
        focused = exprsEl.querySelector(".gp2-inp:last-of-type") ||
                  exprsEl.querySelector(".gp2-inp");
        if (!focused) return;
      }
      focused.focus();

      var s = focused.selectionStart, e = focused.selectionEnd, v = focused.value;
      if (ins === "DEL") {
        if (s === e && s > 0) {
          focused.value = v.slice(0, s - 1) + v.slice(e);
          focused.setSelectionRange(s - 1, s - 1);
        } else {
          focused.value = v.slice(0, s) + v.slice(e);
          focused.setSelectionRange(s, s);
        }
      } else if (ins === "ENTER") {
        $("[data-add]").click();
        return;
      } else {
        focused.value = v.slice(0, s) + ins + v.slice(e);
        var np = s + ins.length;
        // If inserted text ends with '(', put cursor inside
        focused.setSelectionRange(np, np);
      }
      focused.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Presets
    root.querySelector(".gp2-presets").addEventListener("click", function(ev) {
      var btn = ev.target.closest("[data-preset]");
      if (!btn) return;
      var expr = btn.dataset.preset;
      var slot = curves.findIndex(function(c) { return !c.expr.trim(); });
      if (slot < 0) {
        if (curves.length >= 7) slot = curves.length - 1;
        else { curves.push({ expr:"", compiled:null, err:null, visible:true, ci: curves.length % COLOURS.length }); slot = curves.length - 1; }
      }
      curves[slot].expr = expr;
      recompile(); drawExprs(); draw(); showReadout();
    });

    // Window range inputs
    root.querySelectorAll("[data-win]").forEach(function(inp) {
      inp.addEventListener("change", function() {
        var v = parseFloat(inp.value);
        if (!isFinite(v)) return;
        view[inp.dataset.win] = v;
        draw(); showReadout();
      });
    });

    // Option checkboxes
    root.querySelectorAll("[data-opt]").forEach(function(cb) {
      cb.addEventListener("change", function() {
        options[cb.dataset.opt] = cb.checked;
        draw();
      });
    });

    // Zoom buttons
    $(".gp2-controls").addEventListener("click", function(ev) {
      var btn = ev.target.closest("[data-zoom]");
      if (!btn) return;
      if (btn.dataset.zoom === "reset") {
        view = { xmin:-10, xmax:10, ymin:-10, ymax:10 };
        syncWindowInputs();
      } else scaleView(btn.dataset.zoom === "in" ? 0.7 : 1 / 0.7);
      draw(); showReadout();
    });

    // Scroll to zoom
    canvas.addEventListener("wheel", function(ev) {
      ev.preventDefault();
      var r = canvas.getBoundingClientRect();
      scaleView(ev.deltaY > 0 ? 1.12 : 1 / 1.12,
        frX(ev.clientX - r.left), frY(ev.clientY - r.top));
      draw(); showReadout();
    }, { passive: false });

    // Mouse pan + trace
    var drag = null;
    canvas.addEventListener("mousedown", function(ev) {
      drag = { cx: ev.clientX, cy: ev.clientY, v: Object.assign({}, view) };
      canvas.style.cursor = "grabbing";
    });
    canvas.addEventListener("mousemove", function(ev) {
      var r = canvas.getBoundingClientRect();
      if (drag) {
        var dx = (ev.clientX - drag.cx) / W() * (drag.v.xmax - drag.v.xmin);
        var dy = (ev.clientY - drag.cy) / H() * (drag.v.ymax - drag.v.ymin);
        view = { xmin: drag.v.xmin - dx, xmax: drag.v.xmax - dx,
                 ymin: drag.v.ymin + dy, ymax: drag.v.ymax + dy };
        syncWindowInputs(); draw(); return;
      }
      var mx = ev.clientX - r.left, my = ev.clientY - r.top;
      trace = { x: frX(mx) };
      coordEl.textContent = "x = " + fmt(frX(mx)) + "  y = " + fmt(frY(my));
      draw(); showReadout();
    });
    window.addEventListener("mouseup", function() {
      drag = null; canvas.style.cursor = ""; showReadout();
    });
    canvas.addEventListener("mouseleave", function() {
      trace = null; coordEl.textContent = ""; draw(); showReadout();
    });

    // Touch: single-finger pan, two-finger pinch
    var pinch = null;
    canvas.addEventListener("touchstart", function(ev) {
      ev.preventDefault();
      if (ev.touches.length === 1) {
        drag = { cx: ev.touches[0].clientX, cy: ev.touches[0].clientY, v: Object.assign({}, view) };
        pinch = null;
      } else if (ev.touches.length === 2) {
        drag = null;
        var d = Math.hypot(ev.touches[0].clientX - ev.touches[1].clientX,
                           ev.touches[0].clientY - ev.touches[1].clientY);
        pinch = { dist: d, v: Object.assign({}, view) };
      }
    }, { passive: false });
    canvas.addEventListener("touchmove", function(ev) {
      ev.preventDefault();
      var r = canvas.getBoundingClientRect();
      if (ev.touches.length === 1 && drag) {
        var dx = (ev.touches[0].clientX - drag.cx) / W() * (drag.v.xmax - drag.v.xmin);
        var dy = (ev.touches[0].clientY - drag.cy) / H() * (drag.v.ymax - drag.v.ymin);
        view = { xmin: drag.v.xmin - dx, xmax: drag.v.xmax - dx,
                 ymin: drag.v.ymin + dy, ymax: drag.v.ymax + dy };
        draw();
      } else if (ev.touches.length === 2 && pinch) {
        var nd = Math.hypot(ev.touches[0].clientX - ev.touches[1].clientX,
                            ev.touches[0].clientY - ev.touches[1].clientY);
        var f = pinch.dist / nd;
        var mcx = (ev.touches[0].clientX + ev.touches[1].clientX) / 2 - r.left;
        var mcy = (ev.touches[0].clientY + ev.touches[1].clientY) / 2 - r.top;
        var pcx = frX(mcx), pcy = frY(mcy);
        var pv = pinch.v;
        view = {
          xmin: pcx + (pv.xmin - pcx) * f, xmax: pcx + (pv.xmax - pcx) * f,
          ymin: pcy + (pv.ymin - pcy) * f, ymax: pcy + (pv.ymax - pcy) * f,
        };
        draw();
      }
    }, { passive: false });
    canvas.addEventListener("touchend", function() {
      drag = null; pinch = null; showReadout();
    });

    // ResizeObserver
    var ro = window.ResizeObserver
      ? new ResizeObserver(resize)
      : null;
    if (ro) ro.observe(canvas.parentElement);
    else window.addEventListener("resize", resize);

    // Boot
    recompile(); drawExprs(); resize(); showReadout();

    return function teardown() {
      if (ro) ro.disconnect(); else window.removeEventListener("resize", resize);
      root.innerHTML = "";
    };
  }

  if (window.PWT) {
    window.PWT.register({ id:"graph", name:"Graph plotter", icon:"📈", mount:mount });
  }
})();
