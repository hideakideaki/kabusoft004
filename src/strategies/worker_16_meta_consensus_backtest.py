from __future__ import annotations

import importlib
import pickle
from pathlib import Path

import pandas as pd

from src.core.backtest_engine import run_backtest
from src.core.metrics import calculate_metrics
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_16"
STRATEGY_NAME = "worker_16"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.70,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.18,
}

MAIN_CANDIDATE_STRATEGIES = (
    "worker_10d",
    "worker_05",
    "worker_01",
    "worker_02",
)
SUPPORT_STRATEGY_ID = "worker_15b"
MAIN_SELECTION_LIMIT = 2
TOP_SIGNALS_PER_DAY = 4
MIN_TRAIN_SHARPE = 0.10

STRATEGY_MODULES = {
    "worker_01": "src.strategies.worker_01_breakout_volume",
    "worker_02": "src.strategies.worker_02_mean_reversion_rebound",
    "worker_05": "src.strategies.worker_05_gradient_boosting",
    "worker_10d": "src.strategies.worker_10d_hybrid_event_pullback_correlation",
    "worker_15b": "src.strategies.worker_15b_stable_compounder_relative",
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
    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
    }
    strategy_cfg = {
        "backtest": strategy_backtest_cfg,
        "walkforward": config["walkforward"],
    }
    generated = module.generate_signals(features, strategy_cfg, holding_days, model_dir=None)
    if isinstance(generated, tuple):
        signals, _ = generated
    else:
        signals = generated
    if signals is None or signals.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"])
    return signals.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)


def _rank_component_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    ranked = signals.sort_values(["date", "score"], ascending=[True, False]).copy()
    ranked["component_rank"] = ranked.groupby("date")["score"].rank(method="first", ascending=False)
    group_size = ranked.groupby("date")["score"].transform("count")
    ranked["component_normalized_score"] = 1.0 - ((ranked["component_rank"] - 1.0) / group_size.clip(lower=1.0))
    return ranked


def _component_train_metrics(
    strategy_id: str,
    train_signals: pd.DataFrame,
    train_features: pd.DataFrame,
    config: dict,
    holding_days: int,
) -> dict:
    if train_signals.empty or train_features.empty:
        return {
            "strategy_id": strategy_id,
            "sharpe": float("-inf"),
            "cagr": float("-inf"),
            "max_drawdown": float("-inf"),
            "num_trades": 0,
        }

    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
        "holding_days": int(holding_days),
    }
    equity_df, trades_df, _ = run_backtest(train_signals, train_features, strategy_backtest_cfg)
    metrics = calculate_metrics(equity_df, trades_df)
    return {"strategy_id": strategy_id, **metrics}


def _select_main_strategies(
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    train_dates: list,
) -> list[dict]:
    train_features = _filter_frame_by_dates(features, train_dates)
    metrics_rows = []
    for strategy_id in MAIN_CANDIDATE_STRATEGIES:
        signals = _filter_frame_by_dates(component_signals[strategy_id], train_dates)
        metrics = _component_train_metrics(strategy_id, signals, train_features, config, holding_days)
        metrics_rows.append(metrics)

    eligible = [
        row for row in metrics_rows
        if row["num_trades"] > 0 and row["sharpe"] >= MIN_TRAIN_SHARPE and row["cagr"] > 0.0
    ]
    if not eligible:
        eligible = [row for row in metrics_rows if row["num_trades"] > 0]

    eligible.sort(
        key=lambda row: (
            float(row["sharpe"]),
            float(row["cagr"]),
            -abs(float(row["max_drawdown"])),
        ),
        reverse=True,
    )
    return eligible[:MAIN_SELECTION_LIMIT]


def _aggregate_consensus_for_dates(
    selected_main: list[dict],
    component_signals: dict[str, pd.DataFrame],
    test_dates: list,
) -> pd.DataFrame:
    if not selected_main:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    weighted_rows: list[pd.DataFrame] = []
    for row in selected_main:
        strategy_id = row["strategy_id"]
        weight = max(float(row["sharpe"]), 0.0) + max(float(row["cagr"]), 0.0)
        if weight <= 0.0:
            weight = 0.10
        signals = _filter_frame_by_dates(component_signals[strategy_id], test_dates)
        if signals.empty:
            continue
        ranked = _rank_component_signals(signals)
        ranked["main_strategy_id"] = strategy_id
        ranked["main_weight"] = weight
        weighted_rows.append(ranked[["date", "symbol", "component_rank", "component_normalized_score", "main_strategy_id", "main_weight"]])

    if not weighted_rows:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    combined = pd.concat(weighted_rows, ignore_index=True)
    support_signals = _filter_frame_by_dates(component_signals[SUPPORT_STRATEGY_ID], test_dates)
    support_pairs = set(zip(support_signals["date"], support_signals["symbol"])) if not support_signals.empty else set()

    grouped_rows = []
    for (date_value, symbol), group in combined.groupby(["date", "symbol"], sort=False):
        support_count = int(len(group))
        weighted_support = float((group["component_normalized_score"] * group["main_weight"]).sum())
        avg_rank = float(group["component_rank"].mean())
        stable_confirmation = (date_value, symbol) in support_pairs
        stable_bonus = 0.75 if stable_confirmation else 0.0
        final_score = weighted_support + support_count * 0.50 + stable_bonus - avg_rank * 0.05
        grouped_rows.append(
            {
                "date": date_value,
                "symbol": symbol,
                "score": final_score,
                "support_count": support_count,
                "stable_confirmation": stable_confirmation,
                "main_strategies": "|".join(group["main_strategy_id"].tolist()),
            }
        )

    consensus = pd.DataFrame(grouped_rows)
    consensus = consensus.sort_values(["date", "score"], ascending=[True, False]).copy()
    consensus["meta_rank"] = consensus.groupby("date")["score"].rank(method="first", ascending=False)
    consensus = consensus[consensus["meta_rank"] <= TOP_SIGNALS_PER_DAY].copy()
    return consensus[["date", "symbol", "score"]].reset_index(drop=True)


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

    component_signals = {
        strategy_id: _resolve_component_signals(strategy_id, features, config, holding_days)
        for strategy_id in (*MAIN_CANDIDATE_STRATEGIES, SUPPORT_STRATEGY_ID)
    }

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

        selected_main = _select_main_strategies(
            component_signals,
            features,
            config,
            holding_days,
            train_dates,
        )
        consensus = _aggregate_consensus_for_dates(selected_main, component_signals, test_dates)
        if consensus.empty:
            start += step_days
            fold_index += 1
            continue

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            ensure_dir(model_path.parent)
            with model_path.open("wb") as handle:
                pickle.dump(
                    {
                        "holding_days": holding_days,
                        "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                        "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                        "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                        "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                        "selected_main": selected_main,
                        "support_strategy_id": SUPPORT_STRATEGY_ID,
                        "candidate_count": int(len(consensus)),
                    },
                    handle,
                )

        predictions.append(consensus)
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_dates)),
                "test_rows": int(len(consensus)),
                "model_path": str(model_path) if model_path is not None else None,
                "selected_main": selected_main,
                "support_strategy_id": SUPPORT_STRATEGY_ID,
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
