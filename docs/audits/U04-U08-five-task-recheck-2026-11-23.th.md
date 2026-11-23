# บันทึกทำงานต่อเนื่อง 5 งาน: U04–U08

วันที่: 2026-11-23 (Asia/Bangkok)  
Planning baseline: `f0b66f4e0e96b071f6b67840e9d34db34bcd469c` (U14–U18 PR #54 merged)
Work branch: `feature/u04-u08-five-task-v4`
ช่วงงาน: ตรวจและพัฒนาตาม Unified Task Register V4 โดยไม่เปลี่ยน runtime profile

## ผลงานรายงาน

### U04 — Initial SL/TP

- ใช้ `TradePlanner` และ `ExecutionGateway` เดิม ไม่สร้าง planner หรือ gateway ใหม่
- เพิ่มการตรวจ SL/TP ที่ร้องขอกับ position readback หลัง fill โดย normalize ตาม tick size ของ symbol จาก adapter
- เส้นที่หายไป ผิดค่า หรือหา symbol spec ไม่ได้ ทำให้ fill คงสถานะ unverified; gateway `unresolved_orders` จะปิดกั้น entry ใหม่จนกว่าจะ reconcile
- การตรวจตอน recovery ใช้กฎเดียวกัน และไม่ยืนยัน order จาก ticket/volume/entry เพียงอย่างเดียว
- `config/risk.yaml` และ candidate activation ไม่เปลี่ยน
- เพิ่ม MT5 adapter preflight สำหรับ side-correct SL/TP, broker stop/freeze distance, broker `order_calc_profit`, `order_calc_margin` และ `order_check`; ผลตรวจไม่ผ่านเป็น known no-send rejection และไม่เรียก `order_send`
- หลักฐานยังเป็น fake-terminal unit tests เท่านั้น; ไม่มี Connext-Demo order_check/margin/post-fill receipt จึงคงสถานะ PARTIAL / NOT ACCEPTED

### U05 — Execution/modify

- ตรวจ source และ regression ของ durable intent ledger ที่เพิ่มในงานก่อนหน้า; ยังคงใช้ `ExecutionGateway` และ position-event ledger เดิม
- ไม่แทน checkout หรือฐานข้อมูล VM100 เพราะ staging parity, backup/restore และ Demo modify/readback ยังไม่มีหลักฐานรับรอง
- สถานะ PARTIAL / BLOCKED คงเดิม: ต้องได้ U01 fresh verified quote และทำ Demo modify/reconciliation ที่ได้รับอนุมัติก่อน

### U06 — Position protection

- เพิ่ม Paper integration regression: `PositionManager` สร้าง trailing SL intent → `ExecutionGateway.modify` → `PaperBroker` readback → durable intent เป็น `confirmed`
- ทดสอบทั้งการคง TP เดิมและการเลื่อน SL ในทิศทางลดความเสี่ยง
- ใช้ test settings เฉพาะกรณี; ไม่เปิด management policy ใน runtime profile
- สถานะ PARTIAL / NOT ACCEPTED จนกว่าจะมี broker stops/freeze, restart/ambiguous-ack และ Demo reconciliation evidence

### U07 — Operating modes

- ตรวจ role/mode regression เดิม: การเปลี่ยน Full Auto switch และเปิด entry mode ยังอยู่หลัง admin/security lock; startup ปิดโหมดค้างเมื่อ security switch ไม่อนุญาต
- ยังไม่มี Manual/Semi-Auto/Full-Auto/Hybrid position-protection modes พร้อม account-scoped versioned overrides
- คง PARTIAL; ไม่เปิด Full Auto

### U08 — Calculators

- ตรวจ calculator shared core ที่มีอยู่และชุดทดสอบ account-currency/FX provenance; ไม่ทำ math ซ้ำใน UI หรือ backend
- นิยาม catalog เครื่องมือ read-only 16 รายการจาก Master Task ที่ผู้ใช้ให้ไว้ใน `docs/calculators/TRADING-CALCULATOR-16-TOOL-CATALOG-V4.md`; ยังต้อง implement tools/UI/export/lessons และเทียบผลเงินกับ MT5 account/spec จริง
- คง PARTIAL; การเทียบเงินจริง NOT TESTED

## หลักฐานการตรวจ

- U04–U08 focused regression command ครอบคลุม MT5 preflight/account continuity, planner, execution/recovery, position protection, modify intents, roles, risk, points/spec safety, invariants และ API: **304 passed, 1 pre-existing Starlette/httpx deprecation warning**
- API deep-link smoke `/`, `/forecast`, `/risk` อยู่ใน `tests/test_api.py` และรวมอยู่ในผล 304 tests แล้ว
- Dashboard production build: Vite 5.4.21, **626 modules transformed**, build ผ่าน
- `ruff --select E9,F`, `compileall` และ `git diff --check`: ผ่าน
- `npm ci` รายงาน dependency advisories **2 moderate และ 1 high**; ไม่ได้รัน auto-fix หรือแก้ lockfile ในงานนี้

## ยังไม่ได้ทดสอบ / ห้ามสรุปเกินหลักฐาน

- MT5 `order_check`, margin, stops/freeze response และ post-fill SL/TP บน broker จริง: NOT TESTED
- U05 staging runtime replacement/restart, backup restore และ Connext-Demo modify/readback: NOT TESTED
- U06 Demo protection lifecycle และ power-loss/ambiguous acknowledgement: NOT TESTED
- U07 protection-mode overrides: MISSING / NOT TESTED
- U08 account-currency money comparison กับ MT5: NOT TESTED
- U01 fresh verified MT5 quote/clock และ U11 Demo acceptance: ยัง BLOCKED
- ไม่ส่งคำสั่ง Demo/Live, ไม่เปิด Auto, ไม่ deploy และไม่แก้ runtime config

## Rollback และงานต่อ

- Rollback งานนี้โดย revert เฉพาะ commit ใน branch นี้; ไม่มี config migration, schema change หรือการเขียนฐานข้อมูล VM
- เดินคิวถัดไป U09–U13: dashboard acceptance, alert idempotency, Demo gate (รอ U01 และการอนุมัติแยก), AI Trader Team gap, และ doc sync ตาม register

## U04/U08 implementation follow-up — 2026-11-23

- U04 reuses the existing `MT5Broker` and `ExecutionGateway`; no second planner, order gateway, or execution path was added. A fake-terminal regression covers protective BUY/SELL geometry, broker stop/freeze distance, missing/non-loss stop P/L, unavailable or excessive margin, invalid/rejected `order_check`, and confirms preflight failure never invokes `order_send`.
- Focused command: `pytest tests/test_mt5_order_preflight.py tests/test_mt5_account_continuity.py tests/test_v4_plan_candidate.py tests/test_execution_recovery.py -q` — **134 passed**. Ruff E9/F/I and `compileall` passed.
- U06 Paper integration adds a lost-ack case and confirms exact broker readback without a second modification: `pytest tests/test_v4_single_target_manager.py -q` — **9 passed**. PaperBroker data is isolated to a temporary test database.
- U08 catalog scope is now concrete and linked from the Task Register. This is requirements documentation, not implementation; no API, database, UI, exporter, FX request, or trade side effect was added.
- Real broker P/L/margin/order_check, accepted stops/freeze behavior, post-fill SL/TP readback, account-currency comparison, and Demo execution remain **NOT TESTED**. The V4 candidate remains inactive; no broker account, runtime profile, service, or VM changed. PaperBroker was used only in isolated automated tests; no user Demo or Live trade was placed.
