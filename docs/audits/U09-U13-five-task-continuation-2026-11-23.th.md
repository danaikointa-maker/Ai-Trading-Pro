# บันทึกทำงานต่อเนื่อง 5 งาน: U09–U13

วันที่: 2026-11-23 (Asia/Bangkok)  
Planning baseline: `4fa6335`  
Work branch: `feature/u09-u13-five-task-v4`  
คิวอ้างอิง: `docs/UNIFIED-TASK-REGISTER-V4.md`

## ผลงานรายงาน

### U09 — Dashboard

- ตรวจ chart viewport, latest-bar tracking, markers และ symbol matching ซ้ำ: 7 test ผ่าน
- ยังยืนยัน layout ด้วย authenticated desktop/mobile screenshot ไม่ได้ เพราะ Computer Use รายงาน browser host unavailable
- live MT5 quote, reconnect และ broker clock visual acceptance ยัง NOT TESTED; U09 คง PARTIAL

### U10 — Alerts

- ปิดช่อง management-alert dedupe ที่หายหลัง process restart โดย reuse `Notifier` และตาราง `alerts` เดิม
- เพิ่ม fingerprint SHA-256 แบบ opaque ในคอลัมน์ additive `alerts.dedupe_fingerprint` พร้อม index; identity/account key ดิบไม่ถูกเก็บเพิ่ม
- จอง fingerprint และแถว `notify_outbox` ใน SQLite transaction เดียว จึงกู้การส่งได้แม้ process หยุดหลัง commit แต่ก่อนส่ง
- ทดสอบ restart ก่อนส่ง, restart หลังส่ง, concurrent instances, account/action isolation และ migration ที่คง alert/outbox เก่า
- U10 ฝั่ง notification dedupe เป็น DONE; command idempotency/replay ยังคงเป็นงาน U05 แยกต่างหาก

### U11 — Demo acceptance

- ยังคง BLOCKED: ไม่มี U01 fresh verified quote/clock และไม่มีคำสั่งอนุมัติ Demo ใหม่ในงานนี้
- ไม่ส่งคำสั่ง MT5 Demo/Live และไม่ทดสอบ power-loss/partial-fill กับ broker จริง

### U12 — AI Trader Team

- ตรวจ read-only `/api/explain` และ local text-only AI ตาม audit เดิม; ไม่มี tool calling หรือ gateway execution capability
- Multi-officer orchestration และ independent security review ยังไม่มี จึงคง PARTIAL

### U13 — Documentation sync

- ปรับ U10 alert audit, RUNBOOK, U09 visual recheck และ Unified Task Register ใน branch เดียวกับ code/migration
- ไม่มีการเปลี่ยนสูตรเทรดหรือเปิดใช้ runtime profile

## หลักฐานทดสอบ

- Notification/outbox, delivery, ownership, modify, readiness, AI explain และ API regression: **270 passed, 1 deselected, 1 existing Starlette/httpx deprecation warning**
- `tests/test_api.py::test_spa_deep_links_are_served` ถูก deselect เพราะ worktree นี้ยังไม่มี dashboard `dist`; Vite build ผ่านใน PR #52 และไม่มี Vue source change ในชุดนี้
- `node --test apps/web-dashboard/tests/chartViewport.test.mjs`: **7 passed**
- `ruff --select E9,F,I`, `compileall`: ผ่าน
- `git diff --check`: ผ่าน

## สถานะที่ยังไม่รับรอง

- U09 authenticated browser screenshot และ live-feed visual check: NOT TESTED
- U11 Demo/power-loss/partial-fill broker acceptance: BLOCKED
- U12 multi-officer orchestration/security review: NOT IMPLEMENTED
- U10 ทำให้ alert dedupe ข้าม restart ได้ แต่ไม่ได้เปลี่ยนการส่งซ้ำของ order/modify/close และไม่ใช่หลักฐานการส่ง alert ไป provider จริง
- ไม่มี deploy, service restart, MT5 command, Demo/Live order หรือ Auto activation

## Rollback

- Revert code/docs commit เพื่อย้อนการเปลี่ยนแอป; เก็บ `alerts.dedupe_fingerprint` และ index ไว้ เพราะเป็น additive migration และไม่ควรลบข้อมูล schema ระหว่าง rollback

## Merge receipt

- GitHub Actions Gate #156 ผ่านทุก job รวม real-Redis proof/self-check, dashboard build และ bundle-size check
- PR #53 merge เข้า `plan/unified-development-v4` เป็น `7cee568fcdc5b5061d99e9a8393f21aa5c5abde2`
