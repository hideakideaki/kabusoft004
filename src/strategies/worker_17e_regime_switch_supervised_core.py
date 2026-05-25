from __future__ import annotations

import importlib
import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from src.core.backtest_engine import run_backtest
from src.core.metrics import calculate_metrics
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_17e"
STRATEGY_NAME = "worker_17e"
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
    "worker_01",
)
TRAIN_WINDOW_OPTIONS = (60, 90, 120)
BLENDED_SELECTION_LIMIT = 2
TOP_SIGNALS_PER_DAY = 4
MIN_RECENT_60_SHARPE = 0.00
MIN_LONG_TERM_SHARPE = 0.35
MIN_SIGNAL_DAYS_RATIO = 0.10
MIN_TRAIN_TRADES = 20
MAX_TRAIN_DRAWDOWN = -0.28
MIN_HISTORY_SAMPLES = 24
MIN_META_SCORE_FOR_DEPLOY = 0.75
SINGLE_META_SCORE_GAP = 0.30

STRATEGY_MODULES = {
    "worker_01": "src.strategies.worker_01_breakout_volume",
    "worker_06": "src.strategies.worker_06_random_forest",
    "worker_10d": "src.strategies.worker_10d_hybrid_event_pullback_correlation",
    "worker_10f": "src.strategies.worker_10f_hybrid_event_pullback_exposure",
}

META_FEATURE_COLUMNS = [
    "train_window_days",
    "sharpe",
    "cagr",
    "max_drawdown",
    "win_rate",
    "num_trades",
    "recent_20d_sharpe",
    "recent_20d_return",
    "recent_20d_max_drawdown",
    "recent_60d_sharpe",
    "recent_60d_return",
    "recent_60d_max_drawdown",
    "signal_days_ratio",
    "trades_per_day",
    "selection_score",
    "is_worker_01",
    "is_worker_06",
    "is_worker_10d",
    "is_worker_10f",
]


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


def _window_metrics(equity_df: pd.DataFrame, window_days: int) -> dict[str, float]:
    if equity_df.empty:
        return {"return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
    tail = equity_df.tail(window_days).copy()
    if len(tail) < 2:
        return {"return": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}
    tail["daily_return"] = tail["equity"].pct_change().fillna(0.0)
    total_return = float(tail["equity"].iloc[-1] / tail["equity"].iloc[0] - 1.0)
    daily_returns = tail["daily_return"].iloc[1:]
    std = float(daily_returns.std(ddof=0))
    sharpe = 0.0 if std == 0.0 else float(daily_returns.mean() / std * (252**0.5))
    running_max = tail["equity"].cummax()
    max_drawdown = float((tail["equity"] / running_max - 1.0).min())
    return {"return": total_return, "sharpe": sharpe, "max_drawdown": max_drawdown}


def _selection_score(metrics: dict) -> float:
    return (
        float(metrics["recent_60d_sharpe"]) * 0.40
        + float(metrics["recent_20d_sharpe"]) * 0.15
        + float(metrics["sharpe"]) * 0.20
        + max(float(metrics["recent_20d_return"]), 0.0) * 2.0
        + max(float(metrics["recent_60d_return"]), 0.0) * 2.5
        + float(metrics["win_rate"]) * 1.0
        + float(metrics["signal_days_ratio"]) * 1.5
        + float(metrics["trades_per_day"]) * 0.3
        + float(metrics["max_drawdown"]) * 0.8
        + float(metrics["recent_60d_max_drawdown"]) * 0.8
    )


def _component_train_metrics(
    strategy_id: str,
    train_signals: pd.DataFrame,
    train_features: pd.DataFrame,
    config: dict,
    holding_days: int,
    train_days: int,
) -> dict:
    if train_signals.empty or train_features.empty:
        return {
            "strategy_id": strategy_id,
            "sharpe": float("-inf"),
            "cagr": float("-inf"),
            "max_drawdown": float("-inf"),
            "win_rate": 0.0,
            "num_trades": 0,
            "recent_20d_sharpe": float("-inf"),
            "recent_20d_return": float("-inf"),
            "recent_20d_max_drawdown": float("-inf"),
            "recent_60d_sharpe": float("-inf"),
            "recent_60d_return": float("-inf"),
            "recent_60d_max_drawdown": float("-inf"),
            "signal_days": 0,
            "signal_days_ratio": 0.0,
            "trades_per_day": 0.0,
        }

    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
        "holding_days": int(holding_days),
    }
    equity_df, trades_df, _ = run_backtest(train_signals, train_features, strategy_backtest_cfg)
    metrics = calculate_metrics(equity_df, trades_df)
    recent_20 = _window_metrics(equity_df, 20)
    recent_60 = _window_metrics(equity_df, 60)
    signal_days = int(train_signals["date"].nunique()) if not train_signals.empty else 0
    return {
        "strategy_id": strategy_id,
        **metrics,
        "recent_20d_sharpe": recent_20["sharpe"],
        "recent_20d_return": recent_20["return"],
        "recent_20d_max_drawdown": recent_20["max_drawdown"],
        "recent_60d_sharpe": recent_60["sharpe"],
        "recent_60d_return": recent_60["return"],
        "recent_60d_max_drawdown": recent_60["max_drawdown"],
        "signal_days": signal_days,
        "signal_days_ratio": signal_days / float(train_days),
        "trades_per_day": float(metrics["num_trades"]) / float(train_days),
    }


