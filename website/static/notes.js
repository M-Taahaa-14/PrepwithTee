/**
 * notes.js — Student personal notes hub.
 * Phase 2+3: tab navigation, richer cards, mistake/revision flags,
 * location_json written on save, jump-to-source via note-context.js.
 */

import { requireAuth } from '/auth.js';
import { resolveLocation, captureContext, locationLabel } from './note-context.js';

// ── State ──────────────────────────────────────────────────────────────────────
let _notes         = [];
let _viewMode      = 'list';     // 'list' | 'grid'
let _activeTab     = 'all';      // 'all'|'pinned'|'mistakes'|'revision'|'papers'|'flashcards'|'tutor'
let _editingId     = null;       // note id being edited (null = new)
let _editCtx       = null;       // { linked_type, linked_id, linked_label, location_json }
let _selectedColor = 'yellow';
let _selectedType  = 'text';
let _isMistake        = false;
let _isExamRevision   = false;
let _tags          = [];
let _searchTimer;
let _autosaveTimer;
let _enrollments   = [];

// ── DOM refs ───────────────────────────────────────────────────────────────────
const body       = document.getElementById('nh-body');
const overlay    = document.getElementById('nh-overlay');
const newBtn     = document.getElementById('nh-new-btn');
const closeBtn   = document.getElementById('nh-close-btn');
const cancelBtn  = document.getElementById('nh-cancel-btn');
const saveBtn    = document.getElementById('nh-save-btn');
const titleEl    = document.getElementById('nh-modal-title');
const titleIn    = document.getElementById('nh-title-input');
const contentIn  = document.getElementById('nh-content-input');
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

// Filters / view
const fSubject = document.getElementById('nh-filter-subject');
const fSearch  = document.getElementById('nh-search');
const viewList = document.getElementById('nh-view-list');
const viewGrid = document.getElementById('nh-view-grid');

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  await requireAuth();
  await loadEnrollments();
  await loadNotes();
  bindEvents();
}

async function loadEnrollments() {
  try {
    const r = await fetch('/api/enrollments');
    if (r.ok) {
      const data = await r.json();
      _enrollments = (data.enrollments || []).filter(e => e.status === 'active');
    }
  } catch (_) {}
  populateSubjectFilters(); // always called; uses ALL_SUBJECTS fallback if no enrollments
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
    ? _enrollments.map(e => ({code: e.syllabus, label: subjectLabel(e.syllabus)}))
    : ALL_SUBJECTS;
  const opts = source.map(s =>
    `<option value="${esc(s.code)}">${esc(s.label)}</option>`
  ).join('');
  fSubject.insertAdjacentHTML('beforeend', opts);
  subjectIn.insertAdjacentHTML('beforeend', opts);
}

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
    body.innerHTML = `<div class="nh-empty"><div class="nh-empty-ico">⚠️</div><h3>Couldn't load notes</h3><p>Check your connection and try again.</p></div>`;
  }
}

function buildFilterParams() {
  const p = new URLSearchParams();
  if (fSubject.value) p.set('syllabus', fSubject.value);
  const q = fSearch.value.trim();
  if (q) p.set('q', q);

  switch (_activeTab) {
    case 'pinned':     p.set('pinned', 'true');                        break;
    case 'mistakes':   p.set('is_mistake', 'true');                    break;
    case 'revision':   p.set('is_exam_revision', 'true');              break;
    case 'papers':     p.set('linked_type', 'paper');                  break;
    case 'flashcards': p.set('linked_type', 'flashcard_block');        break;
    case 'tutor':      p.set('linked_type', 'tutor_message');          break;
  }
  return p.toString();
}

