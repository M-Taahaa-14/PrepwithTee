// One table component for every admin list.
//
//   new DataTable(el, {
//     id, columns, rowId, searchPlaceholder, filters, bulk, onOpen, views,
//     load(state) -> {rows, total, facets}    // server-side: the server filters/sorts/pages
//     | loadAll() -> rows                      // client-side: filtered/sorted/paged here
//     csv(state) -> url, state, onState(state)
//   })
//
// The toolbar (search box, filters) is built ONCE; typing never rebuilds the
// input, so focus and the caret stay put. Only the body, footer and the
// options inside the filter <select>s are refreshed.

import { $, $$, api, esc, icon, debounce, emptyState, modal, toast } from "./core.js";

const DEFAULTS = { q: "", sort: null, dir: "desc", page: 1, per: 50, filters: {} };

export class DataTable {
  constructor(el, opts) {
    this.el = el;
    this.o = opts;
    this.state = { ...DEFAULTS, ...structuredClone(opts.state || {}) };
    this.state.filters = { ...(opts.state?.filters || {}) };
    if (!this.state.sort) {
      this.state.sort = opts.defaultSort || opts.columns.find(c => c.sort)?.key;
      this.state.dir = opts.defaultDir || "desc";
    }
    this.rows = [];
    this.total = 0;
    this.selected = new Map();          // id -> row (survives paging)
    this.all = null;                    // client-side mode cache
    this.seq = 0;
    this.prefs = this._loadPrefs();
    this._build();
    this.reload();
  }

  /* ── preferences: visible columns, order, density ─────────────────── */
  _loadPrefs() {
    const base = { order: this.o.columns.map(c => c.key),
                   hidden: this.o.columns.filter(c => c.hidden).map(c => c.key), compact: false };
    try {
      const saved = JSON.parse(localStorage.getItem(`pwt-admin-dt:${this.o.id}`) || "null");
      if (saved) {
        const keys = new Set(base.order);
        const order = saved.order.filter(k => keys.has(k));
        base.order.forEach(k => { if (!order.includes(k)) order.push(k); });
        return { order, hidden: saved.hidden.filter(k => keys.has(k)), compact: !!saved.compact };
      }
    } catch { /* storage blocked or corrupt: defaults */ }
    return base;
  }
  _savePrefs() {
    try { localStorage.setItem(`pwt-admin-dt:${this.o.id}`, JSON.stringify(this.prefs)); } catch { /* ok */ }
  }
  get cols() {
    const by = Object.fromEntries(this.o.columns.map(c => [c.key, c]));
    return this.prefs.order.map(k => by[k]).filter(c => c && !this.prefs.hidden.includes(c.key));
  }

  /* ── skeleton ─────────────────────────────────────────────────────── */
  _build() {
    const o = this.o;
    const filters = (o.filters || []).map(f => `
      <label class="sr-only" for="f-${o.id}-${f.key}">${esc(f.label)}</label>
      <select class="select" id="f-${o.id}-${f.key}" data-filter="${f.key}">
        <option value="">${esc(f.label)}</option></select>`).join("");
    this.el.innerHTML = `
      <div class="dt-toolbar">
        <label class="sr-only" for="q-${o.id}">Search</label>
        <input class="input search" id="q-${o.id}" type="search" autocomplete="off"
          placeholder="${esc(o.searchPlaceholder || "Search")}" value="${esc(this.state.q)}">
        ${filters}
        <span class="rel">
          <button class="btn" data-act="cols" aria-haspopup="true">${icon("columns-3")} Columns</button>
        </span>
        <button class="btn icon" data-act="density" aria-label="Toggle compact rows" title="Compact rows">${icon("baseline-density-medium")}</button>
        ${o.csv ? `<button class="btn" data-act="csv">${icon("download")} CSV</button>` : ""}
        <button class="btn icon" data-act="reload" aria-label="Refresh" title="Refresh">${icon("refresh")}</button>
      </div>
      ${o.views ? `<div class="dt-views" data-views></div>` : ""}
      <div class="dt-bulk" data-bulk hidden></div>
      <div class="dt-wrap"><table class="dt${this.prefs.compact ? " compact" : ""}">
        <thead></thead><tbody></tbody></table></div>
      <div class="dt-foot" data-foot></div>`;

    this.table = $("table", this.el);
    const search = $(`#q-${o.id}`, this.el);
    const go = debounce(() => { this.state.q = search.value; this.state.page = 1; this.reload(); }, 280);
    search.addEventListener("input", go);
    $$("[data-filter]", this.el).forEach(sel => {
      sel.value = this.state.filters[sel.dataset.filter] || "";
      sel.addEventListener("change", () => {
        if (sel.value) this.state.filters[sel.dataset.filter] = sel.value;
        else delete this.state.filters[sel.dataset.filter];
        this.state.page = 1;
        this.reload();
      });
    });
    $("[data-act=cols]", this.el).addEventListener("click", e => this._colsPopover(e.currentTarget));
    $("[data-act=density]", this.el).addEventListener("click", () => {
      this.prefs.compact = !this.prefs.compact;
      this.table.classList.toggle("compact", this.prefs.compact);
      this._savePrefs();
    });
    $("[data-act=reload]", this.el).addEventListener("click", () => { this.all = null; this.reload(true); });
    $("[data-act=csv]", this.el)?.addEventListener("click", () => { location.href = o.csv(this._publicState()); });

    this.table.addEventListener("click", e => this._onTableClick(e));
    this.table.addEventListener("change", e => this._onTableChange(e));
    if (o.views) this._loadViews();
    this._renderHead();
  }

