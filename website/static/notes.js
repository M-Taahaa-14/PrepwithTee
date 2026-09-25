/**
 * notes.js — Student personal notes hub.
 * Rich text editing · view overlay with jump-to-source · tabs · masonry board.
 */

import { requireAuth } from '/auth.js';
import { resolveLocation, captureContext, locationLabel } from './note-context.js';

// ── State ──────────────────────────────────────────────────────────────────────
let _notes         = [];
let _viewMode      = 'list';
let _activeTab     = 'all';
let _editingId     = null;
let _editCtx       = null;
let _selectedColor = 'yellow';
let _selectedType  = 'text';
let _isMistake     = false;
let _isExamRevision = false;
let _tags          = [];
let _searchTimer;
let _autosaveTimer;
let _enrollments   = [];

// ── DOM refs ───────────────────────────────────────────────────────────────────
const body       = document.getElementById('nh-body');
const overlay    = document.getElementById('nh-overlay');
const viewOvl    = document.getElementById('nh-view-overlay');
const newBtn     = document.getElementById('nh-new-btn');
const closeBtn   = document.getElementById('nh-close-btn');
const cancelBtn  = document.getElementById('nh-cancel-btn');
const saveBtn    = document.getElementById('nh-save-btn');
const titleEl    = document.getElementById('nh-modal-title');
const titleIn    = document.getElementById('nh-title-input');
const editor     = document.getElementById('nh-editor');       // contenteditable
const subjectIn  = document.getElementById('nh-subject-input');
const colorWrap  = document.getElementById('nh-color-wrap');
const contextRow = document.getElementById('nh-context-row');
const contextTag = document.getElementById('nh-context-tag');
const countEl    = document.getElementById('nh-count');
const toast      = document.getElementById('nh-toast');
const flagMistake  = document.getElementById('nh-flag-mistake');
const flagRevision = document.getElementById('nh-flag-revision');
const autosaveEl   = document.getElementById('nh-autosave');
const tagsWrap     = document.getElementById('nh-tags-wrap');
const tagsInput    = document.getElementById('nh-tags-input');
const fSubject     = document.getElementById('nh-filter-subject');
const fSearch      = document.getElementById('nh-search');
const viewListBtn  = document.getElementById('nh-view-list');
const viewGridBtn  = document.getElementById('nh-view-grid');
const pillsEl      = document.getElementById('nh-subject-pills');

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  await requireAuth();
  await loadEnrollments();
  await loadNotes();
  bindEvents();

  // Check if a note id is in the URL hash (#note-42) and open it
  const hash = location.hash;
  if (hash.startsWith('#note-')) {
    const id = parseInt(hash.slice(6));
    const note = _notes.find(n => n.id === id);
    if (note) openViewer(note);
  }
}

async function loadEnrollments() {
  try {
    const r = await fetch('/api/enrollments');
    if (r.ok) {
      const data = await r.json();
      _enrollments = (data.enrollments || []).filter(e => e.status === 'active');
    }
  } catch (_) {}
  populateSubjectFilters();
}

const ALL_SUBJECTS = [
  {code:'4024',label:'O Level Maths D'},{code:'0580',label:'IGCSE Maths'},
  {code:'5054',label:'O Level Physics'},{code:'0625',label:'IGCSE Physics'},
  {code:'2210',label:'O Level CS'},{code:'0478',label:'IGCSE CS'},
  {code:'5070',label:'O Level Chemistry'},{code:'0620',label:'IGCSE Chemistry'},
  {code:'9709',label:'A Level Maths'},{code:'9702',label:'A Level Physics'},
  {code:'9618',label:'A Level CS'},
];

