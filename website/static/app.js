(function () {
  /* PrepWithTee generator UI */
  const $ = (s) => document.querySelector(s);

  const state = {
    meta: null, syllabus: null, mode: "topical", papers: [], board: null,
    sessions: [],  // empty = all sessions
    variants: [],  // empty = all variants
    subtopics: {}, // topic_name -> Set of selected subtopic names
  };

  const SESSION_LABELS = { s: "May/Jun", w: "Oct/Nov", m: "Feb/Mar", y: "Yearly" };

async function init() {
  const r = await fetch("/api/meta");
  state.meta = await r.json();

  // hero stats
  let total = 0;
  for (const s of state.meta.subjects)
    for (const t of s.topics) total += t.count;
  $("#stat-questions").textContent = total.toLocaleString() + "+";
  $("#stat-subjects").textContent = state.meta.subjects.length;

  // years — initial defaults (overridden per-subject in pickSubject)
  setYearRange(state.meta.year_min, state.meta.year_max);

  // subjects, grouped by board with a switcher toggle
  const row = $("#subjects");
  row.innerHTML = "";
  const byBoard = {};
  for (const s of state.meta.subjects) (byBoard[s.board] ||= []).push(s);
  const order = state.meta.board_order || [];
  const boards = [
    ...order.filter((b) => byBoard[b]),
    ...Object.keys(byBoard).filter((b) => !order.includes(b)),
  ];

  const switcher = document.createElement("div");
  switcher.className = "seg-large";
  switcher.id = "board-toggle";
  for (const board of boards) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.board = board.toLowerCase().replace(/\s+/g, "-");
    btn.textContent = board.replace(/^Cambridge\s+/, "");
    btn.onclick = () => switchBoard(board);
    switcher.appendChild(btn);
  }
  row.appendChild(switcher);

  for (const board of boards) {
    const group = document.createElement("div");
    group.className = "subject-group";
    group.dataset.board = board.toLowerCase().replace(/\s+/g, "-");
    const pr = document.createElement("div");
    pr.className = "pill-row";
    for (const s of byBoard[board]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pill subject";
      b.dataset.syllabus = s.syllabus;
      b.innerHTML = `${s.short || s.subject} <small>${s.syllabus}</small>`;
      b.onclick = () => pickSubject(s.syllabus);
      pr.appendChild(b);
    }
    group.appendChild(pr);
    row.appendChild(group);
  }

  const want = new URLSearchParams(location.search).get("syllabus");
  const first = state.meta.subjects.find((s) => s.syllabus === want) ||
    state.meta.subjects[0];
  switchBoard(first.board);
  pickSubject(first.syllabus);
}

function setYearRange(yearMin, yearMax) {
  const fromSel = $("#yfrom"), toSel = $("#yto");
  const prevFrom = +fromSel.value, prevTo = +toSel.value;
  fromSel.innerHTML = "";
  toSel.innerHTML = "";
  for (let y = yearMin; y <= yearMax; y++) {
    for (const sel of [fromSel, toSel]) {
      const o = document.createElement("option");
      o.value = o.textContent = y;
      sel.appendChild(o);
    }
  }
  fromSel.value = (prevFrom >= yearMin && prevFrom <= yearMax) ? prevFrom : yearMin;
  toSel.value   = (prevTo   >= yearMin && prevTo   <= yearMax) ? prevTo   : yearMax;
}

function switchBoard(board) {
  state.board = board;
  const boardKey = board.toLowerCase().replace(/\s+/g, "-");
  document.querySelectorAll("#board-toggle button").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.board === boardKey));
  document.querySelectorAll("#subjects .subject-group").forEach((g) => {
    g.style.display = g.dataset.board === boardKey ? "" : "none";
  });
}

