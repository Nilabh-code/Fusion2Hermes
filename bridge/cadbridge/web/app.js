/* CAD canvas — draw on a photo, get millimetres, hand them to the agent.
   All geometry lives in IMAGE pixel coordinates; the view transform only
   affects rendering, so annotations stay valid at any zoom. */

const cv = document.getElementById('cv');
const ctx = cv.getContext('2d');

const S = {
  sid: new URLSearchParams(location.search).get('s') || '',
  img: null, imgW: 0, imgH: 0,
  view: { k: 1, ox: 0, oy: 0 },
  tool: 'pan',
  shapes: [],
  undo: [], redo: [],
  sel: -1,
  draft: null,
  poly: null,
  calibration: null,        // {a, b, line_px, real_mm}
  panning: null,
  space: false,
  dpr: window.devicePixelRatio || 1,
  sent: false,
};

const COLORS = {
  line: '#4d9fff', dim: '#ffb454', rect: '#7ee787', circle: '#ff7b72',
  poly: '#d2a8ff', text: '#e6edf3', cal: '#f778ba',
};
const LABEL = {
  line: 'line', dim: 'dim', rect: 'rect', circle: 'hole', poly: 'outline',
  text: 'note', cal: 'calibration',
};

/* ───────────────────────────────────────────────────────────── view maths */
function resize() {
  const r = cv.getBoundingClientRect();
  S.dpr = window.devicePixelRatio || 1;
  cv.width = Math.max(1, Math.round(r.width * S.dpr));
  cv.height = Math.max(1, Math.round(r.height * S.dpr));
  render();
}
function cssSize() {
  return { w: cv.clientWidth, h: cv.clientHeight };
}
function toImg(clientX, clientY) {
  const r = cv.getBoundingClientRect();
  return [(clientX - r.left - S.view.ox) / S.view.k, (clientY - r.top - S.view.oy) / S.view.k];
}
function fit() {
  if (!S.imgW) return;
  const { w, h } = cssSize();
  const k = Math.min(w / S.imgW, h / S.imgH) * 0.92;
  S.view = { k, ox: (w - S.imgW * k) / 2, oy: (h - S.imgH * k) / 2 };
  render();
}
function zoomAt(cx, cy, factor) {
  const r = cv.getBoundingClientRect();
  const px = cx - r.left, py = cy - r.top;
  const k2 = Math.min(40, Math.max(0.02, S.view.k * factor));
  S.view.ox = px - (px - S.view.ox) * (k2 / S.view.k);
  S.view.oy = py - (py - S.view.oy) * (k2 / S.view.k);
  S.view.k = k2;
  render();
}

/* ──────────────────────────────────────────────────────────────── render */
function render() {
  const { w, h } = cssSize();
  ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  ctx.save();
  ctx.translate(S.view.ox, S.view.oy);
  ctx.scale(S.view.k, S.view.k);

  if (S.img) {
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(S.img, 0, 0, S.imgW, S.imgH);
    ctx.strokeStyle = '#2b3947';
    ctx.lineWidth = 1 / S.view.k;
    ctx.strokeRect(0, 0, S.imgW, S.imgH);
  }

  S.shapes.forEach((s, i) => drawShape(s, i === S.sel));
  if (S.draft) drawShape(S.draft, false, true);
  if (S.poly) drawShape({ tool: 'poly', pts: S.poly.pts, label: S.poly.label }, false, true);
  ctx.restore();

  document.getElementById('zoomLabel').textContent = Math.round(S.view.k * 100) + '%';
  updateScaleOut();
}

function px(n) { return n / S.view.k; }   // screen-constant line width

