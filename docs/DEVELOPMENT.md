# Development — จะพัฒนาต่อยังไง

เอกสารนี้คือทางเข้าสำหรับ "เปิดเครื่องมาแล้วทำงานต่อ" — ติดตั้งยังไง, ลูปพัฒนาเป็นแบบไหน,
แก้ตรงไหนไปแตะไฟล์อะไร, เกตก่อนส่งงานคืออะไร, และงานถัดไปที่คุ้มทำที่สุดคืออะไร
(baseline ที่ตรวจแล้วอยู่ที่ [`BASELINE-P1.th.md`](BASELINE-P1.th.md), ข้อจำกัดอยู่ที่
[`LIMITATIONS.md`](LIMITATIONS.md), วิธีดูแลตอนรันอยู่ที่ [`RUNBOOK.md`](RUNBOOK.md))

สำหรับ Windows ใช้ [`LOCAL-VERIFICATION.th.md`](LOCAL-VERIFICATION.th.md) เป็น canonical local QA route;
ตัวเลขเวลาจำนวน tests ในตารางด้านล่างเป็น **historical measurements ไม่ใช่ current acceptance**
CI เป็น workflow ที่ประกาศใน repository ไม่ใช่หลักฐานว่า working tree ที่ยังไม่ commit นี้ผ่าน remote CI

---

## 0. TL;DR

