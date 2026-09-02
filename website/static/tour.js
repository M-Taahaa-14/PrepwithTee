/**
 * PrepWithTee per-page product tour — Driver.js v1.x
 * Detects the current page, shows a floating 🦉 Tour button that
 * launches page-specific guided steps. Steps are silently skipped
 * if the element is not present in the DOM (handles UI changes safely).
 *
 * Dashboard tour is handled separately by tour-dashboard.js (more detail).
 * All other pages are covered here.
 */
(function () {
  'use strict';

  /* ── Step sets per page ─────────────────────────────────────────────── */
  var PAGE_TOURS = {

    /* ── Topical Past Papers ── */
    'papers': {
      key: 'pwtour_seen_papers',
      steps: [
        {
          element: '#paper-toggle',
          popover: {
            title: '📑 Two tools in one',
            description: 'Switch between the <strong>Topical Builder</strong> (your chosen chapters as a PDF) and the <strong>Yearly Library</strong> (full papers by year and session).',
            side: 'bottom', align: 'center',
          },
        },
        {
          element: '#subjects',
          popover: {
            title: '1 · Pick your syllabus',
            description: 'Select the Cambridge qualification you\'re sitting — Physics, Maths, Computer Science, O Level or IGCSE. Both O Level and IGCSE are supported.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#topics',
          popover: {
            title: '2 · Choose topics',
            description: 'Tick the exact chapters you want to practise. Use the search box to find a topic fast, or hit \'select all\' to build a full-subject booklet.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#yfrom',
          popover: {
            title: '3 · Set a year range',
            description: 'Start with recent years (2022–2025) for the most current examiner style. Widen the range for more practice volume.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '[data-mode="test"]',
          popover: {
            title: '🎯 Topic Test mode',
            description: 'Picks a <strong>random subset</strong> of questions to a mark target — like a real timed test. The mark scheme is produced as a <em>separate file</em> so you can sit it blind.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#inc-ms',
          popover: {
            title: '📋 Mark scheme toggle',
            description: 'Keep ticked for learning (mark scheme right after each question). Untick only when sitting the booklet as a test — then check the separate MS file.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#go',
          popover: {
            title: '✅ Generate your PDF',
            description: 'Hit Generate and your topical booklet builds in seconds — original Cambridge vector crops, diagrams and answer lines untouched. Download and print it.',
            side: 'top', align: 'center',
          },
        },
      ],
    },

    /* ── AI Tutor ── */
    'tutor': {
      key: 'pwtour_seen_tutor',
      steps: [
        {
          element: '#tutor-app',
          popover: {
            title: '🤖 Meet Tee, your AI tutor',
            description: 'Ask anything about your Cambridge syllabus — concept explanations, worked problems, past-paper questions, exam technique. Tee knows every topic.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#tutor-left',
          popover: {
            title: '🔧 Context sidebar',
            description: 'Set your subject and topic here so Tee gives focused, syllabus-specific answers. Your past sessions are saved and searchable in this sidebar.',
            side: 'right', align: 'start',
          },
        },
        {
          element: '#tc-subject',
          popover: {
            title: '📚 Subject filter',
            description: 'Pick your subject first. Without it Tee answers generically — with it, every response is scoped to your exact Cambridge syllabus and its mark scheme.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#tc-mode-normal',
          popover: {
            title: '🎓 Three tutor modes',
            description: '<strong>Normal</strong> — clear explanations. <strong>Socratic</strong> — Tee guides with questions instead of handing you the answer. <strong>Exam</strong> — concise, mark-scheme style responses.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.tc-starter-chips',
          popover: {
            title: '⚡ Quick-start prompts',
            description: 'Tap any chip to instantly get practice questions, a concept explained step by step, a quiz, or a list of common exam mistakes on any topic.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#tc-msg',
          popover: {
            title: '💬 Ask your question',
            description: 'Type anything — a concept you\'re confused about, a past-paper question word for word, or "explain step by step". Hit Enter or click Send.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#tc-attach-btn',
          popover: {
            title: '📷 Photo attachment',
            description: 'Snap a photo of a printed question or your working and send it. Tee reads diagrams, graphs and handwritten workings.',
            side: 'top', align: 'start',
          },
        },
      ],
    },

    /* ── Topical Progress Tracker ── */
    'topical-progress': {
      key: 'pwtour_seen_topical_progress',
      steps: [
        {
          element: '.revise-page',
          popover: {
            title: '📖 Progress Tracker',
            description: 'Every chapter of your syllabus in one place. Pick a subject, see all its chapters, and self-mark your confidence — the dashboard rings update automatically.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#revise-subjects',
          popover: {
            title: '1 · Choose your subject',
            description: 'Your enrolled subjects appear as tabs here. Pick one to see all its chapters and where you currently stand on each.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.progress-cross-links',
          popover: {
            title: '🔗 Progress tools',
            description: 'Jump between Topical Progress (chapter-by-chapter), Yearly Progress (full-paper scores) and the Grade Calculator from this navigation bar.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#topic-list',
          popover: {
            title: '📋 Your chapter list',
            description: 'Each chapter shows your confidence — <em>Not started</em>, <em>Learning</em>, or <em>Confident</em>. Tap any chapter to open questions on it, update your status, or run a short Cambridge-style quiz.',
            side: 'right', align: 'start',
          },
        },
      ],
    },

    /* ── Yearly Progress ── */
    'yearly-progress': {
      key: 'pwtour_seen_yearly_progress',
      steps: [
        {
          element: '.revise-page',
          popover: {
            title: '📊 Yearly Progress',
            description: 'Track your scores on complete past papers, session by session. See exactly how your grade is trending over time.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#revise-subjects',
          popover: {
            title: '1 · Choose your subject',
            description: 'Pick a subject to see all available past papers listed by year and session (May/Jun, Oct/Nov, Feb/Mar).',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.progress-cross-links',
          popover: {
            title: '🔗 Progress tools',
            description: 'Switch between Topical Progress, Yearly Progress, Grade Calculator and Grade Trends from here.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#paper-list',
          popover: {
            title: '📄 Paper records',
            description: 'Tick off each paper you\'ve completed, enter your raw mark, and the grade boundary prediction is instant. The trend chart at the top shows your trajectory.',
            side: 'right', align: 'start',
          },
        },
      ],
    },

    /* ── Your Profile ── */
    'profile': {
      key: 'pwtour_seen_profile',
      steps: [
        {
          element: '.profile-sidebar',
          popover: {
            title: '👤 Your profile card',
            description: 'Name, grade level, photo, and a quick summary of today\'s formula reviews and subjects enrolled. The grade level determines which subjects and papers appear across the whole site.',
            side: 'right', align: 'start',
          },
        },
        {
          element: '.profile-avatar-wrap',
          popover: {
            title: '📷 Photo & grade badge',
            description: 'Click the camera icon to update your profile photo. The grade badge (e.g. O Level) is what filters syllabuses site-wide — change it in the form below if needed.',
            side: 'right', align: 'start',
          },
        },
        {
          element: '.enrolled-grid',
          popover: {
            title: '📚 Enrolled subjects',
            description: 'These are the subjects you\'re actively tracking. Each subject unlocks its chapter progress tracker, topical past-paper builder, AI quiz and MCQ practice.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#pf-form',
          popover: {
            title: '✏️ Personal details',
            description: 'Update your display name, qualification, school and exam year here. Your exam year personalises the countdown timer on the dashboard.',
            side: 'top', align: 'start',
          },
        },
      ],
    },

    /* ── Flashcards & Study Library ── */
    'flashcards': {
      key: 'pwtour_seen_flashcards',
      steps: [
        {
          element: '.sl-filters',
          popover: {
            title: '🗂️ Flashcard library',
            description: 'Browse thousands of Cambridge-aligned flashcards. Filter by subject and chapter using the dropdowns, or type a term in the search box.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.sl-type-row',
          popover: {
            title: '📂 Card types',
            description: 'Filter by type: <strong>Definitions</strong>, <strong>Formulae</strong>, <strong>Lists</strong> (key lists and examples), or <strong>Key Facts</strong>. Mix types for a full-topic session.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#fc-grid',
          popover: {
            title: '🃏 Browse the cards',
            description: 'Click any card to flip it and reveal the answer. Star (★) a card to add it to your spaced-repetition review queue for daily practice.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#continue-strip',
          popover: {
            title: '▶ Quick-resume strip',
            description: '<strong>Continue Studying</strong> picks up your last session instantly. <strong>Review Cards</strong> runs your spaced-repetition queue, prioritising cards due today.',
            side: 'bottom', align: 'start',
          },
        },
      ],
    },

    /* ── MCQ Live Session ── */
    'mcq-solver': {
      key: 'pwtour_seen_mcq_solver',
      steps: [
        {
          element: '#setup-panel',
          popover: {
            title: '⚡ MCQ Live Session',
            description: 'Real Cambridge multiple-choice questions one at a time, with a countdown timer. Green/red feedback immediately after each answer, and a score breakdown at the end.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#mcq-subjects',
          popover: {
            title: '1 · Choose a subject',
            description: 'Pick your Cambridge syllabus. MCQ sessions are available for subjects that have a Paper 1 multiple-choice component.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#mcq-mode-seg',
          popover: {
            title: '2 · Topic or full paper',
            description: '<strong>By Topic</strong> drills one chapter. <strong>Full Past Paper</strong> runs an entire MCQ paper in the original order — use this when you\'re near-exam-ready.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#mcq-topics',
          popover: {
            title: '3 · Choose topics',
            description: 'Select the chapter(s) you want to drill. The question count updates live so you know how many are available before you start.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '#mcq-count-pills',
          popover: {
            title: '4 · Question count',
            description: 'Pick 10, 20, 30, 40 or All. Start with 10 for a quick focused drill; go full for a proper timed session.',
            side: 'top', align: 'start',
          },
        },
      ],
    },

    /* ── Notes & Resources ── */
    'resources': {
      key: 'pwtour_seen_resources',
      steps: [
        {
          element: '.hero-slim',
          popover: {
            title: '📚 Notes & Resources',
            description: 'Everything built from the official Cambridge syllabus — chapter notes, formula sheets, revision videos and the official syllabus PDF. All free for every student.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#res-grid',
          popover: {
            title: '📖 Resource library',
            description: 'Browse by subject and category. Click a card to expand and see what\'s inside — notes, revision sheets and past-paper guides are all organised by chapter.',
            side: 'bottom', align: 'start',
          },
        },
      ],
    },

    /* ── Study Hub ── */
    'study-hub': {
      key: 'pwtour_seen_study_hub',
      steps: [
        {
          element: '.sh-hero',
          popover: {
            title: '📚 Study Hub',
            description: 'All your learning materials in one place — flashcards, study notes, formula sheets and key facts. Live stats show your progress across each tool at a glance.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.sh-grid',
          popover: {
            title: '🗂️ Learning tools',
            description: 'Each card shows live stats for that tool — cards due today, mastered count, notes available. Click any card to open that tool or jump to a specific action.',
            side: 'top', align: 'start',
          },
        },
        {
          element: '.sh-flashcards',
          popover: {
            title: '⚡ Flashcards at a glance',
            description: 'See how many cards are due for review today, how many you\'ve mastered and how many are still learning — without leaving the hub. Hit Study now to go straight in.',
            side: 'right', align: 'start',
          },
        },
      ],
    },

    /* ── Analytics ── */
    'analytics': {
      key: 'pwtour_seen_analytics',
      steps: [
        {
          element: '.an-hero',
          popover: {
            title: '📊 Study Analytics',
            description: 'A full view of your study time, topical mastery, yearly paper scores and streak data — everything in one place to see what\'s working and what needs attention.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '#an-subject-picker',
          popover: {
            title: '🔍 Filter by subject',
            description: 'Click any subject card to filter all charts and stats to that syllabus. "All Subjects" shows your complete cross-subject study picture.',
            side: 'bottom', align: 'start',
          },
        },
        {
          element: '.an-stats-row',
          popover: {
            title: '📈 Key stats',
            description: 'Streak, total XP, flashcards mastered and days studied. These update in real time as you study each day.',
            side: 'top', align: 'start',
          },
        },
      ],
    },

  };

  /* ── Detect current page ─────────────────────────────────────────────── */
  function detectPage() {
    var path = window.location.pathname;
    var file = path.split('/').pop().replace('.html', '') || 'index';
    return PAGE_TOURS[file] || null;
  }

  /* ── Helpers ─────────────────────────────────────────────────────────── */
  function markSeen(key) { try { localStorage.setItem(key, '1'); } catch(e) {} }

  function filterSteps(steps) {
    return steps.filter(function(s) {
      if (!s.element) return true;
      try { return !!document.querySelector(s.element); } catch(e) { return false; }
    });
  }

  function ensureFab(launchFn) {
    var existing = document.getElementById('tour-fab');
    if (existing) { existing.onclick = launchFn; return; }
    var btn = document.createElement('button');
    btn.id = 'tour-fab';
    btn.setAttribute('aria-label', 'Take the page tour');
    btn.textContent = '🦉 Tour';
    btn.addEventListener('click', launchFn);
    document.body.appendChild(btn);
  }

  function launch(tourDef) {
    if (typeof window.driver === 'undefined') return;
    var steps = filterSteps(tourDef.steps);
    if (!steps.length) { markSeen(tourDef.key); return; }

    var driverObj = window.driver.js.driver({
      showProgress: true,
      animate: true,
      overlayColor: 'rgba(15,20,40,0.6)',
      popoverClass: 'pwtee-tour',
      nextBtnText: 'Next →',
      prevBtnText: '← Back',
      doneBtnText: 'Done ✓',
      closeBtnText: 'Skip tour',
      showButtons: ['next', 'previous', 'close'],
      onDestroyed: function () {
        markSeen(tourDef.key);
        ensureFab(function() { launch(tourDef); });
      },
      steps: steps,
    });
    driverObj.drive();
  }

  function init() {
    var tourDef = detectPage();
    if (!tourDef) return;
    var launchFn = function() { launch(tourDef); };
    ensureFab(launchFn);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
