"""Read-only signal readiness, calculated *after* the existing risk gate.

This state is never consulted by the executor. It explains whether a signal is
waiting for setup conditions or has been vetoed by safety/account constraints.
"""
from __future__ import annotations

from dataclasses import dataclass

from packages.shared_schemas.models import Signal, SignalAction, SignalReadiness


SAFETY_VETO_CODES = frozenset({
    "news_lockout", "data_quality", "broker_health", "regime_news_shock",
})


@dataclass(frozen=True)
class ReadinessAssessment:
    state: SignalReadiness
    reason: str


def assess_readiness(
    signal: Signal, *, gate_allow: bool, was_tradable: bool = False, as_of: int | None = None,
) -> ReadinessAssessment:
    """Return an explanatory state without changing action, score or plan.

    The caller supplies the same market time used to create the signal; wall
    clock time would spuriously expire replay/backtest signals.
    """
    if as_of is not None and signal.expires_at and as_of >= signal.expires_at:
        return ReadinessAssessment(SignalReadiness.expired, "แผนหมดอายุแล้ว รอวิเคราะห์ใหม่")

    if was_tradable and not gate_allow:
        return ReadinessAssessment(
            SignalReadiness.blocked,
            signal.blockers[0] if signal.blockers else "Risk Gate ไม่อนุญาตให้เปิดออเดอร์",
        )

    if any(code in SAFETY_VETO_CODES for code in signal.blocker_codes):
        return ReadinessAssessment(
            SignalReadiness.blocked,
            signal.blockers[0] if signal.blockers else "เงื่อนไขความปลอดภัยไม่ผ่าน",
        )

    if signal.action in (SignalAction.buy, SignalAction.sell) and signal.plan is not None:
        if gate_allow:
            return ReadinessAssessment(SignalReadiness.ready, "แผนผ่านเงื่อนไขสัญญาณและ Risk Gate")
        return ReadinessAssessment(SignalReadiness.blocked, "Risk Gate ไม่อนุญาตให้เปิดออเดอร์")

    # Low score, incomplete zone, price not at the setup and missing plans are
    # reasons to *wait*, not permission to trade and not a safety veto.
    if signal.action == SignalAction.wait or signal.plan is not None or (
        signal.blocker_codes and signal.blocker_codes != ["no_direction"]
    ):
        return ReadinessAssessment(
            SignalReadiness.wait,
            signal.blockers[0] if signal.blockers else "ยังไม่ครบเงื่อนไขจุดเข้า รอสัญญาณยืนยัน",
        )

    return ReadinessAssessment(SignalReadiness.scanning, "ยังไม่พบจุดเข้า รอสแกนรอบถัดไป")
