/* catalog.js — behaviour for the server-rendered /papers pages.
 *   - "Enrol free" buttons (one click, then the page re-renders personalised)
 *   - the "Which boards are you studying?" modal: shown automatically to a
 *     signed-in student with no saved boards, and from "Edit my boards".
 * Page state is embedded by catalog.py as JSON in #cat-state.
 */
import { api } from "/auth.js?v=20260929a";

const state = JSON.parse(document.getElementById("cat-state")?.textContent || "{}");

// ── Enrol ──────────────────────────────────────────────────────────────────
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-enrol]");
  if (!btn) return;
  if (!state.signedIn) {
    location.href = `/login.html?signup=1&next=${encodeURIComponent(location.pathname)}`;
    return;
  }
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Enrolling…";
  try {
    await api("/api/enrollments", { method: "POST", body: { syllabus: btn.dataset.enrol } });
    location.reload();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = label;
    alertInline(btn, err.message || "Could not enrol. Try again.");
  }
});

function alertInline(near, msg) {
  let p = near.parentElement.querySelector(".cat-err");
  if (!p) {
    p = document.createElement("p");
    p.className = "cat-err";
    p.setAttribute("role", "alert");
    near.parentElement.appendChild(p);
  }
  p.textContent = msg;
}

// ── Boards modal ───────────────────────────────────────────────────────────
const BOARD_HINTS = {
  "o-level": "Physics 5054, Maths 4024, Chemistry, CS, Islamiyat, Pak Studies",
  "igcse": "Physics 0625, Maths 0580, Chemistry 0620, CS 0478",
  "a-level": "Maths 9709, Physics 9702, Computer Science 9618",
};

function openBoards({ required = false } = {}) {
  let modal = document.getElementById("cat-boards-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "cat-boards-modal";
    modal.className = "cat-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "cat-boards-title");
    const names = state.boardNames || {};
    modal.innerHTML = `
      <form class="cat-modal-card" novalidate>
        <h2 id="cat-boards-title">Which boards are you studying?</h2>
        <p>Pick every board you take subjects from. Your past papers, notes and progress
           are organised around them — you can change this any time.</p>
        <div class="cat-board-opts">
          ${Object.keys(names).map((b) => `
            <label class="cat-board-opt">
              <input type="checkbox" name="board" value="${b}" id="board-${b}"
                     ${(state.boards || []).includes(b) ? "checked" : ""}>
              <span><b>Cambridge ${names[b]}</b><small>${BOARD_HINTS[b] || ""}</small></span>
            </label>`).join("")}
        </div>
        <p class="cat-err" role="alert"></p>
        <div class="cat-modal-actions">
          ${required ? "" : '<button type="button" class="cat-btn cat-btn-ghost" data-close>Cancel</button>'}
          <button type="submit" class="cat-btn">Save boards</button>
        </div>
      </form>`;
    document.body.appendChild(modal);
    modal.querySelector("[data-close]")?.addEventListener("click", () => (modal.hidden = true));
    modal.querySelector("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const boards = [...modal.querySelectorAll("input[name=board]:checked")].map((i) => i.value);
      const err = modal.querySelector(".cat-err");
      if (!boards.length) { err.textContent = "Pick at least one board."; return; }
      const submit = modal.querySelector("button[type=submit]");
      submit.disabled = true;
      try {
        const res = await api("/api/me/boards", { method: "PUT", body: { boards } });
        // Land on the primary board unless we are already inside one they kept.
        const here = location.pathname.split("/")[2];
        location.href = boards.includes(here) ? location.pathname : `/papers/${res.primary}`;
      } catch (ex) {
        err.textContent = ex.message || "Could not save. Try again.";
        submit.disabled = false;
      }
    });
  }
  modal.hidden = false;
  modal.querySelector("input")?.focus();
}

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-open-boards]")) openBoards();
});
if (state.signedIn && state.needsBoards) openBoards({ required: true });

