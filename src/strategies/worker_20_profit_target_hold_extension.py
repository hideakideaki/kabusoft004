from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir
from src.strategies.worker_19_profit_target_classifier import (
    MIN_NEGATIVE_SAMPLES,
    MIN_POSITIVE_SAMPLES,
    TARGET_RETURN_THRESHOLD,
    _add_profit_target_label,
    _build_model,
    _within_range,
)


STRATEGY_ID = "worker_20"
STRATEGY_NAME = "worker_20_profit_target_hold_extension"
STRATEGY_TYPE = "ml_based"

MAX_HOLDING_DAYS = 40
TRAILING_DRAWDOWN_PCT = 0.05
CONTINUATION_DRAWDOWN_PCT = 0.04
CONTINUATION_MIN_RET_5 = -0.015


def _continuation_holds(frame: pd.DataFrame, idx: int, best_high: float) -> bool:
    close = float(frame.attrs["close_values"][idx])
    ret_5 = frame.attrs["ret_5_values"][idx]
    if pd.isna(ret_5):
        return False
    near_high = close >= best_high * (1.0 - CONTINUATION_DRAWDOWN_PCT)
    momentum_ok = float(ret_5) >= CONTINUATION_MIN_RET_5
    return bool(near_high and momentum_ok)


def _dynamic_exit_for_signal(
    frame: pd.DataFrame,
    signal_date: pd.Timestamp,
    holding_days: int,
) -> dict | None:
    positions = frame.attrs["date_positions"]
    signal_idx = positions.get(pd.Timestamp(signal_date).normalize())
    if signal_idx is None:
        return None

    date_values = frame.attrs["date_values"]
    open_values = frame.attrs["open_values"]
    high_values = frame.attrs["high_values"]
    close_values = frame.attrs["close_values"]
    entry_idx = signal_idx + 1
    base_exit_idx = entry_idx + holding_days - 1
    if entry_idx >= len(frame) or base_exit_idx >= len(frame):
        return None

    max_exit_idx = min(entry_idx + MAX_HOLDING_DAYS - 1, len(frame) - 1)
    entry_price = float(open_values[entry_idx])
    target_price = entry_price * (1.0 + TARGET_RETURN_THRESHOLD)
    best_high = float(high_values[entry_idx])
    target_reached = False

    for idx in range(entry_idx, base_exit_idx + 1):
        best_high = max(best_high, float(high_values[idx]))
        if best_high >= target_price:
            target_reached = True

    if not target_reached:
        return {
            "custom_exit_date": date_values[base_exit_idx],
            "custom_exit_price_raw": float(close_values[base_exit_idx]),
            "custom_exit_reason": "base_time_exit",
        }

    for idx in range(base_exit_idx, max_exit_idx + 1):
        best_high = max(best_high, float(high_values[idx]))
        close = float(close_values[idx])

        if close <= best_high * (1.0 - TRAILING_DRAWDOWN_PCT):
            return {
                "custom_exit_date": date_values[idx],
                "custom_exit_price_raw": close,
                "custom_exit_reason": "trailing_exit",
            }

        if not _continuation_holds(frame, idx, best_high):
            return {
                "custom_exit_date": date_values[idx],
                "custom_exit_price_raw": close,
                "custom_exit_reason": "continuation_failed",
            }

    return {
        "custom_exit_date": date_values[max_exit_idx],
        "custom_exit_price_raw": float(close_values[max_exit_idx]),
        "custom_exit_reason": "max_holding_exit",
    }


