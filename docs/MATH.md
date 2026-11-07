# สูตรคำนวณทั้งหมด (และจุดที่ยังเป็นการประมาณ)

เอกสารนี้ตอบคำถามว่า "ตัวเลขบนหน้าจอมาจากสูตรอะไร" และ "สูตรไหนยังไม่เป๊ะ"
ทุกข้อที่มีเครื่องหมาย ✅ มี test ครอบอยู่ใน `tests/test_invariants.py` และ `tests/test_currency.py`

## 1. หน่วยราคา (points)

```
value_per_point_per_lot = point × contract_size × quote_to_account_rate
                                                    # XAUUSD: 0.01 × 100 × 1.0 = $1.00
price_move(points)      = points × point            # 500 pts × 0.01 = 5.00 USD
gross_profit            = points × value_per_point_per_lot × lot

pnl_account = Δprice_signed × contract_size × lot × quote_to_account_rate
              # Δprice_signed = (exit − entry) สำหรับ long, (entry − exit) สำหรับ short
```

- `point`, `tick_size`, `contract_size`, `min_lot`, `lot_step`, `stops_level` **อ่านจากโบรกเกอร์**
- ราคาทุกจุดถูก snap ลงกริด `tick_size` ✅ (`SymbolSpec.round_price`)
- `quote_to_account_rate` แปลงกำไรจากสกุล quote → สกุลบัญชี และ **ถูกใช้เหมือนกันทุกเอนจิน** ✅
  (`SymbolSpec.pnl_in_account_currency` → backtest, paper, MT5 offline estimate, risk notional)
- ตัวอย่าง USDJPY (quote = JPY, rate = 1/157.2): ราคา +0.5 บน 0.1 lot
  = 0.5 × 100,000 × 0.1 = 5,000 JPY = **31.81 USD** (ไม่ใช่ 5,000 USD)
- ⚠️ ถ้า resolve rate ไม่ได้ (`rate_source = "unknown"`) ระบบ **ไม่เดาเป็น 1.0**:
  `spec.sizing_blocked` หยุดการคำนวณ lot, MT5 offline estimate โยน `BrokerError`,
  และ position นั้นถูกตัดออกจาก notional exposure แทนการประเมินค่าผิด

## 1b. Swap (ค่าถือข้ามคืน)

โบรกเกอร์ประกาศ swap ได้ 3 หน่วยที่ **ใช้แทนกันไม่ได้** ระบบจึงเก็บ `swap_mode` ไปกับตัวเลขด้วย

```
money   : swap_night = swap_long_per_lot (หรือ short) × lot
points  : swap_night = swap_points × point × contract_size × quote_to_account_rate × lot
percent : swap_night = notional × pct / 100 / 360 × lot        # ดอกเบี้ยรายปี ฐาน 360 วัน
          notional = price × contract_size × quote_to_account_rate
```

- คิด **คืนละครั้ง** ทุกเที่ยงคืน UTC และ **วันพุธคูณ 3** (โบรกเกอร์รวม funding ของสุดสัปดาห์ไว้คืนพุธ)
  ✅ `swap_night_multiplier()` ใน `models.py` ใช้ร่วมกันทั้ง paper และ backtest
- คิดบน volume ที่ยังเปิดอยู่ ณ คืนนั้น (partial close แล้วลดตามจริง)
- MT5: `swap_mode` ของเทอร์มินัลถูกแปลงเป็นหน่วยของเรา (`_swap_fields`)
  1 → points, 3/5 → percent, 2 → money (แปลง profit currency → สกุลบัญชี), 6/7 (reopen) → 0
- รายงานแยกเป็นฟิลด์ `swap` ใน `TradeRecord` ไม่ปนกับ `costs` (ค่าคอมมิชชัน)
  และ `gross_pnl - pnl = costs - swap` ✅ `tests/test_swap.py`

## 2. ขนาดไม้ (lot)

```
risk_amount = equity × risk_pct / 100
loss_per_lot = sl_points × value_per_point_per_lot
raw_lot      = risk_amount / loss_per_lot
lot          = floor_to_step(raw_lot, lot_step)  # ไม่ปัดขึ้น — ห้ามเสี่ยงเกินงบ ✅
if raw_lot < min_lot → ไม่มีแผน (blocker) หรือใช้ min_lot พร้อมรายงาน
```

