from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.core.data_loader import apply_backtest_date_range, load_backtest_config, load_symbol_data
from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_14"
STRATEGY_NAME = "worker_14"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.55,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.12,
}


RELATIVE_FEATURE_COLUMNS = FEATURE_COLUMNS + [
    "benchmark_ret_1",
    "benchmark_ret_5",
    "benchmark_ret_20",
    "benchmark_drawdown_20",
    "benchmark_volatility_20",
    "rel_ret_5",
    "rel_ret_20",
    "rel_strength_20",
]


def _resolve_split_dates(features: pd.DataFrame, cfg: dict) -> tuple[list, list]:
    unique_dates = sorted(features["date"].dropna().unique())
    train_start_date = cfg.get("train_start_date")
    train_end_date = cfg.get("train_end_date")
    test_start_date = cfg.get("test_start_date")
    test_end_date = cfg.get("test_end_date")

    if any([train_start_date, train_end_date, test_start_date, test_end_date]):
        train_dates = [
            date_value
            for date_value in unique_dates
            if (not train_start_date or pd.Timestamp(date_value) >= pd.to_datetime(train_start_date))
            and (not train_end_date or pd.Timestamp(date_value) <= pd.to_datetime(train_end_date))
        ]
        test_dates = [
            date_value
            for date_value in unique_dates
            if (not test_start_date or pd.Timestamp(date_value) >= pd.to_datetime(test_start_date))
            and (not test_end_date or pd.Timestamp(date_value) <= pd.to_datetime(test_end_date))
        ]
        return train_dates, test_dates

    train_days = int(cfg.get("train_days", 252))
    test_days = int(cfg.get("test_days", 63))
    if len(unique_dates) <= train_days:
        return [], []

    split_index = max(train_days, len(unique_dates) - test_days)
    return unique_dates[:split_index], unique_dates[split_index:]


def _build_return_matrix(features: pd.DataFrame) -> pd.DataFrame:
    return (
        features[["date", "symbol", "ret_1"]]
        .dropna()
        .pivot(index="date", columns="symbol", values="ret_1")
        .sort_index()
    )


