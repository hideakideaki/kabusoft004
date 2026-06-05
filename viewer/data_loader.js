import { parseCsv, safeParseJson } from './utils.js';

const REQUIRED_STRATEGY_FILES = ['equity.csv', 'trades.csv', 'metrics.json', 'meta.json', 'result_summary.md'];

function createIssue(scope, path, message) {
  return { scope, path, message };
}

function createProgressReporter(onProgress) {
  return (message, level = 'info') => {
    if (typeof onProgress === 'function') {
      onProgress({ message, level, timestamp: new Date().toISOString() });
    }
  };
}

async function readTextFromReference(ref) {
  if (!ref) {
    return null;
  }
  if (ref.kind === 'handle') {
    const file = await ref.handle.getFile();
    return file.text();
  }
  return ref.file.text();
}

function normalizeInputPaths(files) {
  const items = [];
  for (const file of files) {
    const rawPath = file.webkitRelativePath || file.name;
    const normalized = rawPath.split('/').slice(1).join('/') || file.name;
    items.push([normalized.replaceAll('\\', '/'), { kind: 'file', file }]);
  }
  return new Map(items);
}

async function collectDirectoryEntries(rootHandle) {
  const entries = new Map();
  for await (const [name, handle] of rootHandle.entries()) {
    entries.set(name, handle);
  }
  return entries;
}

async function listFilesInDirectory(handle, prefix) {
  const items = [];
  for await (const [name, entry] of handle.entries()) {
    if (entry.kind === 'file' && !name.startsWith('.')) {
      const file = await entry.getFile();
      items.push({ name, path: `${prefix}/${name}`, size: file.size, ref: { kind: 'handle', handle: entry } });
    }
  }
  return items.sort((left, right) => left.name.localeCompare(right.name, 'ja'));
}

async function loadStrategyFiles(strategyId, fileMap, issues) {
  const strategy = {
    id: strategyId,
    issues: [],
    meta: {},
    metrics: {},
    equity: [],
    trades: [],
    resultSummary: '',
  };

  for (const fileName of REQUIRED_STRATEGY_FILES) {
    const ref = fileMap.get(fileName);
    if (!ref) {
      const issue = createIssue('strategy', `runs/${strategyId}/${fileName}`, '必須ファイルがありません。');
      strategy.issues.push(issue);
      issues.push(issue);
      continue;
    }
    try {
      const text = await readTextFromReference(ref);
      if (fileName.endsWith('.json')) {
        const parsed = safeParseJson(text);
        if (fileName === 'meta.json') {
          strategy.meta = parsed;
        } else {
          strategy.metrics = parsed;
        }
      } else if (fileName.endsWith('.csv')) {
        const parsed = parseCsv(text);
        if (fileName === 'equity.csv') {
          strategy.equity = parsed;
        } else {
          strategy.trades = parsed;
        }
      } else {
        strategy.resultSummary = text;
      }
    } catch (error) {
      const issue = createIssue('strategy', `runs/${strategyId}/${fileName}`, `読み込みに失敗しました: ${error.message}`);
      strategy.issues.push(issue);
      issues.push(issue);
    }
  }

  strategy.meta.strategy_id ??= strategyId;
  strategy.meta.strategy_name ??= strategyId;
  strategy.meta.strategy_type ??= 'unknown';
  strategy.meta.benchmark = Boolean(strategy.meta.benchmark);
  strategy.quality = strategy.issues.length ? 'warn' : 'good';
  return strategy;
}

async function collectFileRefsRecursive(directoryHandle, prefix = '') {
  const refs = new Map();
  for await (const [name, entry] of directoryHandle.entries()) {
    if (name.startsWith('.')) {
      continue;
    }
    const path = prefix ? `${prefix}/${name}` : name;
    if (entry.kind === 'file') {
      refs.set(path, { kind: 'handle', handle: entry });
    } else if (entry.kind === 'directory') {
      const nestedRefs = await collectFileRefsRecursive(entry, path);
      nestedRefs.forEach((ref, nestedPath) => refs.set(nestedPath, ref));
    }
  }
  return refs;
}

