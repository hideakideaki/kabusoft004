from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from src.core.feature_engineering import FEATURE_COLUMNS
from src.core.utils import ensure_dir


STRATEGY_ID = "worker_12"
STRATEGY_NAME = "worker_12"
STRATEGY_TYPE = "ml_based"
BACKTEST_OVERRIDES = {
    "max_positions": 6,
    "top_signals_per_day": 6,
    "max_new_positions_per_day": 2,
    "capital_deployment_ratio": 0.75,
    "stop_loss_pct": 0.08,
    "take_profit_pct": 0.18,
}


def _event_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["volatility_20"] < 0.045)
        & (df["range_pct"] > 0.022)
        & (df["volume_ratio_20"] > 1.05)
        & (df["ret_1"] > -0.01)
        & (df["breakout_strength"] > -0.035)
    )


def _pullback_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["ret_20"] > 0.05)
        & (df["rebound_strength"] > 0.10)
        & (df["breakout_strength"] > -0.05)
        & (df["ret_5"] < -0.015)
        & (df["ret_5"] > -0.08)
        & (df["ret_1"] < 0.01)
        & (df["gap_open"] < 0.012)
        & (df["intraday_return"] > -0.005)
        & (df["volume_ratio_20"] > 0.85)
        & (df["volume_ratio_20"] < 2.4)
        & (df["volatility_20"] < 0.05)
    )


def _rebound_filter(df: pd.DataFrame) -> pd.Series:
    return (
        (df["ret_5"] < -0.04)
        & (df["intraday_return"] > 0.006)
        & (df["volume_ratio_20"] > 1.0)
        & (df["drawdown_20"] < -0.055)
        & (df["ret_1"] > -0.02)
        & (df["volatility_20"] < 0.06)
    )


def _build_return_matrix(features: pd.DataFrame) -> pd.DataFrame:
    return (
        features[["date", "symbol", "ret_1"]]
        .dropna()
        .pivot(index="date", columns="symbol", values="ret_1")
        .sort_index()
    )


def _select_diversified(
    date_group: pd.DataFrame,
    return_matrix: pd.DataFrame,
    lookback_days: int = 20,
    limit: int = 3,
) -> pd.DataFrame:
    if len(date_group) <= limit:
        return date_group.sort_values("score", ascending=False)

    ordered = date_group.sort_values("score", ascending=False).copy()
    current_date = ordered["date"].iloc[0]
    history = return_matrix.loc[return_matrix.index < current_date].tail(lookback_days)
    selected_symbols: list[str] = []
    selected_rows: list[pd.Series] = []

    while len(selected_rows) < limit and not ordered.empty:
        best_idx = None
        best_value = None
        for idx, row in ordered.iterrows():
            candidate_value = float(row["score"])
            if selected_symbols and not history.empty:
                penalties = []
                for selected_symbol in selected_symbols:
                    if row["symbol"] not in history.columns or selected_symbol not in history.columns:
                        continue
                    corr = history[[row["symbol"], selected_symbol]].corr().iloc[0, 1]
                    if pd.notna(corr):
                        penalties.append(abs(float(corr)))
                avg_corr = sum(penalties) / len(penalties) if penalties else 0.0
                candidate_value -= avg_corr * 0.18

            if best_value is None or candidate_value > best_value:
                best_value = candidate_value
                best_idx = idx

        if best_idx is None:
            break

        chosen = ordered.loc[best_idx]
        selected_rows.append(chosen)
        selected_symbols.append(chosen["symbol"])
        ordered = ordered.drop(best_idx)

    return pd.DataFrame(selected_rows)


def _resolve_split_dates(features: pd.DataFrame, cfg: dict) -> tuple[list, list]:
    unique_dates = sorted(features["date"].dropna().unique())
    train_start_date = cfg.get("train_start_date")
    train_end_date = cfg.get("train_end_date")
    test_start_date = cfg.get("test_start_date")
    test_end_date = cfg.get("test_end_date")

    if any([train_start_date, train_end_date, test_start_date, test_end_date]):
        train_dates = [
            date_value
            for date_value in unique_dates
            if (not train_start_date or pd.Timestamp(date_value) >= pd.to_datetime(train_start_date))
            and (not train_end_date or pd.Timestamp(date_value) <= pd.to_datetime(train_end_date))
        ]
        test_dates = [
            date_value
            for date_value in unique_dates
            if (not test_start_date or pd.Timestamp(date_value) >= pd.to_datetime(test_start_date))
            and (not test_end_date or pd.Timestamp(date_value) <= pd.to_datetime(test_end_date))
        ]
        return train_dates, test_dates

    train_days = int(cfg.get("train_days", 252))
    test_days = int(cfg.get("test_days", 63))
    if len(unique_dates) <= train_days:
        return [], []

    split_index = max(train_days, len(unique_dates) - test_days)
    return unique_dates[:split_index], unique_dates[split_index:]


