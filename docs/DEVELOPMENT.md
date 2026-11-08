# Development — จะพัฒนาต่อยังไง

เอกสารนี้คือทางเข้าสำหรับ "เปิดเครื่องมาแล้วทำงานต่อ" — ติดตั้งยังไง, ลูปพัฒนาเป็นแบบไหน,
แก้ตรงไหนไปแตะไฟล์อะไร, เกตก่อนส่งงานคืออะไร, และงานถัดไปที่คุ้มทำที่สุดคืออะไร
(สถานะความจริงของระบบอยู่ที่ [`LIMITATIONS.md`](LIMITATIONS.md), วิธีดูแลตอนรันอยู่ที่ [`RUNBOOK.md`](RUNBOOK.md))

---

## 0. TL;DR

```bash
./scripts/dev_setup.sh      # venv + deps + .env + dashboard bundle (ครั้งแรก ~2 นาที)
./scripts/run.sh            # http://127.0.0.1:8000  →  demo@no7.ai / no7demo1234
./scripts/dev_check.sh      # เกตก่อน commit: ruff + 410 tests (~3 นาที)
```

ทั้งสามคำสั่งรันซ้ำได้เสมอ ไม่พังของเดิม

---

## 1. ติดตั้ง / กู้เครื่องที่ถูกล้าง

`./scripts/dev_setup.sh` ทำ 4 อย่าง แต่ละอย่างข้ามถ้ามีอยู่แล้ว:

| ขั้น | ได้อะไร | ข้ามเมื่อ |
|---|---|---|
| 1 | `.venv/` (ต้องการ Python ≥ 3.11) | มี `.venv/bin/python` แล้ว |
| 2 | `pip install -r requirements-dev.txt` (runtime + ruff + pyarrow + fakeredis) | — (เร็วเมื่อครบแล้ว) |
| 3 | `.env` จาก `.env.example` พร้อม `NO7_JWT_SECRET` สุ่มใหม่ | มี `.env` อยู่แล้ว (ไม่แตะของเดิม) |
| 4 | `apps/web-dashboard/dist/` (`npm install && npm run build`) | มี `dist/index.html` แล้ว (`--rebuild-ui` เพื่อบังคับ build) |

ออปชัน: `--no-ui` (ทำแค่ backend), `--rebuild-ui`, `PYTHON=python3.12 ./scripts/dev_setup.sh`

**สิ่งที่หายเมื่อเครื่อง/แซนด์บ็อกซ์ถูกล้าง** (ทั้งหมดอยู่ใน `.gitignore` — ไม่ได้อยู่ใน git):
`.venv/`, `node_modules/`, `apps/web-dashboard/dist/`, `.env`, `storage/*` (ฐานข้อมูล/โมเดล/รายงาน), `.tools/`
→ รัน `./scripts/dev_setup.sh` อีกครั้งก็กลับมาครบ **ยกเว้นข้อมูลใน `storage/`** ซึ่งสร้างใหม่ตอนบูต
(ฐานข้อมูลว่าง + demo user) — ถ้าอยากเก็บไว้ ให้ copy ออกนอก repo ก่อน

---

## 2. ลูปพัฒนาประจำวัน

```bash
# backend (เสิร์ฟทั้ง API และ dashboard ที่ build ไว้)
./scripts/run.sh                                  # :8000
NO7_PORT=8100 ./scripts/run.sh                    # พอร์ตอื่นเมื่อต้องรันสองตัว

# backend แบบ auto-reload ระหว่างแก้โค้ด
.venv/bin/python -m uvicorn services.api_gateway.app:app --reload --no-proxy-headers --port 8000

# frontend แบบ hot reload (proxy /api และ /ws ไป backend)
cd apps/web-dashboard && NO7_BACKEND=http://127.0.0.1:8000 npm run dev     # :5173

# ยังมีชีวิตและ payload ครบไหม
.venv/bin/python scripts/smoke.py --base http://127.0.0.1:8000

# token สำหรับยิง API ด้วยมือ
TOK=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
      -d '{"email":"demo@no7.ai","password":"no7demo1234"}' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOK" localhost:8000/api/system/health | python3 -m json.tool
```

ข้อควรรู้สองข้อ:

