// The shared folder: one per student per subject. Everything the teacher and
// the student work on together - booklets, mock tests, whiteboards, homework,
// classes, notes, links - with where it's at (to do / in progress / done /
// marked). The student sees the same list on their side.

import { $, $$, api, esc, icon, pill, rel, fmtDate, modal, toast, confirmBox, debounce, emptyState,
         loadingHtml } from "/admin/core.js";
import { setHomework } from "/admin/sections/homework.js";

export const KIND_ICONS = { booklet: "book", test: "clipboard-check", board: "chalkboard", homework: "notebook",
  class: "calendar-event", report: "report", file: "paperclip", note: "note", link: "link" };
export const KIND_LABELS = { booklet: "Topical booklet", test: "Mock test", board: "Whiteboard", homework: "Homework",
  class: "Class", report: "Report", file: "File", note: "Note", link: "Link" };
export const STATUS = { todo: ["To do", ""], in_progress: ["In progress", "warn"], done: ["Done - to mark", "info"],
  marked: ["Marked", "ok"] };
const COLS = ["todo", "in_progress", "done", "marked"];
let closeWired = false;

export async function renderFolder(box, student, syl, onChange = () => {}) {
  box.innerHTML = loadingHtml("Opening the folder…");
  let d;
  try { d = await api(`/api/teach/students/${encodeURIComponent(student.id)}/folder?syllabus=${encodeURIComponent(syl)}`); }
  catch (ex) { box.innerHTML = emptyState("alert-triangle", "Couldn't open the folder.", ex.message); return; }
  const state = { kind: "", q: "" };
  const reload = () => renderFolder(box, student, syl, onChange);
  box.innerHTML = `
    <div class="row folder-bar">
      <div class="new-menu">
        <button class="btn primary" data-new aria-haspopup="true" aria-expanded="false">${icon("plus")} New</button>
        <div class="menu" data-menu hidden role="menu">
          ${[["booklet", "book", "Topical booklet", "Past-paper questions on chosen chapters"],
             ["test", "clipboard-check", "Mock test", "Timed, mark scheme after they finish"],
             ["board", "chalkboard", "Whiteboard", "Teach on it together, live"],
             ["homework", "notebook", "Homework", "Instructions, files, notes, a paper"],
             ["note", "note", "Note for the student", "Shows in their folder"],
             ["link", "link", "Link", "A video, a website, a resource"]].map(([k, ic, l, s]) =>
            `<button type="button" class="menu-item" role="menuitem" data-make="${k}">${icon(ic)}<span><b>${l}</b><small>${s}</small></span></button>`).join("")}
        </div>
      </div>
      <input class="input folder-q" placeholder="Search this folder" aria-label="Search this folder">
      <select class="select folder-kind" aria-label="Kind"><option value="">Everything</option>
        ${Object.entries(KIND_LABELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <span class="grow"></span>
      <span class="small muted">${[["todo", "to do"], ["in_progress", "in progress"], ["done", "to mark"], ["marked", "marked"]]
        .map(([k, l]) => `${d.counts[k] || 0} ${l}`).join(" · ")}</span>
    </div>
    <div class="folder-cols" data-cols></div>`;
  const draw = () => {
    const q = state.q.toLowerCase();
    const items = d.items.filter(i => (!state.kind || i.kind === state.kind)
      && (!q || `${i.title} ${(i.chapters || []).join(" ")}`.toLowerCase().includes(q)));
    $("[data-cols]", box).innerHTML = COLS.map(s => {
      const list = items.filter(i => i.status === s);
      return `<section class="folder-col"><h3>${esc(STATUS[s][0])} <span class="n">${list.length}</span></h3>
        ${list.length ? list.map(itemHtml).join("") : `<p class="small faint">Nothing here.</p>`}</section>`;
    }).join("");
  };
  draw();

  const menu = $("[data-menu]", box), newBtn = $("[data-new]", box);
  newBtn.addEventListener("click", () => { menu.hidden = !menu.hidden; newBtn.setAttribute("aria-expanded", String(!menu.hidden)); });
  if (!closeWired) {                       // one listener for the page, not one per render
    closeWired = true;
    document.addEventListener("click", e => {
      if (e.target.closest(".new-menu")) return;
      $$(".new-menu [data-menu]").forEach(mm => { mm.hidden = true; });
      $$(".new-menu [data-new]").forEach(bb => bb.setAttribute("aria-expanded", "false"));
    });
  }
  $$("[data-make]", box).forEach(b => b.addEventListener("click", async () => {
    menu.hidden = true;
    const k = b.dataset.make;
    let done = false;
    if (k === "booklet" || k === "test") done = await buildPaper(student, syl, k);
    else if (k === "board") done = await newBoard(student, syl);
    else if (k === "homework") done = await setHomework([{ id: student.id, name: student.name, email: student.email }]);
    else done = await noteOrLink(student, syl, k);
    if (done) { onChange(); reload(); }
  }));
  $(".folder-q", box).addEventListener("input", debounce(e => { state.q = e.target.value.trim(); draw(); }, 150));
  $(".folder-kind", box).addEventListener("change", e => { state.kind = e.target.value; draw(); });
  $("[data-cols]", box).addEventListener("change", async e => {
    const sel = e.target.closest("[data-status]");
    if (!sel) return;
    try { await api(`/api/teach/folder/${sel.dataset.status}`, { method: "PATCH", body: { status: sel.value } }); toast("Updated"); reload(); }
    catch (ex) { toast(ex.message, true); }
  });
  $("[data-cols]", box).addEventListener("click", async e => {
    const del = e.target.closest("[data-del]");
    if (!del) return;
    if (!(await confirmBox("Take out of the folder", "Take this out of the folder? The paper or board itself stays with the student.", "Take out", true))) return;
    try { await api(`/api/teach/folder/${del.dataset.del}`, { method: "DELETE" }); reload(); }
    catch (ex) { toast(ex.message, true); }
  });
}

