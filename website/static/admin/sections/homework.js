import { $, $$, api, esc, icon, pill, rel, fmtDate, modal, toast, drawer, confirmBox, download,
         lookup, debounce, avatar, API_BASE } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Homework";

const KINDS = { homework: "Homework", reading: "Reading", practice: "Practice", test: "Test" };

/** Where an assignment stands, for the filter and the pill. */
export function stateOf(a) {
  if (a.status === "done") return "done";
  if (a.submissions?.length) return "handed_in";
  if (a.due_date && a.due_date < new Date().toISOString().slice(0, 10)) return "overdue";
  return "open";
}
export const STATES = { handed_in: ["Handed in - mark it", "info"], overdue: ["Overdue", "bad"], open: ["Open", "warn"], done: ["Done", "ok"] };

export async function render(el, { params, setParams }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Homework</h1>
      <p>Everything set, across every student. Handed-in work waiting on you comes first.</p></div>
      <button class="btn primary" data-new>${icon("plus")} Set homework</button></div>
    <div id="hw"></div>`;
  const { q = "", sort, dir, page, per, ...filters } = params;
  if (!("state" in filters) && !q) filters.state = "handed_in";
  const table = new DataTable($("#hw", el), {
    id: "homework", noun: "assignments", searchPlaceholder: "Search student or title", views: "homework",
    builtinViews: [{ name: "Handed in", params: { state: "handed_in" } }, { name: "Overdue", params: { state: "overdue" } },
                   { name: "Open", params: { state: "open" } }],
    state: { q, sort: sort || "due_date", dir: dir || "asc", page: +page || 1, per: +per || 50, filters },
    loadAll: loadRows,
    searchText: r => `${r.student_name} ${r.email || ""} ${r.title} ${r.syllabus || ""}`,
    onState: setParams,
    filters: [
      { key: "state", label: "Any state", value: stateOf,
        options: c => Object.keys(STATES).map(k => ({ value: k, label: STATES[k][0], count: c[k] || 0 })) },
      { key: "subject", label: "Every subject", value: r => r.syllabus || "" },
      { key: "kind", label: "Every kind", value: r => r.kind || "homework", label_for: v => KINDS[v] || v },
    ],
    columns: [
      { key: "student_name", label: "Student", sort: true, firstDir: "asc",
        render: r => `<div class="who">${avatar({ name: r.student_name, picture_url: r.picture_url })}<div>
          <a href="#/student/${esc(r.user_id)}"><b>${esc(r.student_name)}</b></a></div></div>` },
      { key: "title", label: "Assignment", sort: true, firstDir: "asc",
        render: r => `<b>${esc(r.title)}</b><div class="small faint">${esc(KINDS[r.kind] || "Homework")}${r.syllabus ? ` · ${esc(r.syllabus)}` : ""}</div>` },
      { key: "due_date", label: "Due", sort: true, firstDir: "asc", render: r => r.due_date ? `${esc(fmtDate(r.due_date))} <span class="small faint">${esc(rel(r.due_date))}</span>` : "—" },
      { key: "state", label: "State", sortValue: r => Object.keys(STATES).indexOf(stateOf(r)), sort: true, firstDir: "asc",
        render: r => pill(...STATES[stateOf(r)]) },
      { key: "submissions", label: "Files in", num: true, sortValue: r => r.submissions?.length || 0, sort: true,
        render: r => r.submissions?.length || `<span class="faint">0</span>` },
      { key: "created_at", label: "Set", sort: true, render: r => esc(rel(r.created_at)) },
    ],
    onOpen: r => openAssignment(r, () => table.reload(true)),
    bulk: [
      { label: "Mark done", icon: "check", run: rows => setStatus(rows, "done") },
      { label: "Reopen", icon: "rotate", run: rows => setStatus(rows, "assigned") },
      { label: "Delete", icon: "trash", run: async rows => {
        if (!(await confirmBox("Delete homework", `Delete ${rows.length} assignment${rows.length === 1 ? "" : "s"}? Students lose any files they handed in.`, "Delete", true))) return false;
        for (const r of rows) await api(`${API_BASE}/assignments/${r.id}`, { method: "DELETE" });
        toast("Deleted"); return true;
      } },
    ],
  });
  $("[data-new]", el).addEventListener("click", async () => { if (await setHomework()) table.reload(true); });
}

async function loadRows() {
  const d = await api(`${API_BASE}/homework`);
  return d.students.flatMap(s => s.assignments.map(a => ({ ...a, student_name: s.name, email: s.email, picture_url: s.picture_url })));
}

async function setStatus(rows, status) {
  for (const r of rows) await api(`${API_BASE}/assignments/${r.id}`, { method: "PATCH", body: { status } });
  toast(status === "done" ? "Marked done" : "Reopened");
  return true;
}

export function openAssignment(a, reload) {
  drawer({
    title: a.title,
    body: `
      <div class="row">${pill(...STATES[stateOf(a)])}<span class="small faint">for <a href="#/student/${esc(a.user_id)}">${esc(a.student_name)}</a></span></div>
      <dl class="kv"><dt>Kind</dt><dd>${esc(KINDS[a.kind] || "Homework")}</dd><dt>Subject</dt><dd>${esc(a.subject_name || a.syllabus || "—")}</dd>
        <dt>Due</dt><dd>${esc(a.due_date ? fmtDate(a.due_date) : "no date")}</dd><dt>Set</dt><dd>${esc(fmtDate(a.created_at))}</dd>
        ${a.topics?.length ? `<dt>Topics</dt><dd>${esc(a.topics.join(", "))}</dd>` : ""}
        ${a.student_note ? `<dt>Student's note</dt><dd>${esc(a.student_note)}</dd>` : ""}</dl>
      ${a.instructions ? `<div class="msg">${esc(a.instructions)}</div>` : ""}
      ${a.attachments?.length ? `<h3>Attached</h3>${a.attachments.map(f => f.type === "paper"
        ? `<a class="list-row link" href="/papers/view/${esc(f.booklet_id)}" target="_blank" rel="noopener">${icon("book")}
            <span class="grow">${esc(f.name || "Topical paper")}</span>${icon("external-link")}</a>`
        : `<div class="list-row">${icon(f.type === "resource" ? "file-text" : "paperclip")}
        <span class="grow">${esc(f.name || f.rel || "file")}</span></div>`).join("")}` : ""}
      <h3>Handed in (${a.submissions?.length || 0})</h3>
      ${(a.submissions || []).map(s => `<div class="list-row">${icon("file-upload")}<span class="grow">${esc(s.name)}
        <span class="small faint">${esc(rel(s.submitted_at))}</span></span>
        <button class="btn sm" data-dl="${s.idx}" data-name="${esc(s.name)}">${icon("download")} Download</button></div>`).join("")
        || `<p class="small muted">Nothing handed in yet.</p>`}
      <div class="row">
        <button class="btn primary" data-done>${a.status === "done" ? "Reopen" : "Mark done"}</button>
        <button class="btn" data-due>${icon("calendar")} Change due date</button>
        <button class="btn" data-remind>${icon("bell")} Remind student</button>
        <label class="btn">${icon("upload")} Attach a file<input type="file" hidden data-file></label>
        <span class="grow"></span><button class="btn danger" data-del>${icon("trash")}</button></div>`,
    onMount: (d, close) => {
      const done = () => { close(); reload(); };
      $$("[data-dl]", d).forEach(b => b.addEventListener("click", () =>
        download(`${API_BASE}/assignments/${a.id}/submission/${b.dataset.dl}`, b.dataset.name).catch(e => toast(e.message, true))));
      $("[data-done]", d).addEventListener("click", async () => {
        await api(`${API_BASE}/assignments/${a.id}`, { method: "PATCH", body: { status: a.status === "done" ? "assigned" : "done" } });
        toast("Updated"); done();
      });
      $("[data-due]", d).addEventListener("click", async () => {
        const ok = await modal({ title: "Change due date", submit: "Save",
          body: `<label class="field"><span>Due date</span><input class="input" type="date" name="due" value="${esc(a.due_date || "")}"></label>`,
          run: async m => { await api(`${API_BASE}/assignments/${a.id}`, { method: "PATCH", body: { due_date: $("[name=due]", m).value || null } }); return true; } });
        if (ok) { toast("Due date changed"); done(); }
      });
      $("[data-remind]", d).addEventListener("click", async () => {
        try { const r = await api(`${API_BASE}/students/${a.user_id}/remind`, { method: "POST" });
              toast(r.sent ? `Reminded about ${r.count} open item${r.count === 1 ? "" : "s"}` : "The reminder couldn't be sent", !r.sent); }
        catch (ex) { toast(ex.message, true); }
      });
      $("[data-file]", d).addEventListener("change", async e => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        const res = await fetch(`${API_BASE}/assignments/${a.id}/files`, { method: "POST", body: fd, credentials: "same-origin" });
        if (!res.ok) { toast((await res.json().catch(() => ({}))).detail || "Upload failed", true); return; }
        toast("File attached"); done();
      });
      $("[data-del]", d).addEventListener("click", async () => {
        if (!(await confirmBox("Delete homework", `Delete "${a.title}"?`, "Delete", true))) return;
        await api(`${API_BASE}/assignments/${a.id}`, { method: "DELETE" });
        toast("Deleted"); done();
      });
    },
  });
}

/** Set one piece of homework for one or more students. Exported for the student page.
 *  Attach: notes from Resources, files from this computer (checked here and on the
 *  server), and/or a topical paper the site builds for each student (opens in their
 *  own paper viewer, with the mark scheme and AI help). */
const UPLOAD_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt", ".csv",
                     ".xlsx", ".ppt", ".pptx", ".zip"];
const MAX_MB = 25;

export async function setHomework(preset = []) {
  const [subjects, resources] = await Promise.all([lookup("subjects"),
    api(`${API_BASE}/resources-flat`).then(d => d.files).catch(() => [])]);
  const picked = new Map(preset.map(s => [s.id, s]));
  const files = [];                 // File objects to upload after the assignment exists
  const res = new Map();            // rel -> resource
  const paper = { on: false, chapters: new Set(), tree: null };
  return modal({
    title: "Set homework", submit: "Set homework", size: "lg",
    body: `
      <div class="field"><span>Students</span><div class="chips" data-picked></div>
        <input class="input" data-find placeholder="Search a student by name or email to add" ${preset.length ? "" : "autofocus"}>
        <div class="pick-list" data-results hidden></div></div>
      <div class="row"><label class="field"><span>Title</span><input class="input" name="title" required ${preset.length ? "autofocus" : ""}
          placeholder="Indices worksheet + 10 past-paper questions"></label>
        <label class="field narrow"><span>Kind</span><select class="select" name="kind">${Object.entries(KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label></div>
      <div class="row"><label class="field"><span>Subject</span><select class="select" name="syllabus"><option value="">No subject</option>
          ${subjects.map(s => `<option value="${esc(s.code)}">${esc(s.name)} (${esc(s.code)})</option>`).join("")}</select></label>
        <label class="field narrow"><span>Due</span><input class="input" type="date" name="due"></label></div>
      <label class="field"><span>Instructions</span><textarea class="textarea" name="instructions"
        placeholder="Do questions 1-10 without a calculator, then mark them with the mark scheme."></textarea></label>

      <div class="section-box"><h3>${icon("file-text")} Notes from Resources</h3>
        <input class="input" data-res-find placeholder="Search notes and worksheets (e.g. binomial)">
        <div class="pick-list" data-res-results hidden></div><div class="chips" data-res-picked></div></div>

      <div class="section-box"><h3>${icon("upload")} Files from your computer</h3>
        <label class="drop" data-drop>${icon("cloud-upload")} Drop files here or click to choose
          <span class="small faint">PDF, images, Word, PowerPoint, Excel, text or zip - up to ${MAX_MB} MB each</span>
          <input type="file" multiple hidden data-files accept="${UPLOAD_EXTS.join(",")}"></label>
        <div class="file-list" data-file-list></div></div>

      <div class="section-box"><h3>${icon("book")} Topical paper built for each student</h3>
        <label class="check"><input type="checkbox" data-paper-on> Build a paper from past-paper questions</label>
        <div data-paper hidden class="stack">
          <p class="small muted">Pick the subject above, then the chapters. Each student gets their own copy in their papers, with the mark scheme - it doesn't use their monthly allowance.</p>
          <div class="chips chapter-chips" data-chapters><span class="small faint">Choose a subject first.</span></div>
          <div class="row"><label class="field narrow"><span>Questions</span><input class="input" type="number" min="1" max="60" value="12" name="pq"></label>
            <label class="field narrow"><span>From year</span><input class="input" type="number" name="py1" value="2018"></label>
            <label class="field narrow"><span>To year</span><input class="input" type="number" name="py2" value="${new Date().getFullYear()}"></label>
            <label class="field narrow"><span>Type</span><select class="select" name="pk"><option value="booklet">Practice booklet</option><option value="test">Mock test</option></select></label></div>
          <span class="small" data-pool></span>
        </div></div>

      <label class="check"><input type="checkbox" name="notify" checked> Email the student${preset.length > 1 ? "s" : ""}</label>`,
    onMount: m => {
      /* students */
      const drawPicked = () => {
        $("[data-picked]", m).innerHTML = [...picked.values()].map(s => `<span class="chip on">${esc(s.name || s.email)}
          <button type="button" class="btn ghost sm icon x" data-unpick="${esc(s.id)}" aria-label="Remove ${esc(s.name || "")}">${icon("x")}</button></span>`).join("")
          || `<span class="small faint">Nobody yet</span>`;
        $$("[data-unpick]", m).forEach(b => b.addEventListener("click", () => { picked.delete(b.dataset.unpick); drawPicked(); }));
      };
      drawPicked();
      const find = debounce(async q => {
        const box = $("[data-results]", m);
        if (q.length < 2) { box.hidden = true; return; }
        const { rows } = await api(`${API_BASE}/students/table?q=${encodeURIComponent(q)}&per=8&sort=name&dir=asc`);
        box.hidden = false;
        box.innerHTML = rows.map(r => `<button type="button" class="list-row link" data-pick="${esc(r.id)}">${avatar(r)}<span class="grow">${esc(r.name || r.email)}
          <span class="small faint">${esc(r.email)}</span></span>${icon("plus")}</button>`).join("") || `<p class="small muted">No match.</p>`;
        $$("[data-pick]", box).forEach(b => b.addEventListener("click", () => {
          const r = rows.find(x => x.id === b.dataset.pick); picked.set(r.id, r); drawPicked();
          $("[data-find]", m).value = ""; box.hidden = true;
        }));
      }, 250);
      $("[data-find]", m).addEventListener("input", e => find(e.target.value.trim()));

      /* resources */
      const drawRes = () => {
        $("[data-res-picked]", m).innerHTML = [...res.values()].map(f => `<span class="chip on">${icon("file-text")} ${esc(f.name)}
          <button type="button" class="btn ghost sm icon x" data-unres="${esc(f.rel)}" aria-label="Remove">${icon("x")}</button></span>`).join("");
        $$("[data-unres]", m).forEach(b => b.addEventListener("click", () => { res.delete(b.dataset.unres); drawRes(); }));
      };
      $("[data-res-find]", m).addEventListener("input", e => {
        const q = e.target.value.trim().toLowerCase();
        const box = $("[data-res-results]", m);
        const hits = q.length < 2 ? [] : resources.filter(f => f.rel.toLowerCase().includes(q)).slice(0, 30);
        box.hidden = !hits.length;
        box.innerHTML = hits.map(f => `<button type="button" class="list-row link" data-res="${esc(f.rel)}">${icon("file-text")}
          <span class="grow">${esc(f.name)} <span class="small faint">${esc(f.category)}</span></span>${icon("plus")}</button>`).join("");
        $$("[data-res]", box).forEach(b => b.addEventListener("click", () => {
          const f = resources.find(x => x.rel === b.dataset.res); res.set(f.rel, f); drawRes();
        }));
      });

      /* files from the computer */
      const drawFiles = () => {
        $("[data-file-list]", m).innerHTML = files.map((f, i) => `<div class="list-row">${icon("paperclip")}<span class="grow">${esc(f.name)}</span>
          <span class="small faint">${(f.size / 1048576).toFixed(1)} MB</span>
          <button type="button" class="btn ghost sm icon" data-unfile="${i}" aria-label="Remove ${esc(f.name)}">${icon("x")}</button></div>`).join("");
        $$("[data-unfile]", m).forEach(b => b.addEventListener("click", () => { files.splice(+b.dataset.unfile, 1); drawFiles(); }));
      };
      const add = list => {
        for (const f of list) {
          const ext = (f.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
          if (!UPLOAD_EXTS.includes(ext)) { toast(`${f.name}: ${ext || "that type"} isn't allowed`, true); continue; }
          if (f.size > MAX_MB * 1048576) { toast(`${f.name} is over ${MAX_MB} MB`, true); continue; }
          if (!f.size) { toast(`${f.name} is empty`, true); continue; }
          files.push(f);
        }
        drawFiles();
      };
      const drop = $("[data-drop]", m);
      $("[data-files]", m).addEventListener("change", e => { add(e.target.files); e.target.value = ""; });
      drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
      drop.addEventListener("dragleave", () => drop.classList.remove("over"));
      drop.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("over"); add(e.dataTransfer.files); });

      /* topical paper */
      const loadTree = async () => {
        const syl = $("[name=syllabus]", m).value, box = $("[data-chapters]", m);
        paper.chapters.clear(); paper.tree = null;
        if (!syl) { box.innerHTML = `<span class="small faint">Choose a subject first.</span>`; return; }
        box.innerHTML = `<span class="small faint">Loading chapters…</span>`;
        try {
          paper.tree = await api(`/api/topical/${encodeURIComponent(syl)}/tree`);
          box.innerHTML = paper.tree.chapters.filter(c => c.count).map(c =>
            `<label class="chip"><input type="checkbox" value="${esc(c.name)}">${esc(c.display)} <span class="faint">${c.count}</span></label>`).join("");
        } catch { box.innerHTML = `<span class="small tone-bad">No topical questions for this subject yet.</span>`; }
        countPool();
      };
      const countPool = debounce(async () => {
        const out = $("[data-pool]", m);
        if (!paper.on || !paper.chapters.size || !paper.tree) { out.textContent = ""; return; }
        try {
          const r = await api("/api/booklets/count", { method: "POST", body: paperSel(m, paper) });
          out.textContent = `${r.pool} matching questions (${r.marks} marks) - the paper takes ${Math.min(r.pool, +$("[name=pq]", m).value || 12)}.`;
          out.className = r.pool ? "small muted" : "small tone-bad";
        } catch (ex) { out.textContent = ex.message; out.className = "small tone-bad"; }
      }, 300);
      $("[data-paper-on]", m).addEventListener("change", e => {
        paper.on = e.target.checked; $("[data-paper]", m).hidden = !paper.on;
        if (paper.on && !paper.tree) loadTree();
      });
      $("[name=syllabus]", m).addEventListener("change", () => { if (paper.on) loadTree(); });
      $("[data-chapters]", m).addEventListener("change", e => {
        if (e.target.checked) {
          if (paper.chapters.size >= (paper.tree?.max_chapters || 4)) {
            e.target.checked = false; toast(`At most ${paper.tree?.max_chapters || 4} chapters per paper`, true); return;
          }
          paper.chapters.add(e.target.value);
        } else paper.chapters.delete(e.target.value);
        e.target.closest(".chip").classList.toggle("on", e.target.checked);
        countPool();
      });
      ["pq", "py1", "py2"].forEach(n => $(`[name=${n}]`, m).addEventListener("input", countPool));
    },
    run: async m => {
      const title = $("[name=title]", m).value.trim();
      if (!picked.size) return "Add at least one student.";
      if (!title) return "Give the homework a title.";
      const syllabus = $("[name=syllabus]", m).value || null;
      if (paper.on && (!syllabus || !paper.chapters.size)) return "For the topical paper, choose a subject and at least one chapter.";
      const base = { title, kind: $("[name=kind]", m).value, syllabus,
        due_date: $("[name=due]", m).value || null, instructions: $("[name=instructions]", m).value.trim() || null };
      const notify = $("[name=notify]", m).checked;
      const problems = [];
      for (const [id, s] of picked) {
        const attachments = [...res.values()].map(f => ({ type: "resource", rel: f.rel, name: f.name }));
        if (paper.on) {
          const b = await api(`${API_BASE}/students/${encodeURIComponent(id)}/booklets`, { method: "POST", body: paperSel(m, paper) });
          attachments.push({ type: "paper", booklet_id: b.id, name: b.title });
        }
        // Files go up after the assignment exists, so email the student only once they're attached.
        const { assignment } = await api(`${API_BASE}/students/${encodeURIComponent(id)}/assignments?notify=${notify && !files.length}`,
                                         { method: "POST", body: { ...base, attachments } });
        for (const f of files) {
          const fd = new FormData(); fd.append("file", f);
          const r = await fetch(`${API_BASE}/assignments/${assignment.id}/files`, { method: "POST", body: fd, credentials: "same-origin" });
          if (!r.ok) problems.push(`${f.name}: ${(await r.json().catch(() => ({}))).detail || r.status}`);
        }
        if (notify && files.length) await api(`${API_BASE}/students/${encodeURIComponent(id)}/remind`, { method: "POST" }).catch(() => {});
      }
      if (problems.length) toast(`Set, but some files were refused - ${problems.join("; ")}`, true);
      else toast(`Set for ${picked.size} student${picked.size === 1 ? "" : "s"}`);
      return true;
    },
  });
}

function paperSel(m, paper) {
  return { syllabus: $("[name=syllabus]", m).value, picks: [...paper.chapters].map(c => ({ chapter: c })),
           year_from: +$("[name=py1]", m).value || 2010, year_to: +$("[name=py2]", m).value || new Date().getFullYear(),
           max_questions: Math.max(1, Math.min(60, +$("[name=pq]", m).value || 12)), kind: $("[name=pk]", m).value };
}
