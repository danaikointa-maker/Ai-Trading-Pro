# รอบดึงข้อมูลกราฟ (2026-11-18)

| งาน | เดิม | ใหม่ |
| --- | --- | --- |
| อ่าน quote จาก API ในแท็บที่มองเห็น | 2 วินาที | 1 วินาที |
| โหลดแท่งกราฟจาก API ซ้ำ | 15 วินาที | 5 วินาที |
| ส่งประวัติทุก timeframe จาก MT5 publisher | 60 วินาที | 10 วินาที |
| ส่ง quote จาก MT5 publisher | ประมาณ 1 วินาที + เวลาทำงาน | รอบเป้าหมาย 1 วินาที โดยหักเวลาทำงานก่อนพัก |

เก็บ 600 แท่งต่อ timeframe เช่นเดิม และไม่ปรับเป็น tick-by-tick.
การแสดง bid ระหว่างแท่งยังใช้ quote ล่าสุด ขณะที่ high/low/history เต็ม
แก้ไขตามรอบประวัติ จึงยังมี latency รวมของ MT5/SSH/API/browser.

## ลดภาระก่อนเพิ่มความถี่

- Chart candles endpoint อ่าน OHLCV จาก adapter โดยตรง ไม่เรียก enrichment
  ที่เพิ่ม Indicator ก่อนตัดทิ้งจาก response; strategy/analysis pipeline เดิมยังคงใช้ enrichment
- คำขอ quote มี single-flight: timer ใหม่ถูกข้ามระหว่างคำขอเดิมยังทำงาน ไม่เข้าคิว
- quote timeout 4 วินาที; candles timeout 8 วินาที; failure ปลด guard ให้ลองใหม่ได้
- แท็บที่ซ่อนข้าม quote/history/context timer ของกราฟ แต่ Windows publisher
  และ trading runtime ยังคงทำงานตามเดิม
- Publisher ทำงานทีละรอบ และกำหนด history interval ขั้นต่ำ 5 วินาที

## ผลวัดและขอบเขต

ใช้ข้อมูลจริง XAUUSD.s M3 จำนวน 480 แท่งบน Windows, เปรียบเทียบงาน Python
5 รอบต่อรูปแบบ: median ก่อน 37.05ms หลัง 2.42ms; OHLCV เท่ากันทุกค่า.
นี่เป็นเวลาเฉพาะการเตรียมข้อมูล ไม่ใช่ latency ของ HTTP หรือคำรับรองผลบน VM.
Health API ก่อนเปลี่ยนตอบ 18–322ms จาก 5 requests; ใช้ยืนยันว่าปลายทางตอบได้
ไม่ใช่ benchmark candles endpoint หรือการทดสอบ concurrent users.

pytest API/roles/risk/market/bridge ผ่าน 105 tests; frontend smoke และ build ผ่าน.
ทดสอบคำขอซ้อนและ timeout guard ด้วย promise จำลอง ไม่เรียกซื้อขายโบรกเกอร์.
ยังไม่ทำ multi-user load test หรือรับรองว่าจะไม่หน่วงทุกเงื่อนไข.
หลายแท็บ/ผู้ใช้จำนวนมากหรือ MT5/เครือข่ายช้าเพิ่มภาระได้; guard ช่วยไม่ให้คำขอ
ของกราฟเดียวสะสม แต่ไม่ใช่ global rate limiter.

ตรวจ UI ที่ 18000, VM API/bundle ที่ 18080 → VM loopback 8000.
คืนรอบเดิมได้ด้วย code/bundle 8fe9249 และ publisher `--rates-interval 60`.
