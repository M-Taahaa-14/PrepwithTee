// Shared helpers for the admin console: API client, escaping, formatting,
// toasts and modals. No colours or inline styles here - classes only.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const icon = name => `<i class="ti ti-${name}" aria-hidden="true"></i>`;

export class ApiError extends Error {
  constructor(message, status, detail) { super(message); this.status = status; this.detail = detail; }
}

/** JSON API call. The session cookie authenticates; 401 = signed out. */
export async function api(path, { method = "GET", body, signal } = {}) {
  const res = await fetch(path, {
    method, signal, credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    document.dispatchEvent(new CustomEvent("admin:signed-out"));
  }
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === "string" ? d : d?.message || `Request failed (${res.status})`;
    throw new ApiError(msg, res.status, d);
  }
  return data;
}

export function qs(params) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") u.set(k, v);
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* ── formatting ─────────────────────────────────────────────────────── */

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(String(iso).length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function rel(iso) {
  if (!iso) return "never";
  const d = new Date(String(iso).length === 10 ? `${iso}T12:00:00` : iso);
  const s = (Date.now() - d.getTime()) / 1000;
  if (Number.isNaN(s)) return "—";
  if (s < 0) {
    const days = Math.ceil(-s / 86400);
    return days <= 1 ? "tomorrow" : `in ${days} days`;
  }
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const days = Math.floor(s / 86400);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return fmtDate(iso);
}

export const num = n => (n ?? 0).toLocaleString();
export const pct = n => (n === null || n === undefined ? "—" : `${Math.round(n)}%`);
export const pkr = n => `PKR ${num(Math.round(n || 0))}`;
export const minutes = m => (m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}` : `${m} min`);

export const PLAN_LABELS = { free: "Free", trial: "Trial", solo: "Solo", three: "3 Subjects",
  all: "All Subjects", tutoring: "Tutoring", expired: "Expired" };
export const PLAN_TONES = { free: "", trial: "warn", solo: "acc", three: "ok", all: "pro",
  tutoring: "info", expired: "bad" };
export const PLAN_SUBJECT_LIMITS = { solo: 1, three: 3 };     // must match access.py
export const BOARD_LABELS = { "o-level": "O Level", igcse: "IGCSE", "a-level": "A Level" };

export function pill(text, tone = "") {
  return `<span class="pill ${tone}">${esc(text)}</span>`;
}

export function planPill(row) {
  const p = row.plan_effective || row.plan || "free";
  return pill(PLAN_LABELS[p] || p, PLAN_TONES[p] || "");
}

export function avatar(person, cls = "") {
  const name = person?.name || person?.email || "?";
  if (person?.picture_url) {
    return `<img class="avatar ${cls}" src="${esc(person.picture_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
  }
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase();
  return `<span class="avatar ${cls}" aria-hidden="true">${esc(initials)}</span>`;
}

export function waLink(phone) {
  const digits = String(phone || "").replace(/\D/g, "").replace(/^0(?=3)/, "92");
  return digits.length >= 10 ? `https://wa.me/${digits}` : null;
}

export function emptyState(ic, text, hint = "") {
  return `<div class="empty">${icon(ic)}<div>${esc(text)}</div>${hint ? `<div class="small faint">${esc(hint)}</div>` : ""}</div>`;
}

export const loadingHtml = (text = "Loading…") =>
  `<div class="loading" role="status"><span class="spin"></span>${esc(text)}</div>`;

