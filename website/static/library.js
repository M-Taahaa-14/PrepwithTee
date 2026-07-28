(function () {
  /* PrepWithTee paper library — a collapsible archive tree plus a viewer that
     shows a question paper and its mark scheme together. */
  const $ = (s) => document.querySelector(s);

  const state = {
    syllabus: null,     // currently expanded subject
    selected: null,     // {year, session, name, code, paper, variant, qp, ms}
    layout: "stacked",
    trees: {},          // syllabus -> fetched tree, so re-opening is instant
  };

async function get(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error("could not reach the archive");
  return r.json();
}

/* ---------- tree building ---------------------------------------------- */

function row({ depth, icon, label, count, tag, folder, onClick }) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "tree-row" + (folder ? "" : " tree-file");
  b.style.setProperty("--depth", depth);
  b.innerHTML =
    `<span class="chev">${folder ? "▶" : ""}</span>` +
    `<span class="ico">${icon}</span>` +
    `<span class="lbl">${label}</span>` +
    (tag ? `<span class="tag ${tag}">${tag.toUpperCase()}</span>` : "") +
    (count != null ? `<span class="n">${count}</span>` : "");
  b.onclick = onClick;
  return b;
}

function group(parentEl, headerRow) {
  const kids = document.createElement("div");
  kids.className = "tree-kids";
  kids.hidden = true;
  headerRow.onclick = () => {
    kids.hidden = !kids.hidden;
    headerRow.classList.toggle("open", !kids.hidden);
    if (headerRow.dataset.load && !kids.hidden && !kids.dataset.loaded) {
      kids.dataset.loaded = "1";
      loadSubject(headerRow.dataset.load, kids,
                  +headerRow.style.getPropertyValue("--depth"));
    }
  };
  parentEl.appendChild(headerRow);
  parentEl.appendChild(kids);
  return kids;
}

async function loadSubject(syllabus, container, base) {
  container.innerHTML = '<p class="hint" style="padding:6px 0 6px 34px">Loading…</p>';
  let tree = state.trees[syllabus];
  if (!tree) {
    tree = await get(`/api/library/tree?syllabus=${syllabus}`);
    state.trees[syllabus] = tree;
  }
  container.innerHTML = "";

  // Mirrors the archive on disk: past papers / year / session / files.
  const ppRow = row({ depth: base + 1, icon: "📂", label: "past papers",
                      folder: true });
  const ppKids = group(container, ppRow);

  for (const y of tree.years) {
    const yRow = row({ depth: base + 2, icon: "📂", label: String(y.year),
                       count: y.count, folder: true });
    const yKids = group(ppKids, yRow);

    for (const s of y.sessions) {
      const sRow = row({ depth: base + 3, icon: "📂", label: s.name,
                         count: s.files.length, folder: true });
      const sKids = group(yKids, sRow);

      for (const f of s.files) {
        const fRow = row({
          depth: base + 4, icon: "📄",
          label: f.filename.replace(/\.pdf$/i, ""),
          tag: f.kind,
          onClick: () => selectFile(syllabus, y.year, s, f),
        });
        fRow.dataset.fileId = f.id;
        sKids.appendChild(fRow);
      }
    }
  }
  ppRow.click();                       // open "past papers" straight away
  if (ppKids.firstChild) ppKids.firstChild.click();   // and the newest year
}

async function buildTree() {
  const { boards } = await get("/api/library");
  const tree = $("#tree");
  tree.innerHTML = "";
  const want = new URLSearchParams(location.search).get("syllabus");
  let target = null, targetBoard = null;

  for (const b of boards) {
    const bRow = row({ depth: 0, icon: "🎓", label: b.board, count: b.count,
                       folder: true });
    const bKids = group(tree, bRow);

    for (const s of b.subjects) {
      const sRow = row({ depth: 1, icon: "📁",
                         label: `${s.subject} — ${s.syllabus}`,
                         count: s.count, folder: true });
      sRow.dataset.load = s.syllabus;
      group(bKids, sRow);
      if (s.syllabus === want) { target = sRow; targetBoard = bRow; }
    }
  }

  // Deep link opens its board and subject; otherwise just show the boards.
  if (target) { targetBoard.click(); target.click(); }
}

/* ---------- viewer ------------------------------------------------------ */

function selectFile(syllabus, year, session, file) {
  // Pair the clicked file with its opposite number so both load together.
  const sibling = session.files.find(
    (f) => f.code === file.code && f.kind !== file.kind);
  const qp = file.kind === "qp" ? file : sibling;
  const ms = file.kind === "ms" ? file : sibling;

  state.syllabus = syllabus;
  state.selected = { year, session: session.name, code: file.code, qp, ms };

  document.querySelectorAll(".tree-file").forEach((el) =>
    el.classList.toggle("on",
      el.dataset.fileId === String(qp?.id) || el.dataset.fileId === String(ms?.id)));

  render();
}

function paneHTML(kind, file, label) {
  if (!file) {
    return `<div class="pane ${kind}">
      <div class="pane-head"><b>${label}</b></div>
      <p class="pane-missing">Not in the archive for this paper.</p></div>`;
  }
  return `<div class="pane ${kind}">
    <div class="pane-head">
      <b>${label}</b><span class="file">${file.filename}</span>
    </div>
    <iframe class="lib-frame" title="${label}"
            src="/api/library/pdf/${file.id}#view=FitH"></iframe>
  </div>`;
}

function render() {
  const s = state.selected;
  if (!s) return;
  $("#lib-empty").hidden = true;
  $("#panes").hidden = false;
  $("#lib-layout").hidden = false;
  const fsBtn = $("#lib-fullscreen-btn");
  if (fsBtn) fsBtn.hidden = false;

  $("#lib-title").textContent =
    `${state.syllabus}/${s.code} · ${s.session} ${s.year}`;
  $("#lib-sub").textContent = s.qp && s.ms
    ? "Question paper and mark scheme"
    : (s.qp ? "Question paper only" : "Mark scheme only");

  $("#panes").className = "lib-panes " + state.layout;
  $("#panes").innerHTML =
    paneHTML("qp", s.qp, "Question paper") + paneHTML("ms", s.ms, "Mark scheme");

  const dl = $("#lib-download");
  const openBtn = $("#lib-open");
  const primary = s.qp || s.ms;
  dl.hidden = !primary;
  openBtn.hidden = !primary;
  if (primary) {
    dl.href = `/api/library/pdf/${primary.id}`;
    dl.setAttribute("download", primary.filename);
    openBtn.href = `/api/library/pdf/${primary.id}`;
  }
}

document.querySelectorAll("#lib-layout button").forEach((b) => {
  b.onclick = () => {
    state.layout = b.dataset.layout;
    document.querySelectorAll("#lib-layout button").forEach((x) =>
      x.classList.toggle("on", x === b));
    render();
  };
});

const fsBtn = $("#lib-fullscreen-btn");
if (fsBtn) {
  fsBtn.onclick = () => {
    const viewer = $(".lib-viewer");
    const isFs = viewer.classList.toggle("lib-fullscreen-active");
    fsBtn.innerHTML = isFs ? "✕ Exit Fullscreen" : "⛶ Fullscreen";
  };
}

  buildTree().catch((err) => {
    $("#lib-empty").innerHTML =
      `<span>⚠️</span><b>Archive unavailable</b><p>${err.message}</p>`;
  });
})();