- **`--no-proxy-headers` ต้องมีเสมอ** — ถ้าไม่ใส่ uvicorn จะเขียน client IP/scheme ทับตาม
  `X-Forwarded-*` ก่อนที่แอปจะได้ตัดสินใจ ทำให้ policy ใน `netutil.py` ถูกข้าม (`scripts/run.sh` ใส่ให้แล้ว)
- **runtime เป็น single-writer** — โพรเซสที่สองจะขึ้นเป็น `replica` และรอ lease ของตัวแรก
  (`cluster.state_ttl_seconds: 10`, heartbeat เก่ากว่า 30s ถือว่าตาย) ดังนั้นตอนใช้ `--reload`
  โพรเซสใหม่อาจเป็น replica อยู่ไม่กี่วินาทีก่อนรับช่วง — ดูได้ที่ `/api/system/health → cluster.role`

---

## 3. เกตก่อน commit (ไม่ผ่าน = ไม่ส่ง)

```bash
./scripts/dev_check.sh              # 1) ruff --select F,E9  2) มี dist  3) pytest ทั้งชุด
./scripts/dev_check.sh --lint-only  # วินาทีเดียว ใช้ระหว่างแก้
./scripts/dev_check.sh tests/test_api.py -x
```

ตัวเลขอ้างอิงบนเครื่องพัฒนา (Python 3.11, 2 cores):

| ชุด | จำนวน | เวลา |
|---|---|---|
| ทั้งหมด (`pytest -q`) | 410 | ~2 นาที 50 วินาที |
| ตัดสองไฟล์ที่หนักที่สุด `--ignore=tests/test_backtest_engine.py --ignore=tests/test_model_validation.py` | 382 | ~55 วินาที |
| `tests/test_backtest_engine.py` | 11 | ~40 วินาที |
| `tests/test_model_validation.py` | 17 | ~35 วินาที |

ลูปที่แนะนำ: แก้ → ไฟล์เทสต์ที่เกี่ยวข้อง → ชุด 382 → ชุดเต็มก่อน commit

**เทสต์ไม่เคยแตะข้อมูลจริง** — `tests/conftest.py` ชี้ `NO7_DB_PATH`/`NO7_DATA_DIR`/… ไปที่ temp dir
และ fixture `settings` จะ assert ว่า path มีคำว่า `no7-tests-` อยู่ ถ้าเขียนเทสต์ใหม่ที่ต้องตั้ง env
ให้ตั้ง **ก่อน** เรียก `reload_settings()` เสมอ (settings ถูก cache)

**กฎเอกสาร:** เปลี่ยนพฤติกรรมเมื่อไหร่ ต้องอัปเดตเอกสารในคอมมิตเดียวกัน —
`README.md` (ตารางสถานะ), `docs/API.md` (สัญญา endpoint), `docs/RUNBOOK.md` (วิธีใช้/แก้ปัญหา),
`docs/MATH.md` (สูตร), `docs/LIMITATIONS.md` (สิ่งที่ยังไม่จริง)
ห้ามเขียนว่า "ทดสอบแล้ว" ถ้าไม่มีเทสต์หรือหลักฐานที่รันซ้ำได้ และต้องระบุเสมอว่าเป็นของจำลองหรือของจริง

---

## 4. แผนที่โค้ด — อยากแก้อะไร ไปที่ไหน