function pickSubject(syl) {
  state.syllabus = syl;
  state.papers = [];
  state.sessions = [];
  state.variants = [];
  state.subtopics = {};

  document.querySelectorAll(".subject").forEach((b) =>
    b.classList.toggle("active", b.dataset.syllabus === syl));
  const sub = state.meta.subjects.find((s) => s.syllabus === syl);
  if (sub && sub.board !== state.board) switchBoard(sub.board);

  const compField = $("#component-field");
  const compRow = $("#components");
  compRow.innerHTML = "";
  const hasComponents = sub.components && sub.components.length;

  if (hasComponents) {
    compField.classList.remove("hidden");
    const mk = (paper, label, count) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pill component";
      b.dataset.paper = paper === null ? "" : paper;
      b.innerHTML = `${label} <small>${count}</small>`;
      b.onclick = () => toggleComponent(paper);
      compRow.appendChild(b);
    };
    mk(null, "All papers", sub.components.reduce((sum, c) => sum + c.count, 0));
    for (const c of sub.components) mk(c.paper, c.label, c.count);
    syncComponentPills();
  } else {
    compField.classList.add("hidden");
  }

  // Shift step numbers when component row is present
  const n = hasComponents ? 1 : 0;
  $("#topics-step").textContent = `${2 + n} · Topics`;
  $("#years-label").textContent = `${3 + n} · Years`;
  $("#format-label").textContent = `${4 + n} · Format`;
  $("#filter-label").textContent = `${5 + n} · Narrow by session / variant`;

  // Update year range to match the actual data available for this syllabus
  const yearMin = sub.year_min || state.meta.year_min;
  const yearMax = sub.year_max || state.meta.year_max;
  setYearRange(yearMin, yearMax);

  renderSessionPills(sub);
  renderTopics();
}

// ── Session / variant pills ──────────────────────────────────────────────────

function makePill(label, onclick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "pill filter-pill";
  btn.textContent = label;
  btn.onclick = onclick;
  return btn;
}

function renderSessionPills(sub) {
  const sessions = (sub && sub.sessions) || [];
  const variants = (sub && sub.variants) || [];
  const sessionRow = $("#session-pills");
  const variantRow = $("#variant-pills");
  const variantWrap = $("#variant-wrap");
  sessionRow.innerHTML = "";
  variantRow.innerHTML = "";

  // "All" session pill
  const allSBtn = makePill("All", () => {
    state.sessions = [];
    syncSessionPills();
    updateSummary();
  });
  allSBtn.dataset.sessionAll = "1";
  sessionRow.appendChild(allSBtn);

  for (const code of sessions) {
    const label = SESSION_LABELS[code] || code.toUpperCase();
    const btn = makePill(label, () => {
      if (state.sessions.includes(code)) {
        state.sessions = state.sessions.filter(s => s !== code);
      } else {
        state.sessions = [...state.sessions, code];
      }
      syncSessionPills();
      updateSummary();
    });
    btn.dataset.session = code;
    sessionRow.appendChild(btn);
  }

  // Variant pills (only when syllabus has multiple variants)
  if (variants.length > 1) {
    variantWrap.classList.remove("hidden");
    const allVBtn = makePill("All", () => {
      state.variants = [];
      syncVariantPills();
      updateSummary();
    });
    allVBtn.dataset.variantAll = "1";
    variantRow.appendChild(allVBtn);

    for (const v of variants) {
      const vStr = String(v);
      const btn = makePill(`v${vStr}`, () => {
        if (state.variants.includes(vStr)) {
          state.variants = state.variants.filter(x => x !== vStr);
        } else {
          state.variants = [...state.variants, vStr];
        }
        syncVariantPills();
        updateSummary();
      });
      btn.dataset.variant = vStr;
      variantRow.appendChild(btn);
    }
  } else {
    variantWrap.classList.add("hidden");
  }

  syncSessionPills();
  syncVariantPills();
}

