# สถานะปุ่มและการทดสอบ (2026-11-18)

อัปเดตภายหลัง: S/R, FLIP, FIB และ BOS บน MT5 ใช้ข้อมูลกราฟเองแล้ว
ตาม [MT5-CHART-TOOLS.th.md](MT5-CHART-TOOLS.th.md); รายการด้านล่างเป็นผลก่อนรอบนั้น.

## สิ่งที่แก้

- Timeframe ที่เลือกใช้พื้นทอง ตัวอักษรเข้ม กรอบและ ring ชัดเจน
  ทั้งปุ่มหลักและเมนูเพิ่มเติม ใช้ aria-pressed/aria-current จาก state เดียวกัน
- ปุ่ม toggle อื่นแสดงสถานะค้างไว้ตาม state ส่วนคำสั่งครั้งเดียวแสดง feedback ตอนกด
- Chart overlay ที่มาจาก runtime คนละชุดกับ MT5 ถูก disable พร้อมเหตุผล; EMA ยังใช้กับข้อมูลกราฟได้
- ปุ่มที่ต้องมีแท่งข้อมูลถูก disable ขณะไม่มีข้อมูล/กำลังโหลด
- แก้คีย์ลูกศรซ้ายไปประวัติ ขวาไปแท่งใหม่ และ preset MT5 คืนความสูง 580px ตาม tooltip
- เปลี่ยนโหมดผ่าน helper เดียวกัน: ตรวจสิทธิ์และ Full Auto lock, กันคำขอซ้ำระหว่างรอ,
  เปลี่ยน active หลัง server ยืนยันเท่านั้น และไม่เปลี่ยนสถานะเมื่อคำขอล้มเหลว
- เอา POST config ที่ไม่เกี่ยวกับปุ่มเปลี่ยน symbol ออก
- Save risk, Train, Backtest/Rerun ไม่เปิดให้ viewer กดส่งคำขอที่ server จะปฏิเสธ
- Use broker ไม่เปิดเมื่อ Live ถูกล็อก หรือ broker ยังไม่เชื่อม พร้อม tooltip บอกเหตุผล
- Emergency close แสดงผลตอบรับ/ปฏิเสธ/ไม่ทราบผลจาก server ไม่กล่าวว่าปิดทุกไม้แล้วทันที

## หลักฐานและขอบเขต

| กลุ่ม | ผล | ขอบเขต |
| --- | --- | --- |
| Template event bindings | ผ่าน 99 จุด | ตรวจ binding มีอยู่ใน script/ขอบเขต template ไม่ใช่คลิกจริงครบทุกปุ่ม |
| Timeframe active | ผ่าน | SSR ของ picker สองชุดและเมนู ตรวจ M3 active พร้อมกันหลังเลือก |
| Chart tools | ผ่าน | เรียก handler จริงกับ chart adapter จำลอง: zoom, follow, shift, latest, fit, ช่วงราคา/เวลา, fullscreen, MT5 preset, คีย์บอร์ด |
| Mode change | ผ่าน | API จำลอง: viewer/Full Auto lock ไม่ส่งคำขอ, เปลี่ยนสถานะเมื่อสำเร็จ, คงโหมดเดิมเมื่อคำขอล้มเหลว |
| Position controls | ผ่าน | positions-smoke: unknown, stale, unavailable และ owned-empty |
| Backend API/roles/risk/market/bridge | ผ่าน 104 tests | fixture database/runtime แยกจากระบบใช้งานจริง |
| Dashboard build | ผ่าน | production bundle |
| คลิกครบทุกปุ่มใน Chrome จริง | NOT TESTED | ไม่ใช่หลักฐานจาก SSR หรือการตรวจ binding |
| Fullscreen/PWA install ของ browser จริง | NOT TESTED | ขึ้นกับ browser และ permission |
| Buy/Sell/Approve/Close/Emergency กับ MT5 จริง | NOT TESTED | ไม่ส่งคำสั่งโบรกเกอร์ในการตรวจรอบนี้ |
| Account login/Live execution อัตโนมัติ | ยังไม่พร้อม | ไม่เปิดความสามารถนี้จากการตรวจปุ่ม |

คำสั่งตรวจ: `npm run smoke:ui-actions`, `npm run smoke:chart-controls`,
`node scripts/positions-smoke.mjs`, `npm run build` ใน web-dashboard;
pytest: test_roles, test_api, test_risk_engine, test_market_access,
test_market_freshness, test_bridge.

ต้อง build เสร็จก่อนเริ่ม API tests ที่ตรวจ SPA routes เพราะ Vite จะล้าง dist ระหว่าง build.
พอร์ตตรวจหลัง deploy: UI พัฒนา 18000, VM bundle/API ผ่าน tunnel 18080 → VM loopback 8000.
ย้อนกลับ code/bundle ไป 48d8a99 ได้โดยไม่เปลี่ยนฐานข้อมูลบัญชี.
