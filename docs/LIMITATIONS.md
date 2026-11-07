# Limitations & Honest Status

เอกสารนี้เขียนขึ้นเพื่อกันความเข้าใจผิดก่อนเอาเงินจริงเข้าไปเกี่ยวข้อง
ทุกข้อคือสิ่งที่ **ยังไม่จริง** หรือ **ยังไม่ครบ** ใน V1 นี้

- **ค่าเริ่มต้นของ dashboard คือ feed จำลอง** (seed 7) — พิสูจน์ได้ว่าไปป์ไลน์ถูก ไม่ได้บอกว่าโมเดลมี edge
  มีสองทางที่จะวัดของจริง (ดู `docs/DATA.md`):
  - offline: `scripts/evaluate_dataset.py` บนข้อมูลที่นำเข้า
  - live: ตั้ง `market_data.feed_mode: replay` ให้ทั้งระบบเดินบนแท่งที่นำเข้า
    (เริ่มใช้ได้แล้ว แต่ยังมีข้อจำกัดตามรายการด้านล่าง)
- replay ยังไม่เทียบเท่า tick data: ราคาระหว่างแท่งเดินตามเส้นทางที่กำหนด (open → close)
  อยู่ในกรอบ high/low ของแท่งนั้น → การชน SL/TP ภายในแท่งยังเป็นการประมาณ
  และ spread ต่อแท่งยังมาจาก `spread_typical_points` ของ symbol ไม่ใช่ spread จริงรายแท่ง
- replay หยุดที่ท้ายไฟล์ (ไม่ต่อแท่งใหม่เอง) — clock หยุด, tick แช่ที่ราคาปิดแท่งสุดท้าย,
  `services.feed = "exhausted"` และ gate จะไม่เปิดออเดอร์ใหม่

## 1. ข้อมูลตลาด

- ค่าเริ่มต้นใช้ **simulated feed** (GBM + regime switch + news shock, seed 7)
  ตัวเลขทุกตัวในภาพรวมจึงเป็นตัวอย่าง ไม่ใช่ราคาตลาดจริง
- เมื่อตั้ง `NO7_FEED_MODE=mt5` จะอ่านราคาจากเทอร์มินัลจริง แต่ยังไม่ได้ทดสอบกับ Connext
  ในสภาพตลาดจริง (ต้องมี Windows + terminal + บัญชี Demo)
- **ยังไม่มี tick data จริง** สำหรับ backtest → ใช้ M1 ที่ resample เป็น M5/M15/H1/H4
  การจำลองการชน SL/TP ภายในแท่งจึงต้องเดา (เลือก stop ก่อน target แบบ conservative)

## 2. Backtest

- **ยังไม่ reproducible 100%**: ประวัติถูก generate ตามเวลาปัจจุบัน ทำให้รันซ้ำแล้วหน้าต่างข้อมูล
  เลื่อนไปเล็กน้อย (งานถัดไป: snapshot dataset ลง `storage/datasets` แล้วผูกกับ report)
- ตอนนี้ **ไม่ใช้ edge ของโมเดล ML** ใน backtest (path probability เป็น rule proxy)
  → ตัวเลข backtest จึงวัด "กฎ + risk" ไม่ใช่วัด "คุณภาพโมเดล"
- ยังไม่มี Monte Carlo / slippage distribution / หลายโบรกเกอร์พร้อมกัน
- ผลล่าสุดบน feed นี้: ไม้ไม่ถึง 15 ไม้ใน 6,000 แท่ง (no-trade > 99%) — ตัวเลขสถิติ
  จึงยัง **สรุปอะไรไม่ได้** และไม่ควรตีความว่า "กลยุทธ์ชนะ"

## 3. โมเดล

- LightGBM ผ่านเกณฑ์เฉพาะบาง horizon; horizon ที่ไม่ผ่านถูกทำเครื่องหมาย `UNVALIDATED`
  และระบบใช้ค่าฐานสถิติแทน (ดูได้ที่หน้า Forecast)
