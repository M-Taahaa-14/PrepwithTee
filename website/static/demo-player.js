/* demo-player.js — screenshot "videos" of the real site (P3).
 *
 *   <div class="dp" data-demo="/demos/how-it-works/timeline.json"
 *        aria-label="How PrepWithTee works"></div>
 *
 * The timeline (scripts/capture_demo_shots.py) lists steps
 *   {shot, caption, chapter, cursor:[x,y] | null, click, zoom:{x,y,s} | null, dur}
 * with positions as fractions of the screen. The player shows them in a tablet
 * frame: crossfade, a slow zoom, a cursor that glides to the target and clicks,
 * a caption, and chapter buttons. It loads nothing until the section is near
 * the screen, plays only while visible, pauses on hover / focus / hidden tab,
 * and with reduced motion it just shows the frames with prev / next.
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
    this.steps.forEach((s) => { const im = new Image(); im.src = this.base + s.shot; });   // warm the cache
    this.show(0, true);
    if (!REDUCED) this.bindPlay();
  }

  render(tl) {
    const r = this.root;
    r.innerHTML = `
      <div class="dp-device"><div class="dp-screen" style="aspect-ratio:${tl.w}/${tl.h}">
        <div class="dp-stage">
          <img class="dp-img is-front" alt="" decoding="async"><img class="dp-img" alt="" decoding="async">
          <span class="dp-cursor">${CURSOR}</span><span class="dp-ripple"></span>
        </div>
        <span class="dp-paused" aria-hidden="true">Paused</span>
      </div></div>
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
    if (this.playing) this.later(() => this.show((i + 1) % this.steps.length), s.dur + (i === this.steps.length - 1 ? 1500 : 0));
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
