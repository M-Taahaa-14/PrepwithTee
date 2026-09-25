/* ai-panel.js — the question help panel: Explain · Guide me · Mark scheme · Ask.
 *
 * Shared by the topical viewer (and, next, the MCQ solver). Mount it into any
 * container:   openAiPanel(el, { qid, seq, ref, topic }, { tab: "explain" })
 *
 *   Explain      the stored worked solution (pre-generated per question):
 *                step cards per sub-part, answer, how marks are given, MCQ
 *                option-by-option reasons, common mistakes
 *   Guide me     three hints revealed one at a time, never the answer
 *   Mark scheme  the official Cambridge crop (or the MCQ letter)
 *   Ask          follow-up chat, streamed; select any text in Explain to ask
 *                about exactly that part
 *
 * Maths is LaTeX rendered by KaTeX; prose is Markdown sanitised with
 * DOMPurify (it is model output). Plan gates come back as 403
 * upgrade_required and render as a "take a plan" card, not an error.
 */
import { api, UpgradeRequiredError } from "/auth.js?v=20260829a";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── Markdown + LaTeX ────────────────────────────────────────────────────────
// Math is lifted out before Markdown runs (Markdown would eat _ and \ inside
// TeX), then put back and typeset by KaTeX.
export function renderRich(text) {
  const math = [];
  // Letters-only placeholder: marked turns NUL into U+FFFD, and punctuation
  // (_ * @ [) could be read as Markdown syntax.
  const hold = (m) => { math.push(m); return `KXMATH${math.length - 1}KXEND`; };
  let src = String(text ?? "")
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => hold({ t, d: true }))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => hold({ t, d: true }))
    .replace(/\$([^\n$]+?)\$/g, (_, t) => hold({ t, d: false }))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => hold({ t, d: false }));
  let html = window.marked ? window.marked.parse(src, { breaks: true, gfm: true }) : esc(src);
  html = window.DOMPurify ? window.DOMPurify.sanitize(html) : html;
  return html.replace(/KXMATH(\d+)KXEND/g, (_, i) => {
    const { t, d } = math[+i];
    try {
      return window.katex.renderToString(t, { displayMode: d, throwOnError: false, output: "html" });
    } catch {
      return esc(d ? `$$${t}$$` : `$${t}$`);
    }
  });
}

// ── Panel ───────────────────────────────────────────────────────────────────
const TABS = [["explain", "Explain"], ["hint", "Guide me"], ["ms", "Mark scheme"], ["ask", "Ask"]];

export function openAiPanel(el, q, { tab = "explain", onClose, tabs } = {}) {
  // `tabs` limits what is offered - the MCQ solver hides Explain / Mark scheme
  // until the answer has been revealed, so the panel can't give it away.
  const shown = tabs ? TABS.filter(([k]) => tabs.includes(k)) : TABS;
  if (!shown.some(([k]) => k === tab)) tab = shown[0][0];
  const P = { el, q, tab, hints: 0, quote: null, onClose };
  el.innerHTML = `
    <div class="ai-head">
      <div><b>${esc(q.label || `Q${q.seq}`)}</b> <span>${esc(q.ref || "")}</span><em>${esc(q.topic || "")}</em></div>
      <button type="button" class="ai-x" data-ai="close" aria-label="Close panel">✕</button>
    </div>
    <div class="ai-tabs" role="tablist">${shown.map(([k, label]) => `
      <button type="button" role="tab" data-ai-tab="${k}" id="ai-tab-${k}"
              aria-selected="${k === tab}" aria-controls="ai-body">${label}</button>`).join("")}
    </div>
    <div class="ai-body" id="ai-body" role="tabpanel" tabindex="0"></div>
    <div class="ai-pill" hidden><button type="button" data-ai="quote">💬 Ask about this</button></div>`;
  el.onclick = (e) => click(P, e);
  el.onmouseup = () => selection(P);
  el.onkeyup = (e) => { if (e.key === "Shift") selection(P); };
  show(P, tab);
  return P;
}

function click(P, e) {
  const t = e.target.closest("[data-ai-tab]");
  if (t) return show(P, t.dataset.aiTab);
  const act = e.target.closest("[data-ai]")?.dataset.ai;
  if (act === "close") P.onClose?.();
  else if (act === "hint") nextHint(P);
  else if (act === "quote") quoteSelection(P);
  else if (act === "unquote") { P.quote = null; renderAsk(P); }
  else if (act === "report") report(P);
  else if (act === "send") send(P);
}

