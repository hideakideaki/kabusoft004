from __future__ import annotations

from typing import Callable

import pandas as pd

from src.core.feature_engineering import FEATURE_COLUMNS


def run_walkforward(data: pd.DataFrame, model_factory: Callable[[], object], cfg: dict, holding_days: int) -> pd.DataFrame:
    dates = sorted(data["date"].dropna().unique())
    train_days = int(cfg["train_days"])
    test_days = int(cfg["test_days"])
    step_days = int(cfg["step_days"])
    target_column = f"target_up_{holding_days}"

    usable = data.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
    predictions: list[pd.DataFrame] = []

    start = train_days
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

        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        else:
            scores = model.decision_function(test_df[FEATURE_COLUMNS])

        fold = test_df[["date", "symbol"]].copy()
        fold["score"] = scores
        predictions.append(fold)
        start += step_days

    if not predictions:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    combined = pd.concat(predictions, ignore_index=True)
    combined = combined.sort_values(["date", "score"], ascending=[True, False])
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="first")
    return combined
