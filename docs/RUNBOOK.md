# Runbook — ตั้งค่าและดูแลระบบ

> **Safety baseline:** อ่าน [`BASELINE-P1.th.md`](BASELINE-P1.th.md) และ
> [`SAFETY-HANDOFF.th.md`](SAFETY-HANDOFF.th.md) ก่อนดำเนินการ ขั้นตอนเปิด terminal/Algo Trading,
> เชื่อม MT5/Redis, restart หรือ deploy ใน runbook เป็นคำแนะนำสำหรับการอนุมัติแยก
> ไม่ใช่สิทธิ์จากการผ่าน local QA; งานเฟส 1 ไม่ได้ทำขั้นตอนเหล่านั้น
> Local Windows QA ที่ไม่เริ่ม service ใช้ [`LOCAL-VERIFICATION.th.md`](LOCAL-VERIFICATION.th.md)

## 1. Linux / macOS (โหมด demo, ไม่ต้องมี MT5)

```bash
cp .env.example .env          # ตั้ง NO7_JWT_SECRET อย่างน้อย 32 ตัวอักษร
python3 -c "import secrets;print('NO7_JWT_SECRET='+secrets.token_urlsafe(48))" >> .env

python3 -m pip install fastapi uvicorn pydantic numpy pandas scikit-learn lightgbm PyJWT joblib pyyaml pytest httpx

cd apps/web-dashboard && npm install && npm run build && cd ../..
python3 -m uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8000
```

เข้า `http://127.0.0.1:8000` → `demo@no7.ai` / `no7demo1234`
(เปลี่ยนได้ผ่าน `NO7_DEMO_USER` / `NO7_DEMO_PASSWORD`)

## 2. Windows + MT5 ( Demo ก่อนเสมอ )

1. ติดตั้ง MetaTrader 5 และล็อกอินบัญชี **Demo** ของ Connext
2. เปิด *Tools → Options → Expert Advisors* → อนุญาต algorithmic trading
3. `pip install MetaTrader5` (ใช้ได้เฉพาะ Windows)
4. ตั้งใน `.env`:
   ```
   NO7_FEED_MODE=mt5
   MT5_LOGIN=...
   MT5_PASSWORD=...
   MT5_SERVER=Connext-Demo
   MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
   ```
5. รัน `python -m uvicorn services.api_gateway.app:app --host 127.0.0.1 --port 8000`
   (ผูกที่ `127.0.0.1` เพื่อไม่ให้ endpoint ส่งคำสั่งเข้าถึงจากอินเทอร์เน็ต)
6. ตรวจ `GET /api/brokers` → `health: connected` และ `GET /api/brokers/{id}/symbols`
   ต้องได้ `source: broker` (อ่าน spec จากเทอร์มินัลจริง)

> ถ้า symbol ในโบรกเกอร์ชื่อ `XAUUSDm` หรือ `GOLD` ให้ตั้ง mapping ใน `config/brokers.yaml`
> (`symbol_map: {XAUUSD: XAUUSDm}`) — ระบบอ่าน Digits/Point/TickSize/ContractSize/StopsLevel จากโบรกเกอร์เสมอ

## 3. คำสั่งที่ใช้บ่อย

> จะ **แก้โค้ด** ไม่ใช่แค่ดูแลระบบ: `./scripts/dev_setup.sh` ติดตั้งทุกอย่างให้ในคำสั่งเดียว
> และ [`DEVELOPMENT.md`](DEVELOPMENT.md) อธิบายแผนที่โค้ด/เกต/งานถัดไป

```bash
# ติดตั้งหรือกู้สภาพแวดล้อมพัฒนา (venv + deps + .env + dashboard bundle)
./scripts/dev_setup.sh

# เกตก่อน commit: ruff + ตรวจ bundle + pytest ทั้งชุด
./scripts/dev_check.sh

# rebuild dashboard หลังแก้ frontend
cd apps/web-dashboard && npm run build

# dev server (proxy /api และ /ws ไป backend)
cd apps/web-dashboard && NO7_BACKEND=http://127.0.0.1:8000 npm run dev   # :5173

# tests (fakeredis/ruff/pyarrow อยู่ใน requirements-dev.txt; ไม่ลงก็แค่ skip)
python3 -m pip install -r requirements-dev.txt
./scripts/test.sh                 # = pytest tests/ -q แต่เลือกล่ามจาก .venv ให้เอง
./scripts/dev_check.sh            # เกตเต็ม (เหมือนที่ CI รันทุก PR)

# ดู report ย้อนหลังใน DB
sqlite3 storage/db/no7.sqlite3 "SELECT id,symbol,json_extract(payload,'$.metrics.trades') FROM backtests ORDER BY created_at DESC LIMIT 5;"

# ข้อมูลจริง: นำเข้า CSV จาก MT5 แล้วประเมิน (ดู docs/DATA.md)
.venv/bin/python scripts/import_candles.py --csv ~/Downloads/XAUUSD_M1.csv --symbol XAUUSD --tz Etc/GMT-3
.venv/bin/python scripts/evaluate_dataset.py --symbol XAUUSD

# freeze แท่งเทียนที่ใช้อยู่ และดู snapshot ทั้งหมด (ใช้กับ backtest ซ้ำได้)
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
     -d '{"symbol":"XAUUSD","bars":6000}' http://127.0.0.1:8000/api/datasets
curl -s -H "Authorization: Bearer $TOK" http://127.0.0.1:8000/api/datasets | python3 -m json.tool

# รัน backtest ซ้ำบนข้อมูลชุดเดิม (ผลต้องเท่าเดิมทุกหลัก)
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
     -d '{"symbol":"XAUUSD","snapshot_id":"DS-XXXXXXXXXX"}' http://127.0.0.1:8000/api/backtests

# ให้ dashboard ทั้งระบบเดินบนข้อมูลที่นำเข้า (แล้วคืนค่ากลับเป็น simulate)
NO7_FEED_MODE=replay .venv/bin/python -m uvicorn services.api_gateway.app:app --port 8000
```

> `NO7_FEED_MODE=replay` ต้องมีไฟล์ของทุก symbol ที่ broker ที่ใช้งานเทรด
> (`storage/datasets/XAUUSD_M1.csv` ฯลฯ) และ `market_data.replay.warmup_bars` ต้องพอ
> (ค่าเริ่มต้น 6,000 แท่ง) — ถ้าไม่ครบ ระบบจะถอยไปใช้ feed จำลองและบอกเหตุผลใน
> `/api/system/health` → `feed_note`

## 4. เก็บกวาด / รีเซ็ต

| ต้องทำ | คำสั่ง |
|---|---|
| รีเซ็ตบัญชี paper + ประวัติ | หยุด server แล้ว `rm storage/db/no7.sqlite3` (boot จะสร้างใหม่ + demo user) |
| ลบโมเดลที่ทดลอง | `rm -rf storage/models/*` (ระบบกลับไปใช้ค่าฐานสถิติ) |
| รีเซ็ต UI | ลบ `localStorage` ของเบราว์เซอร์ (key `no7.*`, `no7.token`) |

## 5. แก้ปัญหา