| อยากแก้ | ไฟล์หลัก | เทสต์ที่คุมอยู่ |
|---|---|---|
| endpoint / สัญญา HTTP | `services/api_gateway/routes/*.py` | `tests/test_api.py`, `tests/test_security.py` |
| สิทธิ์ viewer/trader/admin | `services/api_gateway/roles.py`, `deps.py` | `tests/test_roles.py` |
| JWT / login throttle | `services/api_gateway/auth.py` | `tests/test_auth.py` |
| rate limit + store ที่แชร์กัน | `services/api_gateway/ratelimit.py` | `tests/test_ratelimit.py`, `tests/test_ratelimit_shared.py` |
| leader/replica, frame bus | `services/api_gateway/cluster.py`, `state.py` | `tests/test_cluster.py`, `tests/test_runtime_lease.py` |
| ฟีดราคา / simulator / replay | `services/market_data/` | `tests/test_replay_feed.py`, `tests/test_realtime.py` |
| tick storage + ลำดับในแท่ง | `services/market_data/tick_store.py`, `ticks.py` | `tests/test_tick_store.py`, `tests/test_tick_data.py` |
| อินดิเคเตอร์ / โครงสร้างตลาด | `packages/indicators/`, `packages/market_structure/` | `tests/test_points_math.py`, `tests/test_zones.py` |
| กฎเข้าออก / โซน confluence | `packages/strategy_rules/`, `services/strategy_engine/` | `tests/test_strategy_generate.py`, `tests/test_zones.py` |
| คะแนนสัญญาณ / แผนเทรด | `services/strategy_engine/scoring.py`, `services/risk_engine/` | `tests/test_signal_execution.py`, `tests/test_risk_engine.py` |
| เพดานความเสี่ยง / kill switch | `services/risk_engine/` | `tests/test_risk_engine.py`, `tests/test_invariants.py` |
| ส่งคำสั่ง / idempotency / reconcile | `services/execution_gateway/` | `tests/test_signal_execution.py` |
| backtest + cost model + swap | `services/backtest_engine/` | `tests/test_backtest_engine.py`, `tests/test_swap.py`, `tests/test_mt5_swap_modes.py` |
| โมเดล / calibration / เกณฑ์อนุมัติ | `services/ai_forecast/` | `tests/test_model_validation.py` |
| แจ้งเตือน Telegram/LINE/webhook | `services/notification/notifier.py` | `tests/test_notify_channels.py`, `tests/test_notify_delivery.py` |
| EA bridge (MQL5 poll) | `services/bridge/`, `bridge/No7BridgeEA.mq5` | `tests/test_bridge.py` |
| โบรกเกอร์ / spec / paper fill | `integrations/brokers/` | `tests/test_currency.py`, `tests/test_api.py` |
| หน้าจอ dashboard | `apps/web-dashboard/src/views/*.vue`, `router.js` | `tests/test_pwa.py` (เสิร์ฟไฟล์จริงจาก `dist/`) |
| ค่าคอนฟิก / env | `config/*.yaml`, `packages/shared_schemas/settings.py` | `tests/test_api.py::…health`, `tests/test_security.py` |

---

## 5. สูตรสำเร็จ

### 5.1 เพิ่ม endpoint

1. เขียนใน `services/api_gateway/routes/<กลุ่ม>.py` (มี `router = APIRouter(prefix="/api/<กลุ่ม>")` อยู่แล้ว)
   ```python
   @router.get("/summary")
   def summary(runtime: TradingRuntime = Depends(get_runtime), user=Depends(current_user)):
       return {"ok": True}
   ```
   - `Depends(current_user)` **ทุก endpoint** — มันคือที่เดียวที่กัน viewer ไม่ให้เขียน
     (เมธอด POST/PUT/PATCH/DELETE ถูกบล็อกตรงนั้น) ส่วน `require_admin` ใช้กับงานผู้ดูแลระบบ
   - โมดูลใหม่ต้องเพิ่มชื่อในลิสต์ `include_router` ใน `services/api_gateway/app.py`
2. เพิ่มเทสต์ใน `tests/test_api.py` — อย่างน้อย: 200 เมื่อมี token, 401 เมื่อไม่มี, รูปร่าง payload
3. บันทึกใน `docs/API.md` ตารางเดียวกับของเดิม

### 5.2 เพิ่มค่าตั้ง (`NO7_*`)

1. `config/app.yaml`: `my_flag: ${NO7_MY_FLAG:false}` (ค่า default อยู่หลัง `:` เสมอ — code ไม่ hardcode path)
2. อ่านผ่าน `get_settings().app[...]` ไม่ใช่ `os.environ` ตรง ๆ
3. เพิ่มบรรทัดใน `.env.example` พร้อมคอมเมนต์ว่าเปิดแล้วเกิดอะไร
4. ถ้าค่าเปลี่ยนพฤติกรรมด้านความปลอดภัย/ความเสี่ยง → ต้องโผล่ใน `/api/system/health` ด้วย

### 5.3 เพิ่มอินดิเคเตอร์หรือกฎเข้าเทรด

