# เทียบกราฟกับ MT5 (2026-11-18)

- เริ่ม publisher แบบ foreground ผ่าน project Python สำเร็จ; ไม่ต้องใช้ Start-Process แบบซ่อนที่ถูกปฏิเสธก่อนหน้านี้
- ข้อมูลผ่าน VM100 bridge: XAUUSD.s / M5 เทียบแท่งปิด 599 แท่งกับ MT5 บน PC พบ OHLC ต่างกัน 0 แท่ง
- ในครั้งที่ตรวจ bridge รับ snapshot ล่าสุดเมื่อ 0.08 วินาทีก่อนตรวจ; ราคา Bid 3776.48 เทียบ terminal Bid 3776.46 ซึ่งอ่านคนละขณะ
- raw timestamp จาก terminal ล้ำหน้า PC/VM ประมาณ 7200 วินาที ยังไม่รับรองว่าเป็น UTC; คงค่า raw เดิม ไม่เลื่อนเวลาประวัติด้วยค่าที่เดา
- API คง stale=true สำหรับเวลาที่ล้ำหน้า แต่แยก transport_stale เพื่อให้หน้ากราฟแสดง quote ที่รับจาก broker ล่าสุดพร้อมคำเตือนเวลา โดยไม่มีสิทธิ์ execution เพิ่ม
- frontend ใช้ Bid สำหรับแท่ง MT5, โหลด rates ซ้ำทุก 15 วินาที, ไม่ใช้ simulation อัปเดตแท่ง MT5, ใช้เวลาจาก source ใน footer เพื่อเทียบกับแกนกราฟได้
- ตรวจด้วย `scripts/verify_mt5_chart_bridge.py` เป็น read-only; ไม่สร้าง trading runtime เพิ่มและไม่ส่งออร์เดอร์
- การตรวจ browser ด้วยตายังไม่ทำ; ให้เทียบ symbol XAUUSD.s และ timeframe M5 เดียวกันที่ 18000 (dev UI) หรือ 18080 (VM bundle)
- feed_mode ของ runtime ยังคง simulate สำหรับงาน runtime เดิม; chart source แยกเป็น mt5-live เมื่อ bridge เชื่อมอยู่
- publisher ยังต้องมี MT5 เปิดและล็อกอิน Demo อยู่ การเริ่มหลัง reboot และการจัดการ terminal เบื้องหลังยังไม่อยู่ในรอบนี้