function populateSubjectFilters() {
  const source = _enrollments.length > 0
    ? _enrollments.map(e => ({code:e.syllabus, label:subjectLabel(e.syllabus)}))
    : ALL_SUBJECTS;
  const opts = source.map(s =>
    `<option value="${esc(s.code)}">${esc(s.label)}</option>`).join('');
  fSubject.insertAdjacentHTML('beforeend', opts);
  subjectIn.insertAdjacentHTML('beforeend', opts);

  if (pillsEl && source.length) {
    pillsEl.innerHTML = `<button class="nh-spill active" data-syllabus="">All</button>`
      + source.map(s =>
        `<button class="nh-spill" data-syllabus="${esc(s.code)}">${esc(s.label)}</button>`
      ).join('');
    pillsEl.style.display = 'flex';
    pillsEl.addEventListener('click', e => {
      const pill = e.target.closest('.nh-spill');
      if (!pill) return;
      pillsEl.querySelectorAll('.nh-spill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      fSubject.value = pill.dataset.syllabus;
      loadNotes();
    });
  }
}

// ── Load ───────────────────────────────────────────────────────────────────────
async function loadNotes() {
  showSkeleton();
  const params = buildFilterParams();
  try {
    const r = await fetch('/api/notes?' + params);
    if (!r.ok) throw new Error();
    const data = await r.json();
    _notes = data.notes || [];
    render(_notes);
  } catch (_) {
    body.innerHTML = `<div class="nh-empty"><div class="nh-empty-ico">⚠️</div>
      <h3>Couldn't load notes</h3><p>Check your connection and try again.</p></div>`;
  }
}

function buildFilterParams() {
  const p = new URLSearchParams();
  if (fSubject.value) p.set('syllabus', fSubject.value);
  const q = fSearch.value.trim();
  if (q) p.set('q', q);
  switch (_activeTab) {
    case 'pinned':     p.set('pinned','true');                   break;
    case 'mistakes':   p.set('is_mistake','true');               break;
    case 'revision':   p.set('is_exam_revision','true');         break;
    case 'papers':     p.set('linked_type','paper');             break;
    case 'flashcards': p.set('linked_type','flashcard_block');   break;
    case 'tutor':      p.set('linked_type','tutor_message');     break;
  }
  return p.toString();
}

// ── Render ─────────────────────────────────────────────────────────────────────
function render(notes) {
  const count = notes.length;
  countEl.textContent = count ? `${count} note${count===1?'':'s'}` : '';

  if (!count) {
    const emptyMsg = {
      mistakes:'No mistake notes yet. After a wrong answer, tap "Add mistake note" to record it.',
      revision:'Mark important notes with ⭐ Exam Revision to see them here.',
      pinned:'Pin a note from any view to keep it at the top of your dashboard.',
      papers:'No notes linked to past papers yet.',
      flashcards:'No notes linked to flashcards yet.',
      tutor:'No notes linked to AI Tutor conversations yet.',
    }[_activeTab] || 'Click <strong>New Note</strong> to jot your first thought.';
    body.innerHTML = `<div class="nh-empty">
      <div class="nh-empty-ico">📝</div>
      <h3>No notes here yet</h3><p>${emptyMsg}</p>
      <button class="nh-new-btn" onclick="document.getElementById('nh-new-btn').click()"
        style="margin-top:1.1rem;display:inline-flex" type="button">+ New Note</button>
    </div>`;
    return;
  }

  if (_viewMode === 'grid') {
    renderMasonry(notes);
  } else if (_activeTab === 'all' && !fSubject.value) {
    renderGroupedList(notes);
  } else {
    renderList(notes);
  }
}

function renderGroupedList(notes) {
  const groups = new Map();
  for (const n of notes) {
    const key = n.syllabus || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(n);
  }
  const sorted = [...groups.entries()].sort(([a],[b]) => {
    if (!a) return 1; if (!b) return -1;
    return subjectLabel(a).localeCompare(subjectLabel(b));
  });
  let out = '<div class="nh-list">';
  for (const [code, gNotes] of sorted) {
    const label = code ? subjectLabel(code) : 'General';
    out += `<div class="nh-group-head">
      <span>${label}</span><span class="nh-group-count">${gNotes.length}</span>
    </div>`;
    out += gNotes.map(noteRowHtml).join('');
  }
  out += '</div>';
  body.innerHTML = out;
  bindNoteActions();
}

function renderList(notes) {
  body.innerHTML = `<div class="nh-list">${notes.map(noteRowHtml).join('')}</div>`;
  bindNoteActions();
}

function noteRowHtml(n) {
  const icon    = n.type==='sticky' ? '📌' : '📄';
  const preview = plainText(n.content || '').slice(0,140).replace(/\s+/g,' ');
  const date    = relDate(n.updated_at || n.created_at);
  const pinned  = n.pinned_to_dashboard;
  const badges  = buildBadges(n);
  const source  = buildSourceChip(n);
  const tagsHtml= buildTagsHtml(n);
  const jumpUrl = buildJumpUrl(n);

  return `
  <div class="nh-note-row" data-id="${n.id}" tabindex="0" role="button" aria-label="Open note: ${esc(n.title||'Untitled')}">
    <div class="nh-note-row-ico" aria-hidden="true">${icon}</div>
    <div class="nh-note-row-body">
      ${badges ? `<div class="nh-card-flags">${badges}</div>` : ''}
      <div class="nh-note-row-title${!n.title?' untitled':''}">${n.title ? esc(n.title) : 'Untitled'}</div>
      <div class="nh-note-row-preview">${esc(preview)}</div>
      ${source}
      ${tagsHtml}
      <div class="nh-note-row-foot">
        <span class="nh-note-row-date">${date}</span>
      </div>
    </div>
    <div class="nh-note-row-actions">
      ${jumpUrl ? `<button class="nh-jump-btn" data-jump="${esc(jumpUrl)}" title="Go to source page" type="button">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
        Source
      </button>` : ''}
      <button class="nh-action-btn nh-pin-btn${pinned?' pinned':''}"
        data-id="${n.id}" data-pin="${pinned?'0':'1'}"
        title="${pinned?'Unpin':'Pin to dashboard'}" type="button">📌</button>
      <button class="nh-action-btn nh-edit-btn" data-id="${n.id}" title="Edit" type="button">✏️</button>
      <button class="nh-action-btn nh-del-btn"  data-id="${n.id}" title="Delete" type="button">🗑️</button>
    </div>
  </div>`;
}

function renderMasonry(notes) {
  const html = notes.map(n => {
    const color   = n.color || 'yellow';
    const pinned  = n.pinned_to_dashboard;
    const date    = relDate(n.updated_at || n.created_at);
    const badges  = buildBadges(n);
    const tagsHtml = buildTagsHtml(n);
    const jumpUrl  = buildJumpUrl(n);
    const source   = buildSourceChip(n);

    return `
    <div class="nh-sticky color-${color}" data-id="${n.id}" tabindex="0" role="button" aria-label="Open note">
      <div class="nh-sticky-actions">
        ${jumpUrl ? `<button class="nh-jump-btn" data-jump="${esc(jumpUrl)}" title="Go to source" type="button" style="padding:.15rem .4rem;font-size:.64rem">↗</button>` : ''}
        <button class="nh-action-btn nh-pin-btn${pinned?' pinned':''}"
          data-id="${n.id}" data-pin="${pinned?'0':'1'}" title="${pinned?'Unpin':'Pin'}" type="button">📌</button>
        <button class="nh-action-btn nh-edit-btn" data-id="${n.id}" title="Edit" type="button">✏️</button>
        <button class="nh-action-btn nh-del-btn"  data-id="${n.id}" title="Delete" type="button">🗑️</button>
      </div>
      ${badges ? `<div class="nh-card-flags" style="margin-bottom:.3rem">${badges}</div>` : ''}
      ${n.title ? `<div class="nh-sticky-title">${esc(n.title)}</div>` : ''}
      <div class="nh-sticky-body">${renderContent(n.content||'', 220)}</div>
      ${tagsHtml}
      <div class="nh-sticky-meta">
        <span>${date}</span>
        ${source}
      </div>
    </div>`;
  }).join('');
  body.innerHTML = `<div class="nh-masonry">${html}</div>`;
  bindNoteActions();
}

// ── Content helpers ────────────────────────────────────────────────────────────
function isHtml(s) { return s && /<[a-zA-Z]/.test(s); }

function plainText(s) {
  if (!s) return '';
  if (isHtml(s)) {
    const d = document.createElement('div'); d.innerHTML = s;
    return d.textContent || '';
  }
  return s;
}

function renderContent(content, maxLen = 0) {
  if (!content) return '';
  let html;
  if (isHtml(content)) {
    html = content;
  } else {
    html = esc(content).replace(/\n/g,'<br>');
  }
  if (maxLen && plainText(content).length > maxLen) {
    // Truncate by character count
    const d = document.createElement('div'); d.innerHTML = html;
    const text = d.textContent.slice(0, maxLen);
    return esc(text) + '<span style="color:var(--grey)">…</span>';
  }
  return html;
}

function buildBadges(n) {
  let out = '';
  if (n.is_mistake)       out += '<span class="nh-badge nh-badge-mistake">❌ Mistake</span>';
  if (n.is_exam_revision) out += '<span class="nh-badge nh-badge-revision">⭐ Exam</span>';
  return out;
}

function buildSourceChip(n) {
  if (!n.linked_label && !n.location_json) return '';
  const icons = {paper:'📑', flashcard_block:'🗂️', chapter:'📖', tutor_message:'🤖'};
  const ico   = icons[n.linked_type] || '🔗';
  let label   = n.linked_label || '';
  if (n.location_json) {
    const loc = parseLoc(n.location_json);
    const ll = loc ? locationLabel(loc) : null;
    if (ll && ll !== label) label = label ? label+' · '+ll : ll;
  }
  return `<div class="nh-source-chip"><span>${ico}</span><span>${esc(label)}</span></div>`;
}

function buildTagsHtml(n) {
  let tags = [];
  try { tags = n.tags_json ? JSON.parse(n.tags_json) : []; } catch (_) {}
  if (!Array.isArray(tags) || !tags.length) return '';
  return '<div class="nh-card-tags">'+tags.map(t=>`<span class="nh-card-tag">${esc(t)}</span>`).join('')+'</div>';
}

function buildJumpUrl(n) {
  if (n.location_json) {
    const loc = parseLoc(n.location_json);
    const url = loc ? resolveLocation(loc) : null;
    if (url) return url;
  }
  const MAP = {
    paper:           n.linked_id ? `/yearly/open?key=${encodeURIComponent(n.linked_id)}` : null,
    flashcard_block: n.linked_id ? `flashcards.html?block=${n.linked_id}` : null,
    chapter:         'topical-progress.html',
    tutor_message:   'tutor.html',
  };
  return (n.linked_type && MAP[n.linked_type]) || null;
}

function parseLoc(raw) {
  if (!raw) return null;
  if (typeof raw === 'object') return raw;
  try { return JSON.parse(raw); } catch { return null; }
}

// ── Note action handlers ───────────────────────────────────────────────────────
function bindNoteActions() {
  body.querySelectorAll('[data-id]').forEach(el => {
    // Click row → open viewer (not editor)
    el.addEventListener('click', e => {
      if (e.target.closest('.nh-action-btn') || e.target.closest('.nh-jump-btn')) return;
      const id = parseInt(el.dataset.id);
      const note = _notes.find(n => n.id === id);
      if (note) openViewer(note);
    });
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault(); el.click();
      }
    });
  });

  body.querySelectorAll('.nh-jump-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      window.location.href = btn.dataset.jump;
    });
  });

  body.querySelectorAll('.nh-edit-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const note = _notes.find(n => n.id === parseInt(btn.dataset.id));
      if (note) openEditor(note);
    });
  });

  body.querySelectorAll('.nh-del-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm('Delete this note?')) return;
      await deleteNote(parseInt(btn.dataset.id));
    });
  });

  body.querySelectorAll('.nh-pin-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await pinNote(parseInt(btn.dataset.id), btn.dataset.pin==='1');
    });
  });
}

