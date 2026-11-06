"""Support/resistance zones: confluence rules, both sides, and no repainting."""
from __future__ import annotations



def _snapshot(runtime, symbol="XAUUSD"):
    return runtime.ensure_analysis(symbol).snapshot


def test_at_least_three_zones_each_side(runtime):
    snap = _snapshot(runtime)
    assert len(snap.supports) >= 3
    assert len(snap.resistances) >= 3
    assert len(snap.supports) <= 6 and len(snap.resistances) <= 6


def test_zones_are_ordered_by_proximity(runtime):
    snap = _snapshot(runtime)
    price = snap.price
    assert [abs(z.mid - price) for z in snap.resistances] == sorted(abs(z.mid - price) for z in snap.resistances)
    assert [abs(z.mid - price) for z in snap.supports] == sorted(abs(z.mid - price) for z in snap.supports)


def test_high_quality_needs_three_independent_families(runtime):
    snap = _snapshot(runtime)
    for zone in list(snap.supports) + list(snap.resistances):
        families = {e.family if hasattr(e, "family") else e.get("family") for e in zone.evidence}
        assert len(families) == len(zone.evidence), "an evidence family must be counted once"
        if zone.quality == "high":
            assert len(families) >= 3
            assert zone.status == "confirmed"


def test_confirmed_and_candidate_are_separate(runtime):
    """`confirmed` requires a closed-candle retest AND structural evidence.

    Everything else stays a candidate and is never presented as fact.
    """
    snap = _snapshot(runtime)
    assert {z.status for z in snap.zones} <= {"confirmed", "candidate"}
    for z in snap.zones:
        structural = {"structure_swing", "order_block"} & set(z.families)
        if z.status == "confirmed":
            assert z.touches >= 1
            assert structural, "a confirmed zone must rest on market structure"
            assert "Confirmed by" in z.note
        else:
            assert (z.touches < 1) or not structural
            assert "Projection only" in z.note


def test_zones_do_not_repaint_between_ticks(runtime):
    """A small price move must not silently rewrite already-confirmed zones."""
    first = _snapshot(runtime)
    confirmed = {z.id: (round(z.low, 2), round(z.high, 2)) for z in first.zones if z.status == "confirmed"}
    second = _snapshot(runtime)
    for z in second.zones:
        if z.status == "confirmed" and z.id in confirmed:
            assert (round(z.low, 2), round(z.high, 2)) == confirmed[z.id]