  _publicState() {
    const s = this.state;
    return { q: s.q, sort: s.sort, dir: s.dir, page: s.page, per: s.per, ...s.filters };
  }

  /* ── data ─────────────────────────────────────────────────────────── */
  async reload(fresh = false) {
    const seq = ++this.seq;
    this.table.classList.add("busy");
    try {
      let out;
      if (this.o.loadAll) {
        if (!this.all || fresh) this.all = await this.o.loadAll(fresh);
        out = this._clientQuery(this.all);
      } else {
        out = await this.o.load(this._publicState(), fresh);
      }
      if (seq !== this.seq) return;               // a newer request won
      this.rows = out.rows;
      this.total = out.total;
      this.facets = out.facets || this._clientFacets();
      this.meta = out;                              // whole response: options(counts, meta)
      this._fillFilterOptions();
      this._renderBody();
      this._renderFoot();
      this.o.onState?.(this._publicState());
    } catch (ex) {
      if (seq !== this.seq) return;
      $("tbody", this.table).innerHTML =
        `<tr><td colspan="${this.cols.length + 1}">${emptyState("alert-triangle", "Couldn't load this list.", ex.message)}</td></tr>`;
    } finally {
      if (seq === this.seq) this.table.classList.remove("busy");
    }
  }

  _clientQuery(all) {
    const s = this.state;
    const q = s.q.trim().toLowerCase();
    let rows = all.filter(r => {
      if (q && !(this.o.searchText?.(r) ?? JSON.stringify(r)).toLowerCase().includes(q)) return false;
      for (const f of this.o.filters || []) {
        const want = s.filters[f.key];
        if (!want) continue;
        const have = f.value(r);
        if (Array.isArray(have) ? !have.includes(want) : String(have ?? "") !== want) return false;
      }
      return true;
    });
    const col = this.o.columns.find(c => c.key === s.sort);
    if (col) {
      const val = col.sortValue || (r => r[col.key]);
      const dir = s.dir === "asc" ? 1 : -1;
      rows = [...rows].sort((a, b) => {
        const x = val(a), y = val(b);
        if (x === y) return 0;
        if (x === null || x === undefined || x === "") return 1;
        if (y === null || y === undefined || y === "") return -1;
        return (x > y ? 1 : -1) * dir;
      });
    }
    const start = (s.page - 1) * s.per;
    return { rows: rows.slice(start, start + s.per), total: rows.length };
  }

  _clientFacets() {
    if (!this.all) return {};
    const out = {};
    for (const f of this.o.filters || []) {
      if (!f.value) continue;
      out[f.key] = {};
      for (const r of this.all) {
        const v = f.value(r);
        for (const x of Array.isArray(v) ? v : [v]) {
          if (x !== undefined && x !== null && x !== "") out[f.key][x] = (out[f.key][x] || 0) + 1;
        }
      }
    }
    return out;
  }

