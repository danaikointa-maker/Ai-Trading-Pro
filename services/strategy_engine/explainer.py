"""AI Trade Explainer — explains a decision using only recorded facts.

Deterministic template first (always available, no hallucination), optionally
rewritten by the local No7 AI model with the fact sheet pinned in the prompt.
"""
from __future__ import annotations

from typing import Any

from integrations.no7_local_ai.client import No7LocalAI
from packages.shared_schemas.models import AnalysisSnapshot, ForecastBundle, Signal, SignalAction


class TradeExplainer:
    def __init__(self, llm: No7LocalAI | None = None) -> None:
        self.llm = llm or No7LocalAI()

    def fact_sheet(self, signal: Signal | None, snapshot: AnalysisSnapshot | None,
                   forecast: ForecastBundle | None) -> dict[str, Any]:
        facts: dict[str, Any] = {"symbol": snapshot.symbol if snapshot else None,
                                 "price": snapshot.price if snapshot else None,
                                 "timeframe": snapshot.timeframe if snapshot else None}
        if signal:
            facts.update({
                "decision": signal.action.value,
                "status": signal.status.value,
                "score": signal.score,
                "strategy": signal.strategy,
                "regime": signal.regime,
                "reasons": signal.reasons[:8],
                "blockers": signal.blockers[:8],
                "components": [{"name": c.label, "score": c.score, "max": c.max_score, "detail": c.detail}
                               for c in signal.components],
                "conditions": signal.explanation.get("conditions"),
                "p_tp_before_sl": signal.explanation.get("p_tp_before_sl"),
                "breakeven_probability": signal.explanation.get("breakeven_probability"),
                "calibrated": signal.explanation.get("calibrated"),
            })
            if signal.plan:
                p = signal.plan
                facts["plan"] = {
                    "entry": p.entry, "sl": p.sl, "sl_points": p.sl_points,
                    "tp_ladder": [{"level": t.level, "points": t.points, "price": t.price,
                                   "close_pct": t.close_pct, "lot": t.volume, "feasible": t.feasible}
                                  for t in p.partials],
                    "lot": p.lot, "risk_usd": p.risk_amount, "risk_pct": p.risk_pct,
                    "rr_gross": p.reward_risk, "rr_net": p.reward_risk_net,
                    "costs_points": p.estimated_cost, "expected_value_usd": p.expected_value,
                }
        if snapshot:
            facts["trend"] = [{"tf": t.timeframe, "direction": t.direction.value, "strength": t.strength}
                              for t in snapshot.trend]
            facts["zones"] = {
                "supports": [{"id": z.id, "mid": z.mid, "quality": z.quality.value,
                              "status": z.status.value, "families": z.families, "distance_atr": z.distance_atr}
                             for z in snapshot.supports[:3]],
                "resistances": [{"id": z.id, "mid": z.mid, "quality": z.quality.value,
                                 "status": z.status.value, "families": z.families, "distance_atr": z.distance_atr}
                                for z in snapshot.resistances[:3]],
            }
            facts["regime"] = snapshot.regime.model_dump() if snapshot.regime else None
            facts["news_lockout"] = snapshot.news_lockout
            facts["data_quality"] = snapshot.data_quality
        if forecast:
            facts["forecast"] = {
                "model_version": forecast.model_version,
                "approved": forecast.model_approved,
                "confidence": forecast.confidence,
                "horizons": [{"minutes": h.horizon_minutes, "p_up": h.p_up, "p_down": h.p_down,
                              "p_sideways": h.p_sideways, "p10_price": h.p10_price,
                              "p90_price": h.p90_price, "p_tp_before_sl": h.p_tp_before_sl,
                              "calibrated": h.calibrated} for h in forecast.horizons],
                "invalidation": forecast.invalidation,
            }
        return facts

    def deterministic_answer(self, question: str, signal: Signal | None,
                             snapshot: AnalysisSnapshot | None, forecast: ForecastBundle | None) -> dict[str, Any]:
        q = (question or "").lower()
        bullets: list[str] = []
        action = signal.action if signal else SignalAction.no_trade
        if signal is None:
            return {"answer": "ยังไม่มีสัญญาณสำหรับคู่นี้ กรุณารอรอบวิเคราะห์ถัดไป",
                    "bullets": [], "citations": []}

        if "why" in q and ("not" in q or "ไม่" in q):
            bullets = [f"Blocker: {b}" for b in signal.blockers[:5]] or \
                      [f"Score {signal.score:.0f} is below the execution threshold."]
            answer = "ยังไม่เข้าเทรดเพราะเงื่อนไขเหล่านี้:" if signal.blockers else "ยังไม่เข้าเทรดเพราะคะแนนยังไม่ผ่านเกณฑ์"
        elif signal.action in (SignalAction.buy, SignalAction.sell):
            plan = signal.plan
            bullets = [f"{c.label}: {c.score:.0f}/{c.max_score:.0f} — {c.detail}" for c in signal.components]
            if plan:
                bullets.append(
                    f"Lot {plan.lot} จากความเสี่ยง {plan.risk_pct:.2f}% ของทุน "
                    f"(${plan.risk_amount:.2f}) และ SL {plan.sl_points:.0f} points")
                bullets.append(
                    f"TP ladder {', '.join(f'{t.points:.0f}' for t in plan.tp_points)} points, "
                    f"R:R สุทธิ {plan.reward_risk_net:.2f} หลังหัก spread/commission")
                bullets.append(
                    f"โอกาสถึง TP ก่อน SL ≈ {plan.p_tp_before_sl:.0%} "
                    f"(จุดคุ้มทุน {signal.explanation.get('breakeven_probability', 0) or 0:.0%})")
            answer = (f"สัญญาณ {signal.action.value} จากกลยุทธ์ {signal.strategy} "
                      f"ด้วยคะแนน {signal.score:.0f}/100 ใน regime {signal.regime}")
        else:
            bullets = [f"{c.label}: {c.score:.0f}/{c.max_score:.0f} — {c.detail}" for c in signal.components]
            bullets += [f"Blocker: {b}" for b in signal.blockers[:4]]
            answer = f"สถานะ {signal.action.value} (คะแนน {signal.score:.0f}/100) — ยังไม่มี setup ที่ผ่านทุกเงื่อนไข"

        if forecast and forecast.horizons:
            h = max(forecast.horizons, key=lambda x: x.confidence)
            bullets.append(
                f"Forecast {h.horizon_minutes} นาที: up {h.p_up:.0%} / down {h.p_down:.0%} / "
                f"sideways {h.p_sideways:.0%}, ช่วง P10–P90 {h.p10_price:.2f}–{h.p90_price:.2f} "
                f"({'ผ่านการสอบเทียบ' if h.calibrated else 'ยังไม่ผ่านการสอบเทียบ — ใช้เป็นข้อมูลประกอบเท่านั้น'})")

        if snapshot:
            q_zones = [z for z in (snapshot.supports + snapshot.resistances) if z.quality.value == "high"][:2]
            for z in q_zones:
                bullets.append(
                    f"โซนคุณภาพสูง {z.kind.value} {z.id} ({z.low:.2f}–{z.high:.2f}) "
                    f"หลักฐานอิสระ {len(z.families)} กลุ่ม: {', '.join(z.families)}")

        citations = [c.key for c in signal.components]
        return {
            "answer": answer,
            "bullets": bullets,
            "citations": citations,
            "decision": action.value,
            "score": signal.score,
            "model_used": "deterministic",
        }

    #: Words that look like an instruction to trade. The explainer explains; it
    #: never executes, and it must say so instead of leaving the user guessing.
    TRADE_INTENT = ("ซื้อ", "ขาย", "เปิดไม้", "ปิดไม้", "ปิดออเดอร์", "เข้าไม้",
                    " buy ", " sell ", "open ", "close ", "lot")

    def _looks_like_an_order(self, question: str) -> bool:
        text = f" {question.strip().lower()} "
        return any(token in text for token in self.TRADE_INTENT)

    def explain(self, question: str, signal: Signal | None, snapshot: AnalysisSnapshot | None,
                forecast: ForecastBundle | None) -> dict[str, Any]:
        base = self.deterministic_answer(question, signal, snapshot, forecast)
        if self._looks_like_an_order(question):
            base["answer"] = (
                "ช่องนี้ตอบคำถามเท่านั้น ไม่สามารถสั่งซื้อ/ขายได้ — "
                "การเปิด-ปิดไม้ต้องทำที่หน้า Terminal หรือกดยืนยันคำสั่งเอง"
                + "\n\n" + str(base.get("answer", ""))
            )
            base["bullets"] = ["ไม่มีการส่งคำสั่งใด ๆ จากช่องทางนี้"] + list(base.get("bullets") or [])
        if not self.llm.enabled:
            return base
        facts = self.fact_sheet(signal, snapshot, forecast)
        system = (
            "You are No7 AI, the explainer inside a trading terminal. Answer in Thai, concisely. "
            "Use ONLY the JSON fact sheet. Never invent prices, probabilities or P&L. "
            "If a field is missing, say it is unavailable. Never promise profits."
        )
        prompt = (f"คำถามของผู้ใช้: {question}\n\nFACT SHEET (JSON):\n{No7LocalAI.dumps(facts)}\n\n"
                  f"ตอบเป็นภาษาไทย 3-6 ข้อสั้น ๆ")
        text = self.llm.generate(system, prompt)
        if text:
            base["answer"] = text
            base["model_used"] = f"{self.llm.model} (local)"
        return base