function drawShape(s, isSel, isDraft) {
  const col = COLORS[s.tool] || '#4d9fff';
  ctx.save();
  ctx.strokeStyle = col;
  ctx.fillStyle = col + (isDraft ? '22' : '18');
  ctx.lineWidth = px(isSel ? 2.6 : 1.8);
  ctx.setLineDash(isDraft ? [px(6), px(4)] : s.tool === 'dim' ? [px(7), px(4)] : []);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';

  const label = s.label || '';
  if (s.tool === 'line' || s.tool === 'dim' || s.tool === 'cal') {
    const [a, b] = [s.a, s.b];
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    if (s.tool !== 'cal') { tick(a, b, col); tick(b, a, col); }
    const mm = mmOf(s);
    const text = [label, mm].filter(Boolean).join('  ');
    if (text) tag(text, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, col);
  } else if (s.tool === 'rect') {
    const x = Math.min(s.a[0], s.b[0]), y = Math.min(s.a[1], s.b[1]);
    const w = Math.abs(s.b[0] - s.a[0]), h = Math.abs(s.b[1] - s.a[1]);
    ctx.beginPath(); ctx.rect(x, y, w, h); ctx.fill(); ctx.stroke();
    const text = [label, s.w_mm ? `${s.w_mm} x ${s.h_mm}` : ''].filter(Boolean).join('  ');
    if (text) tag(text, x + w / 2, y + h / 2, col);
  } else if (s.tool === 'circle') {
    const r = Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]);
    ctx.beginPath(); ctx.arc(s.a[0], s.a[1], r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(s.a[0] - r * 0.18, s.a[1]); ctx.lineTo(s.a[0] + r * 0.18, s.a[1]);
    ctx.moveTo(s.a[0], s.a[1] - r * 0.18); ctx.lineTo(s.a[0], s.a[1] + r * 0.18); ctx.stroke();
    const text = [label, s.d_mm ? '⌀' + s.d_mm : ''].filter(Boolean).join('  ');
    if (text) tag(text, s.a[0], s.a[1] - r - px(10), col);
  } else if (s.tool === 'poly' && s.pts && s.pts.length > 1) {
    ctx.beginPath();
    ctx.moveTo(s.pts[0][0], s.pts[0][1]);
    for (let i = 1; i < s.pts.length; i++) ctx.lineTo(s.pts[i][0], s.pts[i][1]);
    if (!isDraft) ctx.closePath();
    ctx.fill(); ctx.stroke();
    if (label) tag(label, s.pts[0][0], s.pts[0][1] - px(8), col);
  } else if (s.tool === 'text') {
    ctx.font = `${px(13)}px ui-sans-serif, system-ui, sans-serif`;
    ctx.fillStyle = col;
    ctx.fillText(s.text || label || 'note', s.a[0], s.a[1]);
  }

  if (isSel && s.a) {
    ctx.fillStyle = '#fff';
    for (const p of [s.a, s.b].filter(Boolean)) {
      ctx.beginPath(); ctx.arc(p[0], p[1], px(3.2), 0, Math.PI * 2); ctx.fill();
    }
  }
  ctx.restore();
}

function tick(p, towards, col) {
  const ang = Math.atan2(towards[1] - p[1], towards[0] - p[0]) + Math.PI / 2;
  const L = px(6);
  ctx.beginPath();
  ctx.moveTo(p[0] - Math.cos(ang) * L, p[1] - Math.sin(ang) * L);
  ctx.lineTo(p[0] + Math.cos(ang) * L, p[1] + Math.sin(ang) * L);
  ctx.strokeStyle = col;
  ctx.stroke();
}

function tag(text, x, y, col) {
  ctx.font = `${px(11.5)}px ui-sans-serif, system-ui, sans-serif`;
  const pad = px(3);
  const w = ctx.measureText(text).width + pad * 2;
  const h = px(15);
  ctx.setLineDash([]);
  ctx.fillStyle = '#0b1118e6';
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x - w / 2, y - h - px(4), w, h, px(4));
  else ctx.rect(x - w / 2, y - h - px(4), w, h);
  ctx.fill();
  ctx.fillStyle = col;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x, y - h / 2 - px(4));
  ctx.textAlign = 'start';
  ctx.textBaseline = 'alphabetic';
}

