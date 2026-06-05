from __future__ import annotations

import json
import pickle
from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.core.utils import ensure_dir


STRATEGY_ID = "worker_23b"
STRATEGY_NAME = "worker_23b_profit_target_consensus"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "holding_days_tested": [20],
    "max_positions": 4,
    "top_signals_per_day": 4,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.70,
    "stop_loss_pct": 0.08,
}

TARGET_RETURN_THRESHOLD = 0.03
COMPONENT_TOP_N_PER_DAY = 12
OUTPUT_TOP_N_PER_DAY = 4
MIN_TRAIN_ROWS = 400
MIN_POSITIVE_ROWS = 40
MIN_NEGATIVE_ROWS = 40

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
PROFIT_TARGET_COMPONENTS = {"worker_19", "worker_20", "worker_21", "worker_22"}
CORE_ML_COMPONENTS = {"worker_04", "worker_06", "worker_08", "worker_10e", "worker_10f", "worker_17e"}

MODEL_FEATURE_COLUMNS = [
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
    "ret_5",
    "ret_20",
    "volume_ratio_20",
    "volatility_20",
    "drawdown_20",
    "range_pct",
    "liquidity_score",
]


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


def _component_run_metrics(strategy_id: str, config: dict) -> dict:
    metrics_path = Path(config["backtest"]["_project_root"]) / "runs" / strategy_id / "metrics.json"
    if not metrics_path.exists():
        return {}
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def _component_weights(config: dict) -> dict[str, float]:
    weights = {}
    for strategy_id in MAIN_COMPONENT_STRATEGIES:
        metrics = _component_run_metrics(strategy_id, config)
        weight = (
            max(float(metrics.get("sharpe", 0.0)), 0.0)
            + max(float(metrics.get("cagr", 0.0)), 0.0) * 0.25
        )
        weights[strategy_id] = max(weight, 0.05)
    return weights


def _load_component_signals(strategy_id: str, features: pd.DataFrame, config: dict) -> pd.DataFrame:
    candidates_path = Path(config["backtest"]["_project_root"]) / "runs" / strategy_id / "candidates.csv"
    if not candidates_path.exists():
        return pd.DataFrame(columns=["date", "symbol", "score"])
    signals = pd.read_csv(candidates_path, usecols=["date", "symbol", "score"])
    if signals.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"])
    signals["date"] = pd.to_datetime(signals["date"])
    signals["symbol"] = signals["symbol"].astype(str)
    signals = signals[signals["date"].isin(features["date"].unique())].copy()
    signals = signals.sort_values(["date", "score"], ascending=[True, False])
    signals["component_rank"] = signals.groupby("date")["score"].rank(
        method="first",
        ascending=False,
    )
    return signals[signals["component_rank"] <= COMPONENT_TOP_N_PER_DAY].reset_index(drop=True)


def _aggregate_consensus_features(
    component_signals: dict[str, pd.DataFrame],
    component_weights: dict[str, float],
    date_values: list | None,
) -> pd.DataFrame:
    frames = []
    for strategy_id in MAIN_COMPONENT_STRATEGIES:
        signals = (
            component_signals[strategy_id].copy()
            if date_values is None
            else _filter_frame_by_dates(component_signals[strategy_id], date_values)
        )
        if signals.empty:
            continue
        signals = signals.copy()
        signals["component_strategy"] = strategy_id
        signals["component_weight"] = float(component_weights.get(strategy_id, 0.05))
        frames.append(signals)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol"])

    combined = pd.concat(frames, ignore_index=True)
    stable = (
        component_signals[STABLE_SUPPORT_STRATEGY].copy()
        if date_values is None
        else _filter_frame_by_dates(component_signals[STABLE_SUPPORT_STRATEGY], date_values)
    )
    stable_pairs = set(zip(stable["date"], stable["symbol"])) if not stable.empty else set()

    rows = []
    for (date_value, symbol), group in combined.groupby(["date", "symbol"], sort=False):
        profit_mask = group["component_strategy"].isin(PROFIT_TARGET_COMPONENTS)
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
                "profit_target_support_count": float(profit_mask.sum()),
                "profit_target_weighted_support": float(group.loc[profit_mask, "component_weight"].sum()),
                "core_ml_support_count": float(group["component_strategy"].isin(CORE_ML_COMPONENTS).sum()),
                "has_worker_19": float((group["component_strategy"] == "worker_19").any()),
                "has_worker_20": float((group["component_strategy"] == "worker_20").any()),
                "has_worker_21": float((group["component_strategy"] == "worker_21").any()),
                "has_worker_22": float((group["component_strategy"] == "worker_22").any()),
                "has_worker_10e": float((group["component_strategy"] == "worker_10e").any()),
                "has_worker_10f": float((group["component_strategy"] == "worker_10f").any()),
                "has_worker_17e": float((group["component_strategy"] == "worker_17e").any()),
            }
        )
    return pd.DataFrame(rows)