/** Tiny bar chart as inline SVG; values [{label, value}] */
export function bars(series, { height = 120 } = {}) {
  if (!series.length) return "";
  const max = Math.max(1, ...series.map(s => s.value));
  const w = 100 / series.length;
  const rects = series.map((s, i) => {
    const h = Math.max(2, (s.value / max) * (height - 18));
    return `<rect class="${s.value ? "" : "zero"}" x="${(i * w + w * 0.15).toFixed(2)}%" y="${height - 14 - h}"
      width="${(w * 0.7).toFixed(2)}%" height="${h}" rx="2"><title>${esc(s.label)}: ${num(s.value)}</title></rect>`;
  }).join("");
  const first = series[0].label, last = series[series.length - 1].label;
  return `<svg class="bars" viewBox="0 0 100 ${height}" preserveAspectRatio="none" role="img"
      aria-label="${esc(`${first} to ${last}`)}">${rects}</svg>
    <div class="row small faint"><span>${esc(first)}</span><span class="grow"></span><span>${esc(last)}</span></div>`;
}

/* ── toasts ─────────────────────────────────────────────────────────── */

export function toast(msg, bad = false) {
  let box = $(".toasts");
  if (!box) {
    box = document.createElement("div");
    box.className = "toasts";
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    document.body.append(box);
  }
  const t = document.createElement("div");
  t.className = `toast${bad ? " bad" : ""}`;
  t.textContent = msg;
  box.append(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3200);
}

/* ── modals ─────────────────────────────────────────────────────────── */

/**
 * modal({title, body, submit, cancel, onMount, run})
 * `run(el)` is called on submit; throw (or return a string) to show an error and
 * keep the modal open. Resolves to run()'s result, or null when cancelled.
 */
export function modal({ title, body, submit = "Save", cancel = "Cancel", danger = false,
                        onMount, run, wide = false, size }) {
  // size: "md" (default), "lg" (forms with several fields), "xl" (editors)
  const sz = size || (wide ? "lg" : "md");
  return new Promise(resolve => {
    const prev = document.activeElement;
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.innerHTML = `
      <div class="modal modal-${sz}" role="dialog" aria-modal="true" aria-labelledby="m-title">
        <div class="modal-head"><h2 id="m-title" class="grow">${esc(title)}</h2>
          <button class="btn ghost icon" data-x aria-label="Close">${icon("x")}</button></div>
        <form class="modal-form">
          <div class="modal-body">${body}<div class="err" role="alert"></div></div>
          <div class="modal-foot">
            ${cancel ? `<button type="button" class="btn" data-x>${esc(cancel)}</button>` : ""}
            ${submit ? `<button type="submit" class="btn ${danger ? "danger" : "primary"}">${esc(submit)}</button>` : ""}
          </div>
        </form>
      </div>`;
    document.body.append(scrim);
    const el = $(".modal", scrim);
    const err = $(".err", scrim);
    const close = val => { scrim.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.(); resolve(val); };
    const onKey = e => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    scrim.addEventListener("mousedown", e => { if (e.target === scrim) close(null); });
    $$("[data-x]", scrim).forEach(b => b.addEventListener("click", () => close(null)));
    $(".modal-form", scrim).addEventListener("submit", async e => {
      e.preventDefault();
      err.textContent = "";
      const btn = $("button[type=submit]", scrim);
      if (btn) btn.disabled = true;
      try {
        const out = run ? await run(el) : true;
        if (typeof out === "string") { err.textContent = out; return; }
        close(out ?? true);
      } catch (ex) {
        err.textContent = ex.message || String(ex);
      } finally {
        if (btn) btn.disabled = false;
      }
    });
    onMount?.(el);
    ($("[autofocus]", el) || $("input, select, textarea, button[type=submit]", el))?.focus();
  });
}

export const confirmBox = (title, text, submit = "Confirm", danger = false) =>
  modal({ title, body: `<p>${esc(text)}</p>`, submit, danger });

/* ── shared lookups (cached for the page's life) ────────────────────── */

const cache = {};
export async function lookup(name) {
  if (cache[name]) return cache[name];
  const urls = {
    subjects: ["/api/admin/overview", d => d.subject_options || []],
    teachers: ["/api/admin/teacher-profiles", d => d.teachers || []],
  };
  const [url, pick] = urls[name];
  cache[name] = api(url).then(pick).catch(e => { delete cache[name]; throw e; });
  return cache[name];
}

/* ── side drawer (detail views) ─────────────────────────────────────── */

