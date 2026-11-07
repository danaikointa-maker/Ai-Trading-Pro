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
| `services.feed = "exhausted"` | ข้อมูล replay เดินจนจบไฟล์แล้ว (clock หยุด, ไม่มีออเดอร์ใหม่) → นำเข้าไฟล์ที่ยาวขึ้นหรือเปิด `replay.loop` |
| โมเดลขึ้น "approval expired" | approval ถูกให้ด้วยกฎเวอร์ชันเก่า → กดเทรนใหม่ (`POST /api/forecast/train`) เพื่อประเมินด้วยกฎปัจจุบัน |
| `401` ทุก endpoint | ไม่ได้ส่ง `Authorization: Bearer` หรือ `security.require_auth` เปิดอยู่แต่ไม่มี token |
| สั่งออร์เดอร์แล้วได้ 400 | เป็นพฤติกรรมที่ถูกต้อง — ดู `detail.blockers` เช่น news lockout/spread/เพดานไม้ |
| `spread ... exceeds max` | ตลาดผันผวนหรือโบรกเกอร์ widen; เพิ่ม `max_spread_points` เฉพาะเมื่อเข้าใจความเสี่ยง |
| Full Auto กดไม่ได้ | ต้อง `NO7_ALLOW_FULL_AUTO=true` + toggle ในหน้า Risk + โมเดล approved + บัญชี demo |
| โมเดลขึ้น `UNVALIDATED` | metric ไม่ผ่านเกณฑ์ OOS — อย่า override, ปล่อยให้ใช้ค่าฐานสถิติ |
| `/api/market/candles` ตอบ 422 | `limit < 20` (ข้อจำกัดของ endpoint) |
| PyJWT เตือน key สั้น | ตั้ง `NO7_JWT_SECRET` ≥ 32 ตัวอักษร |

## 6. ความปลอดภัย

- อย่าเปิดพอร์ต 8000 สู่อินเทอร์เน็ตโดยไม่มี reverse proxy + TLS + auth
- `NO7_JWT_SECRET` ต้องไม่ซ้ำกับระบบอื่น และไม่เข้า git
- MT5 password อยู่ใน `.env` เท่านั้น (ห้าม hardcode ใน MQL5 หรือ Python)
- ทุกคำสั่งถูก audit (`actor`, `action`, `detail`) — ตรวจได้ที่หน้า System
