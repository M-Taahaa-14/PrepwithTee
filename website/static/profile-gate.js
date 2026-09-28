/* profile-gate.js — nobody enrols in a subject with an unfinished profile.
 *
 * The server refuses POST /api/enrollments (409 profile_incomplete /
 * board_not_chosen) until the student has a name, a WhatsApp number and at
 * least one board, and the subject's board is one of theirs. This module is
 * the matching pop-up: every "Enrol" button calls enrol(code), which opens the
 * "Finish your profile" form first when something is missing, saves it
 * (POST /api/me/setup) and then enrols.
 *
 *   enrol(syllabus)          -> true (enrolled) | false (they closed the form)
 *   ensureProfile({board})   -> true once complete | false if dismissed
 *   gateOnLoad()             -> required pop-up on every page (partials/nav.html)
 *                               for students with missing details, including
 *                               those who enrolled before the gate existed
 */

const BOARDS = [
  ["o-level", "Cambridge O Level", "Maths D 4024, Physics 5054, Chemistry 5070, CS 2210"],
  ["igcse", "Cambridge IGCSE", "Maths 0580, Physics 0625, Chemistry 0620, CS 0478"],
  ["a-level", "Cambridge AS & A Level", "Maths 9709, Physics 9702, CS 9618"],
];
const BOARD_OF = {
  "4024": "o-level", "5054": "o-level", "5070": "o-level", "2210": "o-level",
  "2058": "o-level", "2059": "o-level",
  "0580": "igcse", "0625": "igcse", "0620": "igcse", "0478": "igcse",
  "9709": "a-level", "9702": "a-level", "9618": "a-level",
};
const CODES = [
  ["+92", "Pakistan"], ["+971", "UAE"], ["+966", "Saudi Arabia"], ["+974", "Qatar"],
  ["+965", "Kuwait"], ["+968", "Oman"], ["+973", "Bahrain"], ["+44", "United Kingdom"],
  ["+1", "USA / Canada"], ["+91", "India"], ["+880", "Bangladesh"], ["+94", "Sri Lanka"],
  ["+977", "Nepal"], ["+93", "Afghanistan"], ["+98", "Iran"], ["+20", "Egypt"],
  ["+90", "Turkey"], ["+234", "Nigeria"], ["+233", "Ghana"], ["+254", "Kenya"],
  ["+255", "Tanzania"], ["+256", "Uganda"], ["+260", "Zambia"], ["+263", "Zimbabwe"],
  ["+267", "Botswana"], ["+27", "South Africa"], ["+230", "Mauritius"], ["+60", "Malaysia"],
  ["+65", "Singapore"], ["+62", "Indonesia"], ["+86", "China"], ["+852", "Hong Kong"],
  ["+61", "Australia"], ["+64", "New Zealand"], ["+49", "Germany"], ["+33", "France"],
  ["+353", "Ireland"], ["+31", "Netherlands"],
];

export const boardOf = (code) => BOARD_OF[code] || null;

async function call(path, method = "GET", body) {
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = data?.detail;
    const err = new Error((typeof d === "string" ? d : d?.message) || `Request failed (${res.status})`);
    err.status = res.status;
    err.detail = typeof d === "object" && d ? d : {};
    throw err;
  }
  return data;
}

