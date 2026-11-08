## เปลี่ยนอะไร

<!-- หนึ่งย่อหน้า: ทำอะไร และทำไม (ปัญหาที่แก้ ไม่ใช่รายการไฟล์) -->

## พิสูจน์ยังไง

<!-- คำสั่งที่รันจริง + ผลจริง ไม่ใช่ "ควรจะได้" เช่น
     ./scripts/dev_check.sh  →  ruff clean · 410 passed · 150s
     curl .../api/system/health  →  {"status":"ok", ...}
     ถ้าแก้ UI: แคปหน้าจอหรือบอกหน้าที่เปิดดู -->

## ไฟล์กลางที่แตะ (บอกอีกทีมด้วย)

<!-- ติ๊กเฉพาะที่แตะจริง — พวกนี้คือจุดที่ PR สองทีมชนกันบ่อยที่สุด -->

- [ ] `services/api_gateway/app.py` (ลิสต์ router / ลำดับ middleware)
- [ ] `config/*.yaml` (คีย์ใหม่หรือค่า default)
- [ ] `requirements*.txt` / `apps/web-dashboard/package.json`
- [ ] `tests/conftest.py`
- [ ] schema ของฐานข้อมูล (`packages/persistence/`)
- [ ] ไม่แตะอะไรที่ใช้ร่วมกัน

## เอกสาร

- [ ] อัปเดตเอกสารที่เกี่ยวข้องแล้ว (`README.md`, `docs/API.md`, `docs/RUNBOOK.md`, `docs/MATH.md`, `docs/LIMITATIONS.md`)
- [ ] ไม่ได้เคลมเกินกว่าที่ทดสอบจริง (ของจำลอง ≠ ของจริง — ระบุไว้ชัดเจน)
- [ ] ไม่มีความลับ/โทเคน/รหัสผ่านใน diff

## เกต

- [ ] `./scripts/dev_check.sh` ผ่าน (ruff + dashboard bundle + pytest)
- [ ] merge `main` ล่าสุดเข้าสาขานี้แล้วก่อนขอรีวิว
