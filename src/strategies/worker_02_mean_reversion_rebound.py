from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_02"
STRATEGY_NAME = "worker_02"
STRATEGY_TYPE = "rule_based"


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir=None) -> pd.DataFrame:
    signals = features[
        (features["ret_5"] < -0.05)
        & (features["intraday_return"] > 0.01)
        & (features["volume_ratio_20"] > 1.0)
        & (features["drawdown_20"] < -0.06)
        & features["next_open"].notna()
        & features[f"exit_close_{holding_days}"].notna()
    ][["date", "symbol", "drawdown_20", "intraday_return", "volume_ratio_20"]].copy()
    signals["score"] = (
        (-signals["drawdown_20"]) * 10.0
        + signals["intraday_return"] * 100.0
        + signals["volume_ratio_20"]
    )
    return signals[["date", "symbol", "score"]]