| อาการ | สาเหตุ/วิธีแก้ |
|---|---|
| เปิด `/` แล้วเห็นหน้า "API is running" | ยังไม่ `npm run build` (หรือ `dist` ถูกลบ) |
| ล็อกอินแล้วเด้งกลับ /login | token หมดอายุ (`NO7_JWT_TTL_MINUTES`) หรือ `NO7_JWT_SECRET` เปลี่ยนตอนรีสตาร์ต → ล็อกอินใหม่ |
| Dashboard ว่าง/ไม่อัปเดต | WebSocket ถูก proxy บล็อก → ระบบจะ fallback polling ทุก 5s เอง; ตรวจ `/api/trading/live` |
| ป้าย feed ขึ้น "SIMULATED FEED" ทั้งที่ตั้ง replay | replay เริ่มไม่ครบ (ขาดไฟล์/ข้อมูลน้อยกว่า warm-up) → ดู `feed_note` ใน `/api/system/health` |
| ป้าย `snapshot` หายไปจากหน้า backtest | รายงานเก่าก่อนมี snapshot (ไม่มี `dataset` ใน payload) — รันใหม่หนึ่งครั้งเพื่อให้มี provenance |
| `400 bars=… is too few` | engine ต้องการ ≥1700 แท่ง M1 เพื่อ warm up 320 แท่ง M5 — เพิ่ม `bars` หรือใช้ `snapshot_id` |
| `snapshot … is corrupted` | ไฟล์ใน `storage/datasets/snapshots/` ถูกแก้/แทน — ลบ manifest+ไฟล์คู่นั้นแล้วรันใหม่ (อย่าแก้ให้ตรง) |
| `services.feed = "exhausted"` | ข้อมูล replay เดินจนจบไฟล์แล้ว (clock หยุด, ไม่มีออเดอร์ใหม่) → นำเข้าไฟล์ที่ยาวขึ้นหรือเปิด `replay.loop` |
| โมเดลขึ้น "approval expired" | approval ถูกให้ด้วยกฎเวอร์ชันเก่า → กดเทรนใหม่ (`POST /api/forecast/train`) เพื่อประเมินด้วยกฎปัจจุบัน |
| `401` ทุก endpoint | ไม่ได้ส่ง `Authorization: Bearer` หรือ `security.require_auth` เปิดอยู่แต่ไม่มี token |
| สั่งออร์เดอร์แล้วได้ 400 | เป็นพฤติกรรมที่ถูกต้อง — ดู `detail.blockers` เช่น news lockout/spread/เพดานไม้ |
| `spread ... exceeds max` | ตลาดผันผวนหรือโบรกเกอร์ widen; เพิ่ม `max_spread_points` เฉพาะเมื่อเข้าใจความเสี่ยง |
| Full Auto กดไม่ได้ | ต้อง `NO7_ALLOW_FULL_AUTO=true` + toggle ในหน้า Risk + โมเดล approved + บัญชี demo |
| โมเดลขึ้น `UNVALIDATED` | metric ไม่ผ่านเกณฑ์ OOS — อย่า override, ปล่อยให้ใช้ค่าฐานสถิติ |
| `/api/market/candles` ตอบ 422 | `limit < 20` (ข้อจำกัดของ endpoint) |
| PyJWT เตือน key สั้น | ตั้ง `NO7_JWT_SECRET` ≥ 32 ตัวอักษร |

## 6. แจ้งเตือนออกนอกเครื่อง (Telegram / LINE / webhook)

in-app เปิดเสมอ ไม่ต้องตั้งค่า · ช่องทางภายนอก **ปิดเป็นค่าเริ่มต้น** และต้องมีทั้ง token และการเปิดใช้:

```bash
# Telegram
export TELEGRAM_BOT_TOKEN='123456:AA...'      # จาก @BotFather
export NO7_TELEGRAM_CHAT_ID='-1001234567890'  # chat/group id
export NO7_TELEGRAM_ENABLED=1
# LINE (Messaging API)
export LINE_CHANNEL_TOKEN='...'               # channel access token
export NO7_LINE_TARGET_ID='U1234...'          # userId/groupId
export NO7_LINE_ENABLED=1
# webhook ทั่วไป (ได้ JSON {title, message, source})
export NO7_WEBHOOK_URL='https://example.com/hook'
export NO7_WEBHOOK_ENABLED=1
```

ตรวจว่าส่งได้จริงโดยไม่ต้องรอเหตุการณ์จริง: หน้า **/system → ช่องทางแจ้งเตือน → ส่งข้อความทดสอบ**
หรือ `POST /api/system/alerts/test` (ต้อง login) · ผลลัพธ์บอกทีละช่องทาง
ถ้าล้มเหลวจะเห็น `failing` + ข้อความ error บนหน้า /system และใน `/api/system/health` → `services.notify`

> ถ้าตั้ง token แล้วแต่ยังไม่เปิดใช้ ระบบจะ **ไม่ส่ง** อะไรออกนอกเครื่อง (โดยเจตนา)
> และจะบอกว่ายังไม่ได้ตั้งค่า ไม่ใช่เงียบ

## 7. หลาย worker / replica (ต้องมี Redis)

ค่าเริ่มต้นคือโปรเซสเดียว (`cluster.backend: local`) — เฟรมสดอยู่แต่ในโปรเซสนั้น

ถ้าต้องการให้มี API หลายโปรเซสหรือหลายเครื่อง โดยที่ **ยังมีคนเทรดคนเดียว**:

```bash
docker run -d -p 6379:6379 redis:7-alpine
export NO7_CLUSTER_BACKEND=redis
export NO7_REDIS_URL=redis://127.0.0.1:6379/0
# แล้วรัน API ได้หลายโปรเซส
.venv/bin/python -m uvicorn services.api_gateway.app:app --host 0.0.0.0 --port 8000 --workers 4
```

- โปรเซสที่ถือ **lease** = `leader` → เทรด และ `SET no7:live:v1 <frame> EX 10` ทุกวินาที
- โปรเซสอื่น = `replica` → ไม่ tick/ไม่เทรด/ไม่เทรน แต่ `/api/trading/live` และ `/ws/live`
  เสิร์ฟเฟรมของ leader (payload มี `replica: true`, `served_by`, `frame_age_seconds`)
- ดูสถานะที่ `/api/system/health` → `cluster: {role, backend, requested, reason, shared_health}`
  และแถว `cluster` บนหน้า /system

**Hot standby (ค่าเริ่มต้นเปิด):** โปรเซสที่ไม่ได้ lease จะไม่ตายทิ้ง — มันเฝ้าทุก
`standby_poll_seconds` (5s) และถ้า heartbeat ของ leader เงียบเกิน 30s จะยึด lease (compare-and-set,
ผู้ชนะคนเดียว) แล้วเริ่มเทรดเอง บันทึกไว้ใน error log ว่า `promoted to leader …`
ปิดได้ด้วย `NO7_HOT_STANDBY=false` ถ้าต้องการให้ต้องรีสตาร์ตมือ

```bash
# ตัวอย่าง: สองโปรเซส, ตัวที่สองเป็น standby
.venv/bin/python -m uvicorn services.api_gateway.app:app --port 8000 &
.venv/bin/python -m uvicorn services.api_gateway.app:app --port 8001 &   # role: blocked + standby
# ปิดตัวแรก → อีก ~5 วินาที ตัวที่สองกลายเป็น leader เอง
```

ถ้าตั้ง `backend: redis` แต่ยังใช้ไม่ได้ (ไม่มี URL / ไม่ได้ `pip install redis` / ต่อเซิร์ฟเวอร์ไม่ได้)
ระบบจะ **ถอยไปใช้ in-process store** และบอกเหตุผลใน `cluster.reason` — replica จะไม่มีอะไรอ่าน
จึงกลายเป็น `blocked` ตามเดิม (ไม่แอบทำงานครึ่ง ๆ กลาง ๆ)

**หมายเหตุ (bridge)**: state ของ EA bridge อยู่ในตาราง `bridge_sessions`/`bridge_commands`
ในฐานข้อมูล ไม่ใช่ในหน่วยความจำโปรเซส — ดังนั้นเมื่อรัน `--workers N` คำสั่งที่คิวโดย worker ที่ถือ lease
จะถูกส่งให้ EA ไม่ว่า poll จะไปตกที่ worker ตัวไหน และการ claim คำสั่งเป็น `UPDATE ... WHERE state='pending'`
จึงมี worker เดียวที่ได้คำสั่งไป (ทดสอบไว้ใน `tests/test_bridge.py` แล้ว)

## 8. รันได้ทีละโพรเซสเท่านั้น (single-writer)

runtime (tick, signal, order) ใช้ **lease** ในตาราง `kv` (`runtime_lease`) — โปรเซสเดียวเท่านั้นที่ขับเคลื่อนได้
ถ้าเปิดโปรเซสที่สองบนฐานข้อมูลเดียวกัน:

- `/api/system/health` → `status: degraded`, `services.runtime: "blocked (blocked)"`, `runtime_lease.owner` = เจ้าของตัวจริง
- log มี `runtime-lease: another No7 runtime already owns this database (...)`
- หน้า `/system` ขึ้นป้าย `blocked by <owner>`

