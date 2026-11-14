"""Why a decision did not become a trade, counted by a stable reason code.

The measurement that prompted this: on 20,000 simulated M1 bars the engine
analysed 1,634 decision points, called 25 of them actionable and opened 4 trades.
Every stage recorded a *count* and none recorded a *reason*, so the only honest
answer to "why does this system almost never trade?" was "something rejected it".
With 4 trades, no statistic computed downstream means anything either, and no
threshold can be tuned because nobody knows which threshold is binding.

The information already existed — `Signal.blockers` and `RiskGate.checks` are
produced on every decision — it was simply thrown away. This module keeps it.

Two deliberate design decisions:

* **Codes, not prose.** Blocker text contains live numbers ("score 42 is below
  the 70 execution threshold"), so counting the strings produces one bucket per
  decision. Every blocker is emitted with a stable `code` alongside its text, and
  only codes are counted. Pattern-matching the prose was the alternative and it
  rots silently the first time someone rewords a message.
* **`primary` and `fired` are both reported, because they answer different
  questions.** A decision usually trips several rules at once. `fired` counts
  every rule that objected (how often does this rule object?). `primary` counts
  only the most binding one per decision, by a fixed precedence, so the buckets
  sum exactly to the number of blocked decisions — that is the column to read
  when deciding what to fix first. Reporting only `fired` would overstate every
  rule; reporting only `primary` would hide rules that always fire behind a
  higher-precedence one.

An unknown code is never silently merged into a bucket: it is kept under its own
name with sample text, so a new blocker that nobody registered shows up as
`unregistered:*` in the report instead of quietly disappearing.
"""
from __future__ import annotations

from typing import Any, Iterable

# ---------------------------------------------------------------------------
# The taxonomy. Order *is* the precedence used for `primary`: environmental
# facts the strategy cannot influence come first, then structure, then the
# tunable thresholds last — a score threshold is only the binding reason when
# nothing more fundamental objected.
BLOCKER_CODES: tuple[tuple[str, str], ...] = (
    # --- environment: nothing about this trade, everything about the moment
    ("news_lockout", "ช่วงล็อกข่าวแรง"),
    ("data_quality", "คุณภาพข้อมูลไม่ผ่าน"),
    ("broker_health", "การเชื่อมต่อโบรกเกอร์ไม่พร้อม"),
    ("regime_news_shock", "ตลาดอยู่ในภาวะ news shock"),
    # --- structure: there is no trade to make here
    ("no_direction", "โครงสร้างราคาไม่ชี้ทิศ (sideways)"),
    ("entry_conditions", "เงื่อนไขเข้าไม่ครบ"),
    # --- sizing / geometry: there is a trade, but it cannot be built
    ("no_fx_rate", "ไม่มีอัตราแลกเปลี่ยนสำหรับตีมูลค่า P&L"),
    ("risk_budget_min_lot", "งบความเสี่ยงไม่พอสำหรับ lot ขั้นต่ำ"),
    ("lot_step", "lot ที่คำนวณได้ผิด lot step"),
    ("stop_vs_costs", "ระยะ stop สั้นเกินไปเมื่อเทียบกับต้นทุน"),
    ("reward_risk", "reward/risk สุทธิต่ำกว่าขั้นต่ำ"),
    ("tp1_reward", "เป้าหมายแรกให้ผลตอบแทนต่ำกว่า 1R"),
    ("partial_lot", "แบ่งไม้ตาม ladder ไม่ได้ตาม lot step"),
    ("no_plan", "สร้างแผนเทรดไม่สำเร็จ"),
    # --- tunable thresholds: the dials an operator actually turns
    ("score_below_execute", "คะแนนต่ำกว่าเกณฑ์สั่งเข้า"),
    ("probability_floor", "ความน่าจะเป็น TP ก่อน SL ต่ำกว่าพื้น"),
)

CODE_ORDER: dict[str, int] = {code: i for i, (code, _) in enumerate(BLOCKER_CODES)}
CODE_LABELS: dict[str, str] = dict(BLOCKER_CODES)

