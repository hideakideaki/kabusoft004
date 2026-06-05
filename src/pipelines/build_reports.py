from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import STRATEGY_IDS, load_run_snapshot, project_root, relative_to_root


def score(snapshot) -> tuple[float, float, float]:
    metrics = snapshot.metrics
    return (
        float(metrics.get("sharpe", float("-inf"))),
        float(metrics.get("cagr", float("-inf"))),
        float(metrics.get("max_drawdown", float("-inf"))),
    )


def rank_snapshots(snapshots: list[Any]) -> list[Any]:
    return sorted(snapshots, key=score, reverse=True)


def write_strategy_ranking(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "strategy_ranking.csv"
    fieldnames = [
        "rank",
        "strategy_id",
        "strategy_name",
        "strategy_type",
        "status",
        "cagr",
        "max_drawdown",
        "sharpe",
        "win_rate",
        "num_trades",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, snapshot in enumerate(ranked, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "strategy_id": snapshot.strategy_id,
                    "strategy_name": snapshot.meta.get("strategy_name", snapshot.strategy_id),
                    "strategy_type": snapshot.meta.get("strategy_type", ""),
                    "status": snapshot.meta.get("status", ""),
                    "cagr": snapshot.metrics.get("cagr", ""),
                    "max_drawdown": snapshot.metrics.get("max_drawdown", ""),
                    "sharpe": snapshot.metrics.get("sharpe", ""),
                    "win_rate": snapshot.metrics.get("win_rate", ""),
                    "num_trades": snapshot.metrics.get("num_trades", ""),
                }
            )

    return output_path


def _summary_line(summary_text: str) -> str:
    if not summary_text:
        return "要約なし"
    for line in summary_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "要約なし"


def _display_strategy_type(value: str) -> str:
    mapping = {
        "benchmark": "ベンチマーク",
        "rule_based": "ルールベース",
        "ml_based": "機械学習",
    }
    return mapping.get(value, value)


def _display_status(value: str) -> str:
    mapping = {
        "placeholder": "プレースホルダー",
        "completed": "完了",
        "failed": "失敗",
    }
    return mapping.get(value, value)


def write_strategy_comparison(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "strategy_comparison.md"
    lines = [
        "# strategy_comparison.md",
        "",
        "## 全体比較",
        "",
        "| 順位 | 戦略ID | 種別 | 状態 | Sharpe | CAGR | 最大ドローダウン | 取引数 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]

    for index, snapshot in enumerate(ranked, start=1):
        lines.append(
            "| {rank} | {strategy} | {strategy_type} | {status} | {sharpe} | {cagr} | {max_drawdown} | {num_trades} |".format(
                rank=index,
                strategy=snapshot.strategy_id,
                strategy_type=_display_strategy_type(snapshot.meta.get("strategy_type", "")),
                status=_display_status(snapshot.meta.get("status", "")),
                sharpe=snapshot.metrics.get("sharpe", ""),
                cagr=snapshot.metrics.get("cagr", ""),
                max_drawdown=snapshot.metrics.get("max_drawdown", ""),
                num_trades=snapshot.metrics.get("num_trades", ""),
            )
        )

    lines.extend(["", "## 戦略メモ", ""])
    for snapshot in ranked:
        lines.extend(
            [
                f"### {snapshot.strategy_id}",
                "",
                f"- 戦略名: {snapshot.meta.get('strategy_name', snapshot.strategy_id)}",
                f"- 種別: {_display_strategy_type(snapshot.meta.get('strategy_type', ''))}",
                f"- 状態: {_display_status(snapshot.meta.get('status', ''))}",
                f"- ベンチマーク: {'はい' if snapshot.meta.get('benchmark', False) else 'いいえ'}",
                f"- 要約: {_summary_line(snapshot.summary_text)}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_final_summary(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "final_summary.md"
    benchmark = next((item for item in ranked if item.meta.get("benchmark")), None)
    best_overall = ranked[0] if ranked else None
    best_rule = next((item for item in ranked if item.meta.get("strategy_type") == "rule_based"), None)
    best_ml = next((item for item in ranked if item.meta.get("strategy_type") == "ml_based"), None)

    lines = ["# final_summary.md", "", "## サマリー", ""]
    if best_overall:
        lines.append(
            f"- Sharpe 首位: {best_overall.strategy_id} (Sharpe {best_overall.metrics.get('sharpe', '')}, CAGR {best_overall.metrics.get('cagr', '')})"
        )
    if best_rule:
        lines.append(
            f"- ルールベース首位: {best_rule.strategy_id} (Sharpe {best_rule.metrics.get('sharpe', '')})"
        )
    if best_ml:
        lines.append(
            f"- 機械学習首位: {best_ml.strategy_id} (Sharpe {best_ml.metrics.get('sharpe', '')})"
        )
    if benchmark:
        lines.append(
            f"- ベンチマーク: {benchmark.strategy_id} (Sharpe {benchmark.metrics.get('sharpe', '')}, CAGR {benchmark.metrics.get('cagr', '')})"
        )

    lines.extend(["", "## 備考", ""])
    lines.append("- `strategy_ranking.csv` は全期間の成績比較、`operational_selection.*` は実運用向けの長期安定性と直近成績の併記に使う。")
    lines.append("- split 設定を使った run と全期間 run を混在させると比較が崩れるため、運用判断前には同一設定で全戦略を再実行する。")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _load_equity_frame(snapshot) -> pd.DataFrame:
    path = snapshot.run_dir / "equity.csv"
    if not path.exists():
        return pd.DataFrame(columns=["date", "equity"])
    equity = pd.read_csv(path)
    if equity.empty:
        return pd.DataFrame(columns=["date", "equity"])
    equity["date"] = pd.to_datetime(equity["date"])
    equity = equity.sort_values("date").reset_index(drop=True)
    equity["daily_return"] = equity["equity"].pct_change().fillna(0.0)
    return equity


def _recent_window_metrics(equity: pd.DataFrame, window_days: int) -> dict[str, float | str]:
    if equity.empty:
        return {"return": "", "sharpe": "", "max_drawdown": "", "rows": 0}
    tail = equity.tail(window_days).copy()
    if len(tail) < 2:
        return {"return": "", "sharpe": "", "max_drawdown": "", "rows": int(len(tail))}
    total_return = float(tail["equity"].iloc[-1] / tail["equity"].iloc[0] - 1.0)
    daily_returns = tail["daily_return"].iloc[1:]
    std = float(daily_returns.std(ddof=0))
    sharpe = 0.0 if std == 0.0 else float(daily_returns.mean() / std * (252 ** 0.5))
    running_max = tail["equity"].cummax()
    drawdown = float((tail["equity"] / running_max - 1.0).min())
    return {
        "return": round(total_return, 6),
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(drawdown, 6),
        "rows": int(len(tail)),
    }


def _selected_fold_count(snapshot) -> int:
    selected = snapshot.meta.get("selected_holding_days")
    folds = snapshot.meta.get("walkforward_folds", {})
    if selected is None or not isinstance(folds, dict):
        return 0
    selected_folds = folds.get(str(selected), [])
    return len(selected_folds) if isinstance(selected_folds, list) else 0


def _last_fold_end(snapshot) -> str:
    selected = snapshot.meta.get("selected_holding_days")
    folds = snapshot.meta.get("walkforward_folds", {})
    if selected is None or not isinstance(folds, dict):
        return ""
    selected_folds = folds.get(str(selected), [])
    if not isinstance(selected_folds, list) or not selected_folds:
        return ""
    return str(selected_folds[-1].get("test_end", ""))


def _operational_rows(ranked: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in ranked:
        if snapshot.meta.get("benchmark"):
            continue
        equity = _load_equity_frame(snapshot)
        recent_20 = _recent_window_metrics(equity, 20)
        recent_60 = _recent_window_metrics(equity, 60)
        fold_count = _selected_fold_count(snapshot)
        long_term_sharpe = float(snapshot.metrics.get("sharpe", 0.0))
        score = (
            long_term_sharpe * 0.40
            + float(recent_60.get("sharpe") or 0.0) * 0.35
            + float(recent_20.get("sharpe") or 0.0) * 0.25
        )
        rows.append(
            {
                "strategy_id": snapshot.strategy_id,
                "strategy_type": snapshot.meta.get("strategy_type", ""),
                "long_term_sharpe": round(long_term_sharpe, 6),
                "long_term_cagr": snapshot.metrics.get("cagr", ""),
                "long_term_max_drawdown": snapshot.metrics.get("max_drawdown", ""),
                "recent_20d_return": recent_20["return"],
                "recent_20d_sharpe": recent_20["sharpe"],
                "recent_20d_max_drawdown": recent_20["max_drawdown"],
                "recent_60d_return": recent_60["return"],
                "recent_60d_sharpe": recent_60["sharpe"],
                "recent_60d_max_drawdown": recent_60["max_drawdown"],
                "selected_holding_days": snapshot.meta.get("selected_holding_days", ""),
                "walkforward_fold_count": fold_count,
                "last_fold_test_end": _last_fold_end(snapshot),
                "num_trades": snapshot.metrics.get("num_trades", ""),
                "operational_score": round(score, 6),
            }
        )
    rows.sort(
        key=lambda item: (
            float(item["walkforward_fold_count"]),
            float(item["operational_score"]),
            float(item["long_term_sharpe"]),
        ),
        reverse=True,
    )
    return rows


def write_operational_selection_csv(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "operational_selection.csv"
    rows = _operational_rows(ranked)
    fieldnames = [
        "rank",
        "strategy_id",
        "strategy_type",
        "long_term_sharpe",
        "long_term_cagr",
        "long_term_max_drawdown",
        "recent_20d_return",
        "recent_20d_sharpe",
        "recent_20d_max_drawdown",
        "recent_60d_return",
        "recent_60d_sharpe",
        "recent_60d_max_drawdown",
        "selected_holding_days",
        "walkforward_fold_count",
        "last_fold_test_end",
        "num_trades",
        "operational_score",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({"rank": index, **row})
    return output_path


def write_operational_selection_md(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "operational_selection.md"
    rows = _operational_rows(ranked)
    lines = [
        "# operational_selection.md",
        "",
        "## 使い方",
        "",
        "- まず `long_term_sharpe` と `long_term_max_drawdown` で長期的に崩れにくい戦略を絞る。",
        "- そのうえで `recent_20d_*` と `recent_60d_*` を見て、直近の勢いがある戦略を明日用に採用する。",
        "- `walkforward_fold_count` が多いほど、直近評価も時系列に沿って確認できている。",
        "",
        "## 運用選定候補",
        "",
        "| 順位 | 戦略ID | 種別 | 長期Sharpe | 直近20日Sharpe | 直近60日Sharpe | 長期DD | fold数 | 最終fold終端 | 運用スコア |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {strategy_id} | {strategy_type} | {long_term_sharpe} | {recent_20d_sharpe} | {recent_60d_sharpe} | {long_term_max_drawdown} | {walkforward_fold_count} | {last_fold_test_end} | {operational_score} |".format(
                rank=index,
                strategy_id=row["strategy_id"],
                strategy_type=_display_strategy_type(row["strategy_type"]),
                long_term_sharpe=row["long_term_sharpe"],
                recent_20d_sharpe=row["recent_20d_sharpe"],
                recent_60d_sharpe=row["recent_60d_sharpe"],
                long_term_max_drawdown=row["long_term_max_drawdown"],
                walkforward_fold_count=row["walkforward_fold_count"],
                last_fold_test_end=row["last_fold_test_end"] or "-",
                operational_score=row["operational_score"],
            )
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _load_trades_frame(snapshot) -> pd.DataFrame:
    path = snapshot.run_dir / "trades.csv"
    if not path.exists():
        return pd.DataFrame()
    trades = pd.read_csv(path)
    if trades.empty:
        return trades
    for column in ("entry_price", "exit_price", "shares", "return"):
        if column in trades.columns:
            trades[column] = pd.to_numeric(trades[column], errors="coerce")
    if "pnl" not in trades.columns and {"entry_price", "exit_price", "shares"}.issubset(trades.columns):
        trades["pnl"] = (trades["exit_price"] - trades["entry_price"]) * trades["shares"]
    if "entry_value" not in trades.columns and {"entry_price", "shares"}.issubset(trades.columns):
        trades["entry_value"] = trades["entry_price"] * trades["shares"]
    return trades


def _pnl_share(value: float, total_positive_pnl: float) -> float:
    if total_positive_pnl <= 0:
        return 0.0
    return round(float(value) / total_positive_pnl, 6)


def _outlier_rows(ranked: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snapshot in ranked:
        trades = _load_trades_frame(snapshot)
        if trades.empty or "pnl" not in trades.columns:
            rows.append(
                {
                    "strategy_id": snapshot.strategy_id,
                    "num_trades": 0,
                    "total_pnl": 0.0,
                    "total_positive_pnl": 0.0,
                    "top_trade_pnl_share": 0.0,
                    "top_5_trades_pnl_share": 0.0,
                    "top_symbol": "",
                    "top_symbol_pnl_share": 0.0,
                    "max_trade_return": 0.0,
                    "trades_return_ge_50pct": 0,
                    "trades_return_ge_100pct": 0,
                }
            )
            continue

        working = trades.copy()
        working["pnl"] = pd.to_numeric(working["pnl"], errors="coerce").fillna(0.0)
        positive = working[working["pnl"] > 0].sort_values("pnl", ascending=False)
        total_pnl = float(working["pnl"].sum())
        total_positive_pnl = float(positive["pnl"].sum())
        top_trade_pnl = float(positive["pnl"].iloc[0]) if not positive.empty else 0.0
        top_5_trade_pnl = float(positive["pnl"].head(5).sum()) if not positive.empty else 0.0

        by_symbol = (
            working.groupby("code", dropna=False)["pnl"].sum().sort_values(ascending=False)
            if "code" in working.columns
            else pd.Series(dtype=float)
        )
        top_symbol = str(by_symbol.index[0]) if not by_symbol.empty else ""
        top_symbol_pnl = float(by_symbol.iloc[0]) if not by_symbol.empty else 0.0

        returns = pd.to_numeric(working.get("return", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        rows.append(
            {
                "strategy_id": snapshot.strategy_id,
                "num_trades": int(len(working)),
                "total_pnl": round(total_pnl, 6),
                "total_positive_pnl": round(total_positive_pnl, 6),
                "top_trade_pnl_share": _pnl_share(top_trade_pnl, total_positive_pnl),
                "top_5_trades_pnl_share": _pnl_share(top_5_trade_pnl, total_positive_pnl),
                "top_symbol": top_symbol,
                "top_symbol_pnl_share": _pnl_share(top_symbol_pnl, total_positive_pnl),
                "max_trade_return": round(float(returns.max()), 6) if len(returns) else 0.0,
                "trades_return_ge_50pct": int((returns >= 0.50).sum()),
                "trades_return_ge_100pct": int((returns >= 1.00).sum()),
            }
        )
    rows.sort(
        key=lambda item: (
            float(item["top_5_trades_pnl_share"]),
            float(item["top_symbol_pnl_share"]),
            float(item["max_trade_return"]),
        ),
        reverse=True,
    )
    return rows


def write_outlier_contribution_csv(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "outlier_contribution.csv"
    rows = _outlier_rows(ranked)
    fieldnames = [
        "rank",
        "strategy_id",
        "num_trades",
        "total_pnl",
        "total_positive_pnl",
        "top_trade_pnl_share",
        "top_5_trades_pnl_share",
        "top_symbol",
        "top_symbol_pnl_share",
        "max_trade_return",
        "trades_return_ge_50pct",
        "trades_return_ge_100pct",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({"rank": index, **row})
    return output_path


def write_outlier_contribution_md(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "outlier_contribution.md"
    rows = _outlier_rows(ranked)
    lines = [
        "# outlier_contribution.md",
        "",
        "## Purpose",
        "",
        "- Shows whether each strategy's profit depends heavily on a small number of trades or symbols.",
        "- `*_pnl_share` uses positive PnL as the denominator, so a high value means concentrated profit contribution.",
        "",
        "| Rank | Strategy | Trades | Top trade share | Top 5 trades share | Top symbol | Top symbol share | Max return | >=50% trades | >=100% trades |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {strategy_id} | {num_trades} | {top_trade_pnl_share} | {top_5_trades_pnl_share} | {top_symbol} | {top_symbol_pnl_share} | {max_trade_return} | {trades_return_ge_50pct} | {trades_return_ge_100pct} |".format(
                rank=index,
                **row,
            )
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _latest_market_date(ranked: list[Any]) -> str:
    benchmark = next((snapshot for snapshot in ranked if snapshot.meta.get("benchmark")), None)
    if benchmark is not None:
        equity = _load_equity_frame(benchmark)
        if not equity.empty:
            return equity["date"].max().strftime("%Y-%m-%d")

    latest = ""
    for snapshot in ranked:
        equity = _load_equity_frame(snapshot)
        if equity.empty:
            continue
        candidate = equity["date"].max().strftime("%Y-%m-%d")
        if candidate > latest:
            latest = candidate
    return latest


def _candidate_max_date(snapshot) -> str:
    path = snapshot.run_dir / "candidates.csv"
    if not path.exists():
        return ""
    candidates = pd.read_csv(path)
    if candidates.empty or "date" not in candidates.columns:
        return ""
    return str(pd.to_datetime(candidates["date"]).max().strftime("%Y-%m-%d"))


def _load_candidates_for_date(snapshot, target_date: str) -> pd.DataFrame:
    path = snapshot.run_dir / "candidates.csv"
    if not path.exists():
        return pd.DataFrame()
    candidates = pd.read_csv(path)
    if candidates.empty or "date" not in candidates.columns:
        return pd.DataFrame()
    candidates["date"] = pd.to_datetime(candidates["date"]).dt.strftime("%Y-%m-%d")
    return candidates[candidates["date"] == target_date].copy()


def _heuristic_consensus_score(row: dict[str, Any]) -> float:
    return (
        float(row["weighted_support"])
        + float(row["support_count"]) * 0.5
        + (0.75 if row["stable_confirmation"] else 0.0)
        - float(row["avg_signal_rank"]) * 0.05
    )


def _main_strategy_rows(ranked: list[Any]) -> list[dict[str, Any]]:
    latest_market_date = _latest_market_date(ranked)
    rows: list[dict[str, Any]] = []
    for snapshot in ranked:
        if snapshot.meta.get("benchmark"):
            continue

        strategy_type = snapshot.meta.get("strategy_type", "")
        fold_count = _selected_fold_count(snapshot)
        long_term_sharpe = float(snapshot.metrics.get("sharpe", 0.0))
        candidate_max_date = _candidate_max_date(snapshot)

        equity = _load_equity_frame(snapshot)
        recent_20 = _recent_window_metrics(equity, 20)
        recent_60 = _recent_window_metrics(equity, 60)
        recent_20_return = float(recent_20.get("return") or 0.0)
        recent_60_sharpe = float(recent_60.get("sharpe") or 0.0)
        is_fresh = bool(candidate_max_date) and candidate_max_date == latest_market_date

        if strategy_type == "ml_based":
            robust = fold_count >= 20
            perform = long_term_sharpe >= 0.5 and recent_60_sharpe > 0.0
            eligible = robust and perform and is_fresh
            reason = []
            if robust:
                reason.append("walkforward十分")
            else:
                reason.append("walkforward不足")
            if long_term_sharpe >= 0.5:
                reason.append("長期Sharpe通過")
            else:
                reason.append("長期Sharpe不足")
            if recent_60_sharpe > 0.0:
                reason.append("直近60日通過")
            else:
                reason.append("直近60日不通過")
        else:
            robust = True
            perform = long_term_sharpe >= 0.45 and recent_60_sharpe > 0.0 and recent_20_return >= 0.0
            eligible = perform and is_fresh
            reason = []
            if long_term_sharpe >= 0.45:
                reason.append("長期Sharpe通過")
            else:
                reason.append("長期Sharpe不足")
            if recent_60_sharpe > 0.0:
                reason.append("直近60日通過")
            else:
                reason.append("直近60日不通過")
            if recent_20_return >= 0.0:
                reason.append("直近20日通過")
            else:
                reason.append("直近20日不通過")

        rows.append(
            {
                "strategy_id": snapshot.strategy_id,
                "strategy_type": strategy_type,
                "long_term_sharpe": round(long_term_sharpe, 6),
                "recent_60d_sharpe": recent_60.get("sharpe", ""),
                "recent_20d_return": recent_20.get("return", ""),
                "walkforward_fold_count": fold_count,
                "candidate_max_date": candidate_max_date,
                "latest_market_date": latest_market_date,
                "is_fresh": is_fresh,
                "eligible_as_main": eligible,
                "reason": " / ".join(reason),
            }
        )

    rows.sort(
        key=lambda item: (
            int(item["eligible_as_main"]),
            int(item["is_fresh"]),
            float(item["long_term_sharpe"]),
            float(item["recent_60d_sharpe"] or 0.0),
        ),
        reverse=True,
    )
    return rows


def write_main_strategy_selection_csv(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "main_strategy_selection.csv"
    rows = _main_strategy_rows(ranked)
    fieldnames = [
        "rank",
        "strategy_id",
        "strategy_type",
        "long_term_sharpe",
        "recent_60d_sharpe",
        "recent_20d_return",
        "walkforward_fold_count",
        "candidate_max_date",
        "latest_market_date",
        "is_fresh",
        "eligible_as_main",
        "reason",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({"rank": index, **row})
    return output_path


def write_main_strategy_selection_md(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "main_strategy_selection.md"
    rows = _main_strategy_rows(ranked)
    lines = [
        "# main_strategy_selection.md",
        "",
        "## 主力選定ルール",
        "",
        "- `ml_based` は `walkforward_fold_count >= 20` かつ `long_term_sharpe >= 0.5` かつ `recent_60d_sharpe > 0` を主力候補とする。",
        "- `rule_based` は `long_term_sharpe >= 0.45` かつ `recent_60d_sharpe > 0` かつ `recent_20d_return >= 0` を主力候補とする。",
        "- さらに `candidate_max_date` が市場最新日と一致する戦略だけを、翌営業日向けの fresh な候補源として使う。",
        "",
        "## 主力候補一覧",
        "",
        "| 順位 | 戦略ID | 種別 | 長期Sharpe | 直近60日Sharpe | 直近20日Return | fold数 | 候補最新日 | fresh | 主力採用 | 判定理由 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {strategy_id} | {strategy_type} | {long_term_sharpe} | {recent_60d_sharpe} | {recent_20d_return} | {walkforward_fold_count} | {candidate_max_date} | {is_fresh} | {eligible_as_main} | {reason} |".format(
                rank=index,
                strategy_id=row["strategy_id"],
                strategy_type=_display_strategy_type(row["strategy_type"]),
                long_term_sharpe=row["long_term_sharpe"],
                recent_60d_sharpe=row["recent_60d_sharpe"],
                recent_20d_return=row["recent_20d_return"],
                walkforward_fold_count=row["walkforward_fold_count"],
                candidate_max_date=row["candidate_max_date"] or "-",
                is_fresh="yes" if row["is_fresh"] else "no",
                eligible_as_main="yes" if row["eligible_as_main"] else "no",
                reason=row["reason"],
            )
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _latest_consensus_rows(ranked: list[Any]) -> list[dict[str, Any]]:
    main_rows = [row for row in _main_strategy_rows(ranked) if row["eligible_as_main"]]
    if not main_rows:
        return []

    latest_market_date = main_rows[0]["latest_market_date"]
    snapshot_map = {snapshot.strategy_id: snapshot for snapshot in ranked}
    main_ids = [row["strategy_id"] for row in main_rows]
    support_snapshot = snapshot_map.get("worker_15b")
    support_fresh = support_snapshot is not None and _candidate_max_date(support_snapshot) == latest_market_date
    support_candidates = (
        _load_candidates_for_date(support_snapshot, latest_market_date) if support_fresh else pd.DataFrame()
    )
    support_symbols = set(support_candidates["symbol"]) if not support_candidates.empty else set()

    symbol_rows: dict[str, dict[str, Any]] = {}
    for strategy_id in main_ids:
        snapshot = snapshot_map[strategy_id]
        candidates = _load_candidates_for_date(snapshot, latest_market_date)
        if candidates.empty:
            continue
        weight = float(snapshot.metrics.get("sharpe", 0.0)) + max(
            float(_recent_window_metrics(_load_equity_frame(snapshot), 60).get("sharpe") or 0.0),
            0.0,
        )
        for row in candidates.to_dict("records"):
            symbol = str(row["symbol"])
            bucket = symbol_rows.setdefault(
                symbol,
                {
                    "date": latest_market_date,
                    "symbol": symbol,
                    "support_count": 0,
                    "weighted_support": 0.0,
                    "avg_signal_rank": 0.0,
                    "strategies": [],
                    "stable_confirmation": symbol in support_symbols,
                },
            )
            bucket["support_count"] += 1
            bucket["weighted_support"] += weight
            bucket["avg_signal_rank"] += float(row.get("signal_rank", 0) or 0)
            bucket["strategies"].append(strategy_id)
            bucket["stable_confirmation"] = bucket["stable_confirmation"] or (symbol in support_symbols)

    rows: list[dict[str, Any]] = []
    for item in symbol_rows.values():
        count = item["support_count"]
        avg_rank = item["avg_signal_rank"] / count if count else 0.0
        row = {
            "date": item["date"],
            "symbol": item["symbol"],
            "support_count": count,
            "weighted_support": round(item["weighted_support"], 6),
            "avg_signal_rank": round(avg_rank, 4),
            "stable_confirmation": item["stable_confirmation"],
            "support_strategies": "|".join(item["strategies"]),
        }
        row["final_score"] = round(_heuristic_consensus_score(row), 6)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            int(item["support_count"]),
            float(item["final_score"]),
            -float(item["avg_signal_rank"]),
        ),
        reverse=True,
    )
    return rows


def write_latest_consensus_candidates_csv(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "latest_consensus_candidates.csv"
    rows = _latest_consensus_rows(ranked)
    fieldnames = [
        "rank",
        "date",
        "symbol",
        "support_count",
        "weighted_support",
        "avg_signal_rank",
        "stable_confirmation",
        "support_strategies",
        "final_score",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow({"rank": index, **row})
    return output_path


def write_latest_consensus_candidates_md(root: Path, ranked: list[Any]) -> Path:
    output_path = root / "reports" / "latest_consensus_candidates.md"
    rows = _latest_consensus_rows(ranked)
    main_rows = [row for row in _main_strategy_rows(ranked) if row["eligible_as_main"]]
    latest_market_date = main_rows[0]["latest_market_date"] if main_rows else ""
    lines = [
        "# latest_consensus_candidates.md",
        "",
        "## 使い方",
        "",
        "- `main_strategy_selection.md` で主力採用になった戦略だけを対象に、最新市場日で重なった銘柄を集計している。",
        "- `stable_confirmation` は `worker_15b` が同日同銘柄を出しているかを表す。`worker_15b` が stale の日は全件 `false` になる。",
        f"- 現在の集計対象日: {latest_market_date or '-'}",
        "",
        "## 統合候補",
        "",
        "## 列の意味",
        "",
        "- `順位`: 統合候補内の順位。`support_count`、`final_score`、`avg_signal_rank` の順で並べている。",
        "- `日付`: 候補を集計した市場日。",
        "- `銘柄`: 銘柄コード。",
        "- `支持戦略数`: 主力採用戦略のうち、その銘柄を候補に出した戦略数。",
        "- `重み付き支持`: 支持した各戦略の長期 Sharpe と直近60日 Sharpe を加味した支持の合計。",
        "- `平均順位`: 支持した各戦略内での `signal_rank` の平均。小さいほど各戦略で上位に出ている。",
        "- `stable確認`: 補助確認用の `worker_15b` も同じ日に同銘柄を候補に出しているか。",
        "- `戦略一覧`: その銘柄を支持した戦略IDの一覧。",
        "- `最終スコア`: 統合候補の並び替え用スコア。重み付き支持、支持戦略数、stable確認を加点し、平均順位が低いほど減点する暫定式。",
        "",
        "| 順位 | 日付 | 銘柄 | 支持戦略数 | 重み付き支持 | 平均順位 | stable確認 | 戦略一覧 | 最終スコア |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            "| {rank} | {date} | {symbol} | {support_count} | {weighted_support} | {avg_signal_rank} | {stable_confirmation} | {support_strategies} | {final_score} |".format(
                rank=index,
                **row,
            )
        )
    if not rows:
        lines.extend(["", "最新市場日で重なった候補はありません。"])
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_manifests(root: Path, ranked: list[Any], report_paths: list[Path]) -> tuple[Path, Path]:
    generated_at = datetime.now(timezone.utc).isoformat()

    runs_manifest_path = root / "runs" / "manifest.json"
    runs_manifest = {
        "generated_at": generated_at,
        "strategies": [
            {
                "strategy_id": snapshot.strategy_id,
                "path": relative_to_root(snapshot.run_dir, root),
                "meta": snapshot.meta,
                "metrics": snapshot.metrics,
                "row_counts": snapshot.row_counts,
                "files": snapshot.files,
                "issues": snapshot.issues,
            }
            for snapshot in ranked
        ],
    }
    runs_manifest_path.write_text(
        json.dumps(runs_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reports_manifest_path = root / "reports" / "manifest.json"
    reports_manifest = {
        "generated_at": generated_at,
        "reports": [relative_to_root(path, root) for path in report_paths],
        "runs_manifest": relative_to_root(runs_manifest_path, root),
        "strategy_ids": list(STRATEGY_IDS),
    }
    reports_manifest_path.write_text(
        json.dumps(reports_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return runs_manifest_path, reports_manifest_path


def write_report_archive(root: Path, ranked: list[Any], report_paths: list[Path]) -> Path:
    generated_at = datetime.now(timezone.utc).isoformat()
    archive_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = root / "reports" / "archive" / archive_id
    archive_dir.mkdir(parents=True, exist_ok=False)

    for path in report_paths:
        if path.exists():
            shutil.copy2(path, archive_dir / path.name)

    meta = {
        "generated_at": generated_at,
        "latest_market_date": _latest_market_date(ranked),
        "files": [path.name for path in report_paths if path.exists()],
        "note": "Snapshot of decision reports at report build time.",
    }
    (archive_dir / "archive_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return archive_dir


def build_reports(root: Path) -> dict[str, Any]:
    snapshots = [load_run_snapshot(root, strategy_id) for strategy_id in STRATEGY_IDS]
    ranked = rank_snapshots(snapshots)

    ranking_path = write_strategy_ranking(root, ranked)
    comparison_path = write_strategy_comparison(root, ranked)
    final_summary_path = write_final_summary(root, ranked)
    operational_csv_path = write_operational_selection_csv(root, ranked)
    operational_md_path = write_operational_selection_md(root, ranked)
    outlier_contribution_csv_path = write_outlier_contribution_csv(root, ranked)
    outlier_contribution_md_path = write_outlier_contribution_md(root, ranked)
    main_selection_csv_path = write_main_strategy_selection_csv(root, ranked)
    main_selection_md_path = write_main_strategy_selection_md(root, ranked)
    latest_consensus_csv_path = write_latest_consensus_candidates_csv(root, ranked)
    latest_consensus_md_path = write_latest_consensus_candidates_md(root, ranked)
    runs_manifest_path, reports_manifest_path = write_manifests(
        root,
        ranked,
        [
            ranking_path,
            comparison_path,
            final_summary_path,
            operational_csv_path,
            operational_md_path,
            outlier_contribution_csv_path,
            outlier_contribution_md_path,
            main_selection_csv_path,
            main_selection_md_path,
            latest_consensus_csv_path,
            latest_consensus_md_path,
        ],
    )
    archive_dir = write_report_archive(
        root,
        ranked,
        [
            ranking_path,
            comparison_path,
            final_summary_path,
            operational_csv_path,
            operational_md_path,
            outlier_contribution_csv_path,
            outlier_contribution_md_path,
            main_selection_csv_path,
            main_selection_md_path,
            latest_consensus_csv_path,
            latest_consensus_md_path,
            reports_manifest_path,
        ],
    )

    return {
        "ranking": ranking_path,
        "comparison": comparison_path,
        "final_summary": final_summary_path,
        "operational_selection_csv": operational_csv_path,
        "operational_selection_md": operational_md_path,
        "outlier_contribution_csv": outlier_contribution_csv_path,
        "outlier_contribution_md": outlier_contribution_md_path,
        "main_strategy_selection_csv": main_selection_csv_path,
        "main_strategy_selection_md": main_selection_md_path,
        "latest_consensus_candidates_csv": latest_consensus_csv_path,
        "latest_consensus_candidates_md": latest_consensus_md_path,
        "runs_manifest": runs_manifest_path,
        "reports_manifest": reports_manifest_path,
        "archive_dir": archive_dir,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build comparable strategy reports from runs artifacts.")
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="Repository root. Defaults to the current project root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outputs = build_reports(args.root.resolve())
    print(
        json.dumps(
            {key: str(value) for key, value in outputs.items()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