function createReportFile(path, text) {
  const name = path.split('/').at(-1);
  const extension = name.includes('.') ? name.split('.').at(-1).toLowerCase() : '';
  const file = {
    path,
    name,
    extension,
    markdown: '',
    rows: [],
    columns: [],
    json: null,
    rawText: text,
  };

  if (extension === 'csv') {
    file.rows = parseCsv(text);
    file.columns = file.rows[0] ? Object.keys(file.rows[0]) : [];
  } else if (extension === 'json') {
    file.json = safeParseJson(text);
  } else if (extension === 'md') {
    file.markdown = text;
  }
  return file;
}

function createArchiveRuns(reportFiles) {
  const archives = new Map();
  reportFiles.forEach((file) => {
    const parts = file.path.split('/');
    if (parts[0] !== 'archive' || parts.length < 3) {
      return;
    }
    const archiveId = parts[1];
    if (!archives.has(archiveId)) {
      archives.set(archiveId, { id: archiveId, files: [], meta: {} });
    }
    const archive = archives.get(archiveId);
    archive.files.push(file);
    if (file.name === 'archive_meta.json' && file.json) {
      archive.meta = file.json;
    }
  });

  return [...archives.values()]
    .map((archive) => ({
      ...archive,
      files: archive.files.sort((left, right) => left.name.localeCompare(right.name, 'ja')),
    }))
    .sort((left, right) => right.id.localeCompare(left.id, 'ja'));
}

async function parseReports(reportRefs, issues) {
  const reports = {
    ranking: [],
    comparisonMarkdown: '',
    finalSummaryMarkdown: '',
    files: [],
    archiveRuns: [],
  };

  for (const [name, ref] of reportRefs.entries()) {
    try {
      const text = await readTextFromReference(ref);
      const reportFile = createReportFile(name, text);
      reports.files.push(reportFile);
      if (name === 'strategy_ranking.csv') {
        reports.ranking = parseCsv(text);
      } else if (name === 'strategy_comparison.md') {
        reports.comparisonMarkdown = text;
      } else if (name === 'final_summary.md') {
        reports.finalSummaryMarkdown = text;
      }
    } catch (error) {
      issues.push(createIssue('report', `reports/${name}`, `読み込みに失敗しました: ${error.message}`));
    }
  }
  reports.files.sort((left, right) => left.path.localeCompare(right.path, 'ja'));
  reports.archiveRuns = createArchiveRuns(reports.files);

  for (const requiredReport of ['strategy_ranking.csv', 'strategy_comparison.md', 'final_summary.md']) {
    if (!reportRefs.has(requiredReport)) {
      issues.push(createIssue('report', `reports/${requiredReport}`, '想定レポートがありません。'));
    }
  }
  return reports;
}

function sortStrategiesBySharpe(strategies) {
  return [...strategies].sort((left, right) => {
    const a = Number(left.metrics?.sharpe);
    const b = Number(right.metrics?.sharpe);
    return (Number.isFinite(b) ? b : -Infinity) - (Number.isFinite(a) ? a : -Infinity);
  });
}

function createComputedRanking(strategies) {
  return sortStrategiesBySharpe(strategies).map((strategy, index) => ({
    rank: index + 1,
    strategy_id: strategy.id,
    strategy_name: strategy.meta.strategy_name,
    strategy_type: strategy.meta.strategy_type,
    benchmark: strategy.meta.benchmark,
    cagr: strategy.metrics.cagr,
    max_drawdown: strategy.metrics.max_drawdown,
    sharpe: strategy.metrics.sharpe,
    win_rate: strategy.metrics.win_rate,
    num_trades: strategy.metrics.num_trades,
  }));
}

