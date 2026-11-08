# API — what the dashboard relies on

Base: `http://127.0.0.1:8000` · interactive docs: `/api/docs` · OpenAPI: `/api/openapi.json`
ทุก endpoint ใต้ `/api/` (ยกเว้น login/health) ต้องมี `Authorization: Bearer <jwt>`

## EA bridge (MQL5 Expert Advisor)

เซิร์ฟเวอร์ไม่เคยถือรหัส MT5 และไม่ต่อเข้า terminal — **EA ในเทอร์มินัลเป็นฝ่าย poll ออกมา**
(โปรโตคอลเดียวกับ `bridge/No7BridgeEA.mq5` และ `scripts/run_bridge_sim.py`)

| method | path | auth | หมายเหตุ |
|---|---|---|---|
| POST | `/api/bridge/register` | `Authorization: Bearer <bridge token>` | `{account_id, session_id?, terminal, symbols}` → `{session_id, generation, poll_interval_ms, fresh_seconds, stale_seconds}` · session ใหม่ (EA รีสตาร์ท) = ทิ้งคิว+snapshot เก่า (`generation` +1) |
| POST | `/api/bridge/poll` | session id ในบอดี้ | `{session_id, snapshot, results:[{id, ok, status, ticket, …}]}` → `{commands, results, expired_unacked, health}` · 409 = session ตายแล้ว ให้ register ใหม่ |
| GET | `/api/bridge/status` | admin JWT | session/health/queue/polls/duplicates/expiries + `orphaned_commands` (คำสั่งที่ EA ไม่ตอบก่อนรีสตาร์ท) + `store` (`sqlite` = แชร์ข้าม worker, `memory` = โปรเซสเดียว) + `tokens` เป็น sha256 8 ตัวแรกเท่านั้น |
| POST | `/api/bridge/cancel` | admin JWT | ทิ้งทุกคำสั่งที่ยังไม่ถูกส่ง (`pending`) — kill switch ฝั่งคิว |
| GET | `/api/bridge/session` | ทุก role | มุมมองแดชบอร์ด: มี EA ต่ออยู่ไหม, snapshot อายุเท่าไร |

**กติกาที่บังคับใช้ (ไม่ใช่แค่เอกสาร)**
- คำสั่งหนึ่งถูกส่งให้ EA **ครั้งเดียว**: `pending → delivered → acked` ; ถ้าไม่ ack ภายใน `ack_grace_seconds`
  จะกลายเป็น `expired` และ **ไม่ถูกส่งซ้ำ** (เพราะคำสั่งที่ยังไม่ตอบอาจไปถึงโบรกเกอร์แล้ว) — EA เห็น id ใน `expired_unacked`
- `results` ที่ซ้ำ → ตอบ `duplicate: true` ไม่ apply ซ้ำ; id ที่ไม่รู้จัก → `accepted: false` พร้อมเหตุผล (ไม่กลืนหาย)
- `enqueue` ถูกปฏิเสธถ้า session ไม่ fresh (`fresh_seconds`) หรือคิวเต็ม (`max_pending`) หรือยังไม่มี EA
- snapshot เก่ากว่า `stale_seconds` → adapter **raise** (`account_info/positions/ticker/candles`) ไม่คืนค่าเก่า
- state อยู่ในตาราง `bridge_sessions`/`bridge_commands` → หลาย worker เห็นคิวเดียวกัน และ claim แบบ atomic
  (คำสั่งเดียวถูกส่งให้ EA ครั้งเดียวแม้สอง worker ตอบพร้อมกัน)
- EA แจ้ง `rates` เอง; ถ้าไม่มี rates → `candles()` error ไม่ synthesize

## PWA (manifest / service worker / offline)

| path | หมายเหตุ |
|------|----------|
| `GET /manifest.webmanifest` | `application/manifest+json` — name/short_name/start_url/icons (192, 512, maskable) |
| `GET /sw.js` | service worker; ฝั่งเซิร์ฟเวอร์แทน `__NO7_VERSION__` ด้วย sha256 ของ `dist/index.html` (12 ตัวแรก) และส่ง `Cache-Control: no-cache` + `Service-Worker-Allowed: /` |
| `GET /offline.html` | หน้า fallback ตอนเนvigate ไม่ได้ |

service worker **ไม่แคช** `/api/*` และ `/ws` (ราคา/คำสั่งต้องสดเสมอ) — แคชเฉพาะ shell: `/`, `/index.html`,
`/assets/*` (hashed), ไอคอน, manifest, `/offline.html`