ตัวอย่าง: equity 10,000, risk 0.5% = $50, SL 534 pts → 0.09 lot → ความเสี่ยงจริง $48.06 ✅

## 3. Stop

```
vol_floor = max(0.75 × ATR, 4 × spread, sl_min_points 150)
SL        = โครงสร้างใกล้สุด (แนวรับ/แนวต้าน หรือ swing) ± 0.35 ATR
ถ้า SL < vol_floor → ขยายเป็น vol_floor (บันทึกใน notes)
ถ้า SL < stops_level → ขยายเป็น stops_level + 1 ✅
```

## 4. Ladder TP (500–1,000 points)

```
TP1 = clip(ATR × 2.2, 500, 1000)        # adaptive
TP2 = TP1 + (1000 − TP1) × 0.5
TP3 = 1000
ถ้ามีโซนต้าน/รับคุณภาพสูงขวางทาง → cap TP1 ก่อนโซน (ห่าง 0.35 ATR) ✅
```

## 5. Reward/Risk และการตัดสิน

```
cost_points   = spread/2 + commission_per_lot_round_turn / value_per_point_per_lot
                (entry ถูกส่งที่ ask/bid อยู่แล้ว จึงเหลือครึ่ง spread ตอนออกบัญชี)
rr_gross      = avg(TP × close%) / SL
rr_net        = (avg(TP × close%) − cost) / (SL + cost)
rr_net_tp1    = (TP1 − cost) / (SL + cost)
```

เงื่อนไขผ่าน: `rr_net ≥ min_reward_risk (1.3)` **และ** `rr_net_tp1 ≥ 1.0` ✅
(เดิมเช็คแค่ค่า blended ซึ่งแปลว่า "ถ้า TP3 ถึงจริงถึงจะคุ้ม")

```
p_be  = (SL + cost) / (SL + TP1)          # break-even probability (รวมต้นทุน) ✅
EV    = p × profit(TP1 − cost) − (1 − p) × loss(SL + cost)    ✅
```

## 6. Probability ที่ TP ถึงก่อน SL

สร้างตารางจากประวัติของสัญลักษณ์เอง (หน่วย ATR):

```
สำหรับทุกแท่ง i และทุก horizon h:
  high_rel[i,k] = (running max ของ high ภายใน k แท่ง − close[i]) / ATR[i]
  low_rel [i,k] = (running min ของ low  ภายใน k แท่ง − close[i]) / ATR[i]
win_long  = P(ถึง TP ก่อน SL) ในฝั่งซื้อ (เสมอกันในแท่งเดียว = แพ้)
p_tp_before_sl = p_up × win_long + (1 − p_up) × win_short      (ฝั่ง SELL สลับ)
```

- เป็น **empirical** จากข้อมูลจริง ไม่ใช่สูตรสำเร็จ
- เสมอกัน (ชนทั้งสองในแท่งเดียว) นับเป็นแพ้ → อนุรักษ์นิยม ✅
- ⚠️ เป็นการผสมแบบไม่ปรับ conditional เต็มรูปแบบ: `win_long` เป็นค่าเฉลี่ยทั้งตัวอย่าง
  ไม่ได้ conditioning บนสภาวะตลาดปัจจุบัน — ระบุใน coverage note ของ API

## 7. Forecast

```
q10 ≤ q50 ≤ q90                      (บังคับ เรียงใหม่ถ้า quantile ไขว้กัน) ✅
p_up + p_down + p_sideways = 1       (normalize หลัง clip) ✅
P10/P90 price = price + q × ATR_now
volatility_points = ATR_now × sqrt(horizon / 5) / point ✅
scenario path: median(t) = price + (target − price) × sqrt(t/H)
               band(t)   = ± (P90−P10)/2 × sqrt(t/H)     → เป็นช่วงเสมอ ไม่ใช่เส้นเดียว ✅
```

## 8. Backtest metrics

