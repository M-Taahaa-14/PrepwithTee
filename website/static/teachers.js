/* Teachers page — staff cards from the DB plus the "teach with us" form. */

import { api } from "/auth.js";

const SUBJECTS = [
  ["4024", "O Level Maths D"],
  ["0580", "IGCSE Maths"],
  ["5054", "O Level Physics"],
  ["0625", "IGCSE Physics"],
  ["2210", "O Level Computer Science"],
  ["0478", "IGCSE Computer Science"],
  ["5070", "O Level Chemistry"],
  ["0620", "IGCSE Chemistry"],
  ["9709", "A Level Maths"],
  ["9702", "A Level Physics"],
  ["9618", "A Level Computer Science"],
];

/* Rotate the pastel card tints so a row of teachers doesn't read as one block. */
const TINTS = ["lav", "green", "blue", "pink", "orange", "teal"];

const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const initials = name =>
  (name || "?").trim().split(/\s+/).slice(0, 2).map(w => w[0]).join("").toUpperCase();

/* ---- Teacher cards ------------------------------------------------------- */

function card(t, i) {
  const tint = TINTS[i % TINTS.length];
  const subjects = (t.subject_names || []).slice(0, 4);
  const more = (t.subject_names || []).length - subjects.length;

  return `
    <article class="teacher-card tint-${tint}">
      <div class="teacher-portrait">
        ${t.picture_url
          ? `<img src="${esc(t.picture_url)}" alt="${esc(t.name)}">`
          : `<span class="teacher-initials">${esc(initials(t.name))}</span>`}
      </div>
      <h3>${esc(t.name)}</h3>
      ${t.role ? `<p class="teacher-role">${esc(t.role)}</p>` : ""}
      ${t.bio ? `<p class="teacher-bio">${esc(t.bio)}</p>` : ""}
      ${subjects.length ? `
        <div class="teacher-subjects">
          ${subjects.map(s => `<span class="teacher-pill">${esc(s)}</span>`).join("")}
          ${more > 0 ? `<span class="teacher-pill teacher-pill-more">+${more} more</span>` : ""}
        </div>` : ""}
      ${t.qualifications ? `<p class="teacher-quals">${esc(t.qualifications)}</p>` : ""}
    </article>`;
}

async function loadTeachers() {
  const grid = document.getElementById("teacher-grid");
  try {
    const { teachers } = await api("/api/teachers");
    grid.innerHTML = teachers.length
      ? teachers.map(card).join("")
      : `<p class="teacher-loading">We're introducing the team shortly.</p>`;
  } catch {
    grid.innerHTML = `<p class="teacher-loading">Couldn't load the team just now —
      <a href="teachers.html">try again</a>.</p>`;
  }
}

/* ---- Application form ---------------------------------------------------- */

function buildSubjectChecks() {
  document.getElementById("subject-checks").innerHTML = SUBJECTS.map(([code, label]) => `
    <label class="subject-check">
      <input type="checkbox" name="subjects" value="${code}">
      <span>${label}</span>
    </label>`).join("");
}

function wireForm() {
  const form   = document.getElementById("apply-form");
  const alert  = document.getElementById("apply-alert");
  const submit = document.getElementById("apply-submit");

  const fail = msg => {
    alert.className = "auth-alert";
    alert.textContent = msg;
    alert.hidden = false;
    alert.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  form.addEventListener("submit", async e => {
    e.preventDefault();
    alert.hidden = true;

    const name  = form.name.value.trim();
    const email = form.email.value.trim();
    if (!name)  return fail("Please tell us your name.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail("That email doesn't look right.");

    const subjects = [...form.querySelectorAll('input[name="subjects"]:checked')]
      .map(i => i.nextElementSibling.textContent).join(", ");
    if (!subjects) return fail("Pick at least one subject you can teach.");

    submit.disabled = true;
    submit.textContent = "Sending…";
    try {
      const res = await api("/api/teacher-applications", {
        method: "POST",
        body: {
          name, email, subjects,
          phone:          form.phone.value.trim() || null,
          qualifications: form.qualifications.value.trim() || null,
          experience:     form.experience.value.trim() || null,
          message:        form.message.value.trim() || null,
        },
      });
      form.innerHTML = `
        <div class="apply-done">
          <div class="apply-done-mark">✓</div>
          <h3>Application received</h3>
          <p>${esc(res.message || "We'll be in touch soon.")}</p>
          <p class="apply-done-sub">We reply either way — keep an eye on ${esc(email)}.</p>
        </div>`;
    } catch (err) {
      fail(err.message);
      submit.disabled = false;
      submit.textContent = "Send application";
    }
  });
}

buildSubjectChecks();
wireForm();
loadTeachers();
