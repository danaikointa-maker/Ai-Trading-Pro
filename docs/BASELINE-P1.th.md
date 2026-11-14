# P1 — Source/config/evidence baseline และเกณฑ์ปิดเฟส

## ข้อสรุปและขอบเขต

เฟส 1 เป็น **local inventory/review + verification + baseline documentation** ไม่ใช่
release sign-off หรือการรับรองการเทรด ข้อค้นพบที่ต้องแก้ implementation ยังคงอยู่ใน P2–P8
ทะเบียน canonical อยู่ที่
`C:\workspace\Ai-Trading-Pro\.archify\explainer-project-progress-20261109-114911\candidate.archify.md`
และ HTML ในโฟลเดอร์เดียวกัน ไม่สร้างทะเบียนคู่ขนาน

Baseline ID: **P1-local-46438d7** เป็น dirty working-tree snapshot ไม่ใช่ Git tag หรือ commit ใหม่
HEAD ที่ตรวจ: `46438d71e16dfaa5dc58e88d997ca0ed43be2aff`
branch: `integration/safety-main-2026-11-08`; ต้องอ่าน manifest เพื่อดู staged status ณ capture
ไม่ถือว่า HEAD อย่างเดียวบรรจุงาน safety ที่ยัง uncommitted

วันที่ environment ตามบริบทงานคือ 8 พฤศจิกายน 2026 ส่วน local artifacts รายงาน UTC
9 พฤศจิกายน 2026; เก็บเวลาที่เครื่องรายงานไว้ใน evidence ไม่ปรับเวลาเครื่อง
ไม่ใช้วันในชื่อไฟล์/ทะเบียนแทนเวลา capture หรือวันส่งมอบจริงของงานย้อนหลัง

## Source/config baseline ที่ย้อนตรวจได้

- Manifest: [`evidence/P1-source-manifest.json`](evidence/P1-source-manifest.json)
  ระบุ HEAD/branch, repository-relative path, byte length และ SHA-256 ของ source/config/tests/tooling
  ทั้ง tracked และ untracked ที่อยู่ใน scope; แยก changed/new/staged paths อย่างชัดเจน
- Scope: `apps` (ไม่รวม build/dependencies), `bridge` source, `config` ที่ไม่ใช่ local override,
  `integrations`, `packages`, `services`, `scripts`, `tests`, `.github`, requirements,
  `.env.example`, `.gitignore` และ root build/test config ที่ Git รู้จัก
- Hashes วัด **raw bytes** รวม line endings; checkout ข้าม OS อาจทำ hash เปลี่ยนแม้ semantic เหมือนกัน
  Manifest ไม่ใช่ digital signature ไม่รับรองความถูกต้อง/ปลอดภัยของ source เอง
- ไม่อ่าน/เก็บ `.env`, `config/*.local.yaml`, credentials, account databases, runtime state,
  `.venv`, `node_modules`, ignored `.tools` หรือ raw sensitive logs
- เอกสารและ generated Archify HTML/receipts อยู่นอก source fingerprint เพื่อไม่ให้เกิด circular hash
  เนื้อหาเอกสารตรวจด้วย explicit links/contradiction checks และ source review แยก
- P1.1 snapshot เดิมยังอยู่ตาม [`P1-1-CUMULATIVE-REVIEW.th.md`](P1-1-CUMULATIVE-REVIEW.th.md)
  manifest ใหม่ไม่ลบ/แทนข้อสรุปเฉพาะ snapshot เก่า และไม่อ้างว่าตรวจทุก line ของ unchanged repository

## Config contract — ตรวจ source ไม่ instantiate runtime