1. ฟังก์ชันบริสุทธิ์ใน `packages/indicators/core.py` (รับ sequence/array คืน `np.ndarray`
   ความยาวเท่าเดิม, ช่วง warm-up เป็น `nan`) — ห้ามอ่าน I/O, ห้ามใช้ข้อมูลอนาคต
2. ต่อเข้ากับ `services/strategy_engine/` หรือ `packages/strategy_rules/`
3. เทสต์แบบ invariant ไม่ใช่แค่ค่าเดียว: ทิศทาง, ขอบเขต, พฤติกรรมเมื่อข้อมูลสั้นเกินไป
   (`tests/test_invariants.py` เป็นตัวอย่างที่ควรเลียนแบบ)
4. ถ้าเปลี่ยนสูตร → อัปเดต `docs/MATH.md` และบอกว่า "ยังประมาณตรงไหน"

### 5.4 เพิ่มหน้าใน dashboard

1. `apps/web-dashboard/src/views/MyPage.vue` + ลงทะเบียนใน `src/router.js`
2. เรียก API ผ่าน `request()` ใน `src/lib/api.js` (แนบ token, เด้งออกเมื่อ 401,
   แจ้ง UI เมื่อ API เงียบ) — อย่าเรียก `fetch` ดิบ
3. `npm run build` ก่อนรัน pytest ชุดเต็ม ไม่งั้น `tests/test_pwa.py` จะฟ้อง
4. ของที่ว่างต้องบอกว่าว่างเพราะอะไร — ห้ามโชว์ตัวเลขหลอก

### 5.5 เพิ่มช่องทางแจ้งเตือน

`services/notification/notifier.py` มีโครงครบแล้ว (retry, pacing, redact, บันทึกผลส่ง)
ช่องใหม่ต้อง: ชื่อช่องใน `channels`, สถานะรายช่องใน payload ของ `inapp` ด้วย, ความยาวสูงสุดใน `MAX_LEN`,
และ `send_test` ต้องตอบ `ok: null` เมื่อถูก pacing ข้าม (ไม่ใช่ `false`) — ดู `tests/test_notify_channels.py`

---

## 6. กฎที่ห้ามพัง

- **Risk Engine ยับยั้งได้เสมอ** และทุกการปฏิเสธต้องมีชื่อกฎ + ตัวเลขจริงในข้อความ
- **Lot มาจาก risk ÷ ระยะ SL** เท่านั้น; ห้าม Martingale / Grid / Average down
- **Signal score ≠ probability** — คะแนนคือ heuristic ความน่าจะเป็นต้องผ่าน calibration แยก
- **โมเดลที่ไม่ผ่าน OOS ต้องถูกติดป้าย `UNVALIDATED`** และระบบใช้ค่าฐานสถิติแทน — ห้าม override เกณฑ์
- **Full Auto ปิดเป็นค่าเริ่มต้น** ต้องครบทั้ง env + toggle + โมเดล approved + บัญชี demo
- **LLM อธิบายได้ สั่งออร์เดอร์ไม่ได้**
- **ความลับไม่เข้า git** (`.env`, token, รหัสโบรกเกอร์) และ log ต้อง redact
- **ถอยอย่างมีเสียง**: เมื่อของที่พึ่งพาล่ม (Redis, ฟีด, broker) ให้ทำงานต่อแบบจำกัดและ
  *บอกเหตุผล* ใน `/api/system/health` หรือ header — ห้ามเงียบแล้วปล่อยผ่าน

---

## 7. กับดักที่เคยเสียเวลามาแล้ว

