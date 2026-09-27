/* avatar-crop.js - crop a chosen photo before it becomes the profile picture.
 *
 *   const blob = await cropImage(file);   // null if the student cancels
 *
 * A dialog shows the photo behind a circular frame: drag (mouse, touch or pen)
 * to position it, zoom with the slider, the mouse wheel or a two-finger pinch.
 * "Save photo" renders exactly what is inside the circle to a 512 x 512 JPEG.
 * The image can never be dragged so far that the circle shows empty space.
 */
const OUT = 512;         // output size (px)
const FRAME = 280;       // on-screen crop circle (px)

let styled = false;
function addStyles() {
  if (styled) return;
  styled = true;
  const css = document.createElement("style");
  css.textContent = `
  .avc-back { position: fixed; inset: 0; z-index: 2147483600; display: grid; place-items: center; padding: 16px;
    background: rgba(15, 12, 30, .55); backdrop-filter: blur(3px); }
  .avc { width: min(420px, 100%); background: var(--white, #fff); color: var(--ink, #1a1a2e); border-radius: 22px;
    border: 1px solid var(--line, #e8dfce); box-shadow: 0 30px 80px rgba(20, 10, 50, .35); padding: 20px; display: grid; gap: 14px; }
  .avc h2 { margin: 0; font: 800 1.2rem/1.2 "Archivo", sans-serif; }
  .avc p { margin: 0; color: var(--grey, #5a5a72); font-size: .85rem; }
  .avc-stage { position: relative; width: ${FRAME}px; height: ${FRAME}px; max-width: 100%; margin: 0 auto; overflow: hidden;
    border-radius: 18px; background: #111; touch-action: none; cursor: grab; user-select: none; }
  .avc-stage:active { cursor: grabbing; }
  .avc-stage img { position: absolute; left: 0; top: 0; transform-origin: 0 0; pointer-events: none; max-width: none; }
  .avc-mask { position: absolute; inset: 0; pointer-events: none; border-radius: 18px;
    background: radial-gradient(circle at center, transparent ${FRAME / 2 - 1}px, rgba(0, 0, 0, .55) ${FRAME / 2}px); }
  .avc-mask::after { content: ""; position: absolute; inset: 0; border-radius: 50%; box-shadow: inset 0 0 0 2px rgba(255, 255, 255, .85); }
  .avc-zoom { display: flex; align-items: center; gap: 10px; font-size: .8rem; color: var(--grey, #5a5a72); }
  .avc-zoom input { flex: 1; accent-color: var(--accent, #4c2e72); }
  .avc-acts { display: flex; justify-content: flex-end; gap: 8px; }
  .avc-acts button { font: 800 .88rem/1 "Hanken Grotesk", sans-serif; border-radius: 11px; padding: .7rem 1.1rem; cursor: pointer; }
  .avc-cancel { background: transparent; border: 1.5px solid var(--line, #e8dfce); color: var(--ink, #1a1a2e); }
  .avc-save { background: var(--accent, #4c2e72); border: 0; color: var(--on-accent, #fff); }
  .avc-save:focus-visible, .avc-cancel:focus-visible { outline: 2px solid var(--gold, #e8913a); outline-offset: 2px; }`;
  document.head.appendChild(css);
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => resolve({ img, url });
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file is not an image we can read.")); };
    img.src = url;
  });
}