// ── VIEWER OVERLAY ─────────────────────────────────────────────────────────────
function openViewer(note) {
  const jumpUrl  = buildJumpUrl(note);
  const source   = buildSourceChip(note);
  const badges   = buildBadges(note);
  const tagsHtml = buildTagsHtml(note);
  const date     = relDate(note.updated_at || note.created_at);
  const content  = renderContent(note.content || '');

  document.getElementById('vw-title').textContent   = note.title || 'Untitled';
  document.getElementById('vw-date').textContent    = 'Saved '+date;
  document.getElementById('vw-badges').innerHTML    = badges;
  document.getElementById('vw-source').innerHTML    = source;
  document.getElementById('vw-content').innerHTML   = content || '<em style="color:var(--grey)">No content</em>';
  document.getElementById('vw-tags').innerHTML      = tagsHtml;

  const jumpBtn = document.getElementById('vw-jump-btn');
  if (jumpUrl) {
    jumpBtn.style.display = '';
    jumpBtn.onclick = () => window.location.href = jumpUrl;
  } else {
    jumpBtn.style.display = 'none';
  }

  const editBtn = document.getElementById('vw-edit-btn');
  editBtn.onclick = () => { closeViewer(); openEditor(note); };

  const delBtn = document.getElementById('vw-del-btn');
  delBtn.onclick = async () => {
    if (!confirm('Delete this note?')) return;
    closeViewer();
    await deleteNote(note.id);
  };

  // Update URL hash
  history.replaceState(null, '', '#note-'+note.id);

  viewOvl.classList.add('open');
  document.getElementById('vw-close-btn').focus();
}