- Isotonic calibration ฝึกบนช่วง calibration ที่แยกจาก test แต่ยังไม่มี forward test ระยะยาว
- การอนุมัติใช้ walk-forward (ฝึกใหม่ทุก fold, ≥75% ของ fold ต้องผ่านเกณฑ์เดียวกัน) ลดการอนุมัติเพราะโชค
  แต่ยังประเมินบน **feed จำลอง** — ตัวเลขจึงบอกได้แค่ว่าไปป์ไลน์ถูก ไม่ได้บอกว่าโมเดลมี edge จริงในตลาด
- fold ประเมินเฉพาะ classification (directional + Brier); quantile band ยังประเมินจาก split เดียว
- ยังไม่มี Temporal CNN / ensemble — จะเพิ่มเมื่อพิสูจน์ด้วย walk-forward ว่าเหนือกว่า

## 4. Execution / MT5

- **MQL5 EA ยังไม่ถูกเขียน** → ถ้า AI/เซิร์ฟเวอร์ดับระหว่างมีไม้เปิด
  SL/TP ที่ส่งไปแล้วจะอยู่ที่โบรกเกอร์ แต่การจัดการแบบ trailing/partial ในเทอร์มินัลจะหยุด
  (ข้อกำหนด "EA ต้องดูแล SL/TP ในเทอร์มินัล" ยังไม่ครบ)
- ยังไม่ได้ทดสอบ order flow กับโบรกเกอร์จริง (filling mode, stops level, freeze level,
  partial fill, requote) — โค้ดมี verify-after-send และ idempotency แล้ว แต่ยังไม่ผ่านสนามจริง
- Reconcile มีอยู่แต่ยังไม่ได้ทดสอบกับ position ที่ถูกแก้จากมือในเทอร์มินัล

## 5. ระบบโดยรวม

- SQLite เหมาะกับคนเดียว/เครื่องเดียว ยังไม่รองรับ multi-user จริง
- ยังไม่มี role/permission ละเอียด (มี JWT + `owner` role เดียว)
- Telegram/LINE/Web Push ยังไม่ต่อ (มี in-app alert แล้ว)
- Mobile PWA ยังว่าง
- มี rate limiting ในตัวแล้ว (token bucket ต่อผู้ใช้/IP: order 10/นาที, explain 20/นาที,
  backtest 6/นาที, train 2/ชั่วโมง, อื่น ๆ 300/นาที) — **รอบ 19** เพิ่ม store ที่แชร์ได้:
  `memory` (ต่อโปรเซส, ค่าเริ่มต้น) / `sqlite` (worker บนเครื่องเดียว, write ต่อคำขอที่ถูกจำกัด) /
  `redis` (ข้ามเครื่อง, Lua atomic, key มี TTL)
  - วัดจริง: 2 worker + memory → limit 6/นาที ปล่อยผ่าน **7**; 2 worker + sqlite → **6 เท่าพอดี**
  - Redis: **ยังไม่ได้ทดสอบกับ redis-server จริง** ในเครื่องนี้ (ไม่มี binary) — ทดสอบผ่าน
    fakeredis ที่รัน Lua เดียวกัน; เมื่อมี `NO7_REDIS_URL` จริง เทสต์ชุดเดียวกันจะยิงของจริง
  - ถ้า Redis ล่มกลางทาง ระบบ **จำกัดด้วย bucket ในโปรเซสต่อไป** + `degraded++` +
    header `x-ratelimit-degraded` (เลือกทางนี้แทนการปล่อยผ่านโล่ง ๆ หรือทำให้ระบบล่ม)
  - ตัวนับใช้เวลาของแอป (ไม่ใช่ Redis TIME) → ต้องมี NTP; clock skew ทำให้ refill คลาดเคลื่อน
    ไม่ทำให้ token หายหรือเพิ่ม
  - ยังไม่มี quota ต่อ IP แบบ distributed สำหรับ WebSocket (จำกัดเฉพาะ HTTP) และไม่มี WAF