  _fillFilterOptions() {
    for (const f of this.o.filters || []) {
      const sel = $(`[data-filter="${f.key}"]`, this.el);
      if (!sel) continue;
      const counts = this.facets?.[f.key] || {};
      const opts = f.options ? f.options(counts, this.meta || {})
        : Object.keys(counts).sort().map(v => ({ value: v, label: f.label_for?.(v) || v, count: counts[v] }));
      const cur = this.state.filters[f.key] || "";
      sel.innerHTML = `<option value="">${esc(f.label)}</option>` + opts.map(op =>
        `<option value="${esc(op.value)}">${esc(op.label)}${op.count !== undefined ? ` (${op.count})` : ""}</option>`).join("");
      sel.value = cur;
      sel.classList.toggle("on", !!cur);
    }
  }

  /* ── head / body / foot ───────────────────────────────────────────── */
  _renderHead() {
    const s = this.state;
    const ths = this.cols.map(c => {
      const cls = c.num ? ' class="num"' : "";
      if (!c.sort) return `<th scope="col"${cls}><span class="static">${esc(c.label)}</span></th>`;
      const on = s.sort === c.key;
      const aria = on ? (s.dir === "asc" ? "ascending" : "descending") : "none";
      const arrow = on ? icon(s.dir === "asc" ? "arrow-up" : "arrow-down") : "";
      return `<th scope="col"${cls} aria-sort="${aria}"><button class="sort" data-sort="${c.key}">${esc(c.label)}${arrow}</button></th>`;
    }).join("");
    $("thead", this.table).innerHTML = `<tr>${this.o.bulk ? `<th class="cb"><input type="checkbox" data-all aria-label="Select all on this page"></th>` : ""}${ths}</tr>`;
  }

  _renderBody() {
    const id = this.o.rowId || (r => r.id);
    const tbody = $("tbody", this.table);
    if (!this.rows.length) {
      tbody.innerHTML = `<tr><td colspan="${this.cols.length + 1}">${emptyState("mood-empty",
        this.state.q || Object.keys(this.state.filters).length ? "Nothing matches these filters." : (this.o.emptyText || "Nothing here yet."))}</td></tr>`;
    } else {
      tbody.innerHTML = this.rows.map((r, i) => {
        const rid = String(id(r));
        const sel = this.selected.has(rid);
        const cells = this.cols.map(c => `<td${c.num ? ' class="num"' : ""}>${c.render ? c.render(r) : esc(r[c.key] ?? "—")}</td>`).join("");
        return `<tr data-i="${i}" class="${this.o.onOpen ? "click" : ""}${sel ? " sel" : ""}">
          ${this.o.bulk ? `<td class="cb"><input type="checkbox" data-row="${esc(rid)}" ${sel ? "checked" : ""} aria-label="Select row"></td>` : ""}${cells}</tr>`;
      }).join("");
    }
    const all = $("[data-all]", this.table);
    if (all) all.checked = this.rows.length > 0 && this.rows.every(r => this.selected.has(String(id(r))));
    this._renderBulk();
  }

  _renderFoot() {
    const s = this.state;
    const from = this.total ? (s.page - 1) * s.per + 1 : 0;
    const to = Math.min(this.total, s.page * s.per);
    const pages = Math.max(1, Math.ceil(this.total / s.per));
    const foot = $("[data-foot]", this.el);
    foot.innerHTML = `
      <span>${from.toLocaleString()}–${to.toLocaleString()} of ${this.total.toLocaleString()}${this.o.noun ? ` ${esc(this.o.noun)}` : ""}</span>
      <span class="grow"></span>
      <label class="row">Rows <select class="select" data-per>${[25, 50, 100, 250].map(n =>
        `<option${n === s.per ? " selected" : ""}>${n}</option>`).join("")}</select></label>
      <button class="btn sm icon" data-page="-1" aria-label="Previous page" ${s.page <= 1 ? "disabled" : ""}>${icon("chevron-left")}</button>
      <span>Page ${s.page} of ${pages}</span>
      <button class="btn sm icon" data-page="1" aria-label="Next page" ${s.page >= pages ? "disabled" : ""}>${icon("chevron-right")}</button>`;
    $("[data-per]", foot).addEventListener("change", e => { s.per = +e.target.value; s.page = 1; this.reload(); });
    $$("[data-page]", foot).forEach(b => b.addEventListener("click", () => {
      s.page = Math.min(pages, Math.max(1, s.page + +b.dataset.page)); this.reload();
    }));
  }