ระวัง: worker ที่สองจะไม่เทรด (ซึ่งปลอดภัย) และจะไม่เห็นข้อมูลสดของ leader เว้นแต่ตั้ง `cluster.backend: redis`
หรืออ่านผ่าน DB — bridge เป็นข้อยกเว้น เพราะ state อยู่ใน DB ร่วม (ดู §7)
ถ้าจำเป็นต้องมีหลายโปรเซสจริง ๆ ให้ตั้ง `NO7_ALLOW_MULTI_RUNTIME=1` **เฉพาะเมื่อ** ตัวที่ไม่ใช่เจ้าของเปิดอ่านอย่างเดียว
และเข้าใจว่าออเดอร์อาจซ้ำได้ (ระบบจะขึ้น `shared` + บันทึก error ไว้)

heartbeat ทุก 5 วินาที, ถือว่า lease ตายเมื่อเงียบเกิน 30 วินาที → เปิดใหม่ได้ทันทีแม้โดน `kill -9`

## 9. ผู้ใช้และสิทธิ์

บัญชี demo เป็น `admin` โดยอัตโนมัติ (`NO7_DEMO_ROLE` เปลี่ยนได้, ค่าเริ่มต้น `admin`)

```bash
TOK=$(curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"email":"demo@no7.ai","password":"no7demo1234"}' \
  http://127.0.0.1:8000/api/auth/login | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# ดูผู้ใช้ทั้งหมด
curl -s -H "Authorization: Bearer $TOK" http://127.0.0.1:8000/api/users | python3 -m json.tool

# เพิ่ม viewer
curl -s -X POST -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"email":"somchai@example.com","password":"อย่างน้อย8ตัว","role":"viewer"}' \
  http://127.0.0.1:8000/api/users

# เปลี่ยน role / ปิดบัญชี (มีผลกับ token ที่ใช้งานอยู่ทันที)
curl -s -X PATCH -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"role":"trader"}' http://127.0.0.1:8000/api/users/somchai@example.com
curl -s -X PATCH -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"active":false}' http://127.0.0.1:8000/api/users/somchai@example.com
```

หรือทำผ่านหน้า **/system → ผู้ใช้และสิทธิ์** (เห็นเฉพาะ admin)

> ถ้าติด lockout (ไม่มี admin ที่ใช้งานอยู่เลย) ให้แก้ที่ฐานข้อมูลโดยตรง:
> `sqlite3 storage/db/no7.sqlite3 "UPDATE users SET role='admin', active=1 WHERE email='...';"`

## 10. ข้อมูล tick (ทำให้ backtest ไม่ต้องเดาลำดับในแท่ง)

```bash
# 1) import ไฟล์ tick ของโบรกเกอร์ (ต้องมีคอลัมน์ time, bid, ask)
.venv/bin/python scripts/import_ticks.py --csv ~/Downloads/XAUUSD_ticks.csv --symbol XAUUSD
#    ไฟล์ไม่มี timezone → บอกให้ชัด (ชื่อ tz ของ IANA)
.venv/bin/python scripts/import_ticks.py --csv ticks.csv --symbol XAUUSD --tz Etc/GMT-3
#    ไฟล์ยักษ์ (หลายล้านแถว) → ลด memory ต่อการอ่านหนึ่งครั้ง
.venv/bin/python scripts/import_ticks.py --csv big.csv --symbol XAUUSD --chunk-rows 100000
#    ต้องได้ layout เดิมแบบไฟล์เดียว (เพื่อ reproduce ของเก่า) เท่านั้น
.venv/bin/python scripts/import_ticks.py --csv old.csv --symbol XAUUSD --single-file

# 2) ดูว่ามี tick อะไรอยู่ ครอบคลุมแค่ไหน และเป็นของจริงหรือของจำลอง
curl -s localhost:8000/api/datasets/ticks/status -H "Authorization: Bearer $TOKEN" | jq
#    .ticks[].days = รายวัน (day, rows, first_t, last_t, format, bytes)
#    .ticks[].gaps = วันที่หายไปตรงกลางช่วง เช่น ["2026-01-06"]
#    .ticks[].rows_loaded = 0 เสมอ: ตอบจาก manifest ไม่ได้อ่านไฟล์แม้แต่ไฟล์เดียว

# 3) เก็บกวาดวันเก่า (admin) — ค่าเริ่มต้นจะ *ปฏิเสธ* ถ้ามี backtest ที่เคยใช้วันนั้น
curl -s -X POST "localhost:8000/api/datasets/ticks/prune?symbol=XAUUSD&keep_days=60" \
  -H "Authorization: Bearer $TOKEN" | jq
#    409 = มี report ที่อ้างวันนั้นอยู่ → รัน backtest ใหม่หรือส่ง force=true

# 3) รัน backtest — ใช้ tick อัตโนมัติ; เทียบกับโหมดเดิมได้ด้วย use_ticks=false
curl -s localhost:8000/api/backtests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"symbol":"XAUUSD","bars":6000,"use_ticks":true,"snapshot_id":"DS-XXXXXXXXXX"}'
```

อ่านผล: `diagnostics.intra_bar.bars_settled_by_ticks` = จำนวนแท่งที่ตัดสินด้วย tick จริง,
`bars_without_ticks` = จำนวนแท่งที่ยังใช้สมมติฐาน SL-ก่อน, `dataset.ticks.rows` = จำนวน tick ที่มีอยู่,
`ticks_in_window` = tick ที่มีในช่วงที่รัน (0 = ไม่มีข้อมูลครอบช่วงนี้จริง ไม่ใช่ "ไม่มีแท่งกำกวม"),
`dataset.ticks.days_used` = วันไหนที่ backtest นั้นอ่านจริง (ใช้ตัดสินตอน prune)

### การเก็บ tick: หนึ่งไฟล์ต่อวัน (parquet)

```
storage/datasets/ticks/XAUUSD/
  2026-11-05.parquet      ← หนึ่งวัน UTC ต่อหนึ่งไฟล์
  2026-11-06.parquet
  manifest.json           ← rows/first_t/last_t/sha256 ต่อวัน + ที่มาของไฟล์
```

backtest อ่านเฉพาะวันทีหน้าต่างแท่งทับอยู่ (เก็บ cache 4 วันล่าสุดแบบ LRU) — หน้าต่าง 1 วัน
บน store 12 วัน/1 ล้านแถว อ่านไฟล์เดียว ไม่ใช่ทั้งก้อน ตัวเลขนี้วัดได้จาก
`report.dataset.ticks.days_loaded` และ `days_used`; ถ้าไม่มี pyarrow ระบบจะเขียน `.csv.gz`
แทนให้อัตโนมัติ (ดู `layout`/`format` ใน `/api/datasets/ticks/status`)

**การย้าย/สำรองข้อมูล**: copy ทั้งโฟลเดอร์ `ticks/<SYMBOL>/` ทั้งก้อน (manifest ไปด้วย) —
ไฟล์เดียวไม่พอ, และถ้า manifest หาย ระบบจะเปิดอ่านทีละไฟล์เพื่อสร้างช่วงเวลาใหม่
(ผลลัพธ์เท่าเดิม แค่ช้าครั้งแรก)

**ถ้าต้องการทดสอบเฉพาะไปป์ไลน์โดยยังไม่มีไฟล์จริง**: `scripts/reconstruct_ticks.py` สร้าง tick
จากแท่ง M1 (ติดธง `reconstruction` ใน manifest) — ห้ามใช้ตัวเลขจากโหมดนี้ตัดสินใจเทรด

## 11. PWA / ติดตั้งเป็นแอป (มือถือ/เดสก์ท็อป)

```bash
cd apps/web-dashboard && npm run build      # ต้อง build ก่อน; public/ ถูกคัดลอกเข้า dist/
.venv/bin/python scripts/make_pwa_icons.py  # สร้างไอคอนใหม่ (ไม่ต้องใช้ Photoshop/ Pillow)
curl -s localhost:8000/manifest.webmanifest | jq '{id,start_url,scope,display,display_override,icons:[.icons[].sizes]}'
curl -s localhost:8000/sw.js | grep -c 'SKIP_WAITING'   # 1 = มีช่องให้หน้าเว็บสั่ง activate เอง
curl -sD - -o /dev/null localhost:8000/sw.js | grep -i 'cache-control\|service-worker-allowed'
curl -s localhost:8000/sw.js | grep "const VERSION"   # ต้องเป็น hash 12 ตัว ไม่ใช่ __NO7_VERSION__
```

