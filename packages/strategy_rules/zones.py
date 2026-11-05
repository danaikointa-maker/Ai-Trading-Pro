"""Support / resistance engine with weighted, *independent* confluence.

Design rules
------------
* A candidate level is produced by exactly one detector ("family").
* Levels closer than ``cluster_tolerance_atr`` collapse into one zone and each
  family contributes its weight **once**, so five EMA lengths cannot pretend to
  be five independent confirmations.
* ``confirmed`` zones have been re-tested by price using closed candles only;
  ``candidate`` zones are projections and are labelled as such (no repainting).
* High quality requires >= 3 independent families AND enough total weight.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from packages.indicators import core as ta
from packages.market_structure.patterns import (
    Level,
    find_equal_levels,
    find_fair_value_gaps,
    find_order_blocks,
    reaction_count,
    swing_origin_levels,
)
from packages.market_structure.structure import Swing
from packages.shared_schemas.models import (
    Zone,
    ZoneEvidence,
    ZoneKind,
    ZoneQuality,
    ZoneStatus,
)


@dataclass
class ZoneEngineConfig:
    max_supports: int = 5
    max_resistances: int = 5
    min_required: int = 3
    cluster_tolerance_atr: float = 0.45
    min_quality_score: float = 0.45
    high_quality_min_families: int = 3
    high_quality_min_weight: float = 0.50
    families: dict[str, float] | None = None

    @classmethod
    def from_dict(cls, cfg: dict, families: dict[str, float]) -> "ZoneEngineConfig":
        return cls(
            max_supports=int(cfg.get("max_supports", 5)),
            max_resistances=int(cfg.get("max_resistances", 5)),
            min_required=int(cfg.get("min_required", 3)),
            cluster_tolerance_atr=float(cfg.get("cluster_tolerance_atr", 0.45)),
            min_quality_score=float(cfg.get("min_quality_score", 0.45)),
            high_quality_min_families=int(cfg.get("high_quality_min_families", 3)),
            high_quality_min_weight=float(cfg.get("high_quality_min_weight", 0.50)),
            families=families,
        )


_FAMILY_LABELS = {
    "structure_swing": "Swing structure",
    "order_block": "Order block / supply-demand",
    "fair_value_gap": "Fair value gap",
    "pivot": "Daily pivot",
    "fibonacci": "Fibonacci retracement",
    "volume_profile": "Volume profile",
    "vwap": "Session VWAP",
    "ema": "EMA dynamic level",
    "liquidity_equal_levels": "Equal highs/lows liquidity",
    "round_number": "Round number",
    "reaction_history": "Reaction history",
}


def _zone_id(kind: str, mid: float, digits: int) -> str:
    raw = f"{kind}:{round(mid, digits)}".encode()
    return "Z" + hashlib.sha1(raw).hexdigest()[:8].upper()


def _fib_levels(swings: list[Swing], ratios: list[float], pad: float) -> list[Level]:
    if len(swings) < 2:
        return []
    leg = None
    for a, b in zip(reversed(swings[:-1]), reversed(swings[1:])):
        if a.kind != b.kind:
            leg = (a, b)
            break
    if leg is None:
        return []
    a, b = leg
    out: list[Level] = []
    direction = "support" if b.price > a.price else "resistance"
    for ratio in ratios:
        price = b.price - (b.price - a.price) * ratio
        out.append(Level(price - pad, price + pad, "fibonacci", f"Fib {ratio:.3f}", b.idx, b.t, direction,
                         False, {"ratio": ratio}))
    return out


def _pivot_levels(pivots: dict[str, float], pad: float) -> list[Level]:
    out: list[Level] = []
    for name, price in pivots.items():
        family_dir = "resistance" if name.startswith("R") else ("support" if name.startswith("S") else "neutral")
        out.append(Level(price - pad, price + pad, "pivot", f"Pivot {name}", 0, 0, family_dir, False, {"pivot": name}))
    return out


def _volume_profile_levels(vp: dict, pad: float) -> list[Level]:
    out: list[Level] = []
    for key, label in (("poc", "POC"), ("vah", "VAH"), ("val", "VAL")):
        price = float(vp.get(key) or 0.0)
        if price <= 0:
            continue
        direction = "resistance" if key == "vah" else ("support" if key == "val" else "neutral")
        out.append(Level(price - pad, price + pad, "volume_profile", f"Volume {label}", 0, 0, direction, False, {}))
    return out


def _dynamic_levels(price: float, vwap: float, ema50: float, ema200: float, pad: float, t: int) -> list[Level]:
    out: list[Level] = []
    for value, label in ((vwap, "Session VWAP"), (ema50, "EMA 50"), (ema200, "EMA 200")):
        if value is None or not np.isfinite(value) or value <= 0:
            continue
        family = "vwap" if "VWAP" in label else "ema"
        direction = "support" if value < price else "resistance"
        out.append(Level(float(value) - pad, float(value) + pad, family, label, 0, t, direction, False, {}))
    return out


def _round_numbers(price: float, atr_value: float, pad: float, step: float, t: int) -> list[Level]:
    base = math.floor(price / step) * step
    out: list[Level] = []
    for offset in (-1, 0, 1, 2):
        level = base + offset * step
        if abs(level - price) > atr_value * 8:
            continue
        out.append(Level(level - pad, level + pad, "round_number", f"Round {level:,.0f}", 0, t,
                         "support" if level < price else "resistance", False, {}))
    return out


def build_zones(
    df,
    spec,
    price: float,
    swings: list[Swing],
    atr_value: float,
    pivots: dict[str, float],
    vwap: float,
    ema50: float,
    ema200: float,
    volume_profile: dict,
    cfg: ZoneEngineConfig,
    round_step: float | None = None,
) -> tuple[list[Zone], list[Zone], list[Zone]]:
    """Return (all_zones, supports, resistances) with supports nearest-first."""
    families = cfg.families or {}
    atr_value = float(atr_value) if np.isfinite(atr_value) and atr_value > 0 else max(price * 0.0005, 1e-6)
    tol = max(atr_value * cfg.cluster_tolerance_atr, spec.point * 10)
    pad = max(atr_value * 0.08, spec.point * 5)
    t_now = int(df["t"].iloc[-1]) if len(df) else 0

    candidates: list[Level] = []
    candidates += swing_origin_levels(swings, atr_value)
    candidates += find_order_blocks(df, df["atr"].to_numpy(float))
    candidates += find_fair_value_gaps(df, df["atr"].to_numpy(float))
    candidates += find_equal_levels(swings, atr_value)
    candidates += _fib_levels(swings, [0.236, 0.382, 0.5, 0.618, 0.786], pad)
    candidates += _pivot_levels(pivots, pad)
    candidates += _volume_profile_levels(volume_profile, pad)
    candidates += _dynamic_levels(price, vwap, ema50, ema200, pad, t_now)
    candidates += _round_numbers(price, atr_value, pad, round_step or max(10.0, atr_value * 4), t_now)

    # ---- cluster by price proximity -------------------------------------
    candidates.sort(key=lambda lv: lv.mid)
    clusters: list[list[Level]] = []
    for level in candidates:
        placed = False
        for cluster in clusters:
            centre = sum(lv.mid for lv in cluster) / len(cluster)
            if abs(level.mid - centre) <= tol:
                cluster.append(level)
                placed = True
                break
        if not placed:
            clusters.append([level])

    zones: list[Zone] = []
    for cluster in clusters:
        by_family: dict[str, list[Level]] = {}
        for lv in cluster:
            by_family.setdefault(lv.family, []).append(lv)

        weight = 0.0
        evidence: list[ZoneEvidence] = []
        for family, levels in by_family.items():
            fam_weight = float(families.get(family, 0.05))
            # One family counts once, no matter how many of its levels sit here.
            weight += fam_weight
            labels = ", ".join(sorted({lv.label for lv in levels}))
            evidence.append(ZoneEvidence(
                family=family,
                label=_FAMILY_LABELS.get(family, family),
                weight=round(fam_weight, 3),
                detail=f"{len(levels)}x {labels}",
            ))

        low = min(lv.low for lv in cluster)
        high = max(lv.high for lv in cluster)
        mid = (low + high) / 2.0
        touches = reaction_count(df, low, high, atr_value)
        kind = ZoneKind.support if mid < price else ZoneKind.resistance
        # A zone sitting exactly on price is treated as support if price is
        # above its mid, otherwise resistance — done by the comparison above.

        reaction_weight = float(families.get("reaction_history", 0.12)) if touches >= 1 else 0.0
        total = min(1.0, weight + reaction_weight + min(0.10, 0.025 * touches))
        if touches >= 1 and "reaction_history" not in by_family:
            evidence.append(ZoneEvidence(
                family="reaction_history", label=_FAMILY_LABELS["reaction_history"],
                weight=round(reaction_weight, 3), detail=f"{touches} tested reaction(s) in closed candles",
            ))

        family_names = sorted(by_family.keys() | ({"reaction_history"} if touches >= 1 else set()))
        independent = len(family_names)
        has_structure = "structure_swing" in by_family or "order_block" in by_family
        confirmed = touches >= 1 and has_structure
        status = ZoneStatus.confirmed if confirmed else ZoneStatus.candidate

        if independent >= cfg.high_quality_min_families and total >= cfg.high_quality_min_weight and confirmed:
            quality = ZoneQuality.high
        elif independent >= 2 and total >= cfg.min_quality_score:
            quality = ZoneQuality.medium
        else:
            quality = ZoneQuality.low

        last_tested = None
        if touches:
            tail = df.tail(400)
            hit_mask = (tail["l"].to_numpy(float) <= high) & (tail["h"].to_numpy(float) >= low)
            hits = np.nonzero(hit_mask)[0]
            if len(hits):
                last_tested = int(tail["t"].to_numpy(int)[hits[-1]])

        distance = abs(price - mid)
        zones.append(Zone(
            id=_zone_id(kind.value, mid, spec.digits),
            kind=kind,
            low=round(low, spec.digits),
            high=round(high, spec.digits),
            mid=round(mid, spec.digits),
            strength=round(total, 3),
            quality=quality,
            status=status,
            families=family_names,
            evidence=evidence,
            touches=touches,
            distance_points=round(distance / spec.point, 1),
            distance_atr=round(distance / atr_value, 2),
            created_t=min((lv.t for lv in cluster), default=t_now),
            last_tested_t=last_tested,
            note=("Confirmed by " + ", ".join(_FAMILY_LABELS.get(f, f) for f in family_names)
                  if confirmed else "Projection only — no closed-candle retest yet"),
        ))

    supports = [z for z in zones if z.kind == ZoneKind.support]
    resistances = [z for z in zones if z.kind == ZoneKind.resistance]
    supports.sort(key=lambda z: (z.distance_atr, -z.strength))
    resistances.sort(key=lambda z: (z.distance_atr, -z.strength))
    return zones, supports[: cfg.max_supports], resistances[: cfg.max_resistances]


def nearest_zone(zones: list[Zone], price: float, digits: int, max_distance_atr: float = 1.0) -> Zone | None:
    best: Zone | None = None
    best_d = float("inf")
    for zone in zones:
        d = abs(price - zone.mid)
        if d < best_d:
            best_d = d
            best = zone
    if best is None:
        return best
    if best.distance_atr and best.distance_atr > max_distance_atr:
        return None
    return best


def zone_contains(zone: Zone, price: float) -> bool:
    return zone.low <= price <= zone.high


def strongest_opposing_zone(zones: list[Zone], entry: float, target: float, direction: str) -> Zone | None:
    """Nearest high-quality zone standing between entry and target."""
    lo, hi = sorted((entry, target))
    blocker = None
    for zone in zones:
        if not (lo < zone.mid < hi):
            continue
        if zone.quality == ZoneQuality.low:
            continue
        if direction == "up" and zone.kind != ZoneKind.resistance:
            continue
        if direction == "down" and zone.kind != ZoneKind.support:
            continue
        if blocker is None or abs(zone.mid - entry) < abs(blocker.mid - entry):
            blocker = zone
    return blocker


def zone_table(zones: list[Zone]) -> list[dict]:
    return [
        {
            "id": z.id,
            "kind": z.kind.value,
            "mid": z.mid,
            "range": [z.low, z.high],
            "strength": z.strength,
            "quality": z.quality.value,
            "status": z.status.value,
            "families": z.families,
            "touches": z.touches,
            "distance_points": z.distance_points,
        }
        for z in zones
    ]


__all__ = ["build_zones", "nearest_zone", "zone_contains", "strongest_opposing_zone", "zone_table",
           "ZoneEngineConfig", "ta"]
