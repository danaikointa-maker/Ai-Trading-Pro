# บันทึกงานต่อเนื่อง U06–U10: Position Size Calculator

วันที่: 2026-11-23  
Branch: `feature/u06-u10-followup-v4-20261123`  
ขอบเขต: เพิ่ม calculator item แรกใน U08 โดยไม่เปิดใช้งานการส่งคำสั่งซื้อขาย

## Gap และการเปลี่ยนแปลง

- ตรวจคิว V4 แล้ว U06 ยังต้องการ broker/Demo acceptance, U07 ยังไม่มีโหมดคุ้มครอง Manual/Semi-Auto/Full-Auto/Hybrid, U08 มี catalog แต่ยังขาดเครื่องมือ และ U11 Demo acceptance ยัง BLOCKED
- เพิ่ม `position_size_calculator` ใน shared Risk Engine calculator core; ไม่สร้าง math engine หรือ execution gateway ใหม่ และไม่เปลี่ยน `TradePlanner.lot_for_risk` สำหรับการส่งคำสั่งจริง
- หน้า Points Calculator มีแท็บ Position size ที่รับ equity จำลอง, risk %, และ SL points ด้วยตนเอง พร้อมระบุ `MANUAL · SANDBOX`; ไม่อ่านหรือบันทึกยอดจริง
- ใช้ market-data specification ชุดเดียวกับกราฟและ Points → P&L รวมถึง MT5 Demo publisher spec ที่สดและผ่าน allowlist; regression ยืนยันว่าค่า point size, cost, สกุลบัญชี และ lot มาจาก spec เดียวกัน
- คำนวณความเสี่ยงด้วย symbol/account-currency specification ที่ตรวจได้ รวม typical spread และ round-turn commission, ปัด lot ลงตาม broker step, และไม่เพิ่มเป็น minimum lot หากเกินงบ
- ไม่ทราบสเปกหรืออัตราแปลงเงินจะไม่แสดง lot; ค่าขอบเขตตัวเลขที่ใหญ่เกินช่วงรองรับถูกปฏิเสธหรือจำกัดที่ max lot ตามสเปกก่อนคำนวณ
- API คง route เดิม `/api/risk/calculator`; ส่งพารามิเตอร์ position sizing มาไม่ครบตอบ 422; ไม่มีการเรียก submit/order/modify/close

## ผลตรวจ

| รายการ | ผล |
|---|---|
| `tests/test_points_math.py tests/test_api.py tests/test_invariants.py -q` | PASS — 75 passed, 1 existing Starlette/httpx deprecation warning |
| U06–U10 wider Python regression set | PASS — 289 passed, same existing deprecation warning |
| Ruff E9/F/I, Python compileall, `git diff --check` | PASS |
| Vite 5.4.21 production build | PASS — 626 modules transformed |
| MT5 live account/spec comparison | NOT TESTED |
| UI browser/role visual acceptance | NOT TESTED |
| Remaining calculator tools, export, save, and learning center | NOT IMPLEMENTED; U08 stays PARTIAL |
| Demo/Live trade or Auto activation | NOT DONE |

## Rollback และงานถัดไป

Rollback ได้ด้วย revert เฉพาะ commit นี้; ไม่มี config migration, DB/schema change, runtime deployment หรือ VM change. ทำงานต่อในคิว V4 ตาม dependencies โดยรักษา U06/U07/U08/U11 ที่ยัง partial หรือ blocked; ห้ามยกสถานะเป็น DONE จนมีหลักฐาน acceptance ครบ.