/* ───────────────────────────────────────────────────────────── mm helpers */
function scaleMM() {
  const c = S.calibration;
  if (!c || !c.line_px || !c.real_mm) return null;
  return c.real_mm / c.line_px;
}
function mmOf(s) {
  if (s.value_mm) return s.value_mm.toFixed(2) + ' mm';
  const k = scaleMM();
  if (!k || !s.a || !s.b) return '';
  if (s.tool === 'line' || s.tool === 'dim') {
    return (Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) * k).toFixed(2) + ' mm';
  }
  if (s.tool === 'rect') {
    return `${(Math.abs(s.b[0] - s.a[0]) * k).toFixed(2)} x ${(Math.abs(s.b[1] - s.a[1]) * k).toFixed(2)} mm`;
  }
  if (s.tool === 'circle') {
    return '⌀' + (2 * Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) * k).toFixed(2) + ' mm';
  }
  return '';
}
function updateScaleOut() {
  const k = scaleMM();
  document.getElementById('scaleOut').textContent =
    k ? `scale: ${k.toFixed(4)} mm/px` : 'scale: not calibrated';
  const c = S.calibration;
  document.getElementById('calOut').textContent = c && k
    ? `${c.line_px.toFixed(1)} px = ${c.real_mm} mm -> ${k.toFixed(4)} mm/px`
    : 'no calibration';
}

/* ─────────────────────────────────────────────────────────────── history */
function snapshot() {
  S.undo.push(JSON.stringify({ shapes: S.shapes, calibration: S.calibration }));
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0;
}
function undo() {
  if (!S.undo.length) return;
  S.redo.push(JSON.stringify({ shapes: S.shapes, calibration: S.calibration }));
  const st = JSON.parse(S.undo.pop());
  S.shapes = st.shapes; S.calibration = st.calibration; S.sel = -1;
  renderList(); render();
}
function redo() {
  if (!S.redo.length) return;
  S.undo.push(JSON.stringify({ shapes: S.shapes, calibration: S.calibration }));
  const st = JSON.parse(S.redo.pop());
  S.shapes = st.shapes; S.calibration = st.calibration; S.sel = -1;
  renderList(); render();
}

/* ─────────────────────────────────────────────────────────── interaction */
function currentLabel() {
  return (document.getElementById('labelInput').value || '').trim();
}

