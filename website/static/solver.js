/* solver.js — /solver: the Photo Solver.
 *
 *   Solve a question   photo of a question -> step-by-step worked solution
 *   Check my working   question photo + your working (photo or typed) -> marked
 *                      step by step, like an examiner would
 *
 * Photos come in by drop, paste (Ctrl+V), camera or file picker; each gets a crop
 * box (drag it, drag its corners) and is cropped + downscaled here before upload,
 * so a 6 MB phone photo goes up as ~200 KB. A short follow-up can be asked about
 * the answer. Free AI providers only (/api/solve, /api/solve/followup).
 */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = { mode: "solve", wtab: "photo", slots: {}, busy: false, solution: "", lastSlot: "question" };

// ── Modes ───────────────────────────────────────────────────────────────────
function setMode(m) {
  S.mode = m;
  document.querySelectorAll(".sv-mode").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === m)));
  $("#sv-working").hidden = m !== "check";
  $("#sv-go").textContent = m === "check" ? "Check my working" : "Solve it";
  $("#sv-placeholder p").textContent = m === "check"
    ? "Your marked working will appear here." : "Your worked solution will appear here.";
  ready();
}
document.querySelectorAll(".sv-mode").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

document.querySelectorAll("[data-wtab]").forEach((b) => b.addEventListener("click", () => {
  S.wtab = b.dataset.wtab;
  document.querySelectorAll("[data-wtab]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("#sv-w").hidden = S.wtab !== "photo";
  $("#sv-wtext").hidden = S.wtab !== "type";
  if (S.wtab === "type") $("#sv-wtext").focus();
  ready();
}));
$("#sv-wtext").addEventListener("input", ready);

function ready() {
  const q = !!S.slots.question;
  const w = S.mode !== "check" || (S.wtab === "photo" ? !!S.slots.working : $("#sv-wtext").value.trim().length > 0);
  $("#sv-go").disabled = S.busy || !(q && w);
}

// ── Photos in ───────────────────────────────────────────────────────────────
function loadImage(file) {
  return new Promise((resolve, reject) => {
    if (!file || !/^image\//.test(file.type)) return reject(new Error("That isn't an image."));
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("That image couldn't be read - try a JPG or PNG."));
    img.src = url;
  });
}

async function accept(slot, file) {
  const box = document.querySelector(`[data-slot="${slot}"]`);
  try {
    const img = await loadImage(file);
    S.slots[slot] = { img, crop: { x: 0.03, y: 0.03, w: 0.94, h: 0.94 } };
    S.lastSlot = slot;
    drawCropper(box, slot);
    status("");
  } catch (e) { status(e.message, true); }
  ready();
}

document.querySelectorAll(".sv-drop").forEach((box) => {
  const slot = box.dataset.slot;
  box.addEventListener("change", (e) => { if (e.target.matches("[data-pick]")) accept(slot, e.target.files[0]); });
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("is-over"); });
  box.addEventListener("dragleave", () => box.classList.remove("is-over"));
  box.addEventListener("drop", (e) => {
    e.preventDefault();
    box.classList.remove("is-over");
    if (e.dataTransfer.files[0]) accept(slot, e.dataTransfer.files[0]);
  });
  box.addEventListener("click", () => { S.lastSlot = slot; });
});
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (!item) return;
  e.preventDefault();
  // paste into the question first, then the working (check mode)
  const slot = !S.slots.question ? "question"
    : S.mode === "check" && S.wtab === "photo" && !S.slots.working ? "working" : S.lastSlot;
  accept(slot, item.getAsFile());
});

// ── Crop box ────────────────────────────────────────────────────────────────
function drawCropper(box, slot) {
  const { img } = S.slots[slot];
  box.classList.add("has-img");
  box.innerHTML = `
    <div class="sv-crop">
      <img src="${img.src}" alt="Your photo" draggable="false">
      <div class="sv-crop-rect" tabindex="0" aria-label="Crop area - drag to move">
        ${["nw", "ne", "sw", "se"].map((c) => `<span class="sv-h sv-h-${c}" data-h="${c}"></span>`).join("")}
      </div>
    </div>
    <div class="sv-crop-bar">
      <span>Drag the box and its corners to crop to one question.</span>
      <button type="button" class="sv-link" data-reset>Reset</button>
      <button type="button" class="sv-link" data-remove>Remove</button>
    </div>`;
  const wrap = box.querySelector(".sv-crop"), rect = box.querySelector(".sv-crop-rect");
  const paint = () => {
    const c = S.slots[slot].crop;
    Object.assign(rect.style, { left: `${c.x * 100}%`, top: `${c.y * 100}%`, width: `${c.w * 100}%`, height: `${c.h * 100}%` });
  };
  paint();
  rect.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    rect.setPointerCapture(e.pointerId);
    const handle = e.target.dataset.h;
    const r = wrap.getBoundingClientRect();
    const c0 = { ...S.slots[slot].crop }, x0 = e.clientX, y0 = e.clientY;
    const min = 0.06, cl = (v) => Math.min(1, Math.max(0, v));
    const move = (ev) => {
      const dx = (ev.clientX - x0) / r.width, dy = (ev.clientY - y0) / r.height;
      const c = { ...c0 };
      if (!handle) {
        c.x = cl(Math.min(c0.x + dx, 1 - c0.w));
        c.y = cl(Math.min(c0.y + dy, 1 - c0.h));
      } else {
        if (handle.includes("w")) { c.x = cl(Math.min(c0.x + dx, c0.x + c0.w - min)); c.w = c0.x + c0.w - c.x; }
        if (handle.includes("e")) c.w = Math.max(min, Math.min(1 - c0.x, c0.w + dx));
        if (handle.includes("n")) { c.y = cl(Math.min(c0.y + dy, c0.y + c0.h - min)); c.h = c0.y + c0.h - c.y; }
        if (handle.includes("s")) c.h = Math.max(min, Math.min(1 - c0.y, c0.h + dy));
      }
      S.slots[slot].crop = c;
      paint();
    };
    const up = () => { rect.removeEventListener("pointermove", move); rect.removeEventListener("pointerup", up); };
    rect.addEventListener("pointermove", move);
    rect.addEventListener("pointerup", up);
  });
  box.querySelector("[data-reset]").addEventListener("click", () => {
    S.slots[slot].crop = { x: 0.03, y: 0.03, w: 0.94, h: 0.94 }; paint();
  });
  box.querySelector("[data-remove]").addEventListener("click", () => {
    delete S.slots[slot];
    box.classList.remove("has-img");
    box.innerHTML = box.dataset.empty;
    ready();
  });
}
document.querySelectorAll(".sv-drop").forEach((b) => { b.dataset.empty = b.innerHTML; });

