/* Student homework page — what the tutor assigned, and what's overdue.
 *
 * Read-mostly: the only things a student can change are "mark done" and their
 * own note. Attachments come in three flavours and each needs a different
 * link — an uploaded worksheet streams from the API (ownership-checked
 * server-side), a resource opens the shared notes file, and a booklet is
 * generated on demand by POSTing the tutor's saved parameters to /api/generate.
 */

import { requireProfile, api, teeLoader, UpgradeRequiredError } from "/auth.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const KIND_LABEL = {
  homework: "Homework", reading: "Reading",
  practice: "Practice", test: "Test",
};

let items = [];

/* Start fetching before the auth round-trip resolves — both endpoints enforce
   the session themselves, so waiting on /auth/me only added latency. */
const dataPromise = Promise.all([
  api("/api/assignments"),
  api("/api/classes").catch(() => ({ classes: [], held: 0 })),
]);
dataPromise.catch(() => {});

const user = await requireProfile();
if (user) init();

async function init() {
  try {
    const [hw, cls] = await dataPromise;
    items = hw.assignments || [];
    render();
    renderClasses(cls);
    renderCalendarCard();
  } catch (err) {
    const box = document.getElementById("hw-open");
    if (err instanceof UpgradeRequiredError) {
      box.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;gap:16px;
                    padding:48px 24px;text-align:center">
          <span style="font-size:2.8rem">🎓</span>
          <h3 style="font-family:'Playfair Display',Georgia,serif;color:var(--purple);margin:0">
            Homework is a Tutoring feature</h3>
          <p style="color:var(--grey);max-width:38ch;line-height:1.6;margin:0">
            Homework is assigned by your teacher and available on the
            <strong>Tutoring plan</strong> — which includes 1-on-1 lessons, a
            personal teacher, and everything below.</p>
          <div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center">
            <a href="pricing.html#tutoring" class="btn btn-dark">See Tutoring plan →</a>
            <a href="https://wa.me/923204884375?text=Hi%20Tee%21%20I%27d%20like%20to%20ask%20about%20one-on-one%20tuition."
               class="btn btn-outline">Ask Tee on WhatsApp</a>
          </div>
        </div>`;
    } else {
      box.innerHTML =
        `<p class="dash-loading">Couldn't load your homework: ${esc(err.message)}</p>`;
    }
  }
}

/* ---- due-date wording ---------------------------------------------------- */

function dueLabel(a) {
  if (!a.due_date) return { text: "No deadline", tone: "" };
  const d = a.days_left;
  if (a.status === "done") return { text: `Was due ${a.due_date}`, tone: "" };
  if (d < 0) return { text: `${Math.abs(d)} day${Math.abs(d) === 1 ? "" : "s"} overdue`, tone: "late" };
  if (d === 0) return { text: "Due today", tone: "soon" };
  if (d === 1) return { text: "Due tomorrow", tone: "soon" };
  if (d <= 3) return { text: `Due in ${d} days`, tone: "soon" };
  return { text: `Due ${a.due_date}`, tone: "" };
}

/* ---- reminder banner ----------------------------------------------------- */

function renderAlert(open) {
  const box = document.getElementById("hw-alert");
  const overdue = open.filter(a => a.overdue);
  const today = open.filter(a => a.days_left === 0);

  if (overdue.length) {
    box.innerHTML = `
      <div class="hw-banner hw-banner-late">
        <span class="hw-banner-icon">⏰</span>
        <div>
          <strong>${overdue.length} piece${overdue.length === 1 ? "" : "s"} of work
            ${overdue.length === 1 ? "is" : "are"} overdue.</strong>
          <p>${esc(overdue.map(a => a.title).slice(0, 3).join(" · "))}</p>
        </div>
      </div>`;
  } else if (today.length) {
    box.innerHTML = `
      <div class="hw-banner hw-banner-soon">
        <span class="hw-banner-icon">📌</span>
        <div>
          <strong>${today.length} due today.</strong>
          <p>${esc(today.map(a => a.title).join(" · "))}</p>
        </div>
      </div>`;
  } else {
    box.innerHTML = "";
  }
}

/* ---- cards --------------------------------------------------------------- */