function hitTest(pt) {
  const tol = px(8);
  for (let i = S.shapes.length - 1; i >= 0; i--) {
    const s = S.shapes[i];
    if ((s.tool === 'line' || s.tool === 'dim' || s.tool === 'cal') && s.a && s.b) {
      if (distToSeg(pt, s.a, s.b) < tol) return i;
    } else if (s.tool === 'rect') {
      const x0 = Math.min(s.a[0], s.b[0]), x1 = Math.max(s.a[0], s.b[0]);
      const y0 = Math.min(s.a[1], s.b[1]), y1 = Math.max(s.a[1], s.b[1]);
      const inside = pt[0] > x0 - tol && pt[0] < x1 + tol && pt[1] > y0 - tol && pt[1] < y1 + tol;
      const nearEdge = inside && (Math.abs(pt[0] - x0) < tol || Math.abs(pt[0] - x1) < tol ||
        Math.abs(pt[1] - y0) < tol || Math.abs(pt[1] - y1) < tol);
      if (nearEdge) return i;
    } else if (s.tool === 'circle') {
      const r = Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]);
      const d = Math.hypot(pt[0] - s.a[0], pt[1] - s.a[1]);
      if (Math.abs(d - r) < tol) return i;
    } else if (s.tool === 'poly' && s.pts) {
      for (let j = 1; j < s.pts.length; j++) {
        if (distToSeg(pt, s.pts[j - 1], s.pts[j]) < tol) return i;
      }
    } else if (s.tool === 'text') {
      if (Math.hypot(pt[0] - s.a[0], pt[1] - s.a[1]) < tol * 3) return i;
    }
  }
  return -1;
}
function distToSeg(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L2 = dx * dx + dy * dy;
  if (!L2) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

cv.addEventListener('pointerdown', (ev) => {
  if (ev.button === 1 || ev.button === 2 || S.tool === 'pan' || S.space) {
    S.panning = { x: ev.clientX, y: ev.clientY, ox: S.view.ox, oy: S.view.oy };
    cv.classList.add('panning');
    try { cv.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic event */ }
    return;
  }
  const p = toImg(ev.clientX, ev.clientY);
  ev.preventDefault();

  if (S.tool === 'erase') {
    const i = hitTest(p);
    if (i >= 0) {
      snapshot();
      const removed = S.shapes.splice(i, 1)[0];
      if (removed.tool === 'cal') S.calibration = null;
      S.sel = -1;
      renderList(); render();
    }
    return;
  }
  if (S.tool === 'text') {
    const t = prompt('Text note:', currentLabel() || 'note');
    if (t) {
      snapshot();
      S.shapes.push({ tool: 'text', a: p, text: t, label: t });
      renderList(); render();
    }
    return;
  }
  if (S.tool === 'poly') {
    if (!S.poly) S.poly = { pts: [p], label: currentLabel() };
    else S.poly.pts.push(p);
    render();
    return;
  }
  if (['line', 'dim', 'rect', 'circle', 'cal'].includes(S.tool)) {
    S.draft = { tool: S.tool, a: p, b: p, label: currentLabel() };
    try { cv.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic event */ }
  }
});

cv.addEventListener('pointermove', (ev) => {
  if (S.panning) {
    S.view.ox = S.panning.ox + (ev.clientX - S.panning.x);
    S.view.oy = S.panning.oy + (ev.clientY - S.panning.y);
    render();
    return;
  }
  const p = toImg(ev.clientX, ev.clientY);
  const k = scaleMM();
  document.getElementById('cursorOut').textContent =
    `x ${p[0].toFixed(0)} y ${p[1].toFixed(0)} px` +
    (k ? `  (${(p[0] * k).toFixed(1)}, ${(p[1] * k).toFixed(1)} mm)` : '');

  if (S.draft) {
    if (ev.shiftKey) {
      // axis lock for lines and dimensions
      const [a] = [S.draft.a];
      if (Math.abs(p[0] - a[0]) > Math.abs(p[1] - a[1])) p[1] = a[1];
      else p[0] = a[0];
    }
    S.draft.b = p;
    render();
  }
});

cv.addEventListener('pointerup', (ev) => {
  if (S.panning) {
    S.panning = null; cv.classList.remove('panning');
    return;
  }
  if (!S.draft) return;
  const d = S.draft; S.draft = null;
  const len = Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]);
  if (len < 2) { render(); return; }        // ignore clicks

  if (d.tool === 'cal') {
    snapshot();
    S.calibration = { a: d.a, b: d.b, line_px: +len.toFixed(2), real_mm: null };
    S.shapes.push({ tool: 'cal', a: d.a, b: d.b, label: 'calibrate' });
    renderList(); render();
    const inp = document.getElementById('calInput');
    inp.focus();
    toast('Now type the real length of that line in mm and press Enter');
    return;
  }
  snapshot();
  S.shapes.push(d);
  renderList(); render();
});

cv.addEventListener('dblclick', () => {
  if (S.poly) finishPoly();
});
cv.addEventListener('contextmenu', (e) => e.preventDefault());
cv.addEventListener('wheel', (ev) => {
  ev.preventDefault();
  zoomAt(ev.clientX, ev.clientY, ev.deltaY < 0 ? 1.12 : 1 / 1.12);
}, { passive: false });

function finishPoly() {
  if (S.poly && S.poly.pts.length > 2) {
    snapshot();
    S.shapes.push({ tool: 'poly', pts: S.poly.pts, label: S.poly.label });
  }
  S.poly = null;
  renderList(); render();
}