```
win_rate            = wins / trades (pnl > 0)
profit_factor       = gross_profit / gross_loss   (ถ้าไม่มีไม้ขาดทุน → cap 99) ✅
expectancy          = net / trades
expectancy_r        = mean(pnl / risk_at_fill)     # risk ที่วัดตอน fill จริง ✅
directional_accuracy= สัดส่วนไม้ที่ราคาไปถูกทาง (points > 0) ไม่นับต้นทุน ✅
tp_before_sl_rate   = สัดส่วนไม้ที่แตะ target อย่างน้อย TP1 ก่อนค่อยโดน stop ✅
max_drawdown_pct    = max |equity − peak| / peak
no_trade_rate       = 1 − trades / decisions
sharpe              = mean(bar returns)/std × sqrt(252×288)   (แท่ง 5 นาที)
recovery_factor     = net / (max_dd × starting_balance)
```

`equity` ระหว่าง backtest = balance (บวก/ลบ pnl ที่ปิดแล้ว) + floating ของไม้ที่เปิด ✅
(ก่อนหน้านี้ balance ไม่ถูกอัปเดต ทำให้ equity แบนและ return = 0)

## 9. สิ่งที่ยังเป็นการประมาณ (ไม่ใช่บั๊ก แต่ต้องรู้)

| เรื่อง | สถานะ |
|---|---|
| ต้นทุน spread ใน backtest | ใส่ที่ราคาเข้า (bid/ask + slippage) แต่SL/TP ตัดสินจากราคา mid ของแท่ง |
| SL/TP ชนในแท่งเดียวกัน | เลือก stop ก่อน target (อนุรักษ์นิยม) |
| ค่าธรรมเนียม | ใช้ `commission_per_lot_round_turn` จาก spec (ถ้าโบรกเกอร์ไม่ให้มา = 0) |
| swap | คิดตามโหมดที่โบรกเกอร์ประกาศ (money / points / percent) |
| สกุลเงินกำไร ≠ USD | แปลงด้วย `quote_to_account_rate` แล้ว ✅ (ถ้า resolve ไม่ได้ = บล็อกการคำนวณ lot) |
| walk-forward | แบ่งข้อมูลเป็น fold ตามเวลาและ **ฝึกใหม่ทุก fold** (expanding window) ต้องผ่านเกณฑ์ใน ≥75% ของ fold; ยังประเมินบน feed จำลอง |
| Sharpe | annualise จากแท่ง 5 นาที; ช่วงที่ไม่มีไม้จะได้ return = 0 ทำให้ค่าสูงเกินจริงได้ |

## 9b. เกณฑ์อนุมัติโมเดล (fold consistency)

```
approved_horizon = (fold_pass_rate >= 0.75)
                 ∧ (median directional accuracy ของ fold >= 0.52)
                 ∧ (median Brier improvement ของ fold >= 0.02)
                 ∧ (directional accuracy รวม >= 0.52)
                 ∧ (Brier improvement รวม >= 0.02)
```

- fold = บล็อกต่อเนื่องตามเวลาภายในข้อมูล (`split_folds`, ไม่สุ่ม)
- เดิมตัดสินจาก slice เดียว → โมเดลที่ฟลุ๊กเดือนเดียวก็ผ่าน ทำให้ `approved` แกว่งระหว่างรอบ
- ตอนนี้ **เข้มขึ้น** ไม่ใช่ผ่อน: ต้องผ่านทั้งค่ากลางและสัดส่วน fold

### วิธีสร้าง fold (walk-forward)

```
blocks = split_folds(n_rows, folds + 1)      # บล็อกแรก = ช่วงฝึกเริ่มต้น
for block_i in blocks[1:]:
    train_end = block_i.start × (1 − calibration_fraction)
    ถ้า train_end < walk_forward_min_train_rows → ข้าม fold (ประวัติไม่พอ)
    fit classifier บน rows[:train_end]        ← ฝึกใหม่ทุก fold
    score บน rows[block_i]                    ← ข้อมูลที่โมเดลนั้นไม่เคยเห็น
```

- ประเมินเฉพาะ **classification** (directional accuracy + Brier เทียบ prior ของ training window)
  ส่วน quantile regressors ไม่ถูก refit ใน fold (ไม่ได้ใช้ตัดสิน gate) → fold ละ 1 fit
- ถ้าข้อมูลไม่พอจนได้ fold < 2 จะถอยไปใช้วิธี "แบ่ง slice ของโมเดลที่ fit แล้ว"
  และ `metrics.validation_method` จะบอกว่าใช้วิธีไหน
