/**
 * note-annotate.js — Text-selection annotation toolbar.
 *
 * Drop <script type="module" src="note-annotate.js"></script> into any page.
 * Selecting text shows a floating "📝 Annotate" button above the selection.
 * Clicking it opens the notes side pane pre-filled with the quoted passage.
 *
 * If window.openNoteComposer is available (i.e., we're on notes.html with
 * notes.js loaded) that composer is used; otherwise a self-contained pane
 * is injected so the module is zero-dependency on any page.
 */

import { captureContext, locationLabel } from './note-context.js';

// ── Constants ─────────────────────────────────────────────────────────────────
const ALL_SUBJECTS = [
  ['4024','O Level Maths D'],['0580','IGCSE Maths'],
  ['5054','O Level Physics'],['0625','IGCSE Physics'],
  ['2210','O Level CS'],['0478','IGCSE CS'],
  ['5070','O Level Chemistry'],['0620','IGCSE Chemistry'],
  ['9709','A Level Maths'],['9702','A Level Physics'],['9618','A Level CS'],
];

// ── State ─────────────────────────────────────────────────────────────────────
let _selTimer   = null;
let _pendingTxt = '';
let _pendingCtx = null;
let _paneCtx    = null;

// ── CSS injection ─────────────────────────────────────────────────────────────
function injectStyles() {
  if (document.getElementById('na-styles')) return;
  const s = document.createElement('style');
  s.id = 'na-styles';
  s.textContent = `
/* Floating toolbar */
#na-toolbar {
  position: absolute; z-index: 8900; display: none;
  background: var(--navy,#1B3A7A); border-radius: 9px;
  padding: 5px 3px; box-shadow: 0 4px 20px rgba(10,6,26,.28);
  pointer-events: all; user-select: none;
}
#na-annotate-btn {
  background: none; border: none; color: #fff;
  font-size: .81rem; font-weight: 700; cursor: pointer;
  padding: 3px 9px; border-radius: 6px; white-space: nowrap;
  display: flex; align-items: center; gap: 4px; transition: background .13s;
}
#na-annotate-btn:hover { background: rgba(255,255,255,.15); }
/* Arrow below toolbar */
#na-toolbar::after {
  content: '';
  position: absolute; left: 50%; transform: translateX(-50%);
  bottom: -6px; border: 6px solid transparent;
  border-top-color: var(--navy,#1B3A7A); border-bottom: none;
}
#na-toolbar.below::after { display: none; }
#na-toolbar.below::before {
  content: '';
  position: absolute; left: 50%; transform: translateX(-50%);
  top: -6px; border: 6px solid transparent;
  border-bottom-color: var(--navy,#1B3A7A); border-top: none;
}

/* Side pane overlay */
#na-overlay {
  position: fixed; inset: 0; z-index: 8950; pointer-events: none;
}
#na-overlay.open { pointer-events: all; }
#na-overlay-bg {
  position: absolute; inset: 0;
  background: rgba(10,6,26,.38); backdrop-filter: blur(2px);
  opacity: 0; transition: opacity .22s; cursor: pointer;
}
#na-overlay.open #na-overlay-bg { opacity: 1; }
#na-pane {
  position: absolute; top: 0; right: 0; bottom: 0;
  width: min(460px, 100vw);
  background: #fff;
  box-shadow: -6px 0 40px rgba(10,6,26,.18);
  display: flex; flex-direction: column;
  transform: translateX(100%);
  transition: transform .28s cubic-bezier(.34,1.0,.64,1);
  overflow: hidden;
}
html[data-theme="dark"] #na-pane {
  background: #1e1b2e; border-left: 1.5px solid rgba(255,255,255,.1);
}
#na-overlay.open #na-pane { transform: translateX(0); }

#na-pane-head {
  padding: .9rem 1.1rem .8rem;
  border-bottom: 1px solid var(--line,#e4dff2);
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0;
}
.na-pane-title { font-weight: 700; font-size: .95rem; color: var(--navy,#1B3A7A); }
.na-pane-close {
  width: 30px; height: 30px; border: none;
  background: var(--cream,#FAF8F5); border-radius: 8px;
  cursor: pointer; color: var(--grey,#5A5A72);
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem; transition: background .13s;
}
.na-pane-close:hover { background: var(--line,#e4dff2); }

#na-pane-body {
  padding: 1rem 1.1rem; display: flex; flex-direction: column;
  gap: .75rem; overflow-y: auto; flex: 1;
}

/* Quote block */
.na-quote-block {
  background: var(--cream,#FAF8F5);
  border-left: 3px solid var(--navy,#1B3A7A);
  border-radius: 0 8px 8px 0;
  padding: .6rem .8rem; font-style: italic;
  font-size: .82rem; color: var(--grey,#5A5A72); line-height: 1.55;
  overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 5; -webkit-box-orient: vertical;
}
.na-quote-label {
  font-style: normal; font-size: .7rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: .07em;
  color: var(--navy,#1B3A7A); display: block; margin-bottom: .3rem;
}

/* Form fields */
.na-field { display: flex; flex-direction: column; gap: .3rem; }
.na-field label {
  font-size: .75rem; font-weight: 600; color: var(--grey,#5A5A72);
  text-transform: uppercase; letter-spacing: .07em;
}
.na-textarea {
  width: 100%; padding: .55rem .75rem;
  border: 1.5px solid var(--line,#e4dff2); border-radius: 10px;
  font-size: .88rem; font-family: inherit; color: var(--ink,#1B1B2E);
  background: #fff; resize: vertical; min-height: 130px; max-height: 280px;
  transition: border-color .15s;
}
.na-textarea:focus { outline: none; border-color: var(--navy,#1B3A7A); }
html[data-theme="dark"] .na-textarea {
  background: var(--dark-lighter,#2a2740);
  border-color: var(--line,rgba(255,255,255,.12)); color: #f0eeff;
}
.na-select {
  width: 100%; padding: .52rem .7rem;
  border: 1.5px solid var(--line,#e4dff2); border-radius: 10px;
  font-size: .85rem; font-family: inherit; color: var(--ink,#1B1B2E);
  background: #fff; cursor: pointer; transition: border-color .15s;
}
.na-select:focus { outline: none; border-color: var(--navy,#1B3A7A); }
html[data-theme="dark"] .na-select {
  background: var(--dark-lighter,#2a2740); color: #f0eeff;
  border-color: var(--line,rgba(255,255,255,.12));
}

/* Source context tag */
.na-source-tag {
  display: inline-flex; align-items: center; gap: .3rem;
  font-size: .73rem; font-weight: 600; padding: .22rem .6rem;
  border-radius: 20px; background: var(--lav,#EEE8FF); color: var(--navy,#1B3A7A);
}

#na-pane-foot {
  padding: .85rem 1.1rem; border-top: 1px solid var(--line,#e4dff2);
  display: flex; gap: .5rem; justify-content: flex-end;
  align-items: center; flex-shrink: 0;
}
#na-pane-status { font-size: .78rem; color: var(--grey,#5A5A72); margin-right: auto; }
.na-cancel-btn {
  padding: .5rem 1rem; border-radius: 10px;
  background: var(--cream,#FAF8F5); color: var(--ink,#1B1B2E);
  font-weight: 600; font-size: .85rem;
  border: 1.5px solid var(--line,#e4dff2); cursor: pointer; transition: border-color .15s;
}
.na-cancel-btn:hover { border-color: var(--navy,#1B3A7A); }
.na-save-btn {
  padding: .5rem 1.2rem; border-radius: 10px;
  background: var(--navy,#1B3A7A); color: #fff;
  font-weight: 700; font-size: .85rem;
  border: none; cursor: pointer; transition: background .15s, transform .12s;
}
.na-save-btn:hover { background: var(--navy-deep,#0f2255); transform: translateY(-1px); }
.na-save-btn:disabled { opacity: .5; cursor: wait; transform: none; }

/* Saved toast */
@keyframes na-toast-in {
  from { opacity:0; transform:translateX(-50%) translateY(12px); }
  to   { opacity:1; transform:translateX(-50%) translateY(0); }
}
#na-toast {
  position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%);
  background: var(--navy,#1B3A7A); color: #fff; border-radius: 12px;
  padding: .6rem 1.3rem; font-size: .84rem; font-weight: 700;
  z-index: 9999; animation: na-toast-in .25s ease;
  pointer-events: none; white-space: nowrap;
}
  `;
  document.head.appendChild(s);
}

