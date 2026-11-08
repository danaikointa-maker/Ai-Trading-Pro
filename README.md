# No7 AI Trading Pro — V1

[![gate](https://github.com/danaikointa-maker/TradeAi/actions/workflows/ci.yml/badge.svg)](https://github.com/danaikointa-maker/TradeAi/actions/workflows/ci.yml)

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
| EA bridge (MQL5 poll → API) | ✅ ฝั่งเซิร์ฟเวอร์ + EA จำลองทดสอบแล้ว / ⏳ EA จริงยังไม่ compile |
| นำเข้าข้อมูลจริง (CSV) + ประเมิน offline บนข้อมูลจริง | ✅ `scripts/import_candles.py` (ดู `docs/DATA.md`) |
| Live replay จากข้อมูลที่นำเข้า (`feed_mode: replay`) | ✅ ใช้งานได้ (ยังไม่ใช่ tick data) |
| Trend · Market structure (BOS/CHoCH) · S/R confluence | ✅ |
| Forecast 5/15/30/60/240 นาที + isotonic calibration + P10–P90 | ✅ (บาง horizon ยังไม่ผ่านเกณฑ์ OOS) |
| Signal scoring 0–100 + Risk Gate | ✅ |
| Risk Engine (kill switch, daily/weekly loss, cooldown, spread, news) | ✅ |
| Execution gateway (idempotent, verify-after-send, paper broker) | ✅ |
| Backtest engine + walk-forward + cost model | ✅ |
| AI Journal / Explainer (deterministic, LLM เป็นตัวเลือก) | ✅ |
| Dashboard (Vue 3 + Tailwind + ECharts + Lightweight Charts) | ✅ 10 หน้า |
| MQL5 EA + bridge (คำสั่งไปถึงเทอร์มินัลครั้งเดียว, shared store หลาย worker) | ✅ (ยังไม่ compile กับ MT5 จริง) |
| Tick storage รายวัน (parquet, lazy) + intra-bar ordering | ✅ |
| Mobile PWA (ติดตั้งได้, แถบอัปเดต/ออฟไลน์ที่บอกความจริง) | ✅ |
| TLS (uvicorn หรือ reverse proxy) + security headers/CORS allowlist | ✅ |
| Telegram / LINE แจ้งเตือน | ✅ ส่งจริงผ่าน HTTP (retry/pacing/redact) — ยังไม่ทดสอบกับปลายทางจริง |

## Quickstart (Linux/macOS/Windows, ไม่ต้องมี MT5)

```bash
./scripts/dev_setup.sh           # venv + dependencies + .env + dashboard bundle (ครั้งแรก ~2 นาที)
./scripts/run.sh                 # ตรวจ/สร้าง dashboard bundle แล้วเปิด port 8000
# เทียบเท่า: python3 -m uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8000
# เปิด http://127.0.0.1:8000  →  demo@no7.ai / no7demo1234
# API docs: http://127.0.0.1:8000/api/docs
```

ติดตั้งเองทีละขั้นก็ได้: `python3 -m pip install -r requirements.txt` แล้ว
`cd apps/web-dashboard && npm install && npm run build`
**จะพัฒนาต่อ** อ่าน [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) (แผนที่โค้ด, สูตรสำเร็จ, กับดัก, งานถัดไป)

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
  notification/            in-app alerts + opt-in Telegram/LINE/webhook (delivery ผลถูกบันทึก)
packages/
  shared_schemas/          pydantic models + settings loader
  indicators/              EMA/RSI/ATR/ADX/MACD/VWAP/volume profile
  market_structure/        swings, BOS, CHoCH, regime
  strategy_rules/          zone builder (confluence), entry rules
  persistence/             SQLite (swap for Postgres later)
services/bridge/           EA bridge relay (MQL5 EA polls out, queue + freshness)
bridge/                    No7BridgeEA.mq5 — EA client (ต้อง compile บน Windows, ยังไม่ทดสอบจริง)
integrations/
  brokers/                 adapter interface, paper/MT5/bridge, registry, profiles
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
./scripts/dev_check.sh           # เกตเต็ม: ruff + dashboard bundle + 548 tests (~2 นาที)
./scripts/test.sh                # เฉพาะ pytest (เลือก .venv ให้เอง)
```

เกตตัวเดียวกันนี้ถูกรันอัตโนมัติทุก pull request ผ่าน GitHub Actions (`.github/workflows/ci.yml`)

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
- [`docs/MATH.md`](docs/MATH.md) — สูตรคำนวณทุกตัว (points/lot/RR/probability/metrics) + สิ่งที่ยังเป็นการประมาณ
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — สิ่งที่ยังไม่จริง/ยังไม่ครบ (อ่านก่อนตัดสินใจ)
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — พัฒนาต่อยังไง: ติดตั้ง, ลูปงาน, เกต, แผนที่โค้ด, backlog
- [`.env.example`](.env.example) — ตัวแปรทั้งหมดที่ต้องตั้ง

## คำสั่งที่ใช้บ่อย (`scripts/`)

| คำสั่ง | ทำอะไร |
|---|---|
| `./scripts/dev_setup.sh` | ติดตั้ง/กู้สภาพแวดล้อมพัฒนา: `.venv` + deps + `.env` + dashboard bundle |
| `./scripts/dev_check.sh` | เกตก่อน commit: ruff → ตรวจ bundle → pytest ทั้งชุด |
| `./scripts/run.sh` | เปิดแอปที่ port 8000 (สร้าง dashboard ให้ถ้ายังไม่มี) |
| `./scripts/build_ui.sh` | `npm install` + build dashboard ลง `apps/web-dashboard/dist` |
| `./scripts/test.sh` | รันชุดทดสอบทั้งหมด (unit + API contract + invariant สูตร) |
| `./scripts/smoke.py` | เช็คว่าระบบมีชีวิตและ payload ครบ (health/live/model/errors) |
| `TOKEN=… ./scripts/train.sh XAUUSD` | สั่งฝึกโมเดลใหม่ผ่าน API |
| `.venv/bin/python scripts/run_bridge_sim.py --token …` | EA จำลอง (โปรโตคอลเดียวกับ EA จริง) สำหรับทดสอบ bridge ก่อนมี MT5 |
| `.venv/bin/python scripts/import_ticks.py --csv … --symbol XAUUSD` | นำเข้า tick จริงให้ backtest ตัดสินลำดับในแท่ง (แยกไฟล์ต่อวัน, อ่านแบบ lazy) |
| `.venv/bin/python scripts/make_pwa_icons.py` | สร้างไอคอน PWA (ถ้าแก้ดีไซน์) |
| `./scripts/fetch_redis_server.sh` | ดึง `redis-server` จริง (ไม่ต้อง root) ไว้ทดสอบ shared rate limit / cluster |