def _realized_fold_score(metrics: dict) -> float:
    return (
        float(metrics["sharpe"]) * 0.65
        + max(float(metrics["cagr"]), 0.0) * 1.10
        + float(metrics["win_rate"]) * 0.25
        + float(metrics["max_drawdown"]) * 0.80
    )


def _component_test_metrics(
    strategy_id: str,
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    test_dates: list,
) -> dict:
    test_features = _filter_frame_by_dates(features, test_dates)
    test_signals = _filter_frame_by_dates(component_signals[strategy_id], test_dates)
    if test_features.empty or test_signals.empty:
        return {
            "strategy_id": strategy_id,
            "cagr": float("-inf"),
            "max_drawdown": float("-inf"),
            "sharpe": float("-inf"),
            "win_rate": 0.0,
            "num_trades": 0,
            "realized_score": float("-inf"),
        }
    module = _load_strategy_module(strategy_id)
    strategy_backtest_cfg = {
        **config["backtest"],
        **getattr(module, "BACKTEST_OVERRIDES", {}),
        "holding_days": int(holding_days),
    }
    equity_df, trades_df, _ = run_backtest(test_signals, test_features, strategy_backtest_cfg)
    metrics = calculate_metrics(equity_df, trades_df)
    return {
        "strategy_id": strategy_id,
        **metrics,
        "realized_score": _realized_fold_score(metrics),
    }