/** drawer({title, body, onMount}) -> {el, close}. One at a time; Esc closes. */
export function drawer({ title, body, onMount, onClose }) {
  $(".drawer-scrim")?.remove();
  const prev = document.activeElement;
  const scrim = document.createElement("div");
  scrim.className = "drawer-scrim";
  scrim.innerHTML = `<aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="d-title">
      <div class="drawer-head"><h2 id="d-title" class="grow">${esc(title)}</h2>
        <button class="btn ghost icon" data-x aria-label="Close">${icon("x")}</button></div>
      <div class="drawer-body">${body}</div></aside>`;
  document.body.append(scrim);
  const el = $(".drawer", scrim);
  const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.(); onClose?.(); };
  const onKey = e => { if (e.key === "Escape" && !$(".scrim")) close(); };
  document.addEventListener("keydown", onKey);
  scrim.addEventListener("mousedown", e => { if (e.target === scrim) close(); });
  $("[data-x]", scrim).addEventListener("click", close);
  onMount?.(el, close);
  ($("[autofocus]", el) || $("[data-x]", el)).focus();
  return { el, close };
}

/** Segmented tab bar. tabs = [[key, label, count?]]; returns html. */
export function tabBar(tabs, active) {
  return `<div class="tabs" role="tablist">${tabs.map(([k, label, n]) =>
    `<button class="tab${k === active ? " on" : ""}" role="tab" aria-selected="${k === active}" data-tab="${esc(k)}">${esc(label)}${
      n !== undefined && n !== null ? `<span class="n">${esc(n)}</span>` : ""}</button>`).join("")}</div>`;
}

/** Download a file through fetch (session cookie) and save it. */
export async function download(url, filename) {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename || url.split("/").pop();
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ── progress rings + grades ────────────────────────────────────────── */

/** SVG progress ring. tone: violet | teal | amber | rose | sky */
export function ring(pct, label, tone = "violet", center = null, sub = "") {
  const r = 34, c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="ring ring-${tone}" title="${esc(sub || label)}">
    <svg viewBox="0 0 80 80" aria-hidden="true"><circle class="ring-bg" cx="40" cy="40" r="${r}"></circle>
      <circle class="ring-fg" cx="40" cy="40" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - p / 100)).toFixed(1)}"></circle></svg>
    <div class="ring-c">${esc(center ?? `${Math.round(p)}%`)}</div>
    <div class="ring-l">${esc(label)}</div>${sub ? `<div class="ring-s">${esc(sub)}</div>` : ""}</div>`;
}

/** Cambridge grade from a raw mark and that sitting's thresholds (same rule as the
 *  student pages, static/progress-shared.js). Falls back to percentages. */
export function gradeFor(score, max, t) {
  if (score === "" || score === null || score === undefined || isNaN(score) || !max) return { grade: null, pct: null };
  score = Number(score); max = Number(max);
  const pct = Math.round((score / max) * 100);
  if (!t) return { grade: pct >= 85 ? "A*" : pct >= 70 ? "A" : pct >= 60 ? "B" : pct >= 50 ? "C" : pct >= 40 ? "D" : pct >= 30 ? "E" : "U", pct, estimated: true };
  if (t.grade_astar != null && score >= t.grade_astar) return { grade: "A*", pct };
  for (const [g, k] of [["A", "grade_a"], ["B", "grade_b"], ["C", "grade_c"], ["D", "grade_d"], ["E", "grade_e"], ["F", "grade_f"], ["G", "grade_g"]]) {
    if (t[k] != null && score >= t[k]) return { grade: g, pct };
  }
  return { grade: "U", pct };
}

export function gradePill(grade, extra = "") {
  if (!grade) return `<span class="gp gp-none">${esc(extra || "—")}</span>`;
  return `<span class="gp gp-${grade === "A*" ? "As" : grade}">${esc(grade)}${extra ? ` <span class="faint">${esc(extra)}</span>` : ""}</span>`;
}
