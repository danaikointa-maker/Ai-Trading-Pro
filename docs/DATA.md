# ข้อมูลจริง (Real data) — จากไฟล์ CSV สู่ตัวเลขที่ใช้อ้างอิงได้

> **ทำไมต้องมีขั้นนี้:** ค่าเริ่มต้นของระบบใช้ **feed จำลอง** (seed 7) ซึ่งพิสูจน์ได้แค่ว่าไปป์ไลน์ถูก
> ไม่ได้บอกว่าโมเดลมี edge จริง ตราบใดที่ยังรันบน feed จำลอง คำตอบที่ถูกของ gate คือ
> `UNVALIDATED` — และมันจะยังเป็นอย่างนั้นตลอดไป ไม่ว่าจะปรับ threshold เท่าไร

ไฟล์ CSV จากโบรกเกอร์/MT5 → นำเข้า → ประเมินด้วย trainer + backtest engine ตัวเดียวกับที่ dashboard ใช้

---

### Model artifact quarantine — H076–H078

Model list/approval ตรวจ registration และ SHA-256 โดยไม่ deserialize; API คืน `409`
เมื่อ registry ปฏิเสธ ไม่อ้าง `ok=true` หรือโหลด predictor ต่อ
หากพบ registered model เสีย/ขาด/ไม่ตรง provenance จะเก็บ `model.quarantine:<version>`
ใน workspace SQLite เป็น durable latch; list แสดง `artifact_status=quarantined`
และ generic `artifact_reason` โดยไม่เปิดเผย path หรือ raw exception
คืนไฟล์เดิมหรือเปิดโปรแกรมใหม่ไม่ปลด latch; malformed record ก็ปฏิเสธการโหลด
การ revoke approval ไม่ปลด quarantine และไม่ลบ/ย้าย/แก้ artifact หรือ provenance เดิม
H079 decoder failure หลัง hash ผ่านก็สร้าง durable latch และคืน load refusal โดยไม่ raw error
H080 reload approval ต้องผ่านทั้ง payload และ DB; revoke แล้ว route reload predictor ด้วย
H081 horizon inference ต้องผ่าน global predictor approval ด้วย; ยังไม่รับรอง cached forecasts,
path-table หรือ concurrent model mutation
H082–H084 addendum: revoked predictor ไม่เรียก path-table; arrays ว่างล้าง table เก่า
training install ทั้ง predictor/runtime worker โหลด registered bytes/DB approval ใหม่
approve/revoke ล้าง cache ทุก symbol ใต้ runtime lock; forecast_for ตรวจ version/approval
ยังไม่ครอบคลุม consumers ที่อ่าน dictionary ตรง/replica/UI merge, loaded artifact mutation
หรือ concurrent decision writes; local lock ไม่ใช่หลาย process/broker fencing
H085 decode สำเร็จยังต้องผ่าน schema: version/symbol ผูก registration, approved เป็น bool,
metrics/models เป็น mappings, trained_at/rule/horizon ถูกชนิด และ path high/low เป็น finite
numeric 2-D arrays ขนาดตรงคู่/horizon; schema refusal เก็บ durable generic latch เดิม
ไม่ใช่ sandbox และไม่ทำให้ joblib ที่เป็น executable ปลอดภัย; unknown NPZ metadata keys ยังเก็บได้
H086 local cached_forecast accessor ใช้ร่วมกันใน signals/explain/live/watchdog/management
เพื่อไม่ใช้ cache version เก่าหรือ approved cache เมื่อ predictor ถูก revoke; baseline/current cache ยังใช้ได้
ไม่รับรอง replica frames, UI merge, concurrent decision write หรือ DB/artifact mutation หลัง load
H087–H088 addendum: UI เคารพ explicit null และทิ้ง forecast เมื่อ symbol/version/approval ไม่ตรง
loaded forecast/path/status และ approved cache recheck DB approval/quarantine/artifact bytes โดยไม่ decode ซ้ำ
เมื่อ authority ใช้ไม่ได้ demote และ clear models/table ไม่ auto-reapprove; ต้อง explicit verified reload
ยังมี check/use concurrency/TOCTOU และ repeated hashing cost; ไม่ใช่ signature, sandbox หรือหลาย process fencing
ขณะนี้ยังไม่มี operator release API/CLI ที่รับรองแล้ว ให้เก็บหลักฐานและฝึกใหม่ด้วย version ใหม่
ห้ามแก้ hash/ลบ latch เพื่อ bypass; digest ไม่ใช่ signature และยังไม่รับรอง root/TOCTOU race

### Local tick path safety — H066