| ประเด็น | As-is / หลักฐาน | ข้อจำกัด |
| --- | --- | --- |
| Load order | `packages/shared_schemas/settings.py`: process env ที่มีอยู่ชนะ `.env`; YAML placeholders interpolate จาก env | การล้าง env ไม่ได้ปิด dotenv loader; tests ใช้ temp-path fixtures และ overrides ของตนเอง |
| Paths | `Settings._resolve_paths()` resolve ตาม `NO7_ROOT`; YAML ใน `config/app.yaml` | default DB path ไม่ใช่ QA database; runner ต้องล้าง inherited overrides |
| Workspace | `Settings.security`, DB/JWT namespace ใช้ `NO7_WORKSPACE_ID` default `local` | ยังไม่มี per-user account grants; wrong-workspace DB preflight/legacy adoption อยู่ P2.5 |
| Local QA | `scripts/verify_local.py`: สำเนา env ลบ `NO7_*`/`MT5_*`, Node parent ลง child PATH | ไม่บันทึกค่า env; explicit Python เป็น caller responsibility |
| Local launcher | `scripts/run-local.ps1`, `windows-common.ps1`: paper/simulated, loopback, Full Auto/bridge/alerts off | launcher ไม่ได้รันในงานนี้; ไม่เท่ากับ QA runner และไม่ใช่ runtime acceptance |
| Default config | `.env.example` เป็น template; `config/app.yaml` auto-train default true และ template host `0.0.0.0` | ไม่ใช่ isolated safe launcher profile; ห้ามนำ generic quickstart ไปเปิดสู่ public โดยอาศัยผล QA |
| CI | `.github/workflows/ci.yml`: Linux Python 3.11/Node 22, fetch Redis, Bash gate | เป็น declared workflow ไม่ใช่ remote result ของ dirty tree นี้; local Node version ดู evidence |

ไม่แก้ config values, secrets หรือ production defaults ใน P1.4; รายงาน baseline ตามของจริง

## Evidence baseline และการรักษาหลักฐาน

สรุปที่ผ่านการคัดข้อมูลแล้วอยู่ใน [`evidence/P1-verification.json`](evidence/P1-verification.json)
เก็บจำนวน JUnit, exits, reasons for skips, tool versions และ SHA-256 ของ local artifacts
ไม่คัด raw logs หรือ environment values เข้าชุด durable summary
ไฟล์ใน `docs/evidence` **ไม่ถูก ignore แต่ยัง untracked จนกว่าจะมีการอนุมัติ commit**
จึงเป็น release-evidence candidate ใน workspace ไม่ใช่หลักฐานว่าเก็บถาวรบน remote แล้ว

| รอบ | บทบาท | ตำแหน่ง local |
| --- | --- | --- |
| history-final / atomic-final | หลักฐานย้อนหลัง P1.2; ไม่ใช้แทน latest tree | `storage/local-dev/qa/safety/{history,atomic}-final-*` |
| p11 | inventory/diff review และ focused tests | `storage/local-dev/qa/safety/p11-*` |
| p13-final | deterministic runner baseline: 717 passed / 39 skipped / 1 warning | `storage/local-dev/qa/safety/p13-final/` |
| p1-close-verification | full closing run ของ source tree เดียวกัน; ดู terminal status ใน durable summary | `storage/local-dev/qa/safety/p1-close-verification/` |

Closing run: **717 passed / 39 skipped / 1 warning**, 756 JUnit cases failures/errors 0;
pip/Ruff/build/tests/diff และ tool-version jobs exit 0 ครบ, Node/PWA ผ่าน
skip Redis 20, Bash 13, policy 6; ไม่ถือว่าข้อที่ skip ผ่าน acceptance
เวลา artifact ของรอบนี้ `2026-11-09T05:29:38Z` ถึง `2026-11-09T05:33:46Z`

Manifest ครอบคลุม **237 source/config/test/tooling files**; เปรียบเทียบ 30 ไฟล์จาก P1.1
ที่อยู่ใน source scope แล้ว SHA-256 ยังเดิม การตรวจ preservation ไม่รวมเอกสารที่ตั้งใจปรับในงานนี้
ตรวจ source snapshot ช่วง capture → finalize ไม่เปลี่ยน; ไม่ใช่ background monitoring
ตรวจเอกสาร 8 ไฟล์: relative links 42 จุดมี target, code fences ครบ และข้อความ README ที่ขัดกันถูกแก้
ผลตรวจเอกสารเป็น static checks/source review ไม่ใช่ browser rendering

