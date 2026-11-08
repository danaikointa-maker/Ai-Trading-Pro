# งานความปลอดภัย local และขั้นตอนส่งต่อ MT5

สถานะวันที่ 8 พฤศจิกายน 2026 — เอกสารนี้แยกผลโค้ด local ออกจากการติดตั้งจริง

## 1. งานโค้ดที่เปลี่ยน

### WebSocket

- `services/api_gateway/routes/ws.py` ตรวจ JWT และ user row ก่อน accept
  ก่อนสร้าง payload และก่อนส่งทุก frame ทั้ง `/ws/live` และ `/ws`
- บัญชีหาย/token ใช้ไม่ได้ปิดด้วย 4401, disabled/role เปลี่ยนปิดด้วย 4403
  และตรวจสิทธิ์ไม่ได้เพราะ DB failure ปิดด้วย 1011
- role ที่เปลี่ยนต้องเชื่อมต่อใหม่เพื่อรับ authority ปัจจุบัน ไม่ยึด role เก่าใน JWT
- ไม่ใช่ tenant isolation: payload ยังคงเป็น runtime ร่วม ต้องออกแบบ ownership แยกก่อนหลายบัญชี

### Notifications

- runtime สร้าง `Notifier(background=True)` เสมอ: `emit()` เขียน in-app ก่อน
  แล้ว enqueue แบบไม่รอพื้นที่; worker เดียวทำ HTTP/retry/pacing
- `alerts.queue_size` จำกัดจำนวนรอ ค่าเริ่มต้น 100
- payload มี `delivery_state`: `queued`, `completed`, `queue_full`, `stopped`
  และ delivery results ภายหลัง; completed หมายถึงพยายามส่งจบ ไม่ได้แปลว่าทุก channel สำเร็จ
- `status().queue` แสดง pending/capacity/dropped/errors/running/closed
- queue เต็มยังเก็บ in-app; worker error ไม่ทำให้ trading thread ล้ม
- shutdown ปิดรับงานใหม่และพยายาม drain ตาม budget; หากยังไม่จบ runtime บันทึก error
  HTTP ที่กำลังทำอยู่ไม่ถูกฆ่ากลางทาง ปุ่ม send-test หลัง close ถูกปฏิเสธ
- queue อยู่ในหน่วยความจำ ไม่ใช่ durable outbox: process crash อาจทำ outbound สูญหาย
  แม้ in-app ยังอยู่ และไม่มี replay อัตโนมัติเพื่อหลีกเลี่ยงส่งซ้ำ
- standalone Notifier ยังใช้ synchronous เป็นค่าเริ่มต้นเพื่อคง contract เดิม;
  explicit send-test ยังคงรอผล ไม่ถูกเรียกจาก trading loop
- ยังมี local DB writes ใน `emit()` ไม่ใช่การรับรองว่า trading loop ไม่มี blocking I/O ทุกชนิด

### Read-only bridge

- `bridge.enabled` ยังปิดโดยค่าเริ่มต้น; `bridge.read_only` เพิ่มค่าเริ่มต้น true
- read-only ปฏิเสธ enqueue ทุกชนิดและไม่ส่งคำสั่งเก่าที่ค้างอยู่
- runtime บังคับ Demo identity: login/server ต้องตรง config, trade_mode ต้องเป็น demo,
  connected ต้องเป็น true ทุก register/poll; poll ต้องมี account snapshot
- identity mismatch ล้าง snapshot เก่าและ orphan pending commands
- identity ฝั่งเซิร์ฟเวอร์เป็นข้อมูลที่ client ส่งภายใต้ token ไม่ใช่การรับรองจากโบรกเกอร์โดยตรง
  จึงต้องใช้คู่กับ EA guard และการตรวจ terminal จริง
- EA เพิ่ม `InpReadOnly=true`, `InpExpectedLogin`, `InpExpectedServer`;
  ตรวจ identity ก่อน/หลัง HTTP และก่อน order/close/modify
