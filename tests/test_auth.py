"""Login hardening: password guessing must cost something.

The console was previously wide open — unlimited attempts per second, no audit
beyond a generic failure line. These tests pin the throttle policy.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_throttle(runtime):
    runtime.db.execute("DELETE FROM login_throttle")
    yield
    runtime.db.execute("DELETE FROM login_throttle")


def _login(client, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_repeated_failures_lock_the_account(client):
    email = "intruder@no7.ai"
    for attempt in range(5):
        res = _login(client, email, "wrong-password")
        assert res.status_code == 401, f"attempt {attempt + 1} should still be a plain 401"

    locked = _login(client, email, "wrong-password")
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0

    # The correct password must not be usable while the key is locked.
    still_locked = _login(client, email, "no7demo1234")
    assert still_locked.status_code == 429


def test_unknown_email_is_throttled_the_same_way(client):
    """No user enumeration: a non-existent account behaves like a real one."""
    email = "does-not-exist@no7.ai"
    for _ in range(5):
        assert _login(client, email, "whatever").status_code == 401
    assert _login(client, email, "whatever").status_code == 429


def test_successful_login_resets_the_counter(client):
    email = "demo@no7.ai"
    for _ in range(3):
        assert _login(client, email, "wrong-password").status_code == 401

    ok = _login(client, email, "no7demo1234")
    assert ok.status_code == 200

    # The counter is gone, so one more mistake is a 401, not a lockout.
    assert _login(client, email, "wrong-password").status_code == 401


def test_throttle_key_is_per_email_and_ip(client, runtime):
    from services.api_gateway.auth import LoginThrottle

    throttle = LoginThrottle(runtime.db)
    other = throttle.key_for("someone@else.ai", "10.0.0.9")
    assert throttle.register_failure(other) == 0
    for _ in range(4):
        throttle.register_failure(other)
    locked, retry = throttle.check(other)
    assert locked is True and retry > 0

    # A different email from the same IP keeps its own budget.
    neighbour = throttle.key_for("another@else.ai", "10.0.0.9")
    assert throttle.check(neighbour) == (False, 0)


def test_lockout_grows_with_repeated_abuse(runtime):
    from services.api_gateway.auth import LoginThrottle

    throttle = LoginThrottle(runtime.db, max_failures=2, lock_seconds=60, max_lock_seconds=600)
    key = throttle.key_for("abuse@no7.ai", "10.0.0.1")
    assert throttle.register_failure(key) == 0          # 1 failure
    first = throttle.register_failure(key)              # 2nd -> locked
    assert first == 60
    second = throttle.register_failure(key)             # 3rd -> doubled
    assert second == 120
    for _ in range(20):                                 # capped
        third = throttle.register_failure(key)
    assert third == 600
