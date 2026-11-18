# การเลือก timeframe และปรับปุ่มกราฟ

- ปุ่มเริ่มต้น: M1, **M3**, M5, M15, H1, H4
- ตัวเลือกเพิ่มเติม: M30 และ D1 ผ่านเมนู **Timeframe เพิ่มเติม / จัดปุ่ม**
- ในเมนูกดชื่อ timeframe เพื่อดูได้ทันที; checkbox **แสดงปุ่ม** ใช้ปักหรือซ่อนปุ่ม โดยไม่เปลี่ยน timeframe ที่กำลังดู
- เหลืออย่างน้อยหนึ่งปุ่มเสมอ หากซ่อนปุ่มที่กำลังดูจะมีข้อความบอก timeframe ปัจจุบัน
- เก็บตัวเลือกใน localStorage ของเบราว์เซอร์ แถบบนและแถบกราฟใช้รายการเดียวกัน มีปุ่มคืนค่าเริ่มต้น
- เป็นการปรับมุมมองกราฟ ไม่เปลี่ยน timeframe ของ strategy หรือเปิดการส่งคำสั่งซื้อขาย

M3 รองรับตั้งแต่ MT5 Python publisher และ EA rates ไปจนถึง broker adapter,
simulated/replay aggregation และ frontend quote bucket ขนาด 180 วินาที.
เมื่อไม่มี native M3 จะรวมเฉพาะแท่ง M1 ที่ได้รับ; ไม่ใช้แท่ง M5 แทน M3.

ส่วนควบคุมซูมจากงานก่อนหน้ารวมในรอบนี้ด้วย: ความกว้างแท่ง, Fullscreen,
Auto scroll, Chart shift, ลากสเกลราคา, ช่วงราคาตายตัวและช่วงเวลา,
รวมถึงการเก็บมุมมองเมื่อ refresh ข้อมูล. EMA ไม่ขยายขอบเขต autoscale ของราคา.
เว็บกับ MT5 ใช้คนละ chart renderer; ขนาดระดับพิกเซลขึ้นกับพื้นที่กราฟและสเกลที่ตั้ง.

ตรวจรอบนี้: pytest bridge/market 47 ผ่าน, chart controls smoke ผ่าน, dashboard build ผ่าน,
EA compile 0 errors / 0 warnings. Native M3 จาก bridge เทียบแท่งปิดกับ MT5
598 แท่ง OHLC ต่างกัน 0 แท่ง. ไม่รวมแท่งที่ยังเปิดเมื่อ snapshot ถูกบันทึก.
ยังไม่ตรวจคลิกปุ่ม/ซูมใน browser จริงหลัง deploy.

พอร์ต: 18000 สำหรับ UI พัฒนา; 18080 สำหรับ UI/API VM ผ่าน SSH ไป VM loopback 8000.
ย้อนกลับ code/bundle ไป commit e193f6f ได้โดยไม่เปลี่ยนฐานข้อมูลบัญชี.

## แถบเครื่องมือแบบย่อ

ปุ่มปรับ timeframe ใช้ไอคอน sliders; ปุ่มซูม เลื่อนตามราคา เว้นท้าย กลับล่าสุด
แสดงทั้งหมด เต็มจอ และสเกลราคาใช้ SVG พร้อม title/aria-label.
สถานะเปิด–ปิดยังใช้ aria-pressed และสีเน้น ปุ่ม timeframe คงชื่อ M1/M3 ฯลฯ.
ส่วนหัวใช้ไอคอนแทน Equity, P&L, clock, role และ logout; โหมดใช้ MAN/SEMI/AUTO.
ตั้งความสูง/ช่วงเวลา/ช่วงราคาและรายละเอียดโมเดลอยู่ในเมนูขยาย.
สถานะ SIMULATED, ข้อมูลค้าง และความต่างเวลา MT5 ยังมีข้อความสถานะสั้นให้เห็น.
ค่าตัวเลขราคาและคำเตือนที่จำเป็นไม่ถูกซ่อนทั้งหมดไว้ใน tooltip.

ตรวจ compact UI: build และ chart/header SSR smoke ผ่าน รวมป้ายชื่อและ tooltip
ของปุ่มไอคอน; อ่าน accessibility ของ Chrome จริงแล้วพบชื่อปุ่มครบ.
ยังไม่ตรวจภาพหน้าจอระดับพิกเซล เนื่องจาก capture timeout และ native click
รายงาน coordinate input geometry is unavailable.