| อาการ | สาเหตุจริง |
|---|---|
| `/api/market/candles` ตอบ 422 | endpoint บังคับ `limit ≥ 20` |
| `POST /api/backtest` → 405 | path คือ `/api/backtests` (พหูพจน์); `POST /api/brokers/active` ก็ไม่มี |
| `/api/redoc` → 404 | มีแค่ `/api/docs` (CSP ของหน้านั้นเปิดให้ jsDelivr เฉพาะที่นั่น) |
| ตั้ง `NO7_*` แล้วไม่มีผล | ตั้งหลัง `get_settings()` ไปแล้ว — ต้องตั้งก่อน แล้วเรียก `reload_settings()` |
| เทสต์ middleware rate limit แล้วปล่อยผ่านหมด | `RateLimiter` ที่ไม่มี rule ชื่อ `default` = ไม่จำกัดอะไรเลย |
| `AttributeError: 'Row' object has no attribute 'get'` | `sqlite3.Row` ใช้ `row["col"]` เท่านั้น |
| สร้าง store redis ไม่ได้ | `make_store()` สร้างไม่ได้ ต้องใช้ `build_store()` (คืน `(store, status)` พร้อม `reason`) |
| ตั้ง redis แล้วกลายเป็น memory | ต่อ Redis ไม่ได้ → ถอยไป sqlite ถ้ามี `store_path` ไม่งั้น memory และบอกเหตุผลใน health |
| service worker ไม่อัปเดตตอน dev | SW ทำงานเฉพาะ build โปรดักชัน (`npm run build`) ตั้งใจให้เป็นแบบนั้น |
| `test_spa_deep_links_are_served` 404 | ยังไม่ได้ `npm run build` (ไม่มี `apps/web-dashboard/dist`) |
| ออร์เดอร์ถูกปฏิเสธ 400 | ถูกต้องแล้ว — อ่าน `detail.blockers` (คะแนนต่ำ/ข่าว/spread/เพดาน) |
| pandas เตือน/พังเรื่องเวลา | pandas 3 ใช้ `datetime64[us]` และ `.ffill()` (ไม่ใช่ `fillna(method=...)`) |
| ผลเทสต์เพี้ยนเมื่อรันหลายโพรเซส | multiprocessing แบบ spawn import โมดูลซ้ำ — โค้ดเริ่ม/หยุดต้องอยู่ใต้ `if __name__ == "__main__"` |

---

## 8. Git / PR

- ทำงานบนสาขาที่เซสชันนี้ให้มา (`arena/...`) — ชื่อสาขาเปลี่ยนไม่ได้, อย่าสลับไปสาขาอื่น
- คอมมิตละเรื่องเดียว หัวเรื่องสั้นเป็นประโยคบอกสิ่งที่ทำ + เนื้อความบอก "พิสูจน์ยังไง"
  (ถ้าข้อความมี backtick ให้ใช้ `git commit -F msg.txt` / `gh pr create --body-file`)
- ก่อนเปิด PR: `./scripts/dev_check.sh` ต้องเขียว
- หลัง PR ถูก merge บน GitHub: `git fetch origin main && git reset --mixed FETCH_HEAD` — **ห้าม force-push**
- ห้าม commit: `.env`, `storage/*`, `dist/`, `node_modules/`, `.venv/`, `.tools/` (อยู่ใน `.gitignore` แล้ว)

---

## 9. งานถัดไปที่คุ้มทำ (เรียงตามคุ้มค่า/แรงที่ใช้)

### 9.1 พิสูจน์ Redis ด้วย `redis-server` จริง ⟵ เริ่มตรงนี้ได้เลย

ตอนนี้ชุดเทสต์ของ shared rate limit รันบน **fakeredis** (Lua เดียวกัน แต่คนละ implementation)
เครื่องมือมีให้แล้ว:

```bash
./scripts/fetch_redis_server.sh          # ดึง redis-server 6.2.14 จากวีล redislite → .tools/bin
.tools/bin/redis-server --port 6399 --save '' --appendonly no &
NO7_RATELIMIT_STORE=redis NO7_CLUSTER_BACKEND=redis \
  NO7_REDIS_URL=redis://127.0.0.1:6399/0 ./scripts/run.sh
# ตรวจแล้วได้: ratelimit {store: redis, shared: true}  /  cluster {backend: redis, role: leader}
```

ที่ยังขาดคือ *เทสต์* ที่ยิงของจริง: `tests/test_redis_real.py` ที่สตาร์ต `redis-server` เอง
(ข้ามเมื่อไม่มี binary), เทียบผลการตัดสินใจกับ `MemoryBucketStore` ตัวต่อตัว, จำลอง 4 โพรเซสแย่งโควตาเดียวกัน,
ฆ่า Redis กลางทางแล้วต้องเห็น `x-ratelimit-degraded` และ `/api/system/health → cluster.shared_health.ok: false`
จากนั้นค่อยเขียนตัวตรวจฝั่งผู้ดูแล (`scripts/check_redis.py`) ที่ยิง URL จริงโดยไม่ FLUSHDB
เสร็จแล้วแก้ถ้อยคำใน `LIMITATIONS.md` ให้ตรง (ตอนนี้ยังเขียนว่า "ยังไม่ได้ทดสอบกับ redis-server จริง")
ยังไม่ครอบคลุม: TLS (`rediss://`), `requirepass`, Sentinel/Cluster, Redis ที่ช้าแต่ไม่ตาย

