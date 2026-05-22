from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.core.data_loader import apply_backtest_date_range, load_backtest_config, load_symbol_data
from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_15b"
STRATEGY_NAME = "worker_15b"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 1,
    "capital_deployment_ratio": 0.55,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.18,
}

DAILY_SELECTION_LIMIT = 1

RELATIVE_STABLE_FEATURE_COLUMNS = FEATURE_COLUMNS + [
    "market_breadth_20",
    "market_breadth_5",
    "market_median_ret_5",
    "market_median_drawdown_20",
    "up_day_ratio_20",
    "downside_vol_20",
    "range_stability_20",
    "distance_from_sma20",
    "sma_trend_20_60",
    "trend_efficiency_20",
    "close_position_20",
    "benchmark_ret_5",
    "benchmark_ret_20",
    "benchmark_drawdown_20",
    "benchmark_volatility_20",
    "rel_ret_5",
    "rel_ret_20",
    "rel_strength_20",
]


def _within_range(date_value, start_date: str | None, end_date: str | None) -> bool:
    ts = pd.Timestamp(date_value)
    if start_date and ts < pd.to_datetime(start_date):
        return False
    if end_date and ts > pd.to_datetime(end_date):
        return False
    return True


def _build_return_matrix(features: pd.DataFrame) -> pd.DataFrame:
    return (
        features[["date", "symbol", "ret_1"]]
        .dropna()
        .pivot(index="date", columns="symbol", values="ret_1")
        .sort_index()
    )


def _load_benchmark_features(root: Path, benchmark_symbol: str, config: dict) -> pd.DataFrame:
    benchmark = load_symbol_data(root, benchmark_symbol)
    benchmark = apply_backtest_date_range(benchmark, config)
    benchmark = benchmark.sort_values("date").copy()
    if benchmark.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "benchmark_ret_5",
                "benchmark_ret_20",
                "benchmark_drawdown_20",
                "benchmark_volatility_20",
                "benchmark_future_return_10",
                "benchmark_future_return_20",
            ]
        )

    benchmark["benchmark_ret_5"] = benchmark["close"].pct_change(5)
    benchmark["benchmark_ret_20"] = benchmark["close"].pct_change(20)
    rolling_high = benchmark["high"].rolling(20).max().shift(1)
    benchmark["benchmark_drawdown_20"] = (benchmark["close"] / rolling_high) - 1.0
    benchmark["benchmark_volatility_20"] = benchmark["close"].pct_change().rolling(20).std().shift(1)
    benchmark["benchmark_next_open"] = benchmark["open"].shift(periods=-1)

    for horizon in (10, 20):
        benchmark[f"benchmark_exit_close_{horizon}"] = benchmark["close"].shift(periods=-horizon)
        benchmark[f"benchmark_future_return_{horizon}"] = (
            benchmark[f"benchmark_exit_close_{horizon}"] / benchmark["benchmark_next_open"]
        ) - 1.0

    return benchmark[
        [
            "date",
            "benchmark_ret_5",
            "benchmark_ret_20",
            "benchmark_drawdown_20",
            "benchmark_volatility_20",
            "benchmark_future_return_10",
            "benchmark_future_return_20",
        ]
    ].copy()


def _add_market_state_features(features: pd.DataFrame) -> pd.DataFrame:
    augmented = features.copy()
    grouped = augmented.groupby("symbol", group_keys=False)
    augmented["up_day_ratio_20"] = grouped["ret_1"].transform(
        lambda series: series.gt(0).rolling(20).mean().shift(1)
    )
    augmented["downside_vol_20"] = grouped["ret_1"].transform(
        lambda series: series.clip(upper=0).rolling(20).std().shift(1)
    )
    augmented["range_stability_20"] = grouped["range_pct"].transform(
        lambda series: series.rolling(20).mean().shift(1)
    )
    augmented["sma20"] = grouped["close"].transform(
        lambda series: series.rolling(20).mean().shift(1)
    )
    augmented["sma60"] = grouped["close"].transform(
        lambda series: series.rolling(60).mean().shift(1)
    )
    augmented["distance_from_sma20"] = (augmented["close"] / augmented["sma20"]) - 1.0
    augmented["sma_trend_20_60"] = (augmented["sma20"] / augmented["sma60"]) - 1.0
    augmented["trend_path_20"] = grouped["ret_1"].transform(
        lambda series: series.abs().rolling(20).sum().shift(1)
    )
    augmented["trend_efficiency_20"] = augmented["ret_20"].abs() / augmented["trend_path_20"]
    rolling_high = grouped["high"].transform(lambda series: series.rolling(20).max().shift(1))
    rolling_low = grouped["low"].transform(lambda series: series.rolling(20).min().shift(1))
    price_span = (rolling_high - rolling_low).replace(0, pd.NA)
    augmented["close_position_20"] = (augmented["close"] - rolling_low) / price_span
    market_state = (
        augmented.groupby("date")
        .agg(
            market_breadth_20=("ret_20", lambda s: float((s > 0).mean())),
            market_breadth_5=("ret_5", lambda s: float((s > 0).mean())),
            market_median_ret_5=("ret_5", "median"),
            market_median_drawdown_20=("drawdown_20", "median"),
        )
        .reset_index()
    )
    return augmented.merge(market_state, on="date", how="left")


