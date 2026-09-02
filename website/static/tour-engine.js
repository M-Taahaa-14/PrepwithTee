/* tour-engine.js — ES module for Driver.js-powered page tours.
 * Exported by this file; consumed by tour-dashboard.js and other
 * page-specific tour modules that need proper ES module imports.
 */

const LS_PRE = 'pwtour_seen_';

function _key(label) {
  return LS_PRE + label.toLowerCase().replace(/\s+/g, '_');
}
function _markSeen(label) {
  try { localStorage.setItem(_key(label), '1'); } catch {}
}
function _isSeen(label) {
  try { return !!localStorage.getItem(_key(label)); } catch { return false; }
}

function _filterSteps(steps) {
  return steps.filter(s => {
    if (!s.element) return true;
    try { return !!document.querySelector(s.element); } catch { return false; }
  });
}

function _toDriverSteps(steps) {
  return steps.map(s => ({
    element: s.element || null,
    popover: {
      title: s.title || '',
      description: s.body || '',
      side: (s.position && s.position !== 'auto') ? s.position : 'auto',
      align: 'start',
    },
  }));
}

function _ensureFab(launchFn) {
  const existing = document.getElementById('tour-fab');
  if (existing) { existing.onclick = launchFn; return; }
  const btn = document.createElement('button');
  btn.id = 'tour-fab';
  btn.setAttribute('aria-label', 'Take the page tour');
  btn.textContent = '🦉 Tour';
  btn.addEventListener('click', launchFn);
  document.body.appendChild(btn);
}

/**
 * startTour(steps, opts)
 * Immediately launch a Driver.js tour.
 * opts: { label, onComplete, onSkip }
 */
export function startTour(steps, opts = {}) {
  if (typeof window.driver === 'undefined') return;
  const filtered = _filterSteps(steps);
  if (!filtered.length) return;

  const label = opts.label || 'page';
  const driverSteps = _toDriverSteps(filtered);

  const d = window.driver.js.driver({
    showProgress: true,
    animate: true,
    overlayColor: 'rgba(15,20,40,0.6)',
    popoverClass: 'pwtee-tour',
    nextBtnText: 'Next →',
    prevBtnText: '← Back',
    doneBtnText: 'Done ✓',
    closeBtnText: 'Skip tour',
    showButtons: ['next', 'previous', 'close'],
    onDestroyed: () => {
      _markSeen(label);
      opts.onComplete?.();
    },
    steps: driverSteps,
  });
  d.drive();
}

/**
 * autoStartTour(steps, opts)
 * Always shows the FAB button for re-launching the tour.
 * Auto-starts only on first visit (localStorage flag not set).
 * opts: { label, onComplete, onSkip }
 */
export function autoStartTour(steps, opts = {}) {
  const label = opts.label || 'page';
  const launchFn = () => startTour(steps, opts);

  const run = () => {
    _ensureFab(launchFn);
    if (!_isSeen(label)) launchFn();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run);
  } else {
    run();
  }
}
