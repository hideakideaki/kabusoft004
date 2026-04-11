from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import STRATEGY_IDS, project_root
from src.pipelines.build_reports import build_reports
from src.pipelines.run_single_strategy import execute_strategy
from src.validation.check_output_contract import validate_project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all strategy backtests and rebuild reports.")
    parser.add_argument("--root", type=Path, default=project_root())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    results = [execute_strategy(root, strategy_id, refresh_reports=False) for strategy_id in STRATEGY_IDS]
    build_outputs = build_reports(root)
    validation = validate_project(root)
    print(
        json.dumps(
            {
                "results": results,
                "build_outputs": {key: str(value) for key, value in build_outputs.items()},
                "validation_ok": validation["ok"],
                "issue_count": len(validation["issues"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