H068–H069 daily manifest ต้องมี schema/root/symbol/layout/day entries ที่ถูกต้อง; damaged/copied
manifest ไม่ถูก repair/adopt โดย importer ข้อมูลเก่าที่ไม่มี provenance ไม่ได้กลายเป็น trusted อัตโนมัติ
Day load ต้องมี registration และตรวจ SHA-256/size ของ stored bytes ก่อน parse bytes เดียวกัน
แล้วตรวจ canonical digest/rows/time bounds; index นี้ไม่ใช่ลายเซ็นหรือ broker authenticity
ผู้มีสิทธิ์แก้ทั้ง data และ manifest ยังปลอม local evidence ได้; legacy content/cache/TOCTOU ยังเปิด

H070 legacy one-file layout ที่ import ใหม่มี schema/root/symbol/path/stored-byte evidence;
load/summary/import ปฏิเสธ existing missing/foreign/corrupt sidecar ไม่ auto-adopt export รุ่นแรก
ไฟล์เดิมยังอยู่ครบ ให้ตรวจ source แล้ว re-import ไป root ว่างใน workspace ไม่แก้ sidecar เพื่อปลด guard
load ตรวจ stored bytes ก่อน parse และ canonical digest/rows/bounds หลัง parse; ยังไม่ใช่ authenticated provenance

H071 `scripts/import_ticks.py --data-dir` เลือกได้เฉพาะ configured workspace datasets หรือ child
ใช้ path resolver เดียวกับ candle CLI; foreign/link paths ปฏิเสธก่อน importer และ storage refusal คืน exit 1

H072 daily aggregate totals ต้องตรง entries/type; summary ปฏิเสธ day files ที่ไม่มี index
TickStore cache hit ตรวจ index ยังเหมือนตอนสร้าง store; ถ้า index เปลี่ยนต้องสร้าง store ใหม่
ไม่ได้ hash file ใหม่ทุก cache hit และยังไม่ใช่ inode/root/TOCTOU protection

H073 prune ต้องมี valid manifest ก่อนลบและ preflight paths ของวันที่เลือกทั้งหมด
เมื่อสำเร็จปรับ remaining entries/totals/bounds; damaged index ไม่ถูก repair/adopt
ยังไม่ใช่ crash-atomic หลายไฟล์/rollback หรือ data-integrity preflight ครบทุกไฟล์; เก็บ backup/operator evidence แยก

H074 tick status แยก invalid artifact เป็น available=false/status=quarantined/generic reason ต่อ symbol
ไม่เผย raw manifest error/path และไม่กลบ valid symbols; inventory รักษา underscores/ปฏิเสธ linked root
คำว่า quarantined เป็น validation refusal ไม่ใช่ durable operator record; daily status ไม่ hash/parse day data

H075 requested tick-assisted backtest ที่ TickBook.load เกิด exception จะจบ generic job error ไม่ downgrade
เป็น bar-only แล้วบันทึกรายงาน; ไม่เผย raw tick exception/path การไม่มี tick data (load คืน None) ยัง conservative contract เดิม

H067 inventory ตัด `.csv.gz` suffix เต็มเพื่อคืนวันที่จริงและรวม formats ของวันเดียวกัน
ปฏิเสธชื่อ partition ไม่ใช่ calendar day, symlink/dangling link และ directory
Inventory นี้ไม่อ่าน/ยืนยัน data content หรือ trusted manifest provenance

Daily tick staging เปิดด้วย exclusive creation และปฏิเสธ `.tmp` เดิม รวมถึง symlink/dangling link;
หากเขียนไม่สำเร็จอาจเหลือ staging artifact ซึ่งต้องตรวจสอบ ไม่ถูก adopt/ล้างให้อัตโนมัติ
Legacy single-file data/metadata ใช้ symbol/root/link guards เดียวกับ daily paths;
import ตรวจทั้งสอง destination ก่อนอ่าน source หรือเผยแพร่ data
นี่เป็น path safety ไม่ใช่ trusted provenance/signature: re-import ยัง replace daily data ตามพฤติกรรมเดิม
และยังไม่รับรอง reparse/TOCTOU, root rebinding, crash/concurrency หรือ artifact authenticity

## 1. ขอไฟล์จาก MT5

1. เปิดกราฟ `XAUUSD` ที่ timeframe `M1` แล้วเลื่อนกราฟย้อนหลังให้โหลดแท่งครบตามที่ต้องการ
   (หรือ `Tools → History Center` เลือก symbol + M1)
2. คลิกขวาบนกราฟ → **Save As** (หรือเลื่อนกราฟสุดทางขวาแล้ว Save) จะได้ไฟล์ `.csv`
   ที่หัวตารางแบบ `<DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>`