function itemHtml(i) {
  const virtual = i.meta?.virtual;
  const fb = (i.fb || []).find(f => f.question_id == null);
  return `<article class="fi fi-${esc(i.kind)}">
    <div class="fi-head">${icon(KIND_ICONS[i.kind] || "file")}<span class="small faint">${esc(KIND_LABELS[i.kind] || i.kind)}</span>
      <span class="grow"></span>${i.due_at ? `<span class="small ${new Date(i.due_at) < new Date() && i.status !== "marked" ? "tone-bad" : "faint"}">due ${esc(fmtDate(i.due_at))}</span>` : ""}</div>
    ${i.url ? `<a class="fi-title" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>` : `<b class="fi-title">${esc(i.title)}</b>`}
    ${i.meta?.body ? `<p class="small muted fi-body">${esc(i.meta.body)}</p>` : ""}
    ${(i.chapters || []).length ? `<div class="chips">${i.chapters.map(c => `<span class="chip sm">${esc(c)}</span>`).join("")}</div>` : ""}
    <div class="small faint">${i.student_opened_at ? `opened ${esc(rel(i.student_opened_at))}` : "not opened yet"}
      ${i.student_done_at ? ` · finished ${esc(rel(i.student_done_at))}` : ""}</div>
    ${fb ? `<div class="small">${fb.marks != null ? `<b>${esc(fb.marks)}${fb.max_marks ? ` / ${esc(fb.max_marks)}` : ""}</b> ` : ""}${esc(fb.comment || "")}</div>` : ""}
    <div class="row fi-foot">
      ${i.url ? `<a class="btn sm" href="${esc(i.url)}" target="_blank" rel="noopener">${icon("external-link")} Open</a>` : ""}
      ${virtual ? pill(STATUS[i.status][0], STATUS[i.status][1]) : `
        <label class="sr-only" for="st-${esc(i.id)}">Status</label>
        <select class="select sm" id="st-${esc(i.id)}" data-status="${esc(i.id)}">${COLS.map(s =>
          `<option value="${s}"${s === i.status ? " selected" : ""}>${esc(STATUS[s][0])}</option>`).join("")}</select>
        <button class="btn sm icon ghost" data-del="${esc(i.id)}" aria-label="Take out of the folder">${icon("trash")}</button>`}
    </div></article>`;
}

