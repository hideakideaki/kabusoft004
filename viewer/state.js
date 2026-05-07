export function initState() {
  return {
    sourceLabel: '未読み込み',
    repositoryData: null,
    filters: {
      strategySearch: '',
      strategyType: 'all',
      benchmarkOnly: false,
      dataSearch: '',
      dataKind: 'all',
      comparisonXAxisMode: 'date',
    },
    selectedStrategyId: null,
    comparisonStrategyIds: [],
    selectedDataFilePath: null,
  };
}

export function setRepositoryData(state, repositoryData, sourceLabel) {
  state.repositoryData = repositoryData;
  state.sourceLabel = sourceLabel;
  state.selectedStrategyId = repositoryData.strategies[0]?.id ?? null;
  state.comparisonStrategyIds = repositoryData.strategies.slice(0, 2).map((strategy) => strategy.id);
  state.selectedDataFilePath = repositoryData.dataFiles[0]?.path ?? null;
}