function show(P, tab) {
  P.tab = tab;
  P.el.querySelectorAll("[data-ai-tab]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.aiTab === tab)));
  P.el.querySelector(".ai-pill").hidden = true;
  ({ explain: renderExplain, hint: renderHints, ms: renderMs, ask: renderAsk })[tab](P);
}

const body = (P) => P.el.querySelector("#ai-body");
const loading = (P, what) => { body(P).innerHTML = `<p class="ai-muted" role="status">Loading ${what}…</p>`; };

function gated(P, err) {
  if (err instanceof UpgradeRequiredError || err?.detail?.code === "upgrade_required") {
    body(P).innerHTML = `
      <div class="ai-plan">
        <div class="ai-plan-ico" aria-hidden="true">🔓</div>
        <h3>Unlock AI help for every question</h3>
        <p>${esc(err.message)}</p>
        <a class="ai-btn" href="${esc(err.detail?.url || "/pricing.html")}">See plans</a>
      </div>`;
    return true;
  }
  return false;
}

async function load(P, path, what, timeout = 20000) {
  loading(P, what);
  try {
    return await api(path, { timeout });
  } catch (err) {
    if (gated(P, err)) return null;
    body(P).innerHTML = `<p class="ai-muted">${esc(err.message)}</p>`;
    return null;
  }
}

// Explain
async function renderExplain(P) {
  const d = await load(P, `/api/questions/${P.q.qid}/explain`,
    "the worked solution (the first time anyone opens a question this can take up to a minute)",
    95000);
  if (!d || P.tab !== "explain") return;
  const parts = (d.parts || []).map((p) => `
    <section class="ai-part">
      ${p.label ? `<h4>${esc(p.label)}</h4>` : ""}
      ${(p.steps || []).map((s, i) => `
        <div class="ai-step"><div class="ai-step-k">Step ${i + 1} · ${esc(s.title)}</div>
          <div class="ai-rich">${renderRich(s.body)}</div></div>`).join("")}
      ${p.answer ? `<div class="ai-answer"><span>Answer</span><div class="ai-rich">${renderRich(p.answer)}</div></div>` : ""}
      ${p.marking ? `<div class="ai-marking"><b>How the marks are given</b><div class="ai-rich">${renderRich(p.marking)}</div></div>` : ""}
    </section>`).join("");
  const mcq = (d.mcq_options || []).length ? `
    <section class="ai-part"><h4>Why each option</h4>${d.mcq_options.map((o) => {
      const mine = P.q.your && String(o.letter).toUpperCase() === P.q.your;
      return `
      <div class="ai-opt ${o.correct ? "is-right" : "is-wrong"}${mine ? " is-yours" : ""}"><b>${esc(o.letter)}</b>
        <div class="ai-rich">${mine ? `<span class="ai-yours">${o.correct ? "Your answer ✓" : "Your answer"}</span>` : ""}${renderRich(o.why)}</div></div>`;
    }).join("")}</section>` : "";
  const mistakes = (d.common_mistakes || []).length ? `
    <section class="ai-part ai-mistakes"><h4>Common mistakes</h4><ul>${
      d.common_mistakes.map((m) => `<li class="ai-rich">${renderRich(m)}</li>`).join("")}</ul></section>` : "";
  body(P).innerHTML = `
    ${d.confidence === "low" ? `<p class="ai-warn">Check this one against the mark scheme — the
      question or mark scheme was hard to read.</p>` : ""}
    ${d.summary ? `<div class="ai-summary ai-rich">${renderRich(d.summary)}</div>` : ""}
    <div class="ai-explain" data-selectable>${parts}${mcq}${mistakes}</div>
    <p class="ai-foot">Select any line to ask about it ·
      <button type="button" class="ai-link" data-ai="report">Report a mistake</button></p>`;
}

// Guide me
async function renderHints(P) {
  if (!P.hints) {
    body(P).innerHTML = `
      <div class="ai-guide">
        <p>Stuck? Get a nudge, not the answer. Each hint goes one step further.</p>
        <button type="button" class="ai-btn" data-ai="hint">Show hint 1</button>
      </div>`;
    return;
  }
  nextHint(P, true);
}

async function nextHint(P, redraw = false) {
  const level = redraw ? P.hints : Math.min(3, P.hints + 1);
  const d = await load(P, `/api/questions/${P.q.qid}/hints?level=${level}`, "your hint", 95000);
  if (!d || P.tab !== "hint") return;
  P.hints = level;
  body(P).innerHTML = `
    <ol class="ai-hints">${d.hints.map((h, i) => `
      <li><span class="ai-hint-n">Hint ${i + 1}</span><div class="ai-rich">${renderRich(h)}</div></li>`).join("")}
    </ol>
    ${level < 3 ? `<button type="button" class="ai-btn ai-btn-ghost" data-ai="hint">Show hint ${level + 1}</button>`
      : `<p class="ai-muted">That's every hint. Try it, then open <b>Explain</b> to check.</p>`}`;
}

// Mark scheme
async function renderMs(P) {
  loading(P, "the mark scheme");
  try {
    const a = await api(`/api/mcq/answer/${P.q.qid}`);
    if (a.has_answer) {
      body(P).innerHTML = `<div class="ai-mcq-key"><span>Correct answer</span><b>${esc(a.answer)}</b></div>
        <p class="ai-muted">From the official Cambridge mark scheme.</p>`;
      return;
    }
  } catch { /* structured question: show the crop */ }
  const img = new Image();
  img.className = "ai-ms";
  img.alt = `Official mark scheme for question ${P.q.seq}`;
  img.onload = () => {
    if (P.tab !== "ms") return;
    body(P).innerHTML = "";
    body(P).append(img);
    body(P).insertAdjacentHTML("beforeend",
      `<p class="ai-muted">Official Cambridge mark scheme · ${esc(P.q.ref || "")}</p>`);
  };
  img.onerror = () => { body(P).innerHTML = `<p class="ai-muted">No mark scheme is available for this question.</p>`; };
  img.src = `/api/question/${P.q.qid}/ms-preview`;
}

// Ask
async function renderAsk(P) {
  const d = await load(P, `/api/questions/${P.q.qid}/thread`, "your conversation");
  if (!d || P.tab !== "ask") return;
  body(P).innerHTML = `
    <div class="ai-chat" id="ai-chat">${d.messages.length ? d.messages.map(bubble).join("") :
      `<p class="ai-muted">Ask anything about this question — a step you didn't follow,
       why a unit is needed, or what the examiner wants.</p>`}</div>
    <form class="ai-compose" data-ai-form>
      ${P.quote ? `<div class="ai-quote">“${esc(P.quote)}”
        <button type="button" data-ai="unquote" aria-label="Remove quote">×</button></div>` : ""}
      <label class="sr-only" for="ai-msg">Your question</label>
      <textarea id="ai-msg" rows="2" maxlength="2000" placeholder="Ask a follow-up…"></textarea>
      <button type="submit" class="ai-send" aria-label="Send">↑</button>
    </form>`;
  const form = P.el.querySelector("[data-ai-form]");
  const ta = form.querySelector("textarea");
  form.onsubmit = (e) => { e.preventDefault(); send(P); };
  ta.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(P); } };
  ta.focus();
  const chat = P.el.querySelector("#ai-chat");
  chat.scrollTop = chat.scrollHeight;
}

