/* ink/stickers.js — loads the sticker + stamp library (stickers.json, built by
 * scripts/build_stickers.py) and keeps one decoded image per sticker for the
 * canvas. annot_pdf.py reads the same JSON, so downloads match the screen.
 */
const CATS = [["stamps", "Stamps"], ["stickers", "Stickers"], ["emoji", "Emoji"]];
let lib = null, loading = null;
const imgs = new Map();
const waiters = new Set();

export function loadStickers(v) {
  if (lib) return Promise.resolve(lib);
  loading ||= fetch(`/ink/stickers.json?v=${v}`).then((r) => r.json()).then((d) => { lib = d; return d; })
    .catch(() => { loading = null; return {}; });
  return loading;
}

export const stickerCats = () => CATS;
export const stickerLib = () => lib || {};

/** The decoded image for sticker k, or null until it has loaded (onReady fires then). */
export function stickerImage(k, onReady) {
  if (imgs.has(k)) { const im = imgs.get(k); return im.complete && im.naturalWidth ? im : null; }
  if (!lib) { if (onReady) waiters.add(onReady); loadStickers().then(() => waiters.forEach((f) => f())); return null; }
  const s = lib[k];
  if (!s) return null;
  const im = new Image();
  im.decoding = "async";
  im.onload = () => onReady && onReady();
  im.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(s.svg)}`;
  imgs.set(k, im);
  return null;
}

export function stickerSrc(k) {
  const s = lib?.[k];
  return s ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(s.svg)}` : "";
}
