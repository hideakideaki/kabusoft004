from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.data_loader import (  # noqa: E402
    apply_backtest_date_range,
    load_backtest_config,
    load_feature_config,
    load_market_data,
    load_walkforward_config,
)
from src.core.feature_engineering import FEATURE_COLUMNS, build_features  # noqa: E402


STRATEGY_MODULES = {
    "worker_01": "src.strategies.worker_01_breakout_volume",
    "worker_02": "src.strategies.worker_02_mean_reversion_rebound",
    "worker_04": "src.strategies.worker_04_logistic_regression",
    "worker_05": "src.strategies.worker_05_gradient_boosting",
    "worker_06": "src.strategies.worker_06_random_forest",
    "worker_08": "src.strategies.worker_08_hybrid_event_ml_compact",
    "worker_10": "src.strategies.worker_10_hybrid_event_pullback",
    "worker_10b": "src.strategies.worker_10b_hybrid_event_pullback_defensive",
    "worker_10c": "src.strategies.worker_10c_hybrid_event_pullback_diversified",
    "worker_10d": "src.strategies.worker_10d_hybrid_event_pullback_correlation",
    "worker_10e": "src.strategies.worker_10e_hybrid_event_pullback_blend",
    "worker_10f": "src.strategies.worker_10f_hybrid_event_pullback_exposure",
    "worker_17": "src.strategies.worker_17_regime_switch_meta",
    "worker_17b": "src.strategies.worker_17b_regime_switch_adaptive",
    "worker_15b": "src.strategies.worker_15b_stable_compounder_relative",
}


GENERIC_MODEL_FACTORIES = {
    "worker_04": lambda: LogisticRegression(max_iter=500, class_weight="balanced"),
    "worker_05": lambda: HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        random_state=42,
    ),
    "worker_06": lambda: RandomForestClassifier(
        n_estimators=120,
        max_depth=6,
        min_samples_leaf=20,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    ),
}


HYBRID_SCORE_CONFIG = {
    "worker_08": {
        "kind": "event_only",
        "limit": 4,
        "weights": {
            "logistic": 0.35,
            "forest": 0.45,
            "rule": 0.20,
        },
        "rule": {
            "range_pct": 8.0,
            "volume_ratio_20": 0.6,
            "ret_1": 12.0,
            "breakout_strength": 5.0,
        },
    },
    "worker_10": {
        "kind": "event_pullback",
        "limit": 4,
        "weights": {
            "logistic": 0.30,
            "forest": 0.35,
            "rule": 0.20,
            "event": 0.10,
            "pullback": 0.15,
        },
        "rule": {
            "range_pct": 6.0,
            "volume_ratio_20": 0.5,
            "ret_20": 8.0,
            "rebound_strength": 4.0,
            "intraday_return": 20.0,
            "ret_5_abs": -10.0,
        },
    },
    "worker_10b": {
        "kind": "event_pullback",
        "limit": 3,
        "weights": {
            "logistic": 0.34,
            "forest": 0.36,
            "rule": 0.18,
            "event": 0.06,
            "pullback": 0.06,
        },
        "rule": {
            "range_pct": 4.5,
            "volume_ratio_20": 0.4,
            "ret_20": 6.0,
            "rebound_strength": 3.0,
            "intraday_return": 12.0,
            "ret_5_abs": -8.0,
            "volatility_20": -10.0,
        },
    },
    "worker_10c": {
        "kind": "diversified",
        "limit": 3,
        "weights": {
            "logistic": 0.33,
            "forest": 0.35,
            "rule": 0.20,
            "event": 0.06,
            "pullback": 0.06,
        },
        "rule": {
            "range_pct": 5.0,
            "volume_ratio_20": 0.45,
            "ret_20": 6.5,
            "rebound_strength": 3.5,
            "intraday_return": 14.0,
            "ret_5_abs": -8.5,
            "volatility_20": -8.0,
        },
    },
    "worker_10d": {
        "kind": "low_correlation",
        "limit": 3,
        "weights": {
            "logistic": 0.34,
            "forest": 0.36,
            "rule": 0.18,
            "event": 0.06,
            "pullback": 0.06,
        },
        "rule": {
            "range_pct": 4.5,
            "volume_ratio_20": 0.4,
            "ret_20": 6.0,
            "rebound_strength": 3.0,
            "intraday_return": 12.0,
            "ret_5_abs": -8.0,
            "volatility_20": -10.0,
        },
    },
    "worker_10e": {
        "kind": "blended",
        "limit": 3,
        "weights": {
            "logistic": 0.34,
            "forest": 0.36,
            "rule": 0.18,
            "event": 0.05,
            "pullback": 0.05,
            "both": 0.02,
        },
        "rule": {
            "range_pct": 4.8,
            "volume_ratio_20": 0.42,
            "ret_20": 6.2,
            "rebound_strength": 3.2,
            "intraday_return": 13.0,
            "ret_5_abs": -8.2,
            "volatility_20": -9.0,
        },
    },
    "worker_10f": {
        "kind": "low_correlation",
        "limit": 3,
        "weights": {
            "logistic": 0.35,
            "forest": 0.37,
            "rule": 0.18,
            "event": 0.05,
            "pullback": 0.05,
        },
        "rule": {
            "range_pct": 4.2,
            "volume_ratio_20": 0.38,
            "ret_20": 5.8,
            "rebound_strength": 2.8,
            "intraday_return": 11.0,
            "ret_5_abs": -7.8,
            "volatility_20": -10.5,
        },
    },
}