function bubble(m) {
  return m.role === "user"
    ? `<div class="ai-msg ai-msg-u">${m.quoted_text ? `<div class="ai-quote">“${esc(m.quoted_text)}”</div>` : ""}${esc(m.content)}</div>`
    : `<div class="ai-msg ai-msg-a ai-rich">${renderRich(m.content)}</div>`;
}

async function send(P) {
  const ta = P.el.querySelector("#ai-msg");
  const text = ta?.value.trim();
  if (!text) return;
  const chat = P.el.querySelector("#ai-chat");
  chat.querySelector(".ai-muted")?.remove();
  chat.insertAdjacentHTML("beforeend", bubble({ role: "user", content: text, quoted_text: P.quote }));
  const out = document.createElement("div");
  out.className = "ai-msg ai-msg-a ai-typing";
  out.textContent = "…";
  chat.append(out);
  chat.scrollTop = chat.scrollHeight;
  ta.value = "";
  const quote = P.quote;
  P.quote = null;
  P.el.querySelector(".ai-compose .ai-quote")?.remove();
  try {
    const res = await fetch(`/api/questions/${P.q.qid}/ask`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, quoted_text: quote }),
    });
    if (!res.ok) {
      let detail = {};
      try { detail = (await res.json()).detail || {}; } catch {}
      out.remove();
      if (detail.code === "upgrade_required") return gated(P, { message: detail.message, detail });
      chat.insertAdjacentHTML("beforeend", `<p class="ai-muted">${esc(detail.message || detail || "That didn't go through. Try again.")}</p>`);
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let acc = "";
    out.classList.remove("ai-typing");
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      acc += dec.decode(value, { stream: true });
      out.textContent = acc;                     // plain while streaming
      chat.scrollTop = chat.scrollHeight;
    }
    out.classList.add("ai-rich");
    out.innerHTML = renderRich(acc);             // typeset when complete
  } catch {
    out.textContent = "That didn't go through. Check your connection and try again.";
  }
}

// Select-to-ask
function selection(P) {
  const pill = P.el.querySelector(".ai-pill");
  const sel = window.getSelection();
  const text = sel?.toString().trim();
  const inside = sel?.anchorNode && P.el.querySelector("[data-selectable]")?.contains(sel.anchorNode);
  if (!text || !inside || text.length < 2) { pill.hidden = true; return; }
  P.pending = text.slice(0, 600);
  const r = sel.getRangeAt(0).getBoundingClientRect();
  const box = P.el.getBoundingClientRect();
  pill.style.top = `${r.bottom - box.top + 6}px`;
  pill.style.left = `${Math.min(Math.max(8, r.left - box.left), box.width - 170)}px`;
  pill.hidden = false;
}

function quoteSelection(P) {
  P.quote = P.pending;
  window.getSelection()?.removeAllRanges();
  show(P, "ask");
}

async function report(P) {
  try {
    await api(`/api/questions/${P.q.qid}/report`, { method: "POST", body: { reason: "student report" } });
    P.el.querySelector(".ai-foot").innerHTML = "Thanks — we'll check this explanation.";
  } catch (e) {
    P.el.querySelector(".ai-foot").textContent = e.message;
  }
}