/* ── building a booklet / mock test for the student ──────────────────── */

async function buildPaper(student, syl, kind) {
  let tree;
  try { tree = await api(`/api/topical/${encodeURIComponent(syl)}/tree`); }
  catch (ex) { toast(ex.message, true); return false; }
  const picked = new Set();
  const year = new Date().getFullYear();
  const comps = tree.components || [];
  return modal({
    title: kind === "test" ? `Mock test for ${student.name}` : `Topical booklet for ${student.name}`,
    submit: "Build it", size: "lg",
    body: `
      <p class="small muted">It is built for ${esc(student.name)} and goes in their folder. You both write on it and see each
        other's ink. It doesn't use their monthly allowance.</p>
      <div class="field"><span>Chapters (up to ${tree.max_chapters || 4})</span>
        <input class="input" data-ch-q placeholder="Filter chapters">
        <div class="chips chapter-chips" data-ch>${tree.chapters.filter(c => c.count).map(c =>
          `<label class="chip"><input type="checkbox" value="${esc(c.name)}">${esc(c.display)} <span class="faint">${c.count}</span></label>`).join("")}</div></div>
      ${comps.length > 1 ? `<div class="field"><span>Papers</span><div class="chips" data-comp>${comps.map(c =>
        `<label class="chip on"><input type="checkbox" checked value="${c.paper}">${esc(c.label)}</label>`).join("")}</div></div>` : ""}
      <div class="row">
        <label class="field narrow"><span>Questions</span><input class="input" type="number" min="1" max="${tree.max_questions || 60}" name="n" value="${kind === "test" ? 10 : 15}"></label>
        <label class="field narrow"><span>From year</span><input class="input" type="number" name="y1" min="${tree.year_min}" max="${tree.year_max}" value="${Math.max(tree.year_min, year - 6)}"></label>
        <label class="field narrow"><span>To year</span><input class="input" type="number" name="y2" min="${tree.year_min}" max="${tree.year_max}" value="${tree.year_max}"></label>
        <label class="field narrow"><span>Due (optional)</span><input class="input" type="date" name="due"></label>
      </div>
      ${kind === "test" ? `<label class="field"><span>Mark scheme</span><select class="select" name="ms">
          <option value="after_finish">Opens when they press Finish</option>
          <option value="teacher_only">I keep it - we go through it together</option>
          <option value="now">Open straight away</option></select></label>` : ""}
      <label class="check"><input type="checkbox" name="hw"> Also set it as homework (they get an email and it shows on their homework page)</label>
      <span class="small" data-pool></span>`,
    onMount: m => {
      const count = debounce(async () => {
        const out = $("[data-pool]", m);
        if (!picked.size) { out.textContent = ""; return; }
        try {
          const r = await api("/api/booklets/count", { method: "POST", body: sel(m) });
          out.textContent = `${r.pool} matching questions (${r.marks} marks) - the paper takes ${Math.min(r.pool, +$("[name=n]", m).value || 10)}.`;
          out.className = r.pool ? "small muted" : "small tone-bad";
        } catch (ex) { out.textContent = ex.message; out.className = "small tone-bad"; }
      }, 300);
      $("[data-ch]", m).addEventListener("change", e => {
        if (e.target.checked && picked.size >= (tree.max_chapters || 4)) {
          e.target.checked = false; toast(`At most ${tree.max_chapters || 4} chapters`, true); return;
        }
        e.target.checked ? picked.add(e.target.value) : picked.delete(e.target.value);
        e.target.closest(".chip").classList.toggle("on", e.target.checked);
        count();
      });
      $("[data-comp]", m)?.addEventListener("change", e => { e.target.closest(".chip").classList.toggle("on", e.target.checked); count(); });
      $("[data-ch-q]", m).addEventListener("input", e => {
        const q = e.target.value.trim().toLowerCase();
        $$("[data-ch] .chip", m).forEach(c => { c.hidden = !!q && !c.textContent.toLowerCase().includes(q); });
      });
      ["n", "y1", "y2"].forEach(n => $(`[name=${n}]`, m).addEventListener("input", count));
    },
    run: async m => {
      if (!picked.size) return "Pick at least one chapter.";
      const body = { ...sel(m), due_date: $("[name=due]", m).value || null };
      if (kind === "test") body.ms_policy = $("[name=ms]", m).value;
      const b = await api(`/api/teach/students/${encodeURIComponent(student.id)}/booklets`, { method: "POST", body });
      if ($("[name=hw]", m).checked) {
        await api(`/api/teach/students/${encodeURIComponent(student.id)}/assignments`, { method: "POST", body: {
          title: b.title, kind: kind === "test" ? "test" : "practice", syllabus: syl, due_date: body.due_date,
          attachments: [{ type: "paper", booklet_id: b.id, name: b.title }] } });
      }
      toast(`Building "${b.title}" - it's in ${student.name}'s folder`);
      return true;
    },
  });

  function sel(m) {
    const papers = $$("[data-comp] input:checked", m).map(i => +i.value);
    return { syllabus: syl, kind, picks: [...picked].map(c => ({ chapter: c })),
             year_from: +$("[name=y1]", m).value || tree.year_min, year_to: +$("[name=y2]", m).value || tree.year_max,
             max_questions: Math.max(1, Math.min(tree.max_questions || 60, +$("[name=n]", m).value || 10)),
             ...(comps.length > 1 && papers.length && papers.length < comps.length ? { papers } : {}) };
  }
}

