"""AI Trade Explainer — explains a decision using only recorded facts.

Deterministic template first (always available, no hallucination), optionally
rewritten by the local No7 AI model with the fact sheet pinned in the prompt.
"""
from __future__ import annotations

from typing import Any

from integrations.no7_local_ai.client import No7LocalAI
from packages.shared_schemas.models import (
    AnalysisSnapshot,
    ForecastBundle,
    Signal,
    SignalAction,
)


class TradeExplainer:
    def __init__(self, llm: No7LocalAI | None = None) -> None:
        self.llm = llm or No7LocalAI()

    def fact_sheet(self, signal: Signal | None, snapshot: AnalysisSnapshot | None,
                   forecast: ForecastBundle | None,
                   observability: dict[str, Any] | None = None) -> dict[str, Any]:
        facts: dict[str, Any] = {"symbol": snapshot.symbol if snapshot else None,
                                 "price": snapshot.price if snapshot else None,
                                 "timeframe": snapshot.timeframe if snapshot else None}
        if observability is not None:
            # Deliberately keep this allowlist small: no account identifiers,
            # credentials, positions or command-shaped data enter the AI context.
            facts["observability"] = {
                "feed_mode": str(observability.get("feed_mode") or "unknown"),
                "quote_status": str(observability.get("quote_status") or "unavailable"),
                "quote_source": str(observability.get("quote_source") or "unavailable"),
                "display_basis": str(observability.get("display_basis") or "unknown"),
                "server_utc_offset_seconds": observability.get("server_utc_offset_seconds"),
            }
        if signal:
            facts.update({
                "decision": signal.action.value,
                "status": signal.status.value,
                "score": signal.score,
                "strategy": signal.strategy,
                "regime": signal.regime,
                "reasons": signal.reasons[:8],
                # Raw blocker prose may contain an account-derived cash budget.
                # This route has no selected-account ownership proof, so expose
                # stable reason codes (or one generic marker) instead.
                "blockers": (signal.blocker_codes[:8] if signal.blocker_codes else
                             (["details_unavailable"] if signal.blockers else [])),
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
                                   "close_pct": t.close_pct, "feasible": t.feasible}
                                  for t in p.partials],
                    "rr_gross": p.reward_risk, "rr_net": p.reward_risk_net,
                    "costs_points": p.estimated_cost,
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

    @staticmethod
    def officer_team(facts: dict[str, Any], source_time: int | None = None) -> dict[str, Any]:
        """Build an advisory-only officer brief from the existing allowlisted facts.

        This is a deterministic role projection, not another model, signal, risk,
        account or execution engine. No user prompt or private account data enters it.
        """
        facts = facts if isinstance(facts, dict) else {}
        observability = facts.get("observability")
        observability = observability if isinstance(observability, dict) else {}
        quote_status = observability.get("quote_status")
        quote_status = quote_status if quote_status in {"fresh", "stale", "unavailable"} else "unavailable"
        feed_mode = observability.get("feed_mode")
        feed_mode = feed_mode if feed_mode in {
            "simulate", "simulated", "replay", "mt5", "mt5-live",
            "mt5_demo_publisher", "mt5_demo_publisher_stale", "unknown",
        } else "unknown"
        quote_source = observability.get("quote_source")
        quote_source = quote_source if quote_source in {
            "broker", "persisted", "mt5_demo_publisher", "unavailable",
        } else "unavailable"
        data_quality = facts.get("data_quality")
        analysis_quality = ("ok" if isinstance(data_quality, dict) and data_quality.get("ok") is True
                            else "unverified")
        analysis_ready = quote_status == "fresh" and analysis_quality == "ok"
        time_basis = observability.get("display_basis")
        time_basis = time_basis if time_basis in {"utc", "broker_server", "unknown"} else "unknown"
        freshness = quote_status
        common = {"source_timestamp": source_time if isinstance(source_time, int) else None,
                  "time_basis": time_basis, "freshness": freshness,
                  "analysis_quality": analysis_quality}

        officers: list[dict[str, Any]] = [{
            "role_id": "market_data_steward",
            "title": "ผู้ดูแลข้อมูลตลาด",
            "status": "available" if quote_status == "fresh" else quote_status,
            "summary": (f"Feed {feed_mode}; quote {quote_status} จาก {quote_source}; "
                        f"คุณภาพ snapshot {analysis_quality}; เวลาอ้างอิง {time_basis}."),
            "fact_refs": ["observability.feed_mode", "observability.quote_status",
                          "observability.quote_source", "observability.display_basis", "data_quality"],
            **common,
        }]

        if analysis_ready:
            trend_rows = facts.get("trend") if isinstance(facts.get("trend"), list) else []
            trend_labels: list[str] = []
            for row in trend_rows[:4]:
                if not isinstance(row, dict):
                    continue
                timeframe = row.get("tf")
                direction = row.get("direction")
                if timeframe in {"M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1"} \
                        and direction in {"up", "down", "sideways"}:
                    trend_labels.append(f"{timeframe} {direction}")
            zones = facts.get("zones") if isinstance(facts.get("zones"), dict) else {}
            supports = zones.get("supports") if isinstance(zones.get("supports"), list) else []
            resistances = zones.get("resistances") if isinstance(zones.get("resistances"), list) else []
            if trend_labels:
                summary = "แนวโน้มจาก snapshot เดิม: " + ", ".join(trend_labels)
                refs = ["trend"]
            else:
                summary = "snapshot ปัจจุบันไม่มีข้อมูลแนวโน้มที่ผ่าน allowlist"
                refs = []
            if supports or resistances:
                summary += f"; มีแนวรับ {len(supports)} และแนวต้าน {len(resistances)} รายการใน fact sheet"
                refs.append("zones")
            officers.append({
                "role_id": "structure_analyst",
                "title": "นักวิเคราะห์โครงสร้าง",
                "status": "available" if refs else "unavailable",
                "summary": summary,
                "fact_refs": refs,
                **common,
            })
        else:
            reason = ("คุณภาพ snapshot ไม่ผ่านหรือไม่มีหลักฐาน" if quote_status == "fresh"
                      else "quote ไม่สดหรือไม่มีข้อมูลยืนยัน")
            officers.append({
                "role_id": "structure_analyst", "title": "นักวิเคราะห์โครงสร้าง",
                "status": "unavailable",
                "summary": f"งดสรุปโครงสร้าง เพราะ{reason}",
                "fact_refs": ["observability.quote_status", "data_quality"], **common,
            })

        decision = facts.get("decision")
        decision = decision if decision in {"BUY", "SELL", "WAIT", "NO_TRADE"} else None
        signal_status = facts.get("status")
        signal_status = signal_status if signal_status in {"strong", "valid", "weak", "no_trade"} else None
        if analysis_ready and decision is not None:
            signal_summary = f"สรุปสัญญาณเดิม {decision} (สถานะ {signal_status or 'ไม่ระบุ'}); ไม่คำนวณคะแนนหรือแผนใหม่"
            signal_refs = ["decision"] + (["status"] if signal_status else [])
            signal_state = "available"
        else:
            signal_summary = "ไม่มีสัญญาณสดที่ยืนยันได้ จึงไม่สรุปทิศทาง"
            signal_refs = ["observability.quote_status", "data_quality"]
            signal_state = "unavailable"
        officers.append({
            "role_id": "signal_analyst", "title": "นักวิเคราะห์สัญญาณ",
            "status": signal_state, "summary": signal_summary,
            "fact_refs": signal_refs, **common,
        })
        officers.append({
            "role_id": "risk_officer", "title": "เจ้าหน้าที่ความเสี่ยง",
            "status": "unavailable",
            "summary": "ยังไม่มี Risk Engine read model ที่ผูกสิทธิ์บัญชีใน explain route; ไม่อนุมานวงเงินหรืออนุมัติความเสี่ยง",
            "fact_refs": [], **common,
        })

        if analysis_ready and decision is not None:
            chair_summary = f"รวบรวมจาก quote สดและสัญญาณเดิม {decision}; ไม่มีการโหวตเฉลี่ยหรืออนุมัติคำสั่ง"
            chair_refs = ["observability.quote_status", "decision"]
            chair_state = "available"
        else:
            chair_summary = "ยังสรุปความเห็นร่วมไม่ได้ เพราะข้อมูลตลาดไม่สดหรือสัญญาณไม่พร้อม"
            chair_refs = ["observability.quote_status", "data_quality"]
            chair_state = "unavailable"
        officers.append({
            "role_id": "desk_chair", "title": "หัวหน้าทีม",
            "status": chair_state, "summary": chair_summary,
            "fact_refs": chair_refs, **common,
        })
        return {
            "version": "u12-readonly-v1",
            "mode": "deterministic_read_only",
            "account_specific": False,
            "execution_capability": False,
            "officers": officers,
        }

    def deterministic_answer(self, question: str, signal: Signal | None,
                             snapshot: AnalysisSnapshot | None, forecast: ForecastBundle | None) -> dict[str, Any]:
        q = (question or "").lower()
        bullets: list[str] = []
        action = signal.action if signal else SignalAction.no_trade
        if signal is None:
            return {"answer": "ยังไม่มีสัญญาณสำหรับคู่นี้ กรุณารอรอบวิเคราะห์ถัดไป",
                    "bullets": [], "citations": []}

        if "why" in q and ("not" in q or "ไม่" in q):
            safe_codes = signal.blocker_codes[:5]
            bullets = [f"เงื่อนไขที่ยังไม่ผ่าน: {code}" for code in safe_codes] or \
                      (["มีเงื่อนไขที่ยังไม่ผ่าน; รายละเอียดเชิงบัญชีไม่แสดงในคำอธิบายที่ยังไม่ผูกบัญชี"]
                       if signal.blockers else []) or \
                      [f"Score {signal.score:.0f} is below the execution threshold."]
            answer = "ยังไม่เข้าเทรดเพราะเงื่อนไขเหล่านี้:" if signal.blockers else "ยังไม่เข้าเทรดเพราะคะแนนยังไม่ผ่านเกณฑ์"
        elif signal.action in (SignalAction.buy, SignalAction.sell):
            plan = signal.plan
            bullets = [f"{c.label}: {c.score:.0f}/{c.max_score:.0f} — {c.detail}" for c in signal.components]
            if plan:
                bullets.append(
                    f"แผนมี SL {plan.sl_points:.0f} points; ไม่แสดง lot หรือวงเงินเสี่ยง "
                    "เพราะยังไม่ได้ยืนยันขอบเขตบัญชีของผู้ใช้")
                bullets.append(
                    f"TP ladder {', '.join(f'{points:.0f}' for points in plan.tp_points)} points, "
                    f"R:R สุทธิ {plan.reward_risk_net:.2f} หลังหัก spread/commission")
                bullets.append(
                    f"โอกาสถึง TP ก่อน SL ≈ {plan.p_tp_before_sl:.0%} "
                    f"(จุดคุ้มทุน {signal.explanation.get('breakeven_probability', 0) or 0:.0%})")
            answer = (f"สัญญาณ {signal.action.value} จากกลยุทธ์ {signal.strategy} "
                      f"ด้วยคะแนน {signal.score:.0f}/100 ใน regime {signal.regime}")
        else:
            bullets = [f"{c.label}: {c.score:.0f}/{c.max_score:.0f} — {c.detail}" for c in signal.components]
            bullets += [f"เงื่อนไขที่ยังไม่ผ่าน: {code}" for code in signal.blocker_codes[:4]]
            if signal.blockers and not signal.blocker_codes:
                bullets.append("มีเงื่อนไขที่ยังไม่ผ่าน; รายละเอียดเชิงบัญชีไม่แสดงในคำอธิบายที่ยังไม่ผูกบัญชี")
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
                forecast: ForecastBundle | None,
                observability: dict[str, Any] | None = None) -> dict[str, Any]:
        base = self.deterministic_answer(question, signal, snapshot, forecast)
        if self._looks_like_an_order(question):
            base["answer"] = (
                "ช่องนี้ตอบคำถามเท่านั้น ไม่สามารถสั่งซื้อ/ขายได้ — "
                "การเปิด-ปิดไม้ต้องทำที่หน้า Terminal หรือกดยืนยันคำสั่งเอง"
                + "\n\n" + str(base.get("answer", ""))
            )
            base["bullets"] = ["ไม่มีการส่งคำสั่งใด ๆ จากช่องทางนี้"] + list(base.get("bullets") or [])
            # Do not pass an execution request to a generative model. The model
            # is text-only today, but this remains fail-closed if its transport
            # or deployment changes later.
            return base
        if not self.llm.enabled:
            return base
        facts = self.fact_sheet(signal, snapshot, forecast, observability)
        system = (
            "You are No7 AI, the explainer inside a trading terminal. Answer in Thai, concisely. "
            "Use ONLY the JSON fact sheet. Never invent prices, probabilities or P&L. "
            "If a field is missing, say it is unavailable. Never promise profits. "
            "You have no tools or execution capability. Never claim to place, modify or close an order."
        )
        prompt = (f"คำถามของผู้ใช้: {question}\n\nFACT SHEET (JSON):\n{No7LocalAI.dumps(facts)}\n\n"
                  f"ตอบเป็นภาษาไทย 3-6 ข้อสั้น ๆ")
        text = self.llm.generate(system, prompt)
        if text:
            base["answer"] = text
            base["model_used"] = f"{self.llm.model} (local)"
        return base
