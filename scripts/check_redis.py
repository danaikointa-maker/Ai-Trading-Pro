#!/usr/bin/env python3
"""Check that a real Redis can carry the shared rate limit and the cluster frames.

    .venv/bin/python scripts/check_redis.py                       # uses NO7_REDIS_URL
    .venv/bin/python scripts/check_redis.py --url redis://10.0.0.5:6379/2
    .venv/bin/python scripts/check_redis.py --url … --ttl 2       # also wait out a TTL

Run it against the server you are about to deploy against. It uses the same Lua
script and the same client settings as the application, so a PASS here means the
limiter will behave; it is not a generic Redis benchmark.

Safety rules this tool follows, because it is pointed at production:

* it NEVER calls FLUSHDB/FLUSHALL;
* every key it writes lives under `no7:selftest:<random>:` and is deleted at the end;
* the URL is printed with any password masked;
* read-only checks degrade to a warning when the server forbids them (CONFIG GET),
  instead of failing a healthy deployment.

Exit code 0 = all checks passed (warnings allowed), 1 = a check failed,
2 = could not even connect / bad arguments.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api_gateway.cluster import RedisSharedState  # noqa: E402
from services.api_gateway.ratelimit import RedisBucketStore  # noqa: E402

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def mask(url: str) -> str:
    """redis://user:secret@host:6379/0 -> redis://user:***@host:6379/0"""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    creds, _, host = rest.rpartition("@")
    if ":" in creds:
        user, _, _ = creds.partition(":")
        creds = f"{user}:***"
    else:
        creds = "***"
    return f"{scheme}://{creds}@{host}"


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.warnings: list[str] = []

    def ok(self, title: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  {GREEN}PASS{RESET} {title}" + (f" {DIM}— {detail}{RESET}" if detail else ""))

    def bad(self, title: str, detail: str = "") -> None:
        self.failed += 1
        print(f"  {RED}FAIL{RESET} {title}" + (f" {DIM}— {detail}{RESET}" if detail else ""))

    def warn(self, title: str, detail: str = "") -> None:
        self.warnings.append(f"{title}: {detail}" if detail else title)
        print(f"  {YELLOW}WARN{RESET} {title}" + (f" {DIM}— {detail}{RESET}" if detail else ""))

    def check(self, title: str, fn) -> None:
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - this tool reports failures, never raises
            self.bad(title, f"{type(exc).__name__}: {exc}")
        else:
            self.ok(title, detail or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("NO7_REDIS_URL", ""),
                        help="redis://host:port/db (default: $NO7_REDIS_URL)")
    parser.add_argument("--ttl", type=int, default=0,
                        help="seconds to wait while proving a key really expires (0 = skip)")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="socket timeout, same default the app uses")
    args = parser.parse_args()

    if not args.url:
        print("error: no URL — pass --url or set NO7_REDIS_URL", file=sys.stderr)
        return 2
    try:
        import redis
    except ImportError:
        print("error: the `redis` package is not installed (pip install redis)", file=sys.stderr)
        return 2

    print(f"checking {mask(args.url)}")
    try:
        client = redis.Redis.from_url(args.url, decode_responses=True,
                                      socket_timeout=args.timeout,
                                      socket_connect_timeout=args.timeout)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        print(f"  {RED}FAIL{RESET} cannot connect — {type(exc).__name__}: {exc}")
        print("\nthe app would fall back to the sqlite/memory store and say so in "
              "/api/system/health → ratelimit.reason")
        return 2

    tag = secrets.token_hex(4)
    prefix = f"no7:selftest:{tag}"
    report = Report()
    print(f"{DIM}  keys under {prefix}:* — nothing else is touched{RESET}")

    report.ok("PING", "server answered")

    def server_info() -> str:
        info = client.info("server")
        mode = client.info("replication").get("role", "?")
        return f"{info['redis_version']} {info.get('redis_mode', 'standalone')}, role {mode}"

    report.check("server identifies itself", server_info)

    def eviction_policy() -> str:
        try:
            policy = (client.config_get("maxmemory-policy") or {}).get("maxmemory-policy", "")
        except Exception as exc:  # noqa: BLE001 - managed Redis often blocks CONFIG
            report.warn("eviction policy unreadable (CONFIG restricted)",
                        f"{type(exc).__name__} — check it in your provider's console")
            return ""
        if not policy:
            report.warn("eviction policy unknown", "CONFIG GET returned nothing")
            return ""
        if policy != "noeviction":
            report.warn(f"maxmemory-policy is {policy}",
                        "buckets may be evicted under pressure, silently resetting a "
                        "limit — prefer noeviction")
            return ""
        return "maxmemory-policy = noeviction"

    policy_detail = eviction_policy()
    if policy_detail:
        report.ok("eviction policy is safe for counters", policy_detail)

    # ----------------------------------------------------------------- limiter
    store = RedisBucketStore(client, prefix=prefix)
    other = RedisBucketStore(redis.Redis.from_url(args.url, decode_responses=True,
                                                  socket_timeout=args.timeout), prefix=prefix)

    def lua_runs() -> str:
        decisions = [store.spend(("probe", "a"), 3.0, 0.0001, 1_000.0)[0] for _ in range(4)]
        if decisions != [True, True, True, False]:
            raise AssertionError(f"expected 3 allowed then a denial, got {decisions}")
        return f"3 allowed, 4th denied — {decisions}"

    report.check("Lua token bucket", lua_runs)

    def shared_budget() -> str:
        decisions = [s.spend(("probe", "b"), 2.0, 0.0001, 2_000.0)[0]
                     for _ in range(2) for s in (store, other)]
        if sum(decisions) != 2:
            raise AssertionError(f"a limit of 2 was handed out {sum(decisions)} times")
        return "two connections, one budget"

    report.check("budget is shared across connections", shared_budget)

    def refills() -> str:
        store.spend(("probe", "c"), 1.0, 1.0, 3_000.0)
        denied, _ = store.spend(("probe", "c"), 1.0, 1.0, 3_000.0)
        allowed, tokens = store.spend(("probe", "c"), 1.0, 1.0, 3_001.0)
        if denied or not allowed:
            raise AssertionError("the bucket did not refill after one second of clock")
        return f"balance {tokens:.3f} after spending the refilled token"

    report.check("buckets refill from the caller's clock", refills)

    def exact_balance() -> str:
        _allowed, tokens = store.spend(("probe", "d"), 5.0, 5.0 / 60.0, 4_000.0)
        for step in range(1, 5):
            _allowed, tokens = store.spend(("probe", "d"), 5.0, 5.0 / 60.0, 4_000.0 + step * 4)
        stored = client.hget(f"{prefix}:probe:d", "tokens")
        if float(stored) != tokens:
            raise AssertionError(f"balance changed in transit: {stored} != {tokens!r}")
        return f"{stored} survives the round trip"

    report.check("balances are not rounded by the server", exact_balance)

    def ttl_is_set() -> str:
        store.spend(("probe", "e"), 60.0, 1.0, 5_000.0)
        ttl = client.pttl(f"{prefix}:probe:e")
        if not 0 < ttl <= 60_000:
            raise AssertionError(f"expected a TTL up to 60s, got {ttl}ms")
        return f"idle identities carry a TTL — ttl={ttl // 1000}s"

    report.check("idle identities expire", ttl_is_set)

    # ------------------------------------------------------------------ frames
    writer = RedisSharedState(client, prefix=f"{prefix}:bus", default_ttl=max(1, args.ttl or 5))
    reader = RedisSharedState(redis.Redis.from_url(args.url, decode_responses=True,
                                                   socket_timeout=args.timeout),
                              prefix=f"{prefix}:bus", default_ttl=max(1, args.ttl or 5))

    def frame_round_trip() -> str:
        writer.publish("v1", {"role": "leader", "tag": tag})
        frame = reader.read("v1")
        if frame != {"role": "leader", "tag": tag}:
            raise AssertionError(f"a replica would read {frame!r}")
        return "a frame written by one connection is read by another"

    report.check("cluster frame bus", frame_round_trip)

    if args.ttl > 0:
        def frame_expires() -> str:
            writer.publish("v2", {"role": "leader"}, ttl=args.ttl)
            deadline = time.time() + args.ttl + 3
            while reader.read("v2") is not None and time.time() < deadline:
                time.sleep(0.1)
            if reader.read("v2") is not None:
                raise AssertionError(f"a frame outlived its {args.ttl}s TTL")
            return f"gone after {args.ttl}s, so no replica serves a stale frame"

        report.check("frames expire", frame_expires)
    else:
        print(f"{DIM}  skip frame expiry (pass --ttl 2 to wait it out){RESET}")

    def wrong_type_is_an_error() -> str:
        client.set(f"{prefix}:probe:clash", "not-a-hash")
        try:
            store.spend(("probe", "clash"), 5.0, 1.0, 1.0)
        except redis.exceptions.ResponseError:
            return "a wrong-typed key raises the error the limiter catches"
        raise AssertionError("expected a ResponseError the limiter can degrade on")

    report.check("hostile key survives", wrong_type_is_an_error)

    # ------------------------------------------------------------------ tidy up
    def cleanup() -> str:
        keys = list(client.scan_iter(match=f"{prefix}:*"))
        deleted = client.delete(*keys) if keys else 0
        left = list(client.scan_iter(match=f"{prefix}:*"))
        if left:
            raise AssertionError(f"{len(left)} test keys left behind: {left[:3]}")
        return f"test keys removed — {deleted} deleted"

    report.check("cleans up after itself", cleanup)

    total = report.passed + report.failed
    print()
    if report.failed:
        print(f"{RED}{report.passed}/{total} checks passed — NOT READY{RESET}")
    else:
        line = f"{GREEN}{report.passed}/{total} checks passed — OK{RESET}"
        if report.warnings:
            line += f", {YELLOW}{len(report.warnings)} warning(s){RESET}"
        print(line)
    for warning in report.warnings:
        print(f"  {YELLOW}!{RESET} {warning}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
