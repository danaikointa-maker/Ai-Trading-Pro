# Runbook — ตั้งค่าและดูแลระบบ

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

```bash
# rebuild dashboard หลังแก้ frontend
cd apps/web-dashboard && npm run build

# dev server (proxy /api และ /ws ไป backend)
cd apps/web-dashboard && NO7_BACKEND=http://127.0.0.1:8000 npm run dev   # :5173

# tests
python3 -m pytest tests/ -q

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

# 2) ดูว่ามี tick อะไรอยู่ ครอบคลุมแค่ไหน และเป็นของจริงหรือของจำลอง
curl -s localhost:8000/api/datasets/ticks/status -H "Authorization: Bearer $TOKEN" | jq

# 3) รัน backtest — ใช้ tick อัตโนมัติ; เทียบกับโหมดเดิมได้ด้วย use_ticks=false
curl -s localhost:8000/api/backtests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"symbol":"XAUUSD","bars":6000,"use_ticks":true,"snapshot_id":"DS-XXXXXXXXXX"}'
```

อ่านผล: `diagnostics.intra_bar.bars_settled_by_ticks` = จำนวนแท่งที่ตัดสินด้วย tick จริง,
`bars_without_ticks` = จำนวนแท่งที่ยังใช้สมมติฐาน SL-ก่อน, และ `dataset.ticks.rows` = จำนวน tick ที่โหลด

**ถ้าต้องการทดสอบเฉพาะไปป์ไลน์โดยยังไม่มีไฟล์จริง**: `scripts/reconstruct_ticks.py` สร้าง tick
จากแท่ง M1 (ติดธง `reconstruction` ใน manifest) — ห้ามใช้ตัวเลขจากโหมดนี้ตัดสินใจเทรด

## 11. PWA / ติดตั้งเป็นแอป (มือถือ/เดสก์ท็อป)

```bash
cd apps/web-dashboard && npm run build      # ต้อง build ก่อน; public/ ถูกคัดลอกเข้า dist/
.venv/bin/python scripts/make_pwa_icons.py  # สร้างไอคอนใหม่ (ไม่ต้องใช้ Photoshop/ Pillow)
curl -s localhost:8000/manifest.webmanifest | jq '{name,start_url,display,icons:[.icons[].sizes]}'
curl -sD - -o /dev/null localhost:8000/sw.js | grep -i 'cache-control\|service-worker-allowed'
curl -s localhost:8000/sw.js | grep "const VERSION"   # ต้องเป็น hash 12 ตัว ไม่ใช่ __NO7_VERSION__
```

- เปิดจากมือถือแล้วเลือก **Add to Home Screen / ติดตั้งแอป** → เปิดแบบ standalone
- ออฟไลน์: เปิดแอปได้ (shell ถูกแคช) แต่ขึ้นแถบ "ออฟไลน์" และไม่มีข้อมูลใหม่ — service worker
  **ไม่แคช** `/api/*` หรือ `/ws` โดยตั้งใจ
- deploy build ใหม่: ไม่ต้องแก้อะไร — `/sw.js` ที่เสิร์ฟมี cache name ตาม hash ของ `index.html`
  เบราว์เซอร์จะได้ worker ใหม่ตอนเปิดครั้งถัดไป (cache เก่าถูกลบใน `activate`)
- ถ้าอยากล้าง cache ทั้งหมดระหว่าง debug: DevTools → Application → Service Workers → Unregister + Clear storage
- dev (vite 5173) **ไม่มี** service worker — การทดสอบ PWA ต้องใช้ build + uvicorn เท่านั้น

## 12. เชื่อม MT5 ผ่าน EA bridge (ไม่ต้องรันเซิร์ฟเวอร์บน Windows)

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

## 13. ความปลอดภัย

- อย่าเปิดพอร์ต 8000 สู่อินเทอร์เน็ตโดยไม่มี reverse proxy + TLS + auth
- `NO7_JWT_SECRET` ต้องไม่ซ้ำกับระบบอื่น และไม่เข้า git
- MT5 password อยู่ใน `.env` เท่านั้น (ห้าม hardcode ใน MQL5 หรือ Python)
- ทุกคำสั่งถูก audit (`actor`, `action`, `detail`) — ตรวจได้ที่หน้า System