document.addEventListener('keydown', (ev) => {
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA') {
    if (ev.key === 'Escape') ev.target.blur();
    return;
  }
  if (ev.code === 'Space') { S.space = true; }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') {
    ev.preventDefault(); ev.shiftKey ? redo() : undo(); return;
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    if (S.sel >= 0) {
      snapshot();
      const r = S.shapes.splice(S.sel, 1)[0];
      if (r.tool === 'cal') S.calibration = null;
      S.sel = -1; renderList(); render();
    }
  }
  if (ev.key === 'Enter' && S.poly) return finishPoly();
  if (ev.key === 'Escape') { S.poly = null; S.draft = null; render(); }
  const map = { '1': 'line', '2': 'dim', '3': 'rect', '4': 'circle', '5': 'poly', '6': 'text', '7': 'erase' };
  if (map[ev.key]) setTool(map[ev.key]);
  if (ev.key.toLowerCase() === 'c') setTool('cal');
  if (ev.key.toLowerCase() === 'v') setTool('pan');
  if (ev.key.toLowerCase() === 'e') setTool('erase');
});
document.addEventListener('keyup', (ev) => { if (ev.code === 'Space') S.space = false; });

/* ────────────────────────────────────────────────────────────────── tools */
function setTool(t) {
  S.tool = t;
  if (t !== 'poly') S.poly = null;
  document.querySelectorAll('#tools .tool').forEach(b => {
    b.classList.toggle('active', b.dataset.tool === t);
  });
  cv.style.cursor = t === 'pan' ? 'grab' : t === 'erase' ? 'not-allowed' : 'crosshair';
  render();
}
document.querySelectorAll('#tools .tool').forEach(b => {
  b.addEventListener('click', () => setTool(b.dataset.tool));
});

/* ──────────────────────────────────────────────────────────────── panels */
function renderList() {
  const ul = document.getElementById('shapeList');
  ul.innerHTML = '';
  document.getElementById('shapeCount').textContent = S.shapes.length;
  S.shapes.forEach((s, i) => {
    const li = document.createElement('li');
    if (i === S.sel) li.classList.add('sel');
    const sw = document.createElement('span');
    sw.className = 'swatch';
    sw.style.background = COLORS[s.tool] || '#888';
    const t = document.createElement('span');
    t.className = 't';
    t.textContent = LABEL[s.tool] || s.tool;
    const lbl = document.createElement('span');
    lbl.className = 'lbl';
    lbl.textContent = s.label || s.text || '—';
    const mm = document.createElement('span');
    mm.className = 'mm';
    mm.textContent = mmOf(s);
    const del = document.createElement('button');
    del.className = 'del';
    del.textContent = '✕';
    del.title = 'delete';
    del.onclick = (ev) => {
      ev.stopPropagation();
      snapshot();
      const r = S.shapes.splice(i, 1)[0];
      if (r.tool === 'cal') S.calibration = null;
      S.sel = -1; renderList(); render();
    };
    li.append(sw, t, lbl, mm, del);
    li.onclick = () => { S.sel = i; renderList(); render(); };
    li.ondblclick = () => {
      const v = prompt('Label for this shape:', s.label || '');
      if (v !== null) { s.label = v.trim(); renderList(); render(); }
    };
    ul.appendChild(li);
  });
  document.getElementById('selOut').textContent =
    S.sel >= 0 && S.shapes[S.sel] ? `selected: ${LABEL[S.shapes[S.sel].tool]}` : 'no selection';
}

document.getElementById('calApply').onclick = applyCalibration;
document.getElementById('calInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') applyCalibration();
});
function applyCalibration() {
  const v = parseFloat(document.getElementById('calInput').value);
  if (!S.calibration) { toast('Draw a calibration line first (tool ⇹)'); return; }
  if (!v || v <= 0) { toast('Enter a positive length in mm'); return; }
  S.calibration.real_mm = v;
  snapshot();
  renderList(); render();
  toast(`Calibrated: 1 px = ${(v / S.calibration.line_px).toFixed(4)} mm`);
}