- เปิดจากมือถือแล้วเลือก **Add to Home Screen / ติดตั้งแอป** → เปิดแบบ standalone
- **แถบเชิญติดตั้ง**: แอปจับ `beforeinstallprompt` เองแล้วขึ้นแถบ "ติดตั้ง No7 เป็นแอป"
  (ปิดได้ด้วย "ไม่ใช่ตอนนี้" และจำไว้ใน `localStorage`) — บน iOS ไม่มี prompt API
  จึงขึ้นคำใบ้ *แชร์ → เพิ่มไปที่หน้าจอโฮม*; เมื่อติดตั้งแล้วแถบหายเอง (`display-mode: standalone`)
- **อัปเดต**: worker ใหม่จะ **รอ** ไม่แทรกกลางเซสชัน (กันอาการ JS เก่าคู่กับ asset hash ใหม่
  และกัน ticket ที่กรอกค้างหาย) — หน้าเว็บขึ้นแถบ "มีเวอร์ชันใหม่" พร้อมปุ่ม *รีเฟรชเดี๋ยวนี้*
  ซึ่งส่ง `SKIP_WAITING`; มี `registration.update()` ทุก 30 นาทีเป็นตัวช่วย
- **ออฟไลน์ vs เซิร์ฟเวอร์ไม่ตอบ** แยกข้อความกัน: อุปกรณ์หลุดเน็ต → "ออฟไลน์",
  เปิดเชลล์จากแคชได้แต่ `/api` ยิงไม่ถึง → "เซิร์ฟเวอร์ไม่ตอบ — ตัวเลขที่เห็นคือข้อมูลเก่า"
  พร้อมเวลาข้อมูลล่าสุด (`ข้อมูลล่าสุด HH:MM`) — ไม่มีทางที่ตัวเลขเก่าจะดูเหมือนราคาสด
- **แคชเชลล์ / storage**: เรียก `navigator.storage.persist()` ให้เบราว์เซอร์ไม่ลบแคช
  และแสดง `estimate()` (MB ที่ใช้/โควตา) ในหน้า **/system → แอป / PWA** พร้อมสถานะ
  service worker และปุ่มติดตั้ง (admin ไม่จำเป็น — เป็นข้อมูลฝั่งเบราว์เซอร์)
- service worker **ไม่แคช** `/api/*` หรือ `/ws` โดยตั้งใจ และไม่มี background sync ของออเดอร์
- deploy build ใหม่: ไม่ต้องแก้อะไร — `/sw.js` ที่เสิร์ฟมี cache name ตาม hash ของ `index.html`
  เบราว์เซอร์จะได้ worker ใหม่ตอนเปิดครั้งถัดไป (cache เก่าถูกลบใน `activate`)
- ถ้าอยากล้าง cache ทั้งหมดระหว่าง debug: DevTools → Application → Service Workers → Unregister + Clear storage
- dev (vite 5173) **ไม่มี** service worker — การทดสอบ PWA ต้องใช้ build + uvicorn เท่านั้น

## 12. เชื่อม MT5 ผ่าน EA bridge (ไม่ต้องรันเซิร์ฟเวอร์บน Windows)

> **ขั้นตอนเดิมด้านล่างเป็นข้อมูลเก่า ไม่ใช่คำสั่งเปิดใช้งานในรอบนี้**:
> bridge ปัจจุบันมีค่าเริ่มต้น read-only และต้องระบุ Demo login/server จริง
> ดู [ขั้นตอนส่งต่องานและ acceptance ปัจจุบัน](SAFETY-HANDOFF.th.md) ก่อนติดตั้งหรือเปลี่ยนค่า
> ห้ามเปิด Algo Trading หรือเปิด execution ตามตัวอย่างเดิม; simulator ไม่ใช่ข้อมูลโบรกเกอร์จริง

**หลักการ**: เซิร์ฟเวอร์ไม่ถือรหัส MT5 เลย — EA ในเทอร์มินัลจะ poll `/api/bridge/poll` ทุก 1 วินาที
ส่ง snapshot (บัญชี/ราคา/โพซิชัน/M1 rates) และรับคำสั่งไป execute แล้วรายงานกลับครั้งเดียว

```bash
# 1) เปิด bridge ฝั่งเซิร์ฟเวอร์ + ตั้ง token (ปิดไว้โดยค่าเริ่มต้น = fail closed)
export NO7_BRIDGE_ENABLED=true
export NO7_BRIDGE_TOKEN="$(openssl rand -hex 24)"   # เก็บให้ดี = credential ของบัญชีนี้
scripts/run.sh                                       # หรือ uvicorn ตามปกติ (worker เดียว!)

# 2) ตรวจว่าเซิร์ฟเวอร์พร้อม (ยังไม่มี EA = bridges ว่าง, enabled true)
curl -s localhost:8000/api/bridge/session -H "Authorization: Bearer $TOKEN" | jq

# 3a) ทดสอบก่อนโดยไม่มี MT5 — EA จำลอง (โปรโตคอลเดียวกันเป๊ะ)
.venv/bin/python scripts/run_bridge_sim.py --server http://127.0.0.1:8000 \
    --account mt5-bridge-demo --token "$NO7_BRIDGE_TOKEN" --duration 120 --rates

# 3b) ของจริงบน Windows: MetaEditor -> เปิด bridge/No7BridgeEA.mq5 -> compile
#     ใส่ InpServerUrl / InpToken / InpAccountId ("mt5-bridge-demo") / InpSymbols
#     Tools > Options > Expert Advisors > Allow WebRequest for listed URL: เพิ่ม URL เซิร์ฟเวอร์
#     Attach เข้ากราฟ 1 ชาร์ต (EA ตัวเดียวต่อบัญชี) แล้วเปิด Algo Trading

# 4) ตรวจว่าต่อติด + สลับ broker ที่ใช้งาน
curl -s localhost:8000/api/bridge/status -H "Authorization: Bearer $TOKEN" | jq '.sessions'
curl -s -X POST localhost:8000/api/brokers/mt5-bridge-demo/activate \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}' | jq
```

อ่านสถานะ: `health: connected` = snapshot ใหม่กว่า `fresh_seconds` (5s), `stale` = 5–15s, `disconnected` = เกิน 15s
(ช่วง stale/disconnected ระบบ **ไม่ยอมใช้ราคาหรือส่งคำสั่ง** — ขึ้น error ไม่ใช่ราคาเก่า)

**เมื่อ EA หลุด/รีสตาร์ท**: register ใหม่จะได้ `generation + 1`, คิวเดิมถูกทิ้งเป็น `orphaned_commands`
(ดูใน `/api/bridge/status`) และ snapshot เก่าถูกล้าง — ระบบไม่เอา state ของเทอร์มินัลเก่ามาใช้ต่อ

**ข้อบังคับจากการออกแบบ**
- ใช้ `--workers N` ได้ (state อยู่ใน DB ร่วม) แต่ยังมี **โปรเซสเดียวที่เทรด** ตาม runtime lease —
  worker อื่นรับ HTTP (รวม poll ของ EA) และอ่าน state ร่วมกัน
- ถ้าฐานข้อมูลเป็นไฟล์เดียวกันบนเครื่องเดียว: SQLite WAL รองรับหลาย worker; ถ้าย้ายไป Postgres
  ต้องย้ายตาราง `bridge_*` ตามไปด้วย (ที่เหลือของแอปย้ายตามอยู่แล้ว)
- คำสั่งที่ EA ไม่ ack จะหมดอายุ (`command_ttl_seconds` 30s / `ack_grace_seconds` 20s) และ **ไม่ส่งซ้ำ**
- ต้องเปิด Algo Trading ในเทอร์มินัล ไม่งั้น EA ไม่ execute (ฝั่งเซิร์ฟเวอร์จะเห็นแค่ `expired`)

## 12.4 แจ้งเตือนออกนอกเครื่อง (Telegram / LINE / webhook)

in-app ทำงานเสมอ; ช่องทางภายนอกเป็น **opt-in** (ต้องมี token *และ* เปิดใช้)

