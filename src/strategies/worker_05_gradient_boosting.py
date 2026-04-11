from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingClassifier

from src.core.walkforward import run_walkforward


STRATEGY_ID = "worker_05"
STRATEGY_NAME = "worker_05"
STRATEGY_TYPE = "ml_based"


def generate_signals(features, config: dict, holding_days: int):
    return run_walkforward(
        features,
        lambda: HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, random_state=42),
        config["walkforward"],
        holding_days,
    )
