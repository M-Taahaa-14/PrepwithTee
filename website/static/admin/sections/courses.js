import { $, $$, api, esc, icon, pill, fmtDate, modal, toast, confirmBox, loadingHtml, emptyState, lookup } from "../core.js";

export const title = "Courses";

const LEVELS = ["O Level", "IGCSE", "A Level"];

export async function render(el) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Courses</h1>
      <p>Landing pages at /course.html?slug=… - draft until you publish.</p></div>
      <button class="btn primary" data-new>${icon("plus")} New course</button></div>
    <div id="c-body">${loadingHtml()}</div>`;
  const draw = async () => {
    const { courses } = await api("/api/admin/courses");
    courses.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    $("#c-body", el).innerHTML = courses.length ? `<div class="dt-wrap"><table class="dt"><thead><tr>
        <th><span class="static">Course</span></th><th><span class="static">Code</span></th><th><span class="static">Status</span></th>
        <th class="num"><span class="static">Order</span></th><th><span class="static">Updated</span></th><th></th></tr></thead>
        <tbody>${courses.map(c => `<tr>
          <td><b>${esc(c.title)}</b><div class="small faint">${esc(c.level)} · /course.html?slug=${esc(c.slug)}</div></td>
          <td>${esc(c.syllabus_code)}</td><td>${c.published ? pill("published", "ok") : pill("draft", "warn")}</td>
          <td class="num">${esc(c.sort_order ?? 0)}</td><td>${esc(fmtDate(c.updated_at))}</td>
          <td class="nowrap"><a class="btn sm" href="/course.html?slug=${encodeURIComponent(c.slug)}" target="_blank" rel="noopener">${icon("external-link")} View</a>
            <button class="btn sm" data-toggle="${c.id}">${c.published ? "Unpublish" : "Publish"}</button>
            <button class="btn sm" data-edit="${c.id}">${icon("pencil")} Edit</button>
            <button class="btn sm icon ghost danger" data-del="${c.id}" aria-label="Delete ${esc(c.title)}">${icon("trash")}</button></td></tr>`).join("")}
        </tbody></table></div>` : `<div class="card">${emptyState("book", "No courses yet.", "Create the first landing page.")}</div>`;
    const byId = Object.fromEntries(courses.map(c => [String(c.id), c]));
    $$("[data-edit]", el).forEach(b => b.addEventListener("click", async () => { if (await courseForm(byId[b.dataset.edit])) draw(); }));
    $$("[data-toggle]", el).forEach(b => b.addEventListener("click", async () => {
      const c = byId[b.dataset.toggle];
      await api(`/api/admin/courses/${c.id}`, { method: "PATCH", body: { published: !c.published } });
      toast(c.published ? "Unpublished" : "Published"); draw();
    }));
    $$("[data-del]", el).forEach(b => b.addEventListener("click", async () => {
      const c = byId[b.dataset.del];
      if (!(await confirmBox("Delete course", `Delete "${c.title}"? Its page stops working.`, "Delete", true))) return;
      await api(`/api/admin/courses/${c.id}`, { method: "DELETE" });
      toast("Deleted"); draw();
    }));
  };
  $("[data-new]", el).addEventListener("click", async () => { if (await courseForm(null)) draw(); });
  draw();
}

const slugify = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

async function courseForm(c) {
  const subjects = await lookup("subjects");
  let bullets = [], faq = [];
  try { bullets = JSON.parse(c?.what_you_get_json || "[]"); } catch { /* old row */ }
  try { faq = JSON.parse(c?.faq_json || "[]"); } catch { /* old row */ }
  const regen = k => `<button type="button" class="btn sm ghost" data-regen="${k}" title="Write this field again with AI">${icon("sparkles")} Redo</button>`;
  return modal({
    title: c ? `Edit ${c.title}` : "New course", submit: c ? "Save" : "Create course", size: "xl",
    body: `
      <div class="row"><label class="field grow"><span>Subject</span><select class="select" name="code">
          ${subjects.map(s => `<option value="${esc(s.code)}"${s.code === c?.syllabus_code ? " selected" : ""}>${esc(s.name)} (${esc(s.code)})</option>`).join("")}</select></label>
        <label class="field"><span>Level</span><select class="select" name="level">${LEVELS.map(l => `<option${l === c?.level ? " selected" : ""}>${l}</option>`).join("")}</select></label></div>
      <label class="field"><span>Title</span><input class="input" name="title" required value="${esc(c?.title || "")}" autofocus></label>
      <div class="ai-bar stack">
        <label class="field"><span>${icon("sparkles")} Notes for the AI (what's special about this course)</span>
          <input class="input" name="ai_notes" placeholder="Weekly live classes, small groups of 3, marked homework, May/June 2027 batch"></label>
        <div class="row"><button type="button" class="btn primary sm" data-ai-all>${icon("sparkles")} Fill every field with AI</button>
          <span class="small muted" data-ai-status>Uses the official syllabus chapters and your real prices. Read it before publishing.</span></div>
      </div>
      <div class="row"><label class="field grow"><span>Page address (slug)</span><input class="input" name="slug" required pattern="[a-z0-9-]+" value="${esc(c?.slug || "")}"></label>
        <label class="field"><span>Order</span><input class="input" name="sort_order" type="number" value="${esc(c?.sort_order ?? 0)}"></label></div>
      <label class="field"><span>Subject name on the page</span><input class="input" name="subject" value="${esc(c?.subject || "")}"></label>
      <label class="field"><span class="row">Tagline ${regen("tagline")}</span><input class="input" name="tagline" maxlength="140" value="${esc(c?.tagline || "")}"></label>
      <label class="field"><span class="row">What you get (one per line) ${regen("what_you_get")}</span><textarea class="textarea" name="bullets">${esc(bullets.join("\n"))}</textarea></label>
      <label class="field"><span class="row">Overview (HTML) ${regen("overview_html")}</span><textarea class="textarea tall" name="overview_html">${esc(c?.overview_html || "")}</textarea></label>
      <label class="field"><span class="row">How we teach it (HTML) ${regen("approach_html")}</span><textarea class="textarea tall" name="approach_html">${esc(c?.approach_html || "")}</textarea></label>
      <label class="field"><span class="row">Questions and answers (question line, answer line, blank line between) ${regen("faq")}</span>
        <textarea class="textarea tall" name="faq">${esc(faq.map(x => `${x.q}\n${x.a}`).join("\n\n"))}</textarea></label>
      <label class="field"><span class="row">Search title <span class="faint" data-count="meta_title"></span> ${regen("meta_title")}</span><input class="input" name="meta_title" maxlength="70" value="${esc(c?.meta_title || "")}"></label>
      <label class="field"><span class="row">Search description <span class="faint" data-count="meta_description"></span> ${regen("meta_description")}</span><textarea class="textarea" name="meta_description" maxlength="200">${esc(c?.meta_description || "")}</textarea></label>
      <label class="check"><input type="checkbox" name="published" ${c?.published ? "checked" : ""}> Published</label>`,
    onMount: m => {
      const count = () => $$("[data-count]", m).forEach(s => {
        const n = $(`[name=${s.dataset.count}]`, m).value.length, max = s.dataset.count === "meta_title" ? 60 : 155;
        s.textContent = `${n}/${max}`; s.classList.toggle("tone-bad", n > max);
      });
      m.addEventListener("input", count); count();
      const put = fields => {
        const set = (n, v) => { if (v !== undefined) $(`[name=${n}]`, m).value = v; };
        set("tagline", fields.tagline); set("overview_html", fields.overview_html); set("approach_html", fields.approach_html);
        set("meta_title", fields.meta_title); set("meta_description", fields.meta_description);
        if (fields.what_you_get) set("bullets", fields.what_you_get.join("\n"));
        if (fields.faq) set("faq", fields.faq.map(x => `${x.q}\n${x.a}`).join("\n\n"));
        count();
      };
      const ask = async (field, btn) => {
        const st = $("[data-ai-status]", m);
        btn.disabled = true; st.textContent = "The AI is writing…";
        try {
          const r = await api("/api/admin/courses/ai", { method: "POST", body: {
            syllabus_code: $("[name=code]", m).value, level: $("[name=level]", m).value,
            title: $("[name=title]", m).value.trim() || "Course", notes: $("[name=ai_notes]", m).value.trim() || null, field } });
          put(r.fields); st.textContent = `Written by ${r.model}. Read it through before publishing.`;
        } catch (ex) { st.textContent = ex.message; }
        finally { btn.disabled = false; }
      };
      $("[data-ai-all]", m).addEventListener("click", e => ask(null, e.currentTarget));
      $$("[data-regen]", m).forEach(b => b.addEventListener("click", e => { e.preventDefault(); ask(b.dataset.regen, b); }));
      if (!c) {
        const sync = () => {
          const s = subjects.find(x => x.code === $("[name=code]", m).value);
          if (!s) return;
          const lvl = $("[name=level]", m).value;
          const plain = s.name.replace(/^(O Level|IGCSE|A Level)\s+/, "");
          $("[name=subject]", m).value = plain;
          $("[name=slug]", m).value = slugify(`${lvl} ${plain} ${s.code}`);
          if (!$("[name=title]", m).value || $("[name=title]", m).dataset.auto) {
            $("[name=title]", m).value = `${lvl} ${plain} (${s.code})`; $("[name=title]", m).dataset.auto = "1";
          }
        };
        $("[name=code]", m).addEventListener("change", sync); $("[name=level]", m).addEventListener("change", sync); sync();
        $("[name=title]", m).addEventListener("input", e => delete e.target.dataset.auto);
      }
    },
    run: async m => {
      const v = n => $(`[name=${n}]`, m).value.trim();
      if (!v("title")) return "Give the course a title.";
      if (!/^[a-z0-9-]+$/.test(v("slug"))) return "The page address may only use lowercase letters, numbers and hyphens.";
      const body = { syllabus_code: v("code"), slug: v("slug"), title: v("title"), level: v("level"), subject: v("subject") || v("title"),
        tagline: v("tagline") || null, overview_html: v("overview_html") || null, approach_html: v("approach_html") || null,
        what_you_get_json: JSON.stringify(v("bullets").split("\n").map(x => x.trim()).filter(Boolean)),
        meta_title: v("meta_title") || null, meta_description: v("meta_description") || null,
        faq_json: JSON.stringify(v("faq").split(/\n\s*\n/).map(p => p.split("\n")).filter(p => p.length >= 2)
          .map(([q, ...a]) => ({ q: q.trim(), a: a.join(" ").trim() })).filter(x => x.q && x.a)),
        published: $("[name=published]", m).checked, sort_order: +v("sort_order") || 0 };
      await api(c ? `/api/admin/courses/${c.id}` : "/api/admin/courses", { method: c ? "PUT" : "POST", body });
      toast(c ? "Saved" : "Course created");
      return true;
    },
  });
}
