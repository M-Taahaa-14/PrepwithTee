/* Resources / notes. Loads categories from /api/resources, shows a filterable
   card grid, and on click opens a folder-browser detail view with breadcrumbs
   and an inline file viewer. Hash-routed (#/<slug>) for linkability.

   Two modes:
     browse  — full-width responsive grid of folder cards + file rows
     file-open — .file-open on .res-viewer triggers split: 300px list | viewer
*/
(function () {
  const grid       = document.getElementById('res-grid');
  const filters    = document.getElementById('res-filters');
  const detail     = document.getElementById('res-detail');
  const back       = document.getElementById('res-back');
  const dTitle     = document.getElementById('res-detail-title');
  const fullscreen = document.getElementById('res-fullscreen');
  const fileList   = document.getElementById('res-files');
  const pane       = document.getElementById('res-pane');
  const breadcrumb = document.getElementById('res-breadcrumb');
  const viewer     = document.querySelector('.res-viewer');

  const TINTS = ['blue', 'green', 'orange', 'lav', 'pink', 'teal', 'yellow'];
  const EXT_ICON = { pdf: '📕', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', webp: '🖼️',
    docx: '📘', pptx: '📙', xlsx: '📗', zip: '🗜️', txt: '📄' };
  let CATS = [];
  let board = 'All';

  let navStack   = [];
  let currentCat = null;

  const fmtSize = b => b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB'
    : Math.max(1, Math.round(b / 1024)) + ' KB';

  grid.innerHTML = '<div class="res-loading"><span class="res-spin">⏳</span>Loading resources…</div>';

  fetch('/api/resources').then(r => r.json()).then(data => {
    CATS = data.categories || [];
    injectSearch();
    renderGrid();
    route();
  }).catch(() => {
    grid.innerHTML = '<div class="res-loading">Resources couldn\'t be loaded right now.</div>';
  });

  // ---- search ---------------------------------------------------------------
  function injectSearch() {
    const wrap = document.createElement('div');
    wrap.className = 'res-search-wrap';
    wrap.innerHTML = `
      <div class="res-search-inner">
        <svg class="res-search-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="22" y2="22"/>
        </svg>
        <input type="search" id="resSearch" class="res-search" placeholder="Search topics, chapters, or file names…" autocomplete="off" spellcheck="false">
      </div>
      <div class="res-search-hints">
        <span class="res-hint-label">Try:</span>
        <button class="res-hint-chip" data-q="waves">Waves</button>
        <button class="res-hint-chip" data-q="kinematics">Kinematics</button>
        <button class="res-hint-chip" data-q="organic chemistry">Organic Chemistry</button>
        <button class="res-hint-chip" data-q="logarithm">Logarithms</button>
        <button class="res-hint-chip" data-q="algorithm">Algorithms</button>
        <button class="res-hint-chip" data-q="electricity">Electricity</button>
      </div>`;
    grid.parentNode.insertBefore(wrap, grid);
    const inp = document.getElementById('resSearch');
    let t;
    inp.addEventListener('input', e => {
      clearTimeout(t);
      t = setTimeout(() => {
        const q = e.target.value.trim().toLowerCase();
        if (q.length >= 2) {
          if (currentCat) {
            // inside a category — scope to it, stay in detail pane
            renderScopedSearch(q);
          } else {
            // on home screen — search all categories
            detail.hidden = true;
            grid.hidden = false;
            renderSearchResults(q);
          }
        } else {
          // cleared — restore current view
          if (currentCat) renderDir();
          else route();
        }
      }, 220);
    });
    wrap.querySelectorAll('.res-hint-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        inp.value = btn.dataset.q;
        inp.dispatchEvent(new Event('input'));
        inp.focus();
      });
    });
  }

  function _fileMatches(node, q) {
    if (!node) return false;
    if (node.type === 'file') return (node.title || '').toLowerCase().includes(q);
    // also match folder names
    if ((node.name || '').toLowerCase().includes(q)) return true;
    return (node.children || []).some(c => _fileMatches(c, q));
  }

  function _collectFiles(node, q, out, pathParts) {
    if (!node) return;
    if (node.type === 'file') {
      if ((node.title || '').toLowerCase().includes(q)) out.push({ file: node, path: pathParts });
    } else {
      const folderNameMatches = (node.name || '').toLowerCase().includes(q);
      (node.children || []).forEach(c => {
        const childPath = c.name ? [...pathParts, c.name] : pathParts;
        if (folderNameMatches && c.type === 'file') {
          // parent folder name matched — include all files in it
          out.push({ file: c, path: childPath });
        } else {
          _collectFiles(c, q, out, childPath);
        }
      });
    }
  }

  function renderSearchResults(q) {
    const matching = CATS.filter(c =>
      c.name.toLowerCase().includes(q) ||
      (c.description || '').toLowerCase().includes(q) ||
      _fileMatches(c.tree, q));

    grid.innerHTML = '';

    if (!matching.length) {
      grid.innerHTML = `<div class="res-empty"><span>🔍</span><b>No results for "${esc(q)}"</b>
        <p>Try a topic keyword or chapter name.</p></div>`;
      return;
    }

    matching.forEach(cat => {
      const files = [];
      _collectFiles(cat.tree, q, files, []);

      const section = document.createElement('div');
      section.className = 'res-search-result';

      const head = document.createElement('a');
      head.className = 'res-search-cat-head';
      head.href = '#/' + encodeURIComponent(cat.slug);
      head.innerHTML = `
        <span class="res-icon" style="font-size:1.3rem">${cat.icon || '📚'}</span>
        <span class="res-search-cat-name">${esc(cat.name)}</span>
        ${cat.board ? `<span class="res-badge">${esc(cat.board)}</span>` : ''}
        <span class="res-open" style="margin-left:auto">Open →</span>`;
      section.appendChild(head);

      if (files.length) {
        const ul = document.createElement('ul');
        ul.className = 'res-search-files';
        files.slice(0, 10).forEach(({ file, path }) => {
          const a = document.createElement('a');
          a.className = 'res-file';
          a.href = '/api/resources/file?rel=' + encodeURIComponent(file.rel);
          a.target = '_blank';
          a.rel = 'noopener';
          a.innerHTML = `<span class="fi">${EXT_ICON[file.ext] || '📄'}</span>
            <span class="fn">${esc(file.title)}</span>
            ${path.length > 1 ? `<span class="fm res-search-path">${esc(path.slice(1).join(' › '))}</span>` : ''}`;
          ul.appendChild(a);
        });
        if (files.length > 10) {
          const more = document.createElement('li');
          more.className = 'res-search-more';
          more.textContent = `+${files.length - 10} more — open to see all`;
          ul.appendChild(more);
        }
        section.appendChild(ul);
      }

      grid.appendChild(section);
    });
  }

  // ---- card grid ----------------------------------------------------------
  function renderGrid() {
    const shown = CATS.filter(c => board === 'All' || c.board === board);
    if (!shown.length) {
      grid.innerHTML = `<div class="res-empty">
        <span>📚</span><b>Nothing here yet</b>
        <p>Resources for this board will appear as they're added.</p></div>`;
      return;
    }
    grid.innerHTML = '';

    const grouped = {};
    shown.forEach(c => {
      const b = c.board || 'Other';
      if (!grouped[b]) grouped[b] = [];
      grouped[b].push(c);
    });

    if (!grouped['All boards']) grouped['All boards'] = [];
    grouped['All boards'].unshift({
      isRoadmap: true,
      name: 'Revision Study Guide',
      description: 'A complete step-by-step revision roadmap for Cambridge exams. Learn how to structure your prep using our past papers and study tools.',
      icon: '🗺️',
      board: 'All boards',
      tint: 'lav'
    });

    const order = ['All boards', 'O Level', 'IGCSE', 'A Level'];
    const sortedBoards = Object.keys(grouped).sort((x, y) => {
      const ix = order.indexOf(x), iy = order.indexOf(y);
      if (ix !== -1 && iy !== -1) return ix - iy;
      if (ix !== -1) return -1;
      if (iy !== -1) return 1;
      return x.localeCompare(y);
    });

    let globalCardIdx = 0;
    sortedBoards.forEach(bName => {
      const catsInBoard = grouped[bName];
      const section = document.createElement('div');
      section.className = 'board-section';

      const head = document.createElement('div');
      head.className = 'board-head';

      let subtext = '';
      if      (bName === 'O Level')    subtext = "O Level chapter revision notes, formula sheets, and resources.";
      else if (bName === 'IGCSE')      subtext = "IGCSE chapter revision notes, formula sheets, and resources.";
      else if (bName === 'A Level')    subtext = "A Level chapter revision notes, formula sheets, and resources.";
      else if (bName === 'All boards') subtext = "Official Cambridge syllabuses for O Level, IGCSE and A Level.";
      else                             subtext = `Revision resources for ${bName}.`;

      head.innerHTML = `
        <div class="board-head-left">
          <h2>${esc(bName === 'All boards' ? 'Official Syllabuses' : bName)}</h2>
          <p>${esc(subtext)}</p>
        </div>
        <div class="scroll-controls">
          <button class="scroll-btn prev" aria-label="Scroll left">‹</button>
          <button class="scroll-btn next" aria-label="Scroll right">›</button>
        </div>`;

      const row = document.createElement('div');
      row.className = 'subject-grid';

      catsInBoard.forEach(c => {
        const tint = c.isRoadmap ? 'lav' : TINTS[globalCardIdx % TINTS.length];
        globalCardIdx++;
        const a = document.createElement('a');
        a.className = 'res-card tint-' + tint;
        a.href = c.isRoadmap ? 'guide.html' : '#/' + encodeURIComponent(c.slug);

        const countText = c.isRoadmap ? 'Syllabus Roadmap' : `${c.count} file${c.count !== 1 ? 's' : ''}`;
        a.innerHTML = `
          <div class="res-card-top">
            <span class="res-icon">${c.icon || '📚'}</span>
            <span class="res-count">${countText}</span>
          </div>
          <h3>${esc(c.name)}</h3>
          <p>${esc(c.description || '')}</p>
          <div class="res-card-foot">
            ${c.subject ? `<span class="res-badge">${esc(c.subject)}</span>` : ''}
            <span class="res-open">Open →</span>
          </div>`;
        row.appendChild(a);
      });

      section.appendChild(head);
      section.appendChild(row);
      grid.appendChild(section);

      const prevBtn = head.querySelector('.scroll-btn.prev');
      const nextBtn = head.querySelector('.scroll-btn.next');
      prevBtn.addEventListener('click', () => row.scrollBy({ left: -320, behavior: 'smooth' }));
      nextBtn.addEventListener('click', () => row.scrollBy({ left:  320, behavior: 'smooth' }));
      const updateButtons = () => {
        const hasScroll = row.scrollWidth > row.clientWidth;
        prevBtn.style.display = nextBtn.style.display = hasScroll ? '' : 'none';
        if (hasScroll) {
          prevBtn.disabled = row.scrollLeft <= 0;
          nextBtn.disabled = row.scrollLeft + row.clientWidth >= row.scrollWidth - 1;
        }
      };
      row.addEventListener('scroll', updateButtons);
      window.addEventListener('resize', updateButtons);
      setTimeout(updateButtons, 50);
    });
  }

  // ---- folder-browser detail view ----------------------------------------

  function setBrowseMode() {
    viewer?.classList.remove('file-open');
    if (fullscreen) { fullscreen.href = '#'; fullscreen.style.display = 'none'; }
    pane.innerHTML = `<div class="res-pane-empty">
      <span>📄</span><b>Pick a file to read it here</b>
      <p>PDFs and images open inline; other formats download.</p></div>`;
  }

  function openCat(cat) {
    currentCat = cat;
    navStack   = [cat.tree];
    dTitle.textContent = cat.board ? `${cat.name} — ${cat.board}` : cat.name;
    setBrowseMode();
    grid.hidden = true;
    if (filters) filters.hidden = true;
    const tools = document.getElementById('tools');
    if (tools) tools.style.display = 'none';
    detail.hidden = false;
    renderDir();
    window.scrollTo({ top: detail.offsetTop - 80, behavior: 'smooth' });
  }

  function renderBreadcrumb() {
    if (!breadcrumb) return;
    breadcrumb.innerHTML = '';

    // ← Back button — visible when we're inside a subfolder
    if (navStack.length > 1) {
      const btn = document.createElement('button');
      btn.className = 'bc-back';
      const parentName = navStack.length === 2
        ? (currentCat ? currentCat.name : navStack[0].name)
        : navStack[navStack.length - 2].name;
      btn.textContent = '← ' + parentName;
      btn.addEventListener('click', () => { navStack.pop(); renderDir(); });
      breadcrumb.appendChild(btn);
    }

    // Path segments (clickable except the last)
    navStack.forEach((node, i) => {
      const isCurrent = (i === navStack.length - 1);
      if (i > 0) {
        const sep = document.createElement('span');
        sep.className = 'bc-sep';
        sep.textContent = ' › ';
        breadcrumb.appendChild(sep);
      }
      const seg = document.createElement('span');
      seg.className = 'bc-seg' + (isCurrent ? ' bc-cur' : '');
      seg.textContent = (i === 0 && currentCat) ? currentCat.name : node.name;
      if (!isCurrent) {
        seg.addEventListener('click', () => {
          navStack = navStack.slice(0, i + 1);
          renderDir();
        });
      }
      breadcrumb.appendChild(seg);
    });
  }

  function renderDir() {
    setBrowseMode();        // reset to browse mode when navigating into a folder
    renderBreadcrumb();
    fileList.innerHTML = '';

    const dir = navStack[navStack.length - 1];
    if (!dir || !dir.children) return;

    dir.children.forEach(node => {
      const li = document.createElement('li');
      if (node.type === 'dir') {
        const nFiles = (node.children || []).filter(c => c.type === 'file').length;
        const nDirs  = (node.children || []).filter(c => c.type === 'dir').length;
        const parts  = [];
        if (nDirs)  parts.push(`${nDirs} folder${nDirs  > 1 ? 's' : ''}`);
        if (nFiles) parts.push(`${nFiles} file${nFiles > 1 ? 's' : ''}`);
        li.className = 'res-folder';
        li.innerHTML = `<span class="fi">📁</span>
          <span class="fn">${esc(node.name)}</span>
          ${parts.length ? `<span class="fc">${parts.join(' · ')}</span>` : ''}`;
        li.addEventListener('click', () => { navStack.push(node); renderDir(); });
      } else {
        const fileUrl = '/api/resources/file?rel=' + encodeURIComponent(node.rel);
        li.className = 'res-file';
        li.innerHTML = `<span class="fi">${EXT_ICON[node.ext] || '📄'}</span>
          <span class="fn">${esc(node.title)}</span>
          <span class="fm">${node.ext.toUpperCase()} · ${fmtSize(node.size)}</span>
          <a class="res-newtab" href="${fileUrl}" target="_blank" rel="noopener" title="Open in new tab">↗</a>`;
        li.addEventListener('click', e => {
          if (e.target.closest('.res-newtab')) return;
          openFile(node, li);
        });
      }
      fileList.appendChild(li);
    });
  }

  function renderScopedSearch(q) {
    setBrowseMode();
    // show a simple "Searching…" breadcrumb
    if (breadcrumb) {
      breadcrumb.innerHTML = '';
      const seg = document.createElement('span');
      seg.className = 'bc-seg bc-cur';
      seg.textContent = `Search: "${q}"`;
      breadcrumb.appendChild(seg);
    }
    fileList.innerHTML = '';

    const files = [];
    _collectFiles(currentCat.tree, q, files, [currentCat.name]);

    if (!files.length) {
      const li = document.createElement('li');
      li.className = 'res-empty';
      li.innerHTML = `<span>🔍</span><b>No results for "${esc(q)}"</b><p>Try a different keyword.</p>`;
      fileList.appendChild(li);
      return;
    }

    files.forEach(({ file, path }) => {
      const li = document.createElement('li');
      const fileUrl = '/api/resources/file?rel=' + encodeURIComponent(file.rel);
      li.className = 'res-file';
      li.innerHTML = `<span class="fi">${EXT_ICON[file.ext] || '📄'}</span>
        <span class="fn">${esc(file.title)}</span>
        ${path.length > 1 ? `<span class="fm res-search-path">${esc(path.slice(1).join(' › '))}</span>` : ''}
        <a class="res-newtab" href="${fileUrl}" target="_blank" rel="noopener" title="Open in new tab">↗</a>`;
      li.addEventListener('click', e => {
        if (e.target.closest('.res-newtab')) return;
        openFile(file, li);
      });
      fileList.appendChild(li);
    });
  }

  function openFile(f, li) {
    // Switch to file-open (split) mode
    viewer?.classList.add('file-open');
    fileList.querySelectorAll('.res-file').forEach(x => x.classList.remove('active'));
    if (li) li.classList.add('active');
    const url = '/api/resources/file?rel=' + encodeURIComponent(f.rel);
    if (fullscreen) { fullscreen.href = url; fullscreen.style.display = ''; }
    if (f.ext === 'pdf') {
      const isMobile = window.matchMedia('(max-width: 768px)').matches;
      if (isMobile) {
        pane.innerHTML = `<div class="res-pane-empty" style="padding:40px 24px;">
          <span>📄</span>
          <b style="margin-bottom:8px;">${esc(f.title)}</b>
          <p style="margin-bottom:20px;">PDF previews work best on desktop.<br>Tap below to open in your phone's viewer.</p>
          <a class="btn btn-dark" href="${url}" target="_blank" rel="noopener">Open PDF ↗</a>
        </div>`;
      } else {
        pane.innerHTML = `<iframe class="res-frame" src="${url}#toolbar=1"
          title="${esc(f.title)}"></iframe>`;
      }
    } else if (['png', 'jpg', 'jpeg', 'webp'].includes(f.ext)) {
      pane.innerHTML = `<div class="res-img-wrap"><img src="${url}" alt="${esc(f.title)}"></div>`;
    } else {
      pane.innerHTML = `<div class="res-pane-empty">
        <span>⬇️</span><b>${esc(f.title)}</b>
        <p>${f.ext.toUpperCase()} · ${fmtSize(f.size)} — downloads rather than previewing.</p>
        <a class="btn btn-dark" href="${url}" download>Download file</a></div>`;
    }
  }

  function closeCat() {
    navStack   = [];
    currentCat = null;
    if (breadcrumb) breadcrumb.innerHTML = '';
    viewer?.classList.remove('file-open');
    detail.hidden = true;
    grid.hidden   = false;
    if (filters) filters.hidden =
      [...new Set(CATS.map(c => c.board).filter(Boolean))].length < 2;
    const tools = document.getElementById('tools');
    if (tools) tools.style.display = '';
  }

  back.addEventListener('click', () => { location.hash = ''; });

  const darkBtn = document.getElementById('res-dark-btn');
  if (darkBtn && pane) {
    darkBtn.addEventListener('click', () => {
      const isDark = pane.classList.toggle('res-dark-active');
      darkBtn.innerHTML = isDark ? '☀️ Light Mode' : '🌙 Night Mode';
    });
  }

  function route() {
    const m = location.hash.match(/^#\/(.+)$/);
    if (!m) { closeCat(); return; }
    const cat = CATS.find(c => c.slug === decodeURIComponent(m[1]));
    if (cat) openCat(cat); else closeCat();
  }
  window.addEventListener('hashchange', route);

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
})();
