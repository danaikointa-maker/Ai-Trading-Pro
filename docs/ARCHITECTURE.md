# Architecture — No7 AI Trading Pro V1

## 1. หลักการออกแบบ

1. **Local-first** — ทั้งระบบรันบนเครื่องผู้ใช้ได้ (SQLite, โมเดลในเครื่อง, ไม่พึ่ง cloud)
2. **Hybrid** — rule-based + classical ML; LLM ใช้แค่ภาษา ไม่ใช้ตัดสินใจเทรด
3. **Broker-agnostic** — ทุกคำสั่งผ่าน `BrokerAdapter`; เพิ่มโบรกเกอร์ = 1 adapter + YAML profile
4. **Risk-first** — สร้าง trade plan ก่อน แล้ว Risk Engine ให้ผ่าน/ไม่ผ่าน; ไม่มีทางข้าม gate
5. **Measured, not claimed** — ทุกผลลัพธ์มาพร้อมช่วงความเชื่อมั่น จำนวนไม้ และต้นทุน

## 2. ชั้นข้อมูล (data flow)

```
SimulatedFeed / ReplayFeed (CSV ที่นำเข้า) / MT5 ─┐
                     ├─► MarketDataService (ticks, M1..H4, staleness)
NewsService ─────────┘             │
                                   ▼
                        AnalysisService (1 snapshot / symbol)
                        ├─ indicators (EMA/RSI/ATR/ADX/MACD/VWAP/VP)
                        ├─ market structure (swings, BOS, CHoCH, regime)
                        ├─ zone builder (confluence, confirmed|candidate)
                        └─ data_quality + news_lockout
                                   │
              ┌────────────────────┴─────────────────────┐
              ▼                                          ▼
   ForecastService (LightGBM + isotonic)      StrategyEngine (score + reasons)
              │                                          │
              └──────────────► TradePlanner ◄────────────┘
                                   │  plan: entry/sl/tp1..3/lot/partials
                                   ▼
                             RiskEngine.gate()  ──► allow / blockers
                                   │
                                   ▼
                        ExecutionGateway (idempotency → send → verify)
                                   │
                                   ▼
                        BrokerAdapter (paper / MT5 / future REST)
                                   │
                                   ▼
                    DB (signals, orders, trades, audit) + WS push
```

รอบการตัดสินใจทุก `decision_interval_seconds` (default 4s) ใน thread แยก
WebSocket push snapshot ทุก 1 วินาที (`/ws/live?token=…`)
Dashboard ใช้ WebSocket เป็นหลัก และ fallback ไป `GET /api/trading/live` ทุก 5 วินาที
ถ้า proxy บล็อก WebSocket — payload ตัวเดียวกันทั้งสองทาง

## 3. ทางเลือกที่ตัดสินใจแล้ว (และเหตุผล)

| เรื่อง | ที่ใช้ | เหตุผล |
|---|---|---|
| Web API | **FastAPI** แทน Laravel | เครื่องพัฒนาไม่มี PHP; ML เป็น Python ทั้งหมด → ลด hop, ได้ OpenAPI/Swagger ฟรี, ย้ายไป Laravel ได้ภายหลังเพราะสัญญาเป็น JSON/HTTP |
| DB | **SQLite** (สลับเป็น PostgreSQL ได้) | local-first, ไฟล์เดียว, ไม่ต้องติดตั้ง server; schema อยู่ใน `packages/persistence/db.py` |
| Real-time | WebSocket + REST fallback | dashboard ต้องอัปเดตทุกวินาที แต่ยังต้องใช้ได้ผ่าน proxy ที่ปิด WS |
| SPA | Vue 3 + vue-router (ไม่ใช่ SSR) | เสิร์ฟ `dist` จาก FastAPI พร้อม catch-all → deep link ใช้ได้ |
| Forecast | LightGBM multiclass + isotonic + quantile bands | เร็ว, ให้ทั้งความน่าจะเป็นและช่วงราคา; Temporal CNN จะเพิ่มเมื่อพิสูจน์ว่าเหนือกว่า |
| คำอธิบาย | deterministic template ก่อน, Ollama เป็นตัวเลือก | ระบบต้องอธิบายได้แม้ LLM ไม่ทำงาน และห้าม LLM สั่งออร์เดอร์ |

## 4. Risk Engine

`RiskEngine.gate()` ตรวจตามลำดับและคืน `RiskGate{allow, blockers[], checks[]}`:

| กฎ | ค่าเริ่มต้น (config/risk.yaml) |
|---|---|
| risk per trade | 0.5% ของ equity |
| daily loss | 2.0% → daily kill switch |
| weekly loss | 5.0% |
| max drawdown | 10.0% จาก peak equity |
| max open trades / symbol | 1 / 1 |
| max exposure | 1.0 lot |
| consecutive losses | 3 → cooldown 20 นาที |
| max spread | 60 points |
| max slippage | 15 points |
| min net R:R | 1.3 |
| news lockout | 30 นาทีก่อน – 15 นาทีหลัง ข่าว high-impact |
| abnormal volatility | ATR > 3% ของราคา |
| full auto | env switch + score ≥ 85 + โมเดล approved + P(TP ก่อน SL) ≥ 55% + demo |