function getFileNameFromPath(value) {
  return String(value ?? '').split(/[\\/]/).at(-1) ?? '';
}

async function parseLiveSignalOutputs(outputRefs, issues) {
  const items = [];
  const jsonNames = [...outputRefs.keys()]
    .filter((name) => name.endsWith('.json'))
    .sort((left, right) => right.localeCompare(left, 'ja'));

  for (const jsonName of jsonNames) {
    const ref = outputRefs.get(jsonName);
    if (!ref) {
      continue;
    }
    try {
      const payload = safeParseJson(await readTextFromReference(ref));
      const csvName = getFileNameFromPath(payload.csv_path) || jsonName.replace(/\.json$/i, '.csv');
      const csvRef = outputRefs.get(csvName);
      let csvRows = [];
      if (csvRef) {
        csvRows = parseCsv(await readTextFromReference(csvRef));
      }
      const type = payload.support_strategy_id ? 'meta_consensus' : 'strategy_signal';
      const strategyLabel = payload.strategy_id ?? payload.support_strategy_id ?? 'live_signal';
      items.push({
        id: jsonName,
        name: jsonName,
        type,
        title: type === 'meta_consensus'
          ? `Meta Consensus ${payload.planned_entry_date ?? ''}`.trim()
          : `${strategyLabel} ${payload.planned_entry_date ?? ''}`.trim(),
        jsonPath: `live_signals/outputs/${jsonName}`,
        csvPath: csvRef ? `live_signals/outputs/${csvName}` : null,
        generatedAt: payload.generated_at ?? null,
        signalDate: payload.signal_date ?? null,
        plannedEntryDate: payload.planned_entry_date ?? null,
        strategyId: payload.strategy_id ?? null,
        supportStrategyId: payload.support_strategy_id ?? null,
        mainStrategyIds: payload.main_strategy_ids ?? [],
        entryOffsetDays: payload.entry_offset_days ?? null,
        holdingDays: payload.holding_days ?? null,
        topNPerStrategy: payload.top_n_per_strategy ?? null,
        candidateCount: payload.candidate_count ?? csvRows.length,
        csvRows,
        csvColumns: csvRows[0] ? Object.keys(csvRows[0]) : [],
        payload,
      });
    } catch (error) {
      issues.push(createIssue('live_signals', `live_signals/outputs/${jsonName}`, `隱ｭ縺ｿ霎ｼ縺ｿ縺ｫ螟ｱ謨励＠縺ｾ縺励◆: ${error.message}`));
    }
  }

  items.sort((left, right) => {
    const leftTime = Date.parse(left.generatedAt ?? '');
    const rightTime = Date.parse(right.generatedAt ?? '');
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  });

  return {
    items,
    summary: {
      files: outputRefs.size,
      payloads: items.length,
    },
  };
}

function buildRepositoryData({ strategies, reports, dataFiles, liveSignals, issues }) {
  return {
    strategies: sortStrategiesBySharpe(strategies),
    reports: {
      ...reports,
      ranking: reports.ranking.length ? reports.ranking : createComputedRanking(strategies),
    },
    dataFiles,
    liveSignals,
    issues,
    summary: {
      strategies: strategies.length,
      benchmarkCount: strategies.filter((strategy) => strategy.meta.benchmark).length,
      rawFiles: dataFiles.filter((file) => file.kind === 'raw').length,
      processedFiles: dataFiles.filter((file) => file.kind === 'processed').length,
      liveSignalPayloads: liveSignals?.summary?.payloads ?? 0,
      issueCount: issues.length,
    },
  };
}

