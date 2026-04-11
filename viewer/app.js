import { renderLineChart, renderMetricBars } from './charts.js';
import { loadDataFilePreview, loadRepositoryFromDirectoryHandle, loadRepositoryFromFileList } from './data_loader.js';
import { filterDataFiles, filterStrategies, getStrategyTypes } from './filters.js';
import { initState, setRepositoryData } from './state.js';
import { renderTable } from './tables.js';
import { escapeHtml, formatBytes, formatDate, formatNumber, formatPercent, summarizePriceData, toMarkdownHtml } from './utils.js';

const MAX_COMPARISON_STRATEGIES = 10;

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
  strategySearch: document.querySelector('#strategy-search'),
  strategyTypeFilter: document.querySelector('#strategy-type-filter'),
  benchmarkOnlyFilter: document.querySelector('#benchmark-only-filter'),
  strategyTableContainer: document.querySelector('#strategy-table-container'),
  comparisonLimitText: document.querySelector('#comparison-limit-text'),
  equityChart: document.querySelector('#equity-chart'),
  metricChart: document.querySelector('#metric-chart'),
  detailTitle: document.querySelector('#detail-title'),
  detailBadge: document.querySelector('#detail-badge'),
  detailMetrics: document.querySelector('#detail-metrics'),
  detailMeta: document.querySelector('#detail-meta'),
  detailSummary: document.querySelector('#detail-summary'),
  detailEquityChart: document.querySelector('#detail-equity-chart'),
  detailEquityTable: document.querySelector('#detail-equity-table'),
  detailTradesTable: document.querySelector('#detail-trades-table'),
  reportComparison: document.querySelector('#report-comparison'),
  reportFinal: document.querySelector('#report-final'),
  dataSearch: document.querySelector('#data-search'),
  dataKindFilter: document.querySelector('#data-kind-filter'),
  rawFileList: document.querySelector('#raw-file-list'),
  rawPreviewTitle: document.querySelector('#raw-preview-title'),
  rawSummary: document.querySelector('#raw-summary'),
  rawPreviewTable: document.querySelector('#raw-preview-table'),
  issuesContainer: document.querySelector('#issues-container'),
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
  elements.strategyTypeFilter.innerHTML = types
    .map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type === 'all' ? 'すべて' : type)}</option>`)
    .join('');
  elements.strategyTypeFilter.value = state.filters.strategyType;
}

function renderDataKindOptions() {
  const kinds = ['all', ...new Set((state.repositoryData?.dataFiles ?? []).map((file) => file.kind))];
  elements.dataKindFilter.innerHTML = kinds
    .map((kind) => `<option value="${escapeHtml(kind)}">${escapeHtml(kind === 'all' ? 'すべて' : kind)}</option>`)
    .join('');
  elements.dataKindFilter.value = state.filters.dataKind;
}

function renderStrategyTable() {
  const rows = getVisibleStrategies();
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

function renderComparison() {
  const selectedRows = state.repositoryData?.strategies.filter((strategy) => state.comparisonStrategyIds.includes(strategy.id)) ?? [];
  renderLineChart(elements.equityChart, {
    series: selectedRows.map((strategy) => ({
      label: strategy.meta.strategy_name ?? strategy.id,
      points: strategy.equity
        .map((row, index) => ({ x: index, y: Number(row.equity) }))
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

  renderLineChart(elements.detailEquityChart, {
    series: [
      {
        label: strategy.meta.strategy_name ?? strategy.id,
        points: strategy.equity
          .map((row, index) => ({ x: index, y: Number(row.equity) }))
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
}

function renderReports() {
  const reports = state.repositoryData?.reports;
  elements.reportComparison.innerHTML = `<div class="markdown-body">${toMarkdownHtml(reports?.comparisonMarkdown ?? '')}</div>`;
  elements.reportFinal.innerHTML = `<div class="markdown-body">${toMarkdownHtml(reports?.finalSummaryMarkdown ?? '')}</div>`;
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

async function renderAll() {
  renderSummaryCards();
  renderStrategyFilterOptions();
  renderDataKindOptions();
  renderStrategyTable();
  renderComparison();
  renderStrategyDetail();
  renderReports();
  await renderDataFiles();
  renderIssues();
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
  elements.pickDirectoryButton.addEventListener('click', loadFromDirectoryPicker);
  elements.folderInputButton.addEventListener('click', openFolderInputPicker);
  elements.directoryInput.addEventListener('click', () => {
    pushStatusLog('フォルダ入力ダイアログを開いています。');
  });
  elements.directoryInput.addEventListener('input', (event) => {
    const count = event.target.files?.length ?? 0;
    if (count > 0) {
      pushStatusLog(`フォルダ入力で ${count} ファイルを受け取りました。解析を開始します。`);
      setStatus(`フォルダ入力から ${count} ファイルを受け取りました。`, 'neutral');
    }
  });
  elements.directoryInput.addEventListener('change', async (event) => {
    await loadFromInput(event.target.files);
  });
  elements.strategySearch.addEventListener('input', () => {
    state.filters.strategySearch = elements.strategySearch.value;
    renderAll();
  });
  elements.strategyTypeFilter.addEventListener('change', () => {
    state.filters.strategyType = elements.strategyTypeFilter.value;
    renderAll();
  });
  elements.benchmarkOnlyFilter.addEventListener('change', () => {
    state.filters.benchmarkOnly = elements.benchmarkOnlyFilter.checked;
    renderAll();
  });
  elements.dataSearch.addEventListener('input', () => {
    state.filters.dataSearch = elements.dataSearch.value;
    renderDataFiles();
  });
  elements.dataKindFilter.addEventListener('change', () => {
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
