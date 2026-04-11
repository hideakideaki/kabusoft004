from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import (
    REQUIRED_REPORT_FILES,
    STRATEGY_IDS,
    load_run_snapshot,
    project_root,
    relative_to_root,
)


def validate_project(root: Path) -> dict[str, Any]:
    snapshots = [load_run_snapshot(root, strategy_id) for strategy_id in STRATEGY_IDS]
    issues: list[str] = []

    for report_name in REQUIRED_REPORT_FILES:
        report_path = root / "reports" / report_name
        if not report_path.exists():
            issues.append(f"missing report file: {relative_to_root(report_path, root)}")

    run_issues: dict[str, list[str]] = {}
    for snapshot in snapshots:
        if snapshot.issues:
            run_issues[snapshot.strategy_id] = snapshot.issues
            issues.extend(snapshot.issues)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "ok": not issues,
        "strategy_count": len(snapshots),
        "report_count": len(REQUIRED_REPORT_FILES),
        "issues": issues,
        "runs": {
            snapshot.strategy_id: {
                "path": relative_to_root(snapshot.run_dir, root),
                "complete": snapshot.complete,
                "row_counts": snapshot.row_counts,
                "meta": snapshot.meta,
                "metrics": snapshot.metrics,
                "issues": snapshot.issues,
            }
            for snapshot in snapshots
        },
        "run_issues": run_issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate strategy output contracts required by the viewer."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="Repository root. Defaults to the current project root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the validation result JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_project(args.root.resolve())

    if args.output:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
