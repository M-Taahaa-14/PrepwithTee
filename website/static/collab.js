/* Shared ink, near-live: a teacher and their student draw on ONE layer per page.
 *
 *   const c = collab({ doc: "booklet:abc123:ms", me });
 *   const ann = createAnnotator({ store: c.store, ... });
 *   c.connect(ann, { page: () => currentPageNumber });
 *
 * Saves are optimistic (version per page). On a 409 the page is merged three
 * ways - what we last agreed on (base), mine, theirs - by object id, then saved
 * again, so two people drawing at once both keep their work. A poll every 1.5 s
 * (someone else here) or 6 s (alone) brings the other person's saves in; a page
 * that is busy locally (stroke, drag, text box, unsaved edit) waits for its own
 * save, which merges them. Polling stops while the tab is hidden.
 *
 * Whiteboards (static/board/app.js) use merge3 with their own endpoints.
 */

const FAST = 1500, SLOW = 6000;

async function req(method, url, body) {
  const r = await fetch(url, { method, credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(`collab ${r.status}`); e.status = r.status; e.data = data; throw e; }
  return data;
}

const sig = (o) => JSON.stringify(o, Object.keys(o).filter((k) => k !== "by").sort());

/** Three-way merge by object id. base = Map(id -> signature) of the last copy
 *  both sides agreed on. Mine wins for objects I changed; I take theirs for
 *  objects I didn't touch; a delete on either side sticks unless the other
 *  side changed that object since. Order: theirs, then my new objects. */
export function merge3(base, mine, theirs) {
  const mineById = new Map(mine.map((o) => [o.id, o]));
  const theirsById = new Map(theirs.map((o) => [o.id, o]));
  const changedByMe = (id) => !base.has(id) || base.get(id) !== sig(mineById.get(id));
  const out = [];
  const used = new Set();
  for (const t of theirs) {
    const m = mineById.get(t.id);
    if (m) out.push(changedByMe(t.id) ? m : t);
    else if (!base.has(t.id) || base.get(t.id) !== sig(t)) out.push(t);   // I deleted it: keep only if they changed it
    used.add(t.id);
  }
  for (const m of mine) {
    if (used.has(m.id)) continue;
    // not on their side: new from me, or they deleted it (keep only if I changed it)
    if (!base.has(m.id) || changedByMe(m.id)) out.push(m);
  }
  return out;
}

export const baseOf = (objects) => new Map((objects || []).map((o) => [o.id, sig(o)]));

export function collab({ doc, me, onPeople = null, onError = null }) {
  const S = { versions: new Map(), base: new Map(), since: null, ann: null, timer: 0, here: [],
              people: [], waiting: new Map(), stopped: false, page: () => null };

  const store = {
    async load(d) {
      const data = await req("GET", `/api/collab?doc=${encodeURIComponent(d)}`);
      S.since = data.now;
      S.people = data.people || [];
      const pages = {};
      for (const [pg, v] of Object.entries(data.pages || {})) {
        S.versions.set(pg, v.version);
        S.base.set(pg, baseOf(v.objects));
        pages[pg] = v.objects;
      }
      setHere(data.here || []);
      return pages;
    },
    async save(d, page, objects) {
      const pg = String(page);
      for (const o of objects) if (!o.by) o.by = me;            // authorship of new ink
      let list = objects;
      for (let tries = 0; tries < 5; tries++) {
        try {
          const r = await req("PUT", "/api/collab", { doc: d, page: Number(page), objects: list,
                                                     version: S.versions.get(pg) || 0 });
          S.versions.set(pg, r.version);
          S.base.set(pg, baseOf(r.objects || list));
          return;
        } catch (e) {
          if (e.status !== 409 || e.data?.code !== "stale") { onError?.(e); throw e; }
          const theirs = e.data.objects || [];
          list = merge3(S.base.get(pg) || new Map(), list, theirs);
          S.versions.set(pg, e.data.version || 0);
          S.base.set(pg, baseOf(theirs));
          const p = S.ann?.page(d, page);
          if (p) { p.strokes = list; S.ann.repaint(); }
        }
      }
      throw new Error("Couldn't save - too many changes at once. Try again.");
    },
  };

  function setHere(list) {
    S.here = list;
    onPeople?.(list, S.people);
  }

  async function applyPage(r) {
    const pg = String(r.page);
    if ((S.versions.get(pg) || 0) >= r.version) return true;
    if (!(await S.ann.remote(doc, r.page, r.objects))) return false;    // busy: try next tick
    S.versions.set(pg, r.version);
    S.base.set(pg, baseOf(r.objects));
    return true;
  }

  async function tick() {
    S.timer = 0;
    if (S.stopped) return;
    if (document.hidden) return;                       // resumes on visibilitychange
    try {
      const q = new URLSearchParams({ doc, since: S.since || "" });
      const pg = S.page();
      if (pg != null) q.set("page", String(pg));
      const data = await req("GET", `/api/collab/poll?${q}`);
      S.since = data.now;
      for (const r of data.pages || []) S.waiting.set(String(r.page), r);
      for (const [pg2, r] of [...S.waiting]) if (await applyPage(r)) S.waiting.delete(pg2);
      setHere(data.here || []);
    } catch (e) {
      if (e.status === 401 || e.status === 404 || e.status === 409) { S.stopped = true; return; }
    }
    schedule();
  }

  function schedule() {
    clearTimeout(S.timer);
    if (S.stopped || document.hidden) return;
    S.timer = setTimeout(tick, S.here.length || S.waiting.size ? FAST : SLOW);
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) { clearTimeout(S.timer); tick(); } });

  return {
    store,
    connect(ann, { page } = {}) {
      S.ann = ann;
      if (page) S.page = page;
      schedule();
    },
    get here() { return S.here; },
    get people() { return S.people; },
    stop() { S.stopped = true; clearTimeout(S.timer); },
  };
}