function syncSessionPills() {
  const allActive = state.sessions.length === 0;
  document.querySelectorAll("[data-session-all]").forEach(b =>
    b.classList.toggle("active", allActive));
  document.querySelectorAll("[data-session]").forEach(b =>
    b.classList.toggle("active", state.sessions.includes(b.dataset.session)));
}

function syncVariantPills() {
  const allActive = state.variants.length === 0;
  document.querySelectorAll("[data-variant-all]").forEach(b =>
    b.classList.toggle("active", allActive));
  document.querySelectorAll("[data-variant]").forEach(b =>
    b.classList.toggle("active", state.variants.includes(b.dataset.variant)));
}

// ── Component (multi-select) ─────────────────────────────────────────────────

function toggleComponent(paper) {
  if (paper === null) {
    // "All papers" pill: clear all specific selections
    state.papers = [];
  } else {
    const key = paper;
    if (state.papers.includes(key)) {
      state.papers = state.papers.filter((p) => p !== key);
    } else {
      state.papers = [...state.papers, key];
    }
  }
  syncComponentPills();
  renderTopics();
  updateSummary();
}

function syncComponentPills() {
  const allActive = state.papers.length === 0;
  document.querySelectorAll(".pill.component").forEach((b) => {
    if (b.dataset.paper === "") {
      b.classList.toggle("active", allActive);
    } else {
      b.classList.toggle("active", state.papers.includes(+b.dataset.paper));
    }
  });
}

// ── Topics + subtopics ───────────────────────────────────────────────────────

function renderTopics() {
  const sub = state.meta.subjects.find((s) => s.syllabus === state.syllabus);
  const keep = new Set(
    [...document.querySelectorAll("#topics .topic-cb:checked")].map((i) => i.value));
  const box = $("#topics");
  box.innerHTML = "";

  let shown = 0;
  for (const t of sub.topics) {
    const count = state.papers.length === 0
      ? t.count
      : state.papers.reduce((s, p) => s + (t.papers[String(p)] || 0), 0);
    if (!count) continue;
    shown++;

    const wrapper = document.createElement("div");
    wrapper.className = "topic-wrapper";

    const hasSubtopics = t.subtopics && t.subtopics.length > 0;

    const label = document.createElement("label");
    label.className = "topic";
    label.dataset.count = count;
    label.dataset.topicName = t.name;

    label.innerHTML =
      `<input type="checkbox" class="topic-cb" value="${t.name}">` +
      `<span>${t.name}</span><span class="n">${count}</span>` +
      (hasSubtopics
        ? `<button type="button" class="subtopic-toggle" title="Filter by sub-topic">▾</button>`
        : "");

    const input = label.querySelector(".topic-cb");
    if (keep.has(t.name)) { input.checked = true; label.classList.add("on"); }
    input.onchange = (e) => { label.classList.toggle("on", e.target.checked); updateSummary(); };
    wrapper.appendChild(label);

    if (hasSubtopics) {
      const panel = document.createElement("div");
      panel.className = "subtopic-panel";
      panel.hidden = true;

      const note = document.createElement("p");
      note.className = "subtopic-note";
      note.textContent = "Narrow to specific sub-topics (leave all unchecked to include all):";
      panel.appendChild(note);

      const grid = document.createElement("div");
      grid.className = "subtopic-grid";
      const saved = state.subtopics[t.name] || new Set();

      for (const st of t.subtopics) {
        const row = document.createElement("label");
        row.className = "subtopic-item";
        const countBadge = st.count ? ` <span class="n">${st.count}</span>` : "";
        row.innerHTML =
          `<input type="checkbox" class="subtopic-cb" data-topic="${t.name}" value="${st.name}">` +
          `<span>${st.name}${countBadge}</span>`;
        const stCb = row.querySelector(".subtopic-cb");
        if (saved.has(st.name)) stCb.checked = true;
        stCb.onchange = () => {
          const picked = [...panel.querySelectorAll(".subtopic-cb:checked")].map(x => x.value);
          state.subtopics[t.name] = new Set(picked);
          updateSummary();
        };
        grid.appendChild(row);
      }
      panel.appendChild(grid);
      wrapper.appendChild(panel);

      const toggleBtn = label.querySelector(".subtopic-toggle");
      toggleBtn.onclick = (e) => {
        e.preventDefault();
        const open = !panel.hidden;
        panel.hidden = open;
        toggleBtn.textContent = open ? "▾" : "▴";
        toggleBtn.classList.toggle("open", !open);
      };
    }

    box.appendChild(wrapper);
  }

  const compLabel = state.papers.length === 1
    ? (sub.components || []).find((c) => c.paper === state.papers[0])?.label
    : state.papers.length > 1
    ? state.papers.map((p) => (sub.components || []).find((c) => c.paper === p)?.label || `P${p}`).join(" + ")
    : null;
  $("#topic-note").textContent = compLabel
    ? `${shown} topics in ${compLabel}`
    : `${shown} topics across all papers`;

  const search = $("#topic-search");
  search.style.display = shown > 8 ? "" : "none";
  search.value = "";
  filterTopics("");
  updateSummary();
}

