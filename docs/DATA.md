# ข้อมูลจริง (Real data) — จากไฟล์ CSV สู่ตัวเลขที่ใช้อ้างอิงได้

> **ทำไมต้องมีขั้นนี้:** ค่าเริ่มต้นของระบบใช้ **feed จำลอง** (seed 7) ซึ่งพิสูจน์ได้แค่ว่าไปป์ไลน์ถูก
> ไม่ได้บอกว่าโมเดลมี edge จริง ตราบใดที่ยังรันบน feed จำลอง คำตอบที่ถูกของ gate คือ
> `UNVALIDATED` — และมันจะยังเป็นอย่างนั้นตลอดไป ไม่ว่าจะปรับ threshold เท่าไร

ไฟล์ CSV จากโบรกเกอร์/MT5 → นำเข้า → ประเมินด้วย trainer + backtest engine ตัวเดียวกับที่ dashboard ใช้

---

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

ผลลัพธ์: `storage/datasets/XAUUSD_M1.csv` (สคีมา `t,o,h,l,c,v` เวลาเป็น epoch UTC)
และ sidecar `XAUUSD_M1.meta.json` ที่บันทึก: จำนวนแท่ง, ช่วงเวลา, จำนวน gap,
จำนวนแท่งที่ถูกทิ้งเพราะซ้ำ, จำนวนแท่งที่ OHLC ขัดกันเอง, sha256 ของไฟล์ต้นฉบับ

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

## 5. ข้อจำกัดที่ยังต้องรู้

- **dashboard ที่รันอยู่ยังใช้ feed จำลอง** — ไฟล์นี้ใช้สำหรับ *ประเมิน* แบบ offline
  การสลับ feed สดทั้งระบบไปเป็น replay ยังไม่ได้ทำ
- `ai.training.max_rows` (12,000) คือเพดานจำนวน sample ต่อการฝึก และ trainer ทำ stride
  ทุก 5 แท่ง → ฐานข้อมูลจริงประมาณ ~60,000 แท่งต่อรอบฝึก ถ้ามากกว่านั้นใช้เฉพาะช่วงท้าย
- walk-forward ต้องมี sample อย่างน้อย `walk_forward_min_train_rows` (900) ในช่วงฝึกแรก
  → ถ้าข้อมูลน้อยกว่านั้นจะถอยไปใช้ block slices (และรายงานว่าถอย)
- spread ต่อแท่งมาจากค่า `spread_typical_points` ของ symbol (ไม่ใช่ spread จริงรายแท่ง)
- ยังไม่มี tick data จริง → การทดสอบ slippage/queue ในระดับ tick ยังทำไม่ได้

## 6. ตรวจว่าข้อมูลที่นำเข้าใช้ได้จริง

```bash
.venv/bin/python -m pytest tests/test_dataset_import.py -q
```

ชุดทดสอบนี้ล็อกพฤติกรรมที่เคยพลาด: pandas 3 อ่านเลข epoch เป็นนาโนวินาที (ทำให้ทุกแท่งยุบเหลือแท่งเดียว),
naive timestamp ที่ถูกตีความเป็น UTC (เลื่อนทั้งชุด), แท่งซ้ำ, และ OHLC ที่ขัดกันเอง