export function getSetup() {
  return call("/api/me/setup");
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function splitPhone(phone) {
  const p = (phone || "").trim();
  const hit = [...CODES].sort((a, b) => b[0].length - a[0].length).find(([c]) => p.startsWith(c));
  return hit ? [hit[0], p.slice(hit[0].length).trim()] : ["+92", p.replace(/^\+/, "")];
}

function injectCss() {
  if (document.getElementById("pg-css")) return;
  const st = document.createElement("style");
  st.id = "pg-css";
  st.textContent = `
.pg-modal{position:fixed;inset:0;z-index:2147483100;display:grid;place-items:center;padding:16px;
  background:rgba(20,16,36,.55);backdrop-filter:blur(3px);overflow-y:auto}
.pg-card{width:min(520px,100%);background:var(--white,#fff);color:var(--ink,#1a1a2e);border-radius:22px;
  padding:26px 24px 22px;box-shadow:0 24px 60px rgba(0,0,0,.28);border:1px solid var(--line,#e8dfce)}
.pg-card h2{margin:0 0 .3rem;font:800 1.4rem/1.2 "Archivo",system-ui,sans-serif;color:var(--purple,#4c2e72)}
.pg-lead{margin:0 0 1rem;color:var(--grey,#5a5a72);line-height:1.5;font-size:.93rem}
.pg-why{margin:0 0 1rem;padding:.6rem .8rem;border-radius:12px;background:var(--yellow,#fbf2d2);
  color:var(--yellow-ink,#866312);font-size:.86rem;font-weight:600}
.pg-f{display:block;margin:0 0 .95rem}
.pg-f>span{display:block;font-weight:700;font-size:.85rem;margin:0 0 .35rem}
.pg-f>span i{font-style:normal;color:#c0392b}
.pg-in,.pg-sel{width:100%;box-sizing:border-box;padding:.65rem .75rem;border-radius:12px;font:inherit;
  border:1.5px solid var(--line,#e8dfce);background:var(--page,#fdf9f3);color:var(--ink,#1a1a2e)}
.pg-in:focus,.pg-sel:focus{outline:2px solid var(--accent,#4c2e72);outline-offset:1px}
.pg-phone{display:flex;gap:8px}.pg-phone .pg-sel{width:150px;flex-shrink:0}
.pg-hint{margin:.3rem 0 0;font-size:.76rem;color:var(--grey,#5a5a72)}
.pg-boards{display:grid;gap:8px}
.pg-b{display:flex;gap:.6rem;align-items:flex-start;padding:.6rem .75rem;border-radius:12px;cursor:pointer;
  border:1.5px solid var(--line,#e8dfce);background:var(--page,#fdf9f3)}
.pg-b:has(input:checked){border-color:var(--accent,#4c2e72);background:var(--accent-soft,#eee8f8)}
.pg-b input{margin-top:.2rem;accent-color:var(--accent,#4c2e72)}
.pg-b b{display:block;font-size:.92rem}.pg-b small{color:var(--grey,#5a5a72);font-size:.76rem}
.pg-b em{font-style:normal;font-size:.7rem;font-weight:800;color:var(--orange-ink,#b0541c);margin-left:.35rem}
.pg-err{min-height:1.1em;margin:.2rem 0 .6rem;color:#c0392b;font-weight:600;font-size:.85rem}
.pg-act{display:flex;justify-content:flex-end;gap:.5rem;flex-wrap:wrap}
.pg-btn{border:0;border-radius:999px;padding:.7rem 1.3rem;font:700 .92rem system-ui,sans-serif;cursor:pointer;
  background:var(--accent,#4c2e72);color:var(--on-accent,#fff)}
.pg-btn[disabled]{opacity:.6;cursor:wait}
.pg-ghost{background:transparent;color:var(--grey,#5a5a72);border:1.5px solid var(--line,#e8dfce)}
@media (max-width:480px){.pg-phone{flex-direction:column}.pg-phone .pg-sel{width:100%}}`;
  document.head.appendChild(st);
}

/**
 * Show the "Finish your profile" form. Resolves true after a successful save,
 * false when dismissed (never dismissible with required: true).
 */
export function openSetup({ state = {}, board = null, subjectName = "", required = false, reason = "" } = {}) {
  injectCss();
  document.getElementById("pg-modal")?.remove();
  const boards = new Set(state.boards || []);
  if (board) boards.add(board);
  const [code, number] = splitPhone(state.phone);
  const why = reason || (subjectName
    ? `Before you enrol in ${subjectName}, we need a few details.`
    : "");
  const boardName = BOARDS.find((b) => b[0] === board)?.[1] || "";
  const onlyBoard = !!(state.complete && board);
  const modal = document.createElement("div");
  modal.id = "pg-modal";
  modal.className = "pg-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "pg-title");
  modal.innerHTML = `
    <form class="pg-card" novalidate>
      <h2 id="pg-title">${onlyBoard ? `Add ${esc(boardName)} to your boards` : "Finish your profile"}</h2>
      <p class="pg-lead">${onlyBoard
        ? "This subject is on a board you haven't picked yet. Tick it below to enrol."
        : "Your subjects, past papers and progress are set up around these details. It takes 20 seconds and you only do it once."}</p>
      ${why ? `<p class="pg-why">${esc(why)}</p>` : ""}
      <label class="pg-f"><span>Full name <i>*</i></span>
        <input class="pg-in" name="name" autocomplete="name" required maxlength="80"
               value="${esc(state.name)}" placeholder="e.g. Ayesha Khan"></label>
      <div class="pg-f"><span>WhatsApp number <i>*</i></span>
        <div class="pg-phone">
          <select class="pg-sel" name="code" aria-label="Country code">
            ${CODES.map(([c, n]) => `<option value="${c}" ${c === code ? "selected" : ""}>${c} ${esc(n)}</option>`).join("")}
          </select>
          <input class="pg-in" name="number" type="tel" inputmode="tel" autocomplete="tel-national"
                 required value="${esc(number)}" placeholder="300 1234567" aria-label="WhatsApp number">
        </div>
        <p class="pg-hint">Your tutor uses this for class updates. Never shared.</p>
      </div>
      <fieldset class="pg-f" style="border:0;padding:0;margin:0 0 .6rem">
        <span>Which boards are you studying? <i>*</i></span>
        <div class="pg-boards">
          ${BOARDS.map(([slug, name, hint]) => `
            <label class="pg-b"><input type="checkbox" name="board" value="${slug}" ${boards.has(slug) ? "checked" : ""}>
              <span><b>${esc(name)}${slug === board ? "<em>needed for this subject</em>" : ""}</b>
                <small>${esc(hint)}</small></span></label>`).join("")}
        </div>
      </fieldset>
      <p class="pg-err" role="alert"></p>
      <div class="pg-act">
        ${required ? "" : '<button type="button" class="pg-btn pg-ghost" data-pg-close>Not now</button>'}
        <button type="submit" class="pg-btn">${subjectName || board ? "Save and enrol" : "Save and continue"}</button>
      </div>
    </form>`;
  document.body.appendChild(modal);
  const prevOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  return new Promise((resolve) => {
    const form = modal.querySelector("form");
    const err = modal.querySelector(".pg-err");
    const done = (ok) => {
      document.body.style.overflow = prevOverflow;
      modal.remove();
      document.removeEventListener("keydown", onKey);
      resolve(ok);
    };
    const onKey = (e) => { if (e.key === "Escape" && !required) done(false); };
    document.addEventListener("keydown", onKey);
    modal.querySelector("[data-pg-close]")?.addEventListener("click", () => done(false));
    if (!required) modal.addEventListener("click", (e) => { if (e.target === modal) done(false); });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      err.textContent = "";
      const name = form.name.value.trim();
      const digits = form.number.value.replace(/\D/g, "");
      const picked = [...form.querySelectorAll("input[name=board]:checked")].map((i) => i.value);
      if (name.length < 2) { err.textContent = "Please enter your full name."; form.name.focus(); return; }
      if (digits.length < 7 || digits.length > 13) {
        err.textContent = "Please enter a valid WhatsApp number."; form.number.focus(); return;
      }
      if (!picked.length) { err.textContent = "Pick at least one board."; return; }
      if (board && !picked.includes(board)) {
        err.textContent = `This subject is on ${boardName || "this board"} - tick it to enrol.`;
        return;
      }
      const btn = form.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        await call("/api/me/setup", "POST", {
          name, phone: `${form.code.value} ${digits.replace(/^0+/, "")}`, boards: picked,
        });
        done(true);
      } catch (ex) {
        err.textContent = ex.message || "Could not save. Try again.";
        btn.disabled = false;
      }
    });
    (state.name ? (number ? form.querySelector("input[name=board]") : form.number) : form.name)?.focus();
  });
}