function closeViewer() {
  viewOvl.classList.remove('open');
  history.replaceState(null, '', location.pathname+location.search);
}

// ── EDITOR OVERLAY ─────────────────────────────────────────────────────────────
function openComposer(ctx = null) {
  _editingId      = null;
  _editCtx        = ctx;
  _isMistake      = ctx?.isMistake      || false;
  _isExamRevision = ctx?.isExamRevision || false;
  titleEl.textContent = 'New Note';
  titleIn.value   = ctx?.titleOverride || '';
  setEditorContent('');
  subjectIn.value = ctx?.syllabus || '';
  setType('text');
  setColor('yellow');
  setTags([]);
  showContext(ctx);
  setFlag('mistake',  _isMistake);
  setFlag('revision', _isExamRevision);
  setAutosave('');
  overlay.classList.add('open');
  setTimeout(() => editor.focus(), 280);
}

function openEditor(note) {
  _editingId = note.id;
  _editCtx   = note.linked_type ? {
    linked_type:note.linked_type, linked_id:note.linked_id,
    linked_label:note.linked_label, location_json:note.location_json,
  } : null;
  _isMistake      = !!note.is_mistake;
  _isExamRevision = !!note.is_exam_revision;
  titleEl.textContent = 'Edit Note';
  titleIn.value   = note.title || '';
  setEditorContent(note.content || '');
  subjectIn.value = note.syllabus || '';
  setType(note.type || 'text');
  setColor(note.color || 'yellow');
  let parsedTags = [];
  try { parsedTags = note.tags_json ? JSON.parse(note.tags_json) : []; } catch (_) {}
  setTags(Array.isArray(parsedTags) ? parsedTags : []);
  showContext(_editCtx);
  setFlag('mistake',  _isMistake);
  setFlag('revision', _isExamRevision);
  setAutosave('');
  overlay.classList.add('open');
  setTimeout(() => titleIn.focus(), 280);
}