### Telegram
```bash
# 1) สร้างบอทกับ @BotFather -> ได้ token
# 2) หา chat id: ส่งข้อความหาบอทก่อน แล้วเปิด
#    https://api.telegram.org/bot<TOKEN>/getUpdates  (อ่าน chat.id)
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export NO7_TELEGRAM_CHAT_ID="-1001234567890"
export NO7_TELEGRAM_ENABLED=true
```

### LINE (Messaging API)
```bash
# LINE Developers -> Messaging API channel: channel access token + ผู้รับ (userId/groupId)
export LINE_CHANNEL_TOKEN="..."
export NO7_LINE_TARGET_ID="U..."
export NO7_LINE_ENABLED=true
```

### ทดสอบว่าส่งได้จริง
```bash
TOK=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@no7.ai","password":"no7demo1234"}' | jq -r .token)
curl -s -X POST localhost:8000/api/system/alerts/test -H "Authorization: Bearer $TOK" | jq
#  {"ok": true, "deliveries":[{"channel":"telegram","ok":true,"status":200,"attempts":1}, …],
#   "paced": [], "note": ""}
curl -s localhost:8000/api/system/notify -H "Authorization: Bearer $TOK" | jq '.state, .channels'
```

### พฤติกรรมเมื่อเครือข่ายมีปัญหา (ตั้งใจให้เป็นแบบนี้)
| สถานการณ์ | สิ่งที่เกิดขึ้น |
|---|---|
| timeout / ต่อไม่ติด / **429** / 5xx | ลองใหม่ไม่เกิน `alerts.retry_attempts` (ค่าเริ่มต้น 3) โดยเคารพ `Retry-After` (สูงสุด 30s) และ backoff 0.5s, 1.0s |
| 400/401/403/404 (token/chat id ผิด, บอทถูกบล็อก) | **ไม่ลองซ้ำ** — แก้ config แล้วกดทดสอบใหม่ |
| ข้อความถี่เกิน `alerts.min_interval_seconds` (ค่าเริ่มต้น 1s/channel) | **ข้าม** ข้อความนั้น (in-app ยังบันทึกครบ) และนับใน `dropped` — กันบอทโดน mute |
| ข้อความยาวเกิน | ตัดให้พอดีลิมิต (Telegram 4096 / LINE 5000) ไม่ให้ผู้ให้บริการตอบ 400 |
| ส่งไม่สำเร็จ | บันทึกใน `alerts` + `notify_status` (`failures`), `state: "failing"` ใน health |

**Token ไม่รั่ว**: token ของ Telegram อยู่ใน URL จึงอาจโผล่ในข้อความ error — ทุกสตริงที่ออกจาก
notifier (status, alert payload, error) ถูกแทนด้วย `***` ก่อนเก็บ/ส่ง และ `status()` แสดงแค่
`base` (host) ไม่ใช่ token

### ชี้ transport ไปที่เซิร์ฟเวอร์จำลอง (ใช้ทดสอบ)
```bash
python3 scripts/fake_alert_provider.py 8099        # เทอร์มินัลหนึ่ง
NO7_TELEGRAM_API_BASE=http://127.0.0.1:8099        # อีกเทอร์มินัล: รับเฉพาะ http ไปยัง private host
NO7_LINE_API_BASE=http://127.0.0.1:8099
#   fake provider ตอบ 429 ในครั้งแรกของ Telegram เพื่อให้เห็น retry ทำงานจริง
```
ถ้าตั้ง http ไปยัง host สาธารณะ ระบบจะ **ไม่ใช้** ค่านั้น (plaintext จะทำ token หลุด)
ถอยไปใช้ endpoint จริงและรายงานใน `base_warnings`

## 12.5 Rate limit ที่ใช้ร่วมกันหลาย worker / หลายเครื่อง

ค่าเริ่มต้น `ratelimit.store: memory` = bucket อยู่ในโปรเซสเดียวなので
**`--workers N` จะได้โควตาคูณ N** (limit 6/นาที → เห็นจริง 7 ในการทดสอบ 2 worker)
ถ้าจะรันหลาย worker/หลายเครื่อง ให้เลือก store ที่แชร์:

```bash
# หลาย worker บนเครื่องเดียว — bucket อยู่ในไฟล์ SQLite เล็ก ๆ
NO7_RATELIMIT_STORE=sqlite scripts/run.sh
#   ไฟล์: storage/db/ratelimit.sqlite3 (override: ratelimit.store_path)

# หลายเครื่อง — Redis เป็นเจ้าของตัวนับ (ต้อง pip install redis)
export NO7_RATELIMIT_STORE=redis
export NO7_REDIS_URL=redis://10.0.0.5:6379/0
export NO7_RATELIMIT_PREFIX=no7:ratelimit      # namespace ของ deployment นี้
scripts/run.sh
#   NO7_REDIS_URL ตัวเดียวกันนี้ยังใช้กับ cluster.backend=redis ได้ด้วย
```

ตรวจว่าที่รันอยู่ได้ผลจริง:

```bash
curl -s localhost:8000/api/system/health | jq .ratelimit
#  {"store":"sqlite","requested":"sqlite","shared":true,"path":"…/ratelimit.sqlite3"}
#  {"store":"memory","shared":false,"warning":"… --workers N multiplies the configured limit"}
```

**กติกาความล้มเหลว**: Redis ต่อไม่ได้ตอนบูต → ถอยไป `sqlite` (หรือ `memory` ถ้าไม่มี path)
และบอกเหตุผลใน `reason` ไม่ใช่เงียบ ๆ; ถ้า Redis ล่ม **ระหว่างใช้งาน** คำขอยังผ่านได้ แต่ถูกจำกัด
ด้วย bucket ในโปรเซสแทน, ตัวนับ `degraded` เพิ่มขึ้น และ response มี header
`x-ratelimit-degraded: redis` — เลือกทางนี้เพราะการทำให้หน้าเทรดล่มทั้งระบบ
เพราะ cache กระพริบนั้นอันตรายกว่าการจำกัดชั่วคราวในเครื่องเดียว

ทดสอบฝั่งเทสต์: `tests/test_ratelimit_shared.py` รันสัญญาเดียวกันบน memory/sqlite/redis
(fakeredis รัน Lua ตัวจริง) และมีเคส 4 โปรเซสแยกกันแย่ง bucket 40 → ปล่อยผ่านได้ 40 พอดี
ส่วนการพิสูจน์กับ **redis-server ตัวจริง** อยู่ที่ §12.6

> **health บอกความจริงระหว่างที่ Redis ล่ม** — `/api/system/health → ratelimit` มีฟิลด์
> `degraded` (จำนวนครั้งที่ต้องถอยไป bucket ในโปรเซส) และเมื่อ `degraded > 0` ฟิลด์
> `shared` จะกลายเป็น `false` พร้อม `last_error` + `warning` แทนที่จะยังเขียวว่า `shared: true`

## 12.6 Redis จริง — พิสูจน์ก่อน deploy

fakeredis เป็น implementation คนละตัว การอ้างว่า "Redis ใช้ได้" จึงต้องมีหลักฐานกับ
`redis-server` ตัวจริง ทุกอย่างด้านล่างรันได้โดยไม่ต้องเป็น root

### 12.6.1 เอา redis-server มาโดยไม่ต้องติดตั้ง

```bash
./scripts/fetch_redis_server.sh          # → .tools/bin/redis-server (+ redis-cli), 6.2.14
.venv/bin/python -m pytest tests/test_redis_real.py -q     # 17 passed
```

ไม่มี binary = เทสต์ชุดนี้ **skip** (ไม่ใช่ผ่าน) และ CI จะ fail ถ้ามันถูก skip
— ดู step "Prove the real-Redis tests actually ran" ใน `.github/workflows/ci.yml`

### 12.6.2 ตรวจเซิร์ฟเวอร์จริงก่อนชี้ production ไปหา

```bash
.venv/bin/python scripts/check_redis.py --url redis://10.0.0.5:6379/0 --ttl 2
#  PASS PING / server identifies itself / eviction policy / Lua token bucket /
#       budget shared across connections / refill / exact balance / TTL /
#       frame bus / frames expire / hostile key / cleans up after itself
#  12/12 checks passed — OK
```