export async function loadRepositoryFromDirectoryHandle(rootHandle, options = {}) {
  const progress = createProgressReporter(options.onProgress);
  const issues = [];
  progress('フォルダ構造を確認しています。');
  const topEntries = await collectDirectoryEntries(rootHandle);
  const runsHandle = topEntries.get('runs');
  const reportsHandle = topEntries.get('reports');
  const dataHandle = topEntries.get('data');
  const liveSignalsHandle = topEntries.get('live_signals');

  if (!runsHandle || runsHandle.kind !== 'directory') {
    issues.push(createIssue('root', 'runs/', '`runs/` ディレクトリが見つかりません。'));
    progress('`runs/` が見つかりません。選択したフォルダがリポジトリ直下か確認してください。', 'warn');
  }
  if (!reportsHandle || reportsHandle.kind !== 'directory') {
    issues.push(createIssue('root', 'reports/', '`reports/` ディレクトリが見つかりません。'));
    progress('`reports/` が見つかりません。選択したフォルダがリポジトリ直下か確認してください。', 'warn');
  }
  if (!dataHandle || dataHandle.kind !== 'directory') {
    issues.push(createIssue('root', 'data/', '`data/` ディレクトリが見つかりません。'));
    progress('`data/` が見つかりません。選択したフォルダがリポジトリ直下か確認してください。', 'warn');
  }

  const strategies = [];
  if (runsHandle?.kind === 'directory') {
    progress('`runs/` を走査しています。');
    for await (const [strategyId, entry] of runsHandle.entries()) {
      if (entry.kind !== 'directory') {
        continue;
      }
      progress(`戦略 ${strategyId} を読み込んでいます。`);
      const strategyEntries = new Map();
      for await (const [fileName, fileHandle] of entry.entries()) {
        if (fileHandle.kind === 'file') {
          strategyEntries.set(fileName, { kind: 'handle', handle: fileHandle });
        }
      }
      strategies.push(await loadStrategyFiles(strategyId, strategyEntries, issues));
    }
  }

  const reportRefs = new Map();
  if (reportsHandle?.kind === 'directory') {
    progress('`reports/` を読み込んでいます。');
    const collectedReportRefs = await collectFileRefsRecursive(reportsHandle);
    collectedReportRefs.forEach((ref, name) => reportRefs.set(name, ref));
  }
  const reports = await parseReports(reportRefs, issues);

  const dataFiles = [];
  if (dataHandle?.kind === 'directory') {
    for (const directoryName of ['raw', 'processed', 'manifests']) {
      try {
        progress(`data/${directoryName}/ を走査しています。`);
        const handle = await dataHandle.getDirectoryHandle(directoryName);
        const listed = await listFilesInDirectory(handle, `data/${directoryName}`);
        listed.forEach((item) => dataFiles.push({ ...item, kind: directoryName === 'manifests' ? 'manifest' : directoryName }));
        progress(`data/${directoryName}/ を ${listed.length} 件読み込みました。`, 'good');
      } catch {
        issues.push(createIssue('data', `data/${directoryName}/`, 'ディレクトリが見つからないか空です。'));
        progress(`data/${directoryName}/ は見つからないか空です。`, 'warn');
      }
    }
  }

  let liveSignals = { items: [], summary: { files: 0, payloads: 0 } };
  if (liveSignalsHandle?.kind === 'directory') {
    try {
      progress('`live_signals/outputs/` を読み込み中です。');
      const outputsHandle = await liveSignalsHandle.getDirectoryHandle('outputs');
      const outputRefs = new Map();
      for await (const [name, entry] of outputsHandle.entries()) {
        if (entry.kind === 'file' && !name.startsWith('.')) {
          outputRefs.set(name, { kind: 'handle', handle: entry });
        }
      }
      liveSignals = await parseLiveSignalOutputs(outputRefs, issues);
      progress(`live_signals/outputs/ を ${liveSignals.summary.payloads} 件読み込みました。`, 'good');
    } catch {
      progress('`live_signals/outputs/` は見つからないか空です。', 'warn');
    }
  }

  progress('読み込み処理を集計しています。');
  return buildRepositoryData({ strategies, reports, dataFiles, liveSignals, issues });
}

