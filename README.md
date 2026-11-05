# No7 AI Trading Pro — V1

แพลตฟอร์มเทรดส่วนตัวแบบ **Local-First + Hybrid Quant AI + Multi-Broker**
รวมกราฟราคาแบบ TradingView, การวิเคราะห์โครงสร้างตลาด, แนวรับ–แนวต้านแบบ confluence,
การพยากรณ์ราคาเป็นช่วงความน่าจะเป็น, สัญญาณ Buy/Sell พร้อม SL/TP, Risk Engine ที่ยับยั้งได้ทุกคำสั่ง
และชั้นส่งคำสั่งที่ทำงานร่วมกับ MT5 (เริ่มที่ **Demo เท่านั้น**)

> **หลักคิด:** ไม่มี AI ตัวไหนทายกราฟถูก 100% ระบบนี้จึงเน้น *วัดผลจริง* —
> เก็บสถิติความแม่นยำแยกตามสภาวะตลาด, บันทึกช่วงที่ระบบ "ไม่ยอมเทรด",
> และยอมให้ Risk Engine ยับยั้ง AI ได้เสมอ
>
> ซอฟต์แวร์นี้เป็นเครื่องมือเพื่อการศึกษา/ทดลอง **ไม่ใช่คำแนะนำการลงทุน**
> ผลทดสอบย้อนหลังไม่รับประกันอนาคต

---

## สถานะปัจจุบัน (V1, บนเครื่องนี้)

| ส่วน | สถานะ |
|---|---|
| API Gateway (FastAPI) + JWT + WebSocket | ✅ ทำงาน |
| Market data (simulated feed, seed 7) + MT5 adapter | ✅ / ⏳ ต้องเทอร์มินัล Windows |
| Trend · Market structure (BOS/CHoCH) · S/R confluence | ✅ |
| Forecast 5/15/30/60/240 นาที + isotonic calibration + P10–P90 | ✅ (บาง horizon ยังไม่ผ่านเกณฑ์ OOS) |
| Signal scoring 0–100 + Risk Gate | ✅ |
| Risk Engine (kill switch, daily/weekly loss, cooldown, spread, news) | ✅ |
| Execution gateway (idempotent, verify-after-send, paper broker) | ✅ |
| Backtest engine + walk-forward + cost model | ✅ |
| AI Journal / Explainer (deterministic, LLM เป็นตัวเลือก) | ✅ |
| Dashboard (Vue 3 + Tailwind + ECharts + Lightweight Charts) | ✅ 10 หน้า |
| MQL5 EA (supervise SL/TP ในเทอร์มินัล) | ⏳ ยังไม่เขียน |
| Mobile PWA / Telegram / LINE | ⏳ |

## Quickstart (Linux/macOS/Windows, ไม่ต้องมี MT5)

```bash
python3 -m pip install fastapi uvicorn pydantic numpy pandas scikit-learn lightgbm PyJWT joblib pyyaml pytest httpx

cd apps/web-dashboard && npm install && npm run build && cd ../..

python3 -m uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8000
# เปิด http://127.0.0.1:8000  →  demo@no7.ai / no7demo1234
# API docs: http://127.0.0.1:8000/api/docs
```

`npm run build` คือขั้นตอนที่ทำให้ FastAPI เสิร์ฟ dashboard ที่ `/` ได้
ถ้ายังไม่ build ระบบจะแสดงหน้า placeholder พร้อมคำสั่งที่ต้องรัน
หรือจะรัน `npm run dev` (พอร์ต 5173) ซึ่ง proxy `/api` และ `/ws` ไปที่ backend ก็ได้

## โครงสร้างโปรเจกต์

```
apps/web-dashboard/        Vue 3 + Tailwind + ECharts + Lightweight Charts (10 หน้า)
apps/mobile-pwa/           (ว่าง — เฟสถัดไป)
services/
  api_gateway/             FastAPI, JWT, WebSocket, SPA serving
  market_data/             simulator + news calendar + tick pipeline
  strategy_engine/         trend, structure, scoring, จะ generate สัญญาณ
  ai_forecast/             features, LightGBM, isotonic calibration, quantile bands
  risk_engine/             limits, kill switch, gate, trade planner
  execution_gateway/       idempotent order sending, verification, reconciliation
  backtest_engine/         replay + cost model + walk-forward + verdict
  notification/            in-app alerts (Telegram/LINE = TODO)
packages/
  shared_schemas/          pydantic models + settings loader
  indicators/              EMA/RSI/ATR/ADX/MACD/VWAP/volume profile
  market_structure/        swings, BOS, CHoCH, regime
  strategy_rules/          zone builder (confluence), entry rules
  persistence/             SQLite (swap for Postgres later)
integrations/
  brokers/                 adapter interface, paper/MT5, registry, profiles
  mt5/                     python bridge + MQL5 EA (TODO)
  no7_local_ai/            Ollama client for explanations only
config/                    app.yaml, brokers.yaml, risk.yaml, strategies.yaml
tests/                     pytest — maths, risk gate, zones, HTTP contract
docs/                      architecture, runbook, API, limitations
storage/                   db / datasets / models / backtests / logs (git-ignored)
```

