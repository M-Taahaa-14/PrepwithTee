/* PrepWithTee — command words (mountable widget).
 *
 * Cambridge publishes exactly what each command word requires, and students
 * still lose marks writing a description where the paper said "Explain". The
 * definitions here are lifted verbatim from the 11 official syllabus PDFs.
 *
 * The second half is the part no revision guide has: each word links to REAL
 * questions from the archive that open with it, via /api/questions, so the
 * student sees the word doing its job in a genuine paper rather than in the
 * abstract.
 */
(function () {
  "use strict";

  // How many marks the word typically signals, and the trap students fall
  // into. Written for the tutor's students, not lifted from anywhere.
  var COACHING = {
    "State": "One line, no reasoning. If you find yourself writing “because”, you have misread the question.",
    "Give": "Same as State — recall only. No working, no justification.",
    "Describe": "Say WHAT happens. Not why. Cover every stage the question asks about.",
    "Explain": "Say WHY it happens. Every mark here needs a reason — “because”, “so that”, “due to”.",
    "Calculate": "Show the substitution, not just the answer. Method marks survive an arithmetic slip.",
    "Determine": "Like Calculate, but you must pull the data out of a graph or table first.",
    "Suggest": "There is no single right answer. Apply what you know to an unfamiliar case.",
    "Compare": "Both things, in the same sentence. “A is larger than B” scores; two separate descriptions often do not.",
    "Deduce": "Use the evidence given, then state the conclusion it forces.",
    "Sketch": "Freehand is fine, but shape, intercepts and asymptotes must be right.",
    "Plot": "Accuracy matters — points to within half a small square, then a smooth curve.",
    "Show (that)": "The answer is printed. Marks come from the working, so write every step.",
    "Justify": "Make a claim, then back it with evidence from the question.",
    "Define": "The precise wording from the syllabus. Approximate definitions lose the mark.",
    "Estimate": "Round sensibly first, then calculate. Show what you rounded to.",
    "Identify": "Name it. One word or a short phrase is usually enough.",
    "Predict": "Say what will happen, based on the pattern or data you have been given.",
    "Outline": "Main points only — do not write the full explanation.",
    "Discuss": "Both sides, then a conclusion. Structure earns the marks.",
    "Evaluate": "Weigh strengths against weaknesses and commit to a judgement.",
    "Work out": "Calculate — and the syllabus notes this may be with or without a calculator.",
    "Write down": "No working expected. Read it straight off.",
    "Construct": "Ruler and compasses. Leave your arcs visible — they are worth marks."
  };

  function mount(root, opts) {
    var PWTx = window.PWT, esc = PWTx.esc;
    var compact = opts && opts.mode === "dock";
    var ctx = (opts && opts.ctx) || {};
    var DATA = null, state = { syllabus: null, query: "", open: null };

    root.innerHTML =
      '<div class="fs-controls">' +
        '<select class="tool-select" data-syl aria-label="Choose a subject"></select>' +
        '<input class="fs-search" data-search type="search" ' +
          'placeholder="Search — “explain”, “state”…" aria-label="Search command words">' +
      "</div>" +
      '<div class="cw-note">Cambridge publishes these definitions in the syllabus. ' +
      'They are what the examiner marks against — matching the command word is ' +
      'often worth more than knowing more content.</div>' +
      '<div data-out><p class="fs-vars">Loading…</p></div>';

    var $ = function (s) { return root.querySelector(s); };
    var selEl = $("[data-syl]"), searchEl = $("[data-search]"), outEl = $("[data-out]");

    Promise.all([
      PWTx.data("command-words"),
      fetch("/api/enrollments").then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (results) {
      DATA = results[0];
      var enrollRes = results[1];
      var codes = Object.keys(DATA);
      var enrolled = enrollRes && enrollRes.enrollments ? enrollRes.enrollments.map(function(e) { return e.syllabus; }) : [];

      if (enrolled.length > 0) {
        codes = codes.filter(function(c) { return enrolled.indexOf(c) >= 0; });
      }

      // Grouped by qualification, so a student scanning for their course is
      // not reading through eleven flat entries. The subject strings carry
      // the level in brackets — "Physics (IGCSE)".
      var ORDER = ["Cambridge O Level", "Cambridge IGCSE", "Cambridge A Level"];
      var byLevel = {};
      codes.forEach(function (c) {
        var m = /\(([^)]+)\)\s*$/.exec(DATA[c].subject);
        var level = "Cambridge " + (m ? m[1] : "Other");
        (byLevel[level] = byLevel[level] || []).push(c);
      });
      selEl.innerHTML = ORDER.concat(Object.keys(byLevel).filter(function (l) {
        return ORDER.indexOf(l) < 0;
      })).filter(function (l) { return byLevel[l]; }).map(function (level) {
        return '<optgroup label="' + esc(level) + '">' +
          byLevel[level].map(function (c) {
            var name = DATA[c].subject.replace(/\s*\([^)]*\)\s*$/, "");
            return '<option value="' + esc(c) + '">' + esc(name) +
              " (" + esc(c) + ")</option>";
          }).join("") + "</optgroup>";
      }).join("");
      var pick = (codes.indexOf(ctx.syllabus) >= 0 && ctx.syllabus) || codes[0];
      if (pick) {
        selEl.value = pick; state.syllabus = pick;
        render();
      } else {
        outEl.innerHTML = '<div class="fs-empty">Enroll in a subject to view command words.</div>';
      }
    }).catch(function (err) {
      outEl.innerHTML = '<div class="fs-empty">Could not load command words (' +
        esc(err.message) + ").</div>";
    });

    function onSyl() {
      state.syllabus = selEl.value; state.open = null;
      if (ctx.set) ctx.set(selEl.value);
      render();
    }
    selEl.addEventListener("change", onSyl);

    function onSearch() { state.query = searchEl.value.trim().toLowerCase(); render(); }
    searchEl.addEventListener("input", onSearch);

    var off = ctx.onChange ? ctx.onChange(function (syl) {
      if (!DATA || !DATA[syl] || state.syllabus === syl) return;
      state.syllabus = syl; selEl.value = syl; state.open = null; render();
    }) : function () {};

    function render() {
      var sub = DATA && DATA[state.syllabus];
      if (!sub) { outEl.innerHTML = ""; return; }
      var q = state.query;
      var words = Object.keys(sub.words).sort().filter(function (w) {
        return !q || (w + " " + sub.words[w]).toLowerCase().indexOf(q) >= 0;
      });

      outEl.innerHTML = words.length ? '<div class="cw-list">' + words.map(function (w) {
        var open = state.open === w;
        return '<article class="cw-item' + (open ? " open" : "") + '" data-word="' + esc(w) + '">' +
          '<button class="cw-head" data-toggle="' + esc(w) + '">' +
            '<span class="cw-word">' + esc(w) + "</span>" +
            '<span class="cw-def">' + esc(sub.words[w]) + "</span>" +
            '<span class="cw-chev">' + (open ? "▴" : "▾") + "</span>" +
          "</button>" +
          (open ? '<div class="cw-body">' +
            (COACHING[w] ? '<p class="cw-coach"><strong>In the exam:</strong> ' +
                            esc(COACHING[w]) + "</p>" : "") +
            '<div class="cw-examples" data-examples="' + esc(w) + '">' +
              '<p class="fs-vars">Finding real questions…</p></div>' +
          "</div>" : "") +
          "</article>";
      }).join("") + "</div>"
        : '<div class="fs-empty">No command word matches “' + esc(q) + '”.</div>';

      if (state.open) loadExamples(state.open);
    }

    function onToggle(ev) {
      var b = ev.target.closest("[data-toggle]");
      if (!b) return;
      state.open = state.open === b.dataset.toggle ? null : b.dataset.toggle;
      render();
    }
    outEl.addEventListener("click", onToggle);

    // Real questions that open with this command word. The archive stores full
    // question text, so a regex on the word boundary finds genuine usages.
    var exampleCache = {};
    function loadExamples(word) {
      var host = outEl.querySelector('[data-examples="' + cssEsc(word) + '"]');
      if (!host) return;
      var key = state.syllabus + "|" + word;
      if (exampleCache[key]) return paint(host, exampleCache[key]);

      // "Show (that)" is printed with brackets; the paper says "Show that".
      var probe = word.replace(/\s*\(([^)]*)\)/, " $1").trim();
      fetch("/api/questions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          syllabus: state.syllabus,
          topics: allTopics(),
          contains: "\\b" + probe.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b"
        })
      }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          var qs = (d && d.questions ? d.questions : []).slice(0, 4);
          exampleCache[key] = qs;
          paint(host, qs);
        })
        .catch(function () { host.innerHTML = '<p class="fs-vars">Examples unavailable.</p>'; });
    }

    function paint(host, qs) {
      if (!host) return;
      if (!qs.length) {
        host.innerHTML = '<p class="fs-vars">No question in the archive uses this word for ' +
          'this subject yet.</p>';
        return;
      }
      host.innerHTML = '<p class="cw-ex-head">Real questions using it</p>' +
        qs.map(function (q) {
          return '<a class="cw-ex" href="/api/question/' + q.id + '/preview" target="_blank" rel="noopener">' +
            '<span class="cw-ex-ref">' + esc(q.ref) + (q.marks ? " · " + q.marks + "m" : "") + "</span>" +
            '<span class="cw-ex-text">' + esc((q.text_snippet || "").slice(0, 130)) + "…</span></a>";
        }).join("");
    }

    // The API needs a topic list; ask for every topic this subject has.
    var topicCache = null;
    function allTopics() {
      if (topicCache && topicCache.syl === state.syllabus) return topicCache.list;
      return [];
    }
    function primeTopics() {
      fetch("/api/meta").then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          var s = (d.subjects || []).find(function (x) { return x.syllabus === state.syllabus; });
          topicCache = { syl: state.syllabus,
                         list: s ? s.topics.map(function (t) { return t.name; }) : [] };
          if (state.open) { exampleCache = {}; loadExamples(state.open); }
        }).catch(function () {});
    }
    selEl.addEventListener("change", primeTopics);
    setTimeout(primeTopics, 0);

    function cssEsc(s) { return String(s).replace(/"/g, '\\"'); }

    return function teardown() {
      selEl.removeEventListener("change", onSyl);
      selEl.removeEventListener("change", primeTopics);
      searchEl.removeEventListener("input", onSearch);
      outEl.removeEventListener("click", onToggle);
      off();
      root.innerHTML = "";
    };
  }

  if (window.PWT) {
    window.PWT.register({ id: "command", name: "Command words", icon: "💡", mount: mount });
  }
})();
