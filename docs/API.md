# API — what the dashboard relies on

Base: `http://127.0.0.1:8000` · interactive docs: `/api/docs` · OpenAPI: `/api/openapi.json`
ทุก endpoint ใต้ `/api/` (ยกเว้น login/health) ต้องมี `Authorization: Bearer <jwt>`

## Rate limits

ทุกคำขอ (ยกเว้น `/api/system/health`, static, `/api/docs`, `/ws`) ถูกนับแบบ token bucket
ต่อ **ผู้ใช้** (ถ้ามี bearer token ที่ถูกต้อง) หรือต่อ **IP** ถ้าไม่มี:

| bucket | ครอบคลุม | limit |
|---|---|---|
| `order` | `POST /api/trading/order`, `/close`, `/close-all` | 10 / นาที |
| `explain` | `POST /api/explain` | 20 / นาที |
| `backtest` | `POST /api/backtests` | 6 / นาที |
| `train` | `POST /api/forecast/train` | 2 / ชั่วโมง |
| `default` | ที่เหลือ (รวม GET ทั้งหมด) | 300 / นาที |

- เกิน limit → **429** พร้อม header `Retry-After` (วินาที) และ body
  `{"detail": "...", "rule": "order", "retry_after": 2.4}`
- ทุกคำขอที่ผ่านจะได้ header `X-RateLimit-Remaining`
- ค่าปรับได้ที่ `config/app.yaml` → `ratelimit.rules` (ปิดทั้งบล็อกได้ด้วย `enabled: false`)
- **ที่เก็บ bucket** เลือกได้ที่ `ratelimit.store`:
  - `memory` (ค่าเริ่มต้น) — bucket อยู่ในโปรเซสเดียว เหมาะกับ uvicorn worker เดียว
  - `sqlite` — bucket อยู่ในไฟล์ SQLite (`store_path` หรือ `storage/db/ratelimit.sqlite3`)
    ทำให้ **หลาย worker บนเครื่องเดียวกันใช้โควตาร่วมกัน** แลกกับ write ต่อคำขอที่ถูกจำกัด
    (แต่ละครั้งเป็น `BEGIN IMMEDIATE` จึงไม่มีการใช้โทเคนซ้ำข้าม worker)
  - ค่าอื่น → app ไม่ start (ผิดชัดเจน ดีกว่าเงียบ ๆ ใช้ memory)