## กฎที่ระบบบังคับใช้ (ไม่ใช่แค่เอกสาร)

- **Risk Engine veto ได้ทุกเมื่อ** — ทุกการปฏิเสธมีชื่อกฎและตัวเลขกำกับ
  (`spread 82 pts exceeds max 60 pts`, `daily P&L -2.10% has reached the -2.00% limit`)
- **Lot มาจาก risk amount ÷ ระยะ SL** ไม่ใช่ lot คงที่ และถูกปัดตาม lot step ของโบรกเกอร์
- **ไม่มี Martingale / Grid เพิ่มไม้ขาดทุน / Average down**
- **ไม่เทรดเมื่อ** ข้อมูลค้าง, MT5 ขาดการเชื่อมต่อ, spread กว้าง, slippage สูง,
  มีไม้ซ้ำ, ชนเพดานขาดทุน, หรืออยู่ในช่วงข่าวแรง
- **Signal score ≠ probability** — คะแนนเป็น heuristic, ความน่าจะเป็นต้องผ่าน calibration แยก
- **Forecast ต้องมี 3 สถานการณ์ + ช่วง P10–P90** ไม่มีเส้นเดียวที่บอกอนาคต
- **โซน confirmed vs candidate แยกกัน** — confirmed ต้องมีการทดสอบซ้ำด้วยแท่งปิด
- **Full Auto ปิดไว้เป็นค่าเริ่มต้น** ต้องเปิด env + toggle + โมเดลผ่าน OOS + บัญชี demo
- **LLM อธิบายได้ แต่สั่งออร์เดอร์ไม่ได้**
- **Secrets ไม่อยู่ใน git** (`NO7_JWT_SECRET`, MT5 password, bot tokens → `.env`)

## การใช้งานประจำวัน

| หน้า | ใช้ทำอะไร |
|---|---|
| Terminal | ราคา + โซน + สัญญาณ + แผนเทรด + สถานะ risk ในหน้าจอเดียว |
| Forecast | 3 scenarios, P10–P90, P(TP ก่อน SL), ตาราง metric OOS |
| Zones | บันไดแนวรับ/แนวต้านพร้อมหลักฐานอิสระและน้ำหนัก |
| Trades | สถิติจริงหลังหักต้นทุน, equity curve, สาเหตุการปิดไม้ |
| Risk | ตั้งเพดาน, kill switch, points calculator, ladder preview |
| Backtest | ทดสอบย้อนหลังพร้อม spread/commission/slippage + walk-forward |
| Journal | บันทึกทุกไม้อัตโนมัติ + บทเรียน + ถาม Explainer |
| Brokers | สลับโบรกเกอร์, spec จริงต่อบัญชี, health/reconcile |
| System | สถานะ service, model registry, audit log, error log |

## ทดสอบ

```bash
python3 -m pytest tests/ -q      # 37 tests: maths, risk gate, zones, HTTP contract
```

## ข้อจำกัดที่ต้องอ่านก่อนใช้เงินจริง

1. **Feed ในเครื่องนี้เป็น simulated** (seed 7) — ตัวเลขทั้งหมดเป็นตัวอย่าง ไม่ใช่ตลาดจริง
2. **โมเดลยังไม่ผ่านเกณฑ์ทุก horizon** — ระบบจะติดป้าย `UNVALIDATED` และใช้ค่าฐานสถิติแทน
3. **ยังไม่มี tick data จริง** สำหรับ backtest (ใช้ M1 จาก feed) — ต้องอัปเกรดก่อนเชื่อถือผล
4. **Backtest ยังไม่ reproducible 100%** เพราะ feed ถูก generate ตามเวลาปัจจุบัน (ดู `docs/LIMITATIONS.md`)
5. **MQL5 EA ยังไม่เขียน** — ถ้า AI ดับ SL/TP จะไม่ถูกดูแลในเทอร์มินัล (ข้อกำหนดข้อนี้ยังไม่ครบ)
6. **Connext + FSA (SVG) ไม่ได้กำกับ Forex โดยตรง** และ ธปท. เตือนเรื่องแพลตฟอร์มนอกระบบ
   → ใช้ Demo, ตรวจสอบกฎหมาย/ความคุ้มครองในไทยก่อนฝากเงินจริง

## เอกสาร

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — ชั้นต่าง ๆ และเหตุผลการออกแบบ
- [`docs/API.md`](docs/API.md) — รายการ endpoint ที่ dashboard ใช้
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — ตั้งค่า Windows + MT5, env, การแก้ปัญหา
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — สิ่งที่ยังไม่จริง/ยังไม่ครบ (อ่านก่อนตัดสินใจ)
- [`.env.example`](.env.example) — ตัวแปรทั้งหมดที่ต้องตั้ง