function attachmentHtml(a) {
  if (!a.attachments?.length) return "";
  // Labelled explicitly. Without a heading these files sat directly above the
  // student's own uploads with nothing saying which was which.
  return `<div class="hw-block">
    <p class="hw-block-lbl hw-block-from">📥 From your tutor</p>
    <div class="hw-files">${a.attachments.map(t => {
    if (t.type === "upload") {
      return `<a class="hw-file" href="/api/assignments/${a.id}/file/${t.idx}"
                 target="_blank" rel="noopener">
                <span class="hw-file-ic">📎</span>
                <span>${esc(t.name || "Worksheet")}<em>Download</em></span></a>`;
    }
    if (t.type === "resource") {
      return `<a class="hw-file" href="/api/resources/file?rel=${encodeURIComponent(t.rel || "")}"
                 target="_blank" rel="noopener">
                <span class="hw-file-ic">📄</span>
                <span>${esc(t.name || t.rel)}<em>Read these notes</em></span></a>`;
    }
    if (t.type === "paper") {
      return `<a class="hw-file" href="/papers/view/${encodeURIComponent(t.booklet_id || "")}"
                 target="_blank" rel="noopener">
                <span class="hw-file-ic">📝</span>
                <span>${esc(t.name || "Topical paper")}<em>Open your paper</em></span></a>`;
    }
    if (t.type === "booklet") {
      return `<button type="button" class="hw-file hw-file-btn"
                      data-booklet="${a.id}" data-idx="${t.idx}">
                <span class="hw-file-ic">📚</span>
                <span>${esc(t.name || "Practice booklet")}<em>Build &amp; download</em></span></button>`;
    }
    return "";
  }).join("")}</div>
  </div>`;
}

function submissionsHtml(a) {
  const subs = a.submissions || [];
  const hasSubs = subs.length > 0;
  return `
    <div class="hw-block hw-submit${hasSubs ? " has-subs" : ""}" data-submit-zone="${a.id}">
      <p class="hw-block-lbl hw-block-mine">
        📤 Your submission${hasSubs ? ` <i>${subs.length} file${subs.length === 1 ? "" : "s"} sent to your tutor</i>` : ""}
      </p>
      ${hasSubs ? `
        <div class="hw-submitted-files">
          ${subs.map((s, i) => `
            <a class="hw-file hw-file-sub"
               href="/api/assignments/${a.id}/submission/${i}"
               target="_blank" rel="noopener">
              <span class="hw-file-ic">✅</span>
              <span>${esc(s.name || "Submitted file")}<em>You submitted this${s.submitted_at
                ? " on " + s.submitted_at.slice(0, 10) : ""}</em></span>
            </a>`).join("")}
        </div>`
      : `<p class="hw-nosub">You haven't submitted anything for this yet.</p>`}
      <div class="hw-upload-row">
        <label class="hw-upload-label" for="hw-file-${a.id}">
          <span class="hw-upload-icon">📤</span>
          <span>${hasSubs ? "Upload another file" : "Submit your work"}</span>
        </label>
        <input type="file" id="hw-file-${a.id}" class="hw-file-input" data-upload="${a.id}"
               accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.txt,.xlsx,.ppt,.pptx">
        <span class="hw-upload-msg" data-upload-msg="${a.id}"></span>
      </div>
    </div>`;
}

function card(a) {
  const due = dueLabel(a);
  const done = a.status === "done";
  return `
    <article class="hw-item${done ? " done" : ""}${due.tone === "late" ? " late" : ""}"
             data-id="${a.id}">
      <div class="hw-item-top">
        <span class="hw-kind">${esc(KIND_LABEL[a.kind] || a.kind || "Homework")}</span>
        ${a.subject_name ? `<span class="hw-subj">${esc(a.subject_name)}</span>` : ""}
        <span class="hw-when ${due.tone}">${esc(due.text)}</span>
      </div>
      <h3>${esc(a.title)}</h3>
      ${a.instructions ? `<p class="hw-what">${esc(a.instructions)}</p>` : ""}
      ${a.topics?.length ? `<div class="hw-chips">${a.topics.map(t =>
        `<span class="hw-chip">${esc(t)}</span>`).join("")}</div>` : ""}
      ${attachmentHtml(a)}
      ${submissionsHtml(a)}
      <div class="hw-item-foot">
        ${done
          ? `<button type="button" class="btn btn-outline" data-undo="${a.id}">Mark as not done</button>
             <span class="hw-done-at">Completed${a.completed_at
               ? " " + esc(String(a.completed_at).slice(0, 10)) : ""}</span>`
          : `<button type="button" class="btn btn-gold" data-done="${a.id}">Mark as done</button>`}
      </div>
    </article>`;
}

function render() {
  const open = items.filter(a => a.status !== "done");
  const done = items.filter(a => a.status === "done");

  document.getElementById("hw-sub").textContent = open.length
    ? `${open.length} thing${open.length === 1 ? "" : "s"} to do.`
    : "Nothing outstanding — nice work.";

  const counter = document.getElementById("hw-count");
  counter.hidden = !open.length;
  if (open.length) counter.querySelector(".hw-count-num").textContent = open.length;

  renderAlert(open);

  document.getElementById("hw-open").innerHTML = open.length
    // Soonest deadline first; undated work sinks below anything with a date.
    ? `<div class="hw-list">${[...open]
        .sort((a, b) => (a.due_date === null) - (b.due_date === null)
                     || String(a.due_date).localeCompare(String(b.due_date)))
        .map(card).join("")}</div>`
    : `<div class="dash-empty">
         <p><strong>No homework right now.</strong> When Tee sets you work it
         shows up here, and you'll see a reminder on your dashboard.</p>
         <a class="btn btn-outline" href="/notes">Revise something anyway</a>
       </div>`;

  const doneCard = document.getElementById("hw-done-card");
  doneCard.hidden = !done.length;
  if (done.length) {
    document.getElementById("hw-done-note").textContent =
      `${done.length} finished`;
    document.getElementById("hw-done").innerHTML =
      `<div class="hw-list">${done.map(card).join("")}</div>`;
  }

  wire();
}

function wire() {
  document.querySelectorAll("[data-done]").forEach(b =>
    b.addEventListener("click", () => setStatus(b, Number(b.dataset.done), "done")));
  document.querySelectorAll("[data-undo]").forEach(b =>
    b.addEventListener("click", () => setStatus(b, Number(b.dataset.undo), "assigned")));
  document.querySelectorAll("[data-booklet]").forEach(b =>
    b.addEventListener("click", () => buildBooklet(b)));
  document.querySelectorAll("[data-upload]").forEach(input =>
    input.addEventListener("change", () => uploadFile(input)));
}

async function uploadFile(input) {
  const id = Number(input.dataset.upload);
  const file = input.files?.[0];
  if (!file) return;
  const msgEl = document.querySelector(`[data-upload-msg="${id}"]`);
  const label = input.previousElementSibling;

  const setMsg = (text, ok) => {
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.className = "hw-upload-msg " + (ok ? "ok" : ok === false ? "err" : "");
  };

  setMsg("Uploading…", null);
  if (label) label.style.opacity = "0.5";
  input.disabled = true;

  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/assignments/${id}/submit`, {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.message || `Upload failed (${res.status})`);
    // Update local data and re-render the card
    items = items.map(a => a.id === id ? data.assignment : a);
    render();
  } catch (err) {
    setMsg(err.message, false);
    input.disabled = false;
    if (label) label.style.opacity = "";
  }
}

