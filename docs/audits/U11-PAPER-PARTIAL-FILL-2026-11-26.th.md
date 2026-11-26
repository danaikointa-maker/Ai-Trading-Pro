# U11 Paper partial-fill safety check — 2026-11-26

ฐาน: `plan/unified-development-v4` ที่ `bf69e982b9d5cfbc4a09eb38759d189b44b00ff0`

## ช่องว่าง

มี regression สำหรับ timeout/lost acknowledgement, fill ที่ volume ไม่ตรง และ MT5 mocked preflight อยู่แล้ว แต่ยังไม่มี Paper test ที่ส่งผล `partially_filled` จริงให้ gateway แล้วตรวจว่า order เดิมไม่ถูกส่งซ้ำและไม่เปิด entry ใหม่ระหว่างสถานะยังคลุมเครือ

## การเปลี่ยนแปลง

- เพิ่ม `_PartialFillPaperAdapter` ใน `tests/test_paper_reconnect_recovery.py`; adapter ห่อ `PaperBroker` เดิมและจำลอง fill เพียงครึ่ง volume โดยไม่ใช้ MT5 หรือ network
- ยืนยันว่า partial result ถูกบันทึกเป็น `partially_filled`, ไม่ถูกทำเครื่องหมาย verified, replay intent เดิมไม่เรียก send ซ้ำ และ intent ใหม่ถูกปฏิเสธด้วย unresolved-order fence
- ไม่แก้ execution behavior, database, API, config หรือ broker adapter production

## Verification

คำสั่ง regression:

```text
& 'C:\workspace\Ai-Trading-Pro\.venv\Scripts\python.exe' -m pytest tests/test_paper_reconnect_recovery.py tests/test_execution_recovery.py tests/test_mt5_order_preflight.py tests/test_mt5_account_continuity.py -q
```

ผล: **122 passed**. ชุด Paper-only ก่อนรวม: **2 passed**.

## ข้อจำกัดและสถานะ

U11 ยังคง **BLOCKED**. ผลนี้เป็น deterministic Paper/mocked evidence เท่านั้น ไม่ได้พิสูจน์ MT5 Demo partial fill, process power-loss, broker history reconciliation หรือ rollback จริง ไม่มีคำสั่ง broker ถูกส่ง, ไม่มีบัญชีถูกเปลี่ยน และ Live/Auto ไม่ถูกเปิด

## Rollback

เป็น test-only change; revert test และ audit นี้ได้ ไม่มี runtime หรือ persistence migration