# Gate check names come from RiskEngine.gate() and are already stable
# identifiers, so they need no taxonomy of their own — only a readable label.
# `primary` for the gate is the first failing check in the order gate() adds
# them, which runs from the most fundamental (kill switch) outwards. An
# unlisted name still reports under itself rather than being dropped.
GATE_LABELS: dict[str, str] = {
    "kill_switch": "kill switch ทำงาน",
    "broker_health": "การเชื่อมต่อโบรกเกอร์ไม่พร้อม",
    "data_quality": "คุณภาพข้อมูลไม่ผ่าน",
    "spread": "spread กว้างเกินเพดาน",
    "max_open_trades": "จำนวนไม้ที่เปิดพร้อมกันเต็ม",
    "daily_loss": "ชนลิมิตขาดทุนรายวัน",
    "drawdown": "ชนลิมิต drawdown",
    "weekly_loss": "ชนลิมิตขาดทุนรายสัปดาห์",
    "cooldown": "อยู่ในช่วงพักหลังขาดทุนติดกัน",
    "consecutive_losses": "ขาดทุนติดกันถึงเพดาน",
    "exposure": "ขนาดพอร์ตรวมเกินเพดาน",
    "trades_per_week": "โควตาไม้ต่อสัปดาห์เต็ม",
    "volatility": "ความผันผวนสูงผิดปกติ",
    "news_lockout": "ช่วงล็อกข่าวแรง",
    "full_auto_lock": "โหมด full auto ถูกล็อกไว้",
    "full_auto_score": "คะแนนไม่ถึงเกณฑ์ full auto",
    "full_auto_model": "โมเดลไม่อนุมัติสำหรับ full auto",
    "full_auto_probability": "ความน่าจะเป็นไม่ถึงเกณฑ์ full auto",
}


def _label(code: str, labels: dict[str, str]) -> str:
    if code in labels:
        return labels[code]
    if code.startswith("unregistered:"):
        return f"ยังไม่ได้ลงทะเบียนในตาราง ({code.split(':', 1)[1]})"
    return code.replace("_", " ")


def normalise(code: str) -> str:
    """Known codes pass through; anything else is kept, flagged, never merged."""
    code = (code or "").strip()
    if not code:
        return "unregistered:empty"
    return code if code in CODE_ORDER else f"unregistered:{code}"