def generate_signals(
    features: pd.DataFrame,
    config: dict,
    holding_days: int,
    model_dir: Path | None = None,
):
    backtest_cfg = config["backtest"]
    walk_cfg = config["walkforward"]
    target_column = f"target_up_{holding_days}"

    usable = features.dropna(subset=FEATURE_COLUMNS + [target_column]).copy()
    train_dates, test_dates = _resolve_split_dates(usable, {**walk_cfg, **backtest_cfg})
    if not train_dates or not test_dates:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    train_df = usable[usable["date"].isin(train_dates)].copy().reset_index(drop=True)
    test_df = usable[usable["date"].isin(test_dates)].copy().reset_index(drop=True)
    if train_df.empty or test_df.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    logistic = LogisticRegression(max_iter=600, class_weight="balanced")
    boosting = HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.05,
        min_samples_leaf=25,
        random_state=42,
    )
    forest = RandomForestClassifier(
        n_estimators=220,
        max_depth=7,
        min_samples_leaf=18,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    )

    logistic.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))
    boosting.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))
    forest.fit(train_df[FEATURE_COLUMNS], train_df[target_column].astype(int))

    event_mask = _event_filter(test_df)
    pullback_mask = _pullback_filter(test_df)
    rebound_mask = _rebound_filter(test_df)
    candidate_df = test_df[event_mask | pullback_mask | rebound_mask].copy()
    if candidate_df.empty:
        return pd.DataFrame(columns=["date", "symbol", "score"]), []

    logistic_score = logistic.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    boosting_score = boosting.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    forest_score = forest.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]

    candidate_df["logistic_score"] = logistic_score[candidate_df.index]
    candidate_df["boosting_score"] = boosting_score[candidate_df.index]
    candidate_df["forest_score"] = forest_score[candidate_df.index]
    candidate_df["event_bonus"] = event_mask[candidate_df.index].astype(float)
    candidate_df["pullback_bonus"] = pullback_mask[candidate_df.index].astype(float)
    candidate_df["rebound_bonus"] = rebound_mask[candidate_df.index].astype(float)

    candidate_df["event_rule_score"] = (
        candidate_df["range_pct"] * 5.0
        + candidate_df["volume_ratio_20"] * 0.4
        + candidate_df["ret_1"].clip(lower=0.0) * 10.0
        + candidate_df["breakout_strength"] * 3.0
    )
    candidate_df["pullback_rule_score"] = (
        candidate_df["ret_20"] * 35.0
        + candidate_df["rebound_strength"] * 7.0
        + candidate_df["intraday_return"] * 20.0
        - candidate_df["ret_5"].abs() * 8.0
    )
    candidate_df["rebound_rule_score"] = (
        (-candidate_df["drawdown_20"]) * 5.0
        + candidate_df["intraday_return"] * 35.0
        + candidate_df["volume_ratio_20"] * 0.4
        - candidate_df["ret_5"].abs() * 6.0
    )
    candidate_df["rule_score"] = (
        candidate_df["event_rule_score"] * candidate_df["event_bonus"]
        + candidate_df["pullback_rule_score"] * candidate_df["pullback_bonus"]
        + candidate_df["rebound_rule_score"] * candidate_df["rebound_bonus"]
    )
    candidate_df["score"] = (
        candidate_df["logistic_score"] * 0.18
        + candidate_df["boosting_score"] * 0.38
        + candidate_df["forest_score"] * 0.24
        + candidate_df["rule_score"] * 0.16
        + candidate_df["event_bonus"] * 0.02
        + candidate_df["pullback_bonus"] * 0.01
        + candidate_df["rebound_bonus"] * 0.01
    )

    return_matrix = _build_return_matrix(features)
    diversified = []
    for _, date_group in candidate_df.groupby("date", sort=False):
        diversified.append(_select_diversified(date_group, return_matrix, limit=3))
    candidate_df = pd.concat(diversified, ignore_index=True)
    candidate_df = candidate_df.sort_values(["date", "score"], ascending=[True, False])
    candidate_df = candidate_df.drop_duplicates(subset=["date", "symbol"], keep="first")

    folds = [
        {
            "fold": 1,
            "holding_days": holding_days,
            "train_start": pd.Timestamp(train_dates[0]).strftime("%Y-%m-%d"),
            "train_end": pd.Timestamp(train_dates[-1]).strftime("%Y-%m-%d"),
            "test_start": pd.Timestamp(test_dates[0]).strftime("%Y-%m-%d"),
            "test_end": pd.Timestamp(test_dates[-1]).strftime("%Y-%m-%d"),
            "train_rows": int(len(train_df)),
            "test_rows": int(len(candidate_df)),
            "model_path": None,
        }
    ]

    if model_dir is not None:
        ensure_dir(model_dir)
        model_path = model_dir / "fold_01.pkl"
        with model_path.open("wb") as handle:
            pickle.dump(
                {
                    "logistic": logistic,
                    "boosting": boosting,
                    "forest": forest,
                    "holding_days": holding_days,
                    "train_start": folds[0]["train_start"],
                    "train_end": folds[0]["train_end"],
                    "test_start": folds[0]["test_start"],
                    "test_end": folds[0]["test_end"],
                    "candidate_count": int(len(candidate_df)),
                },
                handle,
            )
        folds[0]["model_path"] = str(model_path)

    return candidate_df[["date", "symbol", "score"]], folds