// ── Render ─────────────────────────────────────────────────────────────────────
function render(notes) {
  const tab = _activeTab;
  const count = notes.length;
  countEl.textContent = count ? `${count} note${count === 1 ? '' : 's'}` : '';

  if (!count) {
    const emptyMsg = {
      mistakes:   'No mistake notes yet. After a wrong answer, tap "Add mistake note" to record it.',
      revision:   'No exam revision notes yet. Mark important notes with ⭐ Exam Revision.',
      pinned:     'No pinned notes. Pin a note to keep it at the top of your dashboard.',
      papers:     'No notes linked to past papers yet.',
      flashcards: 'No notes linked to flashcards yet.',
      tutor:      'No notes linked to AI Tutor conversations yet.',
    }[tab] || 'Click <strong>New Note</strong> to jot your first thought, bullet, or sticky reminder.';
    body.innerHTML = `<div class="nh-empty"><div class="nh-empty-ico">📝</div><h3>No notes yet</h3><p>${emptyMsg}</p></div>`;
    return;
  }

  _viewMode === 'grid' ? renderMasonry(notes) : renderList(notes);
}

function renderList(notes) {
  const html = notes.map(n => {
    const icon    = n.type === 'sticky' ? '📌' : '📄';
    const preview = (n.content || '').replace(/\n/g, ' ').slice(0, 130);
    const date    = relDate(n.updated_at || n.created_at);
    const pinned  = n.pinned_to_dashboard;
    const badges  = buildBadges(n);
    const breadcrumb = buildBreadcrumb(n);
    const jumpBtn    = buildJumpBtn(n);
    const tagsHtml   = buildTagsHtml(n);

    return `
      <div class="nh-note-row" data-id="${n.id}">
        <div class="nh-note-row-ico">${icon}</div>
        <div class="nh-note-row-body">
          ${badges ? `<div class="nh-card-flags">${badges}</div>` : ''}
          <div class="nh-note-row-title">${n.title ? esc(n.title) : '<em style="color:var(--grey);font-style:italic">Untitled</em>'}</div>
          <div class="nh-note-row-preview">${esc(preview)}</div>
          ${breadcrumb ? `<div class="nh-breadcrumb">${breadcrumb}</div>` : ''}
          ${tagsHtml}
          <div class="nh-note-row-foot">
            <span class="nh-note-row-date">${date}</span>
          </div>
        </div>
        <div class="nh-note-row-actions">
          ${jumpBtn}
          <button class="nh-action-btn nh-pin-btn${pinned ? ' pinned' : ''}"
            data-id="${n.id}" data-pin="${pinned ? '0' : '1'}"
            title="${pinned ? 'Unpin' : 'Pin to dashboard'}" type="button">📌</button>
          <button class="nh-action-btn nh-edit-btn" data-id="${n.id}" title="Edit" type="button">✏️</button>
          <button class="nh-action-btn nh-del-btn"  data-id="${n.id}" title="Delete" type="button">🗑️</button>
        </div>
      </div>`;
  }).join('');
  body.innerHTML = `<div class="nh-list">${html}</div>`;
  bindNoteActions();
}

function renderMasonry(notes) {
  const html = notes.map(n => {
    const color   = n.color || 'yellow';
    const pinned  = n.pinned_to_dashboard;
    const date    = relDate(n.updated_at || n.created_at);
    const badges  = buildBadges(n);
    const breadcrumb = buildBreadcrumb(n);
    const jumpBtn    = buildJumpBtn(n);
    const tagsHtml   = buildTagsHtml(n);

    return `
      <div class="nh-sticky color-${color}" data-id="${n.id}">
        <div class="nh-sticky-actions">
          ${jumpBtn ? `<span style="margin-right:.2rem">${jumpBtn}</span>` : ''}
          <button class="nh-action-btn nh-pin-btn${pinned ? ' pinned' : ''}"
            data-id="${n.id}" data-pin="${pinned ? '0' : '1'}"
            title="${pinned ? 'Unpin' : 'Pin'}" type="button">📌</button>
          <button class="nh-action-btn nh-edit-btn" data-id="${n.id}" title="Edit" type="button">✏️</button>
          <button class="nh-action-btn nh-del-btn"  data-id="${n.id}" title="Delete" type="button">🗑️</button>
        </div>
        ${badges ? `<div class="nh-card-flags" style="margin-bottom:.35rem">${badges}</div>` : ''}
        ${n.title ? `<div class="nh-sticky-title">${esc(n.title)}</div>` : ''}
        <div class="nh-sticky-body">${esc(n.content || '')}</div>
        ${tagsHtml}
        <div class="nh-sticky-meta">
          <span>${date}</span>
          ${breadcrumb ? `<span class="nh-breadcrumb" style="margin-top:0">${breadcrumb}</span>` : ''}
        </div>
      </div>`;
  }).join('');
  body.innerHTML = `<div class="nh-masonry">${html}</div>`;
  bindNoteActions();
}