def _add_dynamic_exits(
    signals: pd.DataFrame,
    features: pd.DataFrame,
    holding_days: int,
    top_signals_per_day: int,
) -> pd.DataFrame:
    if signals.empty:
        return signals

    scoped = signals.copy()
    scoped["_exit_rank"] = (
        scoped.groupby("date")["score"].rank(method="first", ascending=False).astype(int)
    )
    needs_exit = scoped["_exit_rank"] <= int(top_signals_per_day)
    top_scoped = scoped.loc[needs_exit, ["date", "symbol"]].copy()

    frames: dict[str, pd.DataFrame] = {}
    for symbol, frame in features.sort_values(["symbol", "date"]).groupby("symbol"):
        prepared = frame.reset_index(drop=True).copy()
        prepared.attrs["date_positions"] = {
            pd.Timestamp(date).normalize(): idx
            for idx, date in enumerate(prepared["date"])
        }
        prepared.attrs["date_values"] = prepared["date"].to_numpy()
        prepared.attrs["open_values"] = prepared["open"].to_numpy()
        prepared.attrs["high_values"] = prepared["high"].to_numpy()
        prepared.attrs["close_values"] = prepared["close"].to_numpy()
        prepared.attrs["ret_5_values"] = prepared["ret_5"].to_numpy()
        frames[str(symbol)] = prepared

    exit_rows: list[dict] = []
    for signal_date, symbol in top_scoped.itertuples(index=False, name=None):
        frame = frames.get(str(symbol))
        if frame is None:
            exit_rows.append({})
            continue
        exit_rows.append(_dynamic_exit_for_signal(frame, signal_date, holding_days) or {})

    scoped = scoped.drop(columns=["_exit_rank"])
    exits = pd.DataFrame(exit_rows, index=top_scoped.index)
    for column in ("custom_exit_date", "custom_exit_price_raw", "custom_exit_reason"):
        scoped[column] = exits[column] if column in exits.columns else pd.NA
    return scoped


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    walk_cfg = config["walkforward"]
    dates = sorted(features["date"].dropna().unique())
    train_days = int(walk_cfg["train_days"])
    test_days = int(walk_cfg["test_days"])
    step_days = int(walk_cfg["step_days"])
    target_column = f"profit_target_{holding_days}"
    target_return_column = f"profit_target_return_{holding_days}"
    top_signals_per_day = int(config["backtest"].get("top_signals_per_day", 20))

    labeled = _add_profit_target_label(features, holding_days)
    train_usable = labeled.dropna(subset=FEATURE_COLUMNS + [target_return_column]).copy()
    score_usable = features.dropna(subset=FEATURE_COLUMNS).copy()

    predictions: list[pd.DataFrame] = []
    folds: list[dict] = []

    if model_dir is not None:
        ensure_dir(model_dir)

    start = train_days
    fold_index = 1
    while start < len(dates):
        train_dates = dates[start - train_days : start]
        test_dates = dates[start : start + test_days]
        if len(test_dates) == 0:
            break
        if not _within_range(train_dates[0], walk_cfg.get("train_start_date"), walk_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(train_dates[-1], walk_cfg.get("train_start_date"), walk_cfg.get("train_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[0], walk_cfg.get("test_start_date"), walk_cfg.get("test_end_date")):
            start += step_days
            continue
        if not _within_range(test_dates[-1], walk_cfg.get("test_start_date"), walk_cfg.get("test_end_date")):
            start += step_days
            continue

        train_df = train_usable[train_usable["date"].isin(train_dates)].copy()
        test_df = score_usable[score_usable["date"].isin(test_dates)].copy()
        positive_count = int(train_df[target_column].sum())
        negative_count = int(len(train_df) - positive_count)
        if (
            train_df.empty
            or test_df.empty
            or positive_count < MIN_POSITIVE_SAMPLES
            or negative_count < MIN_NEGATIVE_SAMPLES
        ):
            start += step_days
            continue

        model = _build_model()
        model.fit(train_df[FEATURE_COLUMNS], train_df[target_column])

        model_path = None
        if model_dir is not None:
            model_path = model_dir / f"fold_{fold_index:02d}.pkl"
            with model_path.open("wb") as handle:
                pickle.dump(model, handle)

        fold = test_df[["date", "symbol"]].copy()
        fold["score"] = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
        predictions.append(fold)
        folds.append(
            {
                "fold": fold_index,
                "holding_days": holding_days,
                "target_return_threshold": TARGET_RETURN_THRESHOLD,
                "max_holding_days": MAX_HOLDING_DAYS,
                "trailing_drawdown_pct": TRAILING_DRAWDOWN_PCT,
                "continuation_drawdown_pct": CONTINUATION_DRAWDOWN_PCT,
                "continuation_min_ret_5": CONTINUATION_MIN_RET_5,
                "target_definition": "max high from entry date through planned exit date over next_open",
                "exit_definition": "sell on forced exit or when continuation no longer holds",
                "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
                "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
                "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
                "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
                "train_rows": int(len(train_df)),
                "test_rows": int(len(test_df)),
                "positive_rows": positive_count,
                "negative_rows": negative_count,
                "model_path": str(model_path) if model_path is not None else None,
            }
        )
        start += step_days
        fold_index += 1

    if not predictions:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    combined = pd.concat(predictions, ignore_index=True)
    combined = combined.sort_values(["date", "score"], ascending=[True, False])
    combined = combined.drop_duplicates(subset=["date", "symbol"], keep="first")
    combined = _add_dynamic_exits(combined, features, holding_days, top_signals_per_day)
    return combined, folds