- EA read-only ส่งตำแหน่งทุกตัวในบัญชีเพื่อไม่ซ่อน exposure;
  เส้นทาง close/modify ที่ยังไม่อนุมัติใช้ magic ownership ไม่อาศัย comment อย่างเดียว
- EA อนุญาต HTTPS หรือ loopback รูปแบบ `http://127.0.0.1:port` เท่านั้น
- tests เดิมสำหรับ execution protocol ใช้ simulator configuration เฉพาะ tests
  ไม่เปลี่ยน default ของ production runtime

### เพิ่มเติม: exposure failure hardening (local)

- RiskEngine อ่าน positions ครั้งเดียวต่อ state เพื่อใช้ floating P&L/open lots/notional ชุดเดียวกัน
- อ่าน spec ไม่ได้, conversion rate unresolved, ตัวเลขราคา/volume/contract/rate ไม่เป็น finite
  หรือไม่เป็นบวก และ notional overflow จะทำให้ state ล้มเหลว ไม่ข้าม position หรือรายงาน exposure เป็นศูนย์
- ตรวจ exposure และ account/floating ตัวเลขก่อนบันทึก peak equity
- MT5 adapter แยก `positions_get() is None` (failure) ออกจาก tuple ว่าง (ไม่มี position จริง)
- Bridge adapter ต้องมี positions list อย่างชัดเจน; missing/null ไม่ถือว่าเป็นบัญชีว่าง
- execute_signal ใช้ refusal เดิมเมื่อ state อ่านไม่ได้ และไม่แก้ persistent kill switch
- Regression ครอบคลุมการไม่เรียก gateway.submit เมื่อ exposure ไม่ทราบค่า
- ยังไม่รับรอง live symbol spec provenance/completeness ทั้งระบบ, atomic snapshot ระหว่าง account
  และ positions, หรือ account currency อื่นนอกจาก contract ที่มีอยู่; ไม่ใช่การเปิด execution gate

### เพิ่มเติม: API execution idempotency (local)

- Gateway จอง key ด้วย unique constraint แบบ atomic ก่อนเรียก adapter; ไม่ใช้ INSERT OR REPLACE
- key เดิมไม่ถูกส่งใหม่ แม้ restart, positions อ่านไม่ได้/ไม่พบ หรือคำขอเดิมถูก reject/cancel
- key ซ้ำที่ request ต่างกัน หรือ persisted record/result เสียหาย จะปฏิเสธแบบ fail-closed
- adapter exception ไม่ใช่ rejection receipt: เก็บเป็น pending เพื่อรอ reconciliation
  รวมถึง validation exception ที่ adapter ไม่ได้ส่งกลับเป็น OrderResult.rejected อย่างชัดเจน
- recovery ต้องมี position ตรงเพียงหนึ่งรายการตาม signal/broker/symbol/direction/volume
- การไม่พบ position ไม่ยืนยันว่าไม่เคย execute (อาจปิดไปแล้ว); ห้ามลบ record หรือเปลี่ยน key
  เพื่อ retry โดยไม่มีการตรวจ orders/deals/history ผ่านช่องทางที่ได้รับอนุญาต
- ขอบเขตนี้คืออย่างมากหนึ่ง adapter send attempt ต่อ key ใน DB เดิม ไม่ใช่ broker exactly-once,
  EA durable deduplication หรือ multi-host fencing; partial fills/netting/history ยังไม่รับรอง

## 2. สิ่งที่ยังห้ามสรุปว่าผ่าน

- ยังไม่ compile MQL5, ไม่เปิด MT5, ไม่ผูกบัญชี และไม่เชื่อม VM ในช่องทางงานโค้ด
- tests ที่อ่าน source EA เป็นเพียง structural checks ไม่ใช่ compiler/runtime verification
- ยังไม่รับรอง durable deduplication ของ EA ข้าม restart, execution reconciliation,
  fill semantics, multi-host fencing หรือความพร้อม Demo execution
- ไม่เปลี่ยน `NO7_BRIDGE_READ_ONLY=false` หรือ `InpReadOnly=false` จากเอกสารนี้
- ยังไม่ใช่ full security audit; spec provenance/completeness และ tenant isolation ยังเป็นงานแยก