// ── Card helpers ───────────────────────────────────────────────────────────────
function buildBadges(n) {
  let out = '';
  if (n.is_mistake)        out += '<span class="nh-badge nh-badge-mistake">❌ Mistake</span>';
  if (n.is_exam_revision)  out += '<span class="nh-badge nh-badge-revision">⭐ Exam</span>';
  return out;
}

function buildBreadcrumb(n) {
  if (!n.linked_label && !n.location_json) return '';
  const icons = { paper:'📑', flashcard_block:'🗂️', chapter:'📖', tutor_message:'🤖' };
  const ico   = icons[n.linked_type] || '🔗';

  // Try to build a richer label from location_json
  let label = n.linked_label || '';
  if (n.location_json) {
    const loc = typeof n.location_json === 'string'
      ? (() => { try { return JSON.parse(n.location_json); } catch { return null; } })()
      : n.location_json;
    const ll = loc ? locationLabel(loc) : null;
    if (ll && ll !== label) label = label ? label + ' · ' + ll : ll;
  }

  return `<span class="nh-bc-ico">${ico}</span><span>${esc(label)}</span>`;
}

function buildTagsHtml(n) {
  let tags = [];
  try { tags = n.tags_json ? JSON.parse(n.tags_json) : []; } catch (_) {}
  if (!Array.isArray(tags) || !tags.length) return '';
  return '<div class="nh-card-tags">' + tags.map(t => `<span class="nh-card-tag">${esc(t)}</span>`).join('') + '</div>';
}

function buildJumpBtn(n) {
  // Try location_json first, then fall back to linked_type heuristics
  let url = null;
  if (n.location_json) {
    const loc = typeof n.location_json === 'string'
      ? (() => { try { return JSON.parse(n.location_json); } catch { return null; } })()
      : n.location_json;
    url = loc ? resolveLocation(loc) : null;
  }
  if (!url && n.linked_type) {
    // Fallback: best-effort URL without position
    const MAP = {
      paper:           n.linked_id ? `papers.html?key=${encodeURIComponent(n.linked_id)}` : null,
      flashcard_block: n.linked_id ? `flashcards.html?block=${n.linked_id}` : null,
      chapter:         'topical-progress.html',
      tutor_message:   'tutor.html',
    };
    url = MAP[n.linked_type] || null;
  }
  if (!url) return '';
  return `<button class="nh-jump-btn" data-jump="${esc(url)}" title="Jump to source" type="button">↗ Jump</button>`;
}

// ── Note action handlers ───────────────────────────────────────────────────────
function bindNoteActions() {
  body.querySelectorAll('[data-id]').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.closest('.nh-action-btn') || e.target.closest('.nh-jump-btn')) return;
      const id = parseInt(el.dataset.id);
      const note = _notes.find(n => n.id === id);
      if (note) openEditor(note);
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
      await pinNote(parseInt(btn.dataset.id), btn.dataset.pin === '1');
    });
  });
}

// ── Composer ───────────────────────────────────────────────────────────────────
function openComposer(ctx = null) {
  _editingId    = null;
  _editCtx      = ctx;
  _isMistake    = ctx?.isMistake    || false;
  _isExamRevision = ctx?.isExamRevision || false;
  titleEl.textContent = 'New Note';
  titleIn.value    = ctx?.titleOverride || '';
  contentIn.value  = ctx?.content       || '';
  subjectIn.value  = ctx?.syllabus      || '';
  setType('text');
  setColor('yellow');
  setTags([]);
  showContext(ctx);
  setFlag('mistake',  _isMistake);
  setFlag('revision', _isExamRevision);
  setAutosave('');
  overlay.classList.add('open');
  setTimeout(() => contentIn.focus(), 280);
}

