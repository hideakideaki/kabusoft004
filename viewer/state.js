export function initState() {
  return {
    sourceLabel: '未読み込み',
    repositoryData: null,
    activeTab: 'research',
    filters: {
      strategySearch: '',
      strategyType: 'all',
      benchmarkOnly: false,
      dataSearch: '',
      dataKind: 'all',
    },
    selectedStrategyId: null,
    comparisonStrategyIds: [],
    comparisonDateRange: null,
    selectedDataFilePath: null,
    selectedLiveSignalId: null,
    selectedArchiveRunId: null,
    selectedArchiveReportPath: null,
  };
}

export function setRepositoryData(state, repositoryData, sourceLabel) {
  state.repositoryData = repositoryData;
  state.sourceLabel = sourceLabel;
  state.selectedStrategyId = repositoryData.strategies[0]?.id ?? null;
  state.comparisonStrategyIds = repositoryData.strategies.slice(0, 2).map((strategy) => strategy.id);
  state.comparisonDateRange = null;
  state.selectedDataFilePath = repositoryData.dataFiles[0]?.path ?? null;
  state.selectedLiveSignalId = repositoryData.liveSignals?.items?.[0]?.id ?? null;
  state.selectedArchiveRunId = repositoryData.reports.archiveRuns[0]?.id ?? null;
  state.selectedArchiveReportPath = null;
}
