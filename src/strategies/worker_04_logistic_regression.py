from __future__ import annotations

from sklearn.linear_model import LogisticRegression

from src.core.walkforward import run_walkforward


STRATEGY_ID = "worker_04"
STRATEGY_NAME = "worker_04"
STRATEGY_TYPE = "ml_based"


def generate_signals(features, config: dict, holding_days: int, model_dir=None):
    return run_walkforward(
        features,
        lambda: LogisticRegression(max_iter=500, class_weight="balanced"),
        config["walkforward"],
        holding_days,
        model_dir=model_dir,
    )