/** The cropped photo, at most 1600 px on its long edge, as a JPEG data URL. */
function cropped(slot, maxEdge = 1600) {
  const { img, crop } = S.slots[slot];
  const sx = crop.x * img.naturalWidth, sy = crop.y * img.naturalHeight;
  const sw = crop.w * img.naturalWidth, sh = crop.h * img.naturalHeight;
  const k = Math.min(1, maxEdge / Math.max(sw, sh));
  const c = document.createElement("canvas");
  c.width = Math.round(sw * k); c.height = Math.round(sh * k);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.86);
}

// ── Solve / check ───────────────────────────────────────────────────────────
function status(msg, bad = false) {
  const el = $("#sv-status");
  el.textContent = msg;
  el.classList.toggle("is-bad", bad);
}

function math(el) {
  const go = (tries) => {
    if (window.renderMathInElement) {
      window.renderMathInElement(el, { throwOnError: false, delimiters: [
        { left: "\\[", right: "\\]", display: true }, { left: "\\(", right: "\\)", display: false },
        { left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }] });
    } else if (tries) setTimeout(() => go(tries - 1), 120);
  };
  go(30);
}

async function post(url, body) {
  const r = await fetch(url, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Something went wrong - try again.");
  return d;
}

$("#sv-go").addEventListener("click", async () => {
  if (S.busy) return;
  S.busy = true; ready();
  const check = S.mode === "check";
  $("#sv-placeholder").hidden = true;
  const out = $("#sv-result");
  out.hidden = false;
  out.innerHTML = `<div class="sv-loading"><span class="sv-spin"></span>
    <b>${check ? "Marking your working…" : "Working it out…"}</b><small>Usually 10–30 seconds</small></div>`;
  $("#sv-follow").hidden = true;
  $("#sv-thread").innerHTML = "";
  status("");
  try {
    const body = { image: cropped("question"), note: $("#sv-note").value.trim() || null,
                   syllabus: $("#sv-subject").value || null, mode: S.mode };
    if (check) {
      if (S.wtab === "photo") body.working = cropped("working");
      else body.working_text = $("#sv-wtext").value;
    }
    const d = await post("/api/solve", body);
    S.solution = d.html;
    out.innerHTML = `<div class="sv-result-head"><span class="sv-tag">${check ? "✅ Marked" : "📷 Solved"}</span>
      <button type="button" class="sv-link" data-copy>Copy</button></div>
      <div class="sv-answer ${check ? "is-check" : ""}">${d.html}</div>`;
    math(out);
    $("#sv-follow").hidden = false;
    out.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    out.innerHTML = `<p class="sv-err">⚠️ ${esc(e.message)}</p>`;
  } finally {
    S.busy = false; ready();
  }
});

$("#sv-result").addEventListener("click", (e) => {
  if (!e.target.closest("[data-copy]")) return;
  navigator.clipboard?.writeText($(".sv-answer").innerText).then(() => {
    e.target.textContent = "Copied ✓";
    setTimeout(() => { e.target.textContent = "Copy"; }, 1500);
  });
});

$("#sv-follow").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#sv-fq"), text = q.value.trim();
  if (!text) return;
  const thread = $("#sv-thread");
  thread.insertAdjacentHTML("beforeend", `<div class="sv-q">${esc(text)}</div>`);
  const a = document.createElement("div");
  a.className = "sv-a";
  a.innerHTML = '<span class="sv-spin"></span>';
  thread.appendChild(a);
  q.value = "";
  try {
    const d = await post("/api/solve/followup", { solution: S.solution, message: text });
    a.innerHTML = d.html;
    math(a);
  } catch (err) { a.innerHTML = `<p class="sv-err">⚠️ ${esc(err.message)}</p>`; }
});

// ── Subjects ────────────────────────────────────────────────────────────────
fetch("/api/boards").then((r) => r.json()).then(({ boards }) => {
  const sel = $("#sv-subject");
  for (const b of boards) {
    const g = document.createElement("optgroup");
    g.label = b.short;
    for (const s of b.subjects) g.insertAdjacentHTML("beforeend", `<option value="${s.code}">${esc(s.name)} (${s.code})</option>`);
    sel.appendChild(g);
  }
}).catch(() => {});

const want = new URLSearchParams(location.search).get("mode");
setMode(want === "check" ? "check" : "solve");
