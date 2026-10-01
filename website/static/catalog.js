/* catalog.js — behaviour for the server-rendered /papers pages.
 *   - "Enrol free" buttons (one click, then the page re-renders personalised)
 *   - the "Which boards are you studying?" modal: shown automatically to a
 *     signed-in student with no saved boards, and from "Edit my boards".
 * Page state is embedded by catalog.py as JSON in #cat-state.
 */
import { api } from "/auth.js?v=20260929a";
import { enrol, gateOnLoad } from "/profile-gate.js?v=20260928c";

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
    // Asks for name / WhatsApp / board first when the profile is unfinished.
    if (!(await enrol(btn.dataset.enrol, { subjectName: btn.dataset.enrolName || "" }))) {
      btn.disabled = false;
      btn.textContent = label;
      return;
    }
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
// Unfinished profile (no WhatsApp / board yet): the full required form first
// (profile-gate.gateOnLoad, shared with the header hook); otherwise just boards.
if (state.signedIn) {
  gateOnLoad().then((ok) => { if (ok && state.needsBoards) openBoards({ required: true }); });
}

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
// "Newton's 2nd-law" and "newtons 2nd law" are the same search.
const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
  .toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, " ").trim();

function initPageSearch(root) {
  const input = root.querySelector("[data-ps-q]");
  const count = root.querySelector("[data-ps-count]");
  const items = [...document.querySelectorAll(root.dataset.psItems)];
  const groupSel = root.dataset.psGroups;
  const deep = root.hasAttribute("data-ps-deep");
  const results = deep ? root.nextElementSibling : null;          // ui.page_search puts it right after
  const rows = results ? [...results.querySelectorAll("li")] : [];
  if (!input || (!items.length && !rows.length)) { root.hidden = true; return; }
  const hay = items.map((el) => norm(el.dataset.q || el.textContent));
  const rowHay = rows.map((li) => ({ q: norm(li.dataset.q), t: norm(li.dataset.t), title: li.dataset.t }));
  const list = results?.querySelector("ol");
  const browse = [...document.querySelectorAll("[data-ps-browse]")];

  // Title matches first (whole title, then start of title, then a word start),
  // then matches only in the folder path; shorter paths win ties.
  const score = (r, words, phrase) => {
    let s = 0;
    if (r.t === phrase) s += 100;
    else if (r.t.startsWith(phrase)) s += 60;
    else if (r.t.includes(phrase)) s += 40;
    for (const w of words) {
      if (new RegExp(`(^| )${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(r.t)) s += 10;
      else if (r.t.includes(w)) s += 5;
    }
    return s - r.q.length / 1000;
  };

  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function mark(title, words) {
    if (!words.length) return esc(title);
    const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
    return esc(title).replace(re, "<mark>$1</mark>");
  }

  function apply() {
    const phrase = norm(input.value);
    const words = phrase.split(" ").filter(Boolean);
    if (deep) {
      const on = words.length > 0;
      browse.forEach((b) => { b.hidden = on; });
      results.hidden = !on;
      if (!on) { count.textContent = ""; return remember(""); }
      const hits = [];
      rows.forEach((li, i) => {
        const hit = words.every((w) => rowHay[i].q.includes(w));
        li.hidden = !hit;
        if (hit) hits.push([score(rowHay[i], words, phrase), li, i]);
      });
      hits.sort((a, b) => b[0] - a[0]);
      hits.forEach(([, li, i]) => {
        li.querySelector("b").innerHTML = mark(rowHay[i].title, words);
        list.appendChild(li);                                     // re-order: best first
      });
      results.querySelector(".ps-empty").hidden = hits.length > 0;
      count.textContent = `${hits.length} result${hits.length === 1 ? "" : "s"}`;
      return remember(input.value);
    }
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
    remember(input.value);
  }

  // The search lives in the address bar (?q=), so Back from a file comes back
  // to the same results. replaceState: typing does not fill the history.
  let saveT = null;
  function remember(v) {
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      const u = new URL(location.href);
      if (v.trim()) u.searchParams.set("q", v.trim()); else u.searchParams.delete("q");
      history.replaceState(history.state, "", u);
    }, 300);
  }

  const visibleLinks = () => (results ? [...results.querySelectorAll("li:not([hidden]) a")] : []);

  input.addEventListener("input", apply);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; apply(); }
    if (!deep) return;
    if (e.key === "Enter") {                       // open the best match
      const first = visibleLinks()[0];
      if (first) { e.preventDefault(); first.click(); }
    }
    if (e.key === "ArrowDown") {
      const first = visibleLinks()[0];
      if (first) { e.preventDefault(); first.focus(); }
    }
  });
  results?.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Escape") return;
    e.preventDefault();
    if (e.key === "Escape") return input.focus();
    const links = visibleLinks();
    const i = links.indexOf(document.activeElement);
    if (e.key === "ArrowUp" && i <= 0) return input.focus();
    links[Math.min(links.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  });
  const start = new URLSearchParams(location.search).get("q");
  if (start) { input.value = start; apply(); }
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
