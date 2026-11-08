#!/usr/bin/env python3
"""End-to-end proof of the durable outbox and the webhook signature.

Not a unit test: this drives the *running* API over HTTP, with a real receiver
socket that gets taken down and brought back, and a real server restart in the
middle. It answers the three questions a unit test cannot:

1. Does an alert raised while the receiver is down actually survive?
2. Does it survive the API process being restarted?
3. When it finally arrives, does the HMAC still verify — signed late, with a
   fresh timestamp, against the clock of the machine receiving it?

Usage (the runner script does all of this for you):
    .venv/bin/python scripts/check_outbox.py --port 8070 --receiver-port 8099
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.notification import signing  # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    return ok


class Receiver:
    """A webhook endpoint that can be stopped and started again on one port."""

    def __init__(self, port: int, secret: str) -> None:
        self.port = port
        self.secret = secret
        self.received: list[dict] = []
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                ok, reason = signing.verify(receiver.secret, dict(self.headers), raw)
                receiver.received.append({"raw": raw, "headers": dict(self.headers),
                                          "verified": ok, "reason": reason})
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def api(method: str, url: str, token: str = "", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"_status": exc.code, "_body": exc.read().decode("utf-8", "replace")}


def login(base: str) -> str:
    out = api("POST", f"{base}/api/auth/login",
              payload={"email": "demo@no7.ai", "password": "no7demo1234"})
    return str(out.get("token", ""))


def wait_for_pending(base: str, token: str, predicate, timeout: float = 45.0) -> dict:
    """Poll notify status until `predicate(outbox)` holds or the time runs out."""
    deadline = time.time() + timeout
    status: dict = {}
    while time.time() < deadline:
        status = api("GET", f"{base}/api/system/notify", token)
        outbox = status.get("outbox", {})
        if predicate(outbox):
            return status
        time.sleep(1.0)
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8070)
    parser.add_argument("--receiver-port", type=int, default=8099)
    parser.add_argument("--secret", default="whsec_live_check")
    parser.add_argument("--stage", choices=["before-restart", "after-restart"],
                        default="before-restart")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    token = login(base)
    if not token:
        print("could not log in — is the server up?")
        return 2

    if args.stage == "before-restart":
        print("\n=== 1. receiver is DOWN — the alert must be kept, not lost ===")
        status = api("GET", f"{base}/api/system/notify", token)
        check(status.get("webhook_signed") is True, "webhook signing is on",
              f"warning={status.get('webhook_warning') or 'none'}")
        check(status.get("outbox", {}).get("enabled") is True, "outbox is enabled")

        api("POST", f"{base}/api/system/alerts/test", token)
        status = wait_for_pending(base, token, lambda o: o.get("pending", 0) >= 1, 20)
        pending = status.get("outbox", {}).get("pending", 0)
        check(pending >= 1, "the undeliverable alert was queued", f"pending={pending}")
        return 0 if all(ok for ok, _ in results) else 1

    # ---------------------------------------------------------- after restart
    print("\n=== 2. the API process was restarted — the queue must still hold it ===")
    status = api("GET", f"{base}/api/system/notify", token)
    pending = status.get("outbox", {}).get("pending", 0)
    check(pending >= 1, "the queued alert survived the restart", f"pending={pending}")

    print("\n=== 3. receiver comes back — the loop must drain it unprompted ===")
    receiver = Receiver(args.receiver_port, args.secret)
    receiver.start()
    try:
        # The app keeps trading while this runs, so live alerts arrive on the same
        # socket. Only a delivery that carries a delivery id came out of the queue.
        def from_the_queue():
            return next((r for r in receiver.received
                         if signing.DELIVERY_HEADER in r["headers"]), None)

        deadline = time.time() + 90
        while time.time() < deadline and from_the_queue() is None:
            time.sleep(1.0)
        got = from_the_queue()
        check(got is not None, "the backlog went out by itself (loop, not a user action)",
              f"{len(receiver.received)} request(s), "
              f"{sum(1 for r in receiver.received if signing.DELIVERY_HEADER in r['headers'])} "
              f"from the queue")
        if got is not None:
            check(got["verified"], "the late delivery's HMAC verifies",
                  got["reason"] or "signature ok")
            headers = got["headers"]
            queued_at = headers.get(signing.QUEUED_HEADER, "")
            stamp = headers.get(signing.TIMESTAMP_HEADER, "")
            fresh = stamp and queued_at and int(stamp) > int(queued_at)
            check(bool(fresh), "signed at send time, not at enqueue time",
                  f"queued_at={queued_at} signed_at={stamp} "
                  f"(+{int(stamp) - int(queued_at)}s)" if fresh else "timestamps equal")
            check(bool(headers.get(signing.DELIVERY_HEADER)),
                  "carries a delivery id a receiver can deduplicate on",
                  headers.get(signing.DELIVERY_HEADER, ""))
            body = json.loads(got["raw"])
            check("title" in body and "level" in body, "body carries routable fields",
                  json.dumps(body, ensure_ascii=False)[:90])
        status = wait_for_pending(base, token, lambda o: o.get("pending", 0) == 0, 90)
        outbox = status.get("outbox", {})
        check(outbox.get("pending") == 0, "the queue drained to empty",
              f"delivered={outbox.get('delivered')} pending={outbox.get('pending')}")
    finally:
        receiver.stop()

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