export async function loadRepositoryFromFileList(files, options = {}) {
  const progress = createProgressReporter(options.onProgress);
  const issues = [];
  progress(`フォルダ入力から ${files.length} ファイルを受け取りました。`);
  const refs = normalizeInputPaths(files);
  const topLevelEntries = [...new Set([...refs.keys()].map((path) => path.split('/')[0]).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ja'));
  progress(`検出したトップレベル: ${topLevelEntries.join(', ') || '(なし)'}`);
  const strategyIds = [...new Set(
    [...refs.keys()]
      .filter((path) => path.startsWith('runs/') && path.split('/').length >= 3)
      .map((path) => path.split('/')[1])
      .filter(Boolean),
  )];

  if (!topLevelEntries.includes('runs')) {
    issues.push(createIssue('root', 'runs/', '`runs/` ディレクトリが見つかりません。'));
    progress('`runs/` が見つかりません。`viewer/` ではなくリポジトリのルートを選択してください。', 'warn');
  }
  if (!topLevelEntries.includes('reports')) {
    issues.push(createIssue('root', 'reports/', '`reports/` ディレクトリが見つかりません。'));
    progress('`reports/` が見つかりません。`viewer/` ではなくリポジトリのルートを選択してください。', 'warn');
  }
  if (!topLevelEntries.includes('data')) {
    issues.push(createIssue('root', 'data/', '`data/` ディレクトリが見つかりません。'));
    progress('`data/` が見つかりません。`viewer/` ではなくリポジトリのルートを選択してください。', 'warn');
  }
  progress(`戦略ディレクトリ候補を ${strategyIds.length} 件検出しました。`);

  const strategies = [];
  for (const strategyId of strategyIds) {
    progress(`戦略 ${strategyId} を読み込んでいます。`);
    const strategyEntries = new Map();
    for (const [path, ref] of refs.entries()) {
      const parts = path.split('/');
      if (parts[0] === 'runs' && parts[1] === strategyId && parts[2]) {
        strategyEntries.set(parts.slice(2).join('/'), ref);
      }
    }
    strategies.push(await loadStrategyFiles(strategyId, strategyEntries, issues));
  }

  const reportRefs = new Map();
  for (const [path, ref] of refs.entries()) {
    if (path.startsWith('reports/')) {
      reportRefs.set(path.split('/').slice(1).join('/'), ref);
    }
  }
  progress(`reports ファイルを ${reportRefs.size} 件検出しました。`);
  const reports = await parseReports(reportRefs, issues);

  const dataFiles = [...refs.entries()]
    .filter(([path]) => path.startsWith('data/') && !path.split('/').at(-1).startsWith('.'))
    .map(([path, ref]) => {
      const parts = path.split('/');
      const kind = parts[1] === 'manifests' ? 'manifest' : parts[1];
      return { path, name: parts.at(-1), size: ref.file.size, kind, ref };
    })
    .sort((left, right) => left.path.localeCompare(right.path, 'ja'));
  progress(`data ファイルを ${dataFiles.length} 件検出しました。`);
  const liveSignalRefs = new Map(
    [...refs.entries()]
      .filter(([path]) => path.startsWith('live_signals/outputs/') && !path.split('/').at(-1).startsWith('.'))
      .map(([path, ref]) => [path.split('/').slice(2).join('/'), ref]),
  );
  const liveSignals = await parseLiveSignalOutputs(liveSignalRefs, issues);
  progress(`live_signals ファイルを ${liveSignals.summary.payloads} 件検出しました。`);
  progress('読み込み処理を集計しています。');

  return buildRepositoryData({ strategies, reports, dataFiles, liveSignals, issues });
}

export async function loadDataFilePreview(file) {
  const text = await readTextFromReference(file.ref);
  if (!file.name.endsWith('.csv')) {
    return { rows: [], rawText: text, columns: [] };
  }
  const rows = parseCsv(text);
  return { rows, rawText: text, columns: rows[0] ? Object.keys(rows[0]) : [] };
}
