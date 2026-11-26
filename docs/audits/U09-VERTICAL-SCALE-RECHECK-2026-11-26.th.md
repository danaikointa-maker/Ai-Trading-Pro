# U09 Dashboard — รักษาสเกลราคาเมื่อเลื่อนตามแท่งล่าสุด

วันที่: 2026-11-26
ฐาน: `plan/unified-development-v4` ที่ `f8f742125759dbc2b2e901116b3387f0c732c856`
ขอบเขต: ปรับเฉพาะพฤติกรรมกราฟใน dashboard; ไม่เปลี่ยน API, market feed, broker, risk หรือ execution

## ช่องว่างที่พบ

`PriceChart.vue` เรียก `priceScale('right').applyOptions({ autoScale: true })` ทุกครั้งที่ `goLatest()` ทำงาน การเรียกนี้เกิดหลังแท่งใหม่และเมื่อผู้ใช้ติดตามแท่งล่าสุด จึงยกเลิกสเกลราคาแนวตั้งที่ผู้ใช้ปรับเอง แล้วคำนวณความสูงแท่งใหม่ระหว่างการอัปเดต

## การเปลี่ยนแปลง

- `goLatest()` เลื่อนเฉพาะแกนเวลาและคงสเกลราคาที่ผู้ใช้เลือกไว้
- รีเซ็ต price autoscale เมื่อเปลี่ยน feed, symbol หรือ timeframe เท่านั้น เพื่อให้บริบทใหม่เริ่มด้วยช่วงราคาที่อ่านได้
- เพิ่ม regression test สำหรับการ reset scale เฉพาะเมื่อ view context เปลี่ยน; ไม่เพิ่ม chart engine, dependency หรือ preference store ใหม่

## Verification

| Check | Result |
|---|---|
| `npm.cmd run test:chart-viewport` | PASS — **8 passed** |
| `npm.cmd ci` | PASS — 117 packages audited, 0 vulnerabilities |
| `npm.cmd run build` | PASS — Vite 8.3.8, **666 modules** |
| `git diff --check` | PASS |
| Authenticated browser visual / manual vertical zoom during repeated live ticks | NOT TESTED — ไม่มี local dashboard listener/MT5 terminal ในรอบนี้ |
| MT5 quote, reconnect, broker clock | NOT TESTED — ไม่เปิดหรือเปลี่ยนบัญชี |

## Acceptance และความปลอดภัย

U09 ยัง **PARTIAL** จนกว่าจะตรวจในเบราว์เซอร์ desktop/mobile และเห็นสเกลแนวตั้งคงที่ระหว่างการอัปเดต feed จริง การเปลี่ยนแปลงนี้เป็น chart presentation เท่านั้น; ไม่มี order, account, Risk Engine, Auto/Live หรือ Cloudflare operation เกิดขึ้น

## Rollback

ย้อนกลับได้ด้วยการ revert commit ที่แตะ `PriceChart.vue`, `chartViewport.js`, test และเอกสาร ไม่มี schema/config/data migration
