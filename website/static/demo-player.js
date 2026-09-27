/* demo-player.js — screenshot "videos" of the real site (P3).
 *
 *   <div class="dp" data-demo="/demos/hero/timeline.json" data-frame="laptop"
 *        aria-label="How PrepWithTee works"></div>
 *
 * The timeline (scripts/capture_demo_shots.py) lists steps
 *   {shot, caption, chapter, cursor:[x,y] | null, click, zoom:{x,y,s} | null, dur}
 * with positions as fractions of the screen. The player shows them in a tablet
 * frame: crossfade, a slow zoom, a cursor that glides to the target and clicks,
 * a caption, and chapter buttons. It loads nothing until the section is near
 * the screen, plays only while visible, pauses on hover / focus / hidden tab,
 * and with reduced motion it just shows the frames with prev / next.
 *
 * Extras (home-page hero, 2026-09-28):
 *   - data-frame="laptop": a MacBook-style laptop instead of a tablet; the lid
 *     swings open the first time the player comes into view.
 *   - title cards: a step may have {card: {eyebrow, title, text, buttons:[{label,
 *     href, kind}]}} instead of a shot - a full-screen slide ("Not sure where to
 *     start?", "Talk to Tee") whose buttons are real links.
 */
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CURSOR = `<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path d="M5 3l14 8-6.2 1.8L10 19z"
  fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

class DemoPlayer {
  constructor(root) {
    this.root = root;
    this.src = root.dataset.demo;
    this.base = this.src.slice(0, this.src.lastIndexOf("/") + 1);
    this.i = 0; this.playing = false; this.hold = new Set(); this.timers = [];
    this.front = 0;
  }

  async load() {
    const tl = await fetch(this.src).then((r) => r.json());
    this.steps = tl.steps;
    this.chapters = [...new Set(this.steps.map((s) => s.chapter))];
    this.render(tl);
    this.show(0, true);
    if (this.laptop) this.bindOpen();
    if (!REDUCED) this.bindPlay();
  }

  render(tl) {
    const r = this.root;
    this.laptop = r.dataset.frame === "laptop";
    const screen = `<div class="dp-screen" style="aspect-ratio:${tl.w}/${tl.h}">
        <div class="dp-stage">
          <img class="dp-img is-front" alt="" decoding="async"><img class="dp-img" alt="" decoding="async">
          <span class="dp-cursor">${CURSOR}</span><span class="dp-ripple"></span>
        </div>
        <div class="dp-card" aria-live="polite"></div>
        <span class="dp-paused" aria-hidden="true">Paused</span>
      </div>`;
    r.classList.toggle("dp-laptop", this.laptop);
    r.innerHTML = (this.laptop
      ? `<div class="dp-device dp-mac"><div class="dp-lid"><span class="dp-cam" aria-hidden="true"></span>${screen}</div>
           <div class="dp-base" aria-hidden="true"></div></div>`
      : `<div class="dp-device">${screen}</div>`) + `
      <div class="dp-caption"><span class="dp-n"></span><p aria-live="polite"></p></div>
      <div class="dp-bar">
        <button type="button" class="dp-btn" data-act="prev" aria-label="Previous">‹</button>
        <button type="button" class="dp-btn dp-play" data-act="play" aria-label="Pause">❚❚</button>
        <button type="button" class="dp-btn" data-act="next" aria-label="Next">›</button>
        <div class="dp-chapters">${this.chapters.map((c, k) => `
          <button type="button" class="dp-ch" data-ch="${k}"><i><b></b></i><span>${esc(c)}</span></button>`).join("")}</div>
      </div>`;
    this.imgs = [...r.querySelectorAll(".dp-img")];
    this.stage = r.querySelector(".dp-stage");
    this.cursor = r.querySelector(".dp-cursor");
    this.ripple = r.querySelector(".dp-ripple");
    this.card = r.querySelector(".dp-card");
    this.screenEl = r.querySelector(".dp-screen");
    if (REDUCED) r.querySelector(".dp-play").hidden = true;
    r.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      const ch = e.target.closest("[data-ch]");
      if (act === "play") return this.playing ? this.pause(true) : this.play(true);
      if (act === "prev") return this.jump(Math.max(0, this.i - 1));
      if (act === "next") return this.jump((this.i + 1) % this.steps.length);
      if (ch) return this.jump(this.steps.findIndex((s) => s.chapter === this.chapters[+ch.dataset.ch]));
    });
  }

  clear() { this.timers.forEach(clearTimeout); this.timers = []; }
  later(fn, ms) { this.timers.push(setTimeout(fn, ms)); }

  show(i, instant = false) {
    this.clear();
    this.i = i;
    const s = this.steps[i];
    // title card: a full-screen slide over the (softly blurred) last screenshot
    this.screenEl.classList.toggle("is-card", !!s.card);
    if (s.card) {
      const c = s.card;
      this.card.className = `dp-card dp-card-${c.tone || "intro"}`;
      this.card.innerHTML = `
        ${c.eyebrow ? `<span class="dp-card-eye">${esc(c.eyebrow)}</span>` : ""}
        <b class="dp-card-title">${esc(c.title)}</b>
        ${c.text ? `<span class="dp-card-text">${esc(c.text)}</span>` : ""}
        ${(c.buttons || []).length ? `<span class="dp-card-btns">${c.buttons.map((x) =>
          `<a class="dp-card-btn dp-card-btn-${esc(x.kind || "primary")}" href="${esc(x.href)}"
             ${/^https?:/.test(x.href) ? 'target="_blank" rel="noopener"' : ""}>${esc(x.label)}</a>`).join("")}</span>` : ""}`;
      this.cursor.classList.remove("is-on");
      this.stage.style.transform = "scale(1)";
    }
    if (!s.shot) { this.caption(s, i); return this.next(s, i); }
    // crossfade: load into the back image, then bring it forward
    const back = this.imgs[1 - this.front];
    back.src = this.base + s.shot;
    back.alt = s.caption;
    const swap = () => {
      back.classList.add("is-front");
      this.imgs[this.front].classList.remove("is-front");
      this.front = 1 - this.front;
    };
    back.decode ? back.decode().then(swap, swap) : swap();
    // zoom (slowly, towards the interesting part)
    const z = s.zoom;
    this.stage.style.transition = instant || REDUCED ? "none" : "";
    this.stage.style.transformOrigin = z ? `${z.x * 100}% ${z.y * 100}%` : "50% 50%";
    this.stage.style.transform = z && !REDUCED ? `scale(${z.s})` : "scale(1)";
    // cursor glides in, then clicks
    this.cursor.classList.toggle("is-on", !!s.cursor && !REDUCED);
    if (s.cursor) {
      // not a playback timer: pausing mid-step must still land the cursor on its target
      setTimeout(() => {
        if (this.i !== i) return;
        this.cursor.style.left = `${s.cursor[0] * 100}%`;
        this.cursor.style.top = `${s.cursor[1] * 100}%`;
      }, instant ? 0 : 350);
      if (s.click && !REDUCED) {
        this.later(() => {
          this.cursor.classList.add("is-click");
          Object.assign(this.ripple.style, { left: `${s.cursor[0] * 100}%`, top: `${s.cursor[1] * 100}%` });
          this.ripple.classList.remove("is-go"); void this.ripple.offsetWidth; this.ripple.classList.add("is-go");
        }, 1350);
        this.later(() => this.cursor.classList.remove("is-click"), 1650);
      }
    }
    this.caption(s, i);
    this.next(s, i);
  }

  // Fetch only the next screenshot or two (the hero must not pull ~1 MB up front).
  warm(i) {
    for (let k = 1; k <= 2; k++) {
      const n = this.steps[(i + k) % this.steps.length];
      if (n && n.shot && !n._warm) { n._warm = true; const im = new Image(); im.src = this.base + n.shot; }
    }
  }

  next(s, i) {
    this.warm(i);
    if (this.playing) this.later(() => this.show((i + 1) % this.steps.length), s.dur + (i === this.steps.length - 1 ? 1500 : 0));
  }

  caption(s, i) {
    // caption + chapter progress
    this.root.querySelector(".dp-n").textContent = `${i + 1}/${this.steps.length}`;
    this.root.querySelector(".dp-caption p").textContent = s.caption;
    const cur = this.chapters.indexOf(s.chapter);
    this.root.querySelectorAll(".dp-ch").forEach((b, k) => {
      b.classList.toggle("is-on", k === cur);
      b.classList.toggle("is-past", k < cur);
      const inCh = this.steps.map((x, j) => [x, j]).filter(([x]) => x.chapter === this.chapters[k]);
      const done = inCh.filter(([, j]) => j <= i).length;
      b.querySelector("b").style.width = k < cur ? "100%" : k > cur ? "0%" : `${(done / inCh.length) * 100}%`;
    });
  }

  // The laptop lid swings open the first time the player is on screen.
  bindOpen() {
    if (REDUCED) { this.root.classList.add("is-open"); return; }
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      setTimeout(() => this.root.classList.add("is-open"), 250);
    }, { threshold: 0.3 });
    io.observe(this.root);
  }

  jump(i) { this.show(i); }

  play(user = false) {
    if (user) this.hold.delete("user");
    if (this.hold.size || REDUCED) return;
    if (this.playing) return;
    this.playing = true;
    this.root.classList.remove("is-paused");
    const btn = this.root.querySelector(".dp-play");
    btn.textContent = "❚❚"; btn.setAttribute("aria-label", "Pause");
    this.later(() => this.show((this.i + 1) % this.steps.length), 1800);
  }

  pause(user = false) {
    if (user) this.hold.add("user");
    this.playing = false;
    this.clear();
    this.root.classList.add("is-paused");
    const btn = this.root.querySelector(".dp-play");
    if (btn) { btn.textContent = "▶"; btn.setAttribute("aria-label", "Play"); }
  }

  holdOn(why) { this.hold.add(why); this.pause(); }
  holdOff(why) { this.hold.delete(why); this.play(); }

  bindPlay() {
    const io = new IntersectionObserver(([e]) => {
      e.isIntersecting ? this.holdOff("offscreen") : this.holdOn("offscreen");
    }, { threshold: 0.45 });
    this.hold.add("offscreen");
    io.observe(this.root);
    const screen = this.root.querySelector(".dp-device");
    screen.addEventListener("mouseenter", () => this.holdOn("hover"));
    screen.addEventListener("mouseleave", () => this.holdOff("hover"));
    this.root.addEventListener("focusin", () => this.holdOn("focus"));
    this.root.addEventListener("focusout", () => this.holdOff("focus"));
    document.addEventListener("visibilitychange", () =>
      document.hidden ? this.holdOn("tab") : this.holdOff("tab"));
  }
}

// Load each player only when it gets near the screen (keeps the landing page's first paint fast).
const near = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    near.unobserve(e.target);
    new DemoPlayer(e.target).load().catch(() => {
      e.target.innerHTML = '<p class="dp-err">The demo could not load.</p>';
    });
  }
}, { rootMargin: "600px 0px" });
document.querySelectorAll(".dp[data-demo]").forEach((el) => near.observe(el));