## Rate limits

ตัวนับ rate limit อยู่ที่ `ratelimit.store` — `memory` (ต่อโปรเซส), `sqlite` (ต่อเครื่อง),
`redis` (ข้ามเครื่อง) และทุก response ที่ถูกจำกัดจะแนบ `x-ratelimit-remaining`

ถ้า store ที่ใช้ร่วมกันล่มกลางทาง คำขอจะถูกจำกัดด้วย bucket ในโปรเซสแทน และผลลัพธ์จะบอกตรง ๆ:
`x-ratelimit-degraded: redis` แนบมาทั้งกับ **200** และ **429** (รอบ 24 แก้บั๊กที่ 429 ไม่ส่ง header นี้
— ผู้เรียกจึงเคยแยกไม่ออกว่าโดนปฏิเสธด้วยโควตารวมหรือโควตาสำรอง) ฝั่งผู้ดูแลดูได้ที่
`/api/system/health → ratelimit`: `degraded` คือจำนวนครั้งที่ต้องถอย, `last_error` คือสาเหตุล่าสุด
และ `shared` จะเป็น `false` ตลอดช่วงที่ยังถอยอยู่ แทนที่จะยังเขียวว่าแชร์โควตากันอยู่

CORS เป็น **allowlist**: ค่าเริ่มต้นไม่ให้ origin อื่นเลย (dashboard เสิร์ฟจาก origin เดียวกัน
และ Vite dev proxy `/api` ให้อยู่แล้ว) — เปิดเฉพาะที่ตั้งใจด้วย
`NO7_CORS_ORIGINS=https://dash.example.com`; `*` ใช้ได้แต่ `/api/system/health` จะรายงาน
`cors.wildcard: true` ให้เห็น

