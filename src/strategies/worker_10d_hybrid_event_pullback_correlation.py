from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_10d"
STRATEGY_NAME = "worker_10d"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 6,
    "top_signals_per_day": 6,
    "stop_loss_pct": 0.10,
    "take_profit_pct": 0.30,
}


def _event_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["volatility_20"] < 0.035)
        & (df["range_pct"] > 0.025)
        & (df["volume_ratio_20"] > 1.1)
        & (df["ret_1"] > -0.003)
        & (df["breakout_strength"] > -0.025)
    )


def _pullback_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["ret_20"] > 0.10)
        & (df["rebound_strength"] > 0.12)
        & (df["breakout_strength"] > -0.035)
        & (df["ret_5"] < -0.02)
        & (df["ret_5"] > -0.08)
        & (df["ret_1"] < 0.0)
        & (df["gap_open"] < 0.008)
        & (df["intraday_return"] > 0.0)
        & (df["volume_ratio_20"] > 0.9)
        & (df["volume_ratio_20"] < 2.0)
        & (df["volatility_20"] < 0.04)
    )


def _build_return_matrix(features: pd.DataFrame) -> pd.DataFrame:
    return (
        features[["date", "symbol", "ret_1"]]
        .dropna()
        .pivot(index="date", columns="symbol", values="ret_1")
        .sort_index()
    )


def _select_low_correlation(
    date_group: pd.DataFrame,
    return_matrix: pd.DataFrame,
    lookback_days: int = 20,
    limit: int = 3,
) -> pd.DataFrame:
    if len(date_group) <= limit:
        return date_group

    ordered = date_group.sort_values("score", ascending=False).copy()
    current_date = ordered["date"].iloc[0]
    history = return_matrix.loc[return_matrix.index < current_date].tail(lookback_days)
    if history.empty:
        return ordered.head(limit)

    selected_symbols: list[str] = []
    selected_rows: list[pd.Series] = []

    while len(selected_rows) < limit and not ordered.empty:
        best_idx = None
        best_value = None

        for idx, row in ordered.iterrows():
            symbol = row["symbol"]
            if not selected_symbols:
                candidate_value = float(row["score"])
            else:
                pairwise = []
                for selected_symbol in selected_symbols:
                    if symbol not in history.columns or selected_symbol not in history.columns:
                        continue
                    corr = history[[symbol, selected_symbol]].corr().iloc[0, 1]
                    if pd.notna(corr):
                        pairwise.append(abs(float(corr)))
                avg_corr = sum(pairwise) / len(pairwise) if pairwise else 0.0
                candidate_value = float(row["score"]) - avg_corr * 0.20

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


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir: Path | None = None):
    dates = sorted(features["date"].dropna().unique())
    walk_cfg = config["walkforward"]
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])
    target_column = f"target_up_{holding_days}"

    usable = features.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
    return_matrix = _build_return_matrix(features)
    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []

    if model_dir is not None:
        ensure_dir(model_dir)

    fold_index = 1
    start = train_days
    while start < len(dates):
        train_dates = dates[start - train_days : start]
        test_dates = dates[start : start + test_days]
        if not test_dates:
            break

        train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
        test_df = usable[usable["date"].isin(test_dates)].copy().reset_index(drop=True)
        if train_df.empty or test_df.empty:
            start += step_days
            continue

        logistic = LogisticRegression(max_iter=500, class_weight="balanced")
        random_forest = RandomForestClassifier(
            n_estimators=160,
            max_depth=6,
            min_samples_leaf=20,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        )

        logistic.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))
        random_forest.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))

        logistic_score = logistic.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        forest_score = random_forest.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]

        candidate_mask = _event_filter(test_df) | _pullback_filter(test_df)
        candidate_df = test_df[candidate_mask].copy()
        if candidate_df.empty:
            start += step_days
            fold_index += 1
            continue

        candidate_df["logistic_score"] = logistic_score[candidate_df.index]
        candidate_df["forest_score"] = forest_score[candidate_df.index]
        candidate_df["event_bonus"] = _event_filter(candidate_df).astype(float)
        candidate_df["pullback_bonus"] = _pullback_filter(candidate_df).astype(float)
        candidate_df["rule_score"] = (
            candidate_df["range_pct"] * 4.5
            + candidate_df["volume_ratio_20"] * 0.4
            + candidate_df["ret_20"] * 6.0
            + candidate_df["rebound_strength"] * 3.0
            + candidate_df["intraday_return"] * 12.0
            - candidate_df["ret_5"].abs() * 8.0
            - candidate_df["volatility_20"] * 10.0
        )
        candidate_df["score"] = (
            candidate_df["logistic_score"] * 0.34
            + candidate_df["forest_score"] * 0.36
            + candidate_df["rule_score"] * 0.18
            + candidate_df["event_bonus"] * 0.06
            + candidate_df["pullback_bonus"] * 0.06
        )

        diversified_groups = []
        for _, date_group in candidate_df.groupby("date", sort=False):
            diversified_groups.append(
                _select_low_correlation(date_group, return_matrix, lookback_days=20, limit=3)
            )
        candidate_df = pd.concat(diversified_groups, ignore_index=True)

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(
                    {
                        "logistic": logistic,
                        "random_forest": random_forest,
                        "holding_days": holding_days,
                        "daily_cap": 3,
                        "correlation_filtered": True,
                        "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                        "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                        "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                        "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
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