/* ── whiteboard ──────────────────────────────────────────────────────── */

const TEMPLATES = [["squared", "Maths squared"], ["blank", "Blank"], ["lined", "Lined"], ["graph", "Graph paper"],
                   ["axes", "Graph with axes"], ["dotted", "Dotted"], ["construction", "Construction sheet"]];

async function newBoard(student, syl) {
  return modal({
    title: `Whiteboard with ${student.name}`, submit: "Create and open",
    body: `<p class="small muted">The board belongs to ${esc(student.name)}; you can both draw on it at the same time and
        see each other within a second or two. It doesn't count towards their free boards.</p>
      <label class="field"><span>Name</span><input class="input" name="t" placeholder="Lesson ${esc(new Date().toLocaleDateString())}" autofocus></label>
      <label class="field"><span>Paper</span><select class="select" name="tpl">${TEMPLATES.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>`,
    run: async m => {
      const r = await api(`/api/teach/students/${encodeURIComponent(student.id)}/boards`, { method: "POST",
        body: { syllabus: syl, title: $("[name=t]", m).value.trim(), template: $("[name=tpl]", m).value } });
      window.open(r.board.url, "_blank", "noopener");
      return true;
    },
  });
}

/* ── note / link ─────────────────────────────────────────────────────── */

async function noteOrLink(student, syl, kind) {
  return modal({
    title: kind === "link" ? "Add a link" : "Note for the student", submit: "Add to folder",
    body: `<label class="field"><span>Title</span><input class="input" name="t" required autofocus
        placeholder="${kind === "link" ? "Video: completing the square" : "Before Thursday"}"></label>
      ${kind === "link" ? `<label class="field"><span>Link</span><input class="input" name="u" type="url" placeholder="https://"></label>` : ""}
      <label class="field"><span>${kind === "link" ? "Why it's useful (optional)" : "Note"}</span><textarea class="textarea" name="b"></textarea></label>
      <label class="field narrow"><span>Due (optional)</span><input class="input" type="date" name="due"></label>`,
    run: async m => {
      await api(`/api/teach/students/${encodeURIComponent(student.id)}/folder`, { method: "POST", body: {
        syllabus: syl, kind, title: $("[name=t]", m).value.trim(), body: $("[name=b]", m).value.trim() || null,
        url: $("[name=u]", m)?.value.trim() || null, due_at: $("[name=due]", m).value || null } });
      toast("Added to the folder");
      return true;
    },
  });
}