ทุก response มี security headers (CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`,
`Permissions-Policy`) และมี HSTS เฉพาะเมื่อคำขอมาทาง HTTPS จริง — ดู RUNBOOK §13

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

## สิทธิ์ (roles)

สามระดับ เรียงตามลำดับ: **admin > trader > viewer**

| role | ทำอะไรได้ |
|---|---|
| `viewer` | ทุก GET — POST/PUT/PATCH/DELETE ทุกเส้นทาง (ยกเว้น `/api/auth/login`) ได้ **403** |
| `trader` | ทุกอย่างของผู้ใช้จริง: ออเดอร์, ปิดไม้, kill switch, เทรน, backtest, dataset, สลับ symbol |
| `admin` | เพิ่มจาก trader: จัดการผู้ใช้ (`/api/users`) และเปลี่ยน security posture |

กติกาที่บังคับในโค้ด:

- **สิทธิ์มาจากฐานข้อมูล ไม่ใช่ token** — token บอกว่าเป็นใคร; `users.role` บอกว่าทำอะไรได้
  → ปิดบัญชีหรือลด role มีผลกับ request ถัดไปทันที (ไม่ต้องรอ token หมดอายุ)
- role ที่ไม่รู้จัก/ว่างเปล่า → **viewer** (fail closed) · `owner` (ของเดิม) → `admin`
- ปิด/ลด role/ลบ **admin ที่ยังใช้งานคนสุดท้าย** ไม่ได้ (กัน lockout)
- ทุกการเปลี่ยนผู้ใช้ถูกบันทึกใน audit (`users.create`, `users.update`, `users.delete`)

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
| GET | `/api/users` · `POST /api/users` · `PATCH /api/users/{email}` · `DELETE /api/users/{email}` | จัดการผู้ใช้ (**admin เท่านั้น**) |
| GET | `/api/users/me/permissions` | `{role, can_trade, can_manage_users, roles}` — UI ใช้ปิดปุ่ม |
| GET | `/api/system/health` → `cluster` | `{role: leader\|replica\|blocked\|solo, backend, requested, reason, shared_health}` + `runtime_lease` |
| GET | `/api/system/notify` | สถานะช่องทาง (`configured/ok/failures/skipped/base`), `state`, `retry_attempts`, `retries`, `dropped`, `min_interval_seconds`, `base_warnings` (ไม่คืน token — ถูกแทนด้วย `***`) |
| POST | `/api/system/alerts/test` | ส่งข้อความทดสอบจริงผ่านทุกช่องทางที่เปิดใช้ → `{ok, deliveries:[{channel, ok, status, error, attempts}], paced:[…], note}` · `ok:null` = ถูกเลื่อนเพราะ pacing (ไม่ใช่ล้มเหลว) · ถ้ายังไม่ตั้งค่า จะคืน `ok:false` + `reason` แทนการเงียบ |
| GET | `/api/system/health` → `ratelimit` | `{store: memory\|sqlite\|redis, requested, shared, reason, path?, warning?}` — `shared:false` = โควตาคูณตามจำนวน worker |
| GET | `/api/system/health` → `security` | `{require_auth, jwt_secret_from_env, cors:{origins, wildcard, cross_origin_allowed}, trusted_proxies, csp_mode, hsts_when_https}` — perimeter ที่ใช้งานจริง (ไม่มีความลับ) |

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
| POST | `/api/backtests` | `{symbol,bars,spread_points?,commission_per_lot?,slippage_points,starting_balance,validate_walk_forward,snapshot_id?}` → `{job_id}` · `bars` ต้อง ≥ 1700 (ไม่งั้น 400 พร้อมบอกขั้นต่ำ) · ใส่ `snapshot_id` เพื่อรันซ้ำบนแท่งเทียนชุดเดิม (ตรวจ sha256 ก่อน, ผิด→400) · `use_ticks` (ค่าเริ่มต้น `true`) = ใช้ tick ที่ import ไว้ตัดสินลำดับเหตุการณ์ในแท่ง ที่ชนทั้ง SL และ TP; ถ้าไม่มี tick จะใช้สมมติฐานเดิม (SL ก่อน) และรายงานบอกว่าใช้อย่างไหนกี่แท่ง |
| GET | `/api/datasets` \| `POST /api/datasets` \| `GET /api/datasets/{id}` | snapshot ของแท่งเทียน: list / freeze ข้อมูลปัจจุบัน / manifest + ตรวจ hash |
| GET | `/api/datasets/ticks/status?symbol=` | ข้อมูล tick ที่ import ไว้: จำนวนแถว, ช่วงเวลา, แถวที่ถูกทิ้งเพราะอะไร, และ flag `reconstruction` ถ้าเป็นข้อมูลจำลอง |
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

## `dataset` ของ backtest (provenance)

```json
{
  "id": "DS-1A2B3C4D5E", "symbol": "XAUUSD", "timeframe": "M1",
  "rows": 6000, "first_t": 1793000000, "last_t": 1793360000,
  "sha256": "…", "source": "simulated GBM feed (seed 7)",
  "path": "storage/datasets/snapshots/DS-….csv.gz", "bytes": 812345,
  "feed_mode": "simulate", "reproducible": true,
  "reproduce_with": {"snapshot_id": "DS-1A2B3C4D5E"}
}
```

`assumptions` มีบรรทัด `Bar data: …` ที่ตรงกับแหล่งข้อมูลจริง (simulated / replay / MT5)
— ไม่ใช่ข้อความตายตัวว่า "simulated" อีกต่อไป

## tick (ข้อมูลจริงราย tick)

```bash
.venv/bin/python scripts/import_ticks.py --csv ~/Downloads/XAUUSD_ticks.csv --symbol XAUUSD   # time,bid,ask
.venv/bin/python scripts/import_ticks.py --csv ticks.csv --symbol XAUUSD --tz Etc/GMT-3       # ไฟล์ไม่มี tz
.venv/bin/python scripts/import_ticks.py --csv big.csv --symbol XAUUSD --chunk-rows 100000    # stream
.venv/bin/python scripts/import_ticks.py --csv old.csv --symbol XAUUSD --single-file          # layout เดิม
```
เก็บเป็น **หนึ่งไฟล์ต่อหนึ่งวัน UTC**: `storage/datasets/ticks/XAUUSD/2026-11-05.parquet`
(ถ้าไม่มี pyarrow → `.csv.gz`) พร้อม `ticks/XAUUSD/manifest.json` (rows/first_t/last_t/sha256
ต่อวัน, จำนวนแถวที่ใช้/ที่ทิ้ง, median spread) — backtest อ่านเฉพาะวันทีหน้าต่างแท่งทับ
ไม่โหลดทั้งก้อน; layout ไฟล์เดียวแบบเดิมยังเปิดได้ (auto-detect)

### `GET /api/datasets/ticks/status`

ทุก role อ่านได้ ตอบจาก manifest โดยไม่เปิดไฟล์ข้อมูลเลย (`rows_loaded: 0`):

```json
{"used_for_intra_bar_ordering": true,
 "ticks": [{"symbol": "XAUUSD", "available": true, "layout": "daily", "format": "parquet",
            "rows": 1008000, "days_covered": 12,
            "first_iso": "2026-10-05T00:00:00+00:00", "last_iso": "2026-10-16T23:19:59+00:00",
            "gaps": [],
            "days": [{"day": "2026-10-05", "rows": 84000, "first_t": 1791158400,
                      "last_t": 1791242399, "format": "parquet", "bytes": 769760}],
            "source": "/home/me/XAUUSD_ticks.csv", "dropped": {"ask below bid": 3}}]}
```

`gaps` = วันที่หายไปตรงกลางช่วง (มีไฟล์วันแรกกับวันสุดท้าย แต่ขาดวันระหว่าง) — ถ้าไม่ว่าง
แปลว่า backtest ที่ทับช่วงนั้นจะยังใช้สมมติฐาน SL-ก่อนในแท่งที่ขาด และนับใน `bars_without_ticks`

### `POST /api/datasets/ticks/prune?symbol=XAUUSD&keep_days=60[&force=true]` (admin)

ลบไฟล์วันเก่า เหลือ `keep_days` วันล่าสุด + เขียน audit `datasets.ticks_prune`
**ค่าเริ่มต้นปฏิเสธ (409)** ถ้ามี backtest ที่บันทึกไว้อ้างวันเหล่านั้นอยู่
(`dataset.ticks.days_used`) เพราะ report นั้นจะ reproduce ไม่ได้อีก — `force=true` เท่านั้นที่ลบได้

ใน report:
```json
"diagnostics": {"intra_bar": {"layout": "daily", "days": 18, "days_in_window": 5,
                              "ticks_in_window": 13242, "days_used": ["2026-11-05"],
                              "days_loaded": 1, "rows": 1024000, "rows_in_window": 480,
                              "bars_settled_by_ticks": 3, "bars_without_ticks": 1, ...}},
"assumptions": ["Intra-bar order: 3 ambiguous bars were settled by walking 24000 real ticks in time order; 1 bars had no ticks ..."]
```
ความหมายของตัวเลขใน `intra_bar` (แยกให้ชัด เพราะมันต่างกันจริง):
- `ticks_in_window` = tick ที่ **มีอยู่** ในหน้าต่างที่รัน (ตอบจาก manifest ไม่ได้อ่านไฟล์) —
  ใช้ตอบคำถาม "ทำไม tick ไม่ช่วยอะไรเลย": ถ้าเป็น 0 แปลว่าไม่มีข้อมูลครอบช่วงนี้จริง ๆ
- `days_in_window` / `days_used` / `days_loaded` = วันที่ทับหน้าต่าง / วันที่ถูกอ่านจริง /
  จำนวนไฟล์ที่เปิด — งานที่ไม่มีแท่งกำกวมจะอ่าน 0 ไฟล์แม้มี tick ครบ
- `rows_in_window` = จำนวน tick ที่เดินจริงเพื่อตัดสินแท่ง (0 ถ้าไม่มีแท่งกำกวม)

`_manage_bar` เดิมเดาว่า "แท่งที่ชนทั้ง SL และ TP → SL ก่อน" ซึ่งเปลี่ยนไม้ชนะเป็นไม้แพ้ได้;
เมื่อมี tick ระบบเดินราคาตามเวลาจริงในแท่งนั้น (long ออกที่ bid, short ออกที่ ask) แล้วจึงตัดสิน —
ถ้า tick ไม่ครอบคลุมแท่งนั้น จะกลับไปใช้สมมติฐานเดิม **และนับไว้** ไม่ใช่เงียบ ๆ

## `metrics` ของ backtest

`trades, net_profit, profit_factor (cap 99), expectancy, expectancy_r, win_rate,
directional_accuracy, tp_before_sl_rate, no_trade_rate, max_drawdown_pct, sharpe,
sortino, recovery_factor, total_costs, avg_hold_minutes, max_consecutive_losses`

- `total_costs` = ค่าคอมมิชชัน + spread/slippage ที่ฝังในราคา fill → `gross_pnl − pnl = costs`
- `expectancy_r` ใช้ risk ที่วัดตอน fill จริง ไม่ใช่ risk ตามแผน
- `assumptions[]` ต้องอ่านคู่กับตัวเลขเสมอ (มีทั้งสมมติฐานราคาและจำนวนสัญญาณที่ถูกข้าม)