def _add_profit_target_label(features: pd.DataFrame, holding_days: int) -> pd.DataFrame:
    labeled = features.sort_values(["symbol", "date"]).copy()
    future_max_high_column = f"future_max_high_{holding_days}"
    grouped = labeled.groupby("symbol", group_keys=False)
    labeled[future_max_high_column] = grouped["high"].transform(
        lambda series: series.shift(periods=-1)
        .iloc[::-1]
        .rolling(holding_days, min_periods=holding_days)
        .max()
        .iloc[::-1]
    )
    labeled[f"profit_target_return_{holding_days}"] = (
        labeled[future_max_high_column] / labeled["next_open"]
    ) - 1.0
    labeled[f"profit_target_{holding_days}"] = (
        labeled[f"profit_target_return_{holding_days}"] >= TARGET_RETURN_THRESHOLD
    ).astype(float)
    return labeled


def _attach_market_features_and_target(
    consensus: pd.DataFrame,
    labeled_features: pd.DataFrame,
    holding_days: int,
) -> pd.DataFrame:
    columns = [
        "date",
        "symbol",
        "ret_5",
        "ret_20",
        "volume_ratio_20",
        "volatility_20",
        "drawdown_20",
        "range_pct",
        "liquidity_score",
        f"exit_date_{holding_days}",
        f"profit_target_{holding_days}",
    ]
    merged = consensus.merge(labeled_features[columns], on=["date", "symbol"], how="left")
    merged = merged.dropna(subset=MODEL_FEATURE_COLUMNS + [f"exit_date_{holding_days}", f"profit_target_{holding_days}"])
    merged[f"exit_date_{holding_days}"] = pd.to_datetime(merged[f"exit_date_{holding_days}"])
    return merged


def _sample_weights(target: pd.Series) -> list[float]:
    positive_count = int(target.sum())
    negative_count = int(len(target) - positive_count)
    if positive_count <= 0 or negative_count <= 0:
        return [1.0] * len(target)
    positive_weight = len(target) / (2.0 * positive_count)
    negative_weight = len(target) / (2.0 * negative_count)
    return [positive_weight if value == 1 else negative_weight for value in target.astype(int)]


def _fit_model(train_df: pd.DataFrame, holding_days: int):
    target_column = f"profit_target_{holding_days}"
    positive_count = int(train_df[target_column].sum())
    negative_count = int(len(train_df) - positive_count)
    if (
        len(train_df) < MIN_TRAIN_ROWS
        or positive_count < MIN_POSITIVE_ROWS
        or negative_count < MIN_NEGATIVE_ROWS
    ):
        return None
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=0.5,
            class_weight="balanced",
            max_iter=500,
            random_state=42,
        ),
    )
    model.fit(
        train_df[MODEL_FEATURE_COLUMNS],
        train_df[target_column].astype(int),
    )
    return model


def _fallback_score(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["profit_target_weighted_support"]
        + frame["weighted_support"] * 0.25
        + frame["top3_support_count"] * 0.25
        + frame["top10_support_count"] * 0.08
        - frame["avg_signal_rank"] * 0.03
    )


def _score(model, frame: pd.DataFrame) -> pd.DataFrame:
    scored = frame.copy()
    if model is None:
        scored["score"] = _fallback_score(scored)
    else:
        scored["score"] = model.predict_proba(scored[MODEL_FEATURE_COLUMNS])[:, 1]
    return scored


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
        strategy_id: _load_component_signals(strategy_id, features, config)
        for strategy_id in (*MAIN_COMPONENT_STRATEGIES, STABLE_SUPPORT_STRATEGY)
    }
    component_weights = _component_weights(config)
    consensus = _aggregate_consensus_features(component_signals, component_weights, None)
    labeled_features = _add_profit_target_label(features, holding_days)
    dataset = _attach_market_features_and_target(consensus, labeled_features, holding_days)

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

        train_df = _filter_frame_by_dates(dataset, train_dates)
        train_end = pd.Timestamp(train_dates[-1])
        train_df = train_df[train_df[f"exit_date_{holding_days}"] <= train_end].copy()
        test_df = _filter_frame_by_dates(dataset, test_dates)
        if test_df.empty:
            start += step_days
            fold_index += 1
            continue

        model = _fit_model(train_df, holding_days)
        scored = _score(model, test_df)
        scored = scored.sort_values(["date", "score"], ascending=[True, False]).copy()
        scored["meta_rank"] = scored.groupby("date")["score"].rank(method="first", ascending=False)
        scored = scored[scored["meta_rank"] <= OUTPUT_TOP_N_PER_DAY].copy()

        model_path = None
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
                        "train_rows": int(len(train_df)),
                        "positive_rows": int(train_df[f"profit_target_{holding_days}"].sum()) if not train_df.empty else 0,
                        "test_rows": int(len(scored)),
                        "model_mode": "logistic_regression" if model is not None else "fallback",
                        "feature_columns": MODEL_FEATURE_COLUMNS,
                    },
                    handle,
                )

        predictions.append(scored[["date", "symbol", "score"]])
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "target_return_threshold": TARGET_RETURN_THRESHOLD,
                "target_definition": "max high from entry date through planned exit date over next_open",
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_df)),
                "positive_rows": int(train_df[f"profit_target_{holding_days}"].sum()) if not train_df.empty else 0,
                "test_rows": int(len(scored)),
                "model_path": str(model_path) if model_path is not None else None,
                "model_mode": "logistic_regression" if model is not None else "fallback",
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