เครื่องมือนี้ **ไม่เคย FLUSHDB**, เขียนเฉพาะคีย์ `no7:selftest:<random>:*` แล้วลบทิ้ง,
ปิดรหัสผ่านใน URL ที่พิมพ์ออกมา และคืนค่า exit 0 (ผ่าน) / 1 (มีเช็กตก) / 2 (ต่อไม่ได้)
ถ้า `maxmemory-policy` ไม่ใช่ `noeviction` จะได้ **WARN** เพราะ bucket อาจถูก evict
แล้วโควตารีเซ็ตเงียบ ๆ

### 12.6.3 ผลที่วัดได้จริงด้วยสองโปรเซส + Redis จริง

| ทดสอบ | ผล |
|---|---|
| 2 API (`:8051` leader, `:8052` replica) + Redis `:6392` | ทั้งคู่: `cluster.backend=redis`, `shared_health.ok=true`, `ratelimit {store: redis, shared: true}` |
| ยิงสลับพอร์ตด้วยผู้ใช้เดียว (โควตา default 300/นาที) | ผ่าน **303** ครั้ง (8051=152 + 8052=151) แล้ว **429 ทั้งสองพอร์ต** = โควตาเดียวกันจริง |
| bucket ใน Redis หลังโดนจำกัด | `tokens 0.3343195915222168`, TTL 60s (17 หลัก = ไม่ถูกปัด) |
| ฆ่า leader `:8051` | `:8052` ขึ้นเป็น leader ภายใน **≤4 วินาที**, frame `no7:live:v1` เปลี่ยนเจ้าของ |
| ฆ่า Redis ทั้งตัว | API ยังตอบ 200 พร้อม `x-ratelimit-degraded: redis`, health: `shared_health.ok=false` + `Connection refused`, `ratelimit.degraded > 0` และ `shared=false` |

### 12.6.4 เช็กลิสต์ก่อนใช้ production

- `maxmemory-policy noeviction` (ตัวนับห้ามถูก evict)
- Redis อยู่ในเครือข่ายส่วนตัว หรือมี `requirepass` — **ยังไม่ได้ทดสอบ** `requirepass`/TLS (`rediss://`) ที่นี่
- `NO7_RATELIMIT_PREFIX` แยกต่อ environment (`no7:prod:ratelimit`, `no7:staging:ratelimit`)
- ตั้ง NTP ให้ทุกเครื่อง: ตัวนับใช้เวลาของแอป ไม่ใช่ `TIME` ของ Redis
- ไม่ต้องเปิด persistence: bucket หายคือโควตาเริ่มใหม่ ไม่ใช่ข้อมูลสูญหาย
- socket timeout 2 วินาที (ค่าในโค้ด) — Redis ที่ "ช้าแต่ไม่ตาย" จะหน่วงคำขอได้ถึง 2 วินาที
  ก่อนถอยไป bucket ในเครื่อง ยังไม่มีการทดสอบกรณีนี้

## 12.7 เพดานจำนวน WebSocket ที่เปิดพร้อมกัน

HTTP ถูกจำกัดเป็น "กี่ครั้งต่อนาที" แต่ socket คือคำขอเดียวที่กิน CPU ไปเรื่อย ๆ จนกว่าจะปิด
จึงต้องจำกัดคนละแบบ: **เปิดพร้อมกันได้กี่ตัว**

```yaml
# config/app.yaml
ws:
  max_connections_per_user: 4     # ต่อบัญชี (ไม่มี token → ต่อ IP)
  max_connections_total: 64       # ทั้ง deployment
  lease_ttl_seconds: 45           # slot หมดอายุเองถ้าไม่มีใครต่ออายุ
```

store มาจากบล็อก `ratelimit` อันเดียวกัน (memory / sqlite / redis) ใช้ prefix `no7:ws`
→ ตั้ง `NO7_RATELIMIT_STORE=redis` ครั้งเดียว ได้ทั้งโควตา HTTP และโควตา socket ที่แชร์ข้ามเครื่อง

```bash
curl -s localhost:8000/api/system/health | jq .websockets
# {"enforced":true,"store":"redis","shared":true,"max_per_user":4,"max_total":64,
#  "lease_ttl_seconds":45,"open":3,"granted":12,"refused":2,"degraded":0}
```

**ทำไมเป็น lease ไม่ใช่ตัวนับ**: worker ที่ถูก SIGKILL/OOM ไม่มีโอกาสรัน "ลดตัวนับ" — ถ้าใช้
ตัวนับ ทุกครั้งที่ worker ตายคือ capacity หายถาวรจนกว่าจะรีสตาร์ต lease แก้ด้วยเวลา:
socket ที่ยังสตรีมอยู่จะต่ออายุ lease เรื่อย ๆ ส่วน socket ของโปรเซสที่ตายไปแล้วจะหมดอายุเอง
ราคาที่จ่ายคือ "slot คืนช้าได้ถึง `lease_ttl_seconds`" ซึ่งยอมรับได้มากกว่าการสูญ capacity ถาวร

**client เห็นอะไร**: โดนปฏิเสธ = ได้ 1 เฟรมบอกเหตุผลแล้วปิดด้วย code **4429**;
token หมดอายุระหว่างสตรีม = ปิดด้วย **4401** (socket ต้องไม่อยู่นานกว่าสิทธิ์ที่เปิดมัน)

### 12.7.1 ผลที่วัดได้จริง (2 worker + redis จริง)

| ทดสอบ | ผล |
|---|---|
| health ทั้งสอง worker | `{"store":"redis","shared":true,"max_per_user":4}` |
| เปิด 3 socket ที่ `:8061` แล้วอีก 3 ที่ `:8062` | เปิดได้ **4** (A=3 + B=1) ตัวที่ 5-6 ถูกปฏิเสธ `4429` พร้อมข้อความ `already holds 4 of 4 live sockets` |
| ปิด socket ทั้งหมด | `open: 0` และไม่มีคีย์ `no7:ws*` ค้างใน Redis |
| `kill -9` worker A ขณะถือ socket | lease ยังอยู่ (`zcard = 1`, key TTL 88s) แล้วหายเองตามเวลา — ไม่มีใครรัน release เลย |

### 12.7.2 ปรับเพดานยังไง

- ผู้ใช้หนึ่งคนเปิดได้กี่แท็บคือ `max_connections_per_user` (dashboard ใช้ 1 socket/แท็บ)
  ตั้งต่ำเกินไป = เปิดสองแท็บแล้วพัง; 3-5 เป็นค่าที่ใช้งานได้จริง
- `max_connections_total` ควรตั้งจากจำนวน thread ที่เครื่องรับไหว: ทุก socket ใช้ 1 thread
  ตอนสร้าง payload (`asyncio.to_thread`) — เริ่มที่ 64 แล้วดู CPU
- ตั้ง `0` = ไม่จำกัด (ไม่แนะนำ แต่รองรับไว้สำหรับ deployment ที่มี proxy จำกัดให้แล้ว)
- `lease_ttl_seconds` ต่ำ = คืน slot เร็วแต่ต่ออายุถี่ขึ้น; อย่าตั้งต่ำกว่า ~15 วินาที

## 12.8 แจ้งเตือนออกนอกเครื่อง — คิวที่ไม่หาย และลายเซ็นที่ตรวจได้

### 12.8.1 ปัญหาเดิม

`Notifier` ลองส่งซ้ำอยู่ประมาณ 1 วินาทีแล้วเลิก — ครอบคลุมแค่แพ็กเก็ตตก ไม่ครอบคลุม
กรณีปกติที่สุดคือ "ปลายทางกำลัง deploy อยู่ 1-2 นาที" alert ทุกตัวในช่วงนั้นหายหมด
รวมถึงตัวที่มีไว้เพราะไม่มีใครนั่งดูจอ (`ขาดทุนถึงลิมิตรายวัน`, `Cooldown engaged`)

และ webhook เดิม **ไม่มีลายเซ็น**: `webhook_secret` ถูกอ่านมาเพื่อลบออกจากล็อกเท่านั้น
URL ของ webhook ไม่ใช่ความลับ (มันอยู่ใน config, ใน log ของ CI, ในภาพหน้าจอ) ใครรู้ URL
ก็ยิง alert ปลอมเข้าระบบรับได้

### 12.8.2 ตั้งค่า

