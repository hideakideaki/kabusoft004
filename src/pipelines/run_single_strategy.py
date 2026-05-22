from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.backtest_engine import run_backtest
from src.core.contracts import STRATEGY_IDS, project_root
from src.core.data_loader import (
    apply_backtest_date_range,
    apply_test_date_range,
    load_backtest_config,
    load_feature_config,
    load_market_data,
    load_walkforward_config,
)
from src.core.feature_engineering import build_features
from src.core.metrics import calculate_metrics
from src.core.utils import ensure_dir
from src.pipelines.build_reports import build_reports
from src.strategies.benchmark_buy_and_hold import run_benchmark


STRATEGY_MODULES = {
    "worker_01": "src.strategies.worker_01_breakout_volume",
    "worker_02": "src.strategies.worker_02_mean_reversion_rebound",
    "worker_03": "src.strategies.worker_03_volatility_expansion",
    "worker_04": "src.strategies.worker_04_logistic_regression",
    "worker_05": "src.strategies.worker_05_gradient_boosting",
    "worker_06": "src.strategies.worker_06_random_forest",
    "worker_07": "src.strategies.worker_07_hybrid_event_ml",
    "worker_08": "src.strategies.worker_08_hybrid_event_ml_compact",
    "worker_09": "src.strategies.worker_09_trend_pullback",
    "worker_10": "src.strategies.worker_10_hybrid_event_pullback",
    "worker_10b": "src.strategies.worker_10b_hybrid_event_pullback_defensive",
    "worker_10c": "src.strategies.worker_10c_hybrid_event_pullback_diversified",
    "worker_10d": "src.strategies.worker_10d_hybrid_event_pullback_correlation",
    "worker_10e": "src.strategies.worker_10e_hybrid_event_pullback_blend",
    "worker_10f": "src.strategies.worker_10f_hybrid_event_pullback_exposure",
    "worker_11": "src.strategies.worker_11_low_vol_trend_continuation",
    "worker_12": "src.strategies.worker_12_split_hybrid_ml",
    "worker_13": "src.strategies.worker_13_meta_consensus",
    "worker_14": "src.strategies.worker_14_relative_strength_defensive",
    "worker_15": "src.strategies.worker_15_stable_compounder",
    "worker_15b": "src.strategies.worker_15b_stable_compounder_relative",
}


def _load_strategy_module(strategy_id: str):
    if strategy_id == "benchmark_buy_and_hold":
        return None
    return importlib.import_module(STRATEGY_MODULES[strategy_id])


def _display_strategy_type(strategy_type: str) -> str:
    mapping = {
        "benchmark": "ベンチマーク",
        "rule_based": "ルールベース",
        "ml_based": "機械学習",
    }
    return mapping.get(strategy_type, strategy_type)