class BlockerTally:
    """Counts blocked decisions by reason, for a backtest run or a live window."""

    def __init__(self, keep_samples: int = 2) -> None:
        self.keep_samples = max(0, int(keep_samples))
        self.decisions = 0          # decisions this tally was offered
        self.passed = 0             # decisions that produced an actionable signal
        self.blocked = 0            # decisions that did not
        self.primary: dict[str, int] = {}
        self.fired: dict[str, int] = {}
        self.samples: dict[str, list[str]] = {}
        # gate stage
        self.gate_seen = 0
        self.gate_allowed = 0
        self.gate_blocked = 0
        self.gate_primary: dict[str, int] = {}
        self.gate_fired: dict[str, int] = {}

    # ------------------------------------------------------------------ input
    def _remember(self, code: str, detail: str) -> None:
        if not detail or self.keep_samples <= 0:
            return
        bucket = self.samples.setdefault(code, [])
        if len(bucket) < self.keep_samples and detail not in bucket:
            bucket.append(detail[:160])

    def add_signal(self, actionable: bool, codes: Iterable[str] = (),
                   details: Iterable[str] = ()) -> str | None:
        """Record one decision. Returns the primary blocker code, if blocked.

        `actionable` is the caller's own verdict (the signal asked to buy or
        sell), so this module never re-implements that decision.
        """
        self.decisions += 1
        if actionable:
            self.passed += 1
            return None
        self.blocked += 1
        text = list(details)
        found = [normalise(c) for c in codes if str(c).strip()]
        if not found:
            # A decision that produced no trade and no reason is itself a finding:
            # it means a path returns `no_trade` without saying why.
            found = ["unregistered:no_reason_given"]
        for i, code in enumerate(found):
            self.fired[code] = self.fired.get(code, 0) + 1
            if i < len(text):
                self._remember(code, text[i])
        primary = min(found, key=lambda c: (CODE_ORDER.get(c, len(CODE_ORDER) + 1), c))
        self.primary[primary] = self.primary.get(primary, 0) + 1
        return primary

    def add_gate(self, allow: bool, checks: Iterable[dict[str, Any]] = ()) -> str | None:
        """Record one risk-gate evaluation using `RiskGate.checks`."""
        self.gate_seen += 1
        if allow:
            self.gate_allowed += 1
            return None
        self.gate_blocked += 1
        failed = [str(c.get("name") or "unnamed") for c in checks
                  if isinstance(c, dict) and not c.get("ok", True)]
        if not failed:
            failed = ["unregistered:no_failing_check"]
        for name in failed:
            self.gate_fired[name] = self.gate_fired.get(name, 0) + 1
            detail = next((str(c.get("detail") or "") for c in checks
                           if isinstance(c, dict) and c.get("name") == name), "")
            self._remember(f"gate:{name}", detail)
        primary = failed[0]
        self.gate_primary[primary] = self.gate_primary.get(primary, 0) + 1
        return primary

    # ----------------------------------------------------------------- output
    @staticmethod
    def _rows(counts: dict[str, int], total: int, labels: dict[str, str],
              samples: dict[str, list[str]], prefix: str = "") -> list[dict[str, Any]]:
        out = []
        for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            out.append({
                "code": code,
                "label": _label(code, labels),
                "count": n,
                "pct": round(100.0 * n / total, 1) if total else 0.0,
                "samples": list(samples.get(f"{prefix}{code}", [])),
            })
        return out

    def summary(self) -> dict[str, Any]:
        """Everything a reader needs to answer 'what do I fix first?'."""
        unregistered = sorted(
            [c for c in list(self.fired) + list(self.primary) if c.startswith("unregistered:")]
            + [f"gate:{c}" for c in self.gate_fired if c.startswith("unregistered:")])
        out: dict[str, Any] = {
            "signal": {
                "decisions": self.decisions,
                "actionable": self.passed,
                "blocked": self.blocked,
                "primary": self._rows(self.primary, self.blocked, CODE_LABELS, self.samples),
                "fired": self._rows(self.fired, self.blocked, CODE_LABELS, self.samples),
            },
            "gate": {
                "evaluated": self.gate_seen,
                "allowed": self.gate_allowed,
                "blocked": self.gate_blocked,
                "primary": self._rows(self.gate_primary, self.gate_blocked, GATE_LABELS,
                                      self.samples, prefix="gate:"),
                "fired": self._rows(self.gate_fired, self.gate_blocked, GATE_LABELS,
                                    self.samples, prefix="gate:"),
            },
            "basis": ("primary = เหตุผลที่ผูกมัดที่สุดต่อหนึ่งการตัดสินใจ (ผลรวม = จำนวนที่ถูกบล็อก) · "
                      "fired = ทุกกฎที่คัดค้าน (รวมกันได้เกิน เพราะหนึ่งการตัดสินใจติดหลายข้อ)"),
        }
        if unregistered:
            out["warning"] = ("มีเหตุผลที่ยังไม่ได้ลงทะเบียนในตาราง: "
                              + ", ".join(sorted(set(unregistered))[:6]))
        return out

    def top(self, n: int = 3) -> list[tuple[str, int]]:
        return sorted(self.primary.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    def note(self) -> str:
        """One sentence for a report's notes list."""
        if not self.decisions:
            return "No decisions were evaluated, so there is nothing to attribute."
        if not self.blocked:
            return f"All {self.decisions} analysed decisions produced an actionable signal."
        parts = [f"{_label(code, CODE_LABELS)} {n}" for code, n in self.top(3)]
        gate = ""
        if self.gate_blocked:
            gparts = [f"{_label(c, GATE_LABELS)} {n}"
                      for c, n in sorted(self.gate_primary.items(),
                                         key=lambda kv: (-kv[1], kv[0]))[:2]]
            gate = (f"; the risk gate then blocked {self.gate_blocked} of {self.gate_seen} "
                    f"actionable signals ({', '.join(gparts)})")
        return (f"{self.blocked} of {self.decisions} analysed decisions produced no "
                f"tradable signal — most binding: {', '.join(parts)}{gate}.")


def merge(tallies: Iterable[BlockerTally]) -> BlockerTally:
    """Combine per-symbol tallies into one view."""
    out = BlockerTally()
    for t in tallies:
        out.decisions += t.decisions
        out.passed += t.passed
        out.blocked += t.blocked
        out.gate_seen += t.gate_seen
        out.gate_allowed += t.gate_allowed
        out.gate_blocked += t.gate_blocked
        for src, dst in ((t.primary, out.primary), (t.fired, out.fired),
                         (t.gate_primary, out.gate_primary), (t.gate_fired, out.gate_fired)):
            for code, n in src.items():
                dst[code] = dst.get(code, 0) + n
        for code, rows in t.samples.items():
            bucket = out.samples.setdefault(code, [])
            for row in rows:
                if row not in bucket and len(bucket) < out.keep_samples:
                    bucket.append(row)
    return out