OUTPUT_COLUMNS = [
    "rank",
    "strategy_id",
    "signal_date",
    "planned_entry_date",
    "holding_days",
    "symbol",
    "score",
    "close",
    "volume",
    "ret_1",
    "ret_5",
    "ret_20",
    "volatility_20",
    "volume_ratio_20",
    "range_pct",
    "breakout_strength",
    "rebound_strength",
    "action",
]


def _load_strategy_module(strategy_id: str):
    if strategy_id not in STRATEGY_MODULES:
        supported = ", ".join(sorted(STRATEGY_MODULES))
        raise ValueError(f"unsupported strategy_id: {strategy_id}. Supported: {supported}")
    return importlib.import_module(STRATEGY_MODULES[strategy_id])


def _selected_holding_days(root: Path, strategy_id: str, fallback: int) -> int:
    meta_path = root / "runs" / strategy_id / "meta.json"
    if not meta_path.exists():
        return int(fallback)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    selected = meta.get("selected_holding_days")
    return int(selected) if selected is not None else int(fallback)


def _prepare_features(root: Path) -> pd.DataFrame:
    backtest_cfg = load_backtest_config(root)
    feature_cfg = load_feature_config(root)
    market = load_market_data(str(root), int(backtest_cfg["universe_size"]))
    market = apply_backtest_date_range(market, backtest_cfg)
    features = build_features(market, int(feature_cfg.get("window_main", 20)))
    features = features.sort_values(["date", "symbol"]).reset_index(drop=True)
    return features.groupby("symbol", group_keys=False).filter(
        lambda frame: len(frame) >= int(backtest_cfg.get("min_history_days", 260))
    )


def _latest_prediction_frame(features: pd.DataFrame) -> tuple[pd.Timestamp, pd.DataFrame]:
    latest_date = pd.Timestamp(features["date"].max()).normalize()
    latest = features[features["date"] == latest_date].dropna(subset=FEATURE_COLUMNS).copy()
    if latest.empty:
        raise RuntimeError(f"no usable latest feature rows for {latest_date:%Y-%m-%d}")
    return latest_date, latest.reset_index(drop=True)


def _latest_prediction_frame_custom(
    features: pd.DataFrame,
    required_columns: list[str],
) -> tuple[pd.Timestamp, pd.DataFrame]:
    latest_date = pd.Timestamp(features["date"].max()).normalize()
    latest = features[features["date"] == latest_date].dropna(subset=required_columns).copy()
    if latest.empty:
        raise RuntimeError(f"no usable latest feature rows for {latest_date:%Y-%m-%d}")
    return latest_date, latest.reset_index(drop=True)


