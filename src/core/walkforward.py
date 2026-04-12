from __future__ import annotations

import pickle
from pathlib import Path
from typing import Callable

import pandas as pd

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


def run_walkforward(
    data: pd.DataFrame,
    model_factory: Callable[[], object],
    cfg: dict,
    holding_days: int,
    model_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    dates = sorted(data["date"].dropna().unique())
    train_days = int(cfg["train_days"])
    test_days = int(cfg["test_days"])
    step_days = int(cfg["step_days"])
    target_column = f"target_up_{holding_days}"

    usable = data.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
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

        train_df = usable[usable["date"].isin(train_dates)]
        test_df = usable[usable["date"].isin(test_dates)]
        if train_df.empty or test_df.empty:
            start += step_days
            continue

        model = model_factory()
        model.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)

        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        else:
            scores = model.decision_function(test_df[FEATURE_COLUMNS])

        fold = test_df[["date", "symbol"]].copy()
        fold["score"] = scores
        predictions.append(fold)
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_df)),
                "test_rows": int(len(test_df)),
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
