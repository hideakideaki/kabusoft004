from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_19"
STRATEGY_NAME = "worker_19_profit_target_classifier"
STRATEGY_TYPE = "ml_based"

TARGET_RETURN_THRESHOLD = 0.03
MIN_POSITIVE_SAMPLES = 20
MIN_NEGATIVE_SAMPLES = 20


def _within_range(date_value, start_date: str | None, end_date: str | None) -> bool:
    ts = pd.Timestamp(date_value)
    if start_date and ts < pd.to_datetime(start_date):
        return False
    if end_date and ts > pd.to_datetime(end_date):
        return False
    return True


def _build_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_leaf_nodes=15,
        max_iter=120,
        learning_rate=0.04,
        l2_regularization=0.02,
        random_state=42,
    )


def _add_profit_target_label(features: pd.DataFrame, holding_days: int) -> pd.DataFrame:
    labeled = features.sort_values(["symbol", "date"]).copy()
    target_column = f"profit_target_{holding_days}"
    target_return_column = f"profit_target_return_{holding_days}"
    future_max_high_column = f"future_max_high_{holding_days}"

    grouped = labeled.groupby("symbol", group_keys=False)
    labeled[future_max_high_column] = grouped["high"].transform(
        lambda series: series.shift(periods=-1)
        .iloc[::-1]
        .rolling(holding_days, min_periods=holding_days)
        .max()
        .iloc[::-1]
    )
    labeled[target_return_column] = (
        labeled[future_max_high_column] / labeled["next_open"]
    ) - 1.0
    labeled[target_column] = (
        labeled[target_return_column] >= TARGET_RETURN_THRESHOLD
    ).astype(int)
    return labeled


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    walk_cfg = config["walkforward"]
    dates = sorted(features["date"].dropna().unique())
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])
    target_column = f"profit_target_{holding_days}"
    target_return_column = f"profit_target_return_{holding_days}"

    labeled = _add_profit_target_label(features, holding_days)
    train_usable = labeled.dropna(subset=FEATURE_COLUMNS + [target_return_column]).copy()
    score_usable = features.dropna(subset=FEATURE_COLUMNS).copy()

    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []

    if model_dir is not None:
        ensure_dir(model_dir)

    start = train_days
    fold_index = 1
    while start < len(dates):
        train_dates = dates[start - train_days : start]
        test_dates = dates[start : start + test_days]
        if len(test_dates) == 0:
            break
        if not _within_range(train_dates[0], walk_cfg.get("train_start_date"), walk_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(train_dates[-1], walk_cfg.get("train_start_date"), walk_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[0], walk_cfg.get("test_start_date"), walk_cfg.get("test_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[-1], walk_cfg.get("test_start_date"), walk_cfg.get("test_end_date")):
            start += step_days
            continue

        train_df = train_usable[train_usable["date"].isin(train_dates)].copy()
        test_df = score_usable[score_usable["date"].isin(test_dates)].copy()
        positive_count = int(train_df[target_column].sum())
        negative_count = int(len(train_df) - positive_count)
        if (
            train_df.empty
            or test_df.empty
            or positive_count < MIN_POSITIVE_SAMPLES
            or negative_count < MIN_NEGATIVE_SAMPLES
        ):
            start += step_days
            continue

        model = _build_model()
        model.fit(train_df[FEATURE_COLUMNS], train_df[target_column])

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)

        fold = test_df[["date", "symbol"]].copy()
        fold["score"] = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        predictions.append(fold)
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "target_return_threshold": TARGET_RETURN_THRESHOLD,
                "target_definition": "max high from entry date through planned exit date over next_open",
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_df)),
                "test_rows": int(len(test_df)),
                "positive_rows": positive_count,
                "negative_rows": negative_count,
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