## 3. ส่งต่อช่องทาง MT5-DEV — ยังไม่ต้องใช้ VM

ดำเนินการเมื่อผู้ใช้พร้อมทดสอบ terminal local ผ่านช่องทางจัดการ ไม่ใช่คำสั่งให้เปิดตอนนี้

1. เปิด MT5 local ที่ติดตั้งแล้วและล็อกอิน Demo ด้วยตนเอง ไม่ส่ง password/token ผ่านแชท
2. ตรวจ login/server/symbol ที่ต้องการและยืนยันไม่มี EA/client อื่นส่งออร์เดอร์
3. ใช้ standalone read-only diagnostic ตาม README ก่อน ไม่ต้องติด bridge เพื่ออ่าน quote ครั้งแรก
4. ส่งผลแบบปิดข้อมูลอ่อนไหว: terminal build, Demo ยืนยันหรือไม่, server/symbol,
   quote timestamp และ error code โดยไม่ส่ง password/private key/token
5. ถ้า non-Demo, identity mismatch, terminal disconnected หรือ quote ผิดปกติ ให้หยุด
   ไม่เปลี่ยน guard หรือเปิด AutoTrading เพื่อให้ test ผ่าน

## 4. ส่งต่อรอบ bridge เมื่อ VM พร้อม

### VM100-ADMIN

1. ตรวจ inventory, backup/restore, user สิทธิ์จำกัด และ private connectivity ก่อน deploy
2. เตรียม release ที่ตรวจแล้ว, single worker, DB แยก และ HTTPS certificate ที่ VM200 เชื่อถือ
3. เก็บ config/secrets นอก Git แล้ว inject ผ่าน service ที่ผู้ดูแลอนุมัติ:

```text
NO7_BRIDGE_ENABLED=true
NO7_BRIDGE_READ_ONLY=true
NO7_BRIDGE_EXPECTED_LOGIN=<Demo login ที่ยืนยันจริง>
NO7_BRIDGE_EXPECTED_SERVER=<server ที่ตรง terminal ทุกตัวอักษร>
NO7_BRIDGE_TOKEN=<secret ใหม่ที่เก็บผ่านช่องทางปลอดภัย>
NO7_ALLOW_FULL_AUTO=false
```

ตัวอย่างข้างต้นเป็นรายการค่าที่ต้องเตรียม ไม่ใช่ไฟล์พร้อมรันหรือค่าให้ commit
ห้ามนำ simulator มาป้อน runtime ที่กำลังแสดงข้อมูลว่าเป็น broker feed จริง

### VM200-ADMIN / MT5-DEV สำหรับการทดสอบแยกที่อนุมัติ

1. MetaEditor เปิด source EA จาก release ที่ตรงกัน compile และเก็บ compiler log
   ต้องไม่มี errors; ตรวจ warnings ทุกตัว ห้ามถือ pytest แทน compiler log
2. ล็อกอิน Demo และกรอก `InpExpectedLogin`/`InpExpectedServer` ตรงบัญชีจริง
3. `InpReadOnly=true`; `InpAccountId=mt5-bridge-demo`; ใส่ scoped token ผ่านช่องทางปลอดภัย
4. `InpServerUrl` คือ base origin ไม่มี `/api` และไม่มี trailing slash
   ใช้ HTTPS ข้ามเครื่อง; loopback HTTP ใช้ได้เฉพาะการทดสอบ local ที่ตกลงไว้
5. ตั้ง Allow WebRequest เฉพาะ origin ที่ตรวจแล้ว ไม่เปิด DLL imports หรือ Algo Trading
   เพื่อการอ่านอย่างเดียว; หาก timer/HTTP ทำงานไม่ได้ให้ส่ง log กลับ ไม่ลด safety policy
6. Attach EA เพียงตัวเดียวต่อบัญชี/alias แล้วตรวจ register/poll และ snapshots ผ่าน API
7. ทดสอบ wrong identity/disconnect ในสภาพแวดล้อมที่แยกและไม่มี execution:
   ต้องไม่ refresh snapshot เก่า ไม่ส่งคำสั่ง และแสดงสถานะ stale/disconnected หรือ rejection
