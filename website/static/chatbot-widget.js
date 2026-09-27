/* PrepWithTee Support Chatbot v20260830a — self-contained (CSS embedded) */
(function () {
  'use strict';
  if (document.getElementById('pwt-chatbot-fab')) return;

  // ── Embedded CSS ────────────────────────────────────────────────────────────
  const STYLE = `
/* Chatbot FAB */
.pwt-chatbot-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: linear-gradient(135deg, #2E1B4A 0%, #1a102e 100%);
  color: #fff;
  border: 2.5px solid #E8913A;
  box-shadow: 0 8px 28px rgba(46,27,74,0.45);
  cursor: pointer;
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.55rem;
  transition: transform 0.22s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.22s ease;
  outline: none;
}
.pwt-chatbot-fab:hover {
  transform: scale(1.1) translateY(-3px);
  box-shadow: 0 14px 40px rgba(46,27,74,0.55);
}
/* Pulse ring — draws attention on first load */
.pwt-chatbot-fab::before {
  content: '';
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  border: 2px solid rgba(232,145,58,0.5);
  animation: pwt-pulse 2.6s ease-out 1.2s 3;
  opacity: 0;
}
@keyframes pwt-pulse {
  0%   { transform: scale(1);   opacity: .8; }
  100% { transform: scale(1.5); opacity: 0; }
}
/* Unread badge */
.pwt-chatbot-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  background: #e53e3e;
  color: #fff;
  font-size: 0.62rem;
  font-weight: 700;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid #fff;
  animation: pwt-bounce-in .3s cubic-bezier(.34,1.56,.64,1);
}
@keyframes pwt-bounce-in {
  from { transform: scale(0); }
  to   { transform: scale(1); }
}

/* Tooltip */
.pwt-chatbot-fab-wrap {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9998;
}
.pwt-chatbot-fab-wrap .pwt-chatbot-fab {
  position: relative;
  bottom: auto;
  right: auto;
}
.pwt-chatbot-tooltip {
  position: absolute;
  right: 70px;
  bottom: 10px;
  white-space: nowrap;
  background: #1a1a2e;
  color: #fff;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 6px 12px;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,.25);
  pointer-events: none;
  opacity: 0;
  transform: translateX(6px);
  transition: opacity .2s, transform .2s;
}
.pwt-chatbot-tooltip::after {
  content: '';
  position: absolute;
  right: -6px;
  top: 50%;
  transform: translateY(-50%);
  border: 6px solid transparent;
  border-left-color: #1a1a2e;
  border-right-width: 0;
}
.pwt-chatbot-fab-wrap:hover .pwt-chatbot-tooltip {
  opacity: 1;
  transform: translateX(0);
}

/* Panel */
.pwt-chatbot-panel {
  position: fixed;
  bottom: 100px;
  right: 24px;
  width: min(400px, calc(100vw - 32px));
  height: 540px;
  background: #fff;
  border: 1.5px solid var(--line, #e2e8f0);
  border-radius: 20px;
  box-shadow: 0 24px 72px rgba(0,0,0,.22);
  z-index: 9999;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transform: translateY(28px) scale(0.93);
  transition: opacity .28s cubic-bezier(.16,1,.3,1), transform .28s cubic-bezier(.16,1,.3,1);
}
.pwt-chatbot-panel.active {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0) scale(1);
}

/* Header */
.pwt-chatbot-head {
  background: linear-gradient(135deg, #2E1B4A 0%, #1a102e 100%);
  color: #fff;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}
.pwt-chatbot-head-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.pwt-chatbot-head h4 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 7px;
  letter-spacing: -0.01em;
}
.pwt-chatbot-head-sub {
  font-size: 0.72rem;
  color: rgba(255,255,255,.7);
  display: flex;
  align-items: center;
  gap: 5px;
}
.pwt-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4caf50;
  display: inline-block;
  box-shadow: 0 0 0 2px rgba(76,175,80,.35);
}
.pwt-chatbot-head-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}
.pwt-chatbot-head-btn {
  background: rgba(255,255,255,.12);
  border: none;
  color: rgba(255,255,255,.85);
  font-size: 0.9rem;
  cursor: pointer;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  transition: background .18s;
}
.pwt-chatbot-head-btn:hover { background: rgba(255,255,255,.22); color: #fff; }

/* Messages */
.pwt-chatbot-body {
  flex: 1;
  padding: 14px 14px 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--page, #faf9f6);
  scrollbar-width: thin;
  scrollbar-color: rgba(160,160,190,.3) transparent;
}
.pwt-chatbot-body::-webkit-scrollbar { width: 4px; }
.pwt-chatbot-body::-webkit-scrollbar-track { background: transparent; }
.pwt-chatbot-body::-webkit-scrollbar-thumb { background: rgba(160,160,190,.3); border-radius: 99px; }

.pwt-cb-msg {
  max-width: 90%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 0.87rem;
  line-height: 1.55;
  word-break: break-word;
}
.pwt-cb-msg.bot {
  background: #fff;
  border: 1.5px solid #e2e8f0;
  color: #1a1a2e;
  align-self: flex-start;
  border-bottom-left-radius: 4px;
  box-shadow: 0 2px 8px rgba(0,0,0,.04);
}
.pwt-cb-msg.user {
  background: #2E1B4A;
  color: #fff;
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}
.pwt-cb-msg a {
  color: #E8913A;
  text-decoration: underline;
  word-break: break-all;
}
.pwt-cb-msg strong { font-weight: 700; }
.pwt-cb-msg ul { margin: 6px 0 0; padding-left: 16px; }
.pwt-cb-msg ul li { margin-bottom: 3px; }

/* Nav link chips inside bot messages */
.pwt-cb-nav-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.pwt-cb-nav-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  background: #f0ebff;
  border: 1.5px solid #d5c9f5;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 700;
  color: #2E1B4A;
  cursor: pointer;
  text-decoration: none !important;
  transition: background .18s, border-color .18s;
}
.pwt-cb-nav-link:hover {
  background: #2E1B4A;
  border-color: #2E1B4A;
  color: #fff !important;
}

/* Typing dots */
.pwt-typing-dots {
  display: flex;
  gap: 5px;
  padding: 4px 2px;
  align-items: center;
}
.pwt-typing-dots span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #aaa;
  animation: pwt-dot-bounce 1.2s infinite ease-in-out;
}
.pwt-typing-dots span:nth-child(2) { animation-delay: .2s; }
.pwt-typing-dots span:nth-child(3) { animation-delay: .4s; }
@keyframes pwt-dot-bounce {
  0%, 80%, 100% { transform: translateY(0);   opacity: .5; }
  40%            { transform: translateY(-6px); opacity: 1; }
}

/* Suggestion chips */
.pwt-chatbot-chips {
  padding: 8px 12px;
  display: flex;
  gap: 7px;
  overflow-x: auto;
  background: #fff;
  border-top: 1px solid #eee;
  flex-shrink: 0;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.pwt-chatbot-chips::-webkit-scrollbar { display: none; }

.pwt-cb-chip {
  flex: none;
  background: #f5f0fb;
  border: 1.5px solid #ddd5f5;
  border-radius: 20px;
  padding: 5px 13px;
  font-size: 0.77rem;
  font-weight: 600;
  color: #2E1B4A;
  cursor: pointer;
  white-space: nowrap;
  transition: all .18s ease;
}
.pwt-cb-chip:hover {
  background: #2E1B4A;
  border-color: #2E1B4A;
  color: #fff;
  transform: translateY(-1px);
}

/* Footer / input */
.pwt-chatbot-foot {
  padding: 10px 14px 12px;
  background: #fff;
  border-top: 1px solid #eee;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.pwt-chatbot-input {
  flex: 1;
  padding: 9px 15px;
  border: 1.5px solid #ccc;
  border-radius: 24px;
  font-size: 0.87rem;
  font-family: inherit;
  outline: none;
  background: #fff;
  color: #1a1a2e;
  transition: border-color .18s;
}
.pwt-chatbot-input:focus { border-color: #2E1B4A; }
.pwt-chatbot-send {
  background: #E8913A;
  color: #fff;
  border: none;
  border-radius: 50%;
  width: 38px;
  height: 38px;
  cursor: pointer;
  display: grid;
  place-items: center;
  flex: none;
  font-size: 1.05rem;
  transition: transform .18s, background .18s;
}
.pwt-chatbot-send:hover { transform: scale(1.08); background: #d6812d; }
.pwt-chatbot-send:disabled { opacity: .5; cursor: not-allowed; transform: none; }

/* Escalation strip */
.pwt-cb-escalate {
  margin-top: 10px;
  padding: 9px 12px;
  background: #fff8f0;
  border: 1.5px solid #f5d9b5;
  border-radius: 10px;
  font-size: 0.78rem;
  color: #7a4a10;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.pwt-cb-escalate a {
  font-weight: 700;
  color: #E8913A !important;
  text-decoration: none !important;
}
.pwt-cb-escalate a:hover { text-decoration: underline !important; }

/* Dark mode */
html[data-theme="dark"] .pwt-chatbot-panel { background: #222838; border-color: #3b435a; }
html[data-theme="dark"] .pwt-chatbot-body { background: #0a0a16; }
html[data-theme="dark"] .pwt-cb-msg.bot { background: #1a1936; border-color: #3b435a; color: #e8e8ff; }
html[data-theme="dark"] .pwt-chatbot-chips,
html[data-theme="dark"] .pwt-chatbot-foot { background: #222838; border-color: #3b435a; }
html[data-theme="dark"] .pwt-cb-chip { background: #1e1b38; border-color: #38326a; color: #ddd; }
html[data-theme="dark"] .pwt-chatbot-input { background: #181730; border-color: #343c4c; color: #fff; }
html[data-theme="dark"] .pwt-chatbot-tooltip { background: #2E1B4A; }
html[data-theme="dark"] .pwt-cb-nav-link { background: #1e1b38; border-color: #38326a; color: #c9bfff; }
html[data-theme="dark"] .pwt-cb-escalate { background: #1e1208; border-color: #5a3a10; color: #f5c070; }

/* Nudge note FAB up so it doesn't overlap */
#global-note-fab { bottom: 92px !important; }
`;

  const styleEl = document.createElement('style');
  styleEl.id = 'pwt-chatbot-styles';
  styleEl.textContent = STYLE;
  document.head.appendChild(styleEl);

  // ── HTML ────────────────────────────────────────────────────────────────────
  const WRAP_HTML = `
<div class="pwt-chatbot-fab-wrap" id="pwt-chatbot-wrap">
  <div class="pwt-chatbot-tooltip">Need help? Ask me!</div>
  <button class="pwt-chatbot-fab" id="pwt-chatbot-fab" title="PrepWithTee Support" type="button" aria-label="Open support chat">
    🦉
  </button>
</div>

<div class="pwt-chatbot-panel" id="pwt-chatbot-panel" role="dialog" aria-label="PrepWithTee Support">
  <div class="pwt-chatbot-head">
    <div class="pwt-chatbot-head-info">
      <h4><span>🦉</span> PrepWithTee Support</h4>
      <div class="pwt-chatbot-head-sub">
        <span class="pwt-status-dot"></span> Typically replies in seconds
      </div>
    </div>
    <div class="pwt-chatbot-head-actions">
      <button class="pwt-chatbot-head-btn" id="pwt-cb-clear" title="Clear chat" type="button" aria-label="Clear chat">↺</button>
      <button class="pwt-chatbot-head-btn" id="pwt-chatbot-close" type="button" aria-label="Close chat">✕</button>
    </div>
  </div>

  <div class="pwt-chatbot-body" id="pwt-chatbot-body" aria-live="polite"></div>

  <div class="pwt-chatbot-chips" id="pwt-chatbot-chips">
    <button class="pwt-cb-chip" data-msg="What subjects do you cover?">📚 Subjects</button>
    <button class="pwt-cb-chip" data-msg="What are the pricing plans?">💳 Pricing</button>
    <button class="pwt-cb-chip" data-msg="How does the AI Tutor work?">🤖 AI Tutor</button>
    <button class="pwt-cb-chip" data-msg="What resources are available?">📁 Resources</button>
    <button class="pwt-cb-chip" data-msg="Tell me about notes and flashcards">📒 Notes</button>
    <button class="pwt-cb-chip" data-msg="How do I contact Tee?">📞 Contact</button>
  </div>

  <div class="pwt-chatbot-foot">
    <input type="text" class="pwt-chatbot-input" id="pwt-cb-input"
      placeholder="Ask me anything…" autocomplete="off" maxlength="500">
    <button type="button" class="pwt-chatbot-send" id="pwt-cb-send" aria-label="Send">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
    </button>
  </div>
</div>`;

  const container = document.createElement('div');
  container.innerHTML = WRAP_HTML;
  document.body.appendChild(container);

  // ── Elements ────────────────────────────────────────────────────────────────
  const fab      = document.getElementById('pwt-chatbot-fab');
  const panel    = document.getElementById('pwt-chatbot-panel');
  const closeBtn = document.getElementById('pwt-chatbot-close');
  const clearBtn = document.getElementById('pwt-cb-clear');
  const body     = document.getElementById('pwt-chatbot-body');
  const input    = document.getElementById('pwt-cb-input');
  const sendBtn  = document.getElementById('pwt-cb-send');

  let history = [];
  let unread  = 0;
  let panelOpen = false;

  // ── Local FAQ (no API call) ─────────────────────────────────────────────────
  const FAQ = [
    {
      keys: ['subject', 'offer', 'syllabus', 'course', 'level', 'physics', 'maths', 'math', 'chemistry', 'computer science', 'what do you cover', 'what subjects', 'available'],
      answer: '**Subjects we cover:**\n- Physics: O Level (5054) & IGCSE (0625)\n- Mathematics D: O Level (4024) & IGCSE (0580)\n- Computer Science: O Level (2210) & IGCSE (0478)\n- Chemistry: O Level (5070) & IGCSE (0620)\n- A Level: Maths (9709), Physics (9702), CS (9618)\n\nAll Cambridge syllabus, 2020–2025 papers.',
      links: [{ label: '📚 Browse Subjects', href: 'subjects.html' }]
    },
    {
      keys: ['price', 'pricing', 'cost', 'plan', 'subscription', 'how much', 'pkr', 'pay', 'fee', 'monthly', 'free plan', 'upgrade'],
      answer: '**Our plans:**\n- **Free** — monthly capped access to topicals\n- **Solo Subject** — PKR 1,000/month (1 syllabus)\n- **3 Subjects** — PKR 2,000/month\n- **All Subjects + AI Tutor** — PKR 3,000/month\n- **1-on-1 Tutoring** — PKR 20,000/month\n\nPayment via JazzCash, EasyPaisa, or Bank Transfer.',
      links: [{ label: '💳 See Pricing', href: 'pricing.html' }]
    },
    {
      keys: ['ai tutor', 'tutor', 'explain', 'step by step', 'solve question', 'ask question', 'how does the ai'],
      answer: '**AI Tutor** gives you step-by-step explanations for past paper questions. Pick any question from the topical library and tap "Explain" — it breaks down the working, key formulas, and marking tips in plain language.',
      links: [{ label: '🤖 Try AI Tutor', href: 'tutor.html' }]
    },
    {
      keys: ['resource', 'formula', 'definition', 'periodic table', 'calculator', 'command word', 'tools'],
      answer: '**Free study tools include:**\n- Formula sheets (Physics, Maths, CS)\n- Definitions glossary\n- Periodic table\n- Scientific calculator\n- Command words guide (Cambridge marking)\n- Graph tools & pseudocode editor',
      links: [{ label: '📁 Open Resources', href: '/resources' }, { label: '🔧 Tools Hub', href: 'tools.html' }]
    },
    {
      keys: ['note', 'flashcard', 'revision card', 'study card', 'fc'],
      answer: '**Notes & Flashcards** let you save key points while studying. You can add notes to any question or topic, create colour-coded sticky notes, and build flashcard decks for spaced-repetition revision.',
      links: [{ label: '📒 My Notes', href: 'notes.html' }, { label: '🗂️ Flashcards', href: 'flashcards.html' }]
    },
    {
      keys: ['dashboard', 'progress', 'analytics', 'achievement', 'streak', 'performance', 'stats'],
      answer: '**Your Dashboard** shows your progress across every topic — questions attempted, marks scored, weak areas, and streaks. Access achievements, yearly progress charts, and personalised study recommendations.',
      links: [{ label: '📊 Dashboard', href: 'dashboard.html' }]
    },
    {
      keys: ['study plan', 'schedule', 'how to study', 'revision plan', 'preparation'],
      answer: '**Study Hub** provides guided revision plans tailored to your exam date. It tracks which topics you\'ve covered and prioritises weak areas automatically.',
      links: [{ label: '📅 Study Hub', href: 'study-hub.html' }]
    },
    {
      keys: ['contact', 'whatsapp', 'reach', 'tee', 'message', 'phone', 'email', 'speak', 'human', 'person', 'help'],
      answer: '**Reach Tee directly:**\n- WhatsApp: +92 320 488 4375\n- Or use the contact form on the Contact page\n\nTee typically replies within a few hours.',
      links: [{ label: '📞 Contact Page', href: 'contact.html' }, { label: '💬 WhatsApp Tee', href: 'https://wa.me/923204884375?text=Hi%20Tee!%20I%20have%20a%20question.', external: true }],
      escalate: true
    },
    {
      keys: ['sign up', 'signup', 'register', 'create account', 'login', 'log in', 'join', 'enroll', 'start'],
      answer: 'You can **sign up for free** — no credit card needed. The Free plan gives you capped monthly access to topicals and all tools. Upgrade any time for unlimited access.',
      links: [{ label: '✨ Sign Up Free', href: 'login.html' }]
    },
    {
      keys: ['past paper', 'topical', 'paper', 'question', 'library', 'mark scheme', 'ms'],
      answer: '**5,000+ past paper questions** organised by topic, with official mark schemes. Filter by year, session, paper variant and topic to build your own topical practice set.',
      links: [{ label: '📄 Papers Library', href: '/yearly' }]
    },
    {
      keys: ['mcq', 'multiple choice', 'mock test', 'test', 'quiz', 'practice exam'],
      answer: 'Use the **Quiz** feature to attempt topical MCQs with instant feedback, or generate a full **mock test** from the papers library filtered by topic and year range.',
      links: [{ label: '🎯 Start a Quiz', href: 'quiz.html' }, { label: '📝 Papers', href: '/papers' }]
    },
    {
      keys: ['tutoring', '1-on-1', 'one on one', 'private tutor', 'book', 'demo', 'lesson', 'teacher'],
      answer: '**1-on-1 Tutoring** with Tee (Cambridge-trained) covers all O Level & A Level subjects. PKR 20,000/month. Book a **free 30-minute demo** to try before committing.',
      links: [{ label: '🎓 Teachers Page', href: 'teachers.html' }]
    },
    {
      keys: ['payment', 'jazzcash', 'easypaisa', 'bank transfer', 'how to pay', 'pay online'],
      answer: 'We accept **JazzCash, EasyPaisa, and Bank Transfer** for all subscription plans. After subscribing, your account is upgraded within 24 hours. Contact Tee on WhatsApp for payment confirmation.',
      links: [{ label: '💳 Pricing', href: 'pricing.html' }, { label: '💬 WhatsApp', href: 'https://wa.me/923204884375', external: true }]
    },
  ];

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function matchFAQ(text) {
    const low = text.toLowerCase();
    let best = null, bestScore = 0;
    for (const entry of FAQ) {
      let score = 0;
      for (const k of entry.keys) {
        if (low.includes(k)) score += k.length; // longer matches score higher
      }
      if (score > bestScore) { bestScore = score; best = entry; }
    }
    return bestScore >= 4 ? best : null; // minimum match quality
  }

  function mdToHtml(text) {
    if (!text) return '';
    let html = text
      // escape HTML first
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      // bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // bullet lines: "- text" or "• text"
      .replace(/^[-•] (.+)$/gm, '<li>$1</li>')
      // auto-link URLs
      .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
      // line breaks
      .replace(/\n/g, '<br>');

    // wrap consecutive <li> in <ul>
    html = html.replace(/(<li>.*?<\/li>)(<br>(<li>.*?<\/li>))*/gs, match => {
      const items = match.replace(/<br>/g, '');
      return '<ul>' + items + '</ul>';
    });

    return html;
  }

  function buildNavLinks(links) {
    if (!links || !links.length) return '';
    const items = links.map(l => {
      const href = l.external ? l.href : l.href;
      const target = l.external ? ' target="_blank" rel="noopener"' : '';
      return `<a class="pwt-cb-nav-link" href="${href}"${target}>${l.label}</a>`;
    });
    return `<div class="pwt-cb-nav-links">${items.join('')}</div>`;
  }

  function buildEscalate() {
    return `<div class="pwt-cb-escalate">
      🙋 Need more help? <a href="contact.html">Contact page</a> or
      <a href="https://wa.me/923204884375?text=Hi%20Tee!" target="_blank" rel="noopener">WhatsApp Tee</a> directly.
    </div>`;
  }

  function appendMsg(role, htmlContent, navLinks, showEscalate) {
    const id = 'cb-' + Math.random().toString(36).slice(2, 9);
    const div = document.createElement('div');
    div.id = id;
    div.className = `pwt-cb-msg ${role}`;
    div.innerHTML = htmlContent;
    if (navLinks) div.innerHTML += buildNavLinks(navLinks);
    if (showEscalate) div.innerHTML += buildEscalate();
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return id;
  }

  function showTyping() {
    const id = 'cb-' + Math.random().toString(36).slice(2, 9);
    const div = document.createElement('div');
    div.id = id;
    div.className = 'pwt-cb-msg bot';
    div.innerHTML = '<div class="pwt-typing-dots"><span></span><span></span><span></span></div>';
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return id;
  }

  function bumpUnread() {
    if (panelOpen) return;
    unread++;
    let badge = document.getElementById('pwt-cb-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'pwt-cb-badge';
      badge.className = 'pwt-chatbot-badge';
      fab.appendChild(badge);
    }
    badge.textContent = unread > 9 ? '9+' : unread;
  }

  function clearUnread() {
    unread = 0;
    const badge = document.getElementById('pwt-cb-badge');
    if (badge) badge.remove();
  }

  // ── Welcome message ─────────────────────────────────────────────────────────
  function showWelcome() {
    appendMsg('bot',
      'Hi! 👋 I\'m the <strong>PrepWithTee</strong> support bot. I can help with subjects, pricing, resources, and features. What would you like to know?',
      null, false);
  }
  showWelcome();

  // ── Open / close ─────────────────────────────────────────────────────────────
  function openPanel() {
    panelOpen = true;
    panel.classList.add('active');
    clearUnread();
    setTimeout(() => input.focus(), 280);
  }

  function closePanel() {
    panelOpen = false;
    panel.classList.remove('active');
  }

  function clearChat() {
    body.innerHTML = '';
    history = [];
    showWelcome();
  }

  fab.addEventListener('click', () => panelOpen ? closePanel() : openPanel());
  closeBtn.addEventListener('click', closePanel);
  clearBtn.addEventListener('click', clearChat);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && panelOpen) closePanel();
  });

  // ── Chips ────────────────────────────────────────────────────────────────────
  document.querySelectorAll('.pwt-cb-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const msg = btn.dataset.msg;
      if (msg) handleSend(msg);
    });
  });

  // ── Send ─────────────────────────────────────────────────────────────────────
  sendBtn.addEventListener('click', () => {
    const msg = input.value.trim();
    if (msg) { input.value = ''; handleSend(msg); }
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const msg = input.value.trim();
      if (msg) { input.value = ''; handleSend(msg); }
    }
  });

  async function handleSend(text) {
    if (!panelOpen) openPanel();
    appendMsg('user', mdToHtml(text));
    history.push({ role: 'user', content: text });
    sendBtn.disabled = true;

    // Check local FAQ first
    const faq = matchFAQ(text);
    if (faq) {
      await delay(350); // brief pause so it feels natural
      appendMsg('bot', mdToHtml(faq.answer), faq.links, faq.escalate);
      history.push({ role: 'assistant', content: faq.answer });
      sendBtn.disabled = false;
      bumpUnread();
      return;
    }

    // Detect escalation keywords
    const LOW = text.toLowerCase();
    const wantsHuman = /urgent|complaint|problem|not working|broken|bug|issue|wrong|refund|cancel|escalat|speak to|talk to|real person/.test(LOW);

    const typingId = showTyping();

    try {
      const res = await fetch('/api/chatbot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: history.slice(-8) })
      });

      const data = await res.json();

      if (res.status === 429) {
        document.getElementById(typingId).innerHTML =
          mdToHtml("You've reached the message limit for now. " +
          "Please [contact Tee on WhatsApp](https://wa.me/923204884375?text=Hi+Tee!) for further help.") +
          buildNavLinks([{ label: '💬 WhatsApp Tee', href: 'https://wa.me/923204884375', external: true },
                         { label: '📞 Contact', href: 'contact.html' }]);
        sendBtn.disabled = false;
        return;
      }

      const reply = data.reply || "I couldn't process that right now. Please message Tee on WhatsApp!";

      // Extract any nav suggestions the model returned (we also show escalation if needed)
      document.getElementById(typingId).innerHTML =
        mdToHtml(reply) + (wantsHuman ? buildEscalate() : '');

      history.push({ role: 'assistant', content: reply });

    } catch (_) {
      document.getElementById(typingId).innerHTML =
        'Connection error — please try again or ' +
        '<a href="https://wa.me/923204884375" target="_blank" rel="noopener">message Tee on WhatsApp</a>.';
    }

    sendBtn.disabled = false;
    body.scrollTop = body.scrollHeight;
    bumpUnread();
  }

  function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

})();