function openEditor(note) {
  _editingId = note.id;
  _editCtx   = note.linked_type ? {
    linked_type: note.linked_type, linked_id: note.linked_id,
    linked_label: note.linked_label, location_json: note.location_json,
  } : null;
  _isMistake        = !!note.is_mistake;
  _isExamRevision   = !!note.is_exam_revision;
  titleEl.textContent = 'Edit Note';
  titleIn.value    = note.title || '';
  contentIn.value  = note.content || '';
  subjectIn.value  = note.syllabus || '';
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

function setType(t) {
  _selectedType = t;
  document.querySelectorAll('.nh-type-pill').forEach(p =>
    p.classList.toggle('active', p.dataset.type === t));
  colorWrap.style.display = t === 'sticky' ? '' : 'none';
}

function setColor(c) {
  _selectedColor = c;
  document.querySelectorAll('.nh-color-swatch').forEach(s =>
    s.classList.toggle('active', s.dataset.color === c));
}

function setFlag(flag, active) {
  if (flag === 'mistake') {
    _isMistake = active;
    flagMistake.classList.toggle('active-mistake', active);
  } else {
    _isExamRevision = active;
    flagRevision.classList.toggle('active-revision', active);
  }
}

function showContext(ctx) {
  if (!ctx || !ctx.linked_label) { contextRow.style.display = 'none'; return; }
  contextRow.style.display = '';
  const icons = { paper:'📑', flashcard_block:'🗂️', chapter:'📖', tutor_message:'🤖' };
  contextTag.textContent = (icons[ctx.linked_type] || '🔗') + ' ' + ctx.linked_label;
}

function setAutosave(msg, saved = false) {
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
      _tags.splice(i, 1);
      renderTagChips();
    });
    tagsWrap.insertBefore(chip, tagsInput);
  });
}

function initTagsInput() {
  tagsInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const val = tagsInput.value.trim().replace(/,/g, '');
      if (val && !_tags.includes(val) && _tags.length < 8) {
        _tags.push(val);
        renderTagChips();
      }
      tagsInput.value = '';
    }
    if (e.key === 'Backspace' && !tagsInput.value && _tags.length) {
      _tags.pop();
      renderTagChips();
    }
  });
  tagsWrap.addEventListener('click', () => tagsInput.focus());
}

