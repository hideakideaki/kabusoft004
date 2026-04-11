export function getStrategyTypes(strategies) {
  return ['all', ...new Set(strategies.map((strategy) => strategy.meta?.strategy_type).filter(Boolean))];
}

export function filterStrategies(strategies, filters) {
  const query = filters.strategySearch.trim().toLowerCase();
  return strategies.filter((strategy) => {
    if (filters.strategyType !== 'all' && strategy.meta?.strategy_type !== filters.strategyType) {
      return false;
    }
    if (filters.benchmarkOnly && !strategy.meta?.benchmark) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [strategy.id, strategy.meta?.strategy_name, strategy.meta?.strategy_type]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });
}

export function filterDataFiles(dataFiles, filters) {
  const query = filters.dataSearch.trim().toLowerCase();
  return dataFiles.filter((file) => {
    if (filters.dataKind !== 'all' && file.kind !== filters.dataKind) {
      return false;
    }
    if (!query) {
      return true;
    }
    return file.path.toLowerCase().includes(query) || file.name.toLowerCase().includes(query);
  });
}
