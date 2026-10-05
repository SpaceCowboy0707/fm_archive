/* Inline SVG charts for ```chart blocks. Every value comes from a resolved tool result (src/charts.py). */
(() => {
  // Dark-surface categorical slots in fixed order (validated reference palette); "Other" is neutral.
  const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
  const OTHER = '#6b7686', SURFACE = '#0c1420', GRID = '#233244', AXIS = '#3a4d63', INK = '#e9eef5', MUTED = '#9db0c6';
  const W = 640;
  const fmt = v => typeof v !== 'number' ? String(v) : Math.abs(v) < 10 && !Number.isInteger(v) ? v.toFixed(2) : v.toLocaleString(undefined, {maximumFractionDigits: 1});
  const clip = (s, n) => (s = String(s ?? '')).length > n ? s.slice(0, n - 1) + '…' : s;
  const text = (x, y, s, attrs = '') => `<text x="${x}" y="${y}" fill="${MUTED}" font-size="11" ${attrs}>${esc(s)}</text>`;
  const tip = s => `<title>${esc(s)}</title>`;

  function ticks(lo, hi, count = 5) {
    if (lo === hi) { lo -= 1; hi += 1; }
    const raw = (hi - lo) / count, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
    // The last tick must reach the maximum, or the largest marks fall outside the plot.
    const start = Math.floor(lo / step) * step, stop = Math.ceil(hi / step) * step, out = [];
    for (let v = start; v <= stop + step * 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  const scale = (d0, d1, r0, r1) => v => r0 + (v - d0) / ((d1 - d0) || 1) * (r1 - r0);

  // Rounded data end, square at the baseline.
  function bar(x, y, w, h, horizontal) {
    const r = Math.min(4, (horizontal ? h : w) / 2, Math.abs(horizontal ? w : h));
    if (horizontal) return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - r)}z`;
    return `M${x},${y + h}v${-(h - r)}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - r}z`;
  }

  function legend(names, colors) {
    return names.length < 2 ? '' : `<div class="chart-legend">${names.map((n, i) => `<span><i style="background:${colors[i]}"></i>${esc(n)}</span>`).join('')}</div>`;
  }

  function yAxis(t, y, left, right) {
    return t.map(v => `<line x1="${left}" x2="${right}" y1="${y(v)}" y2="${y(v)}" stroke="${GRID}"/>` + text(left - 6, y(v) + 4, fmt(v), 'text-anchor="end"')).join('');
  }

  function columns(c) {
    const n = c.points.length, s = c.y_labels.length, top = 16, left = 52, right = W - 12;
    const rotate = n > 8, bottom = rotate ? 96 : 40, H = 300, base = H - bottom;
    const vals = c.points.flatMap(p => p.y), t = ticks(Math.min(0, ...vals), Math.max(0, ...vals));
    const y = scale(t[0], t[t.length - 1], base, top), band = (right - left) / n, gap = 2;
    const w = Math.max(3, Math.min(36, (band * 0.72 - gap * (s - 1)) / s));
    let g = yAxis(t, y, left, right);
    c.points.forEach((p, i) => {
      const x0 = left + band * i + (band - (w * s + gap * (s - 1))) / 2;
      p.y.forEach((v, k) => {
        const yv = y(v), y0 = y(0), h = Math.abs(y0 - yv);
        const path = v >= 0 ? bar(x0 + k * (w + gap), yv, w, h, false) : `M${x0 + k * (w + gap)},${y0}h${w}v${h}h${-w}z`;
        g += `<path d="${path}" fill="${SERIES[k]}">${tip(`${p.label} · ${c.y_labels[k]}: ${fmt(v)}`)}</path>`;
      });
      const cx = left + band * (i + 0.5);
      g += rotate ? text(cx, base + 12, clip(p.label, 18), `text-anchor="end" transform="rotate(-40 ${cx} ${base + 12})"`) : text(cx, base + 16, clip(p.label, 12), 'text-anchor="middle"');
    });
    g += `<line x1="${left}" x2="${right}" y1="${y(0)}" y2="${y(0)}" stroke="${AXIS}"/>`;
    return [H, g];
  }

  function rows(c) {
    const n = c.points.length, s = c.y_labels.length, row = 14 * s + 10, top = 8, left = 150, right = W - 56;
    const H = top + n * row + 28, vals = c.points.flatMap(p => p.y), t = ticks(Math.min(0, ...vals), Math.max(0, ...vals));
    const x = scale(t[0], t[t.length - 1], left, right);
    let g = t.map(v => `<line x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${H - 24}" stroke="${GRID}"/>` + text(x(v), H - 8, fmt(v), 'text-anchor="middle"')).join('');
    c.points.forEach((p, i) => {
      const y0 = top + i * row + 5;
      g += text(left - 8, y0 + row / 2, clip(p.label, 22), 'text-anchor="end"');
      p.y.forEach((v, k) => {
        const x0 = x(0), xv = x(v), yy = y0 + k * 14;
        const path = v >= 0 ? bar(x0, yy, Math.max(xv - x0, 0.5), 12, true) : `M${xv},${yy}h${x0 - xv}v12h${xv - x0}z`;
        g += `<path d="${path}" fill="${SERIES[k]}">${tip(`${p.label} · ${c.y_labels[k]}: ${fmt(v)}`)}</path>`;
      });
      if (s === 1) g += text(Math.max(x(p.y[0]), x(0)) + 5, y0 + row / 2, fmt(p.y[0]), `fill="${INK}"`);
    });
    g += `<line x1="${x(0)}" x2="${x(0)}" y1="${top}" y2="${H - 24}" stroke="${AXIS}"/>`;
    return [H, g];
  }

  function line(c) {
    const n = c.points.length, top = 16, left = 52, right = W - 16, H = 300, base = H - 44;
    const vals = c.points.flatMap(p => p.y), t = ticks(Math.min(...vals), Math.max(...vals));
    const y = scale(t[0], t[t.length - 1], base, top), x = i => n === 1 ? (left + right) / 2 : left + (right - left) * i / (n - 1);
    let g = yAxis(t, y, left, right);
    const every = Math.ceil(n / 8);
    // Edge labels anchor inward so the first and last dates stay inside the chart.
    c.points.forEach((p, i) => { if (i % every === 0 || i === n - 1) g += text(x(i), base + 18, clip(p.x, 12), `text-anchor="${n > 1 && i === 0 ? 'start' : n > 1 && i === n - 1 ? 'end' : 'middle'}"`); });
    c.y_labels.forEach((name, k) => {
      g += `<polyline fill="none" stroke="${SERIES[k]}" stroke-width="2" stroke-linejoin="round" points="${c.points.map((p, i) => `${x(i)},${y(p.y[k])}`).join(' ')}"/>`;
      c.points.forEach((p, i) => { g += `<circle cx="${x(i)}" cy="${y(p.y[k])}" r="4" fill="${SERIES[k]}" stroke="${SURFACE}" stroke-width="2">${tip(`${p.x} · ${name}: ${fmt(p.y[k])}`)}</circle>`; });
    });
    return [H, g];
  }

  function scatter(c) {
    const top = 16, left = 56, right = W - 16, H = 340, base = H - 44;
    let xs = c.points.map(p => p.x), ys = c.points.map(p => p.y[0]);
    let lo = [Math.min(...xs), Math.min(...ys)], hi = [Math.max(...xs), Math.max(...ys)];
    if (c.diagonal) { const a = Math.min(lo[0], lo[1], 0), b = Math.max(hi[0], hi[1]); lo = [a, a]; hi = [b, b]; }
    const tx = ticks(lo[0], hi[0]), ty = ticks(lo[1], hi[1]);
    const x = scale(tx[0], tx[tx.length - 1], left, right), y = scale(ty[0], ty[ty.length - 1], base, top);
    let g = yAxis(ty, y, left, right) + tx.map(v => text(x(v), base + 16, fmt(v), 'text-anchor="middle"')).join('');
    g += `<line x1="${left}" x2="${right}" y1="${base}" y2="${base}" stroke="${AXIS}"/>`;
    if (c.diagonal) {
      const d0 = Math.max(tx[0], ty[0]), d1 = Math.min(tx[tx.length - 1], ty[ty.length - 1]);
      g += `<line x1="${x(d0)}" y1="${y(d0)}" x2="${x(d1)}" y2="${y(d1)}" stroke="${MUTED}" stroke-dasharray="4 4" opacity=".6"/>` + text(x(d1) - 4, y(d1) + 14, 'y = x', 'text-anchor="end"');
    }
    // Label only the most notable points: furthest from y = x, or the highest y.
    const score = p => c.diagonal ? Math.abs(p.y[0] - p.x) : p.y[0];
    const named = new Set([...c.points].sort((a, b) => score(b) - score(a)).slice(0, 5));
    c.points.forEach(p => {
      g += `<circle cx="${x(p.x)}" cy="${y(p.y[0])}" r="5" fill="${SERIES[0]}" fill-opacity=".85" stroke="${SURFACE}" stroke-width="2">${tip(`${p.label} · ${c.x_label}: ${fmt(p.x)} · ${c.y_labels[0]}: ${fmt(p.y[0])}`)}</circle>`;
      if (named.has(p)) g += text(x(p.x) + 8, y(p.y[0]) - 6, clip(p.label, 20), `fill="${INK}"`);
    });
    g += text((left + right) / 2, H - 6, c.x_label, 'text-anchor="middle"') + text(14, (top + base) / 2, c.y_labels[0], `text-anchor="middle" transform="rotate(-90 14 ${(top + base) / 2})"`);
    return [H, g];
  }

  function pie(c) {
    const H = 260, cx = 130, cy = 130, r = 110, total = c.points.reduce((s, p) => s + p.y[0], 0);
    let angle = -Math.PI / 2, g = '';
    c.points.forEach((p, i) => {
      const share = p.y[0] / total, a1 = angle + share * 2 * Math.PI, large = share > 0.5 ? 1 : 0;
      const pt = a => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
      const color = p.other ? OTHER : SERIES[i];
      const d = share >= 0.9999 ? `M${cx - r},${cy}a${r},${r} 0 1 0 ${2 * r},0a${r},${r} 0 1 0 ${-2 * r},0` : `M${cx},${cy}L${pt(angle)}A${r},${r} 0 ${large} 1 ${pt(a1)}Z`;
      g += `<path d="${d}" fill="${color}" stroke="${SURFACE}" stroke-width="2">${tip(`${p.label}: ${fmt(p.y[0])} (${(share * 100).toFixed(1)}%)`)}</path>`;
      g += `<rect x="290" y="${24 + i * 26}" width="12" height="12" rx="3" fill="${color}"/>` + text(310, 34 + i * 26, `${clip(p.label, 24)} · ${fmt(p.y[0])} · ${(share * 100).toFixed(1)}%`, `fill="${INK}"`);
      angle = a1;
    });
    return [H, g];
  }

  function table(c) {
    const head = c.type === 'line' || c.type === 'scatter' ? [c.type === 'line' ? 'x' : 'label', ...(c.type === 'scatter' ? [c.x_label] : []), ...c.y_labels] : ['label', ...c.y_labels];
    const body = c.points.map(p => [c.type === 'line' ? p.x : p.label, ...(c.type === 'scatter' ? [p.x] : []), ...p.y]);
    return `<details class="chart-table"><summary>Data table</summary><table><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr>${body.map(r => `<tr>${r.map(v => `<td>${esc(fmt(v))}</td>`).join('')}</tr>`).join('')}</table></details>`;
  }

  window.renderChart = function (json) {
    let c;
    try { c = JSON.parse(json); } catch { return '<pre>' + esc(json) + '</pre>'; }
    const draw = {bar: columns, hbar: rows, line, scatter, pie}[c.type];
    if (!draw || !Array.isArray(c.points)) return '<pre>' + esc(json) + '</pre>';
    const [H, body] = draw(c);
    const names = c.type === 'pie' || c.type === 'scatter' ? [] : c.y_labels;
    const src = c.source || {};
    const notes = [`Values read from query ${[].concat(src.query).join(', ')} (${src.tool})`, src.snapshot_date && `as of ${src.snapshot_date}`,
      c.skipped && `${c.skipped} records without values not shown`, c.folded && `${c.folded} smaller slices combined as Other`].filter(Boolean).join(' · ');
    return `<figure class="chart no-tr"><figcaption>${esc(c.title)}</figcaption>${legend(names, SERIES)}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.title)}">${body}</svg><small>${esc(notes)}</small>${table(c)}</figure>`;
  };
})();