def _training_frame(
    features: pd.DataFrame,
    latest_date: pd.Timestamp,
    holding_days: int,
    train_days: int,
) -> tuple[pd.DataFrame, str, str]:
    target_column = f"target_up_{holding_days}"
    usable = features.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
    usable = usable[usable["date"] < latest_date].copy()
    dates = sorted(usable["date"].dropna().unique())
    if len(dates) < train_days:
        raise RuntimeError(
            f"not enough training dates: required {train_days}, available {len(dates)}"
        )
    train_dates = dates[-train_days:]
    train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
    if train_df[target_column].nunique() < 2:
        raise RuntimeError(f"training target has only one class: {target_column}")
    return (
        train_df,
        pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
        pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
    )


def _training_frame_custom(
    features: pd.DataFrame,
    latest_date: pd.Timestamp,
    required_columns: list[str],
    target_column: str,
    train_days: int,
) -> tuple[pd.DataFrame, str, str]:
    usable = features.dropna(subset=required_columns + [target_column]).copy()
    usable = usable[usable["date"] < latest_date].copy()
    dates = sorted(usable["date"].dropna().unique())
    if len(dates) < train_days:
        raise RuntimeError(
            f"not enough training dates: required {train_days}, available {len(dates)}"
        )
    train_dates = dates[-train_days:]
    train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
    if train_df[target_column].nunique() < 2:
        raise RuntimeError(f"training target has only one class: {target_column}")
    return (
        train_df,
        pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
        pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
    )


def _predict_scores(model: Any, frame: pd.DataFrame) -> pd.Series:
    if hasattr(model, "predict_proba"):
        return pd.Series(model.predict_proba(frame[FEATURE_COLUMNS])[:, 1], index=frame.index)
    return pd.Series(model.decision_function(frame[FEATURE_COLUMNS]), index=frame.index)


def _run_generic_model(
    strategy_id: str,
    train_df: pd.DataFrame,
    latest_df: pd.DataFrame,
    holding_days: int,
) -> pd.DataFrame:
    target_column = f"target_up_{holding_days}"
    model = GENERIC_MODEL_FACTORIES[strategy_id]()
    model.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))
    candidates = latest_df.copy()
    candidates["score"] = _predict_scores(model, candidates)
    return candidates


def _rule_score(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    score = pd.Series(0.0, index=frame.index)
    for column, weight in weights.items():
        if column == "ret_5_abs":
            score += frame["ret_5"].abs() * float(weight)
        else:
            score += frame[column] * float(weight)
    return score


def _return_matrix(features: pd.DataFrame) -> pd.DataFrame:
    return (
        features[["date", "symbol", "ret_1"]]
        .dropna()
        .pivot(index="date", columns="symbol", values="ret_1")
        .sort_index()
    )


def _run_hybrid_model(
    strategy_id: str,
    module: Any,
    features: pd.DataFrame,
    train_df: pd.DataFrame,
    latest_df: pd.DataFrame,
    holding_days: int,
) -> pd.DataFrame:
    target_column = f"target_up_{holding_days}"
    logistic = LogisticRegression(max_iter=500, class_weight="balanced")
    random_forest = RandomForestClassifier(
        n_estimators=160,
        max_depth=6,
        min_samples_leaf=20,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    )
    logistic.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))
    random_forest.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))

    config = HYBRID_SCORE_CONFIG[strategy_id]
    latest = latest_df.copy()
    event_mask = module._event_filter(latest)
    if config["kind"] == "event_only":
        candidate_df = latest[event_mask].copy()
    else:
        pullback_mask = module._pullback_filter(latest)
        candidate_df = latest[event_mask | pullback_mask].copy()
        candidate_df["pullback_bonus"] = pullback_mask[candidate_df.index].astype(float)
        if config["kind"] == "blended":
            candidate_df["both_bonus"] = (
                event_mask[candidate_df.index] & pullback_mask[candidate_df.index]
            ).astype(float)

    if candidate_df.empty:
        return pd.DataFrame(columns=list(latest_df.columns) + ["score"])

    candidate_df["logistic_score"] = logistic.predict_proba(candidate_df[FEATURE_COLUMNS])[:, 1]
    candidate_df["forest_score"] = random_forest.predict_proba(candidate_df[FEATURE_COLUMNS])[:, 1]
    candidate_df["event_bonus"] = event_mask[candidate_df.index].astype(float)
    candidate_df["rule_score"] = _rule_score(candidate_df, config["rule"])

    weights = config["weights"]
    candidate_df["score"] = (
        candidate_df["logistic_score"] * weights.get("logistic", 0.0)
        + candidate_df["forest_score"] * weights.get("forest", 0.0)
        + candidate_df["rule_score"] * weights.get("rule", 0.0)
        + candidate_df["event_bonus"] * weights.get("event", 0.0)
        + candidate_df.get("pullback_bonus", 0.0) * weights.get("pullback", 0.0)
        + candidate_df.get("both_bonus", 0.0) * weights.get("both", 0.0)
    )

    limit = int(config["limit"])
    kind = config["kind"]
    if kind == "diversified":
        candidate_df = module._select_diversified(candidate_df, limit=limit)
    elif kind in {"low_correlation", "blended"}:
        matrix = _return_matrix(features)
        selector = module._select_blended if kind == "blended" else module._select_low_correlation
        candidate_df = selector(candidate_df, matrix, lookback_days=20, limit=limit)
    else:
        candidate_df = candidate_df.sort_values("score", ascending=False).head(limit)

    return candidate_df