// ── Toolbar ───────────────────────────────────────────────────────────────────
function injectToolbar() {
  if (document.getElementById('na-toolbar')) return;
  const el = document.createElement('div');
  el.id = 'na-toolbar';
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = '<button id="na-annotate-btn" type="button">📝 Annotate</button>';
  document.body.appendChild(el);
  document.getElementById('na-annotate-btn').addEventListener('click', handleAnnotate);
}

function showToolbar(rect) {
  const toolbar = document.getElementById('na-toolbar');
  if (!toolbar) return;
  toolbar.style.display = 'block';
  toolbar.classList.remove('below');

  const MARGIN = 10;
  const tw = toolbar.offsetWidth  || 110;
  const th = toolbar.offsetHeight || 34;

  let left = rect.left + rect.width  / 2 - tw / 2 + window.scrollX;
  let top  = rect.top  + window.scrollY - th - 10;

  // Clamp horizontally
  left = Math.max(MARGIN, Math.min(left, document.documentElement.clientWidth - tw - MARGIN));

  // If above viewport, flip below
  if (top < window.scrollY + MARGIN) {
    top = rect.bottom + window.scrollY + 10;
    toolbar.classList.add('below');
  }

  toolbar.style.left = left + 'px';
  toolbar.style.top  = top  + 'px';
}

