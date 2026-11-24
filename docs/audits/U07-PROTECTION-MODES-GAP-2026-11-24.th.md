# U07 — ตรวจช่องว่างโหมด Position Protection (2026-11-24)

## ขอบเขตและผลตรวจ

ตรวจ `services/risk_engine/manager.py`, `services/api_gateway/state.py`, `services/api_gateway/routes/risk.py`, `packages/shared_schemas/models.py`, `config/risk.yaml`, `config/risk_v4_candidate.yaml`, tests ของ PositionManager และเอกสาร Protection V1.1 / Unified Master Plan V4 บน baseline `699d095`.

| ความสามารถ | สถานะ | หลักฐาน |
|---|---|---|
| Entry mode Manual / Semi-Auto / Full Auto | มีบางส่วน | `TradeMode` และ `/api/trading/mode` เป็นโหมดเปิดออเดอร์ ไม่ใช่โหมดจัดการตำแหน่ง |
| PositionManager BE / trailing / partial / exit | มี | `PositionManager.evaluate()` อ่าน `config/risk.yaml` และ `_manage_cycle()` ส่ง actions ไป gateway |
| Manual / Semi / Full / Hybrid สำหรับ position protection | ยังไม่มี | ไม่พบ enum, API, UI, scoped persistence, version หรือ approval/pause state สำหรับโหมดเหล่านี้ |
| Broker modify safety | มีบางส่วน | Gateway เดิมและ Paper readback tests มี; broker Demo reconciliation/restart acceptance ยังไม่ผ่าน U05 |
| Per-account / per-position override | ยังไม่พร้อม | ไม่มี protection-mode owner/version ที่เชื่อมกับ broker account identity และ ticket lifetime |

## พฤติกรรมสำคัญที่ต้องรักษา

`_manage_cycle()` เรียก PositionManager และใช้ actions โดยไม่ตรวจ `runtime.mode`; ดังนั้น entry mode ที่แสดงว่า Manual ไม่ได้แปลว่า BE/trailing/partial management ปิดอยู่. พฤติกรรมปัจจุบันถูกกำหนดจาก `config/risk.yaml` ซึ่งเปิด BE, trailing, partials และ smart exits. การเปลี่ยนความหมายของ Manual หรือการเพิ่มปุ่ม mode แล้วต่อเข้ากับ runtime โดยตรง อาจหยุดหรือเริ่มคำสั่ง modify/close ที่มีผลกับบัญชี จึงห้ามเปลี่ยนค่าเดิมหรือเปิด mode ใหม่ในงาน audit นี้.

V1.1 กำหนดความหมายที่นำไปใช้ต่อได้: Manual = preview/apply โดยผู้ใช้; Semi-Auto = proposal + explicit approval + re-evaluation; Full Auto = Demo ที่อนุญาตไว้และผ่าน guards; Hybrid = protected auto พร้อม pause/override ราย position. ต้องเชื่อมกับ durable single-writer/reconciliation ของ U05 ก่อนใช้จริง.

## ผลตรวจและทดสอบ

- `tests/test_roles.py tests/test_risk_engine.py tests/test_v4_single_target_manager.py`: **41 passed**, warning เดิม Starlette/httpx 1 รายการ.
- สิ่งนี้ยืนยัน entry-mode authorization และ PositionManager/Paper slices เท่านั้น; ไม่ใช่หลักฐานว่าโหมดคุ้มครองตำแหน่ง, account A/B isolation หรือ MT5 Demo modify ผ่านแล้ว.
- ไม่มีการแก้ `config/risk.yaml`, เปลี่ยนบัญชี, ส่งคำสั่ง broker หรือเปิด Auto/Live.

## ลำดับดำเนินงานเมื่อ dependency พร้อม

1. ปิด U05 durable modify/reconciliation และยืนยัน broker account identity โดยไม่ใช้ Live.
2. เพิ่ม protection-mode schema แบบ versioned และ scoped ด้วย account identity hash; default เป็น legacy behavior เพื่อไม่ย้าย config เดิมอัตโนมัติ.
3. เพิ่ม read-only effective settings/preview ก่อน; mutation ทุกจุดต้องมี RBAC, expected version, account/ticket scope และ audit.
4. ทำ Semi-Auto approval/re-evaluation และ Hybrid pause/resume โดย reuse PositionManager/ExecutionGateway เดิม.
5. เปิด Full Auto เฉพาะ DEMO หลัง explicit acceptance; Live คงปิด.

## สถานะ

U07 คง **PARTIAL / BLOCKED BY U05 ACCEPTANCE**. สามารถพัฒนาสัญญาและ tests แบบ inert ต่อได้ แต่ยังไม่มีหลักฐานพอให้สลับ runtime management modes อย่างปลอดภัย.