document.getElementById('undoBtn').onclick = undo;
document.getElementById('clearBtn').onclick = () => {
  if (!S.shapes.length && !S.calibration) return;
  snapshot();
  S.shapes = []; S.calibration = null; S.sel = -1;
  renderList(); render();
};
document.getElementById('fitBtn').onclick = fit;
document.getElementById('zoomIn').onclick = () => zoomAt(cv.clientWidth / 2 + cv.getBoundingClientRect().left,
  cv.clientHeight / 2 + cv.getBoundingClientRect().top, 1.25);
document.getElementById('zoomOut').onclick = () => zoomAt(cv.clientWidth / 2 + cv.getBoundingClientRect().left,
  cv.clientHeight / 2 + cv.getBoundingClientRect().top, 1 / 1.25);

/* ───────────────────────────────────────────────────────────────── images */
function loadImageFile(file) {
  const fr = new FileReader();
  fr.onload = () => setImageDataURL(fr.result);
  fr.readAsDataURL(file);
}
function setImageDataURL(dataUrl) {
  const img = new Image();
  img.onload = () => {
    S.img = img; S.imgW = img.naturalWidth; S.imgH = img.naturalHeight;
    document.getElementById('empty').style.display = 'none';
    fit();
  };
  img.src = dataUrl;
}
document.getElementById('fileInput').addEventListener('change', (e) => {
  if (e.target.files && e.target.files[0]) loadImageFile(e.target.files[0]);
});
document.getElementById('pasteBtn').onclick = async () => {
  try {
    const items = await navigator.clipboard.read();
    for (const it of items) {
      const type = it.types.find(t => t.startsWith('image/'));
      if (type) { loadImageFile(new File([await it.getType(type)], 'clip.png', { type })); return; }
    }
    toast('No image on the clipboard');
  } catch (err) { toast('Clipboard blocked — drag the file onto the canvas instead'); }
};
window.addEventListener('paste', (ev) => {
  for (const it of ev.clipboardData.items) {
    if (it.type.startsWith('image/')) { loadImageFile(it.getAsFile()); return; }
  }
});
['dragenter', 'dragover'].forEach(t => window.addEventListener(t, (e) => {
  e.preventDefault(); document.getElementById('stage').style.outline = '2px dashed #4d9fff';
}));
['dragleave', 'drop'].forEach(t => window.addEventListener(t, (e) => {
  e.preventDefault(); document.getElementById('stage').style.outline = 'none';
}));
window.addEventListener('drop', (ev) => {
  const f = ev.dataTransfer.files && ev.dataTransfer.files[0];
  if (f && f.type.startsWith('image/')) loadImageFile(f);
});

/* ────────────────────────────────────────────────────────────────── toast */
let toastEl = null;
function toast(msg) {
  if (!toastEl) {
    toastEl = document.createElement('div');
    toastEl.style.cssText = 'position:absolute;left:50%;top:14px;transform:translateX(-50%);' +
      'background:#1b2c44;border:1px solid #4d9fff;color:#e6edf3;padding:7px 13px;' +
      'border-radius:8px;font-size:12.5px;z-index:20;transition:opacity .2s';
    document.getElementById('stage').appendChild(toastEl);
  }
  toastEl.textContent = msg;
  toastEl.style.opacity = '1';
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => { toastEl.style.opacity = '0'; }, 2600);
}

/* ──────────────────────────────────────────────────────── composite + send */
function compositeDataURL() {
  if (!S.img) return null;
  const off = document.createElement('canvas');
  off.width = S.imgW; off.height = S.imgH;
  const c = off.getContext('2d');
  c.drawImage(S.img, 0, 0, S.imgW, S.imgH);
  const saved = { view: S.view, sel: S.sel };
  // draw shapes in image space at 1:1
  const realCtx = ctx;
  const saveView = { ...S.view };
  S.view = { k: 1, ox: 0, oy: 0 };
  const draw = (s) => {
    // reuse drawShape against a temporary context binding
    const oldCtx = window.__ctxSwap;
    window.__ctxSwap = c;
    drawShapeOn(c, s, false, false);
    window.__ctxSwap = oldCtx;
  };
  S.shapes.forEach(draw);
  if (S.draft) draw(S.draft);
  S.view = saveView;
  return off.toDataURL('image/png');
}