function closeComposer() {
  overlay.classList.remove('open');
  clearTimeout(_autosaveTimer);
  _editingId = null;
  _editCtx   = null;
}

function setEditorContent(content) {
  if (isHtml(content)) {
    editor.innerHTML = content;
  } else if (content) {
    editor.innerHTML = esc(content).replace(/\n/g,'<br>');
  } else {
    editor.innerHTML = '';
  }
}

function getEditorContent() {
  // Normalise whitespace-only content to empty
  const text = editor.innerText || editor.textContent || '';
  if (!text.trim()) return null;
  return editor.innerHTML;
}

function setType(t) {
  _selectedType = t;
  document.querySelectorAll('.nh-type-pill').forEach(p =>
    p.classList.toggle('active', p.dataset.type===t));
  colorWrap.style.display = t==='sticky' ? '' : 'none';
}

function setColor(c) {
  _selectedColor = c;
  document.querySelectorAll('.nh-color-swatch').forEach(s =>
    s.classList.toggle('active', s.dataset.color===c));
}

function setFlag(flag, active) {
  if (flag==='mistake') {
    _isMistake = active;
    flagMistake.classList.toggle('active-mistake', active);
  } else {
    _isExamRevision = active;
    flagRevision.classList.toggle('active-revision', active);
  }
}