def _run_rule_based_live(
    module: Any,
    features: pd.DataFrame,
    backtest_cfg: dict,
    walk_cfg: dict,
    holding_days: int,
) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame, str, str, int]:
    latest_date, latest_df = _latest_prediction_frame(features)
    signals = module.generate_signals(
        features,
        {"backtest": backtest_cfg, "walkforward": walk_cfg},
        holding_days,
        model_dir=None,
    )
    if signals.empty:
        candidates = pd.DataFrame(columns=["date", "symbol", "score"])
    else:
        candidates = signals[signals["date"] == latest_date].copy()
    return latest_date, latest_df, candidates, "", "", 0


def _run_regime_switch_live(
    module: Any,
    features: pd.DataFrame,
    backtest_cfg: dict,
    walk_cfg: dict,
    holding_days: int,
) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame, str, str, int, list[dict[str, Any]]]:
    latest_date, latest_df = _latest_prediction_frame(features)
    unique_dates = sorted(features["date"].dropna().unique())
    prior_dates = [date_value for date_value in unique_dates if pd.Timestamp(date_value) < latest_date]
    train_days = int(walk_cfg["train_days"])
    if len(prior_dates) < train_days:
        raise RuntimeError(
            f"not enough training dates for regime-switch live mode: required {train_days}, available {len(prior_dates)}"
        )

    train_dates = prior_dates[-train_days:]
    config = {
        "backtest": {
            **backtest_cfg,
            **getattr(module, "BACKTEST_OVERRIDES", {}),
            "holding_days": int(holding_days),
        },
        "walkforward": walk_cfg,
    }
    component_signals = {
        strategy_id: module._resolve_component_signals(strategy_id, features, config, holding_days)
        for strategy_id in module.MAIN_CANDIDATE_STRATEGIES
    }
    selected = module._select_main_strategies(
        component_signals,
        features,
        config,
        holding_days,
        train_dates,
    )
    if isinstance(selected, tuple):
        selected_main = selected[0]
    else:
        selected_main = selected
    candidates = module._aggregate_regime_switch_for_dates(selected_main, component_signals, [latest_date])
    return (
        latest_date,
        latest_df,
        candidates,
        pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
        pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
        int(len(train_dates)),
        selected_main,
    )