`TradePlanner.lot_for_risk()` = `equity × risk% / (SL points × value_per_point_per_lot)`
แล้วปัดตาม `lot_step` ของสัญลักษณ์นั้น ๆ — ไม่มี lot คงที่และไม่มี Martingale

## 5. Zone engine (confluence)

หลักฐาน 11 ตระกูล: structure swing, order block, FVG, pivot, fibonacci,
volume profile, VWAP, EMA, equal highs/lows, round number, reaction history

- ตระกูลหนึ่งนับ **ครั้งเดียว** ในโซนเดียว (กันอินดิเคเตอร์ที่ correlate กันหลอกระบบ)
- `confirmed` = มีการทดสอบซ้ำด้วยแท่งปิด **และ** มีหลักฐานเชิงโครงสร้าง
- `candidate` = projection ล้วน ๆ → แสดงแยก ไม่ใช้ยืนยันสัญญาณ
- ต้องมี ≥ 3 โซนแต่ละฝั่ง (สูงสุด 5) เพื่อให้ decision engine มีบริบท

## 6. Signal scoring

| องค์ประกอบ | น้ำหนัก |
|---|---|
| Trend alignment (หลาย TF) | 30 |
| Market structure (BOS/CHoCH) | 22 |
| Zone quality + proximity | 20 |
| Path probability edge | 18 |
| Momentum / volume | 10 |

ช่วงคะแนน: 85–100 Strong · 70–84 Valid · 50–69 Weak · < 50 No Trade
**คะแนนนี้ไม่ใช่ความน่าจะเป็น** — probability มาจากโมเดลที่สอบเทียบแยก (isotonic)

## 7. Execution

1. สร้าง `idempotency_key` จาก (signal id, symbol, direction) → กันส่งซ้ำ
2. ตรวจ gate อีกครั้งที่ชั้น execution (double-check)
3. ส่งคำสั่ง → **ตรวจสอบกับโบรกเกอร์ทันที** (ticket, volume, price, slippage)
4. บันทึก order/trade/audit ลง DB
5. ถ้าไม่ได้ยืนยัน → mark `unverified` และหยุด ไม่ส่งซ้ำอัตโนมัติ
6. Reconcile ระหว่าง DB กับโบรกเกอร์เป็นรอบ → รายงาน missing/unknown

## 8. Accuracy & honesty

- Directional accuracy, precision, Brier vs baseline, P10–P90 coverage ต่อ horizon
- **การอนุมัติโมเดล**: walk-forward ที่ *ฝึกใหม่ทุก fold* (expanding window) เมื่อประวัติพอ
  ถ้าไม่พอจะถอยไปให้คะแนน slice ของโมเดลเดียว **และระบุว่าถอย** · ต้องผ่าน ≥75% ของ fold,
  ค่ากลางของ fold ต้องผ่านเกณฑ์เดียวกัน และต้องมี **อย่างน้อย 3 fold** — fold เดียวคือหลักฐานไม่พอ
- กฎการอนุมัติมีเวอร์ชัน (`approval_rule`) ฝังในไฟล์โมเดล: กฎเข้มขึ้นเมื่อไร approval เก่าจะถูก demote
  และบอกเหตุผล ไม่ใช่สืบทอดต่อ
- feed ที่ใช้อยู่ (simulate / replay / mt5) ถูกแสดงบนหน้าจอพร้อมข้อจำกัดของมัน ไม่ใช่เดาจากชนิด adapter
- `no_trade_rate` ถูกวัดและรายงาน — "ไม่เทรด" คือผลลัพธ์ที่ถูกต้องได้
- Backtest มี cost model: spread, commission, slippage, swap (คืนละครั้ง, พุธ ×3) และ conservative intrabar assumption (stop ชนก่อน target)

## 9. สิ่งที่ยังขาด (ตามลำดับความสำคัญ)

1. **MQL5 EA + bridge** — ต้องดูแล SL/TP ในเทอร์มินัลเพื่อให้ risk control อยู่รอดเมื่อ AI ดับ
   (ยังทำไม่ได้: ต้องมี Windows + MT5)
2. **tick data จริง** — นำเข้า M1 จากไฟล์ได้แล้วและ replay ผ่านไปป์ไลน์สดได้ แต่ intra-bar path
   ยังเป็นการประมาณ; snapshot ของ dataset สำหรับ reproducible backtest ก็ยังไม่มี
3. **หลาย worker / หลายเครื่อง** — มีสองชั้นแล้ว: (ก) lease ทำให้มี **เจ้าของเดียว** ที่เทรด
   (ข) `cluster.backend: redis` ให้ leader เผยแพร่เฟรมสด แล้วโปรเซสอื่นเสิร์ฟเป็น **replica** ได้
   (อ่านอย่างเดียว) · การได้มา/ต่ออายุ lease เป็น compare-and-set ใน SQL เดียว จึงแข่งกันแล้วมีผู้ชนะคนเดียว · ที่ยังไม่มี: scheduler/training ยังไม่แชร์คิวข้ามเครื่อง, ws hub ยัง fan-out
   ในโปรเซสตัวเอง และ rate limit ข้ามเครื่องยังต้องใช้ store กลาง (`ratelimit.store: sqlite`
   แชร์ได้เฉพาะในเครื่องเดียว)
4. Mobile PWA + Telegram/LINE push
5. Full Auto เปิดใช้หลัง paper forward test ต่อเนื่อง
