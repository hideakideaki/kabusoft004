import { escapeHtml, formatNumber } from './utils.js';

const SERIES_COLORS = ['#b85c38', '#2f5d7c', '#2a6a52', '#d38b2c', '#714d8b'];

function formatXAxisLabel(point) {
  if (point?.label) {
    return String(point.label);
  }
  if (Number.isFinite(point?.x)) {
    return String(point.x);
  }
  return '';
}

export function renderLineChart(container, { series, height = 280 }) {
  const validSeries = series.filter((item) => item.points.length > 1);
  if (!validSeries.length) {
    container.innerHTML = '<div class="chart-empty">表示できる equity データがありません。</div>';
    return;
  }

  const width = 900;
  const xValues = validSeries.flatMap((item) => item.points.map((point) => point.x));
  const yValues = validSeries.flatMap((item) => item.points.map((point) => point.y));
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);
  const tickValues = [0, 0.25, 0.5, 0.75, 1].map((ratio) => yMin + (yMax - yMin) * ratio);
  const maxLabelLength = Math.max(...tickValues.map((value) => formatNumber(value, 0).length), 6);
  const padding = {
    top: 18,
    right: 12,
    bottom: 54,
    left: Math.max(72, maxLabelLength * 10 + 20),
  };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  const scaleX = (value) => padding.left + ((value - xMin) / Math.max(xMax - xMin, 1)) * plotWidth;
  const scaleY = (value) => padding.top + (1 - (value - yMin) / Math.max(yMax - yMin, 1)) * plotHeight;

  const linePaths = validSeries
    .map((item, index) => {
      const path = item.points
        .map((point, pointIndex) => `${pointIndex === 0 ? 'M' : 'L'}${scaleX(point.x).toFixed(2)},${scaleY(point.y).toFixed(2)}`)
        .join(' ');
      return `<path d="${path}" fill="none" stroke="${SERIES_COLORS[index % SERIES_COLORS.length]}" stroke-width="3" stroke-linecap="round" />`;
    })
    .join('');

  const axisLines = `
    <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="rgba(84,62,43,0.25)" />
    <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="rgba(84,62,43,0.25)" />
  `;

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio, index) => {
    const value = tickValues[index];
    const y = padding.top + plotHeight - plotHeight * ratio;
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(84,62,43,0.08)" />
      <text x="${padding.left - 12}" y="${y + 4}" text-anchor="end" fill="#6d6257" font-size="12">${escapeHtml(formatNumber(value, 0))}</text>
    `;
  }).join('');

  const xTickIndexes = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => Math.round((validSeries[0].points.length - 1) * ratio))
    .filter((value, index, array) => array.indexOf(value) === index);

  const xTicks = xTickIndexes.map((pointIndex) => {
    const point = validSeries[0].points[pointIndex];
    const x = scaleX(point.x);
    return `
      <line x1="${x}" y1="${padding.top}" x2="${x}" y2="${height - padding.bottom}" stroke="rgba(84,62,43,0.06)" />
      <line x1="${x}" y1="${height - padding.bottom}" x2="${x}" y2="${height - padding.bottom + 6}" stroke="rgba(84,62,43,0.25)" />
      <text x="${x}" y="${height - padding.bottom + 12}" text-anchor="middle" dominant-baseline="hanging" fill="#6d6257" font-size="12">${escapeHtml(formatXAxisLabel(point))}</text>
    `;
  }).join('');

  const legend = validSeries
    .map((item, index) => `
      <span class="legend-item">
        <span class="legend-swatch" style="background:${SERIES_COLORS[index % SERIES_COLORS.length]}"></span>
        ${escapeHtml(item.label)}
      </span>
    `)
    .join('');

  container.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Equity comparison chart">
      ${yTicks}
      ${xTicks}
      ${axisLines}
      ${linePaths}
    </svg>
    <div class="legend">${legend}</div>
  `;
}

export function renderMetricBars(container, rows, metricKey) {
  const values = rows
    .map((row) => ({ ...row, value: Number(row[metricKey]) }))
    .filter((row) => Number.isFinite(row.value));

  if (!values.length) {
    container.innerHTML = '<div class="chart-empty">表示できる指標がありません。</div>';
    return;
  }

  const max = Math.max(...values.map((row) => Math.abs(row.value))) || 1;

  container.innerHTML = values
    .map((row, index) => {
      const ratio = Math.min(Math.abs(row.value) / max, 1);
      const color = SERIES_COLORS[index % SERIES_COLORS.length];
      return `
        <div style="display:grid;gap:6px;margin-bottom:14px;">
          <div style="display:flex;justify-content:space-between;gap:12px;">
            <strong>${escapeHtml(row.label)}</strong>
            <span class="muted">${escapeHtml(formatNumber(row.value))}</span>
          </div>
          <div style="height:14px;border-radius:999px;background:rgba(84,62,43,0.08);overflow:hidden;">
            <div style="height:100%;width:${Math.max(ratio * 100, 4)}%;background:${color};border-radius:999px;"></div>
          </div>
        </div>
      `;
    })
    .join('');
}