function showContext(ctx) {
  if (!ctx?.linked_label) { contextRow.style.display='none'; return; }
  contextRow.style.display = '';
  const icons = {paper:'📑', flashcard_block:'🗂️', chapter:'📖', tutor_message:'🤖'};
  contextTag.textContent = (icons[ctx.linked_type]||'🔗')+' '+ctx.linked_label;
}

function setAutosave(msg, saved=false) {
  autosaveEl.textContent = msg;
  autosaveEl.classList.toggle('saved', saved);
}

function setTags(arr) {
  _tags = Array.isArray(arr) ? arr.slice() : [];
  renderTagChips();
}

function renderTagChips() {
  tagsWrap.querySelectorAll('.nh-tag-chip').forEach(c => c.remove());
  _tags.forEach((t, i) => {
    const chip = document.createElement('span');
    chip.className = 'nh-tag-chip';
    chip.innerHTML = `${esc(t)}<button class="nh-tag-chip-x" type="button" aria-label="Remove tag">×</button>`;
    chip.querySelector('.nh-tag-chip-x').addEventListener('click', () => {
      _tags.splice(i,1); renderTagChips();
    });
    tagsWrap.insertBefore(chip, tagsInput);
  });
}

function initTagsInput() {
  tagsInput.addEventListener('keydown', e => {
    if (e.key==='Enter'||e.key===',') {
      e.preventDefault();
      const val = tagsInput.value.trim().replace(/,/g,'');
      if (val && !_tags.includes(val) && _tags.length < 8) {
        _tags.push(val); renderTagChips();
      }
      tagsInput.value='';
    }
    if (e.key==='Backspace' && !tagsInput.value && _tags.length) {
      _tags.pop(); renderTagChips();
    }
  });
  tagsWrap.addEventListener('click', () => tagsInput.focus());
}

// ── Rich text editor toolbar ───────────────────────────────────────────────────
function initRichEditor() {
  document.querySelectorAll('[data-cmd]').forEach(btn => {
    btn.addEventListener('mousedown', e => {
      e.preventDefault(); // prevent blur
      const cmd = btn.dataset.cmd;
      editor.focus();
      if (cmd === 'h3') {
        document.execCommand('formatBlock', false, 'h3');
      } else if (cmd === 'code') {
        wrapInline('code');
      } else if (cmd === 'pre') {
        wrapBlock('pre');
      } else {
        document.execCommand(cmd, false, null);
      }
      updateToolbarState();
    });
  });

  editor.addEventListener('keyup', updateToolbarState);
  editor.addEventListener('mouseup', updateToolbarState);
  editor.addEventListener('input', () => {
    updateToolbarState();
    scheduleAutosave();
  });

  // Tab → indent inside editor
  editor.addEventListener('keydown', e => {
    if (e.key === 'Tab') {
      e.preventDefault();
      document.execCommand('insertHTML', false, '&nbsp;&nbsp;&nbsp;&nbsp;');
    }
  });
}

