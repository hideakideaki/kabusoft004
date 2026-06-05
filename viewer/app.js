import { renderLineChart, renderMetricBars } from './charts.js';
import { loadDataFilePreview, loadRepositoryFromDirectoryHandle, loadRepositoryFromFileList } from './data_loader.js';
import { filterDataFiles, filterStrategies, getStrategyTypes } from './filters.js';
import { initState, setRepositoryData } from './state.js';
import { renderTable } from './tables.js';
import { escapeHtml, formatBytes, formatDate, formatNumber, formatPercent, summarizePriceData, toMarkdownHtml } from './utils.js';

const MAX_COMPARISON_STRATEGIES = 10;
const WEEKDAY_DEFINITIONS = [
  { day: 1, key: 'mon', label: '月' },
  { day: 2, key: 'tue', label: '火' },
  { day: 3, key: 'wed', label: '水' },
  { day: 4, key: 'thu', label: '木' },
  { day: 5, key: 'fri', label: '金' },
];

const state = initState();
state.statusLogs = [];

const elements = {
  pickDirectoryButton: document.querySelector('#pick-directory-button'),
  folderInputButton: document.querySelector('#folder-input-button'),
  directoryInput: document.querySelector('#directory-input'),
  sourceBadge: document.querySelector('#source-badge'),
  statusMessage: document.querySelector('#status-message'),
  statusLog: document.querySelector('#status-log'),
  summaryCards: document.querySelector('#summary-cards'),
  researchTabButton: document.querySelector('#research-tab-button'),
  liveSignalsTabButton: document.querySelector('#live-signals-tab-button'),
  researchTabPanel: document.querySelector('#research-tab-panel'),
  liveSignalsTabPanel: document.querySelector('#live-signals-tab-panel'),
  strategySearch: document.querySelector('#strategy-search'),
  strategyTypeFilter: document.querySelector('#strategy-type-filter'),
  benchmarkOnlyFilter: document.querySelector('#benchmark-only-filter'),
  strategyTableContainer: document.querySelector('#strategy-table-container'),
  comparisonLimitText: document.querySelector('#comparison-limit-text'),
  clearComparisonButton: document.querySelector('#clear-comparison-button'),
  comparisonRangeControls: document.querySelector('#comparison-range-controls'),
  equityChart: document.querySelector('#equity-chart'),
  metricChart: document.querySelector('#metric-chart'),
  weekdayProfitTable: document.querySelector('#weekday-profit-table'),
  detailTitle: document.querySelector('#detail-title'),
  detailBadge: document.querySelector('#detail-badge'),
  detailMetrics: document.querySelector('#detail-metrics'),
  detailMeta: document.querySelector('#detail-meta'),
  detailSummary: document.querySelector('#detail-summary'),
  detailEquityChart: document.querySelector('#detail-equity-chart'),
  detailEquityTable: document.querySelector('#detail-equity-table'),
  detailTradesTable: document.querySelector('#detail-trades-table'),
  detailWeekdayTable: document.querySelector('#detail-weekday-table'),
  reportComparison: document.querySelector('#report-comparison'),
  reportFinal: document.querySelector('#report-final'),
  archiveRunList: document.querySelector('#archive-run-list'),
  archiveReportTitle: document.querySelector('#archive-report-title'),
  archiveReportMeta: document.querySelector('#archive-report-meta'),
  archiveReportBadge: document.querySelector('#archive-report-badge'),
  archiveReportTabs: document.querySelector('#archive-report-tabs'),
  archiveReportContent: document.querySelector('#archive-report-content'),
  dataSearch: document.querySelector('#data-search'),
  dataKindFilter: document.querySelector('#data-kind-filter'),
  rawFileList: document.querySelector('#raw-file-list'),
  rawPreviewTitle: document.querySelector('#raw-preview-title'),
  rawSummary: document.querySelector('#raw-summary'),
  rawPreviewTable: document.querySelector('#raw-preview-table'),
  issuesContainer: document.querySelector('#issues-container'),
  liveSignalList: document.querySelector('#live-signal-list'),
  liveSignalDetailTitle: document.querySelector('#live-signal-detail-title'),
  liveSignalDetailBadge: document.querySelector('#live-signal-detail-badge'),
  liveSignalSummary: document.querySelector('#live-signal-summary'),
  liveSignalMeta: document.querySelector('#live-signal-meta'),
  liveSignalCandidatesTable: document.querySelector('#live-signal-candidates-table'),
};

function renderStatusLog() {
  if (!state.statusLogs.length) {
    elements.statusLog.innerHTML = '<div class="status-log-empty">まだ読み込みは開始していません。</div>';
    return;
  }
  elements.statusLog.innerHTML = `
    <div class="status-log-list">
      ${state.statusLogs.map((entry) => `
        <div class="status-log-item is-${escapeHtml(entry.level || 'info')}">
          <span class="status-log-time">${escapeHtml(entry.time)}</span>
          <span class="status-log-message">${escapeHtml(entry.message)}</span>
        </div>
      `).join('')}
    </div>
  `;
  elements.statusLog.scrollTop = elements.statusLog.scrollHeight;
}

function pushStatusLog(message, level = 'info') {
  const time = new Intl.DateTimeFormat('ja-JP', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date());
  state.statusLogs.push({ time, message, level });
  if (state.statusLogs.length > 80) {
    state.statusLogs = state.statusLogs.slice(-80);
  }
  renderStatusLog();
}

function clearStatusLog(initialMessage) {
  state.statusLogs = [];
  if (initialMessage) {
    pushStatusLog(initialMessage, 'info');
  } else {
    renderStatusLog();
  }
}

function setStatus(message, badgeClass = 'neutral') {
  elements.statusMessage.textContent = message;
  elements.sourceBadge.textContent = state.sourceLabel;
  elements.sourceBadge.className = `badge ${badgeClass}`;
}

function renderSummaryCards() {
  if (!state.repositoryData) {
    elements.summaryCards.innerHTML = '';
    return;
  }
  const { summary } = state.repositoryData;
  const cards = [
    ['戦略数', summary.strategies],
    ['benchmark', summary.benchmarkCount],
    ['raw files', summary.rawFiles],
    ['processed files', summary.processedFiles],
    ['live signals', summary.liveSignalPayloads ?? 0],
    ['issues', summary.issueCount],
  ];
  elements.summaryCards.innerHTML = cards.map(([label, value]) => `
    <article class="summary-card">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value">${escapeHtml(formatNumber(value, 0))}</span>
    </article>
  `).join('');
}

