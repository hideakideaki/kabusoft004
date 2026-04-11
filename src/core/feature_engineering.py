from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "ret_1",
    "ret_5",
    "ret_20",
    "gap_open",
    "intraday_return",
    "range_pct",
    "volume_ratio_20",
    "volatility_20",
    "breakout_strength",
    "drawdown_20",
    "rebound_strength",
]


def build_features(df: pd.DataFrame, window_main: int = 20) -> pd.DataFrame:
    working = df.sort_values(["symbol", "date"]).copy()
    grouped = working.groupby("symbol", group_keys=False)

    working["ret_1"] = grouped["close"].pct_change(1)
    working["ret_5"] = grouped["close"].pct_change(5)
    working["ret_20"] = grouped["close"].pct_change(window_main)
    working["gap_open"] = (working["open"] / grouped["close"].shift(1)) - 1.0
    working["intraday_return"] = (working["close"] / working["open"]) - 1.0
    working["range_pct"] = (working["high"] - working["low"]) / working["close"]

    working["avg_volume_20"] = grouped["volume"].transform(
        lambda series: series.rolling(window_main).mean().shift(1)
    )
    working["volume_ratio_20"] = working["volume"] / working["avg_volume_20"]

    working["volatility_20"] = grouped["ret_1"].transform(
        lambda series: series.rolling(window_main).std().shift(1)
    )
    rolling_high = grouped["high"].transform(
        lambda series: series.rolling(window_main).max().shift(1)
    )
    rolling_low = grouped["low"].transform(
        lambda series: series.rolling(window_main).min().shift(1)
    )
    working["breakout_strength"] = (working["close"] / rolling_high) - 1.0
    working["drawdown_20"] = (working["close"] / rolling_high) - 1.0
    working["rebound_strength"] = (working["close"] / rolling_low) - 1.0

    working["next_open"] = grouped["open"].shift(-1)
    working["entry_date"] = grouped["date"].shift(-1)

    for horizon in (10, 20):
        working[f"exit_close_{horizon}"] = grouped["close"].shift(-horizon)
        working[f"exit_date_{horizon}"] = grouped["date"].shift(-horizon)
        working[f"future_return_{horizon}"] = (
            working[f"exit_close_{horizon}"] / working["next_open"]
        ) - 1.0
        working[f"target_up_{horizon}"] = (
            working[f"future_return_{horizon}"] > 0
        ).astype(float)

    working["liquidity_score"] = working["close"] * working["volume"]

    working.replace([np.inf, -np.inf], np.nan, inplace=True)
    return working
