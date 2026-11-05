# API — what the dashboard relies on

Base: `http://127.0.0.1:8000` · interactive docs: `/api/docs` · OpenAPI: `/api/openapi.json`
ทุก endpoint ใต้ `/api/` (ยกเว้น login/health) ต้องมี `Authorization: Bearer <jwt>`

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
| POST | `/api/signals/{id}/approve` \| `/reject` | semi-auto flow |
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
frame ทุก 1 วินาที = `live_payload` + `type:"snapshot"`:
`account, positions, risk_state, limits, signal, gate, analysis, forecast, model,
training, reconcile, alerts, errors, ticker, mode, feed, virtual_time`

ตัวเลขที่ dashboard อ่านตรง ๆ: `risk_state.daily_pnl_pct`, `limits.max_daily_loss_pct`,
`signal.plan.{entry,sl,tp1..3,sl_points,lot,reward_risk_net,partials[]}`,
`forecast.horizons[].{p_up,p_down,p_sideways,p10_price,p90_price,p_tp_before_sl}`,
`analysis.spec.{digits,point,contract_size,lot_step}`