  _renderBulk() {
    const bar = $("[data-bulk]", this.el);
    if (!this.o.bulk || !this.selected.size) { bar.hidden = true; bar.innerHTML = ""; return; }
    bar.hidden = false;
    bar.innerHTML = `<span>${this.selected.size} selected</span>` +
      this.o.bulk.map((b, i) => `<button class="btn sm" data-bulk-i="${i}">${b.icon ? icon(b.icon) : ""}${esc(b.label)}</button>`).join("") +
      `<span class="grow"></span><button class="btn sm ghost" data-bulk-clear>Clear selection</button>`;
    $$("[data-bulk-i]", bar).forEach(btn => btn.addEventListener("click", async () => {
      const action = this.o.bulk[+btn.dataset.bulkI];
      const done = await action.run([...this.selected.values()], this);
      if (done) { this.selected.clear(); this.all = null; this.reload(true); }
    }));
    $("[data-bulk-clear]", bar).addEventListener("click", () => { this.selected.clear(); this._renderBody(); });
  }

  /* ── events ───────────────────────────────────────────────────────── */
  _onTableClick(e) {
    const sortBtn = e.target.closest("[data-sort]");
    if (sortBtn) {
      const k = sortBtn.dataset.sort;
      if (this.state.sort === k) this.state.dir = this.state.dir === "asc" ? "desc" : "asc";
      else { this.state.sort = k; this.state.dir = this.o.columns.find(c => c.key === k)?.firstDir || "desc"; }
      this.state.page = 1;
      this._renderHead();
      this.reload();
      return;
    }
    if (e.target.closest("input, a, button, label")) return;
    const tr = e.target.closest("tbody tr[data-i]");
    if (tr && this.o.onOpen) this.o.onOpen(this.rows[+tr.dataset.i], e);
  }

  _onTableChange(e) {
    const id = this.o.rowId || (r => r.id);
    if (e.target.matches("[data-all]")) {
      this.rows.forEach(r => e.target.checked ? this.selected.set(String(id(r)), r) : this.selected.delete(String(id(r))));
      this._renderBody();
    } else if (e.target.matches("[data-row]")) {
      const r = this.rows.find(x => String(id(x)) === e.target.dataset.row);
      if (e.target.checked) this.selected.set(e.target.dataset.row, r); else this.selected.delete(e.target.dataset.row);
      e.target.closest("tr").classList.toggle("sel", e.target.checked);
      const all = $("[data-all]", this.table);
      if (all) all.checked = this.rows.every(x => this.selected.has(String(id(x))));
      this._renderBulk();
    }
  }

