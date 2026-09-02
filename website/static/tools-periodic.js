/* PrepWithTee — periodic table (mountable widget).
 *
 * This is the Cambridge table, not a generic one: the relative atomic masses
 * are the values printed in the 0620/5070 exam paper (Cl = 35.5, Cu = 64), so
 * a student's practice arithmetic matches what they will have on the day. The
 * mole calculator underneath uses the same numbers.
 */
(function () {
  "use strict";

  // Categories drive the colour key. Derived from position rather than stored
  // per element, so the data file stays a faithful copy of the printed table.
  function category(e) {
    var z = e.z, g = e.group;
    if (e.series) return e.series;
    if (g === 18) return "noble";
    if (g === 1 && z !== 1) return "alkali";
    if (g === 2) return "alkaline";
    if (g >= 3 && g <= 12) return "transition";
    if (z === 1) return "nonmetal";
    var nonmetals = [1, 6, 7, 8, 15, 16, 34, 9, 17, 35, 53, 85];
    if (nonmetals.indexOf(z) >= 0) return g === 17 ? "halogen" : "nonmetal";
    var metalloids = [5, 14, 32, 33, 51, 52, 84];
    if (metalloids.indexOf(z) >= 0) return "metalloid";
    return "poormetal";
  }

  var CAT_LABEL = {
    alkali: "Group I metals", alkaline: "Group II metals", transition: "Transition elements",
    poormetal: "Other metals", metalloid: "Metalloids", nonmetal: "Non-metals",
    halogen: "Group VII halogens", noble: "Group VIII noble gases",
    lanthanide: "Lanthanoids", actinide: "Actinoids"
  };

  function mount(root, opts) {
    var PWTx = window.PWT, esc = PWTx.esc;
    var compact = opts && opts.mode === "dock";
    var DATA = null, selected = null;

    root.innerHTML =
      '<div class="fs-controls">' +
        '<input class="fs-search" data-search type="search" ' +
          'placeholder="Search — “sodium”, “Cu”, “17”…" aria-label="Search elements">' +
        '<div class="fs-filter" data-mode role="group" aria-label="View">' +
          '<button data-v="table" class="on">Table</button>' +
          '<button data-v="moles">Mole calculator</button>' +
        "</div>" +
      "</div>" +
      '<div data-out><p class="fs-vars">Loading the table…</p></div>';

    var $ = function (s) { return root.querySelector(s); };
    var outEl = $("[data-out]"), searchEl = $("[data-search]"), modeEl = $("[data-mode]");
    var view = "table", query = "";

    PWTx.data("elements").then(function (d) {
      DATA = d;
      d.elements.forEach(function (e) { e.cat = category(e); });
      render();
    }).catch(function (err) {
      outEl.innerHTML = '<div class="fs-empty">Could not load the element data (' +
        esc(err.message) + ").</div>";
    });

    function onSearch() { query = searchEl.value.trim().toLowerCase(); render(); }
    searchEl.addEventListener("input", onSearch);

    function onMode(ev) {
      var b = ev.target.closest("button[data-v]");
      if (!b) return;
      view = b.dataset.v;
      modeEl.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      render();
    }
    modeEl.addEventListener("click", onMode);

    function matches(e) {
      if (!query) return true;
      return e.name.indexOf(query) >= 0 || e.symbol.toLowerCase() === query ||
             e.symbol.toLowerCase().indexOf(query) === 0 || String(e.z) === query;
    }

    function cell(e) {
      var dim = query && !matches(e) ? " dim" : "";
      return '<button class="pt-cell cat-' + e.cat + dim + '" data-z="' + e.z + '" ' +
        'title="' + esc(e.name) + '" style="grid-column:' + e.group + ';grid-row:' + e.period + '">' +
        '<span class="pt-z">' + e.z + "</span>" +
        '<span class="pt-sym">' + esc(e.symbol) + "</span>" +
        '<span class="pt-mass">' + (e.mass == null ? "–" : e.mass) + "</span>" +
        "</button>";
    }

    function seriesRow(series, rowStart) {
      var list = DATA.elements.filter(function (e) { return e.series === series; });
      return list.map(function (e, i) {
        var dim = query && !matches(e) ? " dim" : "";
        return '<button class="pt-cell cat-' + e.cat + dim + '" data-z="' + e.z + '" ' +
          'title="' + esc(e.name) + '" style="grid-column:' + (i + 3) + ';grid-row:' + rowStart + '">' +
          '<span class="pt-z">' + e.z + "</span>" +
          '<span class="pt-sym">' + esc(e.symbol) + "</span>" +
          '<span class="pt-mass">' + (e.mass == null ? "–" : e.mass) + "</span></button>";
      }).join("");
    }

    function render() {
      if (!DATA) return;
      if (view === "moles") return renderMoles();

      var main = DATA.elements.filter(function (e) { return e.group && e.period; });
      outEl.innerHTML =
        '<div class="pt-scroll"><div class="pt-grid">' +
          main.map(cell).join("") +
          seriesRow("lanthanide", 9) + seriesRow("actinide", 10) +
        "</div></div>" +
        '<div class="pt-key">' + Object.keys(CAT_LABEL).map(function (c) {
          return '<span class="pt-key-item"><i class="cat-' + c + '"></i>' + CAT_LABEL[c] + "</span>";
        }).join("") + "</div>" +
        '<div class="pt-detail" data-detail>' +
          '<p class="fs-vars">Tap an element for its details. Masses are the values ' +
          'printed in the Cambridge exam paper.</p></div>';
      if (selected) showDetail(selected);
    }

    function onPick(ev) {
      var b = ev.target.closest("[data-z]");
      if (!b) return;
      selected = +b.dataset.z;
      root.querySelectorAll(".pt-cell.on").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      showDetail(selected);
    }
    outEl.addEventListener("click", onPick);

    function showDetail(z) {
      var host = root.querySelector("[data-detail]");
      if (!host) return;
      var e = DATA.elements.find(function (x) { return x.z === z; });
      if (!e) return;
      // Electron shells (2,8,8,...) — the Cambridge model for the first 20.
      var shells = [], left = e.z, caps = [2, 8, 8, 18, 18, 32];
      for (var i = 0; i < caps.length && left > 0; i++) {
        shells.push(Math.min(left, caps[i])); left -= caps[i];
      }
      host.innerHTML =
        '<div class="pt-detail-card cat-' + e.cat + '">' +
          '<div class="pt-detail-sym">' + esc(e.symbol) + "</div>" +
          "<div><h3>" + esc(e.name.charAt(0).toUpperCase() + e.name.slice(1)) + "</h3>" +
          '<p class="fs-vars">' + CAT_LABEL[e.cat] + "</p></div>" +
          '<dl class="pt-facts">' +
            "<div><dt>Proton number</dt><dd>" + e.z + "</dd></div>" +
            "<div><dt>Relative atomic mass</dt><dd>" +
              (e.mass == null ? "no stable isotope" : e.mass) + "</dd></div>" +
            (e.group ? "<div><dt>Group</dt><dd>" + roman(e.group) + "</dd></div>" : "") +
            "<div><dt>Period</dt><dd>" + e.period + "</dd></div>" +
            (e.z <= 20 ? "<div><dt>Electron shells</dt><dd>" + shells.join(", ") + "</dd></div>" : "") +
          "</dl>" +
        "</div>";
    }

    // Cambridge prints group numbers as Roman numerals for the main groups.
    function roman(g) {
      var map = { 1: "I", 2: "II", 13: "III", 14: "IV", 15: "V", 16: "VI", 17: "VII", 18: "VIII" };
      return map[g] || (g + " (transition)");
    }

    // ── Mole calculator ───────────────────────────────────────────────────
    function renderMoles() {
      outEl.innerHTML =
        '<div class="pt-moles">' +
          '<p class="cw-note">Type a formula the way the paper writes it — ' +
          'H2SO4, Ca(OH)2, CuSO4.5H2O — and the relative formula mass is built ' +
          'from the Cambridge masses.</p>' +
          '<div class="pt-mole-row">' +
            '<label>Formula<input class="fs-search" data-formula value="H2SO4" spellcheck="false"></label>' +
            '<label>Mass (g)<input class="fs-search" data-mass type="number" step="any" placeholder="e.g. 4.9"></label>' +
            '<label>Moles<input class="fs-search" data-mol type="number" step="any" placeholder="e.g. 0.05"></label>' +
          "</div>" +
          '<div class="pt-mole-out" data-moleout></div>' +
        "</div>";
      var f = root.querySelector("[data-formula]");
      var mIn = root.querySelector("[data-mass]"), nIn = root.querySelector("[data-mol]");
      var out = root.querySelector("[data-moleout]");

      function calcMr() {
        try { return { mr: formulaMass(f.value), err: null }; }
        catch (e) { return { mr: null, err: e.message }; }
      }
      function update(src) {
        var r = calcMr();
        if (r.err) { out.innerHTML = '<p class="gp-err">' + esc(r.err) + "</p>"; return; }
        var mr = r.mr;
        if (src === "mass" && mIn.value !== "") nIn.value = round(+mIn.value / mr);
        if (src === "mol" && nIn.value !== "") mIn.value = round(+nIn.value * mr);
        out.innerHTML =
          '<div class="pt-mr">M<sub>r</sub> of <strong>' + esc(f.value) + "</strong> = " +
          round(mr) + "</div>" +
          '<p class="fs-vars">n = m ÷ M<sub>r</sub> · one mole of gas is 24 dm³ at r.t.p.</p>';
      }
      function round(v) { return Math.round(v * 10000) / 10000; }
      f.addEventListener("input", function () { update(mIn.value !== "" ? "mass" : "mol"); });
      mIn.addEventListener("input", function () { update("mass"); });
      nIn.addEventListener("input", function () { update("mol"); });
      update();
    }

    // Parses H2SO4, Ca(OH)2 and hydrates like CuSO4.5H2O.
    function formulaMass(src) {
      var s = String(src).replace(/\s+/g, "");
      if (!s) throw new Error("Type a formula");
      var total = 0;
      // A dot separates hydrate parts, each with its own leading multiplier.
      s.split(/[.·]/).forEach(function (part) {
        var lead = part.match(/^(\d+)/);
        var mult = lead ? +lead[1] : 1;
        if (lead) part = part.slice(lead[1].length);
        total += mult * group(part);
      });
      return total;
    }

    function group(s) {
      var i = 0, total = 0;
      function chunk() {
        var sum = 0;
        while (i < s.length) {
          var c = s[i];
          if (c === "(") {
            i++;
            var inner = chunk();
            if (s[i] !== ")") throw new Error("Unmatched ( in the formula");
            i++;
            var n = num();
            sum += inner * n;
          } else if (c === ")") {
            return sum;
          } else if (/[A-Z]/.test(c)) {
            var sym = c; i++;
            while (i < s.length && /[a-z]/.test(s[i])) sym += s[i++];
            var e = DATA.elements.find(function (x) { return x.symbol === sym; });
            if (!e) throw new Error("Unknown element “" + sym + "”");
            if (e.mass == null) throw new Error(sym + " has no stable isotope mass");
            sum += e.mass * num();
          } else {
            throw new Error("Unexpected “" + c + "” in the formula");
          }
        }
        return sum;
      }
      function num() {
        var d = "";
        while (i < s.length && /\d/.test(s[i])) d += s[i++];
        return d ? +d : 1;
      }
      total = chunk();
      if (i < s.length) throw new Error("Unmatched ) in the formula");
      return total;
    }

    return function teardown() {
      searchEl.removeEventListener("input", onSearch);
      modeEl.removeEventListener("click", onMode);
      outEl.removeEventListener("click", onPick);
      root.innerHTML = "";
    };
  }

  if (window.PWT) {
    window.PWT.register({ id: "periodic", name: "Periodic table", icon: "⚗️", mount: mount });
  }
})();