/* drawShape variant that writes into a supplied context (image-space, k=1) */
function drawShapeOn(c, s, isSel, isDraft) {
  const col = COLORS[s.tool] || '#4d9fff';
  const k = 1;
  c.save();
  c.strokeStyle = col; c.fillStyle = col + '22';
  c.lineWidth = 2.2; c.lineJoin = 'round'; c.lineCap = 'round';
  c.setLineDash(s.tool === 'dim' ? [7, 4] : []);
  if ((s.tool === 'line' || s.tool === 'dim' || s.tool === 'cal') && s.a && s.b) {
    c.beginPath(); c.moveTo(s.a[0], s.a[1]); c.lineTo(s.b[0], s.b[1]); c.stroke();
  } else if (s.tool === 'rect') {
    const x = Math.min(s.a[0], s.b[0]), y = Math.min(s.a[1], s.b[1]);
    c.beginPath(); c.rect(x, y, Math.abs(s.b[0] - s.a[0]), Math.abs(s.b[1] - s.a[1]));
    c.fill(); c.stroke();
  } else if (s.tool === 'circle') {
    const r = Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]);
    c.beginPath(); c.arc(s.a[0], s.a[1], r, 0, Math.PI * 2); c.fill(); c.stroke();
  } else if (s.tool === 'poly' && s.pts) {
    c.beginPath(); c.moveTo(s.pts[0][0], s.pts[0][1]);
    for (let i = 1; i < s.pts.length; i++) c.lineTo(s.pts[i][0], s.pts[i][1]);
    c.closePath(); c.fill(); c.stroke();
  } else if (s.tool === 'text') {
    c.font = '14px ui-sans-serif, system-ui, sans-serif';
    c.fillStyle = col; c.fillText(s.text || s.label || '', s.a[0], s.a[1]);
  }
  if (s.label) {
    c.font = '12px ui-sans-serif, system-ui, sans-serif';
    const x = s.a ? (s.b ? (s.a[0] + s.b[0]) / 2 : s.a[0]) : 0;
    const y = s.a ? (s.b ? (s.a[1] + s.b[1]) / 2 : s.a[1]) : 0;
    const w = c.measureText(s.label).width + 8;
    c.setLineDash([]);
    c.fillStyle = '#0b1118dd';
    c.fillRect(x - w / 2, y - 20, w, 16);
    c.fillStyle = col; c.fillText(s.label, x - w / 2 + 4, y - 8);
  }
  c.restore();
}

function annotationPayload() {
  const mm = (s) => {
    const k = scaleMM();
    const out = {};
    if (s.value_mm) out.value_mm = s.value_mm;
    if (!k || !s.a || !s.b) return out;
    if (s.tool === 'line' || s.tool === 'dim') {
      out.length_mm = round2(Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) * k);
    } else if (s.tool === 'rect') {
      out.w_mm = round2(Math.abs(s.b[0] - s.a[0]) * k);
      out.h_mm = round2(Math.abs(s.b[1] - s.a[1]) * k);
    } else if (s.tool === 'circle') {
      const r = Math.hypot(s.b[0] - s.a[0], s.b[1] - s.a[1]) * k;
      out.r_mm = round2(r); out.d_mm = round2(2 * r);
    }
    return out;
  };
  const round2 = (v) => Math.round(v * 100) / 100;

  const shapes = S.shapes.map(s => {
    const base = { tool: s.tool, label: s.label || '' };
    if (s.tool === 'poly') base.pts = s.pts.map(p => [round2(p[0]), round2(p[1])]);
    else if (s.tool === 'text') { base.a = s.a.map(round2); base.text = s.text || s.label; }
    else {
      base.a = [round2(s.a[0]), round2(s.a[1])];
      base.b = [round2(s.b[0]), round2(s.b[1])];
    }
    return { ...base, ...mm(s) };
  });

  return {
    annotation: {
      shapes,
      calibration: S.calibration
        ? { line_px: S.calibration.line_px, real_mm: S.calibration.real_mm }
        : null,
      image_size: [S.imgW, S.imgH],
    },
    notes: document.getElementById('notes').value.trim(),
    prompt: document.getElementById('prompt').value.trim(),
  };
}