3. **สำคัญ:** MT5 เขียนเวลาเป็น **เวลาของเซิร์ฟเวอร์โบรกเกอร์** ไม่ใช่ UTC
   ถ้าเซิร์ฟเวอร์เป็น GMT+3 ให้ส่ง `--tz Etc/GMT-3` หรือถ้าโชคดีที่โบรกเกอร์ตั้งเวลาไทย
   ก็ `--tz Asia/Bangkok` — ใส่ผิดเวลา แท่งทั้งหมดจะเลื่อนไปทั้งชุด และทุกอย่างที่คำนวณต่อจะเพี้ยนตาม

รูปแบบอื่นที่รองรับ (แยกคอลัมน์อะไรก็ได้ตามตารางนี้):

| ความหมาย | ชื่อคอลัมน์ที่ยอมรับ |
|---|---|
| เวลา | `time`, `datetime`, `timestamp`, `date` + `time` แยกกัน, หรือ epoch วินาที |
| ราคา | `open/high/low/close`, `o/h/l/c`, `bid_open…` |
| ปริมาณ | `volume`, `vol`, `tickvol`, `real_volume` (ไม่มีก็ได้ → 0) |

ตัวคั่นที่รองรับ: `,` `;` tab `|` (ตรวจอัตโนมัติ)

## 2. นำเข้า

```bash
.venv/bin/python scripts/import_candles.py \
  --csv ~/Downloads/XAUUSD_M1.csv --symbol XAUUSD --tz Etc/GMT-3
```

ผลลัพธ์อยู่ใต้ configured dataset root ของ workspace เช่น `storage/datasets/workspaces/local/XAUUSD_M1.csv`
(สคีมา `t,o,h,l,c,v` เวลาเป็น epoch UTC)
และ sidecar `XAUUSD_M1.meta.json` ที่บันทึก: จำนวนแท่ง, ช่วงเวลา, จำนวน gap,
จำนวนแท่งที่ถูกทิ้งเพราะซ้ำ, จำนวนแท่งที่ OHLC ขัดกันเอง, sha256 ของไฟล์ต้นฉบับ

### Provenance และ legacy quarantine (H060–H061)

- Sidecar รุ่นใหม่บันทึก `schema`, resolved `dataset_root`, symbol/timeframe และ full SHA-256
  ทั้ง source bytes ที่ parse จริงและ normalized CSV; loader ตรวจหลักฐานก่อน parse bytes ชุดเดียวกับที่ hash
- `--out-dir` / `--dataset-dir` ใช้ configured workspace datasets เป็นค่าเริ่มต้น;
  เลือกได้เฉพาะ root เดิมหรือโฟลเดอร์ย่อย ไม่เลือก legacy/foreign root
- Import **ไม่เขียนทับ** CSV หรือ sidecar ที่มีอยู่ และปฏิเสธ linked artifact paths;
  legacy/sidecar หายหรือผิดรูป/digest ไม่ตรงถูกปฏิเสธ ไม่ย้าย ลบ หรือ adopt อัตโนมัติ
- หากต้องนำเข้ารอบใหม่ ให้ตรวจ source และใช้โฟลเดอร์ว่างภายใน workspace ผ่าน flag ข้างต้น
  แล้วเลือกโฟลเดอร์เดียวกันตอน evaluate/replay; เก็บหลักฐานเดิมไว้ ไม่ลบเพื่อข้าม guard
- นี่เป็น local integrity/root binding ไม่ใช่ broker authenticity หรือ signature;
  ผู้ที่แก้ได้ทั้ง CSV และ sidecar ยังสร้างหลักฐานใหม่ได้ ยังไม่มี DB-backed workspace registry สำหรับ datasets
- Snapshot/tick loaders เป็นคนละเส้นทาง ยังไม่อยู่ในขอบเขต guards รอบนี้;
  root rebinding/reparse race, crash/power-loss และ durable operator quarantine workflow ยังไม่รับรอง

ตัวนำเข้า **ไม่เดา**: คอลัมน์ไม่ครบ → error, เวลา parse ไม่ได้ → error, tz ผิดชื่อ → error
แท่งที่หายไป/ซ้ำจะถูกนับและรายงาน ไม่ใช่เงียบ ๆ ทิ้ง

## 3. ประเมิน

```bash
# ใช้ dataset ที่นำเข้าไว้แล้ว
.venv/bin/python scripts/evaluate_dataset.py --symbol XAUUSD

# หรือนำเข้าและประเมินในคำสั่งเดียว
.venv/bin/python scripts/evaluate_dataset.py --symbol XAUUSD --csv ~/Downloads/XAUUSD_M1.csv --tz Etc/GMT-3
```

