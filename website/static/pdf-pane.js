/* pdf-pane.js — one scrolling column of PDF pages (PDF.js), shared by the
 * booklet viewer (viewer.js) and the yearly paper viewer (paper-viewer.js).
 *
 *   pages   lazily rendered as they scroll into view (IntersectionObserver);
 *           the annotation layer keeps links and fillable fields working
 *   chips   optional per-question Explain / Guide me / Mark scheme buttons,
 *           placed from a page map: [{seq, label?, page, y, ...}]
 *   zoom    fit-to-width by default; refit() when the column changes width
 */
pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

// Standard 14 fonts + Symbol for papers that don't embed them (Greek letters, units).
export const PDF_OPTS = {
  standardFontDataUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/standard_fonts/",
  cMapUrl: "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/cmaps/", cMapPacked: true,
};

const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };

export class PdfPane {
  /**
   * @param {HTMLElement} stage   the scrolling element (pages are put inside it)
   * @param {object} opts
   *   questions  page map entries (chips + "current question"), default none
   *   chips      draw chips beside pages (default true when questions exist)
   *   gutter     px kept free beside the page on wide screens (chips column)
   *   onPage(n) / onQuestion(q) / onZoom(label)   callbacks
   *   ranged     fetch only the byte ranges the visible pages need (the server
   *              answers Range requests), so page 1 shows long before a 5-10 MB
   *              booklet has finished downloading; later pages load as you scroll
   *   uniform    every page has page 1's size (generated booklets are all A4) -
   *              skips reading every page before the first can be drawn
   */
  constructor(stage, opts = {}) {
    this.stage = stage;
    this.questions = opts.questions || [];
    this.chips = opts.chips ?? this.questions.length > 0;
    this.gutter = opts.gutter;
    this.chipHTML = opts.chipHTML;             // (q) => html, replaces the default chips
    this.ranged = !!opts.ranged;
    this.uniform = !!opts.uniform;
    this.on = { page: opts.onPage, question: opts.onQuestion, zoom: opts.onZoom,
                pageEl: opts.onPageEl };       // (el, n) for every page laid out: annotations
    this.doc = null; this.base = null; this.scale = 1; this.fit = 1; this.fitted = true;
    this.pages = []; this.obs = null; this.current = null; this.pageNo = 1;
    this.links = this._linkService();
    stage.addEventListener("scroll", debounce(() => this._onScroll(), 60));
  }

  /** `src` is a URL, or a document (promise) the caller already started loading. */
  async load(src) {
    const lazy = this.ranged ? { disableAutoFetch: true, disableStream: true, rangeChunkSize: 262144 } : {};
    this.doc = await (typeof src === "string"
      ? pdfjsLib.getDocument({ url: src, withCredentials: true, ...PDF_OPTS, ...lazy }).promise : src);
    // Pages can differ: Cambridge mark schemes are a portrait cover followed by
    // landscape (rotated) tables. Size every page, fit to the widest.
    const pages = this.uniform
      ? Array(this.doc.numPages).fill(await this.doc.getPage(1))
      : await Promise.all(Array.from({ length: this.doc.numPages }, (_, i) => this.doc.getPage(i + 1)));
    this.sizes = pages.map((p) => {
      const v = p.getViewport({ scale: 1 });
      return { w: v.width, h: v.height };
    });
    this.base = { width: Math.max(...this.sizes.map((s) => s.w)), height: this.sizes[0].h };
    this._fitWidth();
    this.layout();
    return this;
  }

  get numPages() { return this.doc?.numPages || 0; }
  get zoomLabel() { return `${Math.round(this.scale / this.fit * 100)}%`; }

  _fitWidth() {
    const gutter = this.gutter ?? (window.innerWidth >= 1000 && this.chips ? 150 : 36);
    this.fit = Math.min(1.6, Math.max(0.35, (this.stage.clientWidth - gutter) / this.base.width));
    if (this.fitted) this.scale = this.fit;
  }

  /** The column changed width (drawer, side panel, split view): a page that
   *  was fitted to the width is fitted again. */
  refit() {
    if (!this.doc) return;
    const was = this.fitted;
    this._fitWidth();
    if (was) this.setScale(this.fit, true);
  }

  setScale(s, fitted = false) {
    if (!this.doc) return;
    const ratio = this.stage.scrollTop / Math.max(1, this.stage.scrollHeight);
    this.scale = Math.min(3, Math.max(0.35, s));
    this.fitted = fitted || Math.abs(this.scale - this.fit) < 0.001;
    this.layout();
    this.stage.scrollTop = ratio * this.stage.scrollHeight;
  }

  zoomIn() { this.setScale(this.scale * 1.15); }
  zoomOut() { this.setScale(this.scale / 1.15); }
  zoomFit() { this.setScale(this.fit, true); }