function renderStaticTexts() {
  elements.comparisonLimitText.textContent = `最大 ${MAX_COMPARISON_STRATEGIES} 戦略まで比較表示します。`;
}

function getVisibleStrategies() {
  return filterStrategies(state.repositoryData?.strategies ?? [], state.filters);
}

function getSelectedStrategy() {
  return state.repositoryData?.strategies.find((strategy) => strategy.id === state.selectedStrategyId) ?? null;
}

function getSelectedLiveSignal() {
  return state.repositoryData?.liveSignals?.items?.find((item) => item.id === state.selectedLiveSignalId) ?? null;
}

function renderTabState() {
  const isResearch = state.activeTab !== 'live_signals';
  elements.researchTabButton?.classList.toggle('is-active', isResearch);
  elements.researchTabButton?.setAttribute('aria-selected', String(isResearch));
  elements.liveSignalsTabButton?.classList.toggle('is-active', !isResearch);
  elements.liveSignalsTabButton?.setAttribute('aria-selected', String(!isResearch));
  if (elements.researchTabPanel) {
    elements.researchTabPanel.hidden = !isResearch;
    elements.researchTabPanel.classList.toggle('is-active', isResearch);
  }
  if (elements.liveSignalsTabPanel) {
    elements.liveSignalsTabPanel.hidden = isResearch;
    elements.liveSignalsTabPanel.classList.toggle('is-active', !isResearch);
  }
}

function getStrategyDisplayDateRange(strategy) {
  const startCandidates = [
    strategy?.meta?.train_start_date,
    strategy?.meta?.start_date,
  ].filter(Boolean);
  const endCandidates = [
    strategy?.meta?.test_end_date,
    strategy?.meta?.end_date,
  ].filter(Boolean);

  return {
    start: startCandidates.length ? startCandidates[0] : null,
    end: endCandidates.length ? endCandidates[0] : null,
  };
}

function getDisplayEquityRows(strategy) {
  if (!strategy) {
    return [];
  }
  const { start, end } = getStrategyDisplayDateRange(strategy);
  return strategy.equity.filter((row) => {
    const date = row.date ?? '';
    if (!date) {
      return false;
    }
    if (start && date < start) {
      return false;
    }
    if (end && date > end) {
      return false;
    }
    return true;
  });
}

async function renderRawPreview(file) {
  if (!file) {
    elements.rawPreviewTitle.textContent = 'プレビュー';
    elements.rawSummary.innerHTML = '<div class="empty-state">ファイルを選択してください。</div>';
    elements.rawPreviewTable.innerHTML = '';
    return;
  }

  elements.rawPreviewTitle.textContent = file.path;

  try {
    const preview = await loadDataFilePreview(file);
    const summaryBlocks = [
      { label: 'ファイルサイズ', value: formatBytes(file.size) },
      { label: 'カテゴリ', value: file.kind },
    ];
    if (preview.rows.length) {
      summaryBlocks.push({ label: '行数', value: formatNumber(preview.rows.length, 0) });
      summarizePriceData(preview.rows).forEach((item) => summaryBlocks.push(item));
    }

    elements.rawSummary.innerHTML = `
      <div class="metric-grid">
        ${summaryBlocks.map((item) => `
          <article class="metric-card">
            <span class="label">${escapeHtml(item.label)}</span>
            <span class="value" style="font-size:1.1rem;">${escapeHtml(item.value)}</span>
            ${item.subValue ? `<span class="muted">${escapeHtml(item.subValue)}</span>` : ''}
          </article>
        `).join('')}
      </div>
    `;

    if (preview.rows.length) {
      renderTable(elements.rawPreviewTable, {
        columns: preview.columns.slice(0, 8).map((column) => ({
          label: column,
          key: column,
          render: (row) => `<span class="${column === 'Date' ? 'mono' : ''}">${escapeHtml(row[column])}</span>`,
        })),
        rows: preview.rows.slice(0, 20),
        emptyMessage: 'CSV に表示可能な行がありません。',
      });
    } else {
      elements.rawPreviewTable.innerHTML = `<div class="table-wrap"><pre class="mono">${escapeHtml(preview.rawText.slice(0, 5000))}</pre></div>`;
    }
  } catch (error) {
    elements.rawSummary.innerHTML = `<div class="empty-state">プレビュー失敗: ${escapeHtml(error.message)}</div>`;
    elements.rawPreviewTable.innerHTML = '';
  }
}