### 9.2 ข้อมูลจริงแทนฟีดจำลอง

ท่อครบแล้ว (`scripts/import_candles.py`, `import_ticks.py`, `feed_mode: replay`, snapshot + backtest ซ้ำได้)
สิ่งที่ยังไม่มีคือ **ไฟล์จริง** — ใส่ CSV จาก MT5 เข้าไปแล้ววัดด้วย `scripts/evaluate_dataset.py`
ตัวเลขทุกตัวในระบบตอนนี้มาจาก seed 7 จึงพิสูจน์ได้แค่ว่าไปป์ไลน์ถูก ไม่ได้บอกว่ามี edge

### 9.3 ให้ backtest ใช้ edge ของโมเดลจริง

วันนี้ backtest ใช้ rule proxy ไม่ได้เรียกโมเดล → วัด "กฎ + risk" ไม่ได้วัดโมเดล
งานคือเสียบ forecast เข้า decision loop ของ `services/backtest_engine/` แบบไม่มี look-ahead
(ใช้เฉพาะโมเดลที่ถูกฝึกจากข้อมูลก่อนหน้าจุดนั้น) แล้วรายงานเทียบกับ baseline เดิม

### 9.4 EA จริงบน MT5

`bridge/No7BridgeEA.mq5` ยังไม่เคย compile — ต้องมี Windows + MetaEditor + บัญชี demo
ฝั่งเซิร์ฟเวอร์ทดสอบครบแล้วด้วย EA จำลอง (`scripts/run_bridge_sim.py`) แต่ของจริงจะเจอเรื่อง
filling mode / stops level / requote ที่ยังไม่เคยเจอ

### 9.5 หลายผู้ใช้จริงจัง

SQLite + runtime โพรเซสเดียวคือเพดานปัจจุบัน (`--workers N` ยังไม่รองรับ)
ถ้าจะไปต่อ: ย้าย persistence ไป Postgres, แยก scheduler/simulator ออกจาก API worker,
แล้วค่อยเพิ่ม quota ของ WebSocket แบบ distributed (ตอนนี้จำกัดเฉพาะ HTTP)

### 9.6 ของเล็กที่ยังค้าง

- คิวส่งออกแบบทนรีสตาร์ต + ลายเซ็น webhook (ตอนนี้คิว bridge ที่ยังไม่ ack หายตอนรีสตาร์ต โดยตั้งใจ)
- PWA: screenshots/splash สำหรับ install prompt ที่สวยขึ้น, Web Push (ยังไม่มีโดยตั้งใจ)
- Monte Carlo / การกระจายของ slippage ใน backtest
- Temporal CNN / ensemble — ต่อเมื่อ walk-forward พิสูจน์ว่าดีกว่าของเดิมจริง

---

## 10. อ่านต่อ

| ไฟล์ | เมื่อไหร่ที่ต้องเปิด |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | อยากรู้ว่าชั้นไหนคุยกับชั้นไหน และทำไมถึงแยกแบบนี้ |
| [`API.md`](API.md) | สัญญาของ endpoint ที่ dashboard พึ่งพา |
| [`RUNBOOK.md`](RUNBOOK.md) | ตั้งค่า MT5/Windows, Redis, TLS, แจ้งเตือน, แก้ปัญหาตอนรัน |
| [`MATH.md`](MATH.md) | ทุกสูตร + จุดที่ยังเป็นการประมาณ |
| [`DATA.md`](DATA.md) | นำเข้าข้อมูลจริงและประเมิน offline |
| [`LIMITATIONS.md`](LIMITATIONS.md) | สถานะความจริงของระบบ — อ่านก่อนเคลมอะไรกับใคร |
