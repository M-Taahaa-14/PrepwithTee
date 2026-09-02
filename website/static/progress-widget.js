/**
 * ProgressWidget — Standardized topical progress component for PrepWithTee.
 * Supports Student (self-reported), Teacher, and Admin views with inline status editing.
 */
class ProgressWidget {
  constructor(container, options = {}) {
    this.container = typeof container === 'string' ? document.querySelector(container) : container;
    this.apiBase = options.apiBase || '/api';
    this.readOnly = options.readOnly || false;
    this.syllabus = options.syllabus || '5054';
    this.onUpdate = options.onUpdate || null;
    this.data = [];
    this.init();
  }

  async init() {
    if (!this.container) return;
    this.renderLoading();
    await this.loadData();
    this.render();
  }

  async loadData() {
    try {
      const url = `${this.apiBase}/progress?syllabus=${encodeURIComponent(this.syllabus)}`;
      const res = await fetch(url, { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Failed to load progress data');
      const json = await res.json();
      this.data = json.progress || json.data || [];
    } catch (err) {
      console.error('[ProgressWidget]', err);
      this.data = [];
    }
  }

  renderLoading() {
    this.container.innerHTML = `
      <div style="padding:24px;text-align:center;color:var(--grey,#666)">
        <span style="font-size:1.4rem;display:block;margin-bottom:8px">⌛</span>
        Loading progress tracking data…
      </div>
    `;
  }

  render() {
    if (!this.data || !this.data.length) {
      this.container.innerHTML = `
        <div style="padding:24px;text-align:center;color:var(--grey,#666);background:var(--cream,#faf9f6);border:1.5px solid var(--line,#eee);border-radius:12px">
          <p style="margin:0 0 6px 0;font-weight:600">No progress data recorded yet for syllabus ${this.syllabus}.</p>
          <span style="font-size:0.85rem">Status updates will appear here once study sessions start.</span>
        </div>
      `;
      return;
    }

    const confidentCount = this.data.filter(d => d.status === 'confident').length;
    const pct = Math.round((confidentCount / this.data.length) * 100);

    let html = `
      <div class="pwt-progress-widget" style="background:#fff;border:1.5px solid var(--line,#e2e8f0);border-radius:14px;padding:20px;box-shadow:0 4px 16px rgba(0,0,0,0.03)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--line,#eee)">
          <div>
            <h3 style="margin:0;font-family:'Archivo',sans-serif;font-size:1.05rem;color:var(--purple,#2E1B4A)">Topical Progress Overview</h3>
            <span style="font-size:0.8rem;color:var(--grey,#666)">${confidentCount} of ${this.data.length} topics marked Confident</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:48px;height:48px;border-radius:50%;background:conic-gradient(#E8913A ${pct}%, #e2e8f0 0);display:grid;place-items:center">
              <div style="width:38px;height:38px;border-radius:50%;background:#fff;display:grid;place-items:center;font-size:0.75rem;font-weight:800;color:var(--ink,#1a1a2e)">${pct}%</div>
            </div>
          </div>
        </div>

        <div style="max-height:420px;overflow-y:auto;margin:0 -4px;padding:0 4px">
          <table style="width:100%;border-collapse:collapse;font-size:0.86rem">
            <thead>
              <tr style="text-align:left;border-bottom:1.5px solid var(--line,#eee);color:var(--grey,#666)">
                <th style="padding:8px 6px">Topic</th>
                <th style="padding:8px 6px">Theory Status</th>
                <th style="padding:8px 6px">Past Papers</th>
                ${!this.readOnly ? '<th style="padding:8px 6px;text-align:right">Action</th>' : ''}
              </tr>
            </thead>
            <tbody>
    `;

    this.data.forEach((row, idx) => {
      const statusBadge = this.getStatusBadge(row.status);
      const papersBadge = this.getStatusBadge(row.papers_status || 'not_started');

      html += `
        <tr style="border-bottom:1px solid var(--line,#f4f0ea)">
          <td style="padding:10px 6px;font-weight:600;color:var(--ink,#1a1a2e)">
            ${row.topic}${row.subtopic ? ` <span style="font-weight:400;color:var(--grey,#666)">· ${row.subtopic}</span>` : ''}
          </td>
          <td style="padding:10px 6px">${statusBadge}</td>
          <td style="padding:10px 6px">${papersBadge}</td>
          ${!this.readOnly ? `
            <td style="padding:10px 6px;text-align:right">
              <select class="pwt-status-sel" data-idx="${idx}" style="padding:4px 8px;border-radius:6px;border:1px solid var(--line,#ccc);font-size:0.78rem">
                <option value="not_started" ${row.status === 'not_started' ? 'selected' : ''}>Not Started</option>
                <option value="learning" ${row.status === 'learning' ? 'selected' : ''}>Learning</option>
                <option value="confident" ${row.status === 'confident' ? 'selected' : ''}>Confident</option>
              </select>
            </td>
          ` : ''}
        </tr>
      `;
    });

    html += `
            </tbody>
          </table>
        </div>
      </div>
    `;

    this.container.innerHTML = html;
    this.wireEvents();
  }

  getStatusBadge(status) {
    const map = {
      confident: '<span style="background:#EBF7EE;color:#1B8738;padding:3px 8px;border-radius:6px;font-size:0.75rem;font-weight:700">✓ Confident</span>',
      learning: '<span style="background:#FEF3E6;color:#D97706;padding:3px 8px;border-radius:6px;font-size:0.75rem;font-weight:700">⏳ Learning</span>',
      not_started: '<span style="background:#F1F5F9;color:#64748B;padding:3px 8px;border-radius:6px;font-size:0.75rem;font-weight:600">• Not Started</span>',
    };
    return map[status] || map.not_started;
  }

  wireEvents() {
    if (this.readOnly) return;
    const selects = this.container.querySelectorAll('.pwt-status-sel');
    selects.forEach(sel => {
      sel.addEventListener('change', async (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        const row = this.data[idx];
        if (!row) return;

        const newStatus = e.target.value;
        row.status = newStatus;

        try {
          await fetch(`${this.apiBase}/progress`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
              syllabus: this.syllabus,
              topic: row.topic,
              subtopic: row.subtopic || null,
              status: newStatus,
            })
          });
          this.render();
          if (this.onUpdate) this.onUpdate(row);
        } catch (err) {
          console.error('[ProgressWidget update failed]', err);
        }
      });
    });
  }
}

if (typeof window !== 'undefined') {
  window.ProgressWidget = ProgressWidget;
}
