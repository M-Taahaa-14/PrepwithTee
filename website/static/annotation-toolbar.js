/**
 * annotation-toolbar.js — Ephemeral screen annotation tools.
 * Pen · Highlighter · Laser pointer · Eraser — no save, for live teaching.
 * Toggle:  Alt+A  or click the floating pen button (bottom-right).
 * Undo:    Ctrl+Z while active.
 * Exit:    Esc or toggle button again.
 */
(function () {
  'use strict';
  if (window.self !== window.top) return; // skip iframes

  const COLORS = ['#E53935','#F57C00','#FDD835','#43A047','#1E88E5','#8E24AA','#00ACC1','#212121','#fff'];
  const LASER_COLOR = '#FF1744';

  let _active  = false;
  let _tool    = 'laser';
  let _color   = '#E53935';
  let _drawing = false;
  let _lastX, _lastY, _startX, _startY;
  let _strokes = [];          // committed [{kind,...}]
  let _redo    = [];          // undone strokes, for redo
  let _currentStroke = null;
  let _canvas, _ctx, _dpr = 1;
  let _toolbar, _toggleBtn, _laserEl, _laserTrail = [];
  let _laserFadeTimer, _animFrame;

  // Straight-edge shape tools (dragged from a start point to an end point)
  const SHAPES = new Set(['line','arrow','rect','ellipse']);

  // per-tool stroke sizes (driven by the shared slider)
  const SIZE = { pen: 3, highlighter: 22, eraser: 30, line: 3, arrow: 3, rect: 3, ellipse: 3 };
  const curSize = () => SIZE[_tool] || 3;

  /* ── INIT ──────────────────────────────────────────────────────────────── */

  function init() {
    buildCanvas();
    buildToggleBtn();
    buildToolbar();
    buildLaser();
    bindKeys();
  }

  /* ── CANVAS ────────────────────────────────────────────────────────────── */

  function buildCanvas() {
    _canvas = document.createElement('canvas');
    _canvas.id = 'ann-canvas';
    _canvas.setAttribute('aria-hidden', 'true');
    _css(_canvas, {
      position:'fixed', inset:'0', zIndex:'99990',
      pointerEvents:'none', touchAction:'none',
    });
    _ctx = _canvas.getContext('2d');
    resize();
    document.body.appendChild(_canvas);

    _canvas.addEventListener('mousedown',  onDown);
    _canvas.addEventListener('mousemove',  onMove);
    _canvas.addEventListener('mouseup',    onUp);
    _canvas.addEventListener('mouseleave', onUp);
    _canvas.addEventListener('touchstart', onTouchStart, {passive:false});
    _canvas.addEventListener('touchmove',  onTouchMove,  {passive:false});
    _canvas.addEventListener('touchend',   onUp);

    // Strokes are stored as vectors, so on resize we re-render them crisply
    // at the new size/DPR rather than stretching a bitmap snapshot.
    window.addEventListener('resize', () => { resize(); redraw(); });
  }

  function resize() {
    _dpr = window.devicePixelRatio || 1;
    _canvas.width  = Math.round(window.innerWidth  * _dpr);
    _canvas.height = Math.round(window.innerHeight * _dpr);
    _canvas.style.width  = window.innerWidth  + 'px';
    _canvas.style.height = window.innerHeight + 'px';
    // Draw in CSS pixels; the DPR scale keeps lines sharp on retina screens.
    _ctx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
  }

  function clearCanvas() {
    _ctx.save();
    _ctx.setTransform(1, 0, 0, 1, 0, 0);
    _ctx.clearRect(0, 0, _canvas.width, _canvas.height);
    _ctx.restore();
  }

  /* ── TOGGLE BUTTON ─────────────────────────────────────────────────────── */

  function buildToggleBtn() {
    _toggleBtn = _el('button', {
      id:'ann-toggle', title:'Draw / Annotate (Alt+A)',
      'aria-label':'Toggle annotation tools',
    });
    // Highlighter + pen combo icon — clearly "draw on screen", not "write a note"
    _toggleBtn.innerHTML = `
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z"/>
        <path d="M20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" fill="currentColor" stroke="none" opacity=".6"/>
      </svg>`;
    _css(_toggleBtn, {
      position:'fixed', bottom:'10.5rem', right:'1.4rem', zIndex:'99998',
      width:'44px', height:'44px', borderRadius:'14px',
      border:'1.5px solid rgba(255,255,255,.12)',
      background:'rgba(22,20,50,.88)', color:'#c8b8ff', cursor:'pointer',
      display:'flex', alignItems:'center', justifyContent:'center',
      boxShadow:'0 3px 14px rgba(0,0,0,.35)', backdropFilter:'blur(10px)',
      transition:'all .18s',
    });
    _toggleBtn.addEventListener('mouseenter', () => {
      if (!_active) _toggleBtn.style.background = 'rgba(50,40,100,.95)';
    });
    _toggleBtn.addEventListener('mouseleave', () => {
      if (!_active) _toggleBtn.style.background = 'rgba(22,20,50,.88)';
    });
    _toggleBtn.addEventListener('click', toggleActive);
    document.body.appendChild(_toggleBtn);
  }

  /* ── TOOLBAR ───────────────────────────────────────────────────────────── */

  function buildToolbar() {
    _toolbar = _el('div', {id:'ann-toolbar', role:'toolbar', 'aria-label':'Annotation tools'});
    _css(_toolbar, {
      position:'fixed', right:'1.4rem', bottom:'calc(10.5rem + 54px)', zIndex:'99999',
      display:'none', flexDirection:'column', gap:'6px', alignItems:'center',
    });

    /* colour swatches */
    const cWrap = _panel();
    _css(cWrap, { display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'5px', padding:'8px' });
    COLORS.forEach(c => {
      const sw = _el('button', {title:c, 'aria-label':'Color '+c});
      _css(sw, {
        width:'18px', height:'18px', borderRadius:'50%', padding:'0',
        background:c, border:'2px solid '+(c===_color?'#fff':'transparent'),
        cursor:'pointer', flexShrink:'0',
        outline: c==='#fff'?'1.5px solid #aaa':'none',
      });
      sw.addEventListener('click', () => {
        _color = c;
        cWrap.querySelectorAll('button').forEach(b =>
          b.style.border = b.title===c ? '2px solid #fff' : '2px solid transparent');
      });
      cWrap.appendChild(sw);
    });
    _toolbar.appendChild(cWrap);

    /* tool buttons */
    const tools = [
      { id:'laser',       emoji:'🔴',       label:'Laser pointer (L)' },
      { id:'pen',         svg: penSvg(),    label:'Pen (P)' },
      { id:'highlighter', emoji:'🖊',        label:'Highlighter (H)' },
      { id:'line',        svg: lineSvg(),   label:'Straight line (N)' },
      { id:'arrow',       svg: arrowSvg(),  label:'Arrow (A)' },
      { id:'rect',        svg: rectSvg(),   label:'Rectangle (R)' },
      { id:'ellipse',     svg: ellipseSvg(),label:'Ellipse (O)' },
      { id:'eraser',      emoji:'◻',        label:'Eraser (E)' },
    ];

    const tWrap = _panel();
    _css(tWrap, { display:'flex', flexDirection:'column', gap:'2px', padding:'5px' });

    tools.forEach(t => {
      const btn = _el('button', {title:t.label, 'data-tool':t.id});
      btn.innerHTML = t.svg || `<span style="font-size:14px">${t.emoji}</span>`;
      _css(btn, {
        width:'36px', height:'34px', border:'none', borderRadius:'8px',
        cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center',
        background: t.id===_tool ? 'rgba(255,255,255,.22)' : 'transparent',
        color:'#fff', transition:'background .12s',
      });
      btn.addEventListener('click', () => setTool(t.id));
      tWrap.appendChild(btn);
    });

    /* size slider */
    const sizeWrap = _el('div');
    _css(sizeWrap, { padding:'0 6px 2px', display:'flex', flexDirection:'column', gap:'2px' });
    const sizeLabel = _el('span');
    _css(sizeLabel, { fontSize:'10px', color:'rgba(255,255,255,.5)', textAlign:'center' });
    sizeLabel.textContent = 'Size';
    const slider = _el('input', {type:'range', min:'1', max:'40', value:'3', id:'ann-size-slider'});
    _css(slider, { width:'100%', accentColor:'#7B9FE0' });
    slider.addEventListener('input', () => {
      if (_tool !== 'laser') SIZE[_tool] = parseInt(slider.value);
    });
    sizeWrap.appendChild(sizeLabel);
    sizeWrap.appendChild(slider);
    tWrap.appendChild(_el('div', {}, {height:'4px'}));
    tWrap.appendChild(sizeWrap);

    /* undo / redo */
    const urWrap = _el('div');
    _css(urWrap, { display:'flex', gap:'2px', justifyContent:'center' });
    const mkStep = (title, svg, fn) => {
      const b = _el('button', {title});
      b.innerHTML = svg;
      _css(b, {
        width:'34px', height:'30px', border:'none', borderRadius:'8px',
        cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center',
        background:'transparent', color:'rgba(255,255,255,.55)', transition:'all .12s',
      });
      b.addEventListener('click', fn);
      b.addEventListener('mouseenter', () => b.style.background='rgba(255,255,255,.12)');
      b.addEventListener('mouseleave', () => b.style.background='transparent');
      return b;
    };
    urWrap.appendChild(mkStep('Undo  Ctrl+Z',
      `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>`,
      undoStroke));
    urWrap.appendChild(mkStep('Redo  Ctrl+Shift+Z',
      `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-.49-3.5"/></svg>`,
      redoStroke));
    tWrap.appendChild(urWrap);

    _toolbar.appendChild(tWrap);

    /* clear button */
    const clrWrap = _panel();
    _css(clrWrap, { padding:'5px' });
    const clrBtn = _el('button', {title:'Clear all annotations'});
    clrBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>`;
    _css(clrBtn, {
      width:'36px', height:'32px', border:'none', borderRadius:'8px',
      cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center',
      background:'rgba(220,50,50,.35)', color:'#ff9999', transition:'background .12s',
    });
    clrBtn.addEventListener('click', clearAll);
    clrBtn.addEventListener('mouseenter', () => clrBtn.style.background='rgba(220,50,50,.6)');
    clrBtn.addEventListener('mouseleave', () => clrBtn.style.background='rgba(220,50,50,.35)');
    clrWrap.appendChild(clrBtn);
    _toolbar.appendChild(clrWrap);

    document.body.appendChild(_toolbar);
  }

  function penSvg() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>`;
  }
  function lineSvg() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="4" y1="20" x2="20" y2="4"/></svg>`;
  }
  function arrowSvg() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="20" x2="19" y2="5"/><polyline points="10 5 19 5 19 14"/></svg>`;
  }
  function rectSvg() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="3.5" y="6" width="17" height="12" rx="1.5"/></svg>`;
  }
  function ellipseSvg() {
    return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><ellipse cx="12" cy="12" rx="9" ry="6.5"/></svg>`;
  }

  function setTool(id) {
    _tool = id;
    document.querySelectorAll('#ann-toolbar [data-tool]').forEach(b =>
      b.style.background = b.dataset.tool===id ? 'rgba(255,255,255,.22)' : 'transparent');
    // Sync slider to this tool's remembered size (laser has none)
    const sl = document.getElementById('ann-size-slider');
    if (sl && id !== 'laser') sl.value = SIZE[id] || 3;
    updateCursor();
  }

  /* ── LASER ─────────────────────────────────────────────────────────────── */

  function buildLaser() {
    _laserEl = _el('div', {id:'ann-laser', 'aria-hidden':'true'});
    _css(_laserEl, {
      position:'fixed', width:'20px', height:'20px',
      borderRadius:'50%', transform:'translate(-50%,-50%)',
      background:`radial-gradient(circle, ${LASER_COLOR} 0%, rgba(255,23,68,0) 65%)`,
      boxShadow:`0 0 10px 5px rgba(255,23,68,.55)`,
      pointerEvents:'none', zIndex:'100001', display:'none', opacity:'1',
      transition:'opacity .4s',
    });
    document.body.appendChild(_laserEl);
  }

  function moveLaser(x, y) {
    _laserEl.style.left  = x+'px';
    _laserEl.style.top   = y+'px';
    _laserEl.style.display = '';
    _laserEl.style.opacity = '1';
    clearTimeout(_laserFadeTimer);
    _laserFadeTimer = setTimeout(() => {
      _laserEl.style.opacity = '0';
      setTimeout(() => { if (_tool==='laser') _laserEl.style.display='none'; }, 400);
    }, 900);
  }

  /* ── ACTIVE STATE ──────────────────────────────────────────────────────── */

  function toggleActive() {
    _active = !_active;
    if (_active) {
      _toolbar.style.display = 'flex';
      _canvas.style.pointerEvents = 'all';
      _toggleBtn.style.background = 'rgba(90,55,160,.95)';
      _toggleBtn.style.color = '#fff';
      _toggleBtn.style.border = '1.5px solid rgba(200,184,255,.4)';
      _toggleBtn.style.boxShadow = '0 0 0 3px rgba(140,100,220,.4), 0 3px 14px rgba(0,0,0,.45)';
      _toggleBtn.title = 'Exit annotation mode (Esc)';
      updateCursor();
      // Briefly flash the toggle to confirm activation
      _toggleBtn.animate([{transform:'scale(1)'},{transform:'scale(1.18)'},{transform:'scale(1)'}],
        {duration:280, easing:'ease-out'});
    } else {
      _toolbar.style.display = 'none';
      _canvas.style.pointerEvents = 'none';
      _canvas.style.cursor = '';
      _toggleBtn.style.background = 'rgba(22,20,50,.88)';
      _toggleBtn.style.color = '#c8b8ff';
      _toggleBtn.style.border = '1.5px solid rgba(255,255,255,.12)';
      _toggleBtn.style.boxShadow = '0 3px 14px rgba(0,0,0,.35)';
      _toggleBtn.title = 'Annotation tools (Alt+A)';
      _laserEl.style.display = 'none';
    }
  }

  function updateCursor() {
    if (_tool === 'laser') {
      _canvas.style.cursor = 'none';
      _laserEl.style.display = '';
    } else if (_tool === 'eraser') {
      _canvas.style.cursor = 'cell';
      _laserEl.style.display = 'none';
    } else {
      _canvas.style.cursor = 'crosshair';
      _laserEl.style.display = 'none';
    }
  }

  /* ── DRAWING EVENTS ────────────────────────────────────────────────────── */

  function onDown(e) {
    if (!_active || _tool === 'laser') return;
    const {x, y} = pt(e);
    _drawing = true; _lastX = x; _lastY = y; _startX = x; _startY = y;
    if (SHAPES.has(_tool)) {
      _currentStroke = { kind:'shape', shape:_tool, color:_color, size:curSize(),
        x1:x, y1:y, x2:x, y2:y };
    } else {
      _currentStroke = { kind:'free', tool:_tool, color:_color, size:curSize(),
        points:[{x,y}] };
      drawSeg(x,y,x,y);
    }
  }

  function onMove(e) {
    if (!_active) return;
    const {x, y} = pt(e);
    if (_tool === 'laser') { moveLaser(x,y); return; }
    if (!_drawing) return;
    if (SHAPES.has(_tool)) {
      // Live preview: redraw committed strokes, then the shape being dragged.
      _currentStroke.x2 = x; _currentStroke.y2 = y;
      redraw();
      drawShape(_currentStroke);
    } else {
      drawSeg(_lastX, _lastY, x, y);
      if (_currentStroke) _currentStroke.points.push({x,y});
      _lastX = x; _lastY = y;
    }
  }

  function onUp() {
    if (_drawing && _currentStroke) {
      _strokes.push(_currentStroke);
      _redo = [];                       // a new stroke invalidates the redo trail
      if (_currentStroke.kind === 'shape') redraw();
    }
    _currentStroke = null;
    _drawing = false;
  }

  function onTouchStart(e) {
    e.preventDefault();
    const t = e.touches[0];
    onDown({clientX:t.clientX, clientY:t.clientY});
  }

  function onTouchMove(e) {
    e.preventDefault();
    const t = e.touches[0];
    onMove({clientX:t.clientX, clientY:t.clientY});
  }

  function pt(e) { return {x:e.clientX, y:e.clientY}; }

  /* ── CANVAS DRAW ───────────────────────────────────────────────────────── */

  function drawSeg(x1,y1,x2,y2) {
    applyStyle({ tool:_tool, color:_color, size:curSize() });
    _ctx.beginPath();
    _ctx.moveTo(x1,y1);
    _ctx.lineTo(x2,y2);
    _ctx.stroke();
    _ctx.restore();
  }

  function drawShape(s) {
    // Shapes render as solid strokes (like the pen), regardless of active colour alpha.
    applyStyle({ tool:'pen', color:s.color, size:s.size });
    const {x1,y1,x2,y2} = s;
    _ctx.beginPath();
    if (s.shape === 'line' || s.shape === 'arrow') {
      _ctx.moveTo(x1,y1); _ctx.lineTo(x2,y2); _ctx.stroke();
      if (s.shape === 'arrow') drawArrowHead(x1,y1,x2,y2,s.size);
    } else if (s.shape === 'rect') {
      _ctx.rect(Math.min(x1,x2), Math.min(y1,y2), Math.abs(x2-x1), Math.abs(y2-y1));
      _ctx.stroke();
    } else if (s.shape === 'ellipse') {
      _ctx.ellipse((x1+x2)/2, (y1+y2)/2, Math.abs(x2-x1)/2, Math.abs(y2-y1)/2, 0, 0, 2*Math.PI);
      _ctx.stroke();
    }
    _ctx.restore();
  }

  function drawArrowHead(x1,y1,x2,y2,size) {
    const ang = Math.atan2(y2-y1, x2-x1);
    const len = Math.max(12, size * 3.5);
    _ctx.beginPath();
    _ctx.moveTo(x2,y2);
    _ctx.lineTo(x2 - len*Math.cos(ang - Math.PI/6), y2 - len*Math.sin(ang - Math.PI/6));
    _ctx.moveTo(x2,y2);
    _ctx.lineTo(x2 - len*Math.cos(ang + Math.PI/6), y2 - len*Math.sin(ang + Math.PI/6));
    _ctx.stroke();
  }

  function drawFree(s) {
    if (!s.points || !s.points.length) return;
    applyStyle(s);
    _ctx.beginPath();
    _ctx.moveTo(s.points[0].x, s.points[0].y);
    if (s.points.length < 2) {
      // single click/dot — nudge so the line cap renders a point
      _ctx.lineTo(s.points[0].x + 0.01, s.points[0].y + 0.01);
    } else {
      for (let i=1;i<s.points.length;i++) _ctx.lineTo(s.points[i].x, s.points[i].y);
    }
    _ctx.stroke();
    _ctx.restore();
  }

  function applyStyle(s) {
    _ctx.save();
    if (s.tool === 'pen') {
      _ctx.globalCompositeOperation = 'source-over';
      _ctx.globalAlpha  = 1;
      _ctx.strokeStyle  = s.color;
      _ctx.lineWidth    = s.size;
      _ctx.lineCap      = 'round';
      _ctx.lineJoin     = 'round';
    } else if (s.tool === 'highlighter') {
      _ctx.globalCompositeOperation = 'source-over';
      _ctx.globalAlpha  = 0.3;
      _ctx.strokeStyle  = s.color;
      _ctx.lineWidth    = s.size;
      _ctx.lineCap      = 'square';
      _ctx.lineJoin     = 'round';
    } else if (s.tool === 'eraser') {
      _ctx.globalCompositeOperation = 'destination-out';
      _ctx.globalAlpha  = 1;
      _ctx.strokeStyle  = 'rgba(0,0,0,1)';
      _ctx.lineWidth    = s.size;
      _ctx.lineCap      = 'round';
      _ctx.lineJoin     = 'round';
    }
  }

  function undoStroke() {
    if (!_strokes.length) return;
    _redo.push(_strokes.pop());
    redraw();
  }

  function redoStroke() {
    if (!_redo.length) return;
    _strokes.push(_redo.pop());
    redraw();
  }

  function redraw() {
    clearCanvas();
    for (const s of _strokes) {
      if (s.kind === 'shape') drawShape(s);
      else drawFree(s);
    }
  }

  function clearAll() {
    clearCanvas();
    _strokes = [];
    _redo = [];
  }

  /* ── KEYBOARD ──────────────────────────────────────────────────────────── */

  const TOOL_KEYS = { l:'laser', p:'pen', h:'highlighter', n:'line',
    a:'arrow', r:'rect', o:'ellipse', e:'eraser' };

  function bindKeys() {
    document.addEventListener('keydown', e => {
      if (e.altKey && (e.key==='a'||e.key==='A')) { e.preventDefault(); toggleActive(); return; }
      if (!_active) return;
      if (e.key==='Escape') { toggleActive(); return; }
      if ((e.ctrlKey||e.metaKey) && (e.key==='z'||e.key==='Z')) {
        e.preventDefault();
        if (e.shiftKey) redoStroke(); else undoStroke();
        return;
      }
      if ((e.ctrlKey||e.metaKey) && (e.key==='y'||e.key==='Y')) { e.preventDefault(); redoStroke(); return; }
      // Single-key tool switching — ignore while typing in a field or with modifiers held.
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      const tool = TOOL_KEYS[e.key.toLowerCase()];
      if (tool) { e.preventDefault(); setTool(tool); }
    });
  }

  /* ── DOM HELPERS ───────────────────────────────────────────────────────── */

  function _el(tag, attrs={}, styles={}) {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k, v));
    Object.entries(styles).forEach(([k,v]) => el.style[k]=v);
    return el;
  }

  function _css(el, props) { Object.assign(el.style, props); }

  function _panel() {
    const d = _el('div');
    _css(d, {
      background:'rgba(18,16,38,.9)', borderRadius:'12px',
      border:'1px solid rgba(255,255,255,.09)', backdropFilter:'blur(10px)',
    });
    return d;
  }

  /* ── BOOT ──────────────────────────────────────────────────────────────── */

  if (document.readyState==='loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    setTimeout(init, 180);
  }

})();