// ── Save ───────────────────────────────────────────────────────────────────────
function buildPayload() {
  // Capture location_json: use whatever was passed in context, or auto-detect
  const ctxLoc = _editCtx?.location_json || null;
  const loc     = ctxLoc || captureContext();

  return {
    type:            _selectedType,
    title:           titleIn.value.trim() || null,
    content:         contentIn.value.trim() || null,
    color:           _selectedType === 'sticky' ? _selectedColor : null,
    syllabus:        subjectIn.value || null,
    linked_type:     _editCtx?.linked_type  || null,
    linked_id:       _editCtx?.linked_id    || null,
    linked_label:    _editCtx?.linked_label || null,
    location_json:   loc,
    is_mistake:      _isMistake,
    is_exam_revision: _isExamRevision,
    tags_json:        JSON.stringify(_tags),
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
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } else {
      r = await fetch('/api/notes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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

// Debounced auto-save for edit mode
function scheduleAutosave() {
  if (!_editingId) return;
  clearTimeout(_autosaveTimer);
  setAutosave('Saving…');
  _autosaveTimer = setTimeout(async () => {
    const payload = buildPayload();
    try {
      const r = await fetch(`/api/notes/${_editingId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error();
      setAutosave('✓ Saved', true);
      // Update local cache
      const updated = await r.json();
      const idx = _notes.findIndex(n => n.id === _editingId);
      if (idx !== -1) _notes[idx] = updated;
    } catch (_) {
      setAutosave('Save failed', false);
    }
  }, 1400);
}

async function deleteNote(id) {
  try {
    const r = await fetch(`/api/notes/${id}`, { method: 'DELETE' });
    if (!r.ok) throw new Error();
    showToast('🗑️ Note deleted');
    _notes = _notes.filter(n => n.id !== id);
    render(_notes);
  } catch (_) {
    showToast('❌ Couldn\'t delete note', true);
  }
}

async function pinNote(id, pinned) {
  try {
    const r = await fetch(`/api/notes/${id}/pin`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned }),
    });
    if (!r.ok) throw new Error();
    showToast(pinned ? '📌 Pinned to dashboard' : '📌 Unpinned');
    const idx = _notes.findIndex(n => n.id === id);
    if (idx !== -1) _notes[idx].pinned_to_dashboard = pinned;
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
  initTagsInput();

  // Type pills
  document.querySelectorAll('.nh-type-pill').forEach(p =>
    p.addEventListener('click', () => setType(p.dataset.type)));

  // Colour swatches
  document.querySelectorAll('.nh-color-swatch').forEach(s =>
    s.addEventListener('click', () => setColor(s.dataset.color)));

  // Flag toggles
  flagMistake.addEventListener('click',  () => setFlag('mistake',  !_isMistake));
  flagRevision.addEventListener('click', () => setFlag('revision', !_isExamRevision));

  // Auto-save while editing
  [titleIn, contentIn].forEach(el =>
    el.addEventListener('input', scheduleAutosave));

  // Keyboard
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeComposer();
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && overlay.classList.contains('open'))
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

  // Subject filter
  fSubject.addEventListener('change', loadNotes);

  // Search
  fSearch.addEventListener('input', () => {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(loadNotes, 280);
  });

  // View toggle
  viewList.addEventListener('click', () => {
    _viewMode = 'list';
    viewList.classList.add('active');
    viewGrid.classList.remove('active');
    render(_notes);
  });
  viewGrid.addEventListener('click', () => {
    _viewMode = 'grid';
    viewGrid.classList.add('active');
    viewList.classList.remove('active');
    render(_notes);
  });
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function showSkeleton() {
  const lines = Array.from({length: 4}, () =>
    `<div style="background:#fff;border:1.5px solid var(--line);border-radius:14px;padding:1rem">
      <div class="nh-skeleton" style="width:60%;margin-bottom:8px"></div>
      <div class="nh-skeleton" style="width:90%"></div>
      <div class="nh-skeleton" style="width:45%;margin-top:8px"></div>
    </div>`).join('');
  body.innerHTML = `<div class="nh-list">${lines}</div>`;
}

function relDate(iso) {
  if (!iso) return '';
  const d    = new Date(iso);
  const diff = Math.floor((Date.now() - d) / 1000);
  if (diff < 60)     return 'just now';
  if (diff < 3600)   return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400)  return Math.floor(diff / 3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function subjectLabel(code) {
  const MAP = {
    '4024':'O Level Maths D', '0580':'IGCSE Maths',
    '5054':'O Level Physics',  '0625':'IGCSE Physics',
    '2210':'O Level CS',       '0478':'IGCSE CS',
    '5070':'O Level Chemistry','0620':'IGCSE Chemistry',
    '9709':'A Level Maths',    '9702':'A Level Physics', '9618':'A Level CS',
  };
  return MAP[code] || code;
}

function esc(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let _toastTimer;
function showToast(msg, isWarn = false) {
  toast.textContent = msg;
  toast.style.background = isWarn ? 'var(--red, #c0392b)' : 'var(--navy)';
  toast.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

// ── Public API — used by other pages that call openNoteComposer ────────────────
window.openNoteComposer = function(ctx) { openComposer(ctx); };

// ── Bootstrap ──────────────────────────────────────────────────────────────────
init();