สิ่งที่พิมพ์ออกมา: ข้อมูลสรุปของชุดข้อมูล → ตาราง metric ต่อ horizon (directional accuracy,
Brier improvement, fold pass rate, วิธี validation, verdict) → ผล backtest
(trades, win rate, net, profit factor, expectancy, max DD, `no_trade_rate`, costs/swap)
→ ไฟล์รายงาน JSON ใน `storage/backtests/dataset_eval_*.json`

## 4. อ่านผลอย่างไรไม่ให้หลอกตัวเอง

- **verdict `baseline / UNVALIDATED`** = ไม่ผ่านเกณฑ์ OOS ของระบบเอง (directional ≥ 52%,
  Brier ดีกว่า baseline ≥ 0.02, และผ่านใน ≥ 75% ของ fold) — ไม่ใช่ "แย่" แต่คือ "ยังไม่มีหลักฐานพอ"
- `validation_method` บอกว่า fold มาจากไหน:
  - `walk-forward (refit per fold)` — ฝึกใหม่ทุก fold (ต้องการประวัติพอสมควร)
  - `block slices of one fitted model (not refit)` — ข้อมูลน้อยเกินไปที่จะ refit จึงถอยมาใช้วิธีเดิม
    และ **บอกตรง ๆ** ว่าไม่ได้ refit
  - `no horizon was trained…` — ข้อมูลสั้นเกินกว่าจะฝึกได้เลย
- `no_trade_rate` สูงไม่ใช่บั๊ก — ระบบเลือกไม่เทรดเมื่อไม่ผ่านเงื่อนไข และนับมันเป็นผลลัพธ์
- backtest ตัดสินใจบนแท่ง M5 ที่ปิดแล้ว, fill ที่ open ของแท่งถัดไป, คิด spread + slippage + commission
  และ swap (คืนละครั้ง) — ถ้าในแท่งเดียวชนทั้ง SL และ TP จะถือว่า SL ชนก่อน (conservative)

## 5. ให้ dashboard ทั้งระบบเดินบนข้อมูลจริง (replay)

```yaml
# config/app.yaml
market_data:
  feed_mode: replay          # simulate | mt5 | replay
  replay:
    dataset_dir: storage/datasets
    timeframe: M1
    warmup_bars: 6000        # แท่งที่ analysis เห็นก่อนเริ่มเดิน
    speed_minutes_per_second: 6.0
    loop: false
```

- ต้องมีไฟล์ของ **ทุก symbol ที่ broker ที่ใช้งานอยู่เทรด** (XAUUSD, XAGUSD, EURUSD)
  symbol ของ broker profile อื่นไม่จำเป็น — ถ้าไม่มี ระบบจะบอกไว้ใน `feed_note`
- `warmup_bars` ต้องพอกับหน้าต่างที่ analysis/forecast ใช้: forecast ต้องมี M5 ≥ 260 แท่ง
  (≈ 1,300 แท่ง M1) และ analysis ขอ M5 900 / M15 600 / H1 500 / H4 300 →
  ในทางปฏิบัติควรมีข้อมูลอย่างน้อย **6,000–10,000 แท่ง M1** ต่อ symbol
- ระหว่างเดิน: `GET /api/system/health` → `feed_mode: "replay"`, `feed.symbols[*].progress`,
  และ `analysis.data_quality.feed = "replay"` (label บอกแหล่งข้อมูลจริง ไม่ได้ดูจากชนิด adapter)
- เมื่อข้อมูลหมด: clock หยุด, `services.feed = "exhausted"`, ไม่มีแท่งใหม่ถูกสร้างขึ้นมาเอง
- replay ยังไม่ใช่ tick data — ราคาภายในแท่งเดินตามเส้นทาง open→close ในกรอบ high/low

คำสั่งตรวจเร็ว ๆ ว่า replay ทำงาน: `python scripts/smoke.py` แล้วดูบรรทัด `feed`

## 6. ข้อจำกัดที่ยังต้องรู้
- `ai.training.max_rows` (12,000) คือเพดานจำนวน sample ต่อการฝึก และ trainer ทำ stride
  ทุก 5 แท่ง → ฐานข้อมูลจริงประมาณ ~60,000 แท่งต่อรอบฝึก ถ้ามากกว่านั้นใช้เฉพาะช่วงท้าย
- walk-forward ต้องมี sample อย่างน้อย `walk_forward_min_train_rows` (900) ในช่วงฝึกแรก
  → ถ้าข้อมูลน้อยกว่านั้นจะถอยไปใช้ block slices (และรายงานว่าถอย)