  /* ── columns popover ──────────────────────────────────────────────── */
  _colsPopover(anchor) {
    const open = $(".cols-pop", this.el);
    if (open) { open.remove(); return; }
    const by = Object.fromEntries(this.o.columns.map(c => [c.key, c]));
    const pop = document.createElement("div");
    pop.className = "cols-pop";
    const draw = () => {
      pop.innerHTML = `<div class="small faint">Show, hide and order columns</div>` + this.prefs.order.map((k, i) => `
        <div class="col-row">
          <label class="check"><input type="checkbox" data-col="${k}" ${this.prefs.hidden.includes(k) ? "" : "checked"}>${esc(by[k].label || k)}</label>
          <button class="btn sm icon ghost" data-up="${i}" aria-label="Move ${esc(by[k].label)} up" ${i === 0 ? "disabled" : ""}>${icon("chevron-up")}</button>
          <button class="btn sm icon ghost" data-down="${i}" aria-label="Move ${esc(by[k].label)} down" ${i === this.prefs.order.length - 1 ? "disabled" : ""}>${icon("chevron-down")}</button>
        </div>`).join("") + `<div class="row"><button class="btn sm ghost" data-reset>Reset</button></div>`;
    };
    draw();
    pop.addEventListener("click", e => {
      const up = e.target.closest("[data-up]"), down = e.target.closest("[data-down]");
      const o = this.prefs.order;
      if (up) { const i = +up.dataset.up; [o[i - 1], o[i]] = [o[i], o[i - 1]]; }
      else if (down) { const i = +down.dataset.down; [o[i + 1], o[i]] = [o[i], o[i + 1]]; }
      else if (e.target.closest("[data-reset]")) {
        try { localStorage.removeItem(`pwt-admin-dt:${this.o.id}`); } catch { /* ok */ }
        this.prefs = this._loadPrefs();
      } else return;
      this._savePrefs(); draw(); this._renderHead(); this._renderBody();
    });
    pop.addEventListener("change", e => {
      const k = e.target.dataset.col;
      if (!k) return;
      this.prefs.hidden = e.target.checked ? this.prefs.hidden.filter(x => x !== k) : [...this.prefs.hidden, k];
      this._savePrefs(); this._renderHead(); this._renderBody();
    });
    anchor.parentElement.append(pop);
    const off = e => { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) { pop.remove(); document.removeEventListener("mousedown", off); } };
    setTimeout(() => document.addEventListener("mousedown", off));
  }

  /* ── saved views ──────────────────────────────────────────────────── */
  async _loadViews() {
    const box = $("[data-views]", this.el);
    let views = [];
    try { views = (await api(`/api/admin/views?section=${encodeURIComponent(this.o.views)}`)).views; }
    catch { /* views are optional */ }
    const builtin = this.o.builtinViews || [];
    const isOn = p => JSON.stringify(normalise(p)) === JSON.stringify(normalise({ q: this.state.q, ...this.state.filters }));
    box.innerHTML = `<span class="lbl">Views</span>` +
      [{ name: "Everyone", params: {} }, ...builtin].map((v, i) =>
        `<button class="chip${isOn(v.params) ? " on" : ""}" data-builtin="${i}">${esc(v.name)}</button>`).join("") +
      views.map(v => `<span class="chip${isOn(v.params) ? " on" : ""}" data-view="${v.id}" role="button" tabindex="0">${esc(v.name)}
        <button class="btn ghost sm icon x" data-del="${v.id}" aria-label="Delete view ${esc(v.name)}">${icon("x")}</button></span>`).join("") +
      `<button class="chip" data-save>${icon("plus")} Save view</button>`;
    const apply = params => {
      const { q = "", ...filters } = params;
      this.state.q = q; this.state.filters = { ...filters }; this.state.page = 1;
      $(`#q-${this.o.id}`, this.el).value = q;
      this.reload().then(() => this._loadViews());
    };
    $$("[data-builtin]", box).forEach(b => b.addEventListener("click", () =>
      apply([{ params: {} }, ...builtin][+b.dataset.builtin].params)));
    $$("[data-view]", box).forEach(c => {
      const go = e => { if (e.target.closest("[data-del]")) return; apply(views.find(v => v.id == c.dataset.view).params); };
      c.addEventListener("click", go);
      c.addEventListener("keydown", e => { if (e.key === "Enter") go(e); });
    });
    $$("[data-del]", box).forEach(b => b.addEventListener("click", async e => {
      e.stopPropagation();
      await api(`/api/admin/views/${b.dataset.del}`, { method: "DELETE" });
      this._loadViews();
    }));
    $("[data-save]", box).addEventListener("click", async () => {
      const ok = await modal({
        title: "Save this view", submit: "Save view",
        body: `<label class="field"><span>Name</span><input class="input" name="name" required maxlength="60"
          placeholder="Inactive O Level students" autofocus></label>
          <p class="small muted">Saves the current search and filters.</p>`,
        run: async el => {
          const name = $("[name=name]", el).value.trim();
          if (!name) return "Give the view a name.";
          await api("/api/admin/views", { method: "POST",
            body: { section: this.o.views, name, params: { q: this.state.q, ...this.state.filters } } });
          return true;
        } });
      if (ok) { toast("View saved"); this._loadViews(); }
    });
  }
}

function normalise(p) {
  const out = {};
  Object.keys(p).sort().forEach(k => { if (p[k] !== "" && p[k] != null) out[k] = String(p[k]); });
  return out;
}
