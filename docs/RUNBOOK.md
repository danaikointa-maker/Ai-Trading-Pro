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

## 7. รันได้ทีละโพรเซสเท่านั้น (single-writer)

runtime (tick, signal, order) ใช้ **lease** ในตาราง `kv` (`runtime_lease`) — โปรเซสเดียวเท่านั้นที่ขับเคลื่อนได้
ถ้าเปิดโปรเซสที่สองบนฐานข้อมูลเดียวกัน:

- `/api/system/health` → `status: degraded`, `services.runtime: "blocked (blocked)"`, `runtime_lease.owner` = เจ้าของตัวจริง
- log มี `runtime-lease: another No7 runtime already owns this database (...)`
- หน้า `/system` ขึ้นป้าย `blocked by <owner>`

อย่าใช้ `uvicorn --workers N` กับ build นี้: worker ที่สองจะไม่เทรด (ซึ่งปลอดภัย) แต่ก็ไม่ได้ข้อมูลสดของตัวเอง
ถ้าจำเป็นต้องมีหลายโปรเซสจริง ๆ ให้ตั้ง `NO7_ALLOW_MULTI_RUNTIME=1` **เฉพาะเมื่อ** ตัวที่ไม่ใช่เจ้าของเปิดอ่านอย่างเดียว
และเข้าใจว่าออเดอร์อาจซ้ำได้ (ระบบจะขึ้น `shared` + บันทึก error ไว้)

heartbeat ทุก 5 วินาที, ถือว่า lease ตายเมื่อเงียบเกิน 30 วินาที → เปิดใหม่ได้ทันทีแม้โดน `kill -9`

## 8. ความปลอดภัย

- อย่าเปิดพอร์ต 8000 สู่อินเทอร์เน็ตโดยไม่มี reverse proxy + TLS + auth
- `NO7_JWT_SECRET` ต้องไม่ซ้ำกับระบบอื่น และไม่เข้า git
- MT5 password อยู่ใน `.env` เท่านั้น (ห้าม hardcode ใน MQL5 หรือ Python)
- ทุกคำสั่งถูก audit (`actor`, `action`, `detail`) — ตรวจได้ที่หน้า System
