# U08 — รายงานผลส่งออก PDF จากเครื่องคิดเลข

วันที่: 26 พฤศจิกายน 2026
ฐาน: `plan/unified-development-v4` ที่ `cd157ce`
สถานะ: **โค้ดและ automated checks ผ่าน; การพิมพ์/บันทึก PDF จริงยัง NOT TESTED**

## สิ่งที่ทำ

- เพิ่มปุ่ม **PDF** ข้าง JSON/CSV ใน Trading Calculators
- เปิดหน้าพิมพ์ภายในเครื่องจากผลล่าสุด พร้อม UTF-8, ที่มา, เวลาสร้าง UTC และคำเตือนว่าเป็นข้อมูลประกอบ ไม่ใช่คำสั่งเทรด
- Escape ข้อความทุกช่องก่อนประกอบ HTML และไม่เพิ่มสคริปต์, เครือข่าย, dependency, API หรือฐานข้อมูล
- ผู้ใช้ต้องเลือก **Save as PDF** ใน print dialog ของเบราว์เซอร์เอง; แอปไม่ได้สร้างหรือดาวน์โหลดไฟล์ PDF โดยตรง
- ปรับ README, Runbook, LIMITATIONS, catalog และ Task Register; แก้บันทึกเก่าว่า PR #71 ยังไม่ merge ซึ่ง GitHub ปัจจุบันยืนยันว่า merge แล้ว

## หลักฐาน

| ตรวจ | ผล |
|---|---|
| `npm.cmd run test:calculator-export` | PASS — 5 tests |
| `npm.cmd ci` | PASS — 117 packages audited, 0 vulnerabilities |
| `npm.cmd run build` | PASS — Vite 8.3.8, 666 modules |
| HTML escaping / script injection fixture | PASS |
| Popup blocked / no payload behavior | PASS |
| เปิด print dialog และบันทึก PDF จริงใน browser | NOT TESTED |
| Desktop/mobile authenticated visual review | NOT TESTED |
| MT5 Demo history/margin comparison | NOT TESTED |

ครั้งแรก `npm` PowerShell shim ถูก Execution Policy ปฏิเสธ จึงใช้ `npm.cmd`; การทดสอบรอบแรกพบเพียง expectation ของ test ที่ไม่ได้คาดว่า JSON quotes จะถูก HTML-escape ได้แก้ test แล้วรันซ้ำจนผ่านครบ 5 รายการ

## ความปลอดภัยและ rollback

- ปุ่มส่งเพียง payload เครื่องคิดเลขปัจจุบันไปยังหน้าต่างพิมพ์ใน browser ของผู้ใช้ ไม่มี request เพิ่มไป API และไม่มีคำสั่ง MT5
- Popup ถูกบล็อกแล้วแจ้งวิธีแก้ให้ผู้ใช้ ไม่ fallback ไปส่งข้อมูลที่อื่น
- Rollback: revert การเปลี่ยนแปลง U08 PDF ใน branch นี้; ไม่มี schema migration, runtime config, บัญชี หรือสถานะ trading เปลี่ยน
- U08 ยังคง **PARTIAL** จนกว่าจะตรวจ print/save จริงใน authenticated browser และทำ Demo history/margin acceptance
