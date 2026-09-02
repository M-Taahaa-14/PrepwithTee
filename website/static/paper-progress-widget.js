/**
 * PaperProgressWidget — Reusable yearly paper score grid & grade calculator component.
 */
class PaperProgressWidget {
  constructor(container, options = {}) {
    this.container = typeof container === 'string' ? document.querySelector(container) : container;
    this.apiBase = options.apiBase || '/api';
    this.readOnly = options.readOnly || false;
    this.syllabus = options.syllabus || '0625';
    this.scores = [];
    this.thresholds = [];
    this.init();
  }

  async init() {
    if (!this.container) return;
    this.renderLoading();
    await Promise.all([this.loadScores(), this.loadThresholds()]);
    this.render();
  }

  async loadScores() {
    try {
      const res = await fetch(`${this.apiBase}/student-scores?syllabus=${encodeURIComponent(this.syllabus)}`, { credentials: 'same-origin' });
      if (res.ok) {
        const json = await res.json();
        this.scores = json.scores || [];
      }
    } catch (e) {
      this.scores = [];
    }
  }

  async loadThresholds() {
    try {
      const res = await fetch(`${this.apiBase}/grade-thresholds?syllabus=${encodeURIComponent(this.syllabus)}`, { credentials: 'same-origin' });
      if (res.ok) {
        const json = await res.json();
        this.thresholds = json.thresholds || [];
      }
    } catch (e) {
      this.thresholds = [];
    }
  }

  renderLoading() {
    this.container.innerHTML = `<div style="padding:20px;text-align:center;color:var(--grey,#666)">Loading paper scores grid…</div>`;
  }

  render() {
    let html = `
      <div class="pwt-paper-widget" style="background:#fff;border:1.5px solid var(--line,#e2e8f0);border-radius:14px;padding:20px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <h3 style="margin:0;font-family:'Archivo',sans-serif;font-size:1.05rem;color:var(--purple,#2E1B4A)">Yearly Paper Scores & Grades</h3>
          ${!this.readOnly ? '<button class="btn btn-sm btn-dark pwt-add-score-btn" type="button">+ Enter Score</button>' : ''}
        </div>
        <div style="overflow-x:auto">
          <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
            <thead>
              <tr style="background:var(--cream,#faf9f6);border-bottom:1.5px solid var(--line,#eee);text-align:left">
                <th style="padding:8px 10px">Year / Session</th>
                <th style="padding:8px 10px">Paper & Variant</th>
                <th style="padding:8px 10px">Raw Mark</th>
                <th style="padding:8px 10px">Grade</th>
                <th style="padding:8px 10px">Set By</th>
              </tr>
            </thead>
            <tbody>
    `;

    if (!this.scores.length) {
      html += `<tr><td colspan="5" style="padding:16px;text-align:center;color:var(--grey,#666)">No paper scores entered yet.</td></tr>`;
    } else {
      this.scores.forEach(s => {
        const sessName = s.session === 's' ? 'May/Jun' : s.session === 'w' ? 'Oct/Nov' : 'Feb/Mar';
        const gradeColor = s.component_grade === 'A*' || s.component_grade === 'A' ? '#1B8738' : s.component_grade === 'B' || s.component_grade === 'C' ? '#D97706' : '#DC2626';
        html += `
          <tr style="border-bottom:1px solid var(--line,#eee)">
            <td style="padding:10px;font-weight:600">${s.year} ${sessName}</td>
            <td style="padding:10px">Paper ${s.paper}${s.variant ? ' (v' + s.variant + ')' : ''}</td>
            <td style="padding:10px">${s.raw_mark} / ${s.max_mark}</td>
            <td style="padding:10px"><span style="background:var(--cream);color:${gradeColor};padding:2px 8px;border-radius:4px;font-weight:800">${s.component_grade || '—'}</span></td>
            <td style="padding:10px;font-size:0.75rem;color:var(--grey,#666)">${s.set_by || 'student'}</td>
          </tr>
        `;
      });
    }

    html += `
            </tbody>
          </table>
        </div>
      </div>
    `;

    this.container.innerHTML = html;
  }
}

if (typeof window !== 'undefined') {
  window.PaperProgressWidget = PaperProgressWidget;
}