## Auth & system

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` | `{email,password}` → `{token, expires_in, user}` |
| GET | `/api/auth/me` | ตรวจ token |
| GET | `/api/system/health` | public: services, broker_health, feed_mode, uptime |
| GET | `/api/system/config` | symbols, strategies, zone_engine, security flags, paths |
| POST | `/api/system/symbol` | `{symbol}` สลับ symbol ที่ dashboard ติดตาม |
| GET | `/api/system/audit?limit=` | audit trail (ใครทำอะไร) |
| GET | `/api/system/alerts?limit=` | alert ล่าสุด |
| GET | `/api/system/errors` | error buffer ของ runtime |
| GET | `/api/system/notify` | สถานะช่องทางแจ้งเตือน (`inapp`/`telegram`/`line`/`webhook`), error ล่าสุด, จำนวนครั้งที่พลาด (ไม่คืน token) |
| POST | `/api/system/alerts/test` | ส่งข้อความทดสอบจริงผ่านทุกช่องทางที่เปิดใช้ → `{ok, deliveries:[{channel, ok, status, error}]}` · ถ้ายังไม่ตั้งค่า จะคืน `ok:false` + `reason` แทนการเงียบ |

## Market & analysis

| Method | Path | Notes |
|---|---|---|
| GET | `/api/market/candles?symbol=&timeframe=&limit=` | `limit ≥ 20` |
| GET | `/api/market/ticker?symbol=` | last/bid/ask/spread |
| GET | `/api/market/specs?symbol=` | digits/point/tick/contract/lot step/stops level |
| GET | `/api/market/calculator?symbol=&points=&lot=` | points → profit (ไม่รวม spread/commission/swap/slippage) |
| GET | `/api/analysis/{symbol}` | snapshot เต็ม (trend, structure, zones, indicators, regime) |
| GET | `/api/analysis/{symbol}/zones` | supports/resistances พร้อม evidence |

## Forecast

| Method | Path | Notes |
|---|---|---|
| GET | `/api/forecast?symbol=` | active model + `models[]` ที่ฝึกไว้ |
| POST | `/api/forecast/train` | เริ่มฝึกเบื้องหลัง (progress ผ่าน live payload `training`) |
| POST | `/api/forecast/models/{version}/approve` | อนุมัติเฉพาะเมื่อ metric ผ่าน (ไม่มีการ override) |

## Signals & trading

| Method | Path | Notes |
|---|---|---|
| GET | `/api/signals/latest?symbol=` | signal + gate + forecast บางส่วน |
| GET | `/api/signals/history?limit=` | ประวัติสัญญาณ |
| POST | `/api/signals/{id}/approve` \| `/reject` | semi-auto flow; approve รัน gate ใหม่ทุกครั้ง และปฏิเสธถ้า score ต่ำกว่า `scoring.min_score_to_execute` (ปกติ 70) — ปุ่มนี้ไม่ใช่ override |
| GET | `/api/trading/live` | **payload เดียวกับ WebSocket** (polling fallback) |
| GET | `/api/trading/state` | account/positions/risk/mode/reconcile/broker |
| POST | `/api/trading/order` | `{symbol,direction}` manual; ผ่าน gate เท่านั้น |
| POST | `/api/trading/close` \| `/close-all` | ปิดไม้ |
| POST | `/api/trading/mode` | `manual` \| `semi_auto` \| `full_auto` |
| GET | `/api/trading/trades?limit=` | ไม้ที่ปิดแล้ว |
| GET | `/api/trading/journal?limit=` | journal entries (worked/failed/lesson/tags) |
| GET | `/api/trading/performance` | metrics + equity curve + by_exit_reason |
| GET | `/api/trading/daily` | สรุปรายวัน |

## Risk

| Method | Path | Notes |
|---|---|---|
| GET | `/api/risk/settings` | limits + targets + stops + full_auto requirements |
| PUT | `/api/risk/settings` | `{limits:{...}}` patch (audit ทุกครั้ง) |
| POST | `/api/risk/kill-switch` \| `DELETE` | เปิด/ปิดด้วยมือ |
| GET | `/api/risk/calculator?symbol=&points=&lot=` | เหมือน market calculator |

## Brokers & backtest

| Method | Path | Notes |
|---|---|---|
| GET | `/api/brokers` | รายการ + active + health + account |
| POST | `/api/brokers/{id}/activate` | สลับโบรกเกอร์ |
| GET | `/api/brokers/{id}/symbols` | spec จริงต่อบัญชี (`source: broker|declared`) |
| GET | `/api/brokers/{id}/account` \| `/health` | account info / health probe |
| POST | `/api/backtests` | `{symbol,bars,spread_points?,commission_per_lot?,slippage_points,starting_balance,validate_walk_forward}` → `{job_id}` |
| GET | `/api/backtests/jobs/{job_id}` | `{state,pct,message,report_id,metrics}` |
| GET | `/api/backtests` \| `/api/backtests/{id}` | รายงาน + metrics/verdict/walk_forward/assumptions |

## Explanation

| Method | Path | Notes |
|---|---|---|
| POST | `/api/explain` | `{question,symbol}` → `{answer,bullets,citations,model_used,facts}`; ห้ามสั่งออร์เดอร์ |

## WebSocket

```
ws://<host>/ws/live?token=<jwt>      (alias: /ws)
```
frame ทุก 1 วินาที: `type:"snapshot"` (payload เต็ม) หรือ `type:"tick"` (เบา — ไม่มี `analysis`/`forecast`)
snapshot ถูกส่งครั้งแรกทันที และซ้ำทุก `ws.full_snapshot_seconds` (ค่าเริ่มต้น 5 วินาที) —
client ต้อง merge ไม่ใช่ replace ไม่งั้น panel analysis จะหายไป 1 วินาทีหลังโหลด

payload เต็ม:
`account, positions, risk_state, limits, signal, gate, analysis, forecast, model,
training, reconcile, alerts, errors, ticker, mode, feed, virtual_time`

ตัวเลขที่ dashboard อ่านตรง ๆ: `risk_state.daily_pnl_pct`, `limits.max_daily_loss_pct`,
`signal.plan.{entry,sl,tp1..3,sl_points,lot,reward_risk_net,partials[]}`,
`forecast.horizons[].{p_up,p_down,p_sideways,p10_price,p90_price,p_tp_before_sl}`,
`analysis.spec.{digits,point,contract_size,lot_step}`

---

# ฟิลด์ที่สำคัญ (สัญญาณ/ออเดอร์/backtest)

ส่วนนี้ระบุ *ความหมาย* ของฟิลด์ที่ตัวเลขบนจอขึ้นกับมัน ถ้าเปลี่ยนชื่อ/นิยามต้องอัปเดตที่นี่ด้วย

## `signal.plan` (ใน `/api/trading/live`, `/api/signals/latest`)

| ฟิลด์ | ความหมาย |
|---|---|
| `entry`, `sl`, `tp1..tp3` | ราคาที่ snap ตาม `tick_size` แล้ว |
| `sl_points` | ระยะ stop เป็น points (≥ vol floor ≥ `stops_level`) |
| `lot` | ปัดลงตาม `lot_step` และไม่ทำให้เสี่ยงเกิน budget |
| `risk_amount` | เงินที่เสี่ยงจริง = `lot × sl_points × value_per_point_per_lot` |
| `partials[]` | `{close_pct, volume, price}` — `volume` รวมกันได้เท่า `lot` เสมอ |
| `reward_risk` / `reward_risk_net` | ก่อน/หลังต้นทุน; `net` ต้อง < `gross` |
| `net_rr_tp1` | R:R ของ TP1 หลังต้นทุน ต้อง ≥ 1.0 |
| `breakeven_probability` | `(sl + cost) / (sl + tp1)` |
| `expected_value` | `p×profit(tp1−cost) − (1−p)×loss(sl+cost)` |
| `notes`, `blockers` | เหตุผลที่ขยับ stop/TP หรือเหตุผลที่ไม่มีแผน |

## `POST /api/trading/order` → `{ok, order, risk_check}`

`risk_check` ถูกคำนวณทุกครั้งที่ fill:

| ฟิลด์ | ความหมาย |
|---|---|
| `planned_risk` / `actual_risk` | เงินเสี่ยงตามแผน / ตามราคา fill จริง |
| `planned_sl_points` / `actual_sl_points` | ระยะ stop ที่วางไว้ / ที่เหลือจริงหลัง fill |
| `drift_pct` | ผลต่างเป็น % (บวก = เสี่ยงมากขึ้น) |
| `geometry_broken` | `true` เมื่อระยะ stop จริงเหลือ < 50 % ของแผน (fill กระโดดไปชิด stop) |
| `ok` | `actual_risk ≤ planned×1.25` **และ** ไม่ geometry broken |

- `ok=false` → audit `risk.fill_drift` + notification (Thai) ให้ผู้ใช้ตัดสินใจ
- คำสั่งซื้อขายถูกส่ง **ครั้งเดียว** ไม่มีการส่งซ้ำอัตโนมัติ; ถ้า error ระบบถามโบรกเกอร์ก่อนแล้วค่อย reject
- `POST /api/trading/close` และ `/close-all` คืน `{ok, trade}` (paper) หรือ `{ok, order}` (MT5) — ตรวจ `ok` ก่อนใช้

## `forecast`

| ฟิลด์ | ความหมาย |
|---|---|
| `horizons[].p_up/p_down/p_sideways` | รวม = 1 (±0.0015) |
| `horizons[].p10_price ≤ p50_price ≤ p90_price` | ต้องเรียงถูกเสมอ |
| `horizons[].p_tp_before_sl` | ความน่าจะเป็นเชิงประจักษ์ (ดูวิธีคิดใน MATH.md §6) |
| `scenarios[]` | `bull/base/bear` — `path[].p50` จบที่ `target_price` ของตัวเอง, `path[].p10 ≤ p50 ≤ p90` |
| `volatility_points` | ATR × √(horizon/5) ÷ point |
| `coverage_note` | ข้อจำกัดของแบบจำลอง horizon นั้น (อ่านก่อนเชื่อ) |

## `metrics` ของ backtest

`trades, net_profit, profit_factor (cap 99), expectancy, expectancy_r, win_rate,
directional_accuracy, tp_before_sl_rate, no_trade_rate, max_drawdown_pct, sharpe,
sortino, recovery_factor, total_costs, avg_hold_minutes, max_consecutive_losses`

- `total_costs` = ค่าคอมมิชชัน + spread/slippage ที่ฝังในราคา fill → `gross_pnl − pnl = costs`
- `expectancy_r` ใช้ risk ที่วัดตอน fill จริง ไม่ใช่ risk ตามแผน
- `assumptions[]` ต้องอ่านคู่กับตัวเลขเสมอ (มีทั้งสมมติฐานราคาและจำนวนสัญญาณที่ถูกข้าม)
