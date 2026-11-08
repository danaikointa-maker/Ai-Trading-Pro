"""HMAC-SHA256 signatures for outbound webhooks.

Until now `webhook_secret` was read from config only so that it could be scrubbed
out of error strings — it never signed anything. A receiver therefore had no way
to tell an alert from this system apart from a POST by anyone who learned the URL,
and webhook URLs leak: they sit in config files, in CI logs, in screenshots.

What is signed, and why it is built this way:

* **`timestamp.body`, not `body`.** A bare body signature is replayable forever:
  capture one "Cooldown engaged" POST and you can resend it tomorrow. Binding a
  timestamp into the MAC lets the receiver refuse anything outside a short window.
* **The signature covers the exact bytes on the wire.** The classic failure here is
  signing `json.dumps(payload)` and letting the HTTP layer re-serialise: a different
  key order or separator produces different bytes and *every* signature fails. So
  one function, `canonical_body()`, produces the bytes that are both signed and sent.
* **A receiver must verify over the raw body it received** — never over a re-encoded
  copy of the parsed JSON. `verify()` here takes raw bytes for exactly that reason,
  and it is the same code path the tests use, so the documented recipe is executable.
* **Signing happens at send time, not at enqueue time.** A message that waited in the
  durable outbox for ten minutes would otherwise arrive with a ten-minute-old
  timestamp and be rejected as a replay. The original time travels separately in
  `X-No7-Queued-At`, so a receiver can still see the message is a delayed one.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping

SIGNATURE_HEADER = "X-No7-Signature"
TIMESTAMP_HEADER = "X-No7-Timestamp"
DELIVERY_HEADER = "X-No7-Delivery-Id"
QUEUED_HEADER = "X-No7-Queued-At"
ATTEMPT_HEADER = "X-No7-Attempt"

SCHEME = "sha256="

# How far apart the two clocks may be before a request counts as a replay.
# Five minutes is the usual compromise: long enough to survive NTP drift and a
# slow proxy, short enough that a captured request is not useful for long.
DEFAULT_TOLERANCE_SECONDS = 300.0


def canonical_body(payload: Mapping[str, Any]) -> bytes:
    """The exact bytes that get signed *and* sent.

    `sort_keys` makes the output independent of dict insertion order, and the
    compact separators remove whitespace that serialisers disagree about.
    `ensure_ascii=False` keeps Thai text as UTF-8 instead of `\\uXXXX` escapes —
    either is valid JSON, but the two must not be chosen independently by the
    signer and the sender.
    """
    return json.dumps(payload, default=str, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signature(secret: str, timestamp: Any, body: bytes) -> str:
    """`sha256=<hex>` over `"<timestamp>." + body`."""
    message = f"{timestamp}.".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return SCHEME + digest


def sign_headers(secret: str, body: bytes, *, delivery_id: str = "",
                 queued_at: float | None = None, attempt: int = 1,
                 now: float | None = None) -> dict[str, str]:
    """Headers for one delivery attempt. Empty dict when no secret is configured."""
    if not secret:
        return {}
    stamp = str(int(now if now is not None else time.time()))
    headers = {
        TIMESTAMP_HEADER: stamp,
        SIGNATURE_HEADER: signature(secret, stamp, body),
    }
    if delivery_id:
        headers[DELIVERY_HEADER] = delivery_id
    if queued_at:
        headers[QUEUED_HEADER] = str(int(queued_at))
    if attempt > 1:
        headers[ATTEMPT_HEADER] = str(int(attempt))
    return headers


def verify(secret: str, headers: Mapping[str, str], body: bytes, *,
           tolerance: float = DEFAULT_TOLERANCE_SECONDS,
           now: float | None = None) -> tuple[bool, str]:
    """Check a received webhook. Returns `(ok, reason)` and never raises.

    `headers` may be any mapping with case-insensitive-ish access; the lookup here
    tries the canonical name and the lowercase one, which covers `http.server`,
    FastAPI/Starlette and plain dicts.

    `body` must be the raw bytes as received. Parsing the JSON and re-encoding it
    before verifying is the single most common way to break a webhook integration.
    """
    if not secret:
        return False, "no secret configured"

    def header(name: str) -> str:
        for key in (name, name.lower()):
            value = headers.get(key)  # type: ignore[union-attr]
            if value:
                return str(value)
        return ""

    sent = header(SIGNATURE_HEADER)
    stamp = header(TIMESTAMP_HEADER)
    if not sent:
        return False, f"missing {SIGNATURE_HEADER}"
    if not stamp:
        return False, f"missing {TIMESTAMP_HEADER}"
    try:
        stamp_value = float(stamp)
    except ValueError:
        return False, f"unparsable {TIMESTAMP_HEADER}: {stamp!r}"

    current = time.time() if now is None else now
    age = current - stamp_value
    if tolerance > 0 and abs(age) > tolerance:
        return False, (f"timestamp outside ±{tolerance:g}s window "
                       f"(off by {age:+.0f}s) — possible replay")

    expected = signature(secret, stamp, body)
    # Constant-time: a plain `==` leaks how many leading hex digits were right.
    if not hmac.compare_digest(expected, sent):
        return False, "signature mismatch"
    return True, ""