  layout() {
    this.on.zoom?.(this.zoomLabel);
    this.obs?.disconnect();
    this.stage.innerHTML = "";
    this.stage.classList.toggle("has-chips", this.chips);
    this.pages = [];
    const byPage = {};
    if (this.chips) for (const q of this.questions) (byPage[q.page] ||= []).push(q);
    for (let n = 1; n <= this.doc.numPages; n++) {
      const pg = document.createElement("div");
      pg.className = "vw-pg";
      pg.dataset.n = n;
      pg.style.width = `${this.sizes[n - 1].w * this.scale}px`;
      pg.style.height = `${this.sizes[n - 1].h * this.scale}px`;
      pg.setAttribute("aria-label", `Page ${n}`);
      for (const q of byPage[n] || []) {
        const chips = document.createElement("div");
        chips.className = "vw-chips";
        chips.style.top = `${q.y * this.scale}px`;
        chips.dataset.seq = q.seq;
        const tag = q.label ? `<span class="vw-chip-q">${q.label}</span>` : "";
        chips.innerHTML = this.chipHTML ? this.chipHTML(q) : `${tag}
          <button type="button" data-open="explain" data-seq="${q.seq}" class="vw-chip">✦ Explain</button>
          <button type="button" data-open="hint" data-seq="${q.seq}" class="vw-chip">💡 Guide me</button>
          <button type="button" data-open="ms" data-seq="${q.seq}" class="vw-chip">✓ Mark scheme</button>`;
        pg.appendChild(chips);
      }
      this.stage.appendChild(pg);
      this.pages.push({ el: pg, rendered: false });
      this.on.pageEl?.(pg, n);
    }
    this.obs = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) this._render(+e.target.dataset.n);
    }, { root: this.stage, rootMargin: "900px 0px" });
    this.pages.forEach((p) => this.obs.observe(p.el));
    this._onScroll();
  }

  async _render(n) {
    const slot = this.pages[n - 1];
    if (!slot || slot.rendered) return;
    slot.rendered = true;
    const page = await this.doc.getPage(n);
    const vp = page.getViewport({ scale: this.scale });
    const dpr = window.devicePixelRatio || 1;
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(vp.width * dpr);
    canvas.height = Math.floor(vp.height * dpr);
    canvas.style.width = `${vp.width}px`;
    canvas.style.height = `${vp.height}px`;
    slot.el.prepend(canvas);
    await page.render({ canvasContext: canvas.getContext("2d"), viewport: vp,
                        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
                        annotationMode: pdfjsLib.AnnotationMode.ENABLE_FORMS }).promise;
    const layer = document.createElement("div");
    layer.className = "annotationLayer";
    slot.el.style.setProperty("--scale-factor", vp.scale);
    slot.el.insertBefore(layer, canvas.nextSibling);
    const view = vp.clone({ dontFlip: true });
    await new pdfjsLib.AnnotationLayer({ div: layer, page, viewport: view,
                                         accessibilityManager: null, annotationCanvasMap: null })
      .render({ annotations: await page.getAnnotations(), viewport: view, div: layer, page,
                linkService: this.links, annotationStorage: this.doc.annotationStorage,
                renderForms: true });
  }

  // Minimal PDF.js link service: in-document links jump inside the pane,
  // website links (logo, footer) open in a new tab.
  _linkService() {
    const pane = this;
    return {
      externalLinkEnabled: true,
      getDestinationHash: () => "#",
      getAnchorUrl: (h) => h,
      addLinkAttributes(link, url) { link.href = url; link.target = "_blank"; link.rel = "noopener"; },
      async goToDestination(dest) {
        const d = typeof dest === "string" ? await pane.doc.getDestination(dest) : dest;
        if (!Array.isArray(d)) return;
        const idx = typeof d[0] === "object" ? await pane.doc.getPageIndex(d[0]) : d[0];
        const y = d[1]?.name === "XYZ" && d[3] != null ? pane.sizes[idx].h - d[3] : 0;
        pane.scrollToPage(idx + 1, y);
      },
      goToPage(n) { pane.scrollToPage(n, 0); },
      executeNamedAction() {}, executeSetOCGState() {}, navigateTo(d) { this.goToDestination(d); },
      get pagesCount() { return pane.doc?.numPages || 0; }, page: 1, rotation: 0,
      isInPresentationMode: false,
    };
  }

  scrollToPage(n, y = 0, smooth = true) {
    const pg = this.pages[n - 1]?.el;
    if (!pg) return;
    this.stage.scrollTo({ top: pg.offsetTop + y * this.scale - 12, behavior: smooth ? "smooth" : "auto" });
  }

  scrollToQuestion(seq) {
    const q = this.questions.find((x) => x.seq === +seq);
    if (q) this.scrollToPage(q.page, q.y);
  }

  _onScroll() {
    if (!this.pages.length) return;
    const mid = this.stage.scrollTop + 80;
    let n = 1;
    for (const p of this.pages) { if (p.el.offsetTop <= mid) n = +p.el.dataset.n; else break; }
    if (n !== this.pageNo) { this.pageNo = n; }
    this.on.page?.(n);
    // The question being read: the last one that starts above the reading line.
    let cur = null;
    for (const q of this.questions) {
      const top = this.pages[q.page - 1]?.el.offsetTop + q.y * this.scale;
      if (top <= mid + 40) cur = q; else break;
    }
    if (cur?.seq !== this.current?.seq) { this.current = cur; this.on.question?.(cur); }
  }

  destroy() {
    this.obs?.disconnect();
    this.doc?.destroy();
    this.stage.innerHTML = "";
  }
}

export { debounce };
