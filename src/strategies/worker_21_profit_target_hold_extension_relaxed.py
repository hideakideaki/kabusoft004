from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.strategies import worker_20_profit_target_hold_extension as base


STRATEGY_ID = "worker_21"
STRATEGY_NAME = "worker_21_profit_target_hold_extension_relaxed"
STRATEGY_TYPE = "ml_based"

MAX_HOLDING_DAYS = 40
TRAILING_DRAWDOWN_PCT = 0.08
CONTINUATION_DRAWDOWN_PCT = 0.20
CONTINUATION_MIN_RET_5 = -0.20


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    original = (
        base.MAX_HOLDING_DAYS,
        base.TRAILING_DRAWDOWN_PCT,
        base.CONTINUATION_DRAWDOWN_PCT,
        base.CONTINUATION_MIN_RET_5,
    )
    try:
        base.MAX_HOLDING_DAYS = MAX_HOLDING_DAYS
        base.TRAILING_DRAWDOWN_PCT = TRAILING_DRAWDOWN_PCT
        base.CONTINUATION_DRAWDOWN_PCT = CONTINUATION_DRAWDOWN_PCT
        base.CONTINUATION_MIN_RET_5 = CONTINUATION_MIN_RET_5
        return base.generate_signals(features, config, holding_days, model_dir=model_dir)
    finally:
        (
            base.MAX_HOLDING_DAYS,
            base.TRAILING_DRAWDOWN_PCT,
            base.CONTINUATION_DRAWDOWN_PCT,
            base.CONTINUATION_MIN_RET_5,
        ) = original
