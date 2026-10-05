/* ink/color.js — the colour picker in the annotation rail (and the whiteboard).
 *
 *   const cp = colorPanel({ palette, ink, onPick, alpha: true });
 *   flyout.appendChild(cp.el); cp.set("@blue");
 *
 * Inks (palette tokens, they change shade on dark paper) · a saturation /
 * brightness field + hue slider + opacity slider · hex box (#rgb, #rrggbb,
 * #rrggbbaa) · eyedropper where the browser has one · Recent (last 10) and
 * My colours (saved, localStorage "pwt-ink-colors"). Custom colours are stored
 * as plain hex; 8 digits when they are see-through.
 */
const LS = "pwt-ink-colors";

export const hexToRgb = (h) => {
  h = String(h || "").replace("#", "");
  if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
  const n = parseInt(h.slice(0, 6), 16);
  const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, a];
};
const hx = (v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0");
export const rgbToHex = (r, g, b, a = 1) => `#${hx(r)}${hx(g)}${hx(b)}${a < 0.999 ? hx(a * 255) : ""}`;

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, mx ? d / mx : 0, mx];
}
function hsvToRgb(h, s, v) {
  const f = (n) => { const k = (n + h / 60) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return [f(5) * 255, f(3) * 255, f(1) * 255];
}
export const validHex = (h) => /^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(h || "");
const norm = (h) => { const [r, g, b, a] = hexToRgb(h); return rgbToHex(r, g, b, a); };

function store() {
  try {
    const s = JSON.parse(localStorage.getItem(LS) || "{}");
    return { recent: (s.recent || []).filter(validHex).slice(0, 10), mine: (s.mine || []).filter(validHex).slice(0, 18) };
  } catch { return { recent: [], mine: [] }; }
}
function keep(s) { try { localStorage.setItem(LS, JSON.stringify(s)); } catch { /* ignore */ } }

/** Remember a colour that was used (tokens are not "recent" - they are always on show). */
export function rememberColor(c) {
  if (!validHex(c)) return;
  const s = store();
  s.recent = [norm(c), ...s.recent.filter((x) => x !== norm(c))].slice(0, 10);
  keep(s);
}

export function colorPanel({ palette, ink, onPick, alpha = true, title = "Colour" }) {
  const el = document.createElement("div");
  el.className = "ink-cp";
  el.innerHTML = `
    <p class="ink-fly-head">${title}</p>
    <div class="ink-cp-inks" role="group" aria-label="Inks">${palette.map(([k, , , n]) =>
      `<button type="button" class="ink-dot" data-cp="@${k}" title="${n}" aria-label="${n}"></button>`).join("")}</div>
    <div class="ink-cp-field" tabindex="0" role="slider" aria-label="Saturation and brightness"
         aria-valuetext=""><canvas width="232" height="132"></canvas><i class="ink-cp-knob"></i></div>
    <label class="ink-cp-row"><span class="ink-cp-lbl">Hue</span>
      <input type="range" class="ink-cp-hue" min="0" max="360" step="1" aria-label="Hue"></label>
    ${alpha ? `<label class="ink-cp-row"><span class="ink-cp-lbl">Opacity</span>
      <input type="range" class="ink-cp-alpha" min="10" max="100" step="1" aria-label="Opacity"></label>` : ""}
    <div class="ink-cp-hexrow">
      <i class="ink-cp-now" aria-hidden="true"></i>
      <input class="ink-cp-hex" maxlength="9" spellcheck="false" autocomplete="off" aria-label="Hex colour"
             placeholder="#1d4ed8">
      ${"EyeDropper" in window ? `<button type="button" class="ink-cp-eye" title="Pick a colour from the screen"
              aria-label="Pick a colour from the screen"><svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M14 4l6 6-3 1-7 7H7v-3l7-7z"/><path d="M4 20l3-3"/></svg></button>` : ""}
      <button type="button" class="ink-cp-save" title="Save to My colours" aria-label="Save to My colours">+</button>
    </div>
    <p class="ink-cp-sub" data-cp-recent-h>Recent</p><div class="ink-cp-list" data-cp-recent></div>
    <p class="ink-cp-sub" data-cp-mine-h>My colours <span>(right-click to remove)</span></p>
    <div class="ink-cp-list" data-cp-mine></div>`;

  const cv = el.querySelector("canvas"), ctx = cv.getContext("2d");
  const field = el.querySelector(".ink-cp-field"), knob = el.querySelector(".ink-cp-knob");
  const hue = el.querySelector(".ink-cp-hue"), alp = el.querySelector(".ink-cp-alpha");
  const hex = el.querySelector(".ink-cp-hex"), now = el.querySelector(".ink-cp-now");
  const st = { h: 220, s: 0.8, v: 0.8, a: 1, cur: "@blue" };

  function paintField() {
    const W = cv.width, H = cv.height;
    ctx.fillStyle = `hsl(${st.h} 100% 50%)`;
    ctx.fillRect(0, 0, W, H);
    const g1 = ctx.createLinearGradient(0, 0, W, 0);
    g1.addColorStop(0, "#fff"); g1.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g1; ctx.fillRect(0, 0, W, H);
    const g2 = ctx.createLinearGradient(0, 0, 0, H);
    g2.addColorStop(0, "rgba(0,0,0,0)"); g2.addColorStop(1, "#000");
    ctx.fillStyle = g2; ctx.fillRect(0, 0, W, H);
    knob.style.left = `${st.s * 100}%`;
    knob.style.top = `${(1 - st.v) * 100}%`;
    const [r, g, b] = hsvToRgb(st.h, st.s, st.v);
    knob.style.background = rgbToHex(r, g, b);
    field.setAttribute("aria-valuetext", `saturation ${Math.round(st.s * 100)}%, brightness ${Math.round(st.v * 100)}%`);
    if (alp) alp.style.setProperty("--c", rgbToHex(r, g, b));
  }

  function lists() {
    const s = store();
    const btn = (c, mine) => `<button type="button" class="ink-dot" data-cp="${c}" ${mine ? "data-mine" : ""}
      title="${c}" aria-label="${c}" style="--c:${c}"></button>`;
    el.querySelector("[data-cp-recent]").innerHTML = s.recent.map((c) => btn(c)).join("");
    el.querySelector("[data-cp-mine]").innerHTML = s.mine.map((c) => btn(c, true)).join("") ||
      '<span class="ink-cp-empty">Tap + to save the colour you are using</span>';
    el.querySelector("[data-cp-recent-h]").hidden = !s.recent.length;
  }

  function paint() {
    el.querySelectorAll("[data-cp]").forEach((b) => {
      const c = b.dataset.cp;
      b.style.setProperty("--c", c[0] === "@" ? ink(c) : c);
      b.classList.toggle("is-on", c === st.cur);
    });
    const shown = st.cur[0] === "@" ? ink(st.cur) : st.cur;
    now.style.setProperty("--c", shown);
    if (document.activeElement !== hex) hex.value = st.cur[0] === "@" ? ink(st.cur) : st.cur;
  }

  /** Show colour c (token or hex) without reporting it. */
  function set(c) {
    st.cur = c || "@blue";
    const [r, g, b, a] = hexToRgb(st.cur[0] === "@" ? ink(st.cur) : st.cur);
    const [h, s, v] = rgbToHsv(r, g, b);
    if (s > 0.01 && v > 0.01) st.h = h;
    st.s = s; st.v = v; st.a = a;
    hue.value = Math.round(st.h);
    if (alp) alp.value = Math.round(st.a * 100);
    paintField(); lists(); paint();
  }

  function fromHsv(final) {
    const [r, g, b] = hsvToRgb(st.h, st.s, st.v);
    st.cur = rgbToHex(r, g, b, alpha ? st.a : 1);
    paintField(); paint();
    onPick(st.cur, final);
  }

  // drag in the field
  field.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    field.setPointerCapture(e.pointerId);
    const at = (ev) => {
      const r = field.getBoundingClientRect();
      st.s = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      st.v = 1 - Math.max(0, Math.min(1, (ev.clientY - r.top) / r.height));
      fromHsv(false);
    };
    at(e);
    const up = () => {
      field.removeEventListener("pointermove", at);
      field.removeEventListener("pointerup", up);
      rememberColor(st.cur); lists(); paint();
      onPick(st.cur, true);
    };
    field.addEventListener("pointermove", at);
    field.addEventListener("pointerup", up);
  });
  field.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.1 : 0.02;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (!d) return;
    e.preventDefault(); e.stopPropagation();
    st.s = Math.max(0, Math.min(1, st.s + d[0]));
    st.v = Math.max(0, Math.min(1, st.v + d[1]));
    fromHsv(true);
  });
  hue.addEventListener("input", () => { st.h = +hue.value; fromHsv(false); });
  hue.addEventListener("change", () => { rememberColor(st.cur); lists(); paint(); onPick(st.cur, true); });
  alp?.addEventListener("input", () => { st.a = +alp.value / 100; fromHsv(false); });
  alp?.addEventListener("change", () => { rememberColor(st.cur); lists(); paint(); onPick(st.cur, true); });
  hex.addEventListener("keydown", (e) => {
    e.stopPropagation();                                   // letters are not tool hotkeys
    if (e.key === "Enter") { e.preventDefault(); hex.blur(); }
  });
  const fromHex = (final) => {
    let v = hex.value.trim();
    if (v && v[0] !== "#") v = `#${v}`;
    const ok = validHex(v);
    hex.classList.toggle("is-bad", !!v && !ok && final);
    if (!ok) return;
    set(norm(v));
    if (final) { rememberColor(st.cur); lists(); paint(); }
    onPick(st.cur, final);
  };
  hex.addEventListener("input", () => fromHex(false));
  hex.addEventListener("change", () => fromHex(true));
  el.querySelector(".ink-cp-eye")?.addEventListener("click", async () => {
    try {
      const { sRGBHex } = await new window.EyeDropper().open();
      set(norm(sRGBHex)); rememberColor(st.cur); lists(); paint(); onPick(st.cur, true);
    } catch { /* cancelled */ }
  });
  el.querySelector(".ink-cp-save").addEventListener("click", () => {
    const c = st.cur[0] === "@" ? ink(st.cur) : st.cur;
    const s = store();
    s.mine = [norm(c), ...s.mine.filter((x) => x !== norm(c))].slice(0, 18);
    keep(s); lists(); paint();
  });
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-cp]");
    if (!b) return;
    set(b.dataset.cp);
    if (b.dataset.cp[0] === "#") rememberColor(b.dataset.cp);
    lists(); paint();
    onPick(st.cur, true);
  });
  el.addEventListener("contextmenu", (e) => {
    const b = e.target.closest("[data-mine]");
    if (!b) return;
    e.preventDefault();
    const s = store();
    s.mine = s.mine.filter((x) => x !== b.dataset.cp);
    keep(s); lists(); paint();
  });

  set("@blue");
  return { el, set, repaint: paint };
}