- spread ต่อแท่งมาจากค่า `spread_typical_points` ของ symbol (ไม่ใช่ spread จริงรายแท่ง)
- ยังไม่มี tick data จริง → การทดสอบ slippage/queue ในระดับ tick ยังทำไม่ได้

## 7. ตรวจว่าข้อมูลที่นำเข้าใช้ได้จริง

```bash
.venv/bin/python -m pytest tests/test_dataset_import.py -q
```

ชุดทดสอบนี้ล็อกพฤติกรรมที่เคยพลาด: pandas 3 อ่านเลข epoch เป็นนาโนวินาที (ทำให้ทุกแท่งยุบเหลือแท่งเดียว),
naive timestamp ที่ถูกตีความเป็น UTC (เลื่อนทั้งชุด), แท่งซ้ำ, และ OHLC ที่ขัดกันเอง

## Snapshot: แท่งเทียนที่ backtest ใช้ (reproducible)

ทุกครั้งที่รัน backtest ระบบจะเขียนแท่งเทียนที่ใช้ลง snapshot และเก็บ id + sha256 ไว้ใน report

- ที่เก็บ: `<configured workspace datasets>/snapshots/DS-<hash>.csv.gz` + `.json` (manifest)
- **id มาจากเนื้อข้อมูล** (`sha256` ของแท่งเทียน) → ข้อมูลเดิมได้ id เดิม เสมอ, บันทึกซ้ำไม่เปลืองที่
- รันซ้ำบนข้อมูลชุดเดิม: `POST /api/backtests {"symbol":"XAUUSD","snapshot_id":"DS-XXXXXXXXXX"}`
  → โหลดแท่งเทียนจากไฟล์, **ตรวจ sha256 ก่อนคำนวณ**, แล้วรายงานผลพร้อม `dataset.sha256` เดิม
- ถ้าไฟล์ถูกแก้/แทนที่ → ระบบ **ปฏิเสธ** (`400`, "corrupted … refusing to backtest on changed data")
  เพราะ "รันซ้ำ" บนข้อมูลอื่นไม่ใช่การรันซ้ำ

API:

| endpoint | ทำอะไร |
|---|---|
| `GET /api/datasets?limit=` | snapshot ล่าสุด (newest first) |
| `POST /api/datasets {symbol,timeframe,bars}` | freeze ข้อมูลที่ feed ให้อยู่ตอนนี้ |
| `GET /api/datasets/{id}` | manifest + ตรวจ hash (`verified:true`) + 3 แท่งตัวอย่าง |

ข้อจำกัด: snapshot เก็บ M1 bars เท่านั้น — ไม่มี tick และไม่มี intra-bar path
(การเรียง stop/target ภายในแท่งยังเป็นการประมาณแบบ conservative)

### Snapshot artifact guards (H063)

- Loader derive data path จาก configured root และ ID เท่านั้น ไม่ใช้ `manifest.path` เป็นสิทธิ์เลือกไฟล์
  manifest ต้องมี schema/root/path/id/full digest ที่ตรงกัน; linked root/manifest/data ถูกปฏิเสธ
- ตรวจ decompressed bytes กับ SHA-256 ก่อน parse แล้วตรวจ canonical digest, rows, bytes, first/last timestamps;
  malformed JSON/gzip/deflate คืน `SnapshotError` ไม่เผย raw decoder exception
- Save reuse ได้เมื่อโหลดและตรวจ artifact เดิมผ่าน และ symbol/timeframe/source ตรง;
  existing incomplete/corrupted/legacy evidence ถูกปฏิเสธ ไม่ซ่อม เขียนทับ หรือ adopt อัตโนมัติ
- Legacy snapshot ไม่มี schema/root ใหม่จะโหลดไม่ได้; อย่าแก้ manifest เติมหลักฐานเองเพื่อข้าม guard
  เก็บ evidence เดิมไว้และสร้าง snapshot ใหม่จาก source ที่ตรวจแล้วใน root ว่างที่ได้รับอนุญาต
- Listing ตรวจ manifest/path shape และการมีไฟล์ ไม่ใช่ full content verification;
  detail/load/backtest ตรวจ hash จริงก่อนใช้ข้อมูล
- Content-addressed ID ยังใช้ hash prefix 40 bits; พบ identity/content conflict จะปฏิเสธ ไม่เขียนทับ
  ยังไม่มี DB-backed provenance/signature, decompression size budget, atomic crash publication,
  concurrency acceptance หรือ root reparse/TOCTOU guarantees; tick loaders ยังต้องตรวจต่อ
