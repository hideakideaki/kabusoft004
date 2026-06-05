from __future__ import annotations

import importlib
import json
import pickle
from pathlib import Path

import pandas as pd
from sklearn.linear_model import RidgeCV

from src.core.backtest_engine import run_backtest
from src.core.metrics import calculate_metrics
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_23"
STRATEGY_NAME = "worker_23_calibrated_consensus"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 8,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.70,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.18,
}

MAIN_COMPONENT_STRATEGIES = (
    "worker_04",
    "worker_06",
    "worker_08",
    "worker_10e",
    "worker_10f",
    "worker_16",
    "worker_17e",
    "worker_19",
    "worker_20",
    "worker_21",
    "worker_22",
)
STABLE_SUPPORT_STRATEGY = "worker_15b"
COMPONENT_TOP_N_PER_DAY = 80
OUTPUT_TOP_N_PER_DAY = 8
MIN_TRAIN_ROWS = 300
TARGET_CLIP_LOWER = -0.25
TARGET_CLIP_UPPER = 0.50

CONSENSUS_FEATURE_COLUMNS = [
    "weighted_support",
    "support_count",
    "stable_confirmation",
    "avg_signal_rank",
    "best_signal_rank",
    "rank_strength",
    "top3_support_count",
    "top10_support_count",
    "profit_target_support_count",
    "profit_target_weighted_support",
    "core_ml_support_count",
    "has_worker_19",
    "has_worker_20",
    "has_worker_21",
    "has_worker_22",
    "has_worker_10e",
    "has_worker_10f",
    "has_worker_17e",
]
PROFIT_TARGET_COMPONENTS = {"worker_19", "worker_20", "worker_21", "worker_22"}
CORE_ML_COMPONENTS = {"worker_04", "worker_06", "worker_08", "worker_10e", "worker_10f", "worker_17e"}

STRATEGY_MODULES = {
    "worker_04": "src.strategies.worker_04_logistic_regression",
    "worker_06": "src.strategies.worker_06_random_forest",
    "worker_08": "src.strategies.worker_08_hybrid_event_ml_compact",
    "worker_10e": "src.strategies.worker_10e_hybrid_event_pullback_blend",
    "worker_10f": "src.strategies.worker_10f_hybrid_event_pullback_exposure",
    "worker_15b": "src.strategies.worker_15b_stable_compounder_relative",
    "worker_16": "src.strategies.worker_16_meta_consensus_backtest",
    "worker_17e": "src.strategies.worker_17e_regime_switch_supervised_core",
    "worker_19": "src.strategies.worker_19_profit_target_classifier",
    "worker_20": "src.strategies.worker_20_profit_target_hold_extension",
    "worker_21": "src.strategies.worker_21_profit_target_hold_extension_relaxed",
    "worker_22": "src.strategies.worker_22_profit_target_hold_extension_balanced",
}


def _load_strategy_module(strategy_id: str):
    return importlib.import_module(STRATEGY_MODULES[strategy_id])


def _within_range(date_value, start_date: str | None, end_date: str | None) -> bool:
    ts = pd.Timestamp(date_value)
    if start_date and ts < pd.to_datetime(start_date):
        return False
    if end_date and ts > pd.to_datetime(end_date):
        return False
    return True


def _filter_frame_by_dates(frame: pd.DataFrame, date_values: list) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame[frame["date"].isin(date_values)].copy().reset_index(drop=True)