ถ้า summary ยัง `running`, XML หาย, exit ไม่ใช่ terminal หรือ hash ไม่ตรง ถือว่า **ยังใช้ปิดงานไม่ได้**
`passed_with_skips` ไม่ใช่ทั้งหมดผ่าน: Redis/Bash dependency skip และ policy skip ต้องแยก
PWA ต้องไม่ skip ใน canonical runner; warning Starlette/httpx deprecation ต้องรายงาน ไม่ upgrade เงียบ

### ก่อน release จริง (ขั้นตอนที่กำหนดไว้ ยังไม่ดำเนินการ)

1. ปิด findings/acceptance ของเฟสถัดไปตาม scope release; source/config เปลี่ยนต้อง rerun checks และออก snapshot ใหม่
2. สร้าง evidence directory ใหม่ไม่ทับรอบเก่า; ผูก manifest hash กับ JUnit/log/exit/check receipts
3. ตรวจ privacy/secret และเปรียบเทียบ source hashes หลังตรวจ; checksum ไม่ทดแทน review/sign-off
4. เก็บ sanitized summary + source manifest + ข้อจำกัดใน approved release commit/tag/artifact store
   ส่วน raw evidence เก็บในที่ควบคุมสิทธิ์ที่เจ้าของระบุ พร้อม retention และ recovery verification
5. ถ้า raw evidence สูญหาย ให้ประกาศ unverifiable และรันใหม่ ไม่สร้าง logs/exit ย้อนหลัง
6. commit/tag/push/upload, กำหนดผู้อนุมัติ/retention และเปิดระบบจริงต้องได้รับการอนุมัติแยก
   ยังไม่มีการเลือก remote storage หรือแต่งชื่อเจ้าของที่ไม่มีหลักฐาน

## เกณฑ์ปิดเฟส 1 และงานค้างที่โอนไปเฟสถัดไป

| ID | เกณฑ์ตรวจรับเฉพาะเฟส 1 | หลักฐาน/ข้อจำกัด |
| --- | --- | --- |
| P1.1 | รู้ inventory และตรวจ source diff ของ cumulative safety snapshot | report เดิม + preservation comparison ใน manifest; findings ยังเปิด |
| P1.2 | ตรวจ historical receipts/log/XML/exits ไม่ยืมคำกล่าวอ้างจากแชท | history/atomic summary และ artifact hashes ใน durable evidence |
| P1.3 | tool paths/Node child PATH/exits/skips ทำซ้ำและตรวจได้ | runner tests, full run, build/lint/diff; Windows wrapper parser-only ไม่อ้าง end-to-end |
| P1.4 | current docs ไม่ขัดกับ safety state; source/config/evidence baseline ย้อนตรวจได้ | หน้านี้ + manifests + doc checks; dirty tree ไม่ใช่ release |
| P1.5 | ทะเบียน IDs และ HTML สอดคล้องกับสถานะพร้อม receipt | Archify validate/deliver/check; browser/visual not-run |

งานที่ **ไม่ใช่ข้ออ้างว่าปิด implementation แล้ว**: P2.2/P2.5 ownership/DB adoption,
P3.3/P3.6 authoritative mapping/ledger reopen/concurrency, P4.7 snapshot scope,
P6.6 UI threshold/message; รายการอื่นในทะเบียน P2–P8 ยังคงเดิม
ไม่มี real Redis/VM/MT5 Demo, EA recompile ใหม่, crash/power-loss, multi-host fencing,
browser E2E หรือ profitability acceptance จากเฟสนี้

ลำดับถัดไปหลังปิดเฟส 1: **P2.2 → P2.5 → P3.3 → P3.6**
ไม่ลบ journal/claims, ไม่เปิด trading/connection และไม่ deploy/restart/commit/push อัตโนมัติ