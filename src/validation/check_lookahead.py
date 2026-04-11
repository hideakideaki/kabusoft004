from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.contracts import project_root, relative_to_root


SUSPICIOUS_PATTERNS = (
    "shift(-",
    "pct_change(-",
    "diff(-",
    ".iloc[i + 1]",
    ".iloc[idx + 1]",
    "lead(",
)


def scan_file(path: Path, root: Path) -> list[str]:
    issues: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        for pattern in SUSPICIOUS_PATTERNS:
            if pattern in line:
                issues.append(
                    f"{relative_to_root(path, root)}:{line_number}: suspicious future-looking pattern `{pattern}`"
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan source files for common future-looking code patterns."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=project_root(),
        help="Repository root. Defaults to the current project root.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    targets = list((root / "src" / "strategies").glob("*.py"))

    issues: list[str] = []
    for path in sorted(targets):
        issues.extend(scan_file(path, root))

    print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