```bash
export NO7_WEBHOOK_ENABLED=true
export NO7_WEBHOOK_URL=https://hooks.example.com/no7
export NO7_WEBHOOK_SECRET=$(python3 -c 'import secrets;print("whsec_"+secrets.token_hex(24))')
```

```yaml
# config/app.yaml → alerts.outbox
outbox:
  enabled: true
  max_attempts: 20           # รวมครั้งที่ส่งสดครั้งแรกด้วย
  max_age_seconds: 1800      # เก่ากว่านี้ไม่ต้องส่งแล้ว
  backoff_seconds: 5         # หน่วงครั้งแรก แล้วคูณสองไปเรื่อย ๆ
  backoff_cap_seconds: 60    # เพดานหน่วง = ช้าสุดที่ backlog จะเริ่มไหลหลังปลายทางฟื้น
  capacity: 500              # คิวเต็มแล้วทิ้ง "ตัวเก่าสุด" (ของใหม่มีค่ากว่า)
```

```bash
curl -s localhost:8000/api/system/notify | jq '{webhook_signed, outbox}'
# {"webhook_signed": true,
#  "outbox": {"enabled":true,"pending":0,"queued":12,"delivered":12,
#             "expired":0,"exhausted":0,"overflowed":0,"oldest_seconds":0.0}}
```

### 12.8.3 ฝั่งรับต้องตรวจยังไง

เซ็นด้วย HMAC-SHA256 บน `"<timestamp>." + body` ส่งมาใน 2 เฮดเดอร์หลัก:

| เฮดเดอร์ | ความหมาย |
|---|---|
| `X-No7-Signature` | `sha256=<hex>` |
| `X-No7-Timestamp` | epoch วินาที ที่ใช้เซ็น (เวลาที่ **ส่ง** ไม่ใช่เวลาที่เกิดเหตุ) |
| `X-No7-Delivery-Id` | มีเมื่อส่งจากคิว — ใช้กันข้อความซ้ำ (การส่งเป็นแบบ at-least-once) |
| `X-No7-Queued-At` | มีเมื่อส่งจากคิว — เวลาที่ alert เกิดจริง |
| `X-No7-Attempt` | ครั้งที่เท่าไรของข้อความนี้ |

```python
import hashlib, hmac, time

SECRET = "whsec_..."

def verify(raw_body: bytes, headers) -> bool:
    stamp = headers.get("X-No7-Timestamp", "")
    sent = headers.get("X-No7-Signature", "")
    if not stamp or not sent:
        return False
    if abs(time.time() - float(stamp)) > 300:      # กันการเล่นซ้ำ
        return False
    expect = "sha256=" + hmac.new(
        SECRET.encode(), f"{stamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, sent)       # เทียบแบบ constant-time
```

**กับดักที่พังบ่อยที่สุด**: ต้องตรวจบน **raw bytes ที่ได้รับ** ห้าม `json.loads` แล้ว `json.dumps`
ใหม่ — ลำดับคีย์/ช่องว่างเปลี่ยนนิดเดียวลายเซ็นก็ไม่ตรง (ฝั่งส่งก็ใช้ฟังก์ชันเดียวกันตอนเซ็น
และตอนส่ง ด้วยเหตุผลเดียวกัน — ดู `services/notification/signing.py`)

**เซ็นตอนส่ง ไม่ใช่ตอนเข้าคิว**: ถ้าเซ็นตั้งแต่เข้าคิว ข้อความที่รอในคิว 10 นาทีจะมาพร้อม
timestamp เก่า แล้วถูกฝั่งรับปฏิเสธว่าเป็น replay ทุกครั้งที่ retry — เวลาที่เกิดเหตุจริงอยู่ใน
`X-No7-Queued-At` และในฟิลด์ `ts` ของ body แทน

### 12.8.4 ผลที่วัดได้จริง (`scripts/check_outbox.py`)

รันกับแอปจริง: ปลายทางล่ม → รีสตาร์ต API → ปลายทางกลับมา

| ทดสอบ | ผล |
|---|---|
| ปลายทางล่ม แล้วยิง alert | เข้าคิว `pending=1` (เดิม: หายไปเฉย ๆ) |
| ฆ่าโปรเซส API แล้วเปิดใหม่ | `pending=1` เท่าเดิม — คิวอยู่ใน sqlite |
| เปิดปลายทางกลับมา ไม่แตะอะไรอีก | ลูปส่งให้เองจนคิวว่าง `delivered=1 pending=0` |
| ตรวจลายเซ็นฝั่งรับ | ผ่าน — `signed_at` ช้ากว่า `queued_at` 79 วินาที (เซ็นตอนส่งจริง) |
| เฮดเดอร์ dedupe | `X-No7-Delivery-Id: OB3f14296c4a31` |

```bash
# ทำซ้ำเองได้
.venv/bin/python scripts/check_outbox.py --port 8000 --stage before-restart   # ปลายทางยังไม่เปิด
# ... รีสตาร์ตเซิร์ฟเวอร์ ...
.venv/bin/python scripts/check_outbox.py --port 8000 --stage after-restart
```

### 12.8.5 สิ่งที่คิวนี้ **ไม่** รับประกัน

- **ส่งอย่างน้อยหนึ่งครั้ง ไม่ใช่ครั้งเดียวเป๊ะ** — ถ้า POST สำเร็จแต่ตอบกลับหาย จะส่งซ้ำ
  ฝั่งรับต้อง dedupe ด้วย `X-No7-Delivery-Id`
- **ไม่รับประกันลำดับ** — alert สดถูกส่งก่อน backlog โดยตั้งใจ (ข่าวด่วนไม่ควรรอคิวเก่า)
- **ของเก่าเกิน `max_age_seconds` ถูกทิ้ง** — แต่ถูกนับไว้ใน `outbox.expired` และขึ้น `warning`
- คิวนี้เป็นของเครื่องนี้ (sqlite ไฟล์เดียว) ยังไม่ใช่คิวกลางสำหรับหลายเครื่อง

## 12.9 "ระบบไม่ยอมเทรดเลย" — หาคำตอบใน 30 วินาที

อาการนี้เคยตอบไม่ได้เลย เพราะทุกชั้นนับแต่จำนวน ตอนนี้ถามตรง ๆ ได้:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@no7.ai","password":"no7demo1234"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s localhost:8000/api/system/attribution -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['headline']); \
      [print(f\"  {r['count']:4d} {r['pct']:5.1f}%  {r['label']}  {r['samples'][:1]}\") for r in d['overall']['signal']['primary']]"