def _resolve_component_signals(
    strategy_id: str,
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
) -> pd.DataFrame:
    root = Path(config["backtest"]["_project_root"])
    candidates_path = root / "runs" / strategy_id / "candidates.csv"
    if not candidates_path.exists():
        return pd.DataFrame(columns=["date", "symbol", "score"])
    signals = pd.read_csv(candidates_path)
    signals = signals[["date", "symbol", "score"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    signals["symbol"] = signals["symbol"].astype(str)
    signals = signals[signals["date"].isin(features["date"].unique())].copy()
    if signals.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"])
    signals = signals.sort_values(["date", "score"], ascending=[True, False])
    signals["component_rank"] = signals.groupby("date")["score"].rank(
        method="first",
        ascending=False,
    )
    return signals[signals["component_rank"] <= COMPONENT_TOP_N_PER_DAY].reset_index(drop=True)


def _component_run_metrics(strategy_id: str, config: dict) -> dict:
    root = Path(config["backtest"]["_project_root"])
    metrics_path = root / "runs" / strategy_id / "metrics.json"
    if not metrics_path.exists():
        return {}
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def _window_metrics(equity_df: pd.DataFrame, window_days: int) -> dict[str, float]:
    if equity_df.empty:
        return {"sharpe": 0.0, "return": 0.0}
    tail = equity_df.tail(window_days).copy()
    if len(tail) < 2:
        return {"sharpe": 0.0, "return": 0.0}
    tail["daily_return"] = tail["equity"].pct_change().fillna(0.0)
    daily_returns = tail["daily_return"].iloc[1:]
    std = float(daily_returns.std(ddof=0))
    sharpe = 0.0 if std == 0.0 else float(daily_returns.mean() / std * (252**0.5))
    total_return = float(tail["equity"].iloc[-1] / tail["equity"].iloc[0] - 1.0)
    return {"sharpe": sharpe, "return": total_return}


def _component_weight(
    strategy_id: str,
    signals: pd.DataFrame,
    train_features: pd.DataFrame,
    config: dict,
    holding_days: int,
) -> float:
    if signals.empty or train_features.empty:
        return 0.05
    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
        "holding_days": int(holding_days),
    }
    equity_df, trades_df, _ = run_backtest(signals, train_features, strategy_backtest_cfg)
    metrics = calculate_metrics(equity_df, trades_df)
    recent_60 = _window_metrics(equity_df, 60)
    weight = (
        max(float(metrics["sharpe"]), 0.0)
        + max(float(recent_60["sharpe"]), 0.0) * 0.50
        + max(float(metrics["cagr"]), 0.0) * 0.25
    )
    return max(weight, 0.05)


def _component_weights(
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    train_dates: list,
) -> dict[str, float]:
    weights = {}
    for strategy_id in MAIN_COMPONENT_STRATEGIES:
        metrics = _component_run_metrics(strategy_id, config)
        weight = (
            max(float(metrics.get("sharpe", 0.0)), 0.0)
            + max(float(metrics.get("cagr", 0.0)), 0.0) * 0.25
        )
        weights[strategy_id] = max(weight, 0.05)
    return weights


def _aggregate_consensus_features(
    component_signals: dict[str, pd.DataFrame],
    component_weights: dict[str, float],
    date_values: list | None,
) -> pd.DataFrame:
    weighted_rows = []
    for strategy_id in MAIN_COMPONENT_STRATEGIES:
        signals = (
            component_signals[strategy_id].copy()
            if date_values is None
            else _filter_frame_by_dates(component_signals[strategy_id], date_values)
        )
        if signals.empty:
            continue
        working = signals.copy()
        working["component_strategy"] = strategy_id
        working["component_weight"] = float(component_weights.get(strategy_id, 0.05))
        weighted_rows.append(working)

    if not weighted_rows:
        return pd.DataFrame(columns=["date", "symbol", *CONSENSUS_FEATURE_COLUMNS])

    combined = pd.concat(weighted_rows, ignore_index=True)
    stable_signals = _filter_frame_by_dates(
        component_signals[STABLE_SUPPORT_STRATEGY],
        date_values,
    ) if date_values is not None else component_signals[STABLE_SUPPORT_STRATEGY].copy()
    stable_pairs = (
        set(zip(stable_signals["date"], stable_signals["symbol"]))
        if not stable_signals.empty
        else set()
    )

    rows = []
    for (date_value, symbol), group in combined.groupby(["date", "symbol"], sort=False):
        rows.append(
            {
                "date": date_value,
                "symbol": symbol,
                "weighted_support": float(group["component_weight"].sum()),
                "support_count": float(len(group)),
                "stable_confirmation": 1.0 if (date_value, symbol) in stable_pairs else 0.0,
                "avg_signal_rank": float(group["component_rank"].mean()),
                "best_signal_rank": float(group["component_rank"].min()),
                "rank_strength": float((1.0 / group["component_rank"].clip(lower=1.0)).sum()),
                "top3_support_count": float((group["component_rank"] <= 3).sum()),
                "top10_support_count": float((group["component_rank"] <= 10).sum()),
                "profit_target_support_count": float(group["component_strategy"].isin(PROFIT_TARGET_COMPONENTS).sum()),
                "profit_target_weighted_support": float(
                    group.loc[group["component_strategy"].isin(PROFIT_TARGET_COMPONENTS), "component_weight"].sum()
                ),
                "core_ml_support_count": float(group["component_strategy"].isin(CORE_ML_COMPONENTS).sum()),
                "has_worker_19": float((group["component_strategy"] == "worker_19").any()),
                "has_worker_20": float((group["component_strategy"] == "worker_20").any()),
                "has_worker_21": float((group["component_strategy"] == "worker_21").any()),
                "has_worker_22": float((group["component_strategy"] == "worker_22").any()),
                "has_worker_10e": float((group["component_strategy"] == "worker_10e").any()),
                "has_worker_10f": float((group["component_strategy"] == "worker_10f").any()),
                "has_worker_17e": float((group["component_strategy"] == "worker_17e").any()),
                "support_strategies": "|".join(group["component_strategy"].tolist()),
            }
        )
    return pd.DataFrame(rows)


def _attach_target(
    consensus: pd.DataFrame,
    features: pd.DataFrame,
    holding_days: int,
) -> pd.DataFrame:
    target_columns = [
        "date",
        "symbol",
        f"future_return_{holding_days}",
        f"exit_date_{holding_days}",
    ]
    labeled = consensus.merge(features[target_columns], on=["date", "symbol"], how="left")
    labeled = labeled.dropna(subset=[f"future_return_{holding_days}", f"exit_date_{holding_days}"])
    labeled["target_return"] = labeled[f"future_return_{holding_days}"].clip(
        lower=TARGET_CLIP_LOWER,
        upper=TARGET_CLIP_UPPER,
    )
    labeled[f"exit_date_{holding_days}"] = pd.to_datetime(labeled[f"exit_date_{holding_days}"])
    return labeled


def _fit_calibration_model(train_df: pd.DataFrame):
    if len(train_df) < MIN_TRAIN_ROWS or train_df["target_return"].nunique() < 20:
        return None
    model = RidgeCV(alphas=(0.01, 0.05, 0.10, 0.30, 1.0, 3.0, 10.0, 30.0))
    model.fit(train_df[CONSENSUS_FEATURE_COLUMNS], train_df["target_return"])
    return model


def _heuristic_score(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["weighted_support"] * 1.0
        + frame["support_count"] * 0.50
        + frame["stable_confirmation"] * 0.75
        - frame["avg_signal_rank"] * 0.05
        + frame["top3_support_count"] * 0.10
        + frame["profit_target_support_count"] * 0.10
    )


def _score_consensus(model, frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    if model is None:
        scored["score"] = _heuristic_score(scored)
        return scored
    scored["score"] = model.predict(scored[CONSENSUS_FEATURE_COLUMNS])
    return scored


def _coefficient_payload(model) -> dict:
    if model is None:
        return {
            "mode": "heuristic_fallback",
            "intercept": 0.0,
            "coefficients": {
                "weighted_support": 1.0,
                "support_count": 0.50,
                "stable_confirmation": 0.75,
                "avg_signal_rank": -0.05,
            },
        }
    return {
        "mode": "ridge_regression",
        "alpha": float(model.alpha_),
        "intercept": float(model.intercept_),
        "coefficients": {
            column: float(coef)
            for column, coef in zip(CONSENSUS_FEATURE_COLUMNS, model.coef_)
        },
    }


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
):
    backtest_cfg = config["backtest"]
    walk_cfg = config["walkforward"]
    unique_dates = sorted(features["date"].dropna().unique())
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])

    component_ids = (*MAIN_COMPONENT_STRATEGIES, STABLE_SUPPORT_STRATEGY)
    component_signals = {
        strategy_id: _resolve_component_signals(strategy_id, features, config, holding_days)
        for strategy_id in component_ids
    }
    component_weights = _component_weights(
        component_signals,
        features,
        config,
        holding_days,
        unique_dates,
    )
    all_consensus = _aggregate_consensus_features(
        component_signals,
        component_weights,
        None,
    )

    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []
    if model_dir is not None:
        ensure_dir(model_dir)

    start = train_days
    fold_index = 1
    while start < len(unique_dates):
        train_dates = unique_dates[start - train_days : start]
        test_dates = unique_dates[start : start + test_days]
        if not test_dates:
            break
        if not _within_range(train_dates[0], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(train_dates[-1], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[0], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[-1], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue

        train_consensus = _filter_frame_by_dates(all_consensus, train_dates)
        train_labeled = _attach_target(train_consensus, features, holding_days)
        train_end = pd.Timestamp(train_dates[-1])
        train_labeled = train_labeled[
            train_labeled[f"exit_date_{holding_days}"] <= train_end
        ].copy()
        test_consensus = _filter_frame_by_dates(all_consensus, test_dates)
        if test_consensus.empty:
            start += step_days
            fold_index += 1
            continue

        model = _fit_calibration_model(train_labeled)
        scored = _score_consensus(model, test_consensus)
        scored = scored.sort_values(["date", "score"], ascending=[True, False]).copy()
        scored["meta_rank"] = scored.groupby("date")["score"].rank(
            method="first",
            ascending=False,
        )
        scored = scored[scored["meta_rank"] <= OUTPUT_TOP_N_PER_DAY].copy()

        model_path = None
        coefficient_payload = _coefficient_payload(model)
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(
                    {
                        "holding_days": holding_days,
                        "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                        "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                        "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                        "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                        "train_rows": int(len(train_labeled)),
                        "test_rows": int(len(scored)),
                        "component_weights": component_weights,
                        "calibration": coefficient_payload,
                    },
                    handle,
                )

        predictions.append(scored[["date", "symbol", "score"]])
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_labeled)),
                "test_rows": int(len(scored)),
                "model_path": str(model_path) if model_path is not None else None,
                "calibration": coefficient_payload,
                "component_weights": component_weights,
                "target": f"future_return_{holding_days}",
                "target_clip": [TARGET_CLIP_LOWER, TARGET_CLIP_UPPER],
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