function wrapInline(tag) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return;
  const range = sel.getRangeAt(0);
  const node = document.createElement(tag);
  try { range.surroundContents(node); } catch (_) {
    node.textContent = range.toString();
    range.deleteContents();
    range.insertNode(node);
  }
}

function wrapBlock(tag) {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) {
    document.execCommand('formatBlock', false, tag);
    return;
  }
  const range = sel.getRangeAt(0);
  const node = document.createElement(tag);
  try { range.surroundContents(node); } catch (_) {
    node.textContent = range.toString();
    range.deleteContents();
    range.insertNode(node);
  }
}

function updateToolbarState() {
  ['bold','italic','underline','insertUnorderedList','insertOrderedList'].forEach(cmd => {
    const btn = document.querySelector(`[data-cmd="${cmd}"]`);
    if (btn) btn.classList.toggle('active', document.queryCommandState(cmd));
  });
}

// ── Save ───────────────────────────────────────────────────────────────────────
function buildPayload() {
  const ctxLoc = _editCtx?.location_json || null;
  const loc    = ctxLoc || captureContext();
  return {
    type:            _selectedType,
    title:           titleIn.value.trim() || null,
    content:         getEditorContent(),
    color:           _selectedType==='sticky' ? _selectedColor : null,
    syllabus:        subjectIn.value || null,
    linked_type:     _editCtx?.linked_type  || null,
    linked_id:       _editCtx?.linked_id    || null,
    linked_label:    _editCtx?.linked_label || null,
    location_json:   loc,
    is_mistake:      _isMistake,
    is_exam_revision: _isExamRevision,
    tags_json:       JSON.stringify(_tags),
  };
}

async function saveNote() {
  const payload = buildPayload();
  if (!payload.content && !payload.title) {
    showToast('Type something first!', true); return;
  }
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving…';
  try {
    let r;
    if (_editingId) {
      r = await fetch(`/api/notes/${_editingId}`, {
        method:'PATCH', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
    } else {
      r = await fetch('/api/notes', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
    }
    if (!r.ok) throw new Error();
    closeComposer();
    showToast(_editingId ? '✅ Note updated' : '✅ Note saved');
    await loadNotes();
  } catch (_) {
    showToast('❌ Save failed — try again', true);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save Note';
  }
}

function scheduleAutosave() {
  if (!_editingId) return;
  clearTimeout(_autosaveTimer);
  setAutosave('Saving…');
  _autosaveTimer = setTimeout(async () => {
    const payload = buildPayload();
    try {
      const r = await fetch(`/api/notes/${_editingId}`, {
        method:'PATCH', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
      });
      if (!r.ok) throw new Error();
      setAutosave('✓ Saved', true);
      const updated = await r.json();
      const idx = _notes.findIndex(n => n.id===_editingId);
      if (idx!==-1) _notes[idx] = updated;
    } catch (_) {
      setAutosave('Save failed');
    }
  }, 1400);
}

async function deleteNote(id) {
  try {
    const r = await fetch(`/api/notes/${id}`, {method:'DELETE'});
    if (!r.ok) throw new Error();
    showToast('🗑️ Note deleted');
    _notes = _notes.filter(n => n.id!==id);
    render(_notes);
  } catch (_) {
    showToast('❌ Couldn\'t delete note', true);
  }
}

async function pinNote(id, pinned) {
  try {
    const r = await fetch(`/api/notes/${id}/pin`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pinned}),
    });
    if (!r.ok) throw new Error();
    showToast(pinned ? '📌 Pinned to dashboard' : '📌 Unpinned');
    const idx = _notes.findIndex(n => n.id===id);
    if (idx!==-1) _notes[idx].pinned_to_dashboard = pinned;
    render(_notes);
  } catch (_) {
    showToast('❌ Couldn\'t update pin', true);
  }
}