// ── Board + subject picker (ui.picker) ─────────────────────────────────────
// Board tabs filter the bands in place; the search box filters tiles by name
// or code across every board. "/" focuses the search. The chosen board is
// remembered per section (localStorage, best effort). Without JS every board
// simply shows - the markup is complete.
function initPicker(root) {
  const tabs = [...root.querySelectorAll("button.pk-tab[data-pk-board]")];
  const bands = [...root.querySelectorAll(".pk-board")];
  const input = root.querySelector("[data-pk-q]");
  const none = root.querySelector(".pk-none");
  const echo = root.querySelector("[data-pk-echo]");
  const key = "pk-board:" + location.pathname.split("/")[1];
  let board = "";
  try { board = localStorage.getItem(key) || ""; } catch (_) { /* private mode */ }
  if (board && !bands.some((b) => b.dataset.pkBoard === board)) board = "";
  if (location.hash && bands.some((b) => b.id === location.hash.slice(1))) board = location.hash.slice(1);

  function apply() {
    const q = (input?.value || "").trim().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    let shown = 0;
    for (const band of bands) {
      const onBoard = !board || q ? true : band.dataset.pkBoard === board;
      let n = 0;
      for (const t of band.querySelectorAll(".pk-tile")) {
        const hit = !words.length || words.every((w) => t.dataset.q.includes(w));
        t.hidden = !hit;
        if (hit) n++;
      }
      band.hidden = !onBoard || n === 0;
      if (!band.hidden) shown += n;
    }
    for (const t of tabs) {
      const on = (t.dataset.pkBoard || "") === board && !q;
      t.classList.toggle("is-on", on || (!q && !board && !t.dataset.pkBoard));
      t.setAttribute("aria-pressed", String(t.classList.contains("is-on")));
    }
    if (none) {
      none.hidden = shown > 0;
      if (echo) echo.textContent = `"${input?.value.trim() || ""}"`;
    }
  }

  tabs.forEach((t) => t.addEventListener("click", () => {
    board = t.dataset.pkBoard || "";
    if (input) input.value = "";
    try { localStorage.setItem(key, board); } catch (_) { /* ignore */ }
    apply();
  }));
  input?.addEventListener("input", apply);
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; apply(); input.blur(); }
    if (e.key === "Enter") {                      // open the only / first match
      const first = root.querySelector(".pk-tile:not([hidden]) .pk-link");
      if (first) location.href = first.href;
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const el = document.activeElement;
    if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
    if (!input || input.offsetParent === null) return;
    e.preventDefault();
    input.focus();
  });
  apply();
}
document.querySelectorAll("[data-pk]").forEach(initPicker);

// ── In-page search (ui.page_search) ─────────────────────────────────────────
// Filters a long list on the page (chapters, resource folders and files) as
// you type. Every word must match the item's data-q, or its text.
function initPageSearch(root) {
  const input = root.querySelector("[data-ps-q]");
  const count = root.querySelector("[data-ps-count]");
  const items = [...document.querySelectorAll(root.dataset.psItems)];
  const groupSel = root.dataset.psGroups;
  if (!input || !items.length) { root.hidden = true; return; }
  const hay = items.map((el) => (el.dataset.q || el.textContent).toLowerCase());
  function apply() {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let shown = 0;
    items.forEach((el, i) => {
      const hit = !words.length || words.every((w) => hay[i].includes(w));
      el.hidden = !hit;
      if (hit) shown++;
    });
    if (groupSel) {
      const groups = new Set(items.map((el) => el.closest(groupSel)).filter(Boolean));
      groups.forEach((g) => { g.hidden = words.length > 0 && !g.querySelector(`${root.dataset.psItems}:not([hidden])`); });
    }
    count.textContent = words.length ? `${shown} of ${items.length}` : "";
  }
  input.addEventListener("input", apply);
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") { input.value = ""; apply(); } });
}
document.querySelectorAll("[data-ps]").forEach(initPageSearch);

// ── Board filter on "Your subjects" (/papers) ──────────────────────────────
document.querySelectorAll("[data-bf]").forEach((bar) => {
  const scope = bar.closest("section") || document;
  const rows = [...scope.querySelectorAll(".ui-mine[data-board]")];
  const key = "bf-board";
  function show(board) {
    rows.forEach((r) => { r.hidden = !!board && r.dataset.board !== board; });
    bar.querySelectorAll("[data-bf-board]").forEach((b) => {
      const on = (b.dataset.bfBoard || "") === board;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", String(on));
    });
    try { localStorage.setItem(key, board); } catch (_) { /* ignore */ }
  }
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("[data-bf-board]");
    if (b) show(b.dataset.bfBoard || "");
  });
  let saved = "";
  try { saved = localStorage.getItem(key) || ""; } catch (_) { /* ignore */ }
  if (saved && bar.querySelector(`[data-bf-board="${saved}"]`)) show(saved);
});