- ยังประเมินบน **feed จำลอง** — ตัวเลขบอกได้ว่าไปป์ไลน์ถูก ไม่ได้บอกว่าโมเดลมี edge จริง

## 10. บั๊กสูตรที่แก้ในรอบนี้

1. `lot` ปัดขึ้นเป็น step ใกล้สุด → เสี่ยงเกินงบ → เปลี่ยนเป็นปัดลง ✅
2. ราคาไม่ snap ตาม `tick_size` (เฉพาะ `digits`) ✅
3. TP/partial volumes รวมแล้วไม่เท่า lot และอาจปิดเกินขนาดจริง ✅
4. ไม่บังคับ `stops_level` ของโบรกเกอร์ ✅
5. เช็ค R:R เฉพาะค่า blended (ต้องรอ TP3) → เพิ่มเงื่อนไข TP1 ≥ 1R ✅
6. `profit_factor` คืนค่าเป็น **จำนวนเงิน** เมื่อไม่มีไม้ขาดทุน (`314.77`) → cap 99 ✅
7. `directional_accuracy` ใช้ win_rate (ปนต้นทุน) → วัดจากทิศทางจริง ✅
8. `tp_before_sl_rate` นับเฉพาะ exit สุดท้าย → นับ "แตะ target ก่อน stop" ✅
9. Quantile ไขว้กันไม่ถูกแก้ → บังคับเรียง ✅
10. Scenario fan ใช้ quantile ข้าม horizon และจบไม่ตรง target → แก้ให้จบที่ target ของตัวเอง ✅
11. `exposure_pct` ใช้ contract 100,000 คงที่กับทุก symbol → ใช้ notional จริง ✅
12. `open_time` ของ paper broker ใช้นาฬิกาจริง ขณะที่ตัวจัดการใช้เวลา virtual → time-exit เร็วเกิน ✅
13. `open_positions` mirror ลบแถวที่ปิดแล้วไม่ครบ → reconcile รายงาน mismatch ปลอม ✅
14. โซน/อินดิเคเตอร์คำนวณรวมแท่งที่ยังไม่ปิด → ใช้เฉพาะแท่งปิด (no repainting) ✅
15. ส่งคำสั่งซ้ำเมื่อ error → ไม่ส่งซ้ำอีก, ตรวจกับโบรกเกอร์แล้วรายงาน ✅
16. RSI ตลาดแบนคืนค่า 100 → คืน 50 ✅
17. `partials.enabled` ใน config ไม่ถูกอ่าน (เปิดตลอด) → อ่านค่าจริง ✅
18. R multiple ใน backtest ใช้ risk ที่วางแผนไว้ ไม่ใช่ risk ตอน fill → วัดใหม่ที่ fill ✅
19. **หน่วยผิด**: เงินเสี่ยงใน backtest เอา "ระยะราคา" ไปคูณเป็น points โดยไม่หาร `point`
    (SL 200 points กลายเป็น risk $0.49 แทน $48.72 ทำให้ R multiple เพี้ยนเป็น 11R) → แก้แล้ว ✅
20. R multiple ของ paper broker ใช้ SL ที่ถูกเลื่อน (trailing/BE) เป็นตัวหาร → ใช้ SL ตอนเปิดไม้ ✅
21. ถ้าราคา fill gap ไปจนชิด stop หรือเลย TP1 → ข้ามไม้นั้นและรายงานจำนวนที่ข้าม ✅
22. `max_spread` ใน gate เทียบกับ spread ปัจจุบัน แต่ spread ใน backtest ถูก fix ค่าเดียว → ระบุใน assumptions
23. `total_costs` รายงานแค่ค่าคอมมิชชั่น (XAUUSD = 0) ทั้งที่ราคา fill มี spread 12.5 points ฝังอยู่
    → บันทึกต้นทุนฝั่งเข้าเป็นเงินด้วย ทำให้ `gross_pnl − pnl == costs` เสมอ (ทั้ง paper และ backtest) ✅
    ข้อควรระวัง: ต้นทุนนี้อยู่ในราคาแล้ว จึงหักจาก balance ซ้ำไม่ได้ (มี test ล็อกไว้)
