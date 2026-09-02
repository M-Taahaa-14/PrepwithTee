/**
 * note-context.js — Shared location capture and resolver for context-aware notes.
 *
 * captureContext(overrides)   → location_json object describing where the note was created.
 * resolveLocation(locationJson) → URL string to navigate back to the source.
 *
 * Import this as a module on any page that opens the note composer.
 * notes.js imports it too so the "Jump to source" button works.
 */

// ── Location → URL resolver ───────────────────────────────────────────────────

/**
 * Given a stored location_json object, return the URL to navigate to.
 * Returns null if the location cannot be resolved.
 */
export function resolveLocation(loc) {
  if (!loc || !loc.type) return null;

  switch (loc.type) {
    case 'question':
      // papers.html?key=5054_s23_22&q=17
      if (!loc.paperKey) return null;
      return 'papers.html?key=' + encodeURIComponent(loc.paperKey)
           + (loc.questionNumber != null ? '&q=' + loc.questionNumber : '');

    case 'flashcard':
      // flashcards.html?block=4821
      if (!loc.blockId) return null;
      return 'flashcards.html?block=' + loc.blockId;

    case 'chapter':
      // topical-progress.html?syllabus=5054&topic=Electric+circuits
      if (!loc.syllabus || !loc.topic) return null;
      return 'topical-progress.html?syllabus=' + encodeURIComponent(loc.syllabus)
           + '&topic=' + encodeURIComponent(loc.topic);

    case 'tutor_message':
      return loc.messageId
        ? 'tutor.html?msg=' + encodeURIComponent(loc.messageId)
        : 'tutor.html';

    case 'video':
      if (!loc.resourceId) return null;
      return 'video.html?id=' + encodeURIComponent(loc.resourceId)
           + (loc.timestamp != null ? '&t=' + loc.timestamp : '');

    default:
      return null;
  }
}

// ── Current-page context capture ──────────────────────────────────────────────

/**
 * Inspect the current page URL and any supplied overrides, and return a
 * location_json object.  Callers that know their exact context (e.g. a
 * per-question "Add Note" button) should pass the full overrides object;
 * this function just fills in what it can from the URL automatically.
 */
export function captureContext(overrides = {}) {
  const page = location.pathname.split('/').pop() || '';
  const params = new URLSearchParams(location.search);
  let auto = {};

  if (page === 'papers.html' || page === 'revise.html') {
    const key = params.get('key');
    const q   = params.get('q');
    if (key) auto = { type: 'question', paperKey: key,
                      questionNumber: q != null ? parseInt(q, 10) : null };

  } else if (page === 'flashcards.html') {
    const block = params.get('block');
    if (block) auto = { type: 'flashcard', blockId: parseInt(block, 10) };

  } else if (page === 'topical-progress.html' || page === 'revise.html') {
    const syllabus = params.get('syllabus');
    const topic    = params.get('topic');
    if (syllabus && topic)
      auto = { type: 'chapter', syllabus, topic, scrollY: window.scrollY };

  } else if (page === 'tutor.html' || page === 'ask.html') {
    auto = { type: 'tutor_message', messageId: params.get('msg') || null };
  }

  // Caller overrides take precedence over auto-detected values
  const merged = { ...auto, ...overrides };
  return Object.keys(merged).length ? merged : null;
}

// ── Human-readable source label ───────────────────────────────────────────────

/** Build a short breadcrumb string from a location_json object. */
export function locationLabel(loc) {
  if (!loc) return null;
  switch (loc.type) {
    case 'question':
      return loc.paperKey
        ? loc.paperKey + (loc.questionNumber != null ? ' · Q' + loc.questionNumber : '')
        : null;
    case 'flashcard':  return 'Flashcard';
    case 'chapter':
      return loc.topic || null;
    case 'tutor_message': return 'AI Tutor conversation';
    case 'video':
      return loc.timestamp != null ? 'Video · ' + _fmtTime(loc.timestamp) : 'Video';
    default: return null;
  }
}

function _fmtTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m + ':' + String(s).padStart(2, '0');
}