def _build_meta_features(metrics: dict) -> dict:
    base = {
        "train_window_days": float(metrics["train_window_days"]),
        "sharpe": float(metrics["sharpe"]),
        "cagr": float(metrics["cagr"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "win_rate": float(metrics["win_rate"]),
        "num_trades": float(metrics["num_trades"]),
        "recent_20d_sharpe": float(metrics["recent_20d_sharpe"]),
        "recent_20d_return": float(metrics["recent_20d_return"]),
        "recent_20d_max_drawdown": float(metrics["recent_20d_max_drawdown"]),
        "recent_60d_sharpe": float(metrics["recent_60d_sharpe"]),
        "recent_60d_return": float(metrics["recent_60d_return"]),
        "recent_60d_max_drawdown": float(metrics["recent_60d_max_drawdown"]),
        "signal_days_ratio": float(metrics["signal_days_ratio"]),
        "trades_per_day": float(metrics["trades_per_day"]),
        "selection_score": float(metrics["selection_score"]),
    }
    for strategy_id in MAIN_CANDIDATE_STRATEGIES:
        base[f"is_{strategy_id}"] = 1.0 if metrics["strategy_id"] == strategy_id else 0.0
    return base


def _eligible_rows(metrics_rows: list[dict]) -> list[dict]:
    return [
        row
        for row in metrics_rows
        if row["num_trades"] >= MIN_TRAIN_TRADES
        and row["sharpe"] >= MIN_LONG_TERM_SHARPE
        and row["recent_60d_sharpe"] >= MIN_RECENT_60_SHARPE
        and row["signal_days_ratio"] >= MIN_SIGNAL_DAYS_RATIO
        and row["max_drawdown"] >= MAX_TRAIN_DRAWDOWN
    ]


def _fit_meta_model(history_rows: list[dict]) -> RandomForestRegressor | None:
    if len(history_rows) < MIN_HISTORY_SAMPLES:
        return None
    history_df = pd.DataFrame(history_rows)
    if history_df["target_realized_score"].nunique() < 8:
        return None
    model = RandomForestRegressor(
        n_estimators=260,
        max_depth=5,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(history_df[META_FEATURE_COLUMNS], history_df["target_realized_score"])
    return model


def _selection_mode_from_rows(ranked_rows: list[dict]) -> tuple[list[dict], str]:
    if not ranked_rows:
        return [], "cash"
    top_one = ranked_rows[0]
    if float(top_one["meta_predicted_score"]) < MIN_META_SCORE_FOR_DEPLOY:
        return [], "cash"
    if len(ranked_rows) == 1:
        return [top_one], "single"
    top_two = ranked_rows[1]
    score_gap = float(top_one["meta_predicted_score"]) - float(top_two["meta_predicted_score"])
    if score_gap >= SINGLE_META_SCORE_GAP:
        return [top_one], "single"
    return ranked_rows[:BLENDED_SELECTION_LIMIT], "blended"


def _window_ranking_score(selected_main: list[dict], selection_mode: str) -> float:
    if not selected_main:
        return float("-inf")
    avg_meta_score = sum(float(row["meta_predicted_score"]) for row in selected_main) / len(selected_main)
    avg_heuristic_score = sum(float(row["selection_score"]) for row in selected_main) / len(selected_main)
    mode_bonus = 0.08 if selection_mode == "single" else 0.0
    return avg_meta_score + avg_heuristic_score * 0.06 + mode_bonus


def _select_main_strategies(
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    unique_dates: list,
    start: int,
    history_rows: list[dict],
) -> tuple[list[dict], str, int]:
    meta_model = _fit_meta_model(history_rows)
    best_selected: list[dict] = []
    best_mode = "cash"
    best_window = 0
    best_score = float("-inf")

    for train_days in TRAIN_WINDOW_OPTIONS:
        if start < train_days:
            continue
        train_dates = unique_dates[start - train_days : start]
        train_features = _filter_frame_by_dates(features, train_dates)
        metrics_rows = []
        for strategy_id in MAIN_CANDIDATE_STRATEGIES:
            signals = _filter_frame_by_dates(component_signals[strategy_id], train_dates)
            metrics = _component_train_metrics(
                strategy_id,
                signals,
                train_features,
                config,
                holding_days,
                train_days,
            )
            metrics["selection_score"] = _selection_score(metrics)
            metrics["train_window_days"] = train_days
            feature_row = _build_meta_features(metrics)
            if meta_model is not None:
                metrics["meta_predicted_score"] = float(
                    meta_model.predict(pd.DataFrame([feature_row], columns=META_FEATURE_COLUMNS))[0]
                )
            else:
                metrics["meta_predicted_score"] = float(metrics["selection_score"])
            metrics_rows.append(metrics)

        eligible = _eligible_rows(metrics_rows)
        eligible.sort(
            key=lambda row: (
                float(row["meta_predicted_score"]),
                float(row["selection_score"]),
                float(row["recent_60d_sharpe"]),
            ),
            reverse=True,
        )
        selected_main, selection_mode = _selection_mode_from_rows(eligible)
        candidate_score = _window_ranking_score(selected_main, selection_mode)
        if candidate_score > best_score:
            best_score = candidate_score
            best_selected = selected_main
            best_mode = selection_mode
            best_window = train_days

    return best_selected, best_mode, best_window


def _record_history(
    history_rows: list[dict],
    component_signals: dict[str, pd.DataFrame],
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    unique_dates: list,
    start: int,
    test_dates: list,
) -> None:
    realized_cache = {
        strategy_id: _component_test_metrics(
            strategy_id,
            component_signals,
            features,
            config,
            holding_days,
            test_dates,
        )
        for strategy_id in MAIN_CANDIDATE_STRATEGIES
    }

    for train_days in TRAIN_WINDOW_OPTIONS:
        if start < train_days:
            continue
        train_dates = unique_dates[start - train_days : start]
        train_features = _filter_frame_by_dates(features, train_dates)
        for strategy_id in MAIN_CANDIDATE_STRATEGIES:
            signals = _filter_frame_by_dates(component_signals[strategy_id], train_dates)
            metrics = _component_train_metrics(
                strategy_id,
                signals,
                train_features,
                config,
                holding_days,
                train_days,
            )
            metrics["selection_score"] = _selection_score(metrics)
            metrics["train_window_days"] = train_days
            feature_row = _build_meta_features(metrics)
            history_rows.append(
                {
                    **feature_row,
                    "target_realized_score": float(realized_cache[strategy_id]["realized_score"]),
                }
            )


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
        weight = max(float(row["meta_predicted_score"]), 0.05)
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
    max_train_days = max(TRAIN_WINDOW_OPTIONS)
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])

    component_signals = {
        strategy_id: _resolve_component_signals(strategy_id, features, config, holding_days)
        for strategy_id in MAIN_CANDIDATE_STRATEGIES
    }

    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []
    history_rows: list[dict] = []

    if model_dir is not None:
        ensure_dir(model_dir)

    start = max_train_days
    fold_index = 1
    while start < len(unique_dates):
        train_dates_max = unique_dates[start - max_train_days : start]
        test_dates = unique_dates[start : start + test_days]
        if not test_dates:
            break
        if not _within_range(train_dates_max[0], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(train_dates_max[-1], backtest_cfg.get("train_start_date"), backtest_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[0], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[-1], backtest_cfg.get("test_start_date"), backtest_cfg.get("test_end_date")):
            start += step_days
            continue

        selected_main, selection_mode, selected_train_window = _select_main_strategies(
            component_signals,
            features,
            config,
            holding_days,
            unique_dates,
            start,
            history_rows,
        )
        consensus = _aggregate_regime_switch_for_dates(selected_main, component_signals, test_dates)

        _record_history(
            history_rows,
            component_signals,
            features,
            config,
            holding_days,
            unique_dates,
            start,
            test_dates,
        )

        if consensus.empty:
            start += step_days
            fold_index += 1
            continue

        train_dates = unique_dates[start - selected_train_window : start]
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
                        "selected_train_window": selected_train_window,
                        "selected_main": selected_main,
                        "selection_mode": selection_mode,
                        "history_sample_count": len(history_rows),
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
                "selected_train_window": selected_train_window,
                "selection_mode": selection_mode,
                "history_sample_count": len(history_rows),
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
