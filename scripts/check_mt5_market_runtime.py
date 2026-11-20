"""Read-only readiness check for a deployed MT5 market publisher runtime."""
from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


PUBLISH_PATH = "/api/market/publish/mt5"


def inspect_runtime(base_url: str, opener=urlopen) -> dict[str, Any]:
    base = base_url.rstrip("/")
    report: dict[str, Any] = {"base_url": base, "checks": {}}
    try:
        with opener(base + "/api/system/health", timeout=4) as response:
            health = json.load(response)
        report["checks"]["health_api"] = response.status == 200
    except (OSError, URLError, ValueError) as exc:
        report["checks"]["health_api"] = False
        report["error"] = type(exc).__name__
        report["ready"] = False
        return report
    try:
        with opener(base + "/api/openapi.json", timeout=4) as response:
            schema = json.load(response)
        methods = schema.get("paths", {}).get(PUBLISH_PATH, {})
        route_ready = "post" in {str(method).lower() for method in methods}
    except (OSError, URLError, ValueError) as exc:
        route_ready = False
        report["openapi_error"] = type(exc).__name__
    feed = health.get("feed") or {}
    feed_mode = str(health.get("feed_mode") or feed.get("mode") or "unknown")
    fresh = feed.get("fresh") is True
    report.update({
        "feed_mode": feed_mode,
        "checks": {
            "health_api": report["checks"]["health_api"],
            "publisher_route": route_ready,
            "publisher_fresh": fresh,
        },
    })
    report["ready"] = bool(route_ready and feed_mode == "mt5_demo_publisher" and fresh)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080",
                        help="API base URL; use HTTPS or a loopback SSH tunnel")
    args = parser.parse_args()
    report = inspect_runtime(args.base_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