export async function cropImage(file) {
  addStyles();
  const { img, url } = await loadImage(file);
  const back = document.createElement("div");
  back.className = "avc-back";
  back.innerHTML = `
    <div class="avc" role="dialog" aria-modal="true" aria-labelledby="avc-t">
      <h2 id="avc-t">Adjust your photo</h2>
      <p>Drag to move it, zoom to fit your face inside the circle.</p>
      <div class="avc-stage"><div class="avc-mask"></div></div>
      <label class="avc-zoom"><span>−</span><input type="range" min="1" max="4" step="0.01" value="1" aria-label="Zoom"><span>+</span></label>
      <div class="avc-acts"><button type="button" class="avc-cancel">Cancel</button>
        <button type="button" class="avc-save">Save photo</button></div>
    </div>`;
  const stage = back.querySelector(".avc-stage");
  const zoomEl = back.querySelector('input[type="range"]');
  stage.insertBefore(img, stage.firstChild);
  document.body.appendChild(back);

  const size = stage.clientWidth;                       // square stage
  const inset = (size - Math.min(size, FRAME)) / 2;     // circle = the whole stage
  const base = size / Math.min(img.naturalWidth, img.naturalHeight);   // "cover" scale
  let zoom = 1, x = 0, y = 0;                           // image top-left in stage px

  function clamp() {
    const s = base * zoom, w = img.naturalWidth * s, h = img.naturalHeight * s;
    x = Math.min(inset, Math.max(size - inset - w, x));
    y = Math.min(inset, Math.max(size - inset - h, y));
  }
  function draw() {
    clamp();
    img.style.transform = `translate(${x}px, ${y}px) scale(${base * zoom})`;
  }
  function zoomAt(z, cx = size / 2, cy = size / 2) {
    z = Math.min(4, Math.max(1, z));
    const k = z / zoom;                                  // keep the point under the cursor fixed
    x = cx - (cx - x) * k;
    y = cy - (cy - y) * k;
    zoom = z;
    zoomEl.value = String(z);
    draw();
  }
  x = (size - img.naturalWidth * base) / 2;
  y = (size - img.naturalHeight * base) / 2;
  draw();

  // drag + pinch
  const pts = new Map();
  let last = null, pinch = null;
  stage.addEventListener("pointerdown", (e) => {
    stage.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    last = [e.clientX, e.clientY];
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), z: zoom };
    }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()];
      const r = stage.getBoundingClientRect();
      zoomAt(pinch.z * Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.d,
             (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
      return;
    }
    x += e.clientX - last[0];
    y += e.clientY - last[1];
    last = [e.clientX, e.clientY];
    draw();
  });
  const up = (e) => { pts.delete(e.pointerId); pinch = null; last = pts.size ? [...pts.values()][0] : null; };
  stage.addEventListener("pointerup", up);
  stage.addEventListener("pointercancel", up);
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    zoomAt(zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  zoomEl.addEventListener("input", () => zoomAt(parseFloat(zoomEl.value)));
  // keyboard: arrows move, +/- zoom
  stage.tabIndex = 0;
  stage.setAttribute("aria-label", "Photo position - use arrow keys to move, plus and minus to zoom");
  stage.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 20 : 6;
    if (e.key === "ArrowLeft") x += step; else if (e.key === "ArrowRight") x -= step;
    else if (e.key === "ArrowUp") y += step; else if (e.key === "ArrowDown") y -= step;
    else if (e.key === "+" || e.key === "=") return zoomAt(zoom * 1.08);
    else if (e.key === "-") return zoomAt(zoom / 1.08);
    else return;
    e.preventDefault();
    draw();
  });

  const lastFocus = document.activeElement;
  back.querySelector(".avc-save").focus();

  return new Promise((resolve) => {
    function done(result) {
      back.remove();
      URL.revokeObjectURL(url);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
      resolve(result);
    }
    back.querySelector(".avc-cancel").addEventListener("click", () => done(null));
    back.addEventListener("keydown", (e) => { if (e.key === "Escape") done(null); });
    back.addEventListener("mousedown", (e) => { if (e.target === back) done(null); });
    back.querySelector(".avc-save").addEventListener("click", () => {
      const s = base * zoom;
      const c = document.createElement("canvas");
      c.width = c.height = OUT;
      const g = c.getContext("2d");
      g.fillStyle = "#fff";
      g.fillRect(0, 0, OUT, OUT);
      // source square = the circle's box, mapped back into image pixels
      const sx = (inset - x) / s, sy = (inset - y) / s, sw = (size - 2 * inset) / s;
      g.imageSmoothingQuality = "high";
      g.drawImage(img, sx, sy, sw, sw, 0, 0, OUT, OUT);
      c.toBlob((blob) => done(blob), "image/jpeg", 0.9);
    });
  });
}
