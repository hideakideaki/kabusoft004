from __future__ import annotations

from sklearn.ensemble import RandomForestClassifier

from src.core.walkforward import run_walkforward


STRATEGY_ID = "worker_06"
STRATEGY_NAME = "worker_06"
STRATEGY_TYPE = "ml_based"


def generate_signals(features, config: dict, holding_days: int, model_dir=None):
    return run_walkforward(
        features,
        lambda: RandomForestClassifier(
            n_estimators=120,
            max_depth=6,
            min_samples_leaf=20,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        ),
        config["walkforward"],
        holding_days,
        model_dir=model_dir,
    )