/* ── the little "who's here" bar ─────────────────────────────────────────── */

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const initials = (n) => (n || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

/** Presence dots + "Show only my ink" toggle. Returns an onPeople callback.
 *  host: where the bar goes; ann: the annotator (for hideAuthors). */
export function presenceBar(host, { me, label = "Shared with your teacher", getAnn }) {
  if (!document.querySelector('link[href^="/collab.css"]')) {
    const l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "/collab.css?v=20261009a";
    document.head.appendChild(l);
  }
  const bar = document.createElement("div");
  bar.className = "collab-bar";
  bar.innerHTML = `<span class="collab-live" title="Changes appear for both of you within a second or two">
      <span class="collab-dot"></span><span class="collab-label">${esc(label)}</span></span>
    <span class="collab-faces"></span>
    <button type="button" class="collab-hide" aria-pressed="false">Hide other ink</button>`;
  host.appendChild(bar);
  let people = [];
  const btn = bar.querySelector(".collab-hide");
  btn.addEventListener("click", () => {
    const on = btn.getAttribute("aria-pressed") !== "true";
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = on ? "Show all ink" : "Hide other ink";
    const others = people.map((p) => p.id).filter((id) => id !== me);
    getAnn()?.hideAuthors(on ? others : null);
  });
  return (here, everyone) => {
    people = everyone || people;
    const faces = bar.querySelector(".collab-faces");
    faces.innerHTML = here.map((p) => `<span class="collab-face${p.teacher ? " is-teacher" : ""}"
        title="${esc(p.name)} is here${p.page ? ` (page ${esc(p.page)})` : ""}">${esc(initials(p.name))}</span>`).join("");
    bar.classList.toggle("has-company", here.length > 0);
    bar.querySelector(".collab-label").textContent = here.length
      ? `${here.map((p) => p.name.split(" ")[0]).join(", ")} ${here.length > 1 ? "are" : "is"} here`
      : label;
  };
}