// ── Events ─────────────────────────────────────────────────────────────────────
function bindEvents() {
  newBtn.addEventListener('click', () => openComposer());
  closeBtn.addEventListener('click', closeComposer);
  cancelBtn.addEventListener('click', closeComposer);
  document.getElementById('nh-backdrop').addEventListener('click', closeComposer);
  saveBtn.addEventListener('click', saveNote);

  document.getElementById('vw-close-btn').addEventListener('click', closeViewer);
  document.getElementById('vw-backdrop').addEventListener('click', closeViewer);

  initTagsInput();
  initRichEditor();

  // Type pills
  document.querySelectorAll('.nh-type-pill').forEach(p =>
    p.addEventListener('click', () => setType(p.dataset.type)));

  // Colour swatches
  document.querySelectorAll('.nh-color-swatch').forEach(s =>
    s.addEventListener('click', () => setColor(s.dataset.color)));

  // Flag toggles
  flagMistake.addEventListener('click',  () => setFlag('mistake',  !_isMistake));
  flagRevision.addEventListener('click', () => setFlag('revision', !_isExamRevision));

  // Auto-save on title change
  titleIn.addEventListener('input', scheduleAutosave);

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.key==='Escape') {
      if (overlay.classList.contains('open'))  closeComposer();
      if (viewOvl.classList.contains('open'))  closeViewer();
    }
    if ((e.ctrlKey||e.metaKey) && e.key==='Enter' && overlay.classList.contains('open'))
      saveNote();
  });

  // Tabs
  document.querySelectorAll('.nh-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.nh-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _activeTab = tab.dataset.tab;
      loadNotes();
    });
  });

  fSubject.addEventListener('change', () => {
    if (pillsEl) {
      pillsEl.querySelectorAll('.nh-spill').forEach(p =>
        p.classList.toggle('active', p.dataset.syllabus===fSubject.value));
    }
    loadNotes();
  });

  fSearch.addEventListener('input', () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(loadNotes, 280);
  });

  viewListBtn.addEventListener('click', () => {
    _viewMode='list';
    viewListBtn.classList.add('active'); viewGridBtn.classList.remove('active');
    render(_notes);
  });
  viewGridBtn.addEventListener('click', () => {
    _viewMode='grid';
    viewGridBtn.classList.add('active'); viewListBtn.classList.remove('active');
    render(_notes);
  });
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function showSkeleton() {
  const lines = Array.from({length:4}, () =>
    `<div style="background:#fff;border:1.5px solid var(--line);border-radius:14px;padding:1rem">
      <div class="nh-skeleton" style="width:55%;margin-bottom:8px"></div>
      <div class="nh-skeleton" style="width:90%"></div>
      <div class="nh-skeleton" style="width:40%;margin-top:8px"></div>
    </div>`).join('');
  body.innerHTML = `<div class="nh-list">${lines}</div>`;
}

function relDate(iso) {
  if (!iso) return '';
  const d    = new Date(iso);
  const diff = Math.floor((Date.now()-d)/1000);
  if (diff < 60)     return 'just now';
  if (diff < 3600)   return Math.floor(diff/60)+'m ago';
  if (diff < 86400)  return Math.floor(diff/3600)+'h ago';
  if (diff < 604800) return Math.floor(diff/86400)+'d ago';
  return d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
}

function subjectLabel(code) {
  const MAP = {
    '4024':'O Level Maths D','0580':'IGCSE Maths',
    '5054':'O Level Physics', '0625':'IGCSE Physics',
    '2210':'O Level CS',      '0478':'IGCSE CS',
    '5070':'O Level Chemistry','0620':'IGCSE Chemistry',
    '9709':'A Level Maths',   '9702':'A Level Physics','9618':'A Level CS',
  };
  return MAP[code] || code;
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let _toastTimer;
function showToast(msg, isWarn=false) {
  toast.textContent = msg;
  toast.style.background = isWarn ? 'var(--red,#c0392b)' : 'var(--navy)';
  toast.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

// ── Public API ─────────────────────────────────────────────────────────────────
window.openNoteComposer = ctx => openComposer(ctx);

// ── Bootstrap ──────────────────────────────────────────────────────────────────
init();
