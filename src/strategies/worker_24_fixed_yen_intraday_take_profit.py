from __future__ import annotations

import pandas as pd


STRATEGY_ID = "worker_24"
STRATEGY_NAME = "worker_24_fixed_yen_intraday_take_profit"
STRATEGY_TYPE = "rule_based"

DEFAULT_PROFIT_TARGET_YEN = 50.0

BACKTEST_OVERRIDES = {
    "holding_days_tested": [1],
    "max_new_positions_per_day": 10,
    "top_signals_per_day": 20,
}


def _profit_target_yen(config: dict) -> float:
    return float(config["backtest"].get("profit_target_yen", DEFAULT_PROFIT_TARGET_YEN))


def _add_entry_day_outcomes(features: pd.DataFrame) -> pd.DataFrame:
    working = features.sort_values(["symbol", "date"]).copy()
    grouped = working.groupby("symbol", group_keys=False)
    working["entry_day_high"] = grouped["high"].shift(periods=-1)
    working["entry_day_close"] = grouped["close"].shift(periods=-1)
    return working


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir=None,
) -> pd.DataFrame:
    if int(holding_days) != 1:
        raise ValueError("worker_24 supports holding_days=1 only")

    profit_target_yen = _profit_target_yen(config)
    working = _add_entry_day_outcomes(features)
    required_columns = [
        "next_open",
        "entry_date",
        "entry_day_high",
        "entry_day_close",
        "exit_close_1",
        "exit_date_1",
        "liquidity_score",
        "range_pct",
        "volume_ratio_20",
        "volatility_20",
    ]
    signals = working.dropna(subset=required_columns).copy()
    signals["profit_target_price_raw"] = signals["next_open"] + profit_target_yen
    signals["target_hit"] = signals["entry_day_high"] >= signals["profit_target_price_raw"]
    signals["custom_exit_date"] = signals["entry_date"]
    signals["custom_exit_price_raw"] = signals["entry_day_close"]
    signals.loc[signals["target_hit"], "custom_exit_price_raw"] = signals.loc[
        signals["target_hit"], "profit_target_price_raw"
    ]
    signals["custom_exit_reason"] = "day_close"
    signals.loc[signals["target_hit"], "custom_exit_reason"] = "fixed_yen_take_profit"

    target_return_pct = profit_target_yen / signals["next_open"].astype(float)
    signals["score"] = (
        signals["range_pct"].astype(float).clip(lower=0.0) * 100.0
        + signals["volatility_20"].astype(float).clip(lower=0.0) * 50.0
        + signals["volume_ratio_20"].astype(float).clip(lower=0.0)
        + signals["liquidity_score"].astype(float).rank(pct=True)
        - target_return_pct * 5.0
    )

    return signals[
        [
            "date",
            "symbol",
            "score",
            "custom_exit_date",
            "custom_exit_price_raw",
            "custom_exit_reason",
            "profit_target_price_raw",
            "target_hit",
            "entry_day_high",
            "entry_day_close",
        ]
    ].copy()
