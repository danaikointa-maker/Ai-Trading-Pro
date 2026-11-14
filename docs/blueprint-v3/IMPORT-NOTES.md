# Blueprint v3 — สำเนาอ้างอิงในโปรเจกต์

วันที่นำเข้า: 8 พฤศจิกายน 2026

## เริ่มอ่าน

- [แผนประยุกต์กับโค้ดจริงและการเชื่อมเครื่องเป็นรอบ](../MACHINE-ROLES-AND-CONNECTION-PLAN.th.md)
- [Master Blueprint ต้นฉบับ](MASTER-BLUEPRINT.md)
- [README ต้นฉบับ](README.md)
- [Service และ deployment matrix](docs/09-SERVICE-AND-DEPLOY-MATRIX.md)
- [รายการตรวจ SHA-256 ของไฟล์ต้นฉบับ](SOURCE-SHA256SUMS.txt)

## ที่มาและความครบถ้วน

คัดลอกไฟล์ต้นฉบับทั้ง 28 ไฟล์โดยคงชื่อ โครงสร้าง และเนื้อหาเดิมจาก:

```text
C:\Users\danai\Downloads\TradeAi-Professional-Master-Blueprint-v3\TradeAi-Professional-Master-Blueprint
```

สำเนาครอบคลุม master document, README, AGENTS, เอกสาร 00–12,
config ตัวอย่าง, check/preflight scripts และ templates ไม่จำเป็นต้องมีต้นทาง
ใน Downloads เพื่ออ่านชุดเอกสารนี้อีกต่อไป

`SOURCE-SHA256SUMS.txt` บันทึก SHA-256 ของไฟล์ต้นฉบับทุกไฟล์ตามพาธสัมพัทธ์
ไม่รวมตัว manifest เองและหมายเหตุนำเข้านี้ซึ่งเป็นไฟล์ที่เพิ่มภายหลัง

## ขอบเขตการใช้งาน

- โฟลเดอร์นี้เป็น snapshot อ้างอิง ไม่ใช่หลักฐานว่าบริการหรือ VM ติดตั้งแล้ว
- ไม่คัดลอกทับ README, AGENTS, config หรือ scripts ที่รากโปรเจกต์
- `AGENTS.md` ภายในชุดเป็นเอกสารต้นฉบับ ไม่ได้ย้ายมาเป็นกฎที่รากโปรเจกต์
- พาธ DEV ในต้นฉบับ `C:\workspace\TradeAi` เป็นตัวอย่างที่ไม่ตรงเครื่องนี้
  พาธจริงคือ `C:\workspace\Ai-Trading-Pro` ไม่ย้ายหรือ clone ซ้ำตามตัวอย่าง
- IP/OS/ทรัพยากร/สิทธิ์ของ VM ต้องตรวจจริงก่อนใช้; ค่า config เป็นตัวอย่าง
- อย่ารัน scripts หรือนำ config ไปเปิดใช้โดยอัตโนมัติ ต้องตรวจเทียบ implementation
  และขอบเขตที่ผู้ใช้อนุมัติก่อน โดยเฉพาะ network, secrets และ execution
- ตัวแปร ENV ตัวอย่างไม่ได้รับรองว่า EA อ่านค่าเหล่านั้น หรือปิด order path ได้จริง
- ใช้แผนประยุกต์ด้านบนประกอบเมื่อต้นฉบับต่างจากโค้ดปัจจุบัน และเก็บข้อแตกต่างไว้ชัดเจน
- การนำเข้าครั้งนี้ไม่เชื่อม remote, ไม่ deploy, ไม่ส่งออร์เดอร์ และไม่ commit/push

หากปรับแผนให้ตรง implementation ในอนาคต ให้แก้เอกสารประยุกต์แยกจาก snapshot
เพื่อรักษาหลักฐานว่าต้นฉบับกำหนดอะไรไว้