function filterTopics(q) {
  q = q.trim().toLowerCase();
  document.querySelectorAll("#topics .topic-wrapper").forEach((w) => {
    const name = w.querySelector(".topic span").textContent.toLowerCase();
    w.style.display = !q || name.includes(q) ? "" : "none";
  });
}

// ── Summary ──────────────────────────────────────────────────────────────────

function updateSummary() {
  const checked = [...document.querySelectorAll("#topics .topic-cb:checked")];
  const nTopics = checked.length;
  const nQ = checked.reduce((s, i) => s + (+i.closest(".topic").dataset.count || 0), 0);
  const sub = state.meta.subjects.find((s) => s.syllabus === state.syllabus);
  const go = $("#go");
  const el = $("#gen-summary");

  if (!nTopics) {
    el.innerHTML = '<span class="muted">Pick at least one topic to build your paper.</span>';
    go.disabled = true;
    return;
  }
  go.disabled = false;

  const compLabel = state.papers.length === 0
    ? "All papers"
    : state.papers.map((p) =>
        (sub.components || []).find((c) => c.paper === p)?.label || `P${p}`
      ).join(" + ");
  const yf = $("#yfrom").value, yt = $("#yto").value;
  const fmt = state.mode === "test"
    ? "Timed test (answers separate)"
    : ($("#inc-ms").checked ? "Booklet · mark scheme after each question" : "Booklet · questions only");

  const sessionStr = state.sessions.length
    ? state.sessions.map(s => SESSION_LABELS[s] || s.toUpperCase()).join(" + ")
    : null;
  const variantStr = state.variants.length
    ? state.variants.map(v => `v${v}`).join(", ")
    : null;

  const selectedSubtopicCount = Object.entries(state.subtopics)
    .filter(([topic]) => checked.some(i => i.value === topic))
    .reduce((n, [, s]) => n + s.size, 0);

  const parts = [
    `<b>${sub.subject}</b>`,
    compLabel,
    `<b>${nTopics}</b> topic${nTopics > 1 ? "s" : ""} <span class="muted">(~${nQ} questions)</span>`,
    `${yf}–${yt}`,
  ];
  if (sessionStr) parts.push(`<span class="filter-badge">📅 ${sessionStr}</span>`);
  if (variantStr) parts.push(`<span class="filter-badge">🔢 ${variantStr}</span>`);
  if (selectedSubtopicCount) parts.push(`<span class="filter-badge">🔍 ${selectedSubtopicCount} sub-topic${selectedSubtopicCount > 1 ? "s" : ""}</span>`);
  parts.push(fmt);

  el.innerHTML = parts.join(" &middot; ");
}

// ── Controls ─────────────────────────────────────────────────────────────────