async function send() {
  if (!S.sid) { toast('No session id in the URL'); return; }
  if (S.poly) finishPoly();
  if (!S.shapes.length) { toast('Draw at least one shape'); return; }
  const payload = annotationPayload();
  payload.png_base64 = compositeDataURL();
  const btn = document.getElementById('sendBtn');
  btn.disabled = true; btn.textContent = 'sending…';
  try {
    const res = await fetch('/api/submit/' + S.sid, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'submit failed');
    S.sent = true;
    const ov = document.getElementById('sentOverlay');
    document.getElementById('sentDetail').textContent =
      `${S.shapes.length} shape(s), ` +
      (S.calibration && S.calibration.real_mm
        ? `calibrated at ${(S.calibration.real_mm / S.calibration.line_px).toFixed(4)} mm/px`
        : 'no calibration — the agent will see pixels only');
    ov.classList.remove('hidden');
    btn.textContent = 'Sent ✓';
  } catch (err) {
    btn.disabled = false; btn.textContent = 'Send to agent';
    toast('Send failed: ' + err.message);
  }
}
document.getElementById('sendBtn').onclick = send;
document.getElementById('sentClose').onclick = () => {
  document.getElementById('sentOverlay').classList.add('hidden');
  document.getElementById('sendBtn').disabled = false;
  document.getElementById('sendBtn').textContent = 'Send to agent';
};

window.addEventListener('resize', resize);

/* ───────────────────────────────────────────────────────── test / agent API */
window.CB = {
  get state() { return S; },
  get shapes() { return S.shapes; },
  setTool,
  addShape(s) { S.shapes.push(s); renderList(); render(); return S.shapes.length; },
  setCalibration(line_px, real_mm) {
    S.calibration = { line_px, real_mm, a: [0, 0], b: [line_px, 0] };
    S.shapes.push({ tool: 'cal', a: [0, 0], b: [line_px, 0], label: 'calibrate' });
    renderList(); render(); applyCalibrationValue(real_mm);
  },
  applyCalibrationValue(mm) {
    if (S.calibration) { S.calibration.real_mm = mm; renderList(); render(); }
  },
  setImageDataURL, fit,
  setPrompt(v) { document.getElementById('prompt').value = v; },
  setNotes(v) { document.getElementById('notes').value = v; },
  setLabel(v) { document.getElementById('labelInput').value = v; },
  payload: annotationPayload,
  submit: send,
  scale: scaleMM,
};

/* ────────────────────────────────────────────────────────────── boot */
async function boot() {
  resize();
  setTool('pan');
  renderList();
  if (!S.sid) { document.getElementById('sessionHint').textContent = 'no session — open this page from the agent'; return; }
  try {
    const res = await fetch('/api/session/' + S.sid);
    const sess = await res.json();
    document.getElementById('sessionHint').textContent = 'session ' + S.sid;
    if (sess.prompt) document.getElementById('prompt').value = sess.prompt;
    if (sess.has_image) {
      const img = new Image();
      img.onload = () => {
        S.img = img; S.imgW = img.naturalWidth; S.imgH = img.naturalHeight;
        document.getElementById('empty').style.display = 'none';
        fit();
      };
      img.src = '/image/' + S.sid;
    }
  } catch (err) { /* offline: still usable for drawing */ }
}
window.addEventListener('load', boot);
resize();
