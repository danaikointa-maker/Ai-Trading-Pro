# กราฟก่อนผูกบัญชีและกราฟตามบัญชีโบรกเกอร์

- เมื่อล็อกอินแอปแล้ว เรียกกราฟตลาดกลางได้โดยไม่ต้องสร้าง broker account; ป้าย feed แสดงแหล่งข้อมูลจริง รวมถึง simulate/replay เมื่อไม่มี MT5 feed
- หน้า chart อ่าน `/api/market/context` เพื่อแสดงเฉพาะ managed accounts ที่ผู้ใช้มีสิทธิ์เข้าถึง และเลือกบัญชีที่มี session ยืนยันแล้วโดยอัตโนมัติ
- ผู้ใช้เลือกตลาดกลางเองได้ การเปลี่ยนกราฟไม่เปลี่ยน execution broker
- เมื่อระบุ `account_id` ใน candles/ticker ต้องตรง tenant/access, login fingerprint, server และประเภท demo/live กับ snapshot ของ bridge ที่ connected; ไม่ตรงจะตอบ 404/503 โดยไม่ใช้ราคาอีกบัญชีแทน
- การสร้าง account record ไม่ล็อกอิน MT5; ยังต้องพัฒนา authenticated Windows worker สำหรับ credential delivery, account login, lifecycle และ account-isolated sessions
- bridge ปัจจุบันบังคับ Demo/read-only ดังนั้นบัญชี Live ยังไม่เชื่อมผ่าน deployment นี้ การมีตัวเลือก Live ไม่หมายถึงเปิดใช้ Live แล้ว
- ส่งคำสั่งซื้อขายต้องผ่านสิทธิ์และ execution gates เดิมแยกจากการดูกราฟ

ผล local: bridge tests 37 ผ่าน, market access tests 5 ผ่าน, dashboard build ผ่าน ยังไม่ตรวจหน้า browser หรือ deploy flow นี้บน VM100
พอร์ตสำหรับตรวจหน้าเว็บเมื่อ deploy แล้ว: 18000 (UI dev), 18080 (VM API tunnel ไป 8000)
