"""Who may do what.

Three roles, strictly ordered:

* ``viewer``  — read only. Every GET is fine; nothing that changes state or spends
  compute/risk.
* ``trader``  — runs the platform: orders, closes, kill switch, training, backtests,
  dataset pinning, symbol switching.
* ``admin``   — the two things a trader may not do: manage users, and change the
  security posture (full-auto flag, security config).

Two rules that matter more than the ranking itself:

1. **Unknown or missing roles fail closed.** An empty, misspelled or legacy role
   resolves to ``viewer``, never to something privileged.
2. **Authority comes from the database, not the token.** A token says *who* you are;
   the `users` row says what you may do, so demoting or disabling someone takes
   effect on their next request instead of when their JWT expires.
"""
from __future__ import annotations

from typing import Any

VIEWER, TRADER, ADMIN = "viewer", "trader", "admin"

ROLE_RANK: dict[str, int] = {VIEWER: 1, TRADER: 2, ADMIN: 3}

# Roles that existed before the three-role model (e.g. the demo user was "owner").
ALIASES: dict[str, str] = {
    "owner": ADMIN,
    "admin": ADMIN,
    "trader": TRADER,
    "viewer": VIEWER,
    "readonly": VIEWER,
    "read_only": VIEWER,
    "demo": ADMIN,       # unauthenticated demo mode (require_auth: false)
}

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

ROLE_DESCRIPTIONS: dict[str, str] = {
    VIEWER: "อ่านได้อย่างเดียว — สั่งเทรน/สั่งออเดอร์/แก้ไขไม่ได้",
    TRADER: "สั่งออเดอร์, ปิดไม้, kill switch, เทรนโมเดล, backtest ได้ — จัดการผู้ใช้ไม่ได้",
    ADMIN: "ทุกอย่าง รวมถึงจัดการผู้ใช้และเปลี่ยน security posture",
}


def normalize_role(role: Any) -> str:
    """Map any stored/claimed role onto the canonical three, failing closed."""
    if role is None:
        return VIEWER
    key = str(role).strip().lower()
    return ALIASES.get(key, VIEWER)


def rank(role: Any) -> int:
    return ROLE_RANK[normalize_role(role)]


def at_least(role: Any, minimum: str) -> bool:
    return rank(role) >= ROLE_RANK[normalize_role(minimum)]


def describe_roles() -> list[dict[str, Any]]:
    return [{"role": role, "rank": ROLE_RANK[role], "description": ROLE_DESCRIPTIONS[role]}
            for role in (ADMIN, TRADER, VIEWER)]