- ตัว runtime เอง (simulator, scheduler, websocket hub) ออกแบบสำหรับ **โปรเซสเดียว**
  ดังนั้น `--workers N` ยังไม่ใช่โหมดที่รองรับ: store แบบ sqlite เป็นการวางพื้นฐานให้โควตาร่วม
  ไม่ใช่การประกาศว่า multi-worker พร้อมใช้

## 6. กฎหมาย / ความเสี่ยง

- Connext ระบุเองว่า licence FSA (St. Vincent & the Grenadines) **ไม่ได้กำกับ Forex โดยตรง**
- ธปท. เตือนเรื่องแพลตฟอร์ม Forex ต่างประเทศที่ไม่ได้รับอนุญาต และความเสี่ยงจากการเก็งกำไรค่าเงิน
- ก่อนฝากเงินจริง: ตรวจสอบสถานะทางกฎหมาย, การชดเชยความเสียหาย, การถอนเงิน,
  และภาษีในประเทศไทยกับผู้เชี่ยวชาญ — ระบบนี้ไม่ให้คำแนะนำทางกฎหมาย
- **เริ่มที่ Demo เท่านั้น** และอย่าเปิด Full Auto จนกว่าจะมีผล paper trading ต่อเนื่องที่วัดได้

## 7. สิ่งที่ระบบทำได้จริงในตอนนี้ (เพื่อความชัดเจน)

- อ่าน/วิเคราะห์ตลาดหลาย timeframe และอธิบายเหตุผลเป็นภาษาไทยได้
- สร้างแผนเทรดที่มี SL/TP/partials/lot สอดคล้องกับ spec ของโบรกเกอร์
- ปฏิเสธการเทรดพร้อมเหตุผลที่วัดได้ และบันทึกไว้
- ส่งคำสั่งไปยัง broker adapter (paper) ตรวจสอบผล และเก็บ audit trail
- ทดสอบย้อนหลังพร้อมต้นทุน และรายงาน `no_trade_rate` อย่างตรงไปตรงมา

## 8. ตรวจสูตรรอบล่าสุด (สิ่งที่ยัง "ประมาณ" อยู่)

รอบนี้ไล่แก้บั๊กสูตร 18 จุด (รายการเต็มอยู่ใน [`MATH.md`](MATH.md) ข้อ 10) แต่มีสิ่งที่ยังไม่เป๊ะโดยเจตนา:

- ต้นทุน spread/slippage ถูกคิดที่ราคาเข้าและรายงานเป็นเงินแล้ว (`total_costs`) แต่ SL/TP ยังตัดสินจากราคา mid ของแท่ง ไม่ใช่ bid/ask รายแท่ง
- ถ้าแท่งเดียวชนทั้ง SL และ TP จะถือว่า stop ชนก่อน (conservative) — อาจทำให้ผลลบกว่าความจริงเล็กน้อย
- swap ถูกคิดแล้วทั้งใน paper และ backtest (คืนละครั้งตามเวลา UTC, พุธ ×3) รองรับ money / points / percent
  — MT5 mode 7/8 (reopen) ยังไม่รองรับ จึงรายงานเป็น 0 แทนการเดา (mode 5/6 = percent รองรับแล้ว
  โดย mode 6 คิดบนราคา ณ วันคิดแทนราคาเปิดโพซิชัน)
- ดอกเบี้ยโหมด percent ใช้ฐาน 360 วันคงที่ (โบรกเกอร์บางรายใช้ 365) — ระบุไว้ใน assumption ของผล backtest
- สกุลเงินกำไรที่ไม่ใช่ USD: แปลงเป็นสกุลบัญชีแล้วด้วย `quote_to_account_rate` ในทุกเอนจิน
  (backtest / paper / MT5 offline estimate / risk notional) ✅ — แต่ rate มาจาก ticker ที่มีอยู่
  ณ ตอนนั้น ถ้า resolve ไม่ได้ ระบบจะบล็อกการคำนวณ lot แทนการเดา
