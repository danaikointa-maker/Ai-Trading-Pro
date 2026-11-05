#!/usr/bin/env python3
"""Quick "is it alive and honest" check: health, live payload, model, errors.

    python3 scripts/smoke.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import urllib.request

DEMO = {"email": "demo@no7.ai", "password": "no7demo1234"}


def call(base: str, path: str, payload: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    health = call(args.base, "/api/system/health")
    print(f"health        : {health.get('status')}")

    token = call(args.base, "/api/auth/login", DEMO)["token"]
    live = call(args.base, "/api/trading/live", token=token)
    analysis = live.get("analysis") or {}
    signal = live.get("signal") or {}

    print(f"feed / mode   : {live['feed']} / {live['mode']}")
    print(f"symbol / price: {live['symbol']} @ {live['ticker']['bid']}")
    print(f"zones         : {len(analysis.get('zones', []))} "
          f"(supports {len(analysis.get('supports', []))}, "
          f"resistances {len(analysis.get('resistances', []))})")
    print(f"forecast      : {'yes' if live.get('forecast') else 'no'}")
    print(f"model         : {live['model']['version']} approved={live['model']['approved']}")
    print(f"signal        : {signal.get('action')}"
          + (f" score={signal.get('score')}" if signal else ""))
    print(f"open positions: {len(live.get('positions', []))}")
    print(f"runtime errors: {len(live.get('errors', []))}")

    for error in live.get("errors", []):
        print(f"  ! {error.get('where')}: {str(error.get('error'))[:120]}")

    # The UI is only honest if these blocks exist.
    missing = [k for k in ("analysis", "forecast", "model", "risk_state", "limits")
               if not live.get(k)]
    if missing:
        print(f"MISSING BLOCKS: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