def _select_diversified(
    date_group: pd.DataFrame,
    return_matrix: pd.DataFrame,
    lookback_days: int = 20,
    limit: int = 2,
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
                candidate_value -= avg_corr * 0.20

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


def _load_benchmark_features(root: Path, benchmark_symbol: str, config: dict) -> pd.DataFrame:
    benchmark = load_symbol_data(root, benchmark_symbol)
    benchmark = apply_backtest_date_range(benchmark, config)
    benchmark = benchmark.sort_values("date").copy()
    if benchmark.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "benchmark_ret_1",
                "benchmark_ret_5",
                "benchmark_ret_20",
                "benchmark_drawdown_20",
                "benchmark_volatility_20",
                "benchmark_close",
                "benchmark_sma20",
                "benchmark_future_return_10",
                "benchmark_future_return_20",
            ]
        )

    benchmark["benchmark_ret_1"] = benchmark["close"].pct_change(1)
    benchmark["benchmark_ret_5"] = benchmark["close"].pct_change(5)
    benchmark["benchmark_ret_20"] = benchmark["close"].pct_change(20)
    rolling_high = benchmark["high"].rolling(20).max().shift(1)
    benchmark["benchmark_drawdown_20"] = (benchmark["close"] / rolling_high) - 1.0
    benchmark["benchmark_volatility_20"] = benchmark["benchmark_ret_1"].rolling(20).std().shift(1)
    benchmark["benchmark_sma20"] = benchmark["close"].rolling(20).mean().shift(1)
    benchmark["benchmark_close"] = benchmark["close"]
    benchmark["benchmark_next_open"] = benchmark["open"].shift(periods=-1)
    for horizon in (10, 20):
        benchmark[f"benchmark_exit_close_{horizon}"] = benchmark["close"].shift(periods=-horizon)
        benchmark[f"benchmark_future_return_{horizon}"] = (
            benchmark[f"benchmark_exit_close_{horizon}"] / benchmark["benchmark_next_open"]
        ) - 1.0

    return benchmark[
        [
            "date",
            "benchmark_ret_1",
            "benchmark_ret_5",
            "benchmark_ret_20",
            "benchmark_drawdown_20",
            "benchmark_volatility_20",
            "benchmark_close",
            "benchmark_sma20",
            "benchmark_future_return_10",
            "benchmark_future_return_20",
        ]
    ].copy()


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

    augmented = features.copy()
    benchmark_features = _load_benchmark_features(root, benchmark_symbol, backtest_cfg)
    augmented = augmented.merge(benchmark_features, on="date", how="left")
    augmented["rel_ret_5"] = augmented["ret_5"] - augmented["benchmark_ret_5"]
    augmented["rel_ret_20"] = augmented["ret_20"] - augmented["benchmark_ret_20"]
    augmented["rel_strength_20"] = augmented["breakout_strength"] - augmented["benchmark_drawdown_20"]
    augmented[f"relative_future_return_{holding_days}"] = (
        augmented[f"future_return_{holding_days}"] - augmented[f"benchmark_future_return_{holding_days}"]
    )
    augmented[f"target_relative_up_{holding_days}"] = (
        augmented[f"relative_future_return_{holding_days}"] > 0.02
    ).astype(float)

    target_column = f"target_relative_up_{holding_days}"
    usable = augmented.dropna(subset=RELATIVE_FEATURE_COLUMNS + [target_column]).copy()
    train_dates, test_dates = _resolve_split_dates(usable, {**walk_cfg, **backtest_cfg})
    if not train_dates or not test_dates:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
    test_df = usable[usable["date"].isin(test_dates)].copy().reset_index(drop=True)
    if train_df.empty or test_df.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    logistic = LogisticRegression(max_iter=600, class_weight="balanced")
    boosting = HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        min_samples_leaf=18,
        random_state=42,
    )
    forest = RandomForestClassifier(
        n_estimators=240,
        max_depth=7,
        min_samples_leaf=14,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    )

    logistic.fit(train_df[RELATIVE_FEATURE_COLUMNS], train_df[target_column].astype(int))
    boosting.fit(train_df[RELATIVE_FEATURE_COLUMNS], train_df[target_column].astype(int))
    forest.fit(train_df[RELATIVE_FEATURE_COLUMNS], train_df[target_column].astype(int))

    regime_ok = (
        (test_df["benchmark_close"] > test_df["benchmark_sma20"])
        & (test_df["benchmark_ret_5"] > -0.02)
        & (test_df["benchmark_drawdown_20"] > -0.08)
        & (test_df["benchmark_volatility_20"] < 0.03)
    )
    candidate_mask = (
        regime_ok
        & (test_df["rel_ret_20"] > 0.03)
        & (test_df["rel_ret_5"] > -0.01)
        & (test_df["rel_strength_20"] > 0.02)
        & (test_df["volume_ratio_20"] > 0.9)
        & (test_df["volatility_20"] < 0.05)
        & (test_df["breakout_strength"] > -0.02)
    )
    candidate_df = test_df[candidate_mask].copy()
    if candidate_df.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    logistic_score = logistic.predict_proba(test_df[RELATIVE_FEATURE_COLUMNS])[:, 1]
    boosting_score = boosting.predict_proba(test_df[RELATIVE_FEATURE_COLUMNS])[:, 1]
    forest_score = forest.predict_proba(test_df[RELATIVE_FEATURE_COLUMNS])[:, 1]

    candidate_df["logistic_score"] = logistic_score[candidate_df.index]
    candidate_df["boosting_score"] = boosting_score[candidate_df.index]
    candidate_df["forest_score"] = forest_score[candidate_df.index]
    candidate_df["rule_score"] = (
        candidate_df["rel_ret_20"] * 40.0
        + candidate_df["rel_ret_5"] * 15.0
        + candidate_df["rel_strength_20"] * 12.0
        + candidate_df["rebound_strength"] * 3.0
        + candidate_df["intraday_return"] * 10.0
    )
    candidate_df["score"] = (
        candidate_df["logistic_score"] * 0.22
        + candidate_df["boosting_score"] * 0.40
        + candidate_df["forest_score"] * 0.24
        + candidate_df["rule_score"] * 0.14
    )

    return_matrix = _build_return_matrix(features)
    diversified = []
    for _, date_group in candidate_df.groupby("date", sort=False):
        diversified.append(_select_diversified(date_group, return_matrix, limit=2))
    candidate_df = pd.concat(diversified, ignore_index=True)
    candidate_df = candidate_df.sort_values(["date", "score"], ascending=[True, False])
    candidate_df = candidate_df.drop_duplicates(subset=["date", "symbol"], keep="first")

    folds = [
        {
            "fold": 1,
            "holding_days": holding_days,
            "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
            "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
            "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
            "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(candidate_df)),
            "model_path": None,
        }
    ]

    if model_dir is not None:
        ensure_dir(model_dir)
        model_path = model_dir / "fold_01.pkl"
        with model_path.open("wb") as handle:
            pickle.dump(
                {
                    "logistic": logistic,
                    "boosting": boosting,
                    "forest": forest,
                    "holding_days": holding_days,
                    "train_start": folds[0]["train_start"],
                    "train_end": folds[0]["train_end"],
                    "test_start": folds[0]["test_start"],
                    "test_end": folds[0]["test_end"],
                    "candidate_count": int(len(candidate_df)),
                    "benchmark_symbol": benchmark_symbol,
                },
                handle,
            )
        folds[0]["model_path"] = str(model_path)

    return candidate_df[["date", "symbol", "score"]], folds