async function setStatus(btn, id, status) {
  btn.disabled = true;
  btn.textContent = status === "done" ? "Saving…" : "Reopening…";
  try {
    const res = await api(`/api/assignments/${id}/status`,
                          { method: "POST", body: { status } });
    items = items.map(a => a.id === id ? res.assignment : a);
    render();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = status === "done" ? "Mark as done" : "Mark as not done";
    alert(err.message);
  }
}

/* The tutor stored the booklet's filters, not the PDF — generating on demand
   keeps one source of truth and picks up any reclassification since. */
async function buildBooklet(btn) {
  const a = items.find(x => String(x.id) === btn.dataset.booklet);
  const att = a?.attachments?.find(t => t.idx === Number(btn.dataset.idx));
  if (!att?.params) return;

  const label = btn.querySelector("em");
  const original = label.textContent;
  btn.disabled = true;
  label.textContent = "Building your booklet…";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(att.params),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Generation failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(att.name || "booklet").replace(/[^\w\- ]+/g, "")}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoking immediately can abort the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    label.textContent = "Downloaded ✓";
  } catch (err) {
    label.textContent = original;
    alert(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---- calendar subscription ----------------------------------------------- */

async function renderCalendarCard() {
  let url, webcal;
  try {
    ({ url, webcal } = await api("/api/my-calendar"));
  } catch { return; }              // no feed, no card — never show a dead button

  document.getElementById("hw-cal-card").hidden = false;
  // webcal:// makes a phone hand the URL straight to its calendar app and
  // subscribe (staying in sync), rather than downloading a one-off .ics file.
  document.getElementById("cal-sub-add").href = webcal || url;

  const copy = document.getElementById("cal-sub-copy");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(url);
      copy.textContent = "Copied ✓";
    } catch {
      // Clipboard needs a secure context and permission; fall back to showing
      // the link so it can still be selected by hand.
      prompt("Copy this calendar link:", url);
      copy.textContent = "Copy link";
      return;
    }
    setTimeout(() => { copy.textContent = "Copy link"; }, 2500);
  });
}

/* ---- class log ----------------------------------------------------------- */

function renderClasses({ classes, held }) {
  if (!classes?.length) return;
  document.getElementById("hw-classes-card").hidden = false;
  document.getElementById("hw-classes-note").textContent =
    `${held} lesson${held === 1 ? "" : "s"} taken`;
  document.getElementById("hw-classes").innerHTML = `
    <ul class="cls-list">${classes.slice(0, 20).map(c => `
      <li class="cls-item cls-${esc(c.status || "held")}">
        <span class="cls-date">${esc(c.class_date)}${
          c.start_time ? ` · ${esc(c.start_time)}` : ""}</span>
        <span class="cls-body">
          <strong>${esc(c.topic || c.subject_name || "Lesson")}</strong>
          <em>${esc(c.subject_name || "")}${
            c.duration_min ? ` · ${esc(c.duration_min)} min` : ""}</em>
        </span>
        <span class="cls-status">${esc(c.status || "held")}</span>
      </li>`).join("")}</ul>`;
}
