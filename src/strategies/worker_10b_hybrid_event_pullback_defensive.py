from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_10b"
STRATEGY_NAME = "worker_10b"
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


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir: Path | None = None):
    dates = sorted(features["date"].dropna().unique())
    walk_cfg = config["walkforward"]
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])
    target_column = f"target_up_{holding_days}"

    usable = features.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
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
        candidate_df = (
            candidate_df.sort_values(["date", "score"], ascending=[True, False])
            .groupby("date", group_keys=False)
            .head(3)
        )

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