```

อ่านผลอย่างไร:

| สิ่งที่เห็น | แปลว่า | ทำอะไรต่อ |
|---|---|---|
| `entry_conditions` กินเกือบทั้งหมด | ไม่มีจังหวะเข้าตามกฎ ไม่ใช่ระบบเสีย | ดู `samples`, ตรวจว่า zone/trend ใน `/api/analysis` สมเหตุผล |
| `score_below_execute` สูง | มีจังหวะแต่คะแนนไม่ถึงเกณฑ์ | ดูว่าคะแนนห่างเกณฑ์แค่ไหนใน `samples` ก่อนคิดปรับ `execute` |
| `data_quality` / `broker_health` / `news_lockout` | ปัญหาสภาพแวดล้อม ไม่ใช่กลยุทธ์ | แก้ฟีด/การเชื่อมต่อ แล้ว `POST /api/system/attribution/reset` เริ่มนับใหม่ |
| `gate.blocked` สูงแต่ `signal.actionable` ปกติ | กลยุทธ์หาไม้ได้ แต่ risk gate ปัด | ดู `gate.primary` — มักเป็น `cooldown`, `daily_loss`, `spread` |
| `unregistered:*` + `warning` | มีเหตุผลใหม่ที่ยังไม่ลงทะเบียน | เพิ่ม code ใน `services/strategy_engine/attribution.py` |

- หน้า **System → "ทำไมถึงไม่เทรด"** แสดงชุดเดียวกันเป็นแถบ พร้อมปุ่ม *เริ่มนับใหม่*
- หน้าต่างนับเป็นแบบสะสมตั้งแต่ boot หรือตั้งแต่ reset ล่าสุด (`since`, `window_seconds`)
- นับเฉพาะ gate ของสัญญาณที่ "ขอเทรดจริง" เท่านั้น เพื่อให้เทียบกับ backtest ได้ตรง ๆ
- ของ backtest อยู่ใน `report.diagnostics.attribution` และสรุปหนึ่งบรรทัดใน `assumptions`

> บทเรียนรอบ 28–29: คำถามนี้เปิดเรื่อง `consecutive_losses` ขึ้นมา และรอบ 29 เจ้าของระบบ
> เคาะว่าให้เป็น **การหยุดจริง**: แพ้ติดกัน 3 ไม้ → หยุดทันที ไม่มีตัวจับเวลาปลดให้
> ถ้าเห็น `consecutive_losses` เป็นเหตุผลอันดับหนึ่ง นั่นคือระบบทำงานถูกแล้ว ไม่ใช่เสีย
> — ดูหัวข้อถัดไปว่าจะปลดอย่างไร

## 12.10 ระบบหยุดเพราะแพ้ติดกัน 3 ไม้ — ปลดอย่างไร

กติกา: **แพ้ติดกันครบ 3 ไม้ → หยุดทันที และไม่กลับมาเอง** (cooldown 20 นาทีเป็นการพักคนละตัว
ที่สั้นกว่า) ไม้ที่ปิดเสมอ (P&L = 0) ไม่นับแพ้และไม่ล้างสตรีค

ทางออกมีสองทาง:

1. **มีไม้ที่กำไรถูกบันทึกเข้าบัญชี** — สตรีคล้างเองทันที แต่ระหว่างถูกหยุด
   **ปุ่มอนุมัติไม้ด้วยมือในแอปก็ถูกบล็อกด้วย** (ผ่าน gate ตัวเดียวกัน) ไม้กำไรจึงต้องมาจาก
   การเทรดบนเทอร์มินัล MT5 โดยตรงแล้วให้ระบบ reconcile เข้ามา
2. **ผู้ดูแลกดปลด** — หน้า Dashboard → การ์ด *Risk Engine* → ปุ่ม **ปลดการหยุดจากสตรีคขาดทุน**
   หรือยิง API ตรง:

```bash
curl -s -X POST localhost:8000/api/risk/loss-streak/release \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

การปลดจะเขียน watermark (`loss_streak_release_at`) ไม่ได้แก้ P&L ในตาราง `trades`
ไม้ที่ขาดทุนยังอยู่ครบในสมุดบัญชีและใน Journal ทุกครั้งที่ปลดถูกบันทึก audit
(`risk.loss_streak.release` พร้อมอีเมลคนกด) และ **ปลดแล้วไม่ได้แปลว่าปลอดภัยไปตลอด** —
แพ้ติดกันอีก 3 ไม้หลังจุดที่ปลด ระบบหยุดใหม่ทันที

ตรวจสถานะปัจจุบัน:

```bash
curl -s localhost:8000/api/risk/settings -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; s=json.load(sys.stdin)['state']; \
      print('consecutive_losses', s['consecutive_losses'], '| cooldown_until', s['cooldown_until'])"
```

> ใน backtest ไม่มีใครกดปลดได้ ดังนั้นรันที่ชนกติกานี้จะ**จบตรงนั้น** และรายงานจะขึ้นบรรทัด
> `RUN ENDED ON THE LOSING-STREAK STOP` — ตัวเลข metrics ของรันแบบนั้นบอกแค่ว่า
> "ชนการหยุดเร็วแค่ไหน" ไม่ใช่ผลงานของกลยุทธ์

## 13. ความปลอดภัย — TLS, reverse proxy และ perimeter

### 13.1 เปิด HTTPS (เลือกอย่างใดอย่างหนึ่ง)

```bash
# (ก) ให้ uvicorn ถือ cert เอง — ง่ายสุดสำหรับ LAN
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout certs/dev.key -out certs/dev.crt
NO7_TLS_CERT=certs/dev.crt NO7_TLS_KEY=certs/dev.key scripts/run.sh   # -> https://…:8000

# (ข) วาง reverse proxy ข้างหน้า (แนะนำสำหรับอินเทอร์เน็ต) แล้วบอกว่าใครคือ proxy
export NO7_TRUSTED_PROXIES="127.0.0.1/32,::1/128"
scripts/run.sh
```

nginx (สรุป):
```nginx
server {
  listen 443 ssl http2;
  server_name no7.example.com;
  ssl_certificate     /etc/letsencrypt/live/no7.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/no7.example.com/privkey.pem;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;   # ต่อท้าย ไม่ใช่เขียนทับ
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;                        # /ws ต้องมี
    proxy_set_header Connection "upgrade";
  }
}
```

> **สำคัญ**: `scripts/run.sh` ส่ง `--no-proxy-headers` ให้ uvicorn เสมอ เพราะการตัดสินใจว่า
> "ใครคือ client / คำขอนี้เป็น HTTPS จริงไหม" เป็นของแอป (`services/api_gateway/netutil.py`)
> ที่ใช้ `NO7_TRUSTED_PROXIES` — ถ้ารัน `uvicorn` เองโดยไม่ใส่ `--no-proxy-headers`
> uvicorn จะ rewrite ค่าพวกนี้ด้วย allowlist ของตัวเอง (ค่าเริ่มต้น loopback) ก่อนถึงแอป
> ทำให้ config ที่ตั้งใจไว้ถูกข้าม

### 13.2 ตรวจว่าป้องกันจริง (คัดลอกไปรันได้)

```bash
curl -skD - -o /dev/null https://localhost:8443/ | grep -i 'content-security-policy\|strict-transport'
#  ต้องเห็น CSP (default-src 'self' … frame-ancestors 'none') และ HSTS เมื่อเป็น HTTPS จริง

curl -s http://localhost:8022/api/system/health | jq .security
#  cors / trusted_proxies / csp_mode / hsts_when_https / jwt_secret_from_env

# ปลอม IP ต้องไม่ผ่าน — peer ที่ไม่อยู่ใน trusted list ส่ง X-Forwarded-For มาไม่นับ
for i in 1 2 3; do
  curl -s -o /dev/null -X POST http://localhost:8022/api/auth/login \
    -H 'Content-Type: application/json' -H "X-Forwarded-For: 198.51.100.$i" \
    -d '{"email":"spoof@no7.ai","password":"wrong"}'
done
sqlite3 storage/db/no7.sqlite3 \
  "SELECT key, failures FROM login_throttle WHERE key LIKE 'spoof@no7.ai|%';"
#  ต้องได้ "แถวเดียว" ที่ key ลงท้ายด้วย IP จริงของผู้เรียก ไม่ใช่ 3 แถวตาม header ที่ปลอม
```

### 13.3 สิ่งที่ระบบใส่ให้ทุก response

| header | ค่า | กันอะไร |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; … frame-ancestors 'none'` | XSS ที่ขโมย token ใน `localStorage` |
| `X-Frame-Options` | `DENY` | clickjacking หน้าเทรด |
| `X-Content-Type-Options` | `nosniff` | MIME sniffing |
| `Referrer-Policy` | `no-referrer` | รั่ว path/โทเคนผ่าน referrer |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=()` | ฟีเจอร์ที่ไม่ใช้ |
| `Strict-Transport-Security` | `max-age=15552000; includeSubDomains` | downgrade หลังเคยเข้า HTTPS (เฉพาะเมื่อคำขอมาแบบ HTTPS) |

ตั้ง `NO7_CSP_MODE=report` ถ้า UI บางส่วนพังหลัง deploy (header จะกลายเป็น Report-Only
ไม่บล็อกอะไร แต่ยังรายงานใน console) หรือ `off` เมื่อจำเป็นจริง ๆ

### 13.4 พื้นฐานอื่น

- อย่าเปิดพอร์ต 8000 สู่อินเทอร์เน็ตโดยไม่มี reverse proxy + TLS + auth
- `NO7_JWT_SECRET` ต้องไม่ซ้ำกับระบบอื่น และไม่เข้า git — `/api/system/health` บอก
  `jwt_secret_from_env: false` ถ้ายังใช้ secret สำรองในโค้ด (เท่ากับใครรู้โค้ดก็ปลอม token ได้)
- MT5 password อยู่ใน `.env` เท่านั้น (ห้าม hardcode ใน MQL5 หรือ Python)
- ทุกคำสั่งถูก audit (`actor`, `action`, `detail`) — ตรวจได้ที่หน้า System