- Sharpe ที่ annualise จากแท่ง 5 นาทีจะสูงเกินจริงเมื่อมีไม้ไม่กี่ไม้
- ราคา fill จริงอาจต่างจาก plan (slippage) ทำให้ risk จริงต่างจากที่คำนวณ — ระบบวัดและเตือนแล้ว
  (`risk_check` ในผลออเดอร์ + audit `risk.fill_drift`) แต่ไม่ปรับ SL ตามให้อัตโนมัติ เพราะ SL ผูกกับโครงสร้างราคา

## ข้อมูล tick (รอบ 13–16)

- **ยังไม่มีไฟล์ tick จริงจากผู้ใช้** — ตัว import/โหลด/ตัดสินลำดับในแท่งพร้อมใช้และทดสอบแล้ว
  แต่ข้อมูลที่รันในเครื่องนี้เป็น **reconstruction** จากแท่ง M1 (`scripts/reconstruct_ticks.py`)
  ซึ่ง manifest ติดธง `"reconstruction": true` — ลำดับ high/low ภายในแท่งยังเป็นการเดา ไม่ใช่ข้อมูลจริง
- บนข้อมูลทดสอบ (XAUUSD 6000 แท่ง M1, 24,000 tick, 3 ไม้) **ไม่มีแท่งไหนชนทั้ง SL และ TP ในแท่งเดียว**
  → tick ไม่เปลี่ยนผลลัพธ์เลย (`bars_settled_by_ticks: 0`, รายงานระบุไว้ตรง ๆ)
  ความต่างจะเกิดตอนตลาดเร็ว/สต็อปแคบ เช่นช่วงข่าว — วัดจากข้อมูลจริงได้เมื่อมีไฟล์ tick
- ถ้า tick ในแท่งบอกว่า TP มาก่อน แต่ยังชน SL ในแท่งเดียวกัน ระบบจอง TP ที่ถึงก่อนแล้วปิดที่เหลือที่ SL
  (อนุรักษ์นิยมหลังจุดที่รู้แน่แล้ว) — ไม่ได้แกล้งทำเป็นว่ารอด
- **storage ระดับล้านแถวต่อวัน: ทำแล้ว (รอบ 16)** — แยกไฟล์ต่อวัน UTC เป็น parquet
  (`.csv.gz` ถ้าไม่มี pyarrow) + manifest ต่อวัน; `TickBook` อ่านแบบ lazy ด้วย LRU 4 วัน
  วัดจริง: import 1,008,000 แถว/12 วัน = 14.9s, ไฟล์รวม 8.9MB; เปิด book = 0.00s (อ่าน manifest),
  query 1 วัน = 0.03s และอ่านไฟล์เดียวจาก 12 — layout ไฟล์เดียวแบบเดิมยังใช้ได้ แต่กิน
  memory ตามขนาดไฟล์ (1M แถว ≈ +60MB, 30M แถว ≈ +1.8GB) จึงเก็บไว้เพื่อ reproduce ของเก่าเท่านั้น
- ยังไม่มี spread/slippage ต่อ tick: การจองต้นทุนยังใช้ spread คงที่ตาม config + slippage points
- manifest คือ index ที่เชื่อถือได้ของ layout daily: ถ้าแก้/ลบไฟล์ด้วยมือ ระบบจะอ่านไฟล์ที่เหลือ
  ใหม่หนึ่งครั้งต่อไฟล์ (ผลไม่เปลี่ยน แต่ช้าครั้งแรก) และวันที่มีไฟล์แต่ไม่มีใน manifest
  จะไม่ถูกนับใน `rows` ของ status
- `POST /api/datasets/ticks/prune` ลบได้จริงและกู้คืนไม่ได้ (ไม่มีถังขยะ) — ค่าเริ่มต้น
  ปฏิเสธวันที่มี backtest อ้างถึง แต่ `force=true` ลบได้
- `use_ticks: true` โดยไม่มีไฟล์ = ทำงานเหมือนเดิม (ไม่ error) แต่ `diagnostics.intra_bar.mode` = `conservative`
- tick ไม่ได้ใช้กับ paper/live execution หรือ training เลย — ใช้เฉพาะใน backtest

## EA bridge / MQL5 (รอบ 14)