8. ยืนยัน broker orders/deals ไม่เพิ่มจากการทดสอบ read-only และตรวจ account-level positions ครบ

### เกณฑ์ส่งผลกลับ

- hostname/OS และ release commit + รายการ dirty changes ที่ใช้จริง
- compiler log + terminal build, ค่าที่ไม่ใช่ secrets และยืนยัน read-only ทั้งสองฝั่ง
- register/poll status, account/quote freshness และผล negative tests
- ยืนยันไม่มีออร์เดอร์ใหม่; ห้ามส่ง raw logs ที่มี Authorization/token/login โดยไม่ปิดข้อมูล
- rollback: detach EA, disable bridge และหยุด staging service ผ่านผู้ดูแล ไม่เปิด execution แทน

## 5. หลักฐานการทดสอบ local

ดู logs ที่ `storage/local-dev/qa/safety/` (ถูก ignore จาก Git)
และผลสรุปในบทสนทนาส่งงาน ต้องใช้ผลรอบสุดท้ายหลังแก้ทั้งหมด
ก่อนผ่าน gate ภายนอกต้องมีหลักฐานจากเครื่องจริงตามข้อ 3–4 เพิ่มเสมอ

### Integration รอบ 2026-11-08

- รวม safety `61fbb89` กับ main `b4cb632` บน `integration/safety-main-2026-11-08`;
  ไม่แก้ประวัติ branch เดิม และไม่ merge เข้า main
- WS ตรวจ user/role ต่อเนื่องพร้อม connection lease และคืน lease เมื่อ accept/revocation ล้มเหลว
- Notification คง bounded background queue พร้อม signed durable retry outbox;
  serialize send/drain และ shutdown รอทั้ง delivery และ drain workers ภายใน budget เดียว
- Background delivery เก็บ level/symbol; model validation ใช้ registry แยกจาก runtime
- Risk ปฏิเสธ persisted peak/P&L ที่ไม่ finite ก่อนเขียน peak; `now=0` ใช้ได้
- Bridge ปฏิเสธ unknown symbol แทนการใช้ default spec โดยไม่มีข้อมูลต้นทาง
- ผล final local: **599 passed, 39 skipped, 1 warning**, pytest exit 0;
  Dashboard Vite build exit 0; Ruff `--select F,E9` ผ่านใน services/tests/integrations/packages
- Skipped ไม่ใช่ผ่าน: real Redis ไม่มี binary และ bash/script checks ที่ environment ไม่รองรับ
  หรือเป็น intentional skips; warning มาจาก Starlette testclient deprecation
- หลักฐาน: `integration-final.{log,err,xml,exit}`, `integration-build.{log,err,exit}`
  ใน local QA directory ที่ถูก ignore; ไม่เผยแพร่ raw runtime logs/secrets

### Gate ที่ยังไม่ปิดหลัง integration

1. Spec provenance/completeness: การปฏิเสธ unknown symbol ไม่ได้ยืนยันทุก field;
   ยังต้องตรวจ complete contract/lot/tick specs และ conversion ตาม account currency จริง
2. Partial fill/netting/history: ยังคง strict single-position reconciliation;
   ambiguity ต้อง pending/manual review ห้าม retry ด้วย key ใหม่เพื่อบังคับส่ง
3. EA durable deduplication และ broker exactly-once ยังไม่รับประกัน
4. Tenant/account isolation ต้องกำหนด ownership/data migration และทดสอบข้ามบัญชีก่อนเปิดใช้หลาย tenant
5. MQL5 compile, MT5 Demo/VM acceptance และ real Redis integration ต้องมีหลักฐานจาก environment ที่รองรับ

รายการเหล่านี้เป็นข้อจำกัดและงานต่อ ไม่ใช่สิ่งที่ full local suite รับรองว่าเสร็จแล้ว
คง read-only/Demo safety gates จนกว่าจะผ่านการตรวจแยกที่ได้รับอนุญาต