function hideToolbar() {
  const t = document.getElementById('na-toolbar');
  if (t) t.style.display = 'none';
}

// ── Selection listener ────────────────────────────────────────────────────────
document.addEventListener('selectionchange', () => {
  clearTimeout(_selTimer);
  _selTimer = setTimeout(onSelectionChange, 160);
});

// Hide toolbar when clicking elsewhere (but not on the toolbar itself)
document.addEventListener('mousedown', e => {
  if (!e.target.closest('#na-toolbar')) hideToolbar();
}, true);

function onSelectionChange() {
  const sel = window.getSelection();
  if (!isAnnotatable(sel)) { hideToolbar(); return; }

  const text = sel.toString().trim();
  if (text.length < 3) { hideToolbar(); return; }

  _pendingTxt = text;
  _pendingCtx = captureContext();

  try {
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) { hideToolbar(); return; }
    showToolbar(rect);
  } catch (_) {
    hideToolbar();
  }
}

function isAnnotatable(sel) {
  if (!sel || !sel.toString().trim()) return false;
  const node = sel.anchorNode;
  if (!node) return false;
  const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  if (!el) return false;
  // Skip form elements, our own overlays, and the site header
  if (el.closest('input, textarea, select, [contenteditable="true"]')) return false;
  if (el.closest('#na-toolbar, #na-overlay, .nh-overlay')) return false;
  if (el.closest('.site-header, header, nav')) return false;
  return true;
}

// ── Annotate action ───────────────────────────────────────────────────────────
function handleAnnotate() {
  hideToolbar();
  const text = _pendingTxt;
  const ctx  = _pendingCtx;
  if (!text) return;

  // Build quoted content block
  const quoted = text.split('\n').map(l => '> ' + l).join('\n') + '\n\n';

  // If notes hub is loaded on this page, delegate to its composer
  if (typeof window.openNoteComposer === 'function') {
    window.openNoteComposer({ ...ctx, content: quoted });
    return;
  }

  // Otherwise use the self-contained pane
  openPane(text, ctx);
}

// ── Self-contained side pane ──────────────────────────────────────────────────
function buildSubjectOpts() {
  return ALL_SUBJECTS.map(([code, label]) =>
    `<option value="${code}">${label}</option>`
  ).join('');
}

function injectPane() {
  if (document.getElementById('na-overlay')) return;

  const el = document.createElement('div');
  el.id = 'na-overlay';
  el.innerHTML = `
<div id="na-overlay-bg"></div>
<div id="na-pane" role="dialog" aria-modal="true" aria-label="New annotation">
  <div id="na-pane-head">
    <span class="na-pane-title">New Annotation</span>
    <button class="na-pane-close" type="button" aria-label="Close">✕</button>
  </div>
  <div id="na-pane-body">
    <div class="na-quote-block" id="na-quote-block" style="display:none">
      <span class="na-quote-label">Selected passage</span>
      <span id="na-quote-txt"></span>
    </div>
    <div id="na-source-row" style="display:none">
      <span class="na-source-tag" id="na-source-tag"></span>
    </div>
    <div class="na-field">
      <label for="na-note-ta">Your note</label>
      <textarea class="na-textarea" id="na-note-ta"
        placeholder="What did you notice? What question came up?" maxlength="8000"></textarea>
    </div>
    <div class="na-field">
      <label for="na-subj-sel">Subject (optional)</label>
      <select class="na-select" id="na-subj-sel">
        <option value="">No subject</option>
        ${buildSubjectOpts()}
      </select>
    </div>
  </div>
  <div id="na-pane-foot">
    <span id="na-pane-status"></span>
    <button class="na-cancel-btn" type="button">Cancel</button>
    <button class="na-save-btn" type="button" id="na-save-btn">Save Note</button>
  </div>
</div>`;
  document.body.appendChild(el);

  // Bind close events
  el.querySelector('#na-overlay-bg').addEventListener('click', closePane);
  el.querySelector('.na-pane-close').addEventListener('click', closePane);
  el.querySelector('.na-cancel-btn').addEventListener('click', closePane);
  el.querySelector('#na-save-btn').addEventListener('click', saveAnnotation);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.getElementById('na-overlay')?.classList.contains('open'))
      closePane();
  });
}

function openPane(rawText, ctx) {
  injectPane();
  _paneCtx = ctx;

  // Show the selected passage
  const quoteTxt   = document.getElementById('na-quote-txt');
  const quoteBlock = document.getElementById('na-quote-block');
  const sourceRow  = document.getElementById('na-source-row');
  const sourceTag  = document.getElementById('na-source-tag');
  const ta         = document.getElementById('na-note-ta');
  const status     = document.getElementById('na-pane-status');

  quoteTxt.textContent = rawText;
  quoteBlock.style.display = '';

  // Show source context if available
  const srcLabel = ctx ? locationLabel(ctx) : null;
  if (srcLabel) {
    const icons = { question:'📑', flashcard:'🗂️', chapter:'📖', tutor_message:'🤖', video:'🎬' };
    sourceTag.textContent = (icons[ctx.type] || '🔗') + ' ' + srcLabel;
    sourceRow.style.display = '';
  } else {
    sourceRow.style.display = 'none';
  }

  ta.value = '';
  status.textContent = '';
  document.getElementById('na-overlay').classList.add('open');
  setTimeout(() => ta.focus(), 280);
}

function closePane() {
  const ov = document.getElementById('na-overlay');
  if (ov) ov.classList.remove('open');
  _paneCtx = null;
}

async function saveAnnotation() {
  const ta      = document.getElementById('na-note-ta');
  const subjSel = document.getElementById('na-subj-sel');
  const status  = document.getElementById('na-pane-status');
  const saveBtn = document.getElementById('na-save-btn');
  const rawText = document.getElementById('na-quote-txt').textContent;

  // Compose content: quoted passage + user note
  const quote   = rawText ? rawText.split('\n').map(l => '> ' + l).join('\n') + '\n\n' : '';
  const userNote = ta.value.trim();
  const content  = quote + userNote;

  if (!userNote) {
    status.textContent = 'Add your note before saving.';
    ta.focus();
    return;
  }

  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';
  status.textContent = '';

  // Convert location_json ctx to linked_* fields
  const linked = ctxToLinked(_paneCtx);

  try {
    const r = await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type:          'text',
        content,
        syllabus:      subjSel.value || null,
        linked_type:   linked.linked_type  || null,
        linked_id:     linked.linked_id    || null,
        linked_label:  linked.linked_label || null,
        location_json: _paneCtx || null,
        tags_json:     '["annotation"]',
      }),
    });
    if (r.status === 401) {
      status.textContent = 'Sign in to save notes.'; return;
    }
    if (!r.ok) throw new Error();
    closePane();
    showToast('✅ Annotation saved');
  } catch (_) {
    status.textContent = 'Save failed — try again.';
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save Note';
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function ctxToLinked(loc) {
  if (!loc) return {};
  switch (loc.type) {
    case 'question':
      return { linked_type: 'paper', linked_id: loc.paperKey,
               linked_label: loc.paperKey + (loc.questionNumber != null ? ' Q' + loc.questionNumber : '') };
    case 'flashcard':
      return { linked_type: 'flashcard_block', linked_id: String(loc.blockId || ''), linked_label: 'Flashcard' };
    case 'chapter':
      return { linked_type: 'chapter', linked_id: loc.topic, linked_label: loc.topic };
    case 'tutor_message':
      return { linked_type: 'tutor_message', linked_id: loc.messageId || null, linked_label: 'AI Tutor' };
    default:
      return {};
  }
}

let _toastTimer = null;
function showToast(msg) {
  const existing = document.getElementById('na-toast');
  if (existing) existing.remove();
  clearTimeout(_toastTimer);
  const t = document.createElement('div');
  t.id = 'na-toast';
  t.textContent = msg;
  document.body.appendChild(t);
  _toastTimer = setTimeout(() => t.remove(), 2800);
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
injectStyles();
injectToolbar();