- **EA `.mq5` ยังไม่เคย compile หรือรันกับ MT5 จริง** ในเครื่องนี้ (ไม่มี Windows/terminal) —
  โปรโตคอลถูก pin ด้วย `tests/test_bridge.py` (26 tests) และ exercised ด้วย `scripts/run_bridge_sim.py`
  แต่การคอมไพล์/รันครั้งแรกต้องทำบนเครื่องคุณ
- **TLS (รอบ 18)**: uvicorn อ่าน cert ได้เองผ่าน `NO7_TLS_CERT/NO7_TLS_KEY` (มีใน `scripts/run.sh`)
  หรือจะวาง nginx/caddy ข้างหน้าก็ได้ — แต่ระบบ **ไม่ได้** ออก/ต่ออายุ certificate ให้
  (Let's Encrypt ต้องมีโดเมนจริง) ดังนั้นใน LAN ให้ใช้ self-signed หรือ VPN; ถ้าไม่ใส่ TLS เลย
  token ยังวิ่ง plaintext ห้ามเปิดข้ามอินเทอร์เน็ต
- **perimeter (รอบ 18)**: มี CSP (enforce), nosniff, frame DENY, referrer no-referrer,
  Permissions-Policy, HSTS เฉพาะเมื่อมาทาง HTTPS, CORS เป็น allowlist (ค่าเริ่มต้น = same-origin)
  และตัด IP ที่ปลอม `X-Forwarded-*` ได้ — แต่:
  - CSP ของหน้าแอปไม่อนุญาต CDN เลย; `/api/docs` (Swagger) ได้ policy ผ่อนกว่าเฉพาะ path นั้น
    เพราะโหลด bundle จาก jsDelivr
  - CSP ถูกเขียนให้ตรงกับ bundle ที่ build แล้ว (script/style จาก origin เดียว, ws สำหรับ live feed);
    **ยังไม่ได้ทดสอบในเบราว์เซอร์จริง** ในเครื่องนี้ ถ้า UI ส่วนไหนพังให้ตั้ง `NO7_CSP_MODE=report`
  - ไม่มี WAF, bot/IP reputation, หรือ DDoS protection — rate limit เป็น token bucket ต่อผู้ใช้/IP
  - `X-Forwarded-*` เชื่อเฉพาะ peer ใน `NO7_TRUSTED_PROXIES`; ถ้ารัน uvicorn เอง **ต้องใส่
    `--no-proxy-headers`** ไม่งั้น uvicorn จะ rewrite client/scheme ด้วย allowlist ของตัวเอง
    (ค่าเริ่มต้น loopback) ก่อนถึงแอป
  - `jwt_secret_from_env: false` ใน health = ยังใช้ secret สำรองในโค้ด → ตั้ง `NO7_JWT_SECRET`
    ก่อนเปิดให้ใครใช้ (token ปลอมได้ถ้ารู้ secret นี้)
- state ของ bridge อยู่ในตาราง `bridge_*` ของฐานข้อมูล (แชร์ข้าม worker) แต่ **รีสตาร์ทเซิร์ฟเวอร์ = คิวที่ยังไม่ส่งหาย**
  (session ยังอยู่แต่ heartbeat เก่า → EA register ใหม่ใน 1 รอบ) — ตั้งใจไม่กู้คิวเก่า
- หลาย worker บน SQLite ไฟล์เดียวใช้ได้จริง (claim เป็น conditional UPDATE + WAL) แต่ยังไม่ได้ทดสอบกับ
  Postgres/Redis: ถ้าย้ายที่เก็บต้องคง semantics "ส่งครั้งเดียว" ไว้ให้ได้
- multi-worker startup: `uvicorn --workers 2` เคยพังเพราะสองโปรเซส insert demo user พร้อมกัน (แก้แล้วด้วย
  `INSERT OR IGNORE` + migration ทน `duplicate column`) — ยังไม่มี distributed lock ตอน bootstrap
- ไม่มี background sync: คำสั่งที่ค้างตอนเซิร์ฟเวอร์ปิดหายไป (ไม่มีการกู้คิว) — ตั้งใจ เพราะคำสั่งเทรดเก่าไม่ควรถูกส่งย้อนหลัง
- EA จำกัดที่ symbol ที่ใส่ใน `InpSymbols`, M1 rates ที่ `InpRatesBars` และกรองเฉพาะโพซิชัน magic `70707`
  หรือคอมเมนต์ที่มี `no7` (โพซิชันของ EA ตัวอื่นจะไม่ถูกแตะ)
- `positions()` คือ snapshot ล่าสุดจาก EA ไม่ใช่ streaming: อัตราการอัปเดต = poll interval (ปกติ 1s)
- ยังไม่มี hedging/netting handling พิเศษ, ไม่มี partial-fill ต่อคำสั่ง (โบรกเกอร์คืน volume ที่ fill มาทั้งก้อนในผลลัพธ์เดียว)
- ไม่มีการยืนยัน two-way ว่า EA ใช้เวอร์ชันไหน: `terminal.build` แสดงใน status แต่เซิร์ฟเวอร์ไม่ได้บังคับเวอร์ชัน

## PWA / ออฟไลน์ (รอบ 13, 17)

- ติดตั้งเป็นแอปได้ (manifest + ไอคอน 192/512/maskable + apple-touch-icon) และเปิดหน้าเดิมได้ตอนออฟไลน์
  แต่ **ข้อมูลไม่ถูกแคชเลย**: `/api/*` และ `/ws` ถูกกันออกจาก service worker โดยเจตนา — ออฟไลน์ = ขึ้นแถบเตือน
  ไม่ใช่โชว์ราคาเก่าเป็นราคาปัจจุบัน
- ไม่มี background sync / push: คำสั่งซื้อที่กดตอนออฟไลน์จะ **ไม่** ถูกเก็บไปส่งทีหลัง (จะ error ตรง ๆ) —
  ตั้งใจไม่ทำ เพราะคำสั่งเทรดที่ส่งย้อนหลังด้วยราคาเก่าอันตรายกว่าการที่ผู้ใช้ต้องกดใหม่
- service worker ลงทะเบียนเฉพาะ production build (`import.meta.env.PROD`); dev server ไม่มี SW
- cache name มาจาก hash ของ `dist/index.html` ที่เซิร์ฟเวอร์ inject ตอนส่ง `/sw.js` → build ใหม่ = cache ใหม่
  และ cache เก่าถูกลบตอน activate; แต่ถ้าเบราว์เซอร์ยังไม่ reload หลัง deploy หน้าเก่าจะยังอยู่จนกว่าจะปิดแท็บ
- **รอบ 17 — install polish**: มีแถบเชิญติดตั้งของแอปเอง (`beforeinstallprompt`), มีแถบ
  "มีเวอร์ชันใหม่ → รีเฟรช" (worker **ไม่** `skipWaiting` เองแล้ว), แยกข้อความ
  "ออฟไลน์" กับ "เซิร์ฟเวอร์ไม่ตอบ" พร้อมเวลาข้อมูลล่าสุด, และหน้า /system แสดงสถานะ
  service worker + `storage.persist()`/`estimate()`
- iOS/Safari ยังไม่มี prompt API — แอปขึ้น **คำใบ้** (แชร์ → เพิ่มไปที่หน้าจอโฮม) แทนปุ่มติดตั้ง
- `navigator.storage.persist()` เป็นคำขอ ไม่ใช่สิทธิ์: Firefox/Safari อาจปฏิเสธ และเบราว์เซอร์
  ลบข้อมูลเองได้เมื่อพื้นที่ใกล้เต็ม — ไม่มีการรับประกันว่าแคชเชลล์จะอยู่ตลอด
- ไม่มี `screenshots` ใน manifest (ต้องใช้ภาพหน้าจอจริงจากเบราว์เซอร์ ซึ่งเครื่องนี้ไม่มี
  headless browser ตามกติกาทดสอบ) — Chrome จึงใช้ UI ติดตั้งแบบพื้นฐาน
- ไม่มี `apple-touch-startup-image` (splash screen iOS) เพราะต้องสร้างภาพหลายขนาดต่อรุ่นเครื่อง
- ไม่มี offline fallback สำหรับหน้า `/api/docs` (Swagger) — เป็น HTML จาก CDN, ต้องต่อเน็ต

## การแจ้งเตือนภายนอก

- Telegram/LINE/webhook ถูกทดสอบด้วย transport ปลอมในเทสต์ (ไม่มีการยิงเน็ตออกจริงระหว่างเทสต์)
  การยิงจริงยืนยันได้ด้วย `POST /api/system/alerts/test` บนเครื่องที่ต่อเน็ตได้เท่านั้น
- ข้อความออกนอกเครื่องมีข้อมูลการเทรด (symbol, pnl, เหตุผล) — เปิดเมื่อเข้าใจว่าใครเห็นข้อความเหล่านี้
- ยังไม่มี retry/queue: ถ้าเน็ตล่มในจังหวะนั้น ข้อความนั้นหาย แต่ **in-app ยังอยู่** และสถานะ `failing` จะค้างให้เห็น

## หลายโปรเซส (cluster)

- โค้ด path ของ `replica` ถูกทดสอบกับ stub client (`set/get/ping`) และกับ store ในโปรเซส
  — **ยังไม่เคยรันกับ Redis server จริงในสภาพแวดล้อมนี้** (ไม่มี redis-server ในแซนด์บ็อกซ์)
  สิ่งที่ยืนยันได้แล้วคือ: TTL, การอ่าน/เขียน JSON, การถอยกลับพร้อมเหตุผลเมื่อ redis ใช้ไม่ได้
- replica เสิร์ฟเฟรมที่อาจเก่าได้ถึง `state_ttl_seconds` (ค่าเริ่มต้น 10s) — payload บอก
  `frame_age_seconds` ทุกครั้ง ไม่ใช่ปล่อยให้เข้าใจว่าเป็นข้อมูลสด
- leader ตาย → เฟรมหมดอายุเองใน 10s และ lease หมดอายุใน 30s; โปรเซสที่รออยู่จะ **ยึดงานต่อเอง**
  (hot standby, ทดสอบสดแล้ว: ปิด leader → ตัวสำรองกลายเป็น leader ภายใน ~5 วินาที)
  ข้อจำกัดที่เหลือ: ถ้าไม่มีโปรเซสสำรองรันอยู่เลย ก็ยังไม่มีใครรับงานต่อ; และ state ที่อยู่ในหน่วยความจำ
  ของ leader (ประวัติ, buffer) ไม่ถูกย้ายไปให้ตัวใหม่ — ตัวใหม่เริ่มจาก DB
- การแย่ง lease กันพร้อมกันมีเทสต์ (สองเธรด, ผู้ชนะคนเดียว) แต่ยังไม่มีการทดสอบด้วยโปรเซสจริงหลายตัว
  พร้อมกันบนเครื่องเดียวใน CI

## ผู้ใช้และสิทธิ์

- มี 3 role (admin/trader/viewer) และบังคับใช้จริงที่ฝั่งเซิร์ฟเวอร์ แต่ **ข้อมูลไม่ได้แยกตามผู้ใช้**:
  ทุกคนที่ล็อกอินเห็นพอร์ตเดียวกัน ไม่มี "บัญชีของฉัน" และไม่มี per-user audit isolation
- ไม่มี 2FA, ไม่มี SSO/OIDC, ไม่มี self-service password reset (admin ตั้งรหัสให้)
- ไม่มี session revocation list: ปิดบัญชีแล้ว token ถูกปฏิเสธทันที (เพราะอ่าน DB ทุก request)
  แต่ถ้าต้องการ "บังคับออกจากทุกอุปกรณ์" ต้องเปลี่ยนรหัสผ่านหรือปิด/เปิดบัญชี
- `require_auth: false` (โหมด dev) = ทุก request เป็น admin โดยปริยาย — อย่าใช้บนเครื่องที่แชร์
