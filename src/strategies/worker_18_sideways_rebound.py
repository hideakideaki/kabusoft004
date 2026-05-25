from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.data_loader import apply_backtest_date_range, load_backtest_config, load_symbol_data


STRATEGY_ID = "worker_18"
STRATEGY_NAME = "worker_18"
STRATEGY_TYPE = "rule_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 1,
    "capital_deployment_ratio": 0.55,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.12,
}


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
            ]
        )

    benchmark["benchmark_ret_5"] = benchmark["close"].pct_change(5)
    benchmark["benchmark_ret_20"] = benchmark["close"].pct_change(20)
    rolling_high = benchmark["high"].rolling(20).max().shift(1)
    benchmark["benchmark_drawdown_20"] = (benchmark["close"] / rolling_high) - 1.0
    benchmark["benchmark_volatility_20"] = benchmark["close"].pct_change().rolling(20).std().shift(1)
    return benchmark[
        [
            "date",
            "benchmark_ret_5",
            "benchmark_ret_20",
            "benchmark_drawdown_20",
            "benchmark_volatility_20",
        ]
    ].copy()


def _add_market_state_features(features: pd.DataFrame) -> pd.DataFrame:
    augmented = features.copy()
    grouped = augmented.groupby("symbol", group_keys=False)
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


def generate_signals(features: pd.DataFrame, config: dict, holding_days: int, model_dir=None) -> pd.DataFrame:
    root = Path(config["backtest"]["_project_root"])
    benchmark_symbol = str(load_backtest_config(root).get("benchmark_symbol", "^N225"))

    augmented = _add_market_state_features(features)
    benchmark_features = _load_benchmark_features(root, benchmark_symbol, config["backtest"])
    augmented = augmented.merge(benchmark_features, on="date", how="left")
    augmented["rel_ret_5"] = augmented["ret_5"] - augmented["benchmark_ret_5"]
    augmented["rel_ret_20"] = augmented["ret_20"] - augmented["benchmark_ret_20"]

    regime_mask = (
        (augmented["market_breadth_20"] >= 0.25)
        & (augmented["market_breadth_20"] <= 0.52)
        & (augmented["market_breadth_5"] >= 0.20)
        & (augmented["market_breadth_5"] <= 0.55)
        & (augmented["market_median_ret_5"] <= 0.01)
        & (augmented["market_median_drawdown_20"] <= -0.01)
        & (augmented["market_median_drawdown_20"] >= -0.14)
        & (augmented["benchmark_ret_20"] >= -0.12)
        & (augmented["benchmark_ret_20"] <= 0.03)
        & (augmented["benchmark_ret_5"] >= -0.04)
        & (augmented["benchmark_ret_5"] <= 0.01)
        & (augmented["benchmark_drawdown_20"] <= -0.02)
        & (augmented["benchmark_drawdown_20"] >= -0.18)
        & (augmented["benchmark_volatility_20"] <= 0.035)
    )

    stock_mask = (
        (augmented["ret_5"] <= -0.03)
        & (augmented["ret_5"] >= -0.09)
        & (augmented["drawdown_20"] <= -0.05)
        & (augmented["drawdown_20"] >= -0.18)
        & (augmented["intraday_return"] >= 0.018)
        & (augmented["ret_1"] >= -0.015)
        & (augmented["gap_open"] >= -0.025)
        & (augmented["gap_open"] <= 0.005)
        & (augmented["volume_ratio_20"] >= 1.00)
        & (augmented["volume_ratio_20"] <= 2.50)
        & (augmented["volatility_20"] >= 0.012)
        & (augmented["volatility_20"] <= 0.050)
        & (augmented["close_position_20"] <= 0.48)
        & (augmented["rebound_strength"] >= 0.06)
        & (augmented["rel_ret_5"] <= -0.005)
        & (augmented["rel_ret_5"] >= -0.05)
        & (augmented["rel_ret_20"] >= -0.12)
        & augmented["next_open"].notna()
        & augmented[f"exit_close_{holding_days}"].notna()
    )

    signals = augmented[regime_mask & stock_mask][
        [
            "date",
            "symbol",
            "drawdown_20",
            "intraday_return",
            "volume_ratio_20",
            "close_position_20",
            "rel_ret_5",
            "benchmark_drawdown_20",
        ]
    ].copy()
    if signals.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    signals["score"] = (
        (-signals["drawdown_20"]) * 6.0
        + signals["intraday_return"] * 120.0
        + (-signals["rel_ret_5"]) * 10.0
        + (0.55 - signals["close_position_20"]).clip(lower=0.0) * 3.0
        + (-signals["benchmark_drawdown_20"]).clip(lower=0.0) * 1.5
        + signals["volume_ratio_20"] * 0.3
    )
    return signals[["date", "symbol", "score"]]