function renderStrategyFilterOptions() {
  const types = getStrategyTypes(state.repositoryData?.strategies ?? []);
  if (!elements.strategyTypeFilter) {
    return;
  }
  elements.strategyTypeFilter.innerHTML = types
    .map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type === 'all' ? 'すべて' : type)}</option>`)
    .join('');
  elements.strategyTypeFilter.value = state.filters.strategyType;
}

function renderDataKindOptions() {
  const kinds = ['all', ...new Set((state.repositoryData?.dataFiles ?? []).map((file) => file.kind))];
  if (!elements.dataKindFilter) {
    return;
  }
  elements.dataKindFilter.innerHTML = kinds
    .map((kind) => `<option value="${escapeHtml(kind)}">${escapeHtml(kind === 'all' ? 'すべて' : kind)}</option>`)
    .join('');
  elements.dataKindFilter.value = state.filters.dataKind;
}

function buildComparisonPoint(row, index) {
  const timestamp = Date.parse(row.date ?? '');
  return {
    x: Number.isFinite(timestamp) ? timestamp : index,
    y: Number(row.equity),
    label: row.date ?? String(index),
  };
}

function parseDateWeekday(value) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) {
    return null;
  }
  const [, year, month, day] = match;
  const date = new Date(Number(year), Number(month) - 1, Number(day));
  const weekday = date.getDay();
  return Number.isFinite(weekday) ? weekday : null;
}

function parseDateTimestamp(value) {
  const match = String(value ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) {
    return null;
  }
  const [, year, month, day] = match;
  const timestamp = new Date(Number(year), Number(month) - 1, Number(day)).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function getTradeProfit(row) {
  const pnl = Number(row.pnl);
  if (Number.isFinite(pnl)) {
    return pnl;
  }
  const tradeReturn = Number(row.return);
  const entryValue = Number(row.entry_value);
  if (Number.isFinite(tradeReturn) && Number.isFinite(entryValue)) {
    return tradeReturn * entryValue;
  }
  return null;
}

function createEmptyWeekdayStats() {
  return Object.fromEntries(WEEKDAY_DEFINITIONS.map((item) => [item.day, {
    label: item.label,
    trades: 0,
    pnl: 0,
    returnSum: 0,
    wins: 0,
  }]));
}

function summarizeWeekdayProfits(strategy) {
  const stats = createEmptyWeekdayStats();
  (strategy?.trades ?? []).forEach((trade) => {
    const weekday = parseDateWeekday(trade.entry_date);
    if (!stats[weekday]) {
      return;
    }
    const profit = getTradeProfit(trade);
    const tradeReturn = Number(trade.return);
    stats[weekday].trades += 1;
    if (Number.isFinite(profit)) {
      stats[weekday].pnl += profit;
    }
    if (Number.isFinite(tradeReturn)) {
      stats[weekday].returnSum += tradeReturn;
      if (tradeReturn > 0) {
        stats[weekday].wins += 1;
      }
    } else if (Number.isFinite(profit) && profit > 0) {
      stats[weekday].wins += 1;
    }
  });

  return WEEKDAY_DEFINITIONS.map((item) => {
    const value = stats[item.day];
    return {
      weekday: item.label,
      key: item.key,
      trades: value.trades,
      pnl: value.pnl,
      avgReturn: value.trades ? value.returnSum / value.trades : null,
      winRate: value.trades ? value.wins / value.trades : null,
    };
  });
}

function getWeekdayTotal(summary) {
  return summary.reduce((total, row) => total + row.pnl, 0);
}

function getWeekdayBarScale(summary) {
  const maxAbs = Math.max(...summary.map((row) => Math.abs(Number(row.pnl) || 0)), 0);
  return maxAbs || 1;
}

function renderWeekdayProfitCell(row, maxAbs) {
  const pnl = Number(row?.pnl) || 0;
  const ratio = Math.min(Math.abs(pnl) / maxAbs, 1);
  const width = `${Math.max(ratio * 100, pnl === 0 ? 0 : 4).toFixed(1)}%`;
  const directionClass = pnl >= 0 ? 'is-positive' : 'is-negative';
  return `
    <div class="weekday-profit-cell ${directionClass}">
      <div class="weekday-profit-bar" style="width:${width};"></div>
      <div class="weekday-profit-content">
        <span class="weekday-profit-value mono">${escapeHtml(formatNumber(pnl, 0))}</span>
        <span class="weekday-profit-meta">${escapeHtml(formatNumber(row?.trades ?? 0, 0))} trades</span>
      </div>
    </div>
  `;
}

function getComparisonStrategies() {
  return state.repositoryData?.strategies.filter((strategy) => state.comparisonStrategyIds.includes(strategy.id)) ?? [];
}

function getComparisonDateDomain(strategies) {
  const dateMap = new Map();
  strategies.forEach((strategy) => {
    strategy.equity.forEach((row) => {
      const label = row.date ?? '';
      const timestamp = Date.parse(label);
      if (label && Number.isFinite(timestamp) && !dateMap.has(label)) {
        dateMap.set(label, timestamp);
      }
    });
  });
  return [...dateMap.entries()]
    .sort((left, right) => left[1] - right[1])
    .map(([label, timestamp]) => ({ label, timestamp }));
}

function ensureComparisonDateRange(domain) {
  if (!domain.length) {
    state.comparisonDateRange = null;
    return null;
  }

  const maxIndex = domain.length - 1;
  const minGap = maxIndex > 0 ? 1 : 0;
  const currentRange = state.comparisonDateRange;
  const nextStart = Math.max(0, Math.min(currentRange?.start ?? 0, maxIndex));
  const desiredEnd = Math.min(currentRange?.end ?? maxIndex, maxIndex);
  const nextEnd = Math.max(Math.min(nextStart + minGap, maxIndex), desiredEnd, nextStart);

  state.comparisonDateRange = { start: nextStart, end: nextEnd };
  return state.comparisonDateRange;
}

function renderComparisonRangeControls(domain, range) {
  if (!elements.comparisonRangeControls) {
    return;
  }
  if (!domain.length || !range) {
    elements.comparisonRangeControls.innerHTML = '';
    return;
  }

  const startLabel = domain[range.start]?.label ?? domain[0].label;
  const endLabel = domain[range.end]?.label ?? domain[domain.length - 1].label;

  elements.comparisonRangeControls.innerHTML = `
    <div class="comparison-range-summary">
      <span>表示期間</span>
      <span class="comparison-range-label">${escapeHtml(startLabel)} - ${escapeHtml(endLabel)}</span>
    </div>
    <div class="comparison-range-sliders">
      <div class="comparison-range-row">
        <label for="comparison-range-start">開始</label>
        <input id="comparison-range-start" type="range" min="0" max="${domain.length - 1}" step="1" value="${range.start}">
      </div>
      <div class="comparison-range-row">
        <label for="comparison-range-end">終了</label>
        <input id="comparison-range-end" type="range" min="0" max="${domain.length - 1}" step="1" value="${range.end}">
      </div>
    </div>
  `;

  const startInput = elements.comparisonRangeControls.querySelector('#comparison-range-start');
  const endInput = elements.comparisonRangeControls.querySelector('#comparison-range-end');

  startInput?.addEventListener('input', () => {
    const nextStart = Number(startInput.value);
    const maxIndex = domain.length - 1;
    const minGap = maxIndex > 0 ? 1 : 0;
    const nextEnd = Math.max(Math.min(nextStart + minGap, maxIndex), Number(endInput?.value ?? range.end));
    state.comparisonDateRange = { start: nextStart, end: nextEnd };
    renderComparison();
  });

  endInput?.addEventListener('input', () => {
    const nextEnd = Number(endInput.value);
    const maxIndex = domain.length - 1;
    const minGap = maxIndex > 0 ? 1 : 0;
    const nextStart = Math.min(Number(startInput?.value ?? range.start), Math.max(0, nextEnd - minGap));
    state.comparisonDateRange = { start: nextStart, end: nextEnd };
    renderComparison();
  });
}

function renderStrategyTable() {
  const rows = getVisibleStrategies();
  const recentEndTimestamp = getLatestEntryTimestamp(state.repositoryData?.strategies ?? []);
  renderTable(elements.strategyTableContainer, {
    columns: [
      {
        label: '比較',
        render: (strategy) => {
          const checked = state.comparisonStrategyIds.includes(strategy.id) ? 'checked' : '';
          return `<input type="checkbox" class="strategy-compare-checkbox" data-strategy-id="${escapeHtml(strategy.id)}" ${checked}>`;
        },
      },
      {
        label: 'strategy',
        render: (strategy) => {
          const isActive = strategy.id === state.selectedStrategyId;
          return `
            <button type="button" class="raw-file-button strategy-button ${isActive ? 'is-active' : ''}" data-strategy-id="${escapeHtml(strategy.id)}">
              <span class="file-name">${escapeHtml(strategy.meta.strategy_name ?? strategy.id)}</span>
              <span class="file-meta mono">${escapeHtml(strategy.id)}</span>
            </button>
          `;
        },
      },
      { label: 'type', render: (strategy) => escapeHtml(strategy.meta.strategy_type ?? 'N/A') },
      { label: 'benchmark', render: (strategy) => (strategy.meta.benchmark ? 'yes' : 'no') },
      { label: 'sharpe', render: (strategy) => escapeHtml(formatNumber(strategy.metrics.sharpe)) },
      { label: 'cagr', render: (strategy) => escapeHtml(formatPercent(strategy.metrics.cagr)) },
      { label: 'max_dd', render: (strategy) => escapeHtml(formatPercent(strategy.metrics.max_drawdown)) },
      { label: 'profit', render: (strategy) => `<span class="mono">${escapeHtml(formatNumber(getStrategyTotalProfit(strategy), 0))}</span>` },
      { label: 'profit 1m', render: (strategy) => `<span class="mono">${escapeHtml(formatNumber(getStrategyRecentMonthProfit(strategy, recentEndTimestamp), 0))}</span>` },
      { label: 'trades', render: (strategy) => escapeHtml(formatNumber(strategy.metrics.num_trades, 0)) },
      { label: 'status', render: (strategy) => escapeHtml(strategy.quality === 'good' ? 'ok' : 'issue') },
    ],
    rows,
    emptyMessage: '条件に一致する戦略がありません。',
  });

  elements.strategyTableContainer.querySelectorAll('.strategy-button').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedStrategyId = button.dataset.strategyId;
      renderAll();
    });
  });

  elements.strategyTableContainer.querySelectorAll('.strategy-compare-checkbox').forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
      const strategyId = checkbox.dataset.strategyId;
      const next = new Set(state.comparisonStrategyIds);
      if (checkbox.checked) {
        next.add(strategyId);
      } else {
        next.delete(strategyId);
      }
      state.comparisonStrategyIds = [...next].slice(0, MAX_COMPARISON_STRATEGIES);
      renderAll();
    });
  });
}

function getStrategyTotalProfit(strategy) {
  return (strategy?.trades ?? []).reduce((total, trade) => {
    const profit = getTradeProfit(trade);
    return Number.isFinite(profit) ? total + profit : total;
  }, 0);
}

function getLatestEntryTimestamp(strategies) {
  const timestamps = strategies
    .flatMap((strategy) => strategy.trades ?? [])
    .map((trade) => parseDateTimestamp(trade.entry_date))
    .filter((timestamp) => Number.isFinite(timestamp));
  return timestamps.length ? Math.max(...timestamps) : null;
}

function getStrategyRecentMonthProfit(strategy, endTimestamp) {
  if (!Number.isFinite(endTimestamp)) {
    return 0;
  }
  const endDate = new Date(endTimestamp);
  const startDate = new Date(endDate);
  startDate.setMonth(startDate.getMonth() - 1);
  const startTimestamp = startDate.getTime();

  return (strategy?.trades ?? []).reduce((total, trade) => {
    const timestamp = parseDateTimestamp(trade.entry_date);
    if (!Number.isFinite(timestamp) || timestamp < startTimestamp || timestamp > endTimestamp) {
      return total;
    }
    const profit = getTradeProfit(trade);
    return Number.isFinite(profit) ? total + profit : total;
  }, 0);
}

function renderComparison() {
  const selectedRows = getComparisonStrategies();
  const dateDomain = getComparisonDateDomain(selectedRows);
  const dateRange = ensureComparisonDateRange(dateDomain);
  renderComparisonRangeControls(dateDomain, dateRange);

  const minTimestamp = dateRange ? dateDomain[dateRange.start]?.timestamp ?? Number.NEGATIVE_INFINITY : Number.NEGATIVE_INFINITY;
  const maxTimestamp = dateRange ? dateDomain[dateRange.end]?.timestamp ?? Number.POSITIVE_INFINITY : Number.POSITIVE_INFINITY;

  renderLineChart(elements.equityChart, {
    series: selectedRows.map((strategy) => ({
      label: strategy.meta.strategy_name ?? strategy.id,
      points: getDisplayEquityRows(strategy)
        .map((row, index) => buildComparisonPoint(row, index))
        .filter((point) => point.x >= minTimestamp && point.x <= maxTimestamp)
        .filter((point) => Number.isFinite(point.y)),
    })),
  });
  renderMetricBars(
    elements.metricChart,
    selectedRows.map((strategy) => ({
      label: strategy.meta.strategy_name ?? strategy.id,
      sharpe: strategy.metrics.sharpe,
    })),
    'sharpe',
  );
}

function renderWeekdayProfitComparison() {
  const rows = getVisibleStrategies().map((strategy) => {
    const summary = summarizeWeekdayProfits(strategy);
    const byKey = Object.fromEntries(summary.map((item) => [item.key, item]));
    return {
      strategy,
      summary,
      byKey,
      totalPnl: getWeekdayTotal(summary),
    };
  });

  renderTable(elements.weekdayProfitTable, {
    columns: [
      {
        label: 'strategy',
        render: (row) => `
          <button type="button" class="raw-file-button strategy-button" data-weekday-strategy-id="${escapeHtml(row.strategy.id)}">
            <span class="file-name">${escapeHtml(row.strategy.meta.strategy_name ?? row.strategy.id)}</span>
            <span class="file-meta mono">${escapeHtml(row.strategy.id)}</span>
          </button>
        `,
      },
      ...WEEKDAY_DEFINITIONS.map((item) => ({
        label: `${item.label} pnl`,
        render: (row) => {
          const value = row.byKey[item.key];
          return renderWeekdayProfitCell(value, getWeekdayBarScale(row.summary));
        },
      })),
      { label: 'total pnl', render: (row) => `<span class="mono">${escapeHtml(formatNumber(row.totalPnl, 0))}</span>` },
    ],
    rows,
    emptyMessage: '曜日別利益を表示できる戦略がありません。',
  });

  elements.weekdayProfitTable.querySelectorAll('[data-weekday-strategy-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedStrategyId = button.dataset.weekdayStrategyId;
      renderAll();
    });
  });
}

function renderStrategyDetail() {
  const strategy = getSelectedStrategy();
  if (!strategy) {
    elements.detailTitle.textContent = '戦略詳細';
    elements.detailBadge.textContent = '未選択';
    elements.detailBadge.className = 'badge neutral';
    elements.detailMetrics.innerHTML = '<div class="empty-state">戦略を選択してください。</div>';
    elements.detailMeta.innerHTML = '';
    elements.detailSummary.innerHTML = '';
    elements.detailEquityChart.innerHTML = '';
    elements.detailEquityTable.innerHTML = '';
    elements.detailTradesTable.innerHTML = '';
    elements.detailWeekdayTable.innerHTML = '';
    return;
  }

  elements.detailTitle.textContent = strategy.meta.strategy_name ?? strategy.id;
  elements.detailBadge.textContent = strategy.meta.strategy_type ?? 'unknown';
  elements.detailBadge.className = `badge ${strategy.quality === 'good' ? 'good' : 'warn'}`;

  const metricCards = [
    ['Sharpe', formatNumber(strategy.metrics.sharpe)],
    ['CAGR', formatPercent(strategy.metrics.cagr)],
    ['Max Drawdown', formatPercent(strategy.metrics.max_drawdown)],
    ['Win Rate', formatPercent(strategy.metrics.win_rate)],
    ['Trades', formatNumber(strategy.metrics.num_trades, 0)],
    ['Equity Rows', formatNumber(strategy.equity.length, 0)],
  ];

  elements.detailMetrics.innerHTML = metricCards.map(([label, value]) => `
    <article class="metric-card">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value">${escapeHtml(value)}</span>
    </article>
  `).join('');

  const metaEntries = [
    ['strategy_id', strategy.meta.strategy_id ?? strategy.id],
    ['strategy_name', strategy.meta.strategy_name ?? strategy.id],
    ['strategy_type', strategy.meta.strategy_type ?? 'N/A'],
    ['benchmark', String(strategy.meta.benchmark)],
    ['status', strategy.meta.status ?? 'N/A'],
  ];
  elements.detailMeta.innerHTML = `
    <dl class="meta-list">
      ${metaEntries.map(([key, value]) => `
        <div class="meta-row">
          <dt>${escapeHtml(key)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>
      `).join('')}
    </dl>
  `;
  elements.detailSummary.innerHTML = `<div class="markdown-body">${toMarkdownHtml(strategy.resultSummary)}</div>`;

  const displayEquityRows = getDisplayEquityRows(strategy);

  renderLineChart(elements.detailEquityChart, {
    series: [
      {
        label: strategy.meta.strategy_name ?? strategy.id,
        points: displayEquityRows
          .map((row, index) => ({ x: index, y: Number(row.equity), label: row.date ?? String(index) }))
          .filter((point) => Number.isFinite(point.y)),
      },
    ],
    height: 320,
  });

  renderTable(elements.detailEquityTable, {
    columns: [
      { label: 'date', render: (row) => `<span class="mono">${escapeHtml(formatDate(row.date))}</span>` },
      { label: 'equity', render: (row) => escapeHtml(formatNumber(row.equity, 0)) },
    ],
    rows: strategy.equity.slice(0, 20),
    emptyMessage: 'equity.csv を表示できません。',
  });

  renderTable(elements.detailTradesTable, {
    columns: [
      { label: 'entry', render: (row) => `<span class="mono">${escapeHtml(formatDate(row.entry_date))}</span>` },
      { label: 'exit', render: (row) => `<span class="mono">${escapeHtml(formatDate(row.exit_date))}</span>` },
      { label: 'code', render: (row) => `<span class="mono">${escapeHtml(row.code)}</span>` },
      { label: 'side', render: (row) => escapeHtml(row.side) },
      { label: 'return', render: (row) => escapeHtml(formatPercent(row.return)) },
      { label: 'days', render: (row) => escapeHtml(formatNumber(row.holding_days, 0)) },
    ],
    rows: strategy.trades.slice(0, 20),
    emptyMessage: 'trades.csv を表示できません。',
  });

  const weekdayRows = summarizeWeekdayProfits(strategy);
  const weekdayMaxAbs = getWeekdayBarScale(weekdayRows);
  renderTable(elements.detailWeekdayTable, {
    columns: [
      { label: '買付曜日', render: (row) => escapeHtml(row.weekday) },
      { label: 'pnl合計', render: (row) => renderWeekdayProfitCell(row, weekdayMaxAbs) },
      { label: '平均return', render: (row) => escapeHtml(formatPercent(row.avgReturn)) },
      { label: '勝率', render: (row) => escapeHtml(formatPercent(row.winRate)) },
      { label: 'trades', render: (row) => escapeHtml(formatNumber(row.trades, 0)) },
    ],
    rows: weekdayRows,
    emptyMessage: '曜日別利益を表示できません。',
  });
}

function renderReports() {
  const reports = state.repositoryData?.reports;
  elements.reportComparison.innerHTML = `<div class="markdown-body">${toMarkdownHtml(reports?.comparisonMarkdown ?? '')}</div>`;
  elements.reportFinal.innerHTML = `<div class="markdown-body">${toMarkdownHtml(reports?.finalSummaryMarkdown ?? '')}</div>`;
  renderArchiveReports();
}

function getArchiveDisplayFiles(archive) {
  const preferredOrder = [
    'latest_consensus_candidates.md',
    'latest_consensus_candidates.csv',
    'operational_selection.md',
    'operational_selection.csv',
    'main_strategy_selection.md',
    'main_strategy_selection.csv',
    'outlier_contribution.md',
    'outlier_contribution.csv',
    'final_summary.md',
    'strategy_comparison.md',
    'strategy_ranking.csv',
    'archive_meta.json',
    'manifest.json',
  ];
  return [...(archive?.files ?? [])].sort((left, right) => {
    const leftIndex = preferredOrder.indexOf(left.name);
    const rightIndex = preferredOrder.indexOf(right.name);
    if (leftIndex === -1 && rightIndex === -1) {
      return left.name.localeCompare(right.name, 'ja');
    }
    if (leftIndex === -1) {
      return 1;
    }
    if (rightIndex === -1) {
      return -1;
    }
    return leftIndex - rightIndex;
  });
}

function getSelectedArchiveRun() {
  const archives = state.repositoryData?.reports?.archiveRuns ?? [];
  return archives.find((archive) => archive.id === state.selectedArchiveRunId) ?? null;
}

function getSelectedArchiveReport() {
  const archive = getSelectedArchiveRun();
  return archive?.files.find((file) => file.path === state.selectedArchiveReportPath) ?? null;
}

function renderReportFile(file) {
  if (!file) {
    elements.archiveReportContent.innerHTML = '<div class="empty-state">アーカイブ内のレポートを選択してください。</div>';
    return;
  }

  if (file.extension === 'md') {
    elements.archiveReportContent.innerHTML = `<div class="markdown-body">${toMarkdownHtml(file.markdown)}</div>`;
    return;
  }

  if (file.extension === 'csv') {
    const columns = file.columns.slice(0, 12);
    renderTable(elements.archiveReportContent, {
      columns: columns.map((column) => ({
        label: column,
        render: (row) => `<span class="${['rank', 'strategy_id', 'symbol', 'candidate_max_date', 'latest_market_date'].includes(column) ? 'mono' : ''}">${escapeHtml(row[column] ?? '')}</span>`,
      })),
      rows: file.rows.slice(0, 80),
      emptyMessage: 'CSV に表示可能な行がありません。',
    });
    return;
  }

  if (file.extension === 'json') {
    elements.archiveReportContent.innerHTML = `<div class="table-wrap"><pre class="mono">${escapeHtml(JSON.stringify(file.json ?? {}, null, 2))}</pre></div>`;
    return;
  }

  elements.archiveReportContent.innerHTML = `<div class="table-wrap"><pre class="mono">${escapeHtml(file.rawText.slice(0, 12000))}</pre></div>`;
}

function renderArchiveReports() {
  const archives = state.repositoryData?.reports?.archiveRuns ?? [];
  if (!elements.archiveRunList) {
    return;
  }

  if (!archives.length) {
    elements.archiveRunList.innerHTML = '<div class="empty-state">reports/archive のスナップショットがありません。</div>';
    elements.archiveReportTitle.textContent = 'Archive Report';
    elements.archiveReportMeta.textContent = '';
    elements.archiveReportBadge.textContent = '未選択';
    elements.archiveReportBadge.className = 'badge neutral';
    elements.archiveReportTabs.innerHTML = '';
    elements.archiveReportContent.innerHTML = '<div class="empty-state">表示できるアーカイブがありません。</div>';
    return;
  }

  if (!archives.some((archive) => archive.id === state.selectedArchiveRunId)) {
    state.selectedArchiveRunId = archives[0].id;
  }

  elements.archiveRunList.innerHTML = `<div class="raw-file-list">${
    archives.map((archive) => {
      const generatedAt = archive.meta?.generated_at ? formatDate(archive.meta.generated_at) : 'N/A';
      const marketDate = archive.meta?.latest_market_date ?? 'N/A';
      return `
        <button type="button" class="raw-file-button ${archive.id === state.selectedArchiveRunId ? 'is-active' : ''}" data-archive-id="${escapeHtml(archive.id)}">
          <span class="file-name mono">${escapeHtml(archive.id)}</span>
          <span class="file-meta">latest_market_date: ${escapeHtml(marketDate)}</span>
          <span class="file-meta">generated_at: ${escapeHtml(generatedAt)} / ${escapeHtml(formatNumber(archive.files.length, 0))} files</span>
        </button>
      `;
    }).join('')
  }</div>`;

  elements.archiveRunList.querySelectorAll('[data-archive-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedArchiveRunId = button.dataset.archiveId;
      state.selectedArchiveReportPath = null;
      renderReports();
    });
  });

  const archive = getSelectedArchiveRun();
  const displayFiles = getArchiveDisplayFiles(archive);
  if (!displayFiles.some((file) => file.path === state.selectedArchiveReportPath)) {
    state.selectedArchiveReportPath = displayFiles[0]?.path ?? null;
  }
  const selectedFile = getSelectedArchiveReport();

  elements.archiveReportTitle.textContent = selectedFile?.name ?? 'Archive Report';
  elements.archiveReportMeta.textContent = archive?.meta?.note ?? 'Snapshot of decision reports.';
  elements.archiveReportBadge.textContent = archive?.meta?.latest_market_date ?? archive?.id ?? 'archive';
  elements.archiveReportBadge.className = 'badge good';
  elements.archiveReportTabs.innerHTML = displayFiles.map((file) => `
    <button type="button" class="report-file-tab ${file.path === state.selectedArchiveReportPath ? 'is-active' : ''}" data-report-path="${escapeHtml(file.path)}">
      ${escapeHtml(file.name)}
    </button>
  `).join('');

  elements.archiveReportTabs.querySelectorAll('[data-report-path]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedArchiveReportPath = button.dataset.reportPath;
      renderReports();
    });
  });

  renderReportFile(selectedFile);
}

async function renderDataFiles() {
  const visibleFiles = filterDataFiles(state.repositoryData?.dataFiles ?? [], state.filters);
  if (!visibleFiles.length) {
    elements.rawFileList.innerHTML = '<div class="empty-state">条件に一致するデータファイルがありません。</div>';
    await renderRawPreview(null);
    return;
  }
  if (!visibleFiles.some((file) => file.path === state.selectedDataFilePath)) {
    state.selectedDataFilePath = visibleFiles[0].path;
  }

  elements.rawFileList.innerHTML = `<div class="raw-file-list">${
    visibleFiles.slice(0, 250).map((file) => `
      <button type="button" class="raw-file-button ${file.path === state.selectedDataFilePath ? 'is-active' : ''}" data-file-path="${escapeHtml(file.path)}">
        <span class="file-name mono">${escapeHtml(file.name)}</span>
        <span class="file-meta">${escapeHtml(file.kind)} / ${escapeHtml(formatBytes(file.size))}</span>
        <span class="file-meta">${escapeHtml(file.path)}</span>
      </button>
    `).join('')
  }</div>`;

  elements.rawFileList.querySelectorAll('.raw-file-button').forEach((button) => {
    button.addEventListener('click', async () => {
      state.selectedDataFilePath = button.dataset.filePath;
      await renderDataFiles();
    });
  });

  const selected = visibleFiles.find((file) => file.path === state.selectedDataFilePath) ?? visibleFiles[0];
  await renderRawPreview(selected);
}

function renderIssues() {
  const issues = state.repositoryData?.issues ?? [];
  if (!issues.length) {
    elements.issuesContainer.innerHTML = '<div class="empty-state">欠損やパース失敗は検出されませんでした。</div>';
    return;
  }
  elements.issuesContainer.innerHTML = `
    <div class="issue-list">
      ${issues.map((issue) => `
        <article class="issue-card">
          <h3>${escapeHtml(issue.message)}</h3>
          <span class="issue-location">${escapeHtml(issue.path)}</span>
          <div class="issue-body">${escapeHtml(issue.scope)}</div>
        </article>
      `).join('')}
    </div>
  `;
}

function renderLiveSignalMeta(item) {
  const payload = item?.payload;
  if (!payload) {
    elements.liveSignalMeta.innerHTML = '<div class="empty-state">live signal を選択してください。</div>';
    return;
  }
  const entries = Object.entries(payload)
    .filter(([key]) => !['candidates', 'main_payloads'].includes(key))
    .map(([key, value]) => {
      if (Array.isArray(value)) {
        return [key, value.join(', ')];
      }
      if (value && typeof value === 'object') {
        return [key, `object (${Object.keys(value).length})`];
      }
      return [key, String(value)];
    });

  elements.liveSignalMeta.innerHTML = `
    <dl class="meta-list">
      ${entries.map(([key, value]) => `
        <div class="meta-row">
          <dt>${escapeHtml(key)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>
      `).join('')}
    </dl>
  `;
}

function renderLiveSignals() {
  const items = state.repositoryData?.liveSignals?.items ?? [];
  if (!items.length) {
    elements.liveSignalList.innerHTML = '<div class="empty-state">live_signals/outputs の成果物がありません。</div>';
    elements.liveSignalDetailTitle.textContent = 'Live Signal Detail';
    elements.liveSignalDetailBadge.textContent = '未選択';
    elements.liveSignalDetailBadge.className = 'badge neutral';
    elements.liveSignalSummary.innerHTML = '<div class="empty-state">表示できる live signal がありません。</div>';
    elements.liveSignalMeta.innerHTML = '';
    elements.liveSignalCandidatesTable.innerHTML = '';
    return;
  }

  if (!items.some((item) => item.id === state.selectedLiveSignalId)) {
    state.selectedLiveSignalId = items[0].id;
  }

  elements.liveSignalList.innerHTML = `<div class="raw-file-list">${
    items.map((item) => `
      <button type="button" class="raw-file-button ${item.id === state.selectedLiveSignalId ? 'is-active' : ''}" data-live-signal-id="${escapeHtml(item.id)}">
        <span class="file-name">${escapeHtml(item.title)}</span>
        <span class="file-meta">${escapeHtml(item.type)} / ${escapeHtml(item.plannedEntryDate ?? 'N/A')}</span>
        <span class="file-meta mono">${escapeHtml(item.name)}</span>
      </button>
    `).join('')
  }</div>`;

  elements.liveSignalList.querySelectorAll('[data-live-signal-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedLiveSignalId = button.dataset.liveSignalId;
      renderLiveSignals();
    });
  });

  const item = getSelectedLiveSignal();
  if (!item) {
    return;
  }

  elements.liveSignalDetailTitle.textContent = item.title;
  elements.liveSignalDetailBadge.textContent = item.type === 'meta_consensus' ? 'meta_consensus' : (item.strategyId ?? 'strategy_signal');
  elements.liveSignalDetailBadge.className = `badge ${item.type === 'meta_consensus' ? 'warn' : 'good'}`;

  const summaryCards = [
    ['signal_date', item.signalDate ?? 'N/A'],
    ['planned_entry_date', item.plannedEntryDate ?? 'N/A'],
    ['holding_days', item.holdingDays ?? 'N/A'],
    ['candidate_count', item.candidateCount ?? 0],
    ['entry_offset_days', item.entryOffsetDays ?? 'N/A'],
    ['generated_at', item.generatedAt ? formatDate(item.generatedAt) : 'N/A'],
  ];
  elements.liveSignalSummary.innerHTML = summaryCards.map(([label, value]) => `
    <article class="metric-card">
      <span class="label">${escapeHtml(label)}</span>
      <span class="value" style="font-size:1.1rem;">${escapeHtml(String(value))}</span>
    </article>
  `).join('');

  renderLiveSignalMeta(item);

  const preferredOrder = ['rank', 'strategy_id', 'signal_date', 'planned_entry_date', 'holding_days', 'symbol', 'final_score', 'score', 'support_count', 'main_strategies', 'action'];
  const columns = (item.csvColumns.length ? item.csvColumns : preferredOrder)
    .slice()
    .sort((left, right) => {
      const leftIndex = preferredOrder.indexOf(left);
      const rightIndex = preferredOrder.indexOf(right);
      if (leftIndex === -1 && rightIndex === -1) {
        return left.localeCompare(right, 'ja');
      }
      if (leftIndex === -1) {
        return 1;
      }
      if (rightIndex === -1) {
        return -1;
      }
      return leftIndex - rightIndex;
    })
    .slice(0, 12);

  renderTable(elements.liveSignalCandidatesTable, {
    columns: columns.map((column) => ({
      label: column,
      render: (row) => `<span class="${['symbol', 'strategy_id', 'signal_date', 'planned_entry_date'].includes(column) ? 'mono' : ''}">${escapeHtml(row[column] ?? '')}</span>`,
    })),
    rows: item.csvRows,
    emptyMessage: 'candidate データがありません。',
  });
}

async function renderAll() {
  renderTabState();
  renderSummaryCards();
  renderStrategyFilterOptions();
  renderDataKindOptions();
  renderStrategyTable();
  renderComparison();
  renderWeekdayProfitComparison();
  renderStrategyDetail();
  renderReports();
  await renderDataFiles();
  renderIssues();
  renderLiveSignals();
}

async function applyRepositoryData(repositoryData, sourceLabel) {
  setRepositoryData(state, repositoryData, sourceLabel);
  pushStatusLog(
    `読み込み完了: 戦略 ${repositoryData.summary.strategies} 件、raw ${repositoryData.summary.rawFiles} 件、issues ${repositoryData.summary.issueCount} 件`,
    repositoryData.summary.issueCount ? 'warn' : 'good',
  );
  setStatus(
    `${repositoryData.summary.strategies} 戦略、${repositoryData.summary.rawFiles} raw files を読み込みました。`,
    repositoryData.summary.issueCount ? 'warn' : 'good',
  );
  await renderAll();
}

async function loadFromDirectoryPicker() {
  if (!window.showDirectoryPicker) {
    pushStatusLog('Directory Picker 非対応のブラウザです。フォルダ入力を使ってください。', 'warn');
    setStatus('このブラウザでは Directory Picker が使えません。フォルダ入力を使ってください。', 'warn');
    return;
  }
  try {
    clearStatusLog('Directory Picker の起動を待っています。');
    setStatus('リポジトリを読み込み中です...', 'neutral');
    const directoryHandle = await window.showDirectoryPicker({ mode: 'read' });
    pushStatusLog(`選択フォルダ: ${directoryHandle.name}`);
    const repositoryData = await loadRepositoryFromDirectoryHandle(directoryHandle, {
      onProgress: ({ message, level }) => pushStatusLog(message, level),
    });
    await applyRepositoryData(repositoryData, 'Directory Picker');
  } catch (error) {
    if (error.name === 'AbortError') {
      pushStatusLog('フォルダ選択がキャンセルされました。', 'warn');
      setStatus('フォルダ選択がキャンセルされました。', 'neutral');
      return;
    }
    pushStatusLog(`読み込み失敗: ${error.message}`, 'warn');
    setStatus(`読み込みに失敗しました: ${error.message}`, 'warn');
  }
}

async function loadFromInput(files) {
  if (!files.length) {
    pushStatusLog('フォルダ入力からファイルが渡されませんでした。選択がキャンセルされた可能性があります。', 'warn');
    return;
  }
  try {
    clearStatusLog(`フォルダ入力を受け付けました。ファイル数: ${files.length}`);
    setStatus('フォルダ入力から読み込み中です...', 'neutral');
    const rootName = files[0]?.webkitRelativePath?.split('/')[0] ?? '(unknown)';
    pushStatusLog(`選択フォルダ: ${rootName}`);
    const repositoryData = await loadRepositoryFromFileList(files, {
      onProgress: ({ message, level }) => pushStatusLog(message, level),
    });
    await applyRepositoryData(repositoryData, 'Folder Input');
  } catch (error) {
    pushStatusLog(`読み込み失敗: ${error.message}`, 'warn');
    setStatus(`読み込みに失敗しました: ${error.message}`, 'warn');
  }
}

function openFolderInputPicker() {
  if (!elements.directoryInput) {
    pushStatusLog('フォルダ入力要素が見つかりません。', 'warn');
    return;
  }
  elements.directoryInput.value = '';
  clearStatusLog('フォルダ入力の選択待ちです。');
  setStatus('フォルダ入力の選択待ちです...', 'neutral');
  pushStatusLog('リポジトリのルートフォルダを選択してください。');
  elements.directoryInput.click();
}

function bindEvents() {
  elements.researchTabButton?.addEventListener('click', () => {
    state.activeTab = 'research';
    renderTabState();
  });
  elements.liveSignalsTabButton?.addEventListener('click', () => {
    state.activeTab = 'live_signals';
    renderTabState();
  });
  elements.pickDirectoryButton?.addEventListener('click', loadFromDirectoryPicker);
  elements.folderInputButton?.addEventListener('click', openFolderInputPicker);
  elements.directoryInput?.addEventListener('click', () => {
    pushStatusLog('フォルダ入力ダイアログを開いています。');
  });
  elements.directoryInput?.addEventListener('input', (event) => {
    const count = event.target.files?.length ?? 0;
    if (count > 0) {
      pushStatusLog(`フォルダ入力で ${count} ファイルを受け取りました。解析を開始します。`);
      setStatus(`フォルダ入力から ${count} ファイルを受け取りました。`, 'neutral');
    }
  });
  elements.directoryInput?.addEventListener('change', async (event) => {
    await loadFromInput(event.target.files);
  });
  elements.strategySearch?.addEventListener('input', () => {
    state.filters.strategySearch = elements.strategySearch.value;
    renderAll();
  });
  elements.strategyTypeFilter?.addEventListener('change', () => {
    state.filters.strategyType = elements.strategyTypeFilter.value;
    renderAll();
  });
  elements.benchmarkOnlyFilter?.addEventListener('change', () => {
    state.filters.benchmarkOnly = elements.benchmarkOnlyFilter.checked;
    renderAll();
  });
  elements.clearComparisonButton?.addEventListener('click', () => {
    state.comparisonStrategyIds = [];
    state.comparisonDateRange = null;
    renderAll();
  });
  elements.dataSearch?.addEventListener('input', () => {
    state.filters.dataSearch = elements.dataSearch.value;
    renderDataFiles();
  });
  elements.dataKindFilter?.addEventListener('change', () => {
    state.filters.dataKind = elements.dataKindFilter.value;
    renderDataFiles();
  });
}

function renderInitialFilters() {
  elements.strategyTypeFilter.innerHTML = '<option value="all">すべて</option>';
  elements.dataKindFilter.innerHTML = '<option value="all">すべて</option>';
}

bindEvents();
renderStaticTexts();
renderInitialFilters();
renderSummaryCards();
renderStatusLog();
