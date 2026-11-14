#!/usr/bin/env python3
"""Fail-closed release checklist. Does not connect to a broker or modify settings.

Usage: python scripts/smart_entry_release_gate.py --baseline bt.json \\
       --stress spread_stress.json --stress slippage_stress.json --demo mt5_demo.json
All report files are read-only. Exit 2 means blocked; even exit 0 requires a
separate, explicit operator authorization before any real-money deployment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.backtest_engine.release_gate import assess_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--stress", type=Path, action="append", required=True)
    parser.add_argument("--demo", type=Path, required=True)
    args = parser.parse_args()
    try:
        baseline = json.loads(args.baseline.read_text("utf-8"))
        stress = [json.loads(path.read_text("utf-8")) for path in args.stress]
        demo = json.loads(args.demo.read_text("utf-8"))
        if (not isinstance(baseline, dict) or not all(isinstance(item, dict) for item in stress)
                or not isinstance(demo, dict)):
            raise ValueError("reports must be JSON objects")
        result = assess_release(baseline, stress, demo)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result = {"state": "blocked", "passed": False, "failures": [f"input unavailable or invalid: {exc}"],
                  "operator_review_required": True, "live_auto_enabled": False}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
