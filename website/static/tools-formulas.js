/* PrepWithTee — formula sheets (mountable widget).
 *
 * The badge is the point, not the list. Cambridge prints a List of formulas
 * for Maths and nothing at all for O Level / IGCSE Physics, whose syllabus
 * says "recall and use" for every equation. A generic formula sheet cannot
 * tell a student which half they must memorise. This one can, and each
 * chapter links straight into the past-paper builder.
 *
 * Derivations open in a modal overlay with proper LaTeX rendering via KaTeX
 * (loaded lazily on first open so the tool stays fast for everyone else).
 */
(function () {
  "use strict";

  // ── KaTeX lazy-loader ────────────────────────────────────────────────────
  var katexLoaded = false, katexPending = [];
  function withKaTeX(cb) {
    if (window.katex) { cb(); return; }
    katexPending.push(cb);
    if (katexLoaded) return; // already loading
    katexLoaded = true;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css";
    document.head.appendChild(link);
    var s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js";
    s.onload = function () {
      katexPending.forEach(function (f) { try { f(); } catch(e) {} });
      katexPending = [];
    };
    document.head.appendChild(s);
  }

  // Render a string that may contain $...$ inline math and $$...$$ display math.
  function renderMathStr(text, esc) {
    if (!text) return "";
    if (!window.katex) return esc(text);
    return text
      .replace(/\$\$([^$]+)\$\$/g, function(_, math) {
        try { return window.katex.renderToString(math, { displayMode: true,  throwOnError: false }); }
        catch(e) { return esc(math); }
      })
      .replace(/\$([^$]+)\$/g, function(_, math) {
        try { return window.katex.renderToString(math, { displayMode: false, throwOnError: false }); }
        catch(e) { return esc(math); }
      });
  }

  // ── Shared derivation modal ───────────────────────────────────────────────
  var modal = null;
  function ensureModal() {
    if (modal) return modal;
    var overlay = document.createElement("div");
    overlay.className = "fs-modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "fs-modal-title");
    overlay.innerHTML =
      '<div class="fs-modal-backdrop" data-modal-close></div>' +
      '<div class="fs-modal">' +
        '<button class="fs-modal-close" data-modal-close aria-label="Close">&#10005;</button>' +
        '<div id="fs-modal-body"></div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() {
      overlay.hidden = true;
      document.body.classList.remove("fs-modal-open");
      if (overlay._returnFocus) { overlay._returnFocus.focus(); overlay._returnFocus = null; }
    }
    overlay.addEventListener("click", function(ev) {
      if (ev.target.hasAttribute("data-modal-close")) close();
    });
    document.addEventListener("keydown", function(ev) {
      if (ev.key === "Escape" && !overlay.hidden) close();
    });
    overlay.hidden = true;
    modal = overlay;
    return modal;
  }

  function openDerivModal(f, esc) {
    var m = ensureModal();
    m._returnFocus = document.activeElement;

    withKaTeX(function () {
      var body = document.getElementById("fs-modal-body");
      var html = '<p class="fs-modal-eyebrow">Derivation</p>' +
        '<h2 id="fs-modal-title" class="fs-modal-formula-name">' + esc(f.name) + '</h2>';

      // Big formula display
      html += '<div class="fs-modal-expr">' + renderMathStr(f.expr_latex || "", esc) +
        (f.expr_latex ? "" : '<span class="fs-modal-expr-plain">' + esc(f.expr) + '</span>') +
        '</div>';

      // Derivation steps
      if (f.derivation_latex && f.derivation_latex.length) {
        html += '<div class="fs-deriv-steps-modal">';
        f.derivation_latex.forEach(function(step, i) {
          html += '<div class="fs-deriv-step">' +
            '<div class="fs-step-header"><span class="fs-step-num">Step ' + (i + 1) + '</span></div>';
          if (step.desc) {
            html += '<p class="fs-deriv-desc">' + esc(step.desc) + '</p>';
          }
          if (step.math) {
            html += '<div class="fs-deriv-math">' +
              renderMathStr('$$' + step.math + '$$', esc) + '</div>';
          }
          if (step.note) {
            html += '<p class="fs-deriv-note">' + esc(step.note) + '</p>';
          }
          html += '</div>';
        });
        html += '</div>';
      } else if (f.derivation && f.derivation.length) {
        // Plain-text fallback — still use cards with step numbers
        html += '<div class="fs-deriv-steps-modal fs-deriv-plain">';
        f.derivation.forEach(function(text, i) {
          html += '<div class="fs-deriv-step">' +
            '<div class="fs-step-header"><span class="fs-step-num">Step ' + (i + 1) + '</span></div>' +
            '<p class="fs-deriv-desc">' + esc(text) + '</p>' +
            '</div>';
        });
        html += '</div>';
      }

      // Relations
      if (f.relations) {
        html += '<div class="fs-modal-section fs-relations">' +
          '<h3 class="fs-modal-section-head">🔗 Relationships to notice</h3>' +
          '<div class="fs-relations-body">' + renderMathStr(f.relations, esc) + '</div>' +
          '</div>';
      }

      // Memory cue + watch out
      if (f.memory_cue || f.watch_out) {
        html += '<div class="fs-modal-tips-row">';
        if (f.memory_cue) {
          html += '<div class="fs-modal-tip fs-tip-cue"><strong>Memory cue</strong>' +
            '<p>' + renderMathStr(esc(f.memory_cue), esc) + '</p></div>';
        }
        if (f.watch_out) {
          html += '<div class="fs-modal-tip fs-tip-warn"><strong>Watch out</strong>' +
            '<p>' + renderMathStr(esc(f.watch_out), esc) + '</p></div>';
        }
        html += '</div>';
      }

      // AI Explain button — appended after derivation content
      html += '<div class="fs-ai-explain-wrap" id="fs-ai-explain-wrap">' +
        '<button class="fs-ai-btn" id="fs-ai-btn">🤖 Explain this formula</button>' +
        '<div class="fs-ai-panel" id="fs-ai-panel" hidden></div>' +
        '</div>';

      body.innerHTML = html;
      m.hidden = false;
      document.body.classList.add("fs-modal-open");
      m.querySelector(".fs-modal-close").focus();

      // Wire up the AI explain button
      var aiBtn = document.getElementById("fs-ai-btn");
      var aiPanel = document.getElementById("fs-ai-panel");
      if (aiBtn && aiPanel) {
        aiBtn.addEventListener("click", function() {
          if (aiPanel.dataset.loaded) {
            aiPanel.hidden = !aiPanel.hidden;
            aiBtn.textContent = aiPanel.hidden ? "🤖 Explain this formula" : "🤖 Hide explanation";
            return;
          }
          aiBtn.disabled = true;
          aiBtn.textContent = "⏳ Getting AI explanation…";
          aiPanel.hidden = false;
          aiPanel.innerHTML = '<p class="fs-ai-loading">Thinking…</p>';
          var payload = { name: f.name };
          if (f.expr) payload.expr = f.expr;
          if (f.vars) payload.vars = f.vars;
          fetch("/api/explain-formula", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          }).then(function(r) {
            if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || "AI unavailable"); });
            return r.json();
          }).then(function(d) {
            aiPanel.innerHTML = '<div class="fs-ai-content">' + (d.html || "") + '</div>';
            aiPanel.dataset.loaded = "1";
            aiBtn.disabled = false;
            aiBtn.textContent = "🤖 Hide explanation";
          }).catch(function(err) {
            aiPanel.innerHTML = '<p class="fs-ai-error">' + esc(err.message) + '</p>';
            aiBtn.disabled = false;
            aiBtn.textContent = "🤖 Retry explanation";
          });
        });
      }
    });

    // Show a loading state instantly while KaTeX loads
    if (!window.katex) {
      var body2 = document.getElementById("fs-modal-body");
      if (body2) body2.innerHTML = '<p class="fs-modal-eyebrow">Derivation</p>' +
        '<h2 id="fs-modal-title" class="fs-modal-formula-name">' + esc(f.name) + '</h2>' +
        '<p class="fs-deriv-loading">Loading LaTeX renderer…</p>';
      m.hidden = false;
      document.body.classList.add("fs-modal-open");
    }
  }

  // ── Z-table renderer ─────────────────────────────────────────────────────
  function renderZTable(tbl) {
    if (!tbl || !tbl.rows) return "";
    var html = '<div class="fs-ztable-wrap">';
    html += '<p class="fs-ztable-desc">' + (tbl.desc || "") + '</p>';

    // Usage guide accordion
    if (tbl.usage && tbl.usage.length) {
      html += '<details class="fs-ztable-usage">' +
        '<summary class="fs-ztable-usage-toggle">📖 How to read this table</summary>' +
        '<ol class="fs-ztable-usage-list">';
      tbl.usage.forEach(function(step) {
        // Strip the leading "N. " number since it's in an <ol>
        var text = step.replace(/^\d+\.\s*/, "");
        html += '<li>' + text + '</li>';
      });
      html += '</ol></details>';
    }

    html += '<div class="fs-ztable-scroll"><table class="fs-ztable">' +
      '<thead><tr><th>z</th>';
    for (var d = 0; d <= 9; d++) html += '<th>.0' + d + '</th>';
    html += '</tr></thead><tbody>';
    tbl.rows.forEach(function(row) {
      html += '<tr><td class="fs-ztable-z">' + row.z + '</td>';
      row.vals.forEach(function(v) {
        html += '<td>' + v.toFixed(4) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div></div>';
    return html;
  }

  // ── Graph tip card renderer ───────────────────────────────────────────────
  function renderGraphCard(f, esc) {
    var html = '<article class="fs-item fs-graph-card">' +
      '<div class="fs-graph-head">' +
        '<span class="fs-graph-icon">📊</span>' +
        '<span class="fs-name">' + esc(f.name) + '</span>' +
      '</div>';
    if (f.graph_gradient || f.graph_area) {
      html += '<div class="fs-graph-facts">';
      if (f.graph_gradient) {
        html += '<div class="fs-graph-fact">' +
          '<span class="fs-graph-fact-label">Gradient =</span>' +
          '<span class="fs-graph-fact-val">' + esc(f.graph_gradient) + '</span>' +
          '</div>';
      }
      if (f.graph_area && f.graph_area !== "—") {
        html += '<div class="fs-graph-fact">' +
          '<span class="fs-graph-fact-label">Area under =</span>' +
          '<span class="fs-graph-fact-val">' + esc(f.graph_area) + '</span>' +
          '</div>';
      } else if (f.graph_area === "—") {
        html += '<div class="fs-graph-fact fs-graph-fact-na">' +
          '<span class="fs-graph-fact-label">Area under =</span>' +
          '<span class="fs-graph-fact-val">not meaningful</span>' +
          '</div>';
      }
      html += '</div>';
    }
    if (f.vars) {
      html += '<div class="fs-vars">' + esc(f.vars) + '</div>';
    }
    if (f.watch_out) {
      html += '<div class="fs-tip fs-tip-warn"><strong>Watch out:</strong> ' + esc(f.watch_out) + '</div>';
    }
    if (f.relations) {
      html += '<div class="fs-tip fs-tip-relation"><strong>Relationships:</strong> ' + esc(f.relations) + '</div>';
    }
    html += '</article>';
    return html;
  }

  // ── Main mount function ───────────────────────────────────────────────────
  function mount(root, opts) {
    var PWTx = window.PWT, esc = PWTx.esc;
    var compact = opts && opts.mode === "dock";
    var ctx = (opts && opts.ctx) || {};
    var DATA = null;
    var state = { syllabus: null, filter: "all", query: "", component: "all", recall: false };
    var missionEl = null;

    root.innerHTML =
      '<div data-ar-mission></div>' +
      '<div class="fs-controls-wrap">' +
        '<div class="fs-board-tabs" data-boards></div>' +
        '<div class="fs-subject-tabs" data-subjects></div>' +
        '<div class="fs-controls">' +
          '<input class="fs-search" data-search type="search" ' +
            'placeholder="Search — "density", "sine rule", "moles"…" aria-label="Search formulas">' +
          '<div class="fs-filter" data-filter role="group" aria-label="Filter formulas">' +
            '<button data-f="all" class="on">All</button>' +
            '<button data-f="memo">Must memorise</button>' +
            '<button data-f="given">Given</button>' +
          '</div>' +
          '<label class="fs-recall-toggle">' +
            '<input type="checkbox" data-recall>' +
            '<span>Recall Mode</span>' +
          '</label>' +
          (compact ? "" : '<button class="calc-lock-btn" data-print style="color:var(--grey)">Print</button>') +
        '</div>' +
      '</div>' +
      '<div class="fs-comps" data-comps hidden></div>' +
      '<p class="fs-vars" data-count style="margin-bottom:12px"></p>' +
      '<div class="fs-note" data-note></div>' +
      '<div data-out><p class="fs-vars">Loading…</p></div>';

    var $ = function (s) { return root.querySelector(s); };
    var searchEl = $("[data-search]"), filterEl = $("[data-filter]"), recallEl = $("[data-recall]");
    var outEl = $("[data-out]"), noteEl = $("[data-note]"), countEl = $("[data-count]");
    var boardsEl = $("[data-boards]"), subjectsEl = $("[data-subjects]");
    var compsEl = $("[data-comps]");
    missionEl = $("[data-ar-mission]");

    PWTx.data("formulas").then(function (d) {
      DATA = d;
      var codes = Object.keys(d.syllabuses);
      var pick = (codes.indexOf(ctx.syllabus) >= 0 && ctx.syllabus) || codes[0];
      state.syllabus = pick;
      render();
    }).catch(function (err) {
      outEl.innerHTML = '<div class="fs-empty">Could not load the formula data (' +
        esc(err.message) + "). Try refreshing.</div>";
    });

    function getSyllabusLevel(code) {
      var syl = DATA && DATA.syllabuses[code];
      return syl ? syl.level : null;
    }

    function buildTabs() {
      if (!DATA) return;
      var byLevel = {};
      Object.keys(DATA.syllabuses).forEach(function (code) {
        var s = DATA.syllabuses[code];
        (byLevel[s.level] = byLevel[s.level] || []).push({ code: code, s: s });
      });
      var ORDER = ["Cambridge O Level", "Cambridge IGCSE", "Cambridge A Level"];
      var levels = ORDER.filter(function (l) { return byLevel[l]; })
        .concat(Object.keys(byLevel).filter(function (l) { return ORDER.indexOf(l) < 0; }));

      var activeLevel = getSyllabusLevel(state.syllabus) || levels[0];

      boardsEl.innerHTML = levels.map(function (level) {
        var short = level.replace("Cambridge ", "");
        var isOn = level === activeLevel;
        return '<button class="fs-tab-btn' + (isOn ? ' on' : '') + '" data-level="' + esc(level) + '">' +
          esc(short) + '</button>';
      }).join("");

      var activeSubjects = byLevel[activeLevel] || [];
      subjectsEl.innerHTML = activeSubjects.map(function (item) {
        var isOn = item.code === state.syllabus;
        return '<button class="fs-subtab-btn' + (isOn ? ' on' : '') + '" data-code="' + esc(item.code) + '">' +
          esc(item.s.subject) + ' <span class="fs-code-badge">' + esc(item.code) + '</span></button>';
      }).join("");
    }

    boardsEl.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-level]");
      if (!b) return;
      var level = b.dataset.level;
      var code = null;
      Object.keys(DATA.syllabuses).forEach(function (c) {
        if (!code && DATA.syllabuses[c].level === level) code = c;
      });
      if (code) {
        state.syllabus = code;
        state.component = "all";
        if (ctx.set) ctx.set(code);
        render();
      }
    });

    subjectsEl.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-code]");
      if (!b) return;
      var code = b.dataset.code;
      state.syllabus = code;
      state.component = "all";
      if (ctx.set) ctx.set(code);
      render();
    });

    function buildComponents(syl) {
      if (!syl.components || !syl.components.length) {
        compsEl.hidden = true;
        compsEl.innerHTML = "";
        state.component = "all";
        return;
      }
      compsEl.hidden = false;
      compsEl.innerHTML =
        '<button data-c="all"' + (state.component === "all" ? ' class="on"' : "") +
          ">All components</button>" +
        syl.components.map(function (c) {
          return '<button data-c="' + esc(c.key) + '"' +
            (state.component === c.key ? ' class="on"' : "") + ">" +
            esc(c.label) + "</button>";
        }).join("");
    }

    compsEl.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-c]");
      if (!b) return;
      state.component = b.dataset.c;
      compsEl.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render();
    });

    function onSearch() { state.query = searchEl.value.trim().toLowerCase(); render(); }
    searchEl.addEventListener("input", onSearch);

    function onFilter(ev) {
      var b = ev.target.closest("button[data-f]");
      if (!b) return;
      state.filter = b.dataset.f;
      filterEl.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render();
    }
    filterEl.addEventListener("click", onFilter);

    recallEl.addEventListener("change", function () {
      state.recall = recallEl.checked;
      outEl.classList.toggle("fs-recall-active", state.recall);
      outEl.querySelectorAll(".fs-item").forEach(function (card) {
        card.classList.remove("revealed");
      });
    });

    // ── Click delegation: derivation button → open modal; recall card → reveal
    outEl.addEventListener("click", function (ev) {
      var derivBtn = ev.target.closest("[data-deriv-btn]");
      if (derivBtn) {
        ev.stopPropagation();
        var formulaKey = derivBtn.dataset.derivBtn;
        var syl = DATA && DATA.syllabuses[state.syllabus];
        var found = null;
        if (syl) {
          syl.groups.forEach(function(g) {
            g.formulas.forEach(function(f) {
              if ((f.name + g.topic) === formulaKey) found = f;
            });
          });
        }
        if (found) openDerivModal(found, esc);
        return;
      }

      if (state.recall) {
        var card = ev.target.closest(".fs-item");
        if (card) card.classList.toggle("revealed");
      }
    });

    var printBtn = $("[data-print]");
    if (printBtn) printBtn.addEventListener("click", function () { window.print(); });

    var off = ctx.onChange ? ctx.onChange(function (syl) {
      if (!DATA || !DATA.syllabuses[syl] || state.syllabus === syl) return;
      state.syllabus = syl;
      render();
    }) : function () {};

    function refreshMission() {
      if (!missionEl || compact) return;
      var syl = DATA && DATA.syllabuses[state.syllabus];
      if (!syl || !window.PWT.AR) { missionEl.hidden = true; return; }
      missionEl.hidden = false;
      window.PWT.AR.buildMissionBanner(missionEl, state.syllabus, syl.groups, function () {
        window.PWT.AR.launchSession(state.syllabus, syl.groups, refreshMission);
      });
    }

    function render() {
      var syl = DATA && DATA.syllabuses[state.syllabus];
      if (!syl) { outEl.innerHTML = ""; return; }

      buildTabs();
      buildComponents(syl);
      refreshMission();

      noteEl.className = "fs-note " + (syl.sheet_provided ? "provided" : "memorise");
      noteEl.innerHTML = "<strong>" + esc(syl.level) + " " + esc(syl.subject) + " — " +
        (syl.sheet_provided ? "formula list provided" : "nothing is provided") +
        ".</strong> " + esc(syl.sheet_note) +
        (syl.calculator ? " <em>" + esc(syl.calculator) + "</em>" : "");

      var q = state.query, filter = state.filter, html = "", total = 0;
      syl.groups.forEach(function (g) {
        if (state.component !== "all" && g.component && g.component !== state.component) return;

        // Graph tips section gets a special heading
        var isGraphTips = !!g.graph_tips;
        var isZTable = !!g.z_table;

        var items = g.formulas ? g.formulas.filter(function (f) {
          if (!isGraphTips) {
            if (filter === "given" && !f.given) return false;
            if (filter === "memo"  &&  f.given) return false;
          }
          if (!q) return true;
          return (f.name + " " + f.expr + " " + (f.vars || "") + " " + g.topic)
            .toLowerCase().indexOf(q) >= 0;
        }) : [];

        if (!items.length && !isZTable) return;
        if (!isGraphTips) total += items.length;

        html += '<section class="fs-group' + (isGraphTips ? ' fs-graph-group' : '') + '">' +
          '<div class="fs-group-head">' +
          '<h3>' + esc(g.topic) + '</h3>' +
          (g.component && state.component === "all"
            ? '<span class="fs-comp-tag">' + esc(g.component) + '</span>' : '') +
          (!isGraphTips && !isZTable ?
            '<a href="papers.html?syllabus=' + encodeURIComponent(state.syllabus) +
            "&topics=" + encodeURIComponent(g.topic) + '"' +
            (compact ? ' target="_blank" rel="noopener"' : '') +
            ">Practise this chapter →</a>" : '') +
          '</div>';

        // Z-table render
        if (isZTable && g.z_table) {
          html += renderZTable(g.z_table);
        }

        // Formula cards
        html += '<div class="fs-list">' + items.map(function (f) {
          if (isGraphTips) return renderGraphCard(f, esc);

          var hasDeriv = (f.derivation_latex && f.derivation_latex.length > 0) ||
                         (f.derivation && f.derivation.length > 0);
          var derivKey = (f.name + g.topic).replace(/"/g, "");

          return '<article class="fs-item ' + (f.given ? "is-given" : "is-memo") + '">' +
            '<div class="fs-item-head">' +
              '<span class="fs-name">' + esc(f.name) + '</span>' +
              '<span class="fs-badge ' + (f.given ? "given" : "memo") + '">' +
              (f.given ? "Given in exam" : "Must memorise") + '</span>' +
            '</div>' +
            '<div class="fs-expr-wrap">' +
              '<div class="fs-expr">' + esc(f.expr) + '</div>' +
              '<div class="fs-expr-mask">👁 Click to reveal</div>' +
            '</div>' +
            (f.vars ? '<div class="fs-vars">' + esc(f.vars) + '</div>' : '') +
            (f.relations ? '<div class="fs-tip fs-tip-relation"><strong>Relationships:</strong> ' +
              esc(f.relations) + '</div>' : '') +
            (f.memory_cue ? '<div class="fs-tip fs-tip-cue"><strong>Memory cue:</strong> ' +
              esc(f.memory_cue) + '</div>' : '') +
            (f.watch_out ? '<div class="fs-tip fs-tip-warn"><strong>Watch out:</strong> ' +
              esc(f.watch_out) + '</div>' : '') +
            (hasDeriv ?
              '<button class="fs-deriv-toggle" data-deriv-btn="' + esc(derivKey) + '">' +
                '∑ View step-by-step derivation</button>' : '') +
            '</article>';
        }).join("") + '</div></section>';
      });

      outEl.innerHTML = total ? html
        : '<div class="fs-empty">No formulas match "' + esc(q) + '".</div>';

      var given = 0, memo = 0;
      syl.groups.forEach(function (g) {
        if (g.graph_tips || g.z_table) return;
        (g.formulas || []).forEach(function (f) { f.given ? given++ : memo++; });
      });
      countEl.textContent = total + " shown · " + memo + " to memorise · " +
        given + " given in the exam";

      outEl.classList.toggle("fs-recall-active", state.recall);
    }

    return function teardown() {
      searchEl.removeEventListener("input", onSearch);
      filterEl.removeEventListener("click", onFilter);
      off();
      root.innerHTML = "";
    };
  }

  if (window.PWT) {
    window.PWT.register({ id: "formulas", name: "Formula sheets", icon: "📐", mount: mount });
  }
})();