$("#all").onclick = () => {
  document.querySelectorAll("#topics .topic-cb").forEach((i) => {
    if (i.closest(".topic-wrapper").style.display !== "none") {
      i.checked = true; i.closest(".topic").classList.add("on");
    }
  });
  updateSummary();
};
$("#none").onclick = () => {
  document.querySelectorAll("#topics .topic-cb").forEach((i) => {
    i.checked = false; i.closest(".topic").classList.remove("on");
  });
  updateSummary();
};

$("#topic-search").oninput = (e) => filterTopics(e.target.value);
$("#yfrom").onchange = updateSummary;
$("#yto").onchange = updateSummary;
$("#inc-ms").onchange = updateSummary;

document.querySelectorAll(".mode").forEach((b) => {
  b.onclick = () => {
    state.mode = b.dataset.mode;
    document.querySelectorAll(".mode").forEach((x) =>
      x.classList.toggle("active", x === b));
    $("#topical-opts").classList.toggle("hidden", state.mode !== "topical");
    $("#test-opts").classList.toggle("hidden", state.mode !== "test");
    $("#go").textContent =
      state.mode === "test" ? "Generate test + mark scheme" : "Generate PDF";
    updateSummary();
  };
});

// ── Status helper ────────────────────────────────────────────────────────────

function status(msg, cls = "") {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status " + cls;
}

// ── Generate ─────────────────────────────────────────────────────────────────

$("#go").onclick = async () => {
  const topics = [...document.querySelectorAll("#topics .topic-cb:checked")].map((i) => i.value);
  if (!topics.length) return status("Pick at least one topic first.", "err");

  // Collect selected subtopics (flat list, only for checked topics)
  const subtopics = [];
  for (const [topicName, stSet] of Object.entries(state.subtopics)) {
    if (stSet.size > 0 && topics.includes(topicName)) {
      for (const st of stSet) subtopics.push(st);
    }
  }

  const body = {
    mode: state.mode,
    syllabus: state.syllabus,
    topics,
    year_from: +$("#yfrom").value,
    year_to: +$("#yto").value,
    include_ms: $("#inc-ms").checked,
  };
  if (state.papers.length) body.papers = state.papers;
  if (state.sessions.length) body.sessions = state.sessions;
  if (state.variants.length) body.variants = state.variants;
  if (subtopics.length) body.subtopics = subtopics;
  if (state.mode === "test") {
    const marks = +$("#marks").value;
    if (marks) body.marks = marks;
    else body.count = +$("#count").value || 6;
  }

  const go = $("#go");
  const pwrap = $("#progress-wrap");
  const pbar = $("#progress-bar");
  go.disabled = true;
  pwrap.hidden = false;
  pbar.className = "progress-bar indeterminate";
  pbar.style.width = "";
  status("Building your paper — a few seconds…");

  try {
    const r = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `server error (${r.status})`);
    }

    const cd = r.headers.get("Content-Disposition") || "";
    const name = (cd.match(/filename="?([^";]+)/) || [])[1] ||
      (state.mode === "test" ? "test.zip" : "topical.pdf");
    const total = +(r.headers.get("Content-Length") || 0);
    pbar.className = "progress-bar";
    pbar.style.width = total ? "0%" : "30%";
    status("Downloading…");

    const reader = r.body.getReader();
    const chunks = [];
    let received = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      if (total) pbar.style.width = Math.min(100, Math.round(received / total * 100)) + "%";
    }
    pbar.style.width = "100%";

    const blob = new Blob(chunks);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
    setTimeout(() => {
      pwrap.hidden = true;
      pbar.style.width = "0%";
      pbar.className = "progress-bar";
    }, 700);
    status(`Done — ${name} downloaded.`, "ok");
  } catch (err) {
    pwrap.hidden = true;
    pbar.className = "progress-bar";
    status(err.message, "err");
  } finally {
    go.disabled = false;
  }
};

init();
})();
