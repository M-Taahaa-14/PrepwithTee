/* PrepWithTee — Reminders + Sticky Notes widgets.
 * Data persisted in localStorage; no server round-trip needed.
 */

// ── Reminders ────────────────────────────────────────────────────────────────

const REMINDERS_KEY = "pwt_reminders";

function loadReminders() {
  try { return JSON.parse(localStorage.getItem(REMINDERS_KEY) || "[]"); }
  catch { return []; }
}
function saveReminders(list) {
  try { localStorage.setItem(REMINDERS_KEY, JSON.stringify(list)); } catch {}
}

function formatDue(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((target - today) / 86400000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (diffDays < 0) return `Overdue · ${Math.abs(diffDays)}d ago, ${time}`;
  if (diffDays === 0) return `Today · ${time}`;
  if (diffDays === 1) return `Tomorrow · ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} · ${time}`;
}

function isOverdue(item) {
  if (item.done) return false;
  return item.datetime && new Date(item.datetime) < new Date();
}

export function initReminders(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  let showForm = false;

  function render() {
    const list = loadReminders().sort((a, b) =>
      new Date(a.datetime || "2099") - new Date(b.datetime || "2099")
    );

    const items = list.map(r => `
      <div class="reminder-item ${r.done ? "done" : ""} ${isOverdue(r) ? "overdue" : ""}"
           data-id="${r.id}">
        <input type="checkbox" class="reminder-check" ${r.done ? "checked" : ""}
               aria-label="Mark done">
        <div class="reminder-body">
          <div class="reminder-title">${escHtml(r.title)}</div>
          ${r.datetime ? `<div class="reminder-due">${formatDue(r.datetime)}</div>` : ""}
        </div>
        <button type="button" class="reminder-del" aria-label="Delete reminder">&times;</button>
      </div>`).join("");

    const form = showForm ? `
      <div class="reminder-form">
        <input type="text" class="reminder-input-title" placeholder="Reminder title…" maxlength="120">
        <input type="datetime-local" class="reminder-input-dt">
        <div class="reminder-form-btns">
          <button type="button" class="reminder-save">Add</button>
          <button type="button" class="reminder-cancel">Cancel</button>
        </div>
      </div>` : `
      <div class="reminder-add-row">
        <button type="button" class="reminder-add-btn">+ Add reminder</button>
      </div>`;

    container.innerHTML = `
      <div class="reminder-list">
        ${items || `<p class="reminder-empty">No reminders yet — add one below.</p>`}
      </div>
      ${form}`;

    // Events
    container.querySelectorAll(".reminder-check").forEach(cb => {
      cb.addEventListener("change", () => {
        const id = cb.closest("[data-id]").dataset.id;
        const all = loadReminders();
        const r = all.find(x => x.id === id);
        if (r) { r.done = cb.checked; saveReminders(all); render(); }
      });
    });
    container.querySelectorAll(".reminder-del").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.closest("[data-id]").dataset.id;
        saveReminders(loadReminders().filter(x => x.id !== id));
        render();
      });
    });

    const addBtn = container.querySelector(".reminder-add-btn");
    addBtn?.addEventListener("click", () => { showForm = true; render();
      container.querySelector(".reminder-input-title")?.focus(); });

    const saveBtn = container.querySelector(".reminder-save");
    saveBtn?.addEventListener("click", () => {
      const title = container.querySelector(".reminder-input-title")?.value.trim();
      if (!title) return;
      const dt = container.querySelector(".reminder-input-dt")?.value || "";
      const all = loadReminders();
      all.push({ id: crypto.randomUUID(), title, datetime: dt, done: false });
      saveReminders(all);
      showForm = false;
      render();
    });
    container.querySelector(".reminder-cancel")?.addEventListener("click", () => {
      showForm = false; render();
    });
    container.querySelector(".reminder-input-title")?.addEventListener("keydown", e => {
      if (e.key === "Enter") saveBtn?.click();
    });
  }

  render();
}

// ── Sticky Notes ─────────────────────────────────────────────────────────────

const NOTES_KEY = "pwt_sticky_notes";
const COLORS = ["#FFF9C4", "#B2DFDB", "#FFE0B2", "#F8BBD9"];

function loadNotes() {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) || "[]"); }
  catch { return []; }
}
function saveNotes(list) {
  try { localStorage.setItem(NOTES_KEY, JSON.stringify(list)); } catch {}
}

export function initStickyNotes(boardId) {
  const board = document.getElementById(boardId);
  if (!board) return;

  function render() {
    const notes = loadNotes();
    board.innerHTML = notes.map((n, i) => `
      <div class="sticky-note" data-id="${n.id}"
           style="background:${n.color};transform:rotate(${n.rot}deg)">
        <button type="button" class="sticky-del" aria-label="Delete note">&times;</button>
        <textarea class="sticky-input" maxlength="280"
                  placeholder="Jot something…">${escHtml(n.text)}</textarea>
      </div>`).join("");

    board.querySelectorAll(".sticky-del").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.closest("[data-id]").dataset.id;
        saveNotes(loadNotes().filter(n => n.id !== id));
        render();
      });
    });
    board.querySelectorAll(".sticky-input").forEach(ta => {
      ta.addEventListener("input", () => {
        const id = ta.closest("[data-id]").dataset.id;
        const all = loadNotes();
        const note = all.find(n => n.id === id);
        if (note) { note.text = ta.value; saveNotes(all); }
      });
      // Auto-height
      ta.style.height = "auto";
      ta.style.height = ta.scrollHeight + "px";
      ta.addEventListener("input", () => {
        ta.style.height = "auto";
        ta.style.height = ta.scrollHeight + "px";
      });
    });
  }

  function addNote() {
    const notes = loadNotes();
    const color = COLORS[notes.length % COLORS.length];
    const rot = (Math.random() * 4 - 2).toFixed(1);
    notes.push({ id: crypto.randomUUID(), text: "", color, rot: parseFloat(rot) });
    saveNotes(notes);
    render();
    // Focus the new note's textarea
    const inputs = board.querySelectorAll(".sticky-input");
    inputs[inputs.length - 1]?.focus();
  }

  board.dataset.addNote = "";
  render();

  // The add button is outside the board; wire it via a data attribute on the card.
  document.querySelector("[data-sticky-add]")?.addEventListener("click", addNote);
}

// ── Utility ──────────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
                  .replace(/"/g,"&quot;");
}