def _stable_relative_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["market_breadth_20"] > 0.42)
        & (df["market_breadth_5"] > 0.36)
        & (df["market_median_ret_5"] > -0.02)
        & (df["market_median_drawdown_20"] > -0.11)
        & (df["ret_20"] > 0.05)
        & (df["ret_20"] < 0.26)
        & (df["rel_ret_20"] > 0.02)
        & (df["rel_ret_5"] > -0.015)
        & (df["rel_strength_20"] > 0.015)
        & (df["ret_5"] > -0.04)
        & (df["ret_5"] < 0.035)
        & (df["volatility_20"] > 0.008)
        & (df["volatility_20"] < 0.04)
        & (df["downside_vol_20"] < 0.022)
        & (df["drawdown_20"] > -0.085)
        & (df["breakout_strength"] > -0.03)
        & (df["breakout_strength"] < 0.06)
        & (df["rebound_strength"] > 0.05)
        & (df["range_pct"] < 0.042)
        & (df["range_stability_20"] < 0.040)
        & (df["gap_open"].abs() < 0.02)
        & (df["intraday_return"] > -0.012)
        & (df["intraday_return"] < 0.032)
        & (df["volume_ratio_20"] > 0.80)
        & (df["volume_ratio_20"] < 2.20)
        & (df["up_day_ratio_20"] > 0.50)
        & (df["trend_efficiency_20"] > 0.17)
        & (df["distance_from_sma20"] > -0.02)
        & (df["distance_from_sma20"] < 0.09)
        & (df["sma_trend_20_60"] > 0.0)
        & (df["close_position_20"] > 0.46)
        & (df["close_position_20"] < 0.96)
    )


