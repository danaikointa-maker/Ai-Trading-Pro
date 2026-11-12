# P1.3 — Local verification runner

ใช้ Python ของ repository และระบุ Node/Git เมื่อต้องการผลที่ทำซ้ำได้ ไม่ติดตั้ง dependencies
ไม่เริ่ม API, Redis, MT5 terminal หรือ simulation server และไม่เปิด execution

## คำสั่ง Windows

จาก `C:\workspace\Ai-Trading-Pro`:

```powershell
& 'C:\workspace\Ai-Trading-Pro\.venv\Scripts\python.exe' 'C:\workspace\Ai-Trading-Pro\scripts\verify_local.py' --node 'C:\Users\danai\AppData\Local\Programs\TradeAi\node-v26.13.0-win-x64\node.exe' --git 'C:\Program Files\Git\cmd\git.exe'
```

หรือใช้ `C:\workspace\Ai-Trading-Pro\scripts\check-windows.ps1` ซึ่งใช้ตัวค้นหาเดิม
แล้วส่ง absolute paths เข้า runner; ถ้าต้องการ pin เวอร์ชันให้ใช้คำสั่ง explicit ข้างบน
runner ใช้ `sys.executable` สำหรับ pip, Ruff และ pytest และ prepend directory ของ Node
ลง PATH ของ child จึงไม่ทำให้ PWA test skip เพราะ Node หลุดจาก PATH ของ pytest

## ลำดับและหลักฐาน

1. ตรวจ Node/Git version และ `pip check`
2. `ruff check --select F,E9 .`
3. ใช้ Node ที่เลือกเรียก Vite ใน dependencies ที่ติดตั้งไว้แล้ว เพื่อ build bundle ก่อน PWA tests
4. `pytest tests -q -rs --tb=short` พร้อม JUnit และ faulthandler diagnostic
5. `git diff --check`

ทุก child ใช้ environment สำเนาที่ลบ `NO7_*`/`MT5_*` แบบ case-insensitive
ไม่บันทึก environment values; tests ใช้ fixtures/temp storage ของตนเอง
ไม่แตะ environment ของ parent ใน Python runner

Artifacts อยู่ใต้ `C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\verify-<UTC timestamp>`
หรือ path ของ `--output`; directory ต้องยังไม่มีเพื่อไม่ทับหลักฐานเก่า
แต่ละ job มี `.log`, `.err`, `.exit` พร้อม `summary.json` ที่บันทึก tool paths และ timestamps
`.exit` เป็นเลข exit จริง หรือ `RUNNING`/`TIMEOUT`/`ERROR` ไม่สมมติว่า output ว่างหมายถึงผ่าน
runner หยุดเมื่อ job ผิดพลาด; `summary.json` ที่ยังเป็น `running` ไม่ใช่หลักฐาน completion

`passed_with_skips` หมายถึง commands ผ่านแต่ยังมี skipped tests; exit 0 ไม่ใช่ acceptance ทั้งระบบ
JUnit นับ cases/failures/errors/skips และแจกแจงเหตุผล skip เป็น dependency/policy/unclassified
เหตุผลที่ไม่รู้จักคงเป็น unclassified ให้ผู้ตรวจตัดสิน ไม่เดาว่าเป็น environment ทั้งหมด
เครื่องนี้ยังไม่มี Bash/redis-server บน PATH และไม่ติดตั้งหรือเชื่อม service ให้เอง
การมี dependency อยู่ไม่ได้อนุญาตให้ตั้ง production URL หรือเชื่อม broker

## ข้อจำกัด

- Timeout ค่าเริ่มต้น 900 วินาทีต่อ child; ปรับด้วย `--timeout`; ไม่รับรอง process-tree cleanup
  ของ grandchildren ทุกชนิดบนทุก OS ควรตรวจ process หากงาน timeout โดยไม่ restart service เดิม
- Build อาจเขียน dashboard dist ตามพฤติกรรมเดิม; ไม่ใช่ deploy หรือ browser/visual acceptance
- ไม่มี full Redis, EA compile/crash, VM, MT5 Demo หรือ multi-host fencing acceptance ใน runner นี้
- Local artifacts เป็น ignored storage ไม่ใช่ durable release evidence; sanitized summary และ source manifest
  กำหนดใน [`BASELINE-P1.th.md`](BASELINE-P1.th.md) แล้ว แต่ยังไม่ commit/publish ไป remote
- ผู้ใช้เรียก Python โดยตรงต้องเลือก virtualenv ตามคำสั่ง ไม่ fallback ไป system Python โดยเงียบ

## หลักฐาน P1.3 รอบนี้

Canonical full run ที่ `C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety\p13-final\summary.json`:
2026-11-09T05:19:04Z ถึง 05:23:47Z ตาม artifact clock (ไม่ปรับเวลาเครื่อง)
ได้ 717 passed / 39 skipped / 1 warning; 756 JUnit cases, failures/errors 0
ทุก job exit 0; Redis dependency skip 20, Bash 13, policy 6; ไม่มี Node skip
warning คือ Starlette TestClient deprecation เดิม ไม่อัปเกรด dependency ในงานนี้

RED 12 failures ก่อนสร้าง module และ GREEN 12 passed เก็บที่ `p13-red.log`/`p13-green.log`
ใต้ `C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety`;
รอบแรก `p13-verification` หยุดเพราะ unused import ใน test (แก้แล้ว ไม่ลบหลักฐานเก่า)
focused launch แยกจาก shell ได้ 29 passed/1 Node skip จึงไม่ใช้เป็น canonical
การเตรียม PATH ใน shell คนละ invocation ไม่ใช่หลักฐานว่าถ่ายทอดสำเร็จ; runner เป็นผู้ส่ง child env โดยตรง
Windows wrapper ผ่าน parser เท่านั้น ยังไม่รัน end-to-end ผ่านตัวค้นหา Find-Npm