/** True when the profile allows enrolling (in `board`, if given); else shows the form. */
export async function ensureProfile({ board = null, subjectName = "", state = null, prefill = null } = {}) {
  const st = state || await getSetup();
  if (st.complete && (!board || st.boards.includes(board))) return true;
  // prefill: what the page already holds (e.g. the unsaved profile form)
  const p = prefill || {};
  const merged = { ...st, name: p.name || st.name, phone: p.phone || st.phone,
                   boards: [...new Set([...(st.boards || []), ...(p.boards || [])])] };
  return openSetup({ state: merged, board, subjectName });
}

/**
 * Enrol in a subject, asking for the missing profile details first.
 * Resolves true when enrolled, false if the student closed the form.
 * Throws on other failures (network, invalid code).
 */
export async function enrol(syllabus, { subjectName = "", prefill = null } = {}) {
  const board = boardOf(syllabus);
  if (!(await ensureProfile({ board, subjectName, prefill }))) return false;
  try {
    await call("/api/enrollments", "POST", { syllabus });
  } catch (ex) {
    const code = ex.detail?.code;
    if (code !== "profile_incomplete" && code !== "board_not_chosen") throw ex;
    // Server knows better (e.g. the page's copy was stale): ask again, retry once.
    const ok = await openSetup({ state: await getSetup(), board: ex.detail.board || board,
                                 subjectName, reason: ex.message });
    if (!ok) return false;
    await call("/api/enrollments", "POST", { syllabus });
  }
  return true;
}

/** Restore an archived subject through the same gate. */
export async function restore(syllabus, { subjectName = "" } = {}) {
  if (!(await ensureProfile({ board: boardOf(syllabus), subjectName }))) return false;
  await call(`/api/enrollments/${encodeURIComponent(syllabus)}/restore`, "POST");
  return true;
}

// Pages where the pop-up would get in the way of finishing the profile itself
// (or of signing in / reading the legal pages).
const SKIP = /^\/(profile|login|signup|register|set-password|reset-password|forgot-password|verify|privacy|terms|refund|contact)(\.html)?$/;
let _pending = null;

/**
 * Every page (hooked from partials/nav.html): a signed-in STUDENT whose name,
 * WhatsApp number or board is missing gets the required form - including
 * students who enrolled before the gate existed. Guests, teachers, parents and
 * admins are left alone. Resolves true when nothing was needed.
 */
export function gateOnLoad() {
  if (_pending) return _pending;
  if (SKIP.test(location.pathname)) return Promise.resolve(true);
  _pending = getSetup().then(async (st) => {
    if (st.complete || st.role !== "student") return true;
    // pre-tick the board being browsed (/papers/igcse, /yearly/o-level/...)
    const here = location.pathname.split("/")[2];
    const boards = BOARDS.some((b) => b[0] === here) ? [...new Set([...st.boards, here])] : st.boards;
    const reason = st.enrolled
      ? "We're missing a few details on your account. Please add them to keep using your subjects."
      : "";
    await openSetup({ state: { ...st, boards }, required: true, reason });
    location.reload();
    return false;
  }).catch(() => true);                        // guest (401) or offline: nothing to do
  return _pending;
}