def _select_diversified(
    date_group: pd.DataFrame,
    return_matrix: pd.DataFrame,
    lookback_days: int = 20,
    limit: int = 1,
) -> pd.DataFrame:
    if len(date_group) <= limit:
        return date_group.sort_values("score", ascending=False)

    ordered = date_group.sort_values("score", ascending=False).copy()
    current_date = ordered["date"].iloc[0]
    history = return_matrix.loc[return_matrix.index < current_date].tail(lookback_days)
    selected_symbols: list[str] = []
    selected_rows: list[pd.Series] = []

    while len(selected_rows) < limit and not ordered.empty:
        best_idx = None
        best_value = None
        for idx, row in ordered.iterrows():
            candidate_value = float(row["score"])
            if selected_symbols and not history.empty:
                penalties = []
                for selected_symbol in selected_symbols:
                    if row["symbol"] not in history.columns or selected_symbol not in history.columns:
                        continue
                    corr = history[[row["symbol"], selected_symbol]].corr().iloc[0, 1]
                    if pd.notna(corr):
                        penalties.append(abs(float(corr)))
                avg_corr = sum(penalties) / len(penalties) if penalties else 0.0
                candidate_value -= avg_corr * 0.15

            if best_value is None or candidate_value > best_value:
                best_value = candidate_value
                best_idx = idx

        if best_idx is None:
            break

        chosen = ordered.loc[best_idx]
        selected_rows.append(chosen)
        selected_symbols.append(chosen["symbol"])
        ordered = ordered.drop(best_idx)

    return pd.DataFrame(selected_rows)


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
):
    backtest_cfg = config["backtest"]
    walk_cfg = config["walkforward"]
    root = Path(backtest_cfg["_project_root"])
    benchmark_symbol = str(load_backtest_config(root).get("benchmark_symbol", "^N225"))

    augmented = _add_market_state_features(features)
    benchmark_features = _load_benchmark_features(root, benchmark_symbol, backtest_cfg)
    augmented = augmented.merge(benchmark_features, on="date", how="left")
    augmented["rel_ret_5"] = augmented["ret_5"] - augmented["benchmark_ret_5"]
    augmented["rel_ret_20"] = augmented["ret_20"] - augmented["benchmark_ret_20"]
    augmented["rel_strength_20"] = augmented["breakout_strength"] - augmented["benchmark_drawdown_20"]

    target_column = f"target_relative_stable_{holding_days}"
    relative_threshold = 0.01 if holding_days <= 10 else 0.015
    augmented[target_column] = (
        (augmented[f"future_return_{holding_days}"] - augmented[f"benchmark_future_return_{holding_days}"])
        > relative_threshold
    ).astype(float)

    usable = augmented.dropna(subset=RELATIVE_STABLE_FEATURE_COLUMNS + [target_column]).copy()
    dates = sorted(usable["date"].dropna().unique())
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])
    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []
    return_matrix = _build_return_matrix(features)

    if model_dir is not None:
        ensure_dir(model_dir)

    start = train_days
    fold_index = 1
    while start < len(dates):
        train_dates = dates[start - train_days : start]
        test_dates = dates[start : start + test_days]
        if not test_dates:
            break
        if not _within_range(train_dates[0], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(train_dates[-1], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[0], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[-1], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue

        train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
        test_df = usable[usable["date"].isin(test_dates)].copy().reset_index(drop=True)
        if train_df.empty or test_df.empty:
            start += step_days
            continue

        logistic = LogisticRegression(max_iter=600, class_weight="balanced")
        boosting = HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.04,
            min_samples_leaf=30,
            random_state=42,
        )
        forest = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=22,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        )

        logistic.fit(train_df[RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))
        boosting.fit(train_df[RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))
        forest.fit(train_df[RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))

        candidate_df = test_df[_stable_relative_filter(test_df)].copy()
        if candidate_df.empty:
            start += step_days
            fold_index += 1
            continue

        logistic_score = logistic.predict_proba(test_df[RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]
        boosting_score = boosting.predict_proba(test_df[RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]
        forest_score = forest.predict_proba(test_df[RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]

        candidate_df["logistic_score"] = logistic_score[candidate_df.index]
        candidate_df["boosting_score"] = boosting_score[candidate_df.index]
        candidate_df["forest_score"] = forest_score[candidate_df.index]
        candidate_df["stability_score"] = (
            candidate_df["trend_efficiency_20"] * 10.0
            + candidate_df["up_day_ratio_20"] * 2.6
            + candidate_df["sma_trend_20_60"] * 8.0
            + candidate_df["ret_20"] * 7.0
            - candidate_df["downside_vol_20"] * 18.0
            - candidate_df["volatility_20"] * 14.0
            - candidate_df["range_stability_20"] * 8.0
            - (candidate_df["volume_ratio_20"] - 1.05).abs() * 1.0
            - (candidate_df["close_position_20"] - 0.72).abs() * 1.3
            - candidate_df["gap_open"].abs() * 5.0
        )
        candidate_df["relative_score"] = (
            candidate_df["rel_ret_20"] * 30.0
            + candidate_df["rel_ret_5"] * 10.0
            + candidate_df["rel_strength_20"] * 12.0
            + candidate_df["trend_efficiency_20"] * 3.0
            - candidate_df["benchmark_volatility_20"] * 4.0
        )
        candidate_df["score"] = (
            candidate_df["logistic_score"] * 0.10
            + candidate_df["boosting_score"] * 0.22
            + candidate_df["forest_score"] * 0.12
            + candidate_df["stability_score"] * 0.22
            + candidate_df["relative_score"] * 0.34
        )

        diversified = []
        for _, date_group in candidate_df.groupby("date", sort=False):
            diversified.append(_select_diversified(date_group, return_matrix, limit=DAILY_SELECTION_LIMIT))
        candidate_df = pd.concat(diversified, ignore_index=True)
        candidate_df = candidate_df.sort_values(["date", "score"], ascending=[True, False])
        candidate_df = candidate_df.drop_duplicates(subset=["date", "symbol"], keep="first")

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            ensure_dir(model_path.parent)
            with model_path.open("wb") as handle:
                pickle.dump(
                    {
                        "logistic": logistic,
                        "boosting": boosting,
                        "forest": forest,
                        "holding_days": holding_days,
                        "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                        "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                        "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                        "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                        "candidate_count": int(len(candidate_df)),
                        "benchmark_symbol": benchmark_symbol,
                    },
                    handle,
                )

        predictions.append(candidate_df[["date", "symbol", "score"]].copy())
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_df)),
                "test_rows": int(len(candidate_df)),
                "model_path": str(model_path) if model_path is not None else None,
            }
        )
        start += step_days
        fold_index += 1

    if not predictions:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    combined = pd.concat(predictions, ignore_index=True)
    combined = combined.sort_values(["date", "score"], ascending=[True, False])
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="first")
    return combined, folds
