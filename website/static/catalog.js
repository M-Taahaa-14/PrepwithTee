/* catalog.js — behaviour for the server-rendered /papers pages.
 *   - "Enrol free" buttons (one click, then the page re-renders personalised)
 *   - the "Which boards are you studying?" modal: shown automatically to a
 *     signed-in student with no saved boards, and from "Edit my boards".
 * Page state is embedded by catalog.py as JSON in #cat-state.
 */
import { api } from "/auth.js?v=20260927k";

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