```bash
./scripts/dev_setup.sh      # venv + deps + .env + dashboard bundle (ครั้งแรก ~2 นาที)
./scripts/run.sh            # http://127.0.0.1:8000  →  demo@no7.ai / no7demo1234
./scripts/dev_check.sh      # เกต Bash เดิม: ruff + bundle presence + pytest; จำนวน tests ดู evidence ล่าสุด
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

- **สคริปต์เลือกล่าม Python ให้เอง** — `run.sh` / `test.sh` / `dev_check.sh` / `train.sh`
  source `scripts/python_bin.sh` ซึ่งไล่ลำดับ `$PYTHON` → `.venv/bin/python` → `$VIRTUAL_ENV`
  → `python3` ใน PATH (ตอนรัน `run.sh` จะพิมพ์ `python: …` บอกว่าใช้ตัวไหน)
  บังคับเองได้ด้วย `PYTHON=/path/to/python ./scripts/run.sh` — CI ใช้ช่องทางนี้
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

ตัวเลขอ้างอิงย้อนหลังบนเครื่องพัฒนา (Python 3.11, 2 cores) ไม่ใช่ baseline ปัจจุบัน — ช่วงเวลาคือ *รันแรกหลังล้างเครื่อง*
(cache เย็น, ต้องโหลด sklearn/lightgbm จากดิสก์) ถึง *รันถัดไป* (cache อุ่น):

| ชุด | จำนวน | เวลา |
|---|---|---|
| ทั้งหมด (`pytest -q`) | 564 (558 pass + 6 skip) | **~2 นาที** (รวม backtest ที่ใช้โมเดล 3 รัน ≈ 50 วินาที) |
| ตัดสองไฟล์ที่หนักที่สุด `--ignore=tests/test_backtest_engine.py --ignore=tests/test_model_validation.py` | 536 (530 pass + 6 skip) | ~30 → **~90** วินาที (แล้วแต่โหลดเครื่อง) |
| `tests/test_backtest_engine.py` + `tests/test_model_validation.py` | 28 | ~75 → **~22** วินาที |
| `tests/test_ws_quota.py` (โควตา WebSocket) | 32 | ~5 วินาที |
| `tests/test_redis_real.py` (redis จริง, skip ถ้าไม่มี binary) | 20 | ~4 วินาที |
| `tests/test_notify_outbox.py` (คิวถาวร + ลายเซ็น webhook) | 27 | ~5 วินาที |
| `tests/test_attribution.py` (เหตุผลที่ไม่เทรด + deadlock สตรีคขาดทุน) | 16 | ~4 วินาที |

(6 ที่ skip คือเทสต์สคริปต์ที่ต้องมี `bash`/`.venv` ซึ่งไม่มีในบางสภาพแวดล้อม)

ลูปที่แนะนำ: แก้ → ไฟล์เทสต์ที่เกี่ยวข้อง → ชุดที่ตัดสองไฟล์หนัก → ชุดเต็มก่อน commit

**CI รันเกตตัวเดียวกันนี้ให้อัตโนมัติทุก PR** (`.github/workflows/ci.yml` → `./scripts/dev_check.sh`)
ถ้าเครื่องคุณลืมรัน CI จะจับให้ และถ้าอีกทีม merge อะไรที่ชนกับของเรา CI จะแดงตั้งแต่ใน PR

**ต้องล้าง runtime overrides ก่อนรันเทสต์** — `tests/conftest.py` ใช้ `setdefault` ชี้ `NO7_DB_PATH`/`NO7_DATA_DIR`/… ไปที่ temp dir
จึงไม่ทับค่าที่สืบทอดอยู่; local runner ล้าง `NO7_*`/`MT5_*` ใน child environment ก่อนเรียก pytest
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
| สคริปต์ใน `scripts/` | `scripts/*.sh`, `scripts/python_bin.sh` | `tests/test_scripts.py` |
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
| สคริปต์ใหม่ตาย `No module named uvicorn/pytest` | เขียน `python3 -m …` ตรง ๆ = ล่ามของระบบที่ไม่มี dependency — ต้อง `source scripts/python_bin.sh` แล้วใช้ `"${PY}"` (`tests/test_scripts.py` จับให้) |
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

### 8.1 เมื่อมีมากกว่าหนึ่งทีมในรีโปเดียวกัน

git รวมงานตาม *เนื้อหาไฟล์* ไม่ใช่ตามคน — คนละไฟล์/คนละบรรทัดจะรวมให้เอง บรรทัดเดียวกันจะขึ้น
conflict ให้แก้ (ไม่มีการเขียนทับเงียบ ๆ) ที่ git **ไม่** เตือนคือ "ทำงานซ้ำกัน" และ
"แยกกันผ่าน แต่รวมกันแล้วพัง" — สามอย่างนี้กันไว้แล้ว:

| เครื่องมือ | ทำอะไร |
|---|---|
| `.github/workflows/ci.yml` | รัน `./scripts/dev_check.sh` ทุก PR และทุก push เข้า `main` → จับ "รวมแล้วพัง" ก่อนถึง main |
| `.github/CODEOWNERS` | GitHub ขอรีวิวจากเจ้าของพาธอัตโนมัติ (แก้ไฟล์นี้เพื่อแบ่งอาณาเขตเมื่อทีมที่สองเริ่ม) |
| `.github/pull_request_template.md` | บังคับให้บอก "พิสูจน์ยังไง" และ **ติ๊กไฟล์กลางที่แตะ** |

ธรรมเนียมที่ลด conflict ได้มากที่สุด:

1. **รอบสั้น 1 PR = 1 เรื่อง** — สาขาที่อยู่นานคือสาขาที่ชน
2. **merge `main` ล่าสุดเข้าสาขาก่อนขอรีวิวเสมอ** (`git fetch origin main && git merge origin/main`)
3. **เพิ่มไฟล์ใหม่ดีกว่าแก้ไฟล์กลาง** — route module ใหม่ + ไฟล์เทสต์ใหม่ แทนการยัดลงไฟล์เดิม
4. บอกอีกทีมก่อนแตะ: `services/api_gateway/app.py` (ลำดับ middleware), `config/*.yaml`,
   `tests/conftest.py`, `requirements*.txt`, schema ของ SQLite — พวกนี้ "merge ผ่านแต่พัง" ได้
5. ตัวเลขในเอกสาร (จำนวนเทสต์ ฯลฯ) ล้าสมัยทันทีที่อีกทีม merge — อัปเดตเมื่อเห็นว่าไม่ตรง

---

## 9. งานถัดไปที่คุ้มทำ (เรียงตามคุ้มค่า/แรงที่ใช้)

### 9.1 พิสูจน์ Redis ด้วย `redis-server` จริง ✅ เสร็จแล้ว (รอบ 24)

```bash
./scripts/fetch_redis_server.sh                         # redis-server 6.2.14 → .tools/bin (ไม่ต้อง root)
.venv/bin/python -m pytest tests/test_redis_real.py -q  # 17 passed (~3 วินาที) — skip ถ้าไม่มี binary
.venv/bin/python scripts/check_redis.py --url redis://HOST:6379/0 --ttl 2   # 12/12 PASS
```

สิ่งที่ทำไปแล้ว: `tests/test_redis_real.py` สตาร์ต `redis-server` เอง และเทียบผลการตัดสินใจกับ
`MemoryBucketStore` ทุกคำขอ, 4 โพรเซสแย่งโควตาเดียวกันได้พอดีลิมิต, ฆ่า Redis กลางทางแล้วเห็น
`x-ratelimit-degraded`, frame bus/TTL/fail-closed, `build_store`/`build_shared_state` fallback;
CI มี step ที่ **fail ถ้าเทสต์ชุดนี้ถูก skip** และรัน `scripts/check_redis.py` กับ Redis จริง;
หลักฐานสองโปรเซส + ตารางผลอยู่ใน `docs/RUNBOOK.md` §12.6

**บั๊กที่เจอเพราะทำข้อนี้** (ทั้งหมดแก้แล้ว + มีเทสต์กันถอยหลัง):
1. 429 ไม่ส่ง `x-ratelimit-degraded` — ผู้เรียกจึงแยกไม่ออกว่าโดนจำกัดด้วยโควตารวมหรือโควตาสำรอง
2. Lua เซฟยอดด้วย `tostring()` (`%.14g`) → ยอดถูกปัดทุกครั้งที่ใช้ ทำให้ Redis กับ memory
   ตัดสินใจต่างกันที่ขอบ (แก้เป็น `string.format('%.17g', …)`)
3. `/api/system/health → ratelimit` ยังรายงาน `shared: true` ขณะ Redis ล่ม (รายงานค่าตอนบูต
   อย่างเดียว) → ตอนนี้มี `degraded`, `last_error` และพลิก `shared: false` ตามความจริง

ยังไม่ครอบคลุม: TLS (`rediss://`), `requirepass`, Sentinel/Cluster, Redis ที่ช้าแต่ไม่ตาย

### 9.2 ข้อมูลจริงแทนฟีดจำลอง

ท่อครบแล้ว (`scripts/import_candles.py`, `import_ticks.py`, `feed_mode: replay`, snapshot + backtest ซ้ำได้)
สิ่งที่ยังไม่มีคือ **ไฟล์จริง** — ใส่ CSV จาก MT5 เข้าไปแล้ววัดด้วย `scripts/evaluate_dataset.py`
ตัวเลขทุกตัวในระบบตอนนี้มาจาก seed 7 จึงพิสูจน์ได้แค่ว่าไปป์ไลน์ถูก ไม่ได้บอกว่ามี edge

### 9.3 ให้ backtest ใช้ edge ของโมเดลจริง ✅ เสร็จแล้ว (รอบ 25)

```bash
# เทียบ rule proxy กับโมเดลบนแท่งชุดเดียวกัน (เท่ากันทุกอย่างยกเว้น forecast)
python scripts/model_edge_report.py --bars 20000 --json /tmp/edge.json
python scripts/model_edge_report.py --symbol XAUUSD --dataset     # ข้อมูลที่ import แล้ว
# หรือยิง API: POST /api/backtests {"symbol":"XAUUSD","bars":20000,"forecast_source":"model"}
```

`services/backtest_engine/model_edge.py` ตัดช่วงตัดสินใจเป็น segment แล้วฝึกโมเดลหนึ่งตัวต่อ
segment ด้วย **expanding window ที่ purge แล้ว**: label ของแถว j อ่านราคาที่แท่ง j+hb
ดังนั้นแถวที่ใช้ฝึกต้องจบก่อน segment เริ่มอย่างน้อย hb แท่ง (30 นาที = 6 แท่ง M5)
ค่า NaN เติมด้วย median ของ *แถวที่ใช้ฝึก* ไม่ใช่ของทั้งเฟรม (median ทั้งเฟรมคือข้อมูลอนาคต)
และ segment จะถูกทำเครื่องหมาย `calibrated` ก็ต่อเมื่อ fold ก่อนหน้า (ที่ label จบไปแล้วจริง ๆ)
ผ่านเกณฑ์ directional accuracy — segment แรกจึงรันแบบ "ยังไม่ผ่านการตรวจ" เสมอ
ความแม่นใน report เป็น hindsight สำหรับอ่านอย่างเดียว ไม่เคยป้อนกลับเข้าการตัดสินใจ

**ผลที่ได้จริง (ฟีดจำลอง 8,000 แท่ง)**: โมเดล 0.530 vs rule proxy 0.578 → *ไม่มี edge*
นี่คือคำตอบที่ถูกต้องสำหรับข้อมูลสังเคราะห์ (random walk + trend persistence เข้าทาง proxy)
คำถามจริงต้องวัดบนข้อมูลจริงใน §9.2

**บั๊กที่เจอเพราะทำข้อนี้** (แก้แล้วทั้งหมด + มีเทสต์กันถอยหลัง ใน `tests/test_model_edge.py`):
1. `trades_this_week` ถูกป้อนด้วยจำนวนไม้ *ของวัน* → เพดานไม้รายสัปดาห์ไม่เคยทำงานใน backtest
   (ตัวแปร `trades_week` มีอยู่แต่ไม่เคยถูกใช้และไม่เคยรีเซ็ต)
2. `weekly_pnl` = กำไรทั้งรัน ไม่ใช่กำไรของสัปดาห์ → เกต weekly loss วัดหน้าต่างผิด
   และยิ่งรันยาวยิ่งผิดมาก
3. backtest ตัดวันที่เที่ยงคืน **UTC** แต่ระบบจริงตัดตาม `daily_reset_timezone`
   (default Asia/Bangkok) → ลิมิตรายวันคนละหน้าต่างกับโปรดักชัน 7 ชั่วโมง
4. `evaluate_gate` ไม่ได้ส่ง `now` → cooldown หลังขาดทุนติดกันถูกเทียบกับ **นาฬิกาจริง**
   แทนเวลาในแท่ง: backtest ข้อมูลย้อนหลังจึงไม่เคยติด cooldown เลย

ยังไม่ครอบคลุม: โมเดลยังไม่ถูกใช้เลือก *ทิศทาง* (ทิศทางยังมาจากโครงสร้างราคา) — โมเดลมีผ่าน
`p_up` → `p_tp_before_sl` → คะแนน + เพดานความน่าจะเป็นเท่านั้น; ยังไม่มี Monte-Carlo slippage
และยังไม่ได้วัดบนข้อมูลจริง

### 9.4 EA จริงบน MT5

`bridge/No7BridgeEA.mq5` ยังไม่เคย compile — ต้องมี Windows + MetaEditor + บัญชี demo
ฝั่งเซิร์ฟเวอร์ทดสอบครบแล้วด้วย EA จำลอง (`scripts/run_bridge_sim.py`) แต่ของจริงจะเจอเรื่อง
filling mode / stops level / requote ที่ยังไม่เคยเจอ

### 9.5 หลายผู้ใช้จริงจัง — WebSocket quota ✅ เสร็จแล้ว (รอบ 26), ที่เหลือยังค้าง

เสร็จแล้ว: **quota ของ WebSocket แบบ distributed** (`services/api_gateway/wsquota.py`)
— ก่อนหน้านี้ `/ws/live` ไม่มีเพดานเลย ใครก็เปิด socket ได้ไม่จำกัดจนเครื่องหมดแรง

```bash
# ดูเพดานและการใช้งานจริง
curl -s localhost:8000/api/system/health | jq .websockets
# {"enforced":true,"store":"redis","shared":true,"max_per_user":4,"max_total":64,
#  "lease_ttl_seconds":45,"open":3,"granted":12,"refused":2,"degraded":0}
```

slot เป็น **lease ที่หมดอายุ** ไม่ใช่ตัวนับ เพราะ worker ที่โดน SIGKILL ไม่มีทางคืนค่าตัวนับ
(วัดจริงแล้ว: ฆ่า worker ทิ้งขณะถือ socket → lease ยังอยู่ใน Redis พร้อม TTL แล้วหายเองตามเวลา)
ใช้ store เดียวกับ rate limit (memory / sqlite / redis) ภายใต้ prefix `no7:ws`

ยังค้าง: ย้าย persistence ไป Postgres, แยก scheduler/simulator ออกจาก API worker
(ตอนนี้ runtime ยัง single-writer ด้วย lease — `--workers N` จึงยังไม่ใช่โหมดที่รองรับ)

### 9.6 ของเล็กที่ยังค้าง

- ~~คิวส่งออกแบบทนรีสตาร์ต + ลายเซ็น webhook~~ ✅ **เสร็จรอบ 27** —
  `services/notification/outbox.py` (sqlite, backoff, หมดอายุ, คิวเต็มทิ้งของเก่าสุด) +
  `services/notification/signing.py` (HMAC-SHA256 บน `timestamp.body`, เซ็นตอนส่ง)
  พิสูจน์กับแอปจริงด้วย `scripts/check_outbox.py` (ล่ม → รีสตาร์ต → ฟื้น, 7/7)
  · ที่ยังเหลือในหัวข้อนี้: **คิวคำสั่ง bridge** ที่ยังไม่ ack ยังหายตอนรีสตาร์ต โดยตั้งใจ
  (คำสั่งเทรดเก่าที่ส่งซ้ำหลังรีสตาร์ตอันตรายกว่าคำสั่งที่หาย) และคิวนี้ยังเป็นของเครื่องเดียว
- ~~ไม่มีใครตอบได้ว่า "ทำไมระบบไม่เทรด"~~ ✅ **เสร็จรอบ 28** —
  `services/strategy_engine/attribution.py` นับเหตุผลด้วยรหัสคงที่ (ไม่ใช่ข้อความ)
  โผล่ที่ `report.diagnostics.attribution`, `GET /api/system/attribution`
  และแผงในหน้า System · เจอบั๊ก `consecutive_losses` ล็อกระบบถาวรทันทีที่เปิดดู
  (LIMITATIONS §5) · ที่ยังเหลือ: หน้าต่างนับของระบบสดเป็นแบบสะสม ยังไม่ใช่ rolling รายชั่วโมง
  และยังไม่ได้ผูกเหตุผลกับผลลัพธ์ย้อนหลัง ("ถ้าผ่อนกฎนี้จะได้/เสียเท่าไร")
- **ยังไม่ได้ปรับ threshold ใด ๆ ทั้งที่รู้แล้วว่าตัวไหนบีบ** — 86% ของการตัดสินใจตายที่
  `entry_conditions` แต่การผ่อนกฎบนฟีดจำลองจะได้คำตอบที่เชื่อไม่ได้ (§9.2 ต้องมาก่อน)
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
