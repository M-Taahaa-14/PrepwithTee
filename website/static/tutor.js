/* AI Tutor — question generator / concept chat.
   Loads subjects+topics from /api/meta to ground the prompt, then talks to
   /api/ask. Keeps a short rolling history so follow-ups ("harder", "more like
   Q3") make sense. */
(function () {
  const chat = document.getElementById('chat');
  const empty = document.getElementById('empty');
  const bar = document.getElementById('bar');
  const msg = document.getElementById('msg');
  const send = document.getElementById('send');
  const subjectSel = document.getElementById('subject');
  const topicSel = document.getElementById('topic');

  let META = null;
  const history = [];          // [{role, content}] of plain text, for the model

  // ---- load subjects / topics --------------------------------------------
  fetch('/api/meta').then(r => r.json()).then(data => {
    META = data;
    (data.subjects || []).forEach(s => {
      const o = document.createElement('option');
      o.value = s.syllabus;
      o.textContent = `${s.subject} (${s.syllabus})`;
      subjectSel.appendChild(o);
    });
  }).catch(() => {/* the chat still works without grounding */});

  subjectSel.addEventListener('change', () => {
    topicSel.innerHTML = '<option value="">Any topic</option>';
    const s = (META?.subjects || []).find(x => x.syllabus === subjectSel.value);
    (s?.topics || []).forEach(t => {
      const o = document.createElement('option');
      o.value = t.name;
      o.textContent = `${t.name} (${t.count})`;
      topicSel.appendChild(o);
    });
  });

  // ---- rendering ----------------------------------------------------------
  function bubble(role, html) {
    if (empty) empty.remove();
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    const body = document.createElement('div');
    body.className = 'msg-body';
    body.innerHTML = html;
    wrap.appendChild(body);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return body;
  }
  const escapeHtml = s => s.replace(/[&<>]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

  // ---- send ---------------------------------------------------------------
  let busy = false;
  async function ask(text) {
    if (busy || !text.trim()) return;
    busy = true; send.disabled = true;
    bubble('me', '<p>' + escapeHtml(text).replace(/\n/g, '<br>') + '</p>');
    history.push({ role: 'user', content: text });

    const thinking = bubble('bot thinking',
      '<p class="dots"><span></span><span></span><span></span></p>');

    try {
      const r = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          syllabus: subjectSel.value || null,
          topic: topicSel.value || null,
          history: history.slice(0, -1).slice(-6),
        }),
      });
      const data = await r.json().catch(() => ({}));
      thinking.parentElement.remove();
      if (!r.ok) {
        bubble('bot', '<p class="err">' +
          escapeHtml(data.detail || 'Something went wrong. Try again in a moment.') +
          '</p>');
      } else {
        bubble('bot', data.html || '<p>No answer came back — try rephrasing.</p>');
        history.push({ role: 'assistant', content: (data.html || '').replace(/<[^>]+>/g, ' ').slice(0, 1500) });
      }
    } catch (e) {
      thinking.parentElement.remove();
      bubble('bot', '<p class="err">Could not reach the tutor. Check your connection and try again.</p>');
    } finally {
      busy = false; send.disabled = false;
      msg.focus();
    }
  }

  bar.addEventListener('submit', e => {
    e.preventDefault();
    const t = msg.value;
    msg.value = ''; autosize();
    ask(t);
  });

  // quick-prompt chips
  document.querySelectorAll('.chip').forEach(c =>
    c.addEventListener('click', () => {
      let p = c.dataset.prompt;
      if (!topicSel.value && /this topic/.test(p)) {
        // No topic chosen — make the prompt self-contained.
        p = p.replace(/on this topic/g, 'on a topic of your choice from my subject')
             .replace(/this topic/g, 'a key topic from my subject');
      }
      ask(p);
    }));

  // textarea autosize + Enter-to-send
  function autosize() {
    msg.style.height = 'auto';
    msg.style.height = Math.min(msg.scrollHeight, 160) + 'px';
  }
  msg.addEventListener('input', autosize);
  msg.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      bar.requestSubmit();
    }
  });
})();