def _write_outputs(
    root: Path,
    strategy_id: str,
    equity_df,
    trades_df,
    candidates_df,
    metrics: dict,
    meta: dict,
    summary: str,
) -> Path:
    run_dir = root / "runs" / strategy_id
    ensure_dir(run_dir)
    equity_df.to_csv(run_dir / "equity.csv", index=False, encoding="utf-8")
    trades_df.to_csv(run_dir / "trades.csv", index=False, encoding="utf-8")
    candidates_df.to_csv(run_dir / "candidates.csv", index=False, encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    (run_dir / "result_summary.md").write_text(summary, encoding="utf-8")
    return run_dir


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _normalize_candidates_df(signals_df, strategy_id: str, holding_days):
    base_columns = ["date", "symbol", "score", "strategy_id", "planned_holding_days", "signal_rank"]
    if signals_df is None or len(signals_df) == 0:
        return pd.DataFrame(columns=base_columns)

    candidates_df = signals_df.copy()
    if "date" not in candidates_df.columns or "symbol" not in candidates_df.columns:
        return pd.DataFrame(columns=base_columns)

    if "score" not in candidates_df.columns:
        candidates_df["score"] = 0.0

    candidates_df = candidates_df.sort_values(["date", "score"], ascending=[True, False]).copy()
    candidates_df["strategy_id"] = strategy_id
    candidates_df["planned_holding_days"] = holding_days
    candidates_df["signal_rank"] = (
        candidates_df.groupby("date")["score"].rank(method="first", ascending=False).astype(int)
    )

    if pd.api.types.is_datetime64_any_dtype(candidates_df["date"]):
        candidates_df["date"] = candidates_df["date"].dt.strftime("%Y-%m-%d")

    ordered_columns = base_columns + [
        column
        for column in candidates_df.columns
        if column not in base_columns
    ]
    return candidates_df[ordered_columns]


def _format_period_lines(backtest_cfg: dict) -> list[str]:
    if any(
        backtest_cfg.get(key)
        for key in ("train_start_date", "train_end_date", "test_start_date", "test_end_date")
    ):
        train_label = (
            f"{backtest_cfg.get('train_start_date') or '先頭'} から "
            f"{backtest_cfg.get('train_end_date') or '末尾'}"
        )
        test_label = (
            f"{backtest_cfg.get('test_start_date') or '先頭'} から "
            f"{backtest_cfg.get('test_end_date') or '末尾'}"
        )
        return [
            f"- 学習期間設定: {train_label}",
            f"- テスト期間設定: {test_label}",
        ]

    period_label = (
        f"{backtest_cfg.get('start_date') or '先頭'} から "
        f"{backtest_cfg.get('end_date') or '末尾'}"
    )
    return [f"- バックテスト期間設定: {period_label}"]


def _build_summary(
    strategy_id: str,
    strategy_type: str,
    metrics: dict,
    holding_days,
    initial_capital: float,
    tested: list[dict],
    backtest_cfg: dict,
) -> str:
    lines = [
        f"# {strategy_id}",
        "",
        f"- 戦略種別: {_display_strategy_type(strategy_type)}",
        f"- 初期資金: {int(initial_capital):,} 円",
        *_format_period_lines(backtest_cfg),
        (
            "- 採用保有日数: ベンチマーク長期保有"
            if holding_days is None
            else f"- 採用保有日数: {holding_days}営業日"
        ),
        f"- CAGR: {metrics['cagr']}",
        f"- Sharpe: {metrics['sharpe']}",
        f"- 最大ドローダウン: {metrics['max_drawdown']}",
        f"- 勝率: {metrics['win_rate']}",
        f"- 取引数: {metrics['num_trades']}",
        "",
        "## 試行結果",
        "",
    ]
    for item in tested:
        horizon = item["holding_days"]
        label = "ベンチマーク長期保有" if horizon is None else f"{horizon}営業日"
        lines.append(
            f"- {label}: Sharpe {item['metrics']['sharpe']}, CAGR {item['metrics']['cagr']}, 取引数 {item['metrics']['num_trades']}"
        )
    lines.append("")
    return "\n".join(lines)


def _prepare_market(root: Path, backtest_cfg: dict, feature_cfg: dict):
    market = load_market_data(str(root), int(backtest_cfg["universe_size"]))
    market = apply_backtest_date_range(market, backtest_cfg)
    features = build_features(market, int(feature_cfg.get("window_main", 20)))
    features = features.sort_values(["date", "symbol"]).reset_index(drop=True)
    features = features.groupby("symbol", group_keys=False).filter(
        lambda frame: len(frame) >= int(backtest_cfg.get("min_history_days", 260))
    )
    return features


def _clean_models_dir(run_dir: Path) -> None:
    models_dir = run_dir / "models"
    if models_dir.exists():
        shutil.rmtree(models_dir)


def execute_strategy(root: Path, strategy_id: str, refresh_reports: bool = False) -> dict:
    backtest_cfg = load_backtest_config(root)
    feature_cfg = load_feature_config(root)
    walk_cfg = {**load_walkforward_config(root), **backtest_cfg}
    features = _prepare_market(root, backtest_cfg, feature_cfg)
    run_dir = root / "runs" / strategy_id
    ensure_dir(run_dir)

    if strategy_id == "benchmark_buy_and_hold":
        equity_df, trades_df, engine_meta = run_benchmark(
            features,
            {**backtest_cfg, "_project_root": str(root)},
        )
        candidates_df = _normalize_candidates_df(None, strategy_id, None)
        metrics = calculate_metrics(equity_df, trades_df)
        meta = {
            "strategy_id": strategy_id,
            "strategy_type": "benchmark",
            "strategy_name": strategy_id,
            "benchmark": True,
            "status": "completed",
            "initial_capital": backtest_cfg["initial_capital"],
            "start_date": backtest_cfg.get("start_date"),
            "end_date": backtest_cfg.get("end_date"),
            "train_start_date": backtest_cfg.get("train_start_date"),
            "train_end_date": backtest_cfg.get("train_end_date"),
            "test_start_date": backtest_cfg.get("test_start_date"),
            "test_end_date": backtest_cfg.get("test_end_date"),
            "universe_size": backtest_cfg["universe_size"],
            "selected_holding_days": None,
            "tested_holding_days": [None],
            "models_saved": False,
            "benchmark_symbol": engine_meta.get("benchmark_symbol"),
            "selected_engine_meta": engine_meta,
            "candidate_count": 0,
        }
        summary = _build_summary(
            strategy_id,
            "benchmark",
            metrics,
            None,
            float(backtest_cfg["initial_capital"]),
            [{"holding_days": None, "metrics": metrics}],
            backtest_cfg,
        )
        run_dir = _write_outputs(
            root,
            strategy_id,
            equity_df,
            trades_df,
            candidates_df,
            metrics,
            meta,
            summary,
        )
    else:
        module = _load_strategy_module(strategy_id)
        strategy_backtest_cfg = {
            **backtest_cfg,
            "_project_root": str(root),
            **getattr(module, "BACKTEST_OVERRIDES", {}),
        }
        strategy_cfg = {"backtest": strategy_backtest_cfg, "walkforward": walk_cfg}
        tested_runs = []
        _clean_models_dir(run_dir)

        for holding_days in strategy_backtest_cfg["holding_days_tested"]:
            model_dir = None
            if module.STRATEGY_TYPE == "ml_based":
                model_dir = run_dir / "models" / f"holding_{int(holding_days)}"

            generated = module.generate_signals(
                features,
                strategy_cfg,
                int(holding_days),
                model_dir=model_dir,
            )
            if isinstance(generated, tuple):
                signals, walkforward_folds = generated
            else:
                signals, walkforward_folds = generated, []

            signals = apply_test_date_range(signals, strategy_backtest_cfg)
            equity_df, trades_df, engine_meta = run_backtest(
                signals,
                features,
                {**strategy_backtest_cfg, "holding_days": int(holding_days)},
            )
            metrics = calculate_metrics(equity_df, trades_df)
            tested_runs.append(
                {
                    "holding_days": int(holding_days),
                    "signals": len(signals),
                    "signals_df": signals.copy(),
                    "equity_df": equity_df,
                    "trades_df": trades_df,
                    "metrics": metrics,
                    "engine_meta": engine_meta,
                    "walkforward_folds": walkforward_folds,
                }
            )

        tested_runs.sort(
            key=lambda item: (
                item["metrics"]["sharpe"],
                item["metrics"]["cagr"],
                -abs(item["metrics"]["max_drawdown"]),
            ),
            reverse=True,
        )
        best = tested_runs[0]
        meta = {
            "strategy_id": strategy_id,
            "strategy_type": module.STRATEGY_TYPE,
            "strategy_name": module.STRATEGY_NAME,
            "benchmark": False,
            "status": "completed",
            "initial_capital": backtest_cfg["initial_capital"],
            "start_date": backtest_cfg.get("start_date"),
            "end_date": backtest_cfg.get("end_date"),
            "train_start_date": backtest_cfg.get("train_start_date"),
            "train_end_date": backtest_cfg.get("train_end_date"),
            "test_start_date": backtest_cfg.get("test_start_date"),
            "test_end_date": backtest_cfg.get("test_end_date"),
            "universe_size": backtest_cfg["universe_size"],
            "selected_holding_days": best["holding_days"],
            "tested_holding_days": list(strategy_backtest_cfg["holding_days_tested"]),
            "signals_generated": best["signals"],
            "holding_day_results": {
                str(item["holding_days"]): item["metrics"] for item in tested_runs
            },
            "walkforward_folds": {
                str(item["holding_days"]): item["walkforward_folds"] for item in tested_runs
            },
            "models_saved": module.STRATEGY_TYPE == "ml_based",
            "backtest_overrides": getattr(module, "BACKTEST_OVERRIDES", {}),
            "selected_engine_meta": best["engine_meta"],
            "candidate_count": best["signals"],
        }
        summary = _build_summary(
            strategy_id,
            module.STRATEGY_TYPE,
            best["metrics"],
            best["holding_days"],
            float(backtest_cfg["initial_capital"]),
            [{"holding_days": item["holding_days"], "metrics": item["metrics"]} for item in tested_runs],
            backtest_cfg,
        )
        candidates_df = _normalize_candidates_df(
            best["signals_df"],
            strategy_id,
            best["holding_days"],
        )
        run_dir = _write_outputs(
            root,
            strategy_id,
            best["equity_df"],
            best["trades_df"],
            candidates_df,
            best["metrics"],
            meta,
            summary,
        )
        metrics = best["metrics"]

    payload = {
        "strategy_id": strategy_id,
        "run_dir": str(run_dir),
        "metrics": metrics,
    }
    if refresh_reports:
        payload["build_outputs"] = {key: str(value) for key, value in build_reports(root).items()}
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one strategy backtest and write artifacts.")
    parser.add_argument("strategy_id", choices=STRATEGY_IDS)
    parser.add_argument("--root", type=Path, default=project_root())
    parser.add_argument("--refresh-reports", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = execute_strategy(args.root.resolve(), args.strategy_id, refresh_reports=args.refresh_reports)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
