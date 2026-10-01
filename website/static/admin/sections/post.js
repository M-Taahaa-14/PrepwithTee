// Blog post editor: Markdown with a live preview, AI writer (outline -> draft),
// AI edits on the selected text, SEO checks + Google preview, FAQ, cover,
// scheduling and revision history.

import { $, $$, api, esc, icon, pill, rel, fmtDate, toast, confirmBox, drawer, loadingHtml,
         emptyState, lookup, debounce } from "../core.js";
import { STATE } from "./blog.js";

export const title = "Edit post";

const AI_ACTIONS = [["rewrite", "Rewrite"], ["simplify", "Simpler"], ["shorten", "Shorter"], ["expand", "Expand"],
                    ["add_example", "Add example"], ["continue", "Continue writing"]];
let lib = null;
async function md() {               // marked + DOMPurify, only when the editor opens
  if (!lib) {
    const [{ marked }, purify] = await Promise.all([
      import("https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js"),
      import("https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.es.mjs")]);
    lib = text => purify.default.sanitize(marked.parse(text || ""));
  }
  return lib;
}

export async function render(el, { rest, params, setParams }) {
  const id = rest[0];
  el.innerHTML = `<a class="back" href="#/blog">${icon("arrow-left")} Blog</a><div id="pe">${loadingHtml()}</div>`;
  let d, subjects;
  try { [d, subjects] = await Promise.all([api(`/api/admin/blog/posts/${encodeURIComponent(id)}`), lookup("subjects")]); }
  catch (ex) { $("#pe", el).innerHTML = `<div class="card">${emptyState("alert-triangle", ex.message)}</div>`; return; }
  const p = d.post;
  let dirty = false, aiSource = null;
  const box = $("#pe", el);
  box.innerHTML = `
    <div class="page-head"><div class="grow"><div class="row">${pill(...STATE[p.state])}<span class="small faint" data-saved>saved ${esc(rel(p.updated_at))}</span></div>
        <h1 data-h1>${esc(p.title)}</h1></div>
      ${p.state === "published" ? `<a class="btn" href="/blog/${esc(p.slug)}" target="_blank" rel="noopener">${icon("external-link")} View live</a>` : ""}
      <button class="btn primary" data-save>${icon("device-floppy")} Save</button></div>
    <div class="editor">
      <div class="stack">
        <div class="card stack">
          <label class="field"><span>Title</span><input class="input" name="title" value="${esc(p.title)}"></label>
          <label class="field"><span>Address</span><div class="row"><span class="small faint">prepwithtee.com/blog/</span>
            <input class="input grow" name="slug" value="${esc(p.slug)}"></div></label>
          <div class="md-bar row">
            <button class="btn sm" data-md="**" title="Bold">${icon("bold")}</button>
            <button class="btn sm" data-md="_" title="Italic">${icon("italic")}</button>
            <button class="btn sm" data-md="## " title="Heading">${icon("h-2")}</button>
            <button class="btn sm" data-md="- " title="List">${icon("list")}</button>
            <button class="btn sm" data-md="link" title="Link">${icon("link")}</button>
            <label class="btn sm" title="Insert an image">${icon("photo")}<input type="file" accept="image/*" hidden data-img></label>
            <span class="grow"></span>
            <span class="small faint" data-wc></span>
            <button class="btn sm" data-preview>${icon("eye")} Preview</button>
          </div>
          <div class="ai-bar row" data-aibar>
            <span class="small muted">${icon("sparkles")} AI on the selected text:</span>
            ${AI_ACTIONS.map(([k, l]) => `<button class="btn sm" data-ai="${k}">${l}</button>`).join("")}
          </div>
          <div data-suggest hidden class="suggest"></div>
          <textarea class="textarea mono body-md" name="body" spellcheck="true">${esc(p.body_markdown || "")}</textarea>
          <div class="preview md-preview" data-prev hidden></div>
        </div>
        <div class="card stack"><div class="card-head"><h2 class="grow">FAQ (shown on the page, helps search)</h2>
          <button class="btn sm" data-faq-add>${icon("plus")} Add</button></div><div data-faq></div></div>
      </div>
      <div class="stack side-col">
        <div class="card stack ai-card"><h2>${icon("sparkles")} Write with AI</h2>
          ${d.ai.configured ? "" : `<p class="small tone-bad">No AI provider is set up on the server (add a MISTRAL_API_KEY, NVIDIA_API_KEY or GEMINI_API_KEY).</p>`}
          <textarea class="textarea" name="prompt" placeholder="What should the post be about? e.g. How to score an A* in O Level Physics Paper 2">${esc(params.prompt || "")}</textarea>
          <div class="row"><label class="field grow"><span>Audience</span><select class="select" name="aud"><option value="students">Students</option><option value="parents">Parents</option><option value="students and parents">Both</option></select></label>
            <label class="field grow"><span>Subject</span><select class="select" name="subj"><option value="">General</option>
              ${subjects.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join("")}</select></label></div>
          <div class="row"><label class="field grow"><span>Length</span><select class="select" name="len">
              ${[600, 900, 1300, 1800].map(n => `<option value="${n}"${n === 900 ? " selected" : ""}>~${n} words</option>`).join("")}</select></label>
            <label class="field grow"><span>Tone</span><input class="input" name="tone" placeholder="friendly, exam-focused"></label></div>
          <label class="field"><span>Keywords</span><input class="input" name="kw" value="${esc(p.keywords || "")}" placeholder="o level physics, paper 2 tips"></label>
          <button class="btn primary" data-outline>${icon("list-details")} 1. Plan the outline</button>
          <div data-outline-box></div>
        </div>
        <div class="card stack"><h2>Publishing</h2>
          <div class="row">${pill(...STATE[p.state])}${p.state === "scheduled" ? `<span class="small">goes live ${esc(fmtDate(p.publish_at))} ${esc(new Date(p.publish_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span>` : ""}
            ${p.state === "published" ? `<span class="small faint">since ${esc(fmtDate(p.published_at))}</span>` : ""}</div>
          ${p.state !== "published" ? `<button class="btn primary" data-pub="publish">${icon("world-upload")} Publish now</button>
            <div class="row"><input class="input grow" type="datetime-local" name="when"><button class="btn" data-pub="schedule">${icon("clock")} Schedule</button></div>` : ""}
          ${p.state !== "draft" ? `<button class="btn" data-pub="unpublish">${icon("eye-off")} Back to draft</button>` : ""}
        </div>
        <div class="card stack"><h2>Search and sharing</h2>
          <div class="serp"><div class="serp-url">prepwithtee.com › blog › <span data-serp-slug></span></div>
            <div class="serp-title" data-serp-title></div><div class="serp-desc" data-serp-desc></div></div>
          <label class="field"><span>Search title <span class="faint" data-n="meta_title"></span></span><input class="input" name="meta_title" value="${esc(p.meta_title || "")}"></label>
          <label class="field"><span>Search description <span class="faint" data-n="meta_desc"></span></span><textarea class="textarea short" name="meta_desc">${esc(p.meta_desc || "")}</textarea></label>
          <label class="field"><span>Excerpt (the blog list)</span><textarea class="textarea short" name="excerpt">${esc(p.excerpt || "")}</textarea></label>
          <div class="checks" data-seo></div>
        </div>
        <div class="card stack"><h2>Cover image</h2>
          ${p.cover_url ? `<img class="shot-full" data-cover-img src="${esc(p.cover_url)}" alt="Cover">` : ""}
          <div class="row"><input class="input grow" name="cover_url" value="${esc(p.cover_url || "")}" placeholder="/uploads/blog/…">
            <label class="btn">${icon("upload")}<input type="file" accept="image/*" hidden data-cover></label></div></div>
        <div class="card stack"><h2>Revisions</h2>
          ${d.revisions.length ? d.revisions.map(r => `<button class="list-row link" data-rev="${r.id}">${icon(String(r.source || "").startsWith("ai") ? "sparkles" : "history")}
            <span class="grow">${esc(rel(r.created_at))} <span class="small faint">${esc(String(r.source || "manual").replace(/^ai:/, "AI · "))}${r.created_by ? ` · ${esc(r.created_by)}` : ""}</span></span></button>`).join("")
            : `<p class="small muted">Saved versions appear here.</p>`}
          <button class="btn danger sm" data-del>${icon("trash")} Delete post</button></div>
      </div>
    </div>`;

  const f = n => $(`[name=${n}]`, box);
  const body = f("body");
  let faq = [...(p.faq || [])];
  const markDirty = () => { dirty = true; $("[data-saved]", box).textContent = "unsaved changes"; seo(); };

  /* FAQ */
  const drawFaq = () => {
    $("[data-faq]", box).innerHTML = faq.length ? faq.map((x, i) => `<div class="faq-row">
        <input class="input" data-fq="${i}" value="${esc(x.q)}" placeholder="Question">
        <textarea class="textarea short" data-fa="${i}" placeholder="Answer">${esc(x.a)}</textarea>
        <button class="btn sm icon ghost danger" data-frm="${i}" aria-label="Remove question">${icon("x")}</button></div>`).join("")
      : `<p class="small muted">No questions yet. The AI draft suggests some.</p>`;
  };
  drawFaq();
  $("[data-faq-add]", box).addEventListener("click", () => { faq.push({ q: "", a: "" }); drawFaq(); markDirty(); });
  $("[data-faq]", box).addEventListener("input", e => {
    if (e.target.dataset.fq) faq[+e.target.dataset.fq].q = e.target.value;
    if (e.target.dataset.fa) faq[+e.target.dataset.fa].a = e.target.value;
    markDirty();
  });
  $("[data-faq]", box).addEventListener("click", e => {
    const b = e.target.closest("[data-frm]"); if (!b) return;
    faq.splice(+b.dataset.frm, 1); drawFaq(); markDirty();
  });

  /* SEO checks + Google preview */
  const seo = () => {
    const t = f("meta_title").value || f("title").value, desc = f("meta_desc").value || f("excerpt").value;
    const text = body.value, kw = f("kw").value.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
    const words = (text.match(/\w+/g) || []).length;
    $("[data-wc]", box).textContent = `${words} words`;
    $("[data-serp-title]", box).textContent = t.length > 60 ? `${t.slice(0, 58)}…` : t;
    $("[data-serp-desc]", box).textContent = desc.length > 158 ? `${desc.slice(0, 155)}…` : desc;
    $("[data-serp-slug]", box).textContent = f("slug").value;
    $("[data-n=meta_title]", box).textContent = `${f("meta_title").value.length}/60`;
    $("[data-n=meta_desc]", box).textContent = `${f("meta_desc").value.length}/155`;
    const links = (text.match(/\]\((\/[^)]*|https:\/\/prepwithtee\.com[^)]*)\)/g) || []).length;
    const checks = [
      [t.length >= 30 && t.length <= 60, `Search title ${t.length} characters (aim for 30-60)`],
      [desc.length >= 120 && desc.length <= 160, `Description ${desc.length} characters (aim for 120-160)`],
      [(text.match(/^##\s/gm) || []).length >= 2, "At least two ## section headings"],
      [links >= 2, `${links} link${links === 1 ? "" : "s"} to your own pages (aim for 2+)`],
      [words >= 600, `${words} words (600+ ranks better)`],
      [!kw.length || kw.some(k => t.toLowerCase().includes(k)), kw.length ? "Main keyword in the title" : "Add keywords to check them"],
      [!!f("cover_url").value, "Cover image set"],
      [faq.filter(x => x.q && x.a).length >= 2, "Two or more FAQ answers"],
    ];
    $("[data-seo]", box).innerHTML = checks.map(([ok, txt]) => `<div class="check-row ${ok ? "ok" : "bad"}">${icon(ok ? "circle-check" : "alert-triangle")}<span>${esc(txt)}</span></div>`).join("")
      + `<div class="small muted">${checks.filter(c => c[0]).length} of ${checks.length} done</div>`;
  };
  box.addEventListener("input", e => {
    if (["title", "slug", "body", "meta_title", "meta_desc", "excerpt", "cover_url", "kw"].includes(e.target.name)) markDirty();
    if (e.target.name === "title") $("[data-h1]", box).textContent = e.target.value || "Untitled post";
    if (e.target.name === "body" && !$("[data-prev]", box).hidden) preview();
  });
  seo();

  /* Markdown toolbar + preview */
  const wrap = (before, after = before, placeholder = "text") => {
    const s = body.selectionStart, e = body.selectionEnd, sel = body.value.slice(s, e) || placeholder;
    body.setRangeText(before + sel + after, s, e, "select");
    body.focus(); markDirty();
  };
  $$("[data-md]", box).forEach(b => b.addEventListener("click", () => {
    const k = b.dataset.md;
    if (k === "link") wrap("[", "](/papers)", "link text");
    else if (k.endsWith(" ")) {
      const s = body.value.lastIndexOf("\n", body.selectionStart - 1) + 1;
      body.setRangeText(k, s, s, "end"); body.focus(); markDirty();
    } else wrap(k);
  }));
  const preview = debounce(async () => { $("[data-prev]", box).innerHTML = (await md())(body.value); }, 200);
  $("[data-preview]", box).addEventListener("click", async () => {
    const pv = $("[data-prev]", box), on = pv.hidden;
    pv.hidden = !on; body.hidden = on;
    if (on) { pv.innerHTML = loadingHtml(); pv.innerHTML = (await md())(body.value); }
  });
  const uploadImg = async file => {
    const fd = new FormData(); fd.append("file", file);
    const res = await fetch("/api/admin/blog/upload", { method: "POST", body: fd, credentials: "same-origin" });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.detail || "Upload failed");
    return j.url;
  };
  $("[data-img]", box).addEventListener("change", async e => {
    try { const url = await uploadImg(e.target.files[0]); body.setRangeText(`\n![](${url})\n`, body.selectionStart, body.selectionStart, "end"); markDirty(); }
    catch (ex) { toast(ex.message, true); }
  });
  $("[data-cover]", box).addEventListener("change", async e => {
    try { f("cover_url").value = await uploadImg(e.target.files[0]); markDirty(); toast("Cover uploaded - save to keep it"); }
    catch (ex) { toast(ex.message, true); }
  });

  /* AI on the selection */
  const sug = $("[data-suggest]", box);
  $$("[data-ai]", box).forEach(b => b.addEventListener("click", async () => {
    let s = body.selectionStart, e = body.selectionEnd;
    const action = b.dataset.ai;
    if (s === e && action !== "continue") { toast("Select some text in the post first", true); return; }
    if (action === "continue") { s = Math.max(0, body.value.lastIndexOf("\n\n", e - 1)); }
    const selection = body.value.slice(s, e) || body.value.slice(-1500);
    sug.hidden = false; sug.innerHTML = loadingHtml("The AI is writing…");
    try {
      const r = await api("/api/admin/blog/ai/edit", { method: "POST", body: {
        action, selection, context: body.value.slice(Math.max(0, s - 1500), e + 1500), subject: f("subj").value || null } });
      sug.innerHTML = `<div class="small muted">${icon("sparkles")} Suggestion <span class="faint">(${esc(r.model)})</span></div>
        <div class="msg">${esc(r.replacement)}</div>
        <div class="row"><button class="btn sm primary" data-acc>Use it</button><button class="btn sm" data-again>Try again</button>
          <button class="btn sm ghost" data-no>Discard</button></div>`;
      $("[data-acc]", sug).addEventListener("click", () => {
        const text = action === "continue" ? `${body.value.slice(s, e)}\n\n${r.replacement}` : r.replacement;
        body.setRangeText(text, s, e, "select"); aiSource = `ai:${r.model}`; markDirty(); sug.hidden = true;
      });
      $("[data-again]", sug).addEventListener("click", () => b.click());
      $("[data-no]", sug).addEventListener("click", () => { sug.hidden = true; });
    } catch (ex) { sug.innerHTML = `<p class="tone-bad small">${esc(ex.message)}</p>`; }
  }));

  /* AI writer: outline -> draft */
  const brief = () => ({ prompt: f("prompt").value.trim(), audience: f("aud").value, subject: f("subj").value || null,
                         tone: f("tone").value.trim() || null, length: +f("len").value, keywords: f("kw").value.trim() || null });
  $("[data-outline]", box).addEventListener("click", async e => {
    const b = brief();
    if (b.prompt.length < 5) { toast("Describe the post first", true); return; }
    const ob = $("[data-outline-box]", box), btn = e.currentTarget;
    btn.disabled = true; ob.innerHTML = loadingHtml("Planning the outline…");
    try {
      const { outline, model } = await api("/api/admin/blog/ai/outline", { method: "POST", body: b });
      drawOutline(outline, model);
    } catch (ex) { ob.innerHTML = `<p class="tone-bad small">${esc(ex.message)}</p>`; }
    finally { btn.disabled = false; }
  });
  const drawOutline = (o, model) => {
    const ob = $("[data-outline-box]", box);
    ob.innerHTML = `<div class="small muted">Edit the plan, then write. <span class="faint">${esc(model)}</span></div>
      <input class="input" data-o-title value="${esc(o.title)}">
      ${o.sections.map((s, i) => `<div class="outline-sec"><input class="input" data-o-h="${i}" value="${esc(s.h2)}">
        <textarea class="textarea short" data-o-p="${i}">${esc((s.points || []).join("\n"))}</textarea></div>`).join("")}
      <button class="btn primary" data-write>${icon("pencil")} 2. Write the full draft</button>`;
    $("[data-write]", ob).addEventListener("click", async e => {
      const btn = e.currentTarget;           // currentTarget is null after the first await
      const outline = { title: $("[data-o-title]", ob).value, angle: o.angle, sections: o.sections.map((s, i) => ({
        h2: $(`[data-o-h="${i}"]`, ob).value, points: $(`[data-o-p="${i}"]`, ob).value.split("\n").map(x => x.trim()).filter(Boolean) })) };
      if (body.value.trim() && !(await confirmBox("Replace the text?", "The draft replaces what's in the editor now (the current text stays in Revisions once saved).", "Write the draft"))) return;
      btn.disabled = true;
      ob.insertAdjacentHTML("beforeend", `<div data-wait>${loadingHtml("Writing the draft - this takes about a minute…")}</div>`);
      try {
        const { draft, model } = await api("/api/admin/blog/ai/draft", { method: "POST", body: { ...brief(), outline } });
        f("title").value = draft.title || f("title").value; $("[data-h1]", box).textContent = f("title").value;
        body.value = draft.body_markdown; f("excerpt").value = draft.excerpt; f("meta_title").value = draft.meta_title;
        f("meta_desc").value = draft.meta_desc;
        if (p.title === "Untitled post" || p.slug.startsWith("untitled-post")) f("slug").value = draft.slug;
        if (draft.faq?.length) { faq = draft.faq; drawFaq(); }
        aiSource = `ai:${model}`; markDirty();
        toast("Draft written - read it through, then save");
      } catch (ex) { toast(ex.message, true); }
      finally { $("[data-wait]", ob)?.remove(); btn.disabled = false; }
    });
  };

  /* save / publish / revisions / delete */
  const save = async (quiet = false) => {
    const bodyJson = { title: f("title").value.trim(), slug: f("slug").value.trim(), body_markdown: body.value,
      excerpt: f("excerpt").value.trim() || null, meta_title: f("meta_title").value.trim() || null,
      meta_desc: f("meta_desc").value.trim() || null, cover_url: f("cover_url").value.trim() || null,
      keywords: f("kw").value.trim() || null, faq: faq.filter(x => x.q && x.a), source: aiSource };
    try {
      await api(`/api/admin/blog/posts/${p.id}`, { method: "PATCH", body: bodyJson });
      dirty = false; aiSource = null;
      $("[data-saved]", box).textContent = "saved just now";
      if (!quiet) toast("Saved");
      return true;
    } catch (ex) { toast(ex.message, true); return false; }
  };
  $("[data-save]", box).addEventListener("click", () => save());
  const onKey = e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && box.isConnected) { e.preventDefault(); save(); } };
  document.addEventListener("keydown", onKey);
  const leave = e => { if (dirty && box.isConnected) { e.preventDefault(); e.returnValue = ""; } };
  addEventListener("beforeunload", leave);
  const off = () => { if (!box.isConnected) { document.removeEventListener("keydown", onKey); removeEventListener("beforeunload", leave); removeEventListener("hashchange", off); } };
  addEventListener("hashchange", off);

  $$("[data-pub]", box).forEach(b => b.addEventListener("click", async () => {
    if (dirty && !(await save(true))) return;
    const action = b.dataset.pub;
    let publish_at = null;
    if (action === "schedule") {
      if (!f("when").value) { toast("Pick a date and time", true); return; }
      publish_at = new Date(f("when").value).toISOString();
    }
    try {
      await api(`/api/admin/blog/posts/${p.id}/publish`, { method: "POST", body: { action, publish_at } });
      toast({ publish: "Published", schedule: "Scheduled", unpublish: "Back to draft" }[action]);
      render(el, { rest, params: {}, setParams });
    } catch (ex) { toast(ex.message, true); }
  }));
  $$("[data-rev]", box).forEach(b => b.addEventListener("click", async () => {
    const { revision: r } = await api(`/api/admin/blog/posts/${p.id}/revisions/${b.dataset.rev}`);
    drawer({ title: `Revision from ${fmtDate(r.created_at)}`, body: `
      <p class="small muted">${esc(r.source || "manual")}${r.created_by ? ` · ${esc(r.created_by)}` : ""}</p>
      <h3>${esc(r.title || "")}</h3><div class="msg mono">${esc(r.body_markdown || "")}</div>
      <button class="btn primary" data-restore>${icon("restore")} Restore this version</button>`,
      onMount: (dEl, close) => $("[data-restore]", dEl).addEventListener("click", async () => {
        await api(`/api/admin/blog/posts/${p.id}/revisions/${r.id}/restore`, { method: "POST" });
        close(); toast("Restored"); dirty = false; render(el, { rest, params: {}, setParams });
      }) });
  }));
  $("[data-del]", box).addEventListener("click", async () => {
    if (!(await confirmBox("Delete post", `Delete "${p.title}" and all its revisions? This can't be undone.`, "Delete", true))) return;
    await api(`/api/admin/blog/posts/${p.id}`, { method: "DELETE" });
    dirty = false; toast("Deleted"); location.hash = "#/blog";
  });
  if (params.prompt) $("[data-outline]", box).scrollIntoView({ block: "center" });
}

