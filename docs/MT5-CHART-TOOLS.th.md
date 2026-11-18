# เครื่องมือกราฟ MT5 จากข้อมูล source เดียวกัน

เดิมเปิดเฉพาะ EMA เพราะ S/R, FLIP, FIB, BOS/CHoCH, แผนและ positions
อิง runtime จำลองอีกชุด การปิดปุ่มจึงเป็นเงื่อนไขใน UI ไม่ใช่ MT5 เสีย.

รอบนี้เพิ่ม GET `/api/market/overlays` โดยใช้ตัวเลือก source/account/symbol/timeframe
เดียวกับ candles และตรวจสิทธิ์บัญชีด้วยตัว resolver เดียวกัน.
ใช้ detector เดิมของโครงการกับแท่งปิดอย่างน้อย 30 แท่ง:

- S/R: โซนที่มีการยืนยัน ไม่ใช้ candidate เป็น confirmed
- FLIP: break/retest ของ swing ที่ยืนยันแล้ว
- FIB: คู่ swing ที่ยืนยันแล้ว พร้อม timeframe ตรงกับกราฟ
- BOS/CHoCH: โครงสร้างจากแท่งปิดใน timeframe ที่เลือก

Frontend เปิดปุ่มเมื่อผลวิเคราะห์จาก source เดียวกันพร้อมแล้ว.
เมื่อไม่มีรูปแบบในช่วงข้อมูล ปุ่มยังเปิด–ปิดได้แต่มีข้อความบอกว่าไม่พบรูปแบบ.
ถ้าข้อมูลน้อย/โหลดล้มเหลว ปุ่มแสดงเหตุผลและไม่ใช้ข้อมูลจำลองแทน.
SL/TP และ POS ยังปิดสำหรับกราฟ MT5 จนกว่าจะมีแผนและ positions ของบัญชี
ที่ผูกกับ source นี้โดยตรวจสิทธิ์แล้ว ไม่สร้างไม้หรือแผนขึ้นมาแทน.

## ประสิทธิภาพและความปลอดภัย

- คำขอ overlay ทำหลังโหลดกราฟ โดยแยกจาก quote ทุก 1 วินาที
- single-flight และ timeout 5 วินาที ไม่สะสมคำขอ
- cache 32 ชุดด้วย OHLCV ของแท่งปิด, point/digits, config และ timeframe
  ไม่คำนวณใหม่เพียงเพราะ spread เปลี่ยนหรือแท่งปัจจุบันขยับ
- ไม่เปลี่ยน execution broker, signal, risk gate หรือเปิดคำสั่งเทรด
- แก้ M3 ใน paper adapter ที่ยังขาด multiplier ทำให้ fallback จำลองใช้ M3 ได้ด้วย

## หลักฐานรอบนี้

- pytest API/roles/risk/market/bridge: 108 ผ่าน
- frontend smoke: ปุ่มทั้งสี่เปิดได้เมื่อมี same-source analysis และวาดระดับจาก payload นี้
- native M3 239 แท่งปิด: supports 2, resistances 5, flips 8, Fib มีข้อมูล,
  structure events 7 ณ เวลาที่ตรวจ (จำนวนเปลี่ยนได้ตามแท่งใหม่)
- คำนวณครั้งแรกบน PC 41.27ms, cache hit 0.001ms; ไม่ใช่ latency HTTP รวม
- ทดสอบ forming bar เปลี่ยนแล้วไม่ repaint/cache miss, ไม่มีการใช้ ensure_analysis
  ของ simulation, และการขอบัญชีที่ไม่มีสิทธิ์ถูกปฏิเสธ
- build ผ่าน; ยังไม่ตรวจคลิก UI ทุกปุ่มด้วยมือใน Chrome

UI: 18000, VM UI/API: 18080 ผ่าน tunnel ไป VM loopback 8000.
ย้อนกลับ code/bundle ไป 02bb195 ได้โดยไม่เปลี่ยนบัญชีหรือข้อมูลการเทรด.
