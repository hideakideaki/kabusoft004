from __future__ import annotations

import importlib
import pickle
from pathlib import Path

import pandas as pd

from src.core.backtest_engine import run_backtest
from src.core.metrics import calculate_metrics
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_17b"
STRATEGY_NAME = "worker_17b"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.75,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.18,
}

MAIN_CANDIDATE_STRATEGIES = (
    "worker_06",
    "worker_10f",
    "worker_10d",
    "worker_05",
    "worker_01",
    "worker_02",
)
BLENDED_SELECTION_LIMIT = 2
TOP_SIGNALS_PER_DAY = 4
MIN_RECENT_60_SHARPE = -0.25
MIN_LONG_TERM_SHARPE = 0.30
MIN_SELECTION_SCORE = 0.25
SINGLE_SELECTION_SCORE_GAP = 0.75
SINGLE_SELECTION_MIN_SCORE = 2.0
SINGLE_SELECTION_MIN_RECENT_60 = 1.0

STRATEGY_MODULES = {
    "worker_01": "src.strategies.worker_01_breakout_volume",
    "worker_02": "src.strategies.worker_02_mean_reversion_rebound",
    "worker_05": "src.strategies.worker_05_gradient_boosting",
    "worker_06": "src.strategies.worker_06_random_forest",
    "worker_10d": "src.strategies.worker_10d_hybrid_event_pullback_correlation",
    "worker_10f": "src.strategies.worker_10f_hybrid_event_pullback_exposure",
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


def _recent_window_metrics(equity_df: pd.DataFrame, window_days: int) -> dict[str, float]:
    if equity_df.empty:
        return {"return": 0.0, "sharpe": 0.0}
    tail = equity_df.tail(window_days).copy()
    if len(tail) < 2:
        return {"return": 0.0, "sharpe": 0.0}
    tail["daily_return"] = tail["equity"].pct_change().fillna(0.0)
    total_return = float(tail["equity"].iloc[-1] / tail["equity"].iloc[0] - 1.0)
    daily_returns = tail["daily_return"].iloc[1:]
    std = float(daily_returns.std(ddof=0))
    sharpe = 0.0 if std == 0.0 else float(daily_returns.mean() / std * (252 ** 0.5))
    return {"return": total_return, "sharpe": sharpe}


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
            "recent_20d_sharpe": float("-inf"),
            "recent_20d_return": float("-inf"),
            "recent_60d_sharpe": float("-inf"),
            "recent_60d_return": float("-inf"),
        }

    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
        "holding_days": int(holding_days),
    }
    equity_df, trades_df, _ = run_backtest(train_signals, train_features, strategy_backtest_cfg)
    metrics = calculate_metrics(equity_df, trades_df)
    recent_20 = _recent_window_metrics(equity_df, 20)
    recent_60 = _recent_window_metrics(equity_df, 60)
    return {
        "strategy_id": strategy_id,
        **metrics,
        "recent_20d_sharpe": recent_20["sharpe"],
        "recent_20d_return": recent_20["return"],
        "recent_60d_sharpe": recent_60["sharpe"],
        "recent_60d_return": recent_60["return"],
    }


def _selection_score(metrics: dict) -> float:
    return (
        float(metrics["recent_60d_sharpe"]) * 0.50
        + float(metrics["recent_20d_sharpe"]) * 0.30
        + float(metrics["sharpe"]) * 0.20
        + max(float(metrics["recent_20d_return"]), 0.0) * 4.0
    )


def _select_main_strategies(
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    train_dates: list,
) -> tuple[list[dict], str]:
    train_features = _filter_frame_by_dates(features, train_dates)
    metrics_rows = []
    for strategy_id in MAIN_CANDIDATE_STRATEGIES:
        signals = _filter_frame_by_dates(component_signals[strategy_id], train_dates)
        metrics = _component_train_metrics(strategy_id, signals, train_features, config, holding_days)
        metrics["selection_score"] = _selection_score(metrics)
        metrics_rows.append(metrics)

    eligible = [
        row
        for row in metrics_rows
        if row["num_trades"] > 0
        and row["sharpe"] >= MIN_LONG_TERM_SHARPE
        and row["recent_60d_sharpe"] >= MIN_RECENT_60_SHARPE
        and row["selection_score"] >= MIN_SELECTION_SCORE
    ]
    if not eligible:
        return [], "cash"

    eligible.sort(
        key=lambda row: (
            float(row["selection_score"]),
            float(row["recent_60d_sharpe"]),
            float(row["sharpe"]),
        ),
        reverse=True,
    )
    if len(eligible) == 1:
        return eligible[:1], "single"

    top_one = eligible[0]
    top_two = eligible[1]
    score_gap = float(top_one["selection_score"]) - float(top_two["selection_score"])
    if (
        score_gap >= SINGLE_SELECTION_SCORE_GAP
        and float(top_one["selection_score"]) >= SINGLE_SELECTION_MIN_SCORE
        and float(top_one["recent_60d_sharpe"]) >= SINGLE_SELECTION_MIN_RECENT_60
    ):
        return [top_one], "single"

    return eligible[:BLENDED_SELECTION_LIMIT], "blended"


def _aggregate_regime_switch_for_dates(
    selected_main: list[dict],
    component_signals: dict[str, pd.DataFrame],
    test_dates: list,
) -> pd.DataFrame:
    if not selected_main:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    weighted_rows: list[pd.DataFrame] = []
    for row in selected_main:
        strategy_id = row["strategy_id"]
        weight = max(float(row["selection_score"]), 0.05)
        signals = _filter_frame_by_dates(component_signals[strategy_id], test_dates)
        if signals.empty:
            continue
        ranked = _rank_component_signals(signals)
        ranked["main_strategy_id"] = strategy_id
        ranked["main_weight"] = weight
        weighted_rows.append(
            ranked[
                [
                    "date",
                    "symbol",
                    "component_rank",
                    "component_normalized_score",
                    "main_strategy_id",
                    "main_weight",
                ]
            ]
        )

    if not weighted_rows:
        return pd.DataFrame(columns=["date", "symbol", "score"])

    combined = pd.concat(weighted_rows, ignore_index=True)
    grouped_rows = []
    for (date_value, symbol), group in combined.groupby(["date", "symbol"], sort=False):
        support_count = int(len(group))
        weighted_support = float((group["component_normalized_score"] * group["main_weight"]).sum())
        avg_rank = float(group["component_rank"].mean())
        final_score = weighted_support + support_count * 0.35 - avg_rank * 0.05
        grouped_rows.append(
            {
                "date": date_value,
                "symbol": symbol,
                "score": final_score,
                "support_count": support_count,
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
        for strategy_id in MAIN_CANDIDATE_STRATEGIES
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

        selected_main, selection_mode = _select_main_strategies(
            component_signals,
            features,
            config,
            holding_days,
            train_dates,
        )
        consensus = _aggregate_regime_switch_for_dates(selected_main, component_signals, test_dates)
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
                        "selection_mode": selection_mode,
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
                "selection_mode": selection_mode,
                "selected_main": selected_main,
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
