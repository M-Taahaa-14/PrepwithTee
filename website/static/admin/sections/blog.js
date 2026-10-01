import { $, $$, api, esc, icon, pill, rel, fmtDate, toast, tabBar, loadingHtml, emptyState, num } from "../core.js";
import { DataTable } from "../datatable.js";

export const title = "Blog";

export const STATE = { draft: ["Draft", "warn"], scheduled: ["Scheduled", "info"], published: ["Published", "ok"] };

export async function render(el, { params, setParams, ctx }) {
  const tab = params.tab === "ideas" ? "ideas" : "posts";
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Blog studio</h1>
      <p>Write with the AI, edit, schedule and publish. Every save keeps a revision.</p></div>
      <button class="btn primary" data-new>${icon("plus")} New post</button></div>
    <div id="b-tabs"></div><div id="b-body">${loadingHtml()}</div>`;
  $("#b-tabs", el).innerHTML = tabBar([["posts", "Posts"], ["ideas", "Ideas from your students"]], tab);
  $$("#b-tabs .tab", el).forEach(b => b.addEventListener("click", () => {
    setParams({ tab: b.dataset.tab }); render(el, { params: { tab: b.dataset.tab }, setParams, ctx });
  }));
  $("[data-new]", el).addEventListener("click", () => newPost());
  const body = $("#b-body", el);
  if (tab === "ideas") return ideas(body);
  const { q = "", sort, dir, page, per, tab: _t, ...filters } = params;
  new DataTable(body, {
    id: "blog", noun: "posts", searchPlaceholder: "Search titles",
    state: { q, sort: sort || "updated_at", dir: dir || "desc", page: +page || 1, per: +per || 50, filters },
    loadAll: async () => (await api("/api/admin/blog/posts")).posts,
    searchText: r => `${r.title} ${r.slug} ${r.keywords || ""}`,
    onState: s => setParams(s),
    filters: [{ key: "state", label: "Any state", value: r => r.state,
                options: c => Object.keys(STATE).map(k => ({ value: k, label: STATE[k][0], count: c[k] || 0 })) }],
    columns: [
      { key: "title", label: "Post", sort: true, firstDir: "asc",
        render: r => `<b>${esc(r.title)}</b><div class="small faint">/blog/${esc(r.slug)}</div>` },
      { key: "state", label: "State", sort: true, render: r => pill(...STATE[r.state]) },
      { key: "when", label: "Live", sortValue: r => r.publish_at || r.published_at || "", sort: true,
        render: r => r.state === "scheduled" ? `${esc(fmtDate(r.publish_at))} <span class="small faint">${esc(rel(r.publish_at))}</span>`
          : r.state === "published" ? esc(fmtDate(r.published_at)) : `<span class="faint">—</span>` },
      { key: "words", label: "Words", sort: true, num: true, render: r => num(r.words) },
      { key: "updated_at", label: "Edited", sort: true, render: r => esc(rel(r.updated_at)) },
    ],
    onOpen: r => { location.hash = `#/post/${r.id}`; },
  });
}

export async function newPost(extra = {}, prompt = "") {
  try {
    const { post } = await api("/api/admin/blog/posts", { method: "POST", body: { title: "Untitled post", ...extra } });
    location.hash = `#/post/${post.id}${prompt ? `?prompt=${encodeURIComponent(prompt)}` : ""}`;
  } catch (ex) { toast(ex.message, true); }
}

async function ideas(body) {
  const draw = async polish => {
    body.innerHTML = loadingHtml(polish ? "Asking the AI for titles…" : "Reading your students' data…");
    let d;
    try { d = await api(`/api/admin/blog/ideas${polish ? "?polish=true" : ""}`); }
    catch (ex) { body.innerHTML = `<div class="card">${emptyState("alert-triangle", ex.message)}</div>`; return; }
    const tone = { request: ["Students asked", "t-amber", "message-question"], weak: ["Low scores", "t-rose", "trending-down"],
                   popular: ["Most practised", "t-teal", "flame"] };
    body.innerHTML = `<div class="toolbar-row"><span class="muted small grow">Built from subject requests, AI-quiz scores and the booklets students build.</span>
        <button class="btn" data-polish>${icon("sparkles")} Better titles with AI</button></div>
      ${d.ideas.length ? `<div class="idea-grid">${d.ideas.map((i, n) => `<div class="card idea">
          <div class="row"><span class="kpi-ic ${tone[i.kind][1]}">${icon(tone[i.kind][2])}</span><span class="small muted">${esc(tone[i.kind][0])}</span></div>
          <h3>${esc(i.title)}</h3>${i.angle ? `<p class="small muted">${esc(i.angle)}</p>` : ""}
          <p class="small faint">${esc(i.why)}</p>
          <button class="btn primary sm" data-draft="${n}">${icon("pencil")} Draft this</button></div>`).join("")}</div>`
        : `<div class="card">${emptyState("bulb", "No signals yet.", "Ideas appear as students use quizzes, booklets and subject requests.")}</div>`}`;
    $("[data-polish]", body).addEventListener("click", () => draw(true));
    $$("[data-draft]", body).forEach(b => b.addEventListener("click", () => {
      const i = d.ideas[+b.dataset.draft];
      newPost({ title: i.title }, `${i.title}. ${i.angle || ""} Why now: ${i.why}.`);
    }));
  };
  draw(false);
}
