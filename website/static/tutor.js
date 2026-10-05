import { getUser } from "./auth.js?v=20261005a";

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const $  = (id) => document.getElementById(id);
  const app       = $('tutor-app');
  const messages  = $('tutor-messages');
  const welcome   = $('tc-welcome');
  const form      = $('tc-form');
  const msgTA     = $('tc-msg');
  const sendBtn   = $('tc-send');
  const attachBtn = $('tc-attach-btn');
  const fileInput = $('tc-file-input');
  const micBtn    = $('tc-mic-btn');
  const attachStrip = $('tc-attach-strip');
  const dropOverlay = $('tc-drop-overlay');
  const subjectSel  = $('tc-subject');
  const paperSel    = $('tc-paper');
  const paperLabel  = $('tc-paper-label');
  const topicSel    = $('tc-topic');
  const sessionScroll = $('tc-session-scroll');
  const sessionsEmpty = $('tc-sessions-empty');
  const newChatBtn    = $('tc-new-chat-btn');
  const authNudge     = $('tc-auth-nudge');
  const modeBadge     = $('tc-mode-badge');
  const chatTitleMain = $('tc-chat-title-main');
  const chatTitleSub  = $('tc-chat-title-sub');
  const starterChips  = $('tc-starter-chips');

  // ── State ─────────────────────────────────────────────────────────────────
  let currentUser = null;
  let META = null;
  let busy = false;
  let mode = 'normal'; // 'normal' | 'socratic' | 'exam'

  let session = {
    id: null,
    subject: null,
    topic: null,
    messages: [],
    summary: null,
    title: null,
    locked: false  // subject/topic locked after first message
  };

  let attachedFiles = []; // { name, dataUri }

  // ── Boot ──────────────────────────────────────────────────────────────────
  init();

  async function init() {
    currentUser = await getUser();

    if (currentUser) {
      authNudge.style.display = 'none';
      await loadSessions();
    } else {
      authNudge.style.display = 'block';
      sessionsEmpty.textContent = 'Sign in to save your conversations here.';
    }

    await loadMeta();
    wireEvents();
    checkDeepLink();
    setMode('normal');
  }

  // ── Metadata (subjects / topics) ─────────────────────────────────────────
  async function loadMeta() {
    subjectSel.innerHTML = '<option value="">Loading…</option>';
    subjectSel.disabled = true;

    try {
      const [data, enrollRes, meRes] = await Promise.all([
        apiFetch('/api/meta'),
        apiFetch('/api/enrollments').catch(() => null),
        fetch('/auth/me', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      META = data;
      let subjects = data.subjects || [];
      const _isPrivileged = meRes?.role === 'teacher' || meRes?.role === 'admin';

      if (!_isPrivileged && enrollRes && enrollRes.enrollments) {
        const activeCodes = enrollRes.enrollments.map(e => e.syllabus);
        subjects = subjects.filter(s => activeCodes.includes(s.syllabus));
      }

      subjectSel.innerHTML = '<option value="">Any subject</option>';
      subjects.forEach(s => {
        const o = new Option(`${s.subject} (${s.syllabus})`, s.syllabus);
        subjectSel.appendChild(o);
      });
      subjectSel.disabled = false;
      if (subjectSel._sdInstance) subjectSel._sdInstance.refresh();

      // Auto-select from last session
      if (currentUser) {
        try {
          const sd = await apiFetch('/api/tutor/sessions');
          const last = (sd.sessions || [])[0];
          if (last?.subject && subjectSel.querySelector(`option[value="${last.subject}"]`)) {
            subjectSel.value = last.subject;
            if (subjectSel._sdInstance) subjectSel._sdInstance.refresh();
            populatePapers(last.subject);
            populateTopics(last.subject, '');
          }
        } catch (_) {}
      }
    } catch (_) {
      subjectSel.innerHTML = '<option value="">Any subject</option>';
      subjectSel.disabled = false;
      if (subjectSel._sdInstance) subjectSel._sdInstance.refresh();
    }
  }

  function populatePapers(syllabus) {
    if (!paperSel || !paperLabel) return;
    if (!syllabus || !META) {
      paperSel.style.display = 'none'; paperLabel.style.display = 'none'; return;
    }
    const s = META.subjects.find(x => x.syllabus === syllabus);
    const components = s?.components || [];
    if (components.length < 2) {
      paperSel.style.display = 'none'; paperLabel.style.display = 'none'; return;
    }
    paperSel.innerHTML = '<option value="">All papers</option>';
    components.forEach(c => paperSel.appendChild(new Option(c.label, String(c.paper))));
    paperSel.style.display = 'block';
    paperLabel.style.display = 'block';
    paperSel.value = '';
  }

  function populateTopics(syllabus, paperNum) {
    topicSel.innerHTML = '<option value="">Any topic</option>';
    if (!syllabus || !META) return;
    const s = META.subjects.find(x => x.syllabus === syllabus);
    if (!s || !s.topics?.length) return;

    const components = s.components || [];
    const hasMultiple = components.length > 1;
    const filter = paperNum ? parseInt(paperNum) : null;

    // Which component paper does this topic primarily belong to?
    // Uses paper_scope from taxonomy first; falls back to whichever paper
    // has the most classified questions (handles syllabuses like 0580 where
    // the taxonomy has no papers field).
    const primaryPaper = (t) => {
      if (t.paper_scope?.length) {
        return t.paper_scope.find(p => components.some(c => c.paper === p)) ?? null;
      }
      const counts = t.papers || {};
      let best = null, bestN = 0;
      for (const [p, n] of Object.entries(counts)) {
        const pNum = parseInt(p);
        if (components.some(c => c.paper === pNum) && n > bestN) {
          bestN = n; best = pNum;
        }
      }
      return best;
    };

    // Is this topic in scope for a given paper filter?
    const inPaper = (t, pf) => {
      if (t.paper_scope?.length) return t.paper_scope.includes(pf);
      return (t.papers?.[String(pf)] ?? 0) > 0;
    };

    if (hasMultiple && !filter) {
      // Grouped view — each topic appears in exactly one component group.
      components.forEach(comp => {
        const compTopics = s.topics.filter(t => primaryPaper(t) === comp.paper);
        if (!compTopics.length) return;
        const grp = document.createElement('optgroup');
        grp.label = comp.label;
        compTopics.forEach(t =>
          grp.appendChild(new Option(`${t.display || t.name} (${t.count})`, t.name)));
        topicSel.appendChild(grp);
      });
      // Topics with no assignable paper (zero questions everywhere)
      const ungrouped = s.topics.filter(t => primaryPaper(t) === null);
      if (ungrouped.length) {
        const grp = document.createElement('optgroup');
        grp.label = 'Other';
        ungrouped.forEach(t =>
          grp.appendChild(new Option(`${t.display || t.name} (${t.count})`, t.name)));
        topicSel.appendChild(grp);
      }
    } else if (filter) {
      // Filtered view — topics that belong to this paper.
      s.topics.forEach(t => {
        if (!inPaper(t, filter)) return;
        topicSel.appendChild(new Option(`${t.display || t.name} (${t.count})`, t.name));
      });
    } else {
      // Single-paper subject — plain list in taxonomy (syllabus) order.
      s.topics.forEach(t =>
        topicSel.appendChild(new Option(`${t.display || t.name} (${t.count})`, t.name)));
    }

    updateStarterChips(s.subject);
  }

  function updateStarterChips(subjectName) {
    if (!subjectName) return;
    const sub = $('tc-welcome-sub');
    if (sub) sub.textContent = `You're studying ${subjectName}. Ask me anything or pick a prompt below.`;

    // Add subject-specific chips
    const topic = topicSel.value || 'a topic from your syllabus';
    const extra = [
      { emoji: '🔬', label: `Explain ${topic}`, prompt: `Explain ${topic} in ${subjectName} step by step, then give me one worked example.` },
      { emoji: '📝', label: `Practice: ${topic}`, prompt: `Give me 5 Cambridge-style practice questions on ${topic} in ${subjectName} with worked answers at the end.` },
    ];
    // Append to existing chips (don't replace — keep generic ones)
    extra.forEach(({ emoji, label, prompt }) => {
      if ([...starterChips.querySelectorAll('.tc-starter-chip')].some(c => c.dataset.prompt === prompt)) return;
      const btn = document.createElement('button');
      btn.className = 'tc-starter-chip';
      btn.dataset.prompt = prompt;
      btn.textContent = `${emoji} ${label}`;
      btn.addEventListener('click', () => sendPrompt(prompt));
      starterChips.appendChild(btn);
    });
  }

  // ── Mode toggle ───────────────────────────────────────────────────────────
  function setMode(m) {
    mode = m;
    if (session) session.mode = m;
    document.querySelectorAll('.tc-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === m);
      if (btn.dataset.mode === m) btn.classList.add(m);
      else btn.classList.remove('socratic', 'exam');
    });

    modeBadge.className = 'tc-mode-badge';
    if (m === 'socratic') {
      modeBadge.className = 'tc-mode-badge';
      modeBadge.textContent = '🎓 Guide Me Mode';
    } else if (m === 'exam') {
      modeBadge.className = 'tc-mode-badge exam';
      modeBadge.textContent = '⚡ Exam Mode';
    } else {
      modeBadge.className = 'tc-mode-badge hidden';
    }
  }

  // ── Wire all events ───────────────────────────────────────────────────────
  function wireEvents() {
    // Subject / Paper / Topic selectors
    subjectSel.addEventListener('change', () => {
      if (session.locked) return;
      populatePapers(subjectSel.value);
      populateTopics(subjectSel.value, '');
    });
    if (paperSel) {
      paperSel.addEventListener('change', () => {
        if (session.locked) return;
        populateTopics(subjectSel.value, paperSel.value);
      });
    }

    // Mode buttons
    document.querySelectorAll('.tc-mode-btn').forEach(btn => {
      btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });

    // Mode Help button and card
    const helpBtn = document.getElementById('tc-mode-help-btn');
    const helpCard = document.getElementById('tc-mode-help-card');
    const helpClose = document.getElementById('tc-mode-help-close');
    if (helpBtn && helpCard && helpClose) {
      helpBtn.addEventListener('click', () => {
        const visible = helpCard.style.display === 'block';
        helpCard.style.display = visible ? 'none' : 'block';
      });
      helpClose.addEventListener('click', () => {
        helpCard.style.display = 'none';
      });
    }

    // Sidebar toggle button
    const sidebarToggle = $('tc-sidebar-toggle');
    if (sidebarToggle) {
      if (localStorage.getItem('tutor_sidebar_collapsed') === '1') {
        app.classList.add('sidebar-collapsed');
      }
      sidebarToggle.addEventListener('click', () => {
        app.classList.toggle('sidebar-collapsed');
        const isCollapsed = app.classList.contains('sidebar-collapsed');
        localStorage.setItem('tutor_sidebar_collapsed', isCollapsed ? '1' : '0');
      });
    }

    // New chat
    newChatBtn.addEventListener('click', startNewChat);

    // Starter chips
    starterChips.addEventListener('click', e => {
      const chip = e.target.closest('.tc-starter-chip');
      if (chip) sendPrompt(chip.dataset.prompt);
    });

    // Form submit
    form.addEventListener('submit', e => {
      e.preventDefault();
      const text = msgTA.value.trim();
      const imgs  = [...attachedFiles];
      msgTA.value = '';
      autosizeTA();
      clearAttachments();
      send(text, imgs);
    });

    // Textarea auto-size + Enter to submit
    msgTA.addEventListener('input', autosizeTA);
    msgTA.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });

    // Attach / file
    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', e => { handleFiles(e.target.files); fileInput.value = ''; });

    // Drag & drop on messages area
    messages.addEventListener('dragenter', e => { e.preventDefault(); dropOverlay.classList.add('visible'); });
    messages.addEventListener('dragover',  e => { e.preventDefault(); });
    messages.addEventListener('dragleave', e => { if (!messages.contains(e.relatedTarget)) dropOverlay.classList.remove('visible'); });
    messages.addEventListener('drop', e => {
      e.preventDefault(); dropOverlay.classList.remove('visible');
      if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    });

    // Clipboard paste
    document.addEventListener('paste', e => {
      const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
      if (item) handleFiles([item.getAsFile()]);
    });

    // Voice mic
    wireMic();
  }

  // ── File attachment ───────────────────────────────────────────────────────
  function handleFiles(files) {
    if (attachedFiles.length + files.length > 5) {
      return toastError('You can attach up to 5 images per message.');
    }
    [...files].forEach(file => {
      if (!file.type.startsWith('image/')) return toastError('Images only (PNG, JPEG, WebP).');
      if (file.size > 10 * 1024 * 1024) return toastError(`${file.name} is too large (max 10 MB).`);
      const reader = new FileReader();
      reader.onload = e => { attachedFiles.push({ name: file.name, dataUri: e.target.result }); renderThumbs(); };
      reader.readAsDataURL(file);
    });
  }

  function renderThumbs() {
    attachStrip.innerHTML = '';
    attachStrip.classList.toggle('has-files', attachedFiles.length > 0);
    attachedFiles.forEach((f, i) => {
      const t = document.createElement('div');
      t.className = 'tc-thumb';
      t.innerHTML = `<img src="${f.dataUri}" alt="${esc(f.name)}">
        <button type="button" class="tc-thumb-rm" title="Remove">✕</button>`;
      t.querySelector('.tc-thumb-rm').addEventListener('click', () => {
        attachedFiles.splice(i, 1); renderThumbs();
      });
      attachStrip.appendChild(t);
    });
  }

  function clearAttachments() { attachedFiles = []; renderThumbs(); }

  // ── Voice mic ─────────────────────────────────────────────────────────────
  function wireMic() {
    let recorder = null, chunks = [], recoding = false;
    micBtn.addEventListener('click', async () => {
      if (recoding) { recorder?.stop(); return; }
      if (!navigator.mediaDevices?.getUserMedia) {
        return alert('Voice input is not supported in this browser.');
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        chunks = [];
        recorder = new MediaRecorder(stream);
        recorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
        recorder.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          recoding = false;
          micBtn.classList.remove('recording');
          const blob = new Blob(chunks, { type: 'audio/webm' });
          const fd = new FormData();
          fd.append('audio', blob, 'voice.webm');
          micBtn.disabled = true;
          try {
            const r = await fetch('/api/transcribe', { method: 'POST', body: fd });
            const d = await r.json().catch(() => ({}));
            if (r.ok && d.text) {
              msgTA.value = (msgTA.value ? msgTA.value.trimEnd() + ' ' : '') + d.text;
              autosizeTA(); msgTA.focus();
            }
          } catch (_) {} finally { micBtn.disabled = false; }
        };
        recorder.start();
        recoding = true;
        micBtn.classList.add('recording');
      } catch (_) { alert('Microphone access denied.'); }
    });
  }

  // ── Session management ────────────────────────────────────────────────────
  async function loadSessions() {
    try {
      const data = await apiFetch('/api/tutor/sessions');
      renderSessions(data.sessions || []);
    } catch (_) {}
  }

  function filterSessions() {
    const q = (document.getElementById('tc-search')?.value || '').trim().toLowerCase();
    let shown = 0;
    sessionScroll.querySelectorAll('.tc-date-group, .tc-pinned-group').forEach(grp => {
      let any = false;
      grp.querySelectorAll('.tc-session-item').forEach(it => {
        const ok = !q || it.textContent.toLowerCase().includes(q);
        it.hidden = !ok;
        any ||= ok;
      });
      grp.hidden = !any;
      shown += any ? 1 : 0;
    });
    const none = document.getElementById('tc-search-none');
    if (none) none.hidden = !q || shown > 0;
  }
  document.getElementById('tc-search')?.addEventListener('input', filterSessions);

  function renderSessions(sessions) {
    [...sessionScroll.querySelectorAll('.tc-date-group, .tc-pinned-group')].forEach(el => el.remove());
    sessionsEmpty.style.display = sessions.length ? 'none' : 'block';
    if (!sessions.length) return;

    // Pinned sessions at top
    const pinned = sessions.filter(s => s.pinned);
    if (pinned.length) {
      const grp = document.createElement('div');
      grp.className = 'tc-pinned-group';
      grp.innerHTML = '<span class="tc-date-label tc-pinned-label">Pinned</span>';
      pinned.forEach(sess => grp.appendChild(makeSessionItem(sess)));
      sessionScroll.appendChild(grp);
    }

    const unpinned = sessions.filter(s => !s.pinned);
    const groups = groupByDate(unpinned);
    const order  = ['Today', 'Yesterday', 'Past 7 days', 'Older'];
    order.forEach(label => {
      const items = groups[label];
      if (!items?.length) return;
      const grp = document.createElement('div');
      grp.className = 'tc-date-group';
      grp.innerHTML = `<span class="tc-date-label">${label}</span>`;
      items.forEach(sess => grp.appendChild(makeSessionItem(sess)));
      sessionScroll.appendChild(grp);
    });
    filterSessions();
  }

  function makeSessionItem(sess) {
    const el = document.createElement('div');
    el.className = 'tc-session-item' + (sess.id === session.id ? ' active' : '') + (sess.pinned ? ' pinned' : '');
    el.dataset.id = sess.id;
    const subjTag = sess.subject ? `<span class="tc-session-sub">${sess.subject}</span>` : '';
    el.innerHTML = `
      <div class="tc-session-label">
        <span class="tc-session-title">${esc(sess.title || 'Chat')}</span>
        ${subjTag}
      </div>
      <div class="tc-session-acts">
        <button class="tc-session-act rename-btn" title="Rename">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button class="tc-session-act pin-btn" title="${sess.pinned ? 'Unpin' : 'Pin'}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="${sess.pinned ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17z"/></svg>
        </button>
        <button class="tc-session-act share-btn" title="Export chat">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
        </button>
        <button class="tc-session-act del-btn" title="Delete">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
        </button>
      </div>
    `;
    el.addEventListener('click', e => {
      if (e.target.closest('.tc-session-act')) return;
      loadSession(sess.id);
    });
    el.querySelector('.rename-btn').addEventListener('click', e => { e.stopPropagation(); renameSession(sess.id, sess.title || 'Chat'); });
    el.querySelector('.pin-btn').addEventListener('click', e => { e.stopPropagation(); togglePin(sess.id, !sess.pinned); });
    el.querySelector('.share-btn').addEventListener('click', e => { e.stopPropagation(); shareSession(sess.id); });
    el.querySelector('.del-btn').addEventListener('click', e => { e.stopPropagation(); if (confirm('Delete this conversation?')) deleteSession(sess.id); });
    return el;
  }

  function groupByDate(sessions) {
    const now = new Date();
    const groups = { 'Today': [], 'Yesterday': [], 'Past 7 days': [], 'Older': [] };
    sessions.forEach(s => {
      const d = new Date(s.updated_at);
      const diffDays = Math.floor((now - d) / 86400000);
      if (d.toDateString() === now.toDateString()) groups['Today'].push(s);
      else if (diffDays === 1) groups['Yesterday'].push(s);
      else if (diffDays < 7) groups['Past 7 days'].push(s);
      else groups['Older'].push(s);
    });
    return groups;
  }

  async function loadSession(sessionId) {
    try {
      const data = await apiFetch(`/api/tutor/sessions/${sessionId}`);
      const sess = data.session;
      session = {
        id: sess.id, subject: sess.subject, topic: sess.topic,
        mode: sess.mode || 'normal',
        messages: sess.messages || [], summary: sess.summary,
        title: sess.title, locked: true
      };

      if (sess.subject) {
        subjectSel.value = sess.subject;
        populatePapers(sess.subject);
        populateTopics(sess.subject, '');
      }
      if (sess.topic) topicSel.value = sess.topic;
      subjectSel.disabled = true; topicSel.disabled = true;
      if (paperSel) paperSel.disabled = true;

      setMode(sess.mode || 'normal');
      setChatTitle(sess.title || 'Chat', sess.subject ? `${sess.subject}${sess.topic ? ' · ' + sess.topic : ''}` : '');
      clearMessages();

      session.messages.forEach(m => {
        const attachments = parseAttachments(m.attachments);
        let html = '';
        attachments.forEach(a => { if (a.url) html += `<img src="${a.url}" alt="attachment">`; });
        html += m.content;
        renderBubble(m.role === 'user' ? 'user' : 'bot', html, m.id);
      });

      highlightActiveSession(sessionId);
      if (window.innerWidth <= 900) app.classList.remove('sidebar-open');
    } catch (_) { toastError('Failed to load conversation.'); }
  }

  async function togglePin(id, pinned) {
    try { await apiFetch(`/api/tutor/sessions/${id}`, 'PATCH', { pinned }); await loadSessions(); } catch (_) {}
  }

  async function deleteSession(id) {
    try {
      await apiFetch(`/api/tutor/sessions/${id}`, 'DELETE');
      if (session.id === id) startNewChat();
      await loadSessions();
    } catch (_) {}
  }

  async function renameSession(id, currentTitle) {
    const item = document.querySelector(`.tc-session-item[data-id="${id}"]`);
    if (!item) return;
    const titleEl = item.querySelector('.tc-session-title');
    if (!titleEl) return;

    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentTitle;
    input.className = 'tc-rename-input';
    titleEl.replaceWith(input);
    input.focus(); input.select();

    let saved = false;
    const restore = (text) => {
      const span = document.createElement('span');
      span.className = 'tc-session-title';
      span.textContent = text;
      if (input.parentNode) input.replaceWith(span);
    };
    const save = async () => {
      if (saved) return; saved = true;
      const newTitle = input.value.trim() || currentTitle;
      restore(newTitle);
      try { await apiFetch(`/api/tutor/sessions/${id}`, 'PATCH', { title: newTitle }); await loadSessions(); }
      catch (_) {}
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') save();
      if (e.key === 'Escape') { saved = true; restore(currentTitle); }
    });
    input.addEventListener('blur', save);
  }

  async function shareSession(id) {
    try {
      const data = await apiFetch(`/api/tutor/sessions/${id}`);
      const sess = data.session;
      const msgs = sess.messages || [];
      const title = sess.title || 'AI Tutor Chat';
      const lines = [`# ${title}`, ''];
      msgs.forEach(m => {
        const role = m.role === 'user' ? '**You:**' : '**AI Tutor:**';
        const text = (m.content || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
        if (text) lines.push(role, text, '');
      });
      await navigator.clipboard.writeText(lines.join('\n'));
      const toast = document.createElement('div');
      toast.className = 'tc-toast';
      toast.textContent = '✓ Chat copied to clipboard';
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 2500);
    } catch (_) { toastError('Could not export this chat.'); }
  }

  function startNewChat() {
    session = { id: null, subject: null, topic: null, messages: [], summary: null, title: null, locked: false };
    subjectSel.disabled = false; topicSel.disabled = false;
    if (paperSel) { paperSel.disabled = false; paperSel.value = ''; }
    if (paperLabel) { /* keep visible if paper was showing */ }
    clearMessages();
    setChatTitle('AI Tutor', 'Ask anything from your Cambridge syllabus');
    clearAttachments();
    highlightActiveSession(null);
    if (window.innerWidth <= 900) app.classList.remove('sidebar-open');
  }

  function highlightActiveSession(id) {
    document.querySelectorAll('.tc-session-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === id);
    });
  }

  // ── Chat rendering ─────────────────────────────────────────────────────────
  function clearMessages() {
    messages.innerHTML = '';
    messages.appendChild(welcome);
    welcome.style.display = 'flex';
    dropOverlay.style.display = '';
    messages.appendChild(dropOverlay);
  }

  function showChatArea() {
    if (welcome) welcome.style.display = 'none';
  }

  function renderBubble(role, contentHtml, msgId = null) {
    showChatArea();
    const isUser = role === 'user';

    // Check if already exists (streaming update)
    let row = msgId ? document.getElementById(`tc-msg-${msgId}`) : null;
    if (!row) {
      row = document.createElement('div');
      row.className = `tc-msg ${isUser ? 'user' : 'bot'}`;
      if (msgId) row.id = `tc-msg-${msgId}`;

      const avatarText = isUser ? (currentUser?.email?.[0]?.toUpperCase() || 'U') : '🦉';
      const avatarClass = isUser ? 'user' : 'owl';
      row.innerHTML = `
        <div class="tc-avatar ${avatarClass}">${avatarText}</div>
        <div class="tc-bubble-wrap" style="min-width:0;flex:1;max-width:min(80ch,90%)">
          <div class="tc-bubble"></div>
          ${!isUser && msgId ? `<div class="tc-msg-acts"></div>` : ''}
          ${isUser ? `<div class="tc-user-acts"><button type="button" class="tc-act-btn tc-edit-btn" title="Edit and resend">✏️ Edit</button></div>` : ''}
        </div>
      `;
      messages.appendChild(row);
      if (isUser) row.querySelector('.tc-edit-btn').addEventListener('click', () => editMessage(row));
    }
    if (msgId) row.dataset.msg = msgId;

    const bubble = row.querySelector('.tc-bubble');
    bubble.innerHTML = contentHtml;

    // Wire action bar for bot messages
    if (!isUser && msgId) {
      const acts = row.querySelector('.tc-msg-acts');
      if (acts && !acts.children.length) {
        acts.innerHTML = `
          <button class="tc-act-btn feedback-up" title="Helpful">👍 Helpful</button>
          <button class="tc-act-btn feedback-dn" title="Not helpful">👎</button>
          <button class="tc-act-btn regen-btn" title="Try another explanation">🔄 Regenerate</button>
          <button class="tc-act-btn copy-btn" title="Copy to clipboard">📋 Copy</button>
        `;
        acts.querySelector('.feedback-up').addEventListener('click', e => submitFeedback(msgId, 'up', e.target));
        acts.querySelector('.feedback-dn').addEventListener('click', e => submitFeedback(msgId, 'down', e.target));
        acts.querySelector('.regen-btn').addEventListener('click', () => regenerate(msgId));
        acts.querySelector('.copy-btn').addEventListener('click', () => {
          navigator.clipboard?.writeText(bubble.innerText).then(() => {
            const btn = acts.querySelector('.copy-btn');
            btn.textContent = '✅ Copied'; setTimeout(() => { btn.textContent = '📋 Copy'; }, 1500);
          });
        });
      }
    }

    messages.scrollTop = messages.scrollHeight;
    renderMath(bubble);
    return row;
  }

  function appendSuggestions(chips) {
    const div = document.createElement('div');
    div.className = 'tc-suggestions';
    chips.forEach(({ label, prompt }) => {
      const btn = document.createElement('button');
      btn.className = 'tc-sug-chip';
      btn.textContent = label;
      btn.addEventListener('click', () => { div.remove(); sendPrompt(prompt); });
      div.appendChild(btn);
    });
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function defaultSuggestions() {
    return [
      { label: '🔁 Explain differently', prompt: 'Can you explain that again in a different way, maybe with a different example?' },
      { label: '📝 Similar practice question', prompt: 'Give me a similar practice question I can try myself, with the answer hidden at the end.' },
      { label: '🌍 Real-world example', prompt: 'Can you give me a real-world example that illustrates this concept?' },
    ];
  }

  function renderMath(el) {
    if (window.renderMathInElement) {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
          { left: '\\(', right: '\\)', display: false },
          { left: '\\[', right: '\\]', display: true }
        ],
        throwOnError: false
      });
    }
  }

  // ── Sending messages ───────────────────────────────────────────────────────
  function sendPrompt(text) { send(text, []); }

  async function send(text, images) {
    if (busy) return;
    if (!text.trim() && images.length === 0) return;
    busy = true;
    sendBtn.disabled = true;
    subjectSel.disabled = true; topicSel.disabled = true;
    if (paperSel) paperSel.disabled = true;
    session.locked = true;

    // User bubble
    let userHtml = '';
    images.forEach(img => { userHtml += `<img src="${img.dataUri}" alt="attached image">`; });
    if (text.trim()) userHtml += `<p>${esc(text).replace(/\n/g, '<br>')}</p>`;
    const userRow = renderBubble('user', userHtml);

    session.messages.push({ role: 'user', content: text || '(photo attached)', attachments: images.map(i => ({ type: 'image', url: i.dataUri })) });

    // Bot typing bubble
    const botId = crypto.randomUUID();
    const botRow = renderBubble('bot', '<div class="tc-typing"><span></span><span></span><span></span></div>', botId);
    const botBubble = botRow.querySelector('.tc-bubble');

    try {
      const history = session.messages.slice(0, -1).map(m => ({ role: m.role, content: m.content }));

      const body = {
        message: text || 'Please review my work.',
        syllabus: subjectSel.value || session.subject || null,
        topic: topicSel.value || session.topic || null,
        history,
        images: images.map(i => i.dataUri),
        session_id: session.id,
        summary: session.summary,
        mode: mode !== 'normal' ? mode : null
      };

      const resp = await fetch('/api/tutor/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail = err.detail || {};
        if (resp.status === 403 || resp.status === 429) {
          if (window.showUpgradeModal) {
            window.showUpgradeModal({
              minPlan: detail.min_plan || "solo",
              message: detail.message || "You've reached your free AI Tutor query limit for this month."
            });
          }
        }
        const errMsg = typeof detail === 'object' ? (detail.message || "Could not generate AI response") : (detail || `Server error ${resp.status}`);
        throw new Error(errMsg);
      }

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '', rawText = '';
      botBubble.innerHTML = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          const clean = line.trim();
          if (!clean.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(clean.slice(6));
            if (data.error) {
              throw new Error(data.error);
            }
            if (data.token) {
              rawText += data.token;
              botBubble.textContent = rawText;
              messages.scrollTop = messages.scrollHeight;
            } else if (data.done) {
              // Replace raw text with server-rendered HTML
              botBubble.innerHTML = data.html;
              renderMath(botBubble);

              session.id      = data.session_id;
              session.summary = data.summary;
              // Adopt the ids the server saved the messages under, so feedback,
              // regenerate and edit act on the saved conversation.
              const userMsg = session.messages[session.messages.length - 1];
              if (data.user_message_id && userMsg) {
                userMsg.id = data.user_message_id;
                if (userRow) userRow.dataset.msg = data.user_message_id;
              }
              const finalId = data.bot_message_id || botId;
              if (finalId !== botId) {
                botRow.remove();
                renderBubble('bot', data.html, finalId);
              }
              session.messages.push({ id: finalId, role: 'assistant', content: data.html, provider: data.provider });

              // Append suggestion chips
              appendSuggestions(defaultSuggestions());

              // Update sidebar
              if (currentUser) await loadSessions();

              // Update chat title if new session
              if (data.session_id && !session.title) {
                session.title = null; // will be set on next loadSessions
              }
            } else if (data.error) {
              throw new Error(data.error);
            }
          } catch (parseErr) {
            if (parseErr.message && parseErr.message !== 'Unexpected end of JSON input') {
              console.warn('SSE parse error:', parseErr);
            }
          }
        }
      }
    } catch (err) {
      botBubble.innerHTML = `<p class="err">⚠️ ${esc(err.message)}</p>`;
    } finally {
      busy = false;
      sendBtn.disabled = false;
      msgTA.focus();
    }
  }

  // ── Feedback / regenerate ─────────────────────────────────────────────────
  function submitFeedback(msgId, fb, btn) {
    if (!currentUser) return;
    fetch(`/api/tutor/messages/${msgId}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback: fb })
    }).then(r => {
      if (r.ok) {
        btn.closest('.tc-msg-acts').querySelectorAll('.tc-act-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      }
    }).catch(() => {});
  }

  /** Drop a message and everything after it - on screen, in memory and (signed
   *  in) in the saved conversation - so the next send carries on from there. */
  async function cutFrom(msgIndex) {
    const m = session.messages[msgIndex];
    if (!m) return;
    if (currentUser && session.id && m.id) {
      try { await apiFetch(`/api/tutor/sessions/${session.id}/messages/${m.id}`, 'DELETE'); } catch (_) { /* keep going */ }
    }
    session.messages = session.messages.slice(0, msgIndex);
    const row = m.id ? messages.querySelector(`.tc-msg[data-msg="${CSS.escape(m.id)}"]`) : null;
    if (row) { while (row.nextSibling) row.nextSibling.remove(); row.remove(); }
    messages.querySelectorAll('.tc-suggestions').forEach(el => el.remove());
  }

  async function regenerate(msgId) {
    if (busy) return;
    const idx = session.messages.findIndex(m => m.id === msgId);
    if (idx === -1) return;
    let u = idx - 1;
    while (u >= 0 && session.messages[u].role !== 'user') u--;
    if (u < 0) return;
    const prevUser = session.messages[u];
    await cutFrom(u);
    const imgs = (prevUser.attachments || []).map(a => ({ dataUri: a.url }));
    await send(prevUser.content, imgs);
  }

  /** ✏️ on your own message: edit it in place, then the conversation restarts from it. */
  function editMessage(row) {
    if (busy || row.querySelector('.tc-edit-box')) return;
    const idx = session.messages.findIndex(m => m.id && m.id === row.dataset.msg);
    if (idx === -1) { toastError('Wait for the reply to finish, then edit.'); return; }
    const m = session.messages[idx];
    const bubble = row.querySelector('.tc-bubble');
    const before = bubble.innerHTML;
    bubble.innerHTML = `<div class="tc-edit-box"><textarea rows="3"></textarea>
      <div class="tc-edit-acts"><button type="button" class="tc-act-btn" data-cancel>Cancel</button>
      <button type="button" class="tc-act-btn tc-edit-send" data-send>Send</button></div></div>`;
    const ta = bubble.querySelector('textarea');
    ta.value = m.content === '(photo attached)' ? '' : (m.content || '');
    ta.focus();
    bubble.querySelector('[data-cancel]').onclick = () => { bubble.innerHTML = before; renderMath(bubble); };
    const go = async () => {
      const text = ta.value.trim();
      const imgs = (m.attachments || []).map(a => ({ dataUri: a.url }));
      if (!text && !imgs.length) return;
      await cutFrom(idx);
      await send(text, imgs);
    };
    bubble.querySelector('[data-send]').onclick = go;
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); }
      if (e.key === 'Escape') bubble.querySelector('[data-cancel]').click();
    });
  }

  // ── Textarea auto-height ───────────────────────────────────────────────────
  function autosizeTA() {
    msgTA.style.height = 'auto';
    msgTA.style.height = Math.min(msgTA.scrollHeight, 160) + 'px';
  }

  // ── Chat title ─────────────────────────────────────────────────────────────
  function setChatTitle(main, sub) {
    chatTitleMain.textContent = main || 'AI Tutor';
    chatTitleSub.textContent  = sub || '';
  }

  // ── Deep-link (e.g. from past papers) ────────────────────────────────────
  function checkDeepLink() {
    const p = new URLSearchParams(location.search);
    if (p.get('tab') === 'solver') { location.replace('/solver'); return; }
    const syllabus = p.get('syllabus');
    const topic    = p.get('topic');
    const q        = p.get('q');   // prefilled question
    if (syllabus && subjectSel.querySelector(`option[value="${syllabus}"]`)) {
      subjectSel.value = syllabus;
      populateTopics(syllabus);
    }
    if (topic) topicSel.value = topic;
    if (q) {
      msgTA.value = decodeURIComponent(q);
      autosizeTA();
      msgTA.focus();
    }
  }

  // ── Utilities ──────────────────────────────────────────────────────────────
  function parseAttachments(raw) {
    if (!raw) return [];
    if (typeof raw === 'string') { try { return JSON.parse(raw); } catch { return []; } }
    return Array.isArray(raw) ? raw : [];
  }

  function toastError(msg) {
    const el = document.createElement('div');
    el.className = 'tc-msg bot';
    el.innerHTML = `<div class="tc-avatar owl">🦉</div><div class="tc-bubble-wrap" style="min-width:0"><div class="tc-bubble"><p class="err">⚠️ ${esc(msg)}</p></div></div>`;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function renderMath(elem) {
    if (!elem) return;
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(elem, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false },
            { left: "\\(", right: "\\)", display: false },
            { left: "\\[", right: "\\]", display: true }
          ],
          throwOnError: false
        });
      } catch (e) {
        console.warn("KaTeX render error:", e);
      }
    }
  }

  async function apiFetch(url, method = 'GET', body = null) {
    const opts = { method, headers: {} };
    if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(url, opts);
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.status); }
    return r.json();
  }

})();