def _run_worker_15b_live(
    root: Path,
    module: Any,
    features: pd.DataFrame,
    backtest_cfg: dict,
    walk_cfg: dict,
    holding_days: int,
) -> tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame, str, str, int]:
    benchmark_symbol = str(load_backtest_config(root).get("benchmark_symbol", "^N225"))
    augmented = module._add_market_state_features(features)
    benchmark_features = module._load_benchmark_features(root, benchmark_symbol, backtest_cfg)
    augmented = augmented.merge(benchmark_features, on="date", how="left")
    augmented["rel_ret_5"] = augmented["ret_5"] - augmented["benchmark_ret_5"]
    augmented["rel_ret_20"] = augmented["ret_20"] - augmented["benchmark_ret_20"]
    augmented["rel_strength_20"] = augmented["breakout_strength"] - augmented["benchmark_drawdown_20"]

    target_column = f"target_relative_stable_{holding_days}"
    relative_threshold = 0.01 if holding_days <= 10 else 0.015
    augmented[target_column] = (
        (augmented[f"future_return_{holding_days}"] - augmented[f"benchmark_future_return_{holding_days}"])
        > relative_threshold
    ).astype(float)

    latest_date, latest_df = _latest_prediction_frame_custom(
        augmented,
        module.RELATIVE_STABLE_FEATURE_COLUMNS,
    )
    train_df, train_start, train_end = _training_frame_custom(
        augmented,
        latest_date,
        module.RELATIVE_STABLE_FEATURE_COLUMNS,
        target_column,
        int(walk_cfg["train_days"]),
    )

    logistic = LogisticRegression(max_iter=600, class_weight="balanced")
    boosting = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.04,
        min_samples_leaf=30,
        random_state=42,
    )
    forest = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        min_samples_leaf=22,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    )

    logistic.fit(train_df[module.RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))
    boosting.fit(train_df[module.RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))
    forest.fit(train_df[module.RELATIVE_STABLE_FEATURE_COLUMNS], train_df[target_column].astype(int))

    candidate_df = latest_df[module._stable_relative_filter(latest_df)].copy()
    if candidate_df.empty:
        return latest_date, latest_df, candidate_df, train_start, train_end, int(len(train_df))

    logistic_score = logistic.predict_proba(latest_df[module.RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]
    boosting_score = boosting.predict_proba(latest_df[module.RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]
    forest_score = forest.predict_proba(latest_df[module.RELATIVE_STABLE_FEATURE_COLUMNS])[:, 1]

    candidate_df["logistic_score"] = logistic_score[candidate_df.index]
    candidate_df["boosting_score"] = boosting_score[candidate_df.index]
    candidate_df["forest_score"] = forest_score[candidate_df.index]
    candidate_df["stability_score"] = (
        candidate_df["trend_efficiency_20"] * 10.0
        + candidate_df["up_day_ratio_20"] * 2.6
        + candidate_df["sma_trend_20_60"] * 8.0
        + candidate_df["ret_20"] * 7.0
        - candidate_df["downside_vol_20"] * 18.0
        - candidate_df["volatility_20"] * 14.0
        - candidate_df["range_stability_20"] * 8.0
        - (candidate_df["volume_ratio_20"] - 1.05).abs() * 1.0
        - (candidate_df["close_position_20"] - 0.72).abs() * 1.3
        - candidate_df["gap_open"].abs() * 5.0
    )
    candidate_df["relative_score"] = (
        candidate_df["rel_ret_20"] * 30.0
        + candidate_df["rel_ret_5"] * 10.0
        + candidate_df["rel_strength_20"] * 12.0
        + candidate_df["trend_efficiency_20"] * 3.0
        - candidate_df["benchmark_volatility_20"] * 4.0
    )
    candidate_df["score"] = (
        candidate_df["logistic_score"] * 0.10
        + candidate_df["boosting_score"] * 0.22
        + candidate_df["forest_score"] * 0.12
        + candidate_df["stability_score"] * 0.22
        + candidate_df["relative_score"] * 0.34
    )

    return_matrix = _return_matrix(features)
    candidate_df = module._select_diversified(
        candidate_df,
        return_matrix,
        limit=module.DAILY_SELECTION_LIMIT,
    )
    candidate_df = candidate_df.sort_values("score", ascending=False)
    return latest_date, latest_df, candidate_df, train_start, train_end, int(len(train_df))


def _format_output(
    candidates: pd.DataFrame,
    strategy_id: str,
    signal_date: pd.Timestamp,
    planned_entry_date: pd.Timestamp,
    holding_days: int,
    top_n: int,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    output = candidates.sort_values("score", ascending=False).head(top_n).copy()
    output.insert(0, "rank", range(1, len(output) + 1))
    output["strategy_id"] = strategy_id
    output["signal_date"] = signal_date.strftime("%Y-%m-%d")
    output["planned_entry_date"] = planned_entry_date.strftime("%Y-%m-%d")
    output["holding_days"] = int(holding_days)
    output["action"] = "buy_candidate"
    for column in OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    return output[OUTPUT_COLUMNS]


def generate_buy_candidates(
    root: Path,
    strategy_id: str,
    entry_offset_days: int,
    top_n: int,
) -> dict[str, Any]:
    module = _load_strategy_module(strategy_id)
    backtest_cfg = {
        **load_backtest_config(root),
        **getattr(module, "BACKTEST_OVERRIDES", {}),
    }
    walk_cfg = load_walkforward_config(root)
    fallback_holding_days = int(backtest_cfg["holding_days_tested"][0])
    holding_days = _selected_holding_days(root, strategy_id, fallback_holding_days)

    features = _prepare_features(root)
    selected_main: list[dict[str, Any]] | None = None
    if strategy_id in {"worker_01", "worker_02"}:
        (
            latest_date,
            latest_df,
            candidates,
            train_start,
            train_end,
            train_rows,
        ) = _run_rule_based_live(
            module,
            features,
            backtest_cfg,
            walk_cfg,
            holding_days,
        )
    elif strategy_id == "worker_15b":
        (
            latest_date,
            latest_df,
            candidates,
            train_start,
            train_end,
            train_rows,
        ) = _run_worker_15b_live(
            root,
            module,
            features,
            backtest_cfg,
            walk_cfg,
            holding_days,
        )
    elif strategy_id in {"worker_17", "worker_17b"}:
        (
            latest_date,
            latest_df,
            candidates,
            train_start,
            train_end,
            train_rows,
            selected_main,
        ) = _run_regime_switch_live(
            module,
            features,
            backtest_cfg,
            walk_cfg,
            holding_days,
        )
    else:
        latest_date, latest_df = _latest_prediction_frame(features)
        train_df, train_start, train_end = _training_frame(
            features,
            latest_date,
            holding_days,
            int(walk_cfg["train_days"]),
        )

        if strategy_id in GENERIC_MODEL_FACTORIES:
            candidates = _run_generic_model(strategy_id, train_df, latest_df, holding_days)
        else:
            candidates = _run_hybrid_model(
                strategy_id,
                module,
                features,
                train_df,
                latest_df,
                holding_days,
            )
        train_rows = int(len(train_df))

    if not candidates.empty:
        enrich_columns = [
            "date",
            "symbol",
            "close",
            "volume",
            "ret_1",
            "ret_5",
            "ret_20",
            "volatility_20",
            "volume_ratio_20",
            "range_pct",
            "breakout_strength",
            "rebound_strength",
        ]
        latest_enriched = latest_df[[column for column in enrich_columns if column in latest_df.columns]].copy()
        merge_keys = {"date", "symbol"}
        drop_columns = [
            column for column in enrich_columns if column in candidates.columns and column not in merge_keys
        ]
        candidates = candidates.drop(columns=drop_columns, errors="ignore")
        candidates = candidates.merge(latest_enriched, on=["date", "symbol"], how="left")

    planned_entry_date = latest_date + pd.Timedelta(days=int(entry_offset_days))
    output = _format_output(
        candidates,
        strategy_id,
        latest_date,
        planned_entry_date,
        holding_days,
        top_n,
    )

    output_dir = root / "live_signals" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"{strategy_id}_signal_{latest_date:%Y%m%d}"
        f"_entry_{planned_entry_date:%Y%m%d}"
    )
    csv_path = output_dir / f"{stem}.csv"
    json_path = output_dir / f"{stem}.json"
    output.to_csv(csv_path, index=False, encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": strategy_id,
        "signal_date": latest_date.strftime("%Y-%m-%d"),
        "planned_entry_date": planned_entry_date.strftime("%Y-%m-%d"),
        "entry_offset_days": int(entry_offset_days),
        "holding_days": int(holding_days),
        "train_start": train_start,
        "train_end": train_end,
        "train_rows": int(train_rows),
        "latest_rows": int(len(latest_df)),
        "candidate_count": int(len(output)),
        "csv_path": str(csv_path),
        "candidates": output.to_dict(orient="records"),
    }
    if selected_main is not None:
        payload["selected_main"] = selected_main
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    payload["json_path"] = str(json_path)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate live buy candidates from the latest DB date."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strategy-id", default="worker_10c", choices=sorted(STRATEGY_MODULES))
    parser.add_argument("--entry-offset-days", type=int, choices=(1, 2), default=1)
    parser.add_argument("--top-n", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = generate_buy_candidates(
        args.root.resolve(),
        args.strategy_id,
        args.entry_offset_days,
        args.top_n,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
