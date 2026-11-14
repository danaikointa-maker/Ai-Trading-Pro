# TradeAi — หน้าที่เครื่องและแผนเชื่อมต่อเป็นรอบ

วันที่ทบทวน: 8 พฤศจิกายน 2026

## 1. สถานะและขอบเขต

เอกสารนี้เป็นแผนประยุกต์ Blueprint v3 กับ repository ปัจจุบัน ไม่ใช่หลักฐานว่าติดตั้งหรือเชื่อม VM สำเร็จแล้ว

- Source จริง: `C:\workspace\Ai-Trading-Pro` ไม่ใช่ `C:\workspace\TradeAi` ตามตัวอย่าง Blueprint ไม่ย้าย/clone ซ้ำโดยอัตโนมัติ
- Commit ที่ตรวจ: `e25e72335600d189c7893a805b2c902b9d511e43` พร้อมงานแก้ไขที่ยังไม่ commit
- Blueprint ต้นทาง: `C:\Users\danai\Downloads\TradeAi-Professional-Master-Blueprint-v3\TradeAi-Professional-Master-Blueprint`
- สำเนาต้นฉบับครบชุดอยู่ในโปรเจกต์แล้ว: [Blueprint v3 และหมายเหตุนำเข้า](blueprint-v3/IMPORT-NOTES.md) ใช้ลิงก์นี้ต่อได้โดยไม่ต้องมีโฟลเดอร์ Downloads ต้นทาง
- อ่านเอกสารหลัก README, AGENTS, เอกสาร 00–12, config ตัวอย่าง, inspection/preflight scripts และ templates แล้ว; ไม่ได้รันสคริปต์บน VM
- รอบนี้ตรวจ source และเขียนแผนเท่านั้น ไม่เปิดพอร์ต ไม่ตั้ง SSH/TLS ไม่คัดลอก secrets ไม่ deploy และไม่ส่งออร์เดอร์
- ผลทดสอบจากรอบก่อนเป็น historical evidence ไม่ใช่ผลทดสอบใหม่ของรอบนี้

### ขอบเขตช่องทางงานโค้ดที่ผู้ใช้กำหนด

- ช่องทางนี้ทำเฉพาะโค้ด การทดสอบ local แบบแยกจากระบบจริง และเอกสารที่เกี่ยวข้องภายใน `C:\workspace\Ai-Trading-Pro` โดยรักษางานเดิมที่ยังไม่ commit
- ใช้ Blueprint ในโปรเจกต์เป็นข้อมูลอ้างอิง ไม่ใช่คำอนุญาตให้ติดตั้ง เชื่อมต่อ หรือเปลี่ยนระบบภายนอก
- ทำได้ใน repository: backend/frontend, source EA, contracts, safety guards, tests, example config และ scripts สำหรับส่งต่อให้ผู้ดูแลตรวจ ไม่รัน scripts ที่เปลี่ยนระบบภายนอก
- งาน VM100/VM200/Proxmox, SSH/RDP, firewall/VPN/TLS จริง, storage/backup/restore, deploy/service management, ติดตั้งหรือเปิด MT5/AutoTrading และการเชื่อมบัญชี/ส่งออร์เดอร์ ให้ดำเนินการผ่านช่องทางจัดการแยก
- เมื่อพบงานนอกขอบเขต ให้แจ้งเครื่องและช่องทาง เหตุผล สิ่งที่ต้องเตรียม ขั้นตอน/ข้อควรระวัง เกณฑ์ยอมรับ และหลักฐานที่ต้องส่งกลับ โดยไม่ขอ secrets ในแชท
- หยุดเฉพาะส่วนที่ต้องพึ่งระบบภายนอกและทำงานโค้ดที่ไม่ติด dependency ต่อได้ ห้ามอ้างว่า remote/deployment/MT5 ผ่านจากผล unit tests หรือ mocks
- หากต้อง compile/test EA ด้วย terminal หรือ toolchain นอกขอบเขต ให้ส่งต่องานและระบุ NOT TESTED จนได้รับหลักฐานจริง
- ตารางรอบงานด้านล่างเป็นภาพรวมข้ามช่องทาง ไม่ใช่สิทธิ์ให้ช่องทางงานโค้ดดำเนินการภายนอกเอง; ไม่ commit/push หรือเปิด Demo execution โดยไม่มีคำอนุมัติแยก
- ก่อนถึงงานภายนอก ให้ส่งขั้นตอนติดตั้ง/เซตอัพ/ตั้งค่า วิธีทำงาน วิธีตรวจผล และเงื่อนไขหยุดสำหรับช่องทางปลายทางในบทสนทนาที่กำลังทำงาน ไม่ใช่การแจ้งเตือนเบื้องหลัง

### ความคืบหน้างานโค้ด local

- 8 พฤศจิกายน 2026: เพิ่มการปฏิเสธแบบ fail-closed เมื่อ `risk.state()` ล้มเหลวใน decision cycle, risk-state view และก่อน submit คำสั่ง พร้อม regression tests ไม่เชื่อม MT5/VM
- สถานะ fallback แสดง kill switch ชั่วคราวเพื่อบล็อก ไม่เขียนทับ persistent kill switch; เมื่ออ่าน risk state สำเร็จใช้สถานะจริงตามเดิม
- งานนี้ไม่ใช่การตรวจ risk engine ครบทุกกรณี: exposure/spec ที่อ่านไม่ได้, synchronous notifications และ WebSocket reauthorization ยังต้องตรวจแยกก่อน execution gate
- รอบถัดมา: เพิ่ม WebSocket reauthorization ทุก frame, runtime notification worker queue และ read-only/Demo identity guard ใน relay/API/source EA แล้ว ดู [สถานะและขั้นตอนส่งต่อปัจจุบัน](SAFETY-HANDOFF.th.md) ข้อความ backlog/EA ในส่วนทบทวนเดิมด้านล่างเป็นหลักฐานก่อนแก้ ไม่ใช่สถานะโค้ดล่าสุด
- MQL5 compile, MT5/VM integration, durable deduplication ข้าม restart และ execution reconciliation ยังไม่ยืนยัน ต้องทำผ่านช่องทางแยกและไม่เปิด execution จากผล local tests

## 2. หน้าที่แต่ละเครื่อง

| เครื่อง | หน้าที่เป้าหมาย | สิ่งที่ไม่ควรทำ | สถานะหลักฐาน |
|---|---|---|---|
| DEV PC เครื่องนี้ | source, VS Code/Cline, tests, Vue build, QA/manual, release packaging; local paper และ MT5 Demo probe แยก | เป็น executor แข่งกับ VM200; ใช้ local DB เป็นฐานข้อมูลกลาง | ตรวจ source และไฟล์ local แล้ว; MT5 probe มีโค้ด แต่ยังไม่มีหลักฐานอ่านบัญชีจริงสำเร็จ |
| VM100 Ubuntu | FastAPI/REST/WS, Vue static, market normalization, analysis/strategy/risk, model inference, backtest, journal/report, canonical application DB และ server-side bridge relay | เรียก terminal MT5 ของ Windows ผ่าน Python แบบ local; ฝึกหนักใน trading fast path | บทบาทตาม Blueprint; OS/IP/services/resources จริงยังไม่ตรวจ |
| VM200 Windows | MT5 Demo, MetaEditor/EA, market/account/position snapshots; ภายหลังเป็น executor เดียวของบัญชี พร้อม local guard และ reconciliation | รัน Trading Core อีกชุด, central DB, training/LLM; เปิด public order listener | บทบาทตาม Blueprint; MT5/EA/บัญชี/การ compile บน VM ยังไม่ตรวจ |
| Proxmox host | VM100/200, VM networking, storage, backup/restore, resource management | ติดตั้งแอป/DB/trading runtime ลง host; ใช้ root เป็นบัญชี coding agent | Blueprint ระบุ `192.168.1.254`; ยังไม่ยืนยัน connectivity หรือสภาพเครื่อง |
| ที่เก็บ backup แยก | สำรอง VM/DB/config/model และทดสอบ restore แบบแยกวง | ถือ snapshot บน host เดียวเป็น off-host backup | ยังไม่ทราบอุปกรณ์ที่พร้อมใช้งาน |

RAM/vCPU ใน Blueprint (VM100 16 GiB/2 vCPU, VM200 8 GiB/2 vCPU, host 32 GiB) เป็นเป้าหมาย ไม่ใช่ค่าที่ตรวจจริง และต้องวัด headroom ก่อนเปิดงานหนัก

Blueprint รายงาน Seagate 3TB มี I/O errors: ให้ถือเป็นข้อห้ามใช้เป็น backup จนมีการตรวจโดยผู้ดูแล ไม่ใช่ผล SMART ที่ตรวจใหม่ในรอบนี้ ห้ามซ่อมเขียน/ย้าย disk/LVM จากแผนนี้

## 3. โค้ดส่วนไหนอยู่ที่ไหน

| โค้ดใน repository | ตำแหน่งทำงานเป้าหมาย | หน้าที่ |
|---|---|---|
| `apps/web-dashboard/` | build บน DEV; static assets บน VM100; browser ผู้ใช้แสดงผล | UI ไม่เก็บ broker secrets; ไม่เรียก MT5 โดยตรง |
| `services/api_gateway/` | VM100 | auth/API/WS และประกอบ runtime; เริ่ม single worker |
| `services/market_data/`, `services/strategy_engine/` | VM100 | ตรวจแหล่งข้อมูล/ความสดและวิเคราะห์/สร้างสัญญาณ |
| `services/ai_forecast/`, `services/risk_engine/` | VM100 | inference, planner และ risk veto; training แยกงาน/จำกัดทรัพยากร |
| `services/backtest_engine/` | DEV และ VM100 แบบ offline/research | backtest บน dataset แยก ไม่เป็นเส้นทางส่งออร์เดอร์ |
| `services/execution_gateway/`, `services/bridge/` | VM100 | ประสาน intent/queue/receipt; ไม่ใช่ terminal execution โดยตรง |
| `integrations/brokers/bridge.py` | VM100 | adapter อ่าน snapshots/ส่งคำสั่งผ่าน relay ภายหลังผ่าน gate |
| `bridge/No7BridgeEA.mq5` | source ตรวจบน DEV; compile/ติดตั้งบน VM200 | client outbound ไป VM100; มี order/close/modify จึงยังไม่ใช่ read-only EA |
| `integrations/brokers/mt5_readonly.py`, `scripts/check-mt5-demo.ps1` | DEV ตอนนี้; VM200 ภายหลังเมื่อเตรียม Python | probe Demo สถานะ/quote แบบ standalone ไม่ป้อน Dashboard โดยอัตโนมัติ |
| `integrations/brokers/mt5_live.py` | Windows เท่านั้นเมื่อเลือก direct-terminal architecture | มีเส้นทางส่งคำสั่ง ไม่ใช่เส้นทางหลัก VM100→VM200 และไม่ควรเปิดร่วม EA executor |
| `packages/persistence/`, `packages/shared_schemas/` | VM100 เป็น authority; DEV ใช้ test/local DB แยก | DB/schema/contracts ไม่แชร์ SQLite ผ่าน network filesystem |
| `services/notification/`, `integrations/no7_local_ai/` | VM100 เมื่อผ่านการตรวจ | notification และ read-only explanation; ไม่ให้ LLM อนุมัติ/ส่งออร์เดอร์ |
| `tests/`, scripts/docs | DEV; เลือก test บน staging ตามความเหมาะสม | หลักฐานก่อน deploy และคู่มือที่ตรงเวอร์ชัน |

ไม่ต้องแตกทุกโฟลเดอร์ `services/` เป็น VM/container ใหม่ โค้ดปัจจุบันประกอบเป็น modular application; การแยก worker ต้องออกแบบ contracts/ownership ก่อน

## 4. ช่องทางเชื่อมต่อ (เป้าหมาย ยังไม่ตั้งจริง)

```text
DEV --Git/build/release--> verified artifact --deploy--> VM100 application
DEV --SSH management--------------------------------> VM100
DEV --SSH management / interactive console-----------> VM200
DEV --restricted admin UI/console--------------------> Proxmox

Browser --HTTPS + authenticated REST/WSS-------------> VM100 reverse proxy
VM100 reverse proxy --loopback-----------------------> FastAPI :8000

VM200 EA --outbound HTTPS register/poll---------------> VM100 bridge API
VM200 EA <--poll response: approved intents----------- VM100 (future gated Demo)
VM200 MT5 <----------broker terminal connection------> Broker Demo
VM200 EA --snapshots + receipts----------------------> VM100
VM100 --managed backup/export------------------------> healthy separate storage
```

### Management และ data plane ต้องแยกกัน

| ช่องทาง | ผู้เริ่มเชื่อม | จุดหมาย/พอร์ตเป้าหมาย | เตรียมเมื่อใด |
|---|---|---|---|
| `DEV` | terminal local | workspace จริง | ตอนนี้ |
| `VM100-ADMIN` | DEV | SSH ของ Ubuntu ปกติ 22 ผ่าน LAN/VPN; user/key/host fingerprint จริง | รอบ 1–2 |
| `VM200-ADMIN` | DEV | SSH Windows ถ้ามี; console/RDP ที่ผู้ดูแลอนุมัติสำหรับ GUI/MT5 | รอบ 1–2 |
| `PVE-ADMIN` | ผู้ดูแลจาก DEV | Proxmox UI เป้าหมาย 8006; SSH เฉพาะงานที่อนุญาต | รอบ 1 |
| `APP-QA` | browser/QA | VM100 HTTPS เป้าหมาย 443; FastAPI loopback 8000 | รอบ 3 |
| `MT5-BRIDGE` | VM200 | VM100 HTTPS เป้าหมาย 443 + trusted certificate + account-scoped key | รอบ 4 |
| `BACKUP-OPS` | ผู้ดูแล/งาน backup ที่อนุมัติ | storage/protocol ที่เลือกหลัง audit ไม่เดาพอร์ต | ก่อนเปลี่ยนระบบ |

ชื่อช่องทางเป็นชื่อจัดการ/แชท/VS Code window ที่เสนอ ยังไม่ได้สร้าง SSH profiles หรือเปิดการเชื่อมต่อไว้
WSL/Remote SSH แต่ละเครื่องมี workspace, environment และ terminal ของตนเอง ต้องตรวจ hostname/path ก่อนทุกคำสั่ง ห้ามใช้ `.venv` Windows บน Ubuntu

### Contract ที่มีจริงกับตัวอย่างที่ยังไม่มี

- API จริง: `POST /api/bridge/register`, `POST /api/bridge/poll`, `GET /api/bridge/status` (admin), `GET /api/bridge/session`, `POST /api/bridge/cancel` (admin)
- EA เรียก register/poll โดยใช้ Bearer bridge token แยกจาก user JWT
- EA ใช้ `InpServerUrl` เป็น **base origin ไม่มี `/api` ต่อท้าย** เพราะโค้ดเติม `/api/bridge/...` เอง; `InpToken`, `InpAccountId`, `InpSymbols` เป็น inputs จริง
- ตัวอย่าง Blueprint `NO7_BRIDGE_URL`, `NO7_BROKER_ACCOUNT`, `NO7_EXECUTION_ENABLED` ไม่ได้ถูกอ่านโดย EA อัตโนมัติ ต้องทำ configuration mapping ที่ตรวจได้ก่อน ห้ามเชื่อว่าใส่ ENV แล้วปิด order path สำเร็จ
- `/api/v1/bridge/heartbeat`, `/api/v1/market/batch`, `/api/v1/execution/*` เป็นข้อเสนอใน Blueprint ไม่ใช่ endpoint ที่พร้อมใช้แล้ว
- `NO7_ROOT` ช่วย resolve runtime paths แต่ settings ปัจจุบันอ่าน `.env` จาก repository root และ config จาก directory ของ source โดย default; env file นอก checkout ต้องถูก inject โดย launcher/service อย่างชัดเจน
- ไม่เปลี่ยน endpoint เดิมของ Dashboard โดยไม่มี compatibility tests

## 5. State และผู้รับผิดชอบ

- Canonical application ledger/state อยู่ VM100; broker เป็นแหล่งยืนยันสถานะ orders/deals/positions ภายนอก ต้อง reconcile ทั้งสอง ไม่ถือ DB หรือ HTTP 200 เป็นหลักฐาน fill
- VM200 เก็บ broker login ใน terminal/account Windows; bridge secret แยกเก็บแบบปลอดภัยทั้งสองปลาย ไม่ส่งผ่านแชท/Git
- DEV มี local/test storage ของตนเอง ไม่ copy DB ทับ VM100 และไม่ถือ lease ใน DB คนละไฟล์ว่าป้องกัน executor ข้ามเครื่องได้
- เป้าหมายคือหนึ่ง decision leader และหนึ่ง executor ต่อบัญชี; lease/fencing/restart ต้องพิสูจน์ก่อนทำ multi-host/HA
- งาน training/LLM เป็น slow path; ไม่บล็อก data/risk/execution และไม่ auto-promote model
- SQLite เริ่มต้นคงไว้บน VM100; PostgreSQL/Redis เป็นงานภายหลังที่มี migration/backup/parity/rollback ไม่ใช่ prerequisite สำหรับ local probe

## 6. ช่องว่างก่อนเชื่อม

1. **EA ยังไม่พร้อมรับรอง read-only:** มี `OrderSend`, order/close/modify; ยังไม่พบ explicit read-only input หรือ actual-account Demo guard แบบ probe ใหม่ ต้องเพิ่ม/ทดสอบก่อนผูกบัญชีจริงของ terminal แม้ตั้ง alias ว่า demo
2. **EA duplicate memory:** `g_executed_ids` เป็น array ในหน่วยความจำ ไม่ใช่ durable guard ข้าม restart; ต้องตรวจร่วม server store และ broker history ห้ามรับรอง exactly-once
3. **EA ยังไม่ได้ compile/run บน VM:** source เองระบุ untested ต้องใช้ MetaEditor เก็บผลจริง
4. **Safety debt:** notification HTTP/retry อยู่ในเส้นทาง synchronous; risk-state fallback และ WS auth หลังเชื่อมต่อยังต้อง regression review ก่อน order gate
5. **Backtest:** โค้ดมี `backtest-proxy`/`rule-proxy` ไม่ใช่การรับรอง LightGBM เดียวกับ inference
6. **Multiuser:** มี role ไม่เท่ากับแยก tenant/บัญชี; ต้องทดสอบ ownership และ privacy ก่อนเปิดหลายผู้ใช้
7. **เครื่องปลายทาง:** IP, hostname, OS/support status, ทรัพยากร, SSH fingerprints, firewall, TLS และ restore ยังไม่ยืนยัน
8. **เอกสารบางส่วนล้าหลัง:** LIMITATIONS มีข้อความเก่าว่า EA ยังไม่เขียนทั้งที่มี source แล้ว; อ้าง implementation และหลักฐานใหม่เป็นหลัก ไม่แก้ทั้งเอกสารโดยไม่อยู่ใน scope

## 7. แผนปฏิบัติเป็นรอบและจังหวะเตรียมเครื่อง

| รอบ | งาน | ต้องเตรียมเครื่อง/ช่องทาง | Gate ก่อนจบรอบ |
|---|---|---|---|
| 0 — ตอนนี้ | ตกลงบทบาท อ่าน Blueprint เทียบ source; ปิด live; local paper/standalone Demo probe | `DEV` เท่านั้น; MT5 local ต้องล็อกอิน Demo ด้วยตนเองหากจะ probe | บันทึก commit/dirty state, ขอบเขต, ไม่อ้างว่าต่อ VM แล้ว |
| 1 — inventory/recovery | ตรวจ Proxmox/guest แบบ read-only, IP/OS/resources/clock/storage และหลักฐาน backup/restore | แจ้งเตรียม `PVE-ADMIN`, `VM100-ADMIN`, `VM200-ADMIN`, `BACKUP-OPS`; เริ่มผ่าน console ได้ | inventory จริงครบ; ไม่เปลี่ยน storage หาก restore ยังไม่ผ่าน |
| 2 — management | ตั้ง/ตรวจ least-privilege SSH, fingerprint, LAN/VPN/ACL, ชื่อ endpoint | DEV→VM100 และ DEV→VM200; ผู้ดูแลยืนยันสิทธิ์ก่อนเปลี่ยน users/firewall | แยก terminal/host ชัด, เข้าได้เฉพาะที่อนุญาต; ไม่มี public order/DB |
| 3 — Ubuntu staging | package release จาก source ที่ตกลง, Python env บน Ubuntu, Vue dist, data paths/secrets, single worker และ TLS proxy | `VM100-ADMIN`, `APP-QA`; ยังไม่ต้อง EA execution | tests/build/auth/WS/restart/backup ผ่าน; bridge/order disabled |
| 4 — Windows read-only bridge | ตรวจ/เพิ่ม Demo identity guard และ read-only ทั้ง client/server ก่อน compile EA; snapshots→VM100→UI | แจ้ง `VM200-ADMIN` + `VM100-ADMIN`; trusted URL/token/cert; local probe ไม่แทน bridge acceptance | บัญชี/ราคา/spec/freshness ถูกต้อง; ปฏิเสธคำสั่งซื้อขายทุกชนิด; ไม่มีออร์เดอร์ |
| 5 — safety/reconciliation | fail-closed DB/risk, stale/disconnect, expiry, account change, duplicate/restart/UNKNOWN, receipts และ ownership | ทั้งสอง VM และ QA; ทดสอบไม่ส่งคำสั่งจริงก่อน | หลักฐาน recovery และ unique executor; ช่องว่าง P0 ถูกปิด |
| 6 — Demo execution เท่านั้น | พิจารณาส่งคำสั่ง Demo ขนาด/ขอบเขตที่ตกลงหลังอนุมัติแยก | แจ้งผู้ใช้ก่อนเปิดเสมอ; VM200 เป็น executor เดียว; DEV ไม่ส่งคำสั่ง | manual approval, risk/kill switch, broker receipt และ ledger reconcile; ไม่เลื่อน live |
| 7 — research/คู่มือ | frozen datasets, ML-aware backtest, journal/report, real-screen QA/manual, จำกัดงาน AI | VM100 research + DEV QA; VM200 เฉพาะข้อมูลที่อนุญาต | ผล reproducible, source label จริง, คู่มือภาพระบบจริง, ข้อจำกัดชัด |
| 8 — multiuser/release | migration ที่จำเป็น, tenant/privacy, load/soak, restore/rollback และ sign-off | เตรียมแต่ละเครื่องตาม change scope ไม่ติดตั้งทั้งหมดพร้อมกัน | ผ่าน acceptance ที่ระบุ; DEMO_ACCEPTED ไม่เท่ากับ LIVE |

ระหว่างรอ backup/VM สามารถพัฒนา/tests แบบ local ไม่ทำลายข้อมูลได้ ไม่จำเป็นต้องหยุดงาน DEV ทั้งหมด

## 8. รูปแบบแจ้งก่อนเปลี่ยนเครื่องทุกครั้ง

ก่อนคำสั่งที่ต้องไปอีกเครื่อง ให้แจ้งในแชท:

1. รอบ/เป้าหมาย: งานอะไร ทำไมต้องใช้เครื่องนี้ตอนนี้
2. ช่องทางที่ต้องเปิด: `DEV` / `PVE-ADMIN` / `VM100-ADMIN` / `VM200-ADMIN` / `APP-QA` / `BACKUP-OPS`
3. เครื่องต้นทาง→ปลายทาง, hostname/IP ที่ยืนยัน, workspace/runtime path, identity/สิทธิ์ (ไม่แสดง secret)
4. ชนิดงาน: read-only หรือเปลี่ยน state; คำสั่ง/ไฟล์/service/พอร์ตที่ได้รับผล
5. สิ่งที่ผู้ใช้ต้องเตรียมและ permission ที่ต้องอนุมัติ โดยไม่ส่ง password/private key ในแชท
6. เงื่อนไขก่อนเริ่ม, ผลที่ต้องเห็น, rollback/stop condition และหลักฐานหลังจบ

แจ้งซ้ำเมื่อเปลี่ยน scope/host/order mode; ห้ามข้ามไปใช้ VM หรือแก้ network เพราะเพียงมีแผนนี้อยู่ การแจ้งนี้เกิดเมื่อทำงานในรอบสนทนาจริง ไม่ใช่ระบบแจ้งเตือนเบื้องหลัง

### ข้อมูลที่ขอเมื่อเริ่มรอบ 1 (ไม่ใช่ secrets)

- วิธีเปิด console Proxmox ที่ใช้อยู่และยืนยัน host address
- VM100/VM200 มีอยู่/เปิดอยู่หรือไม่, hostname, IP/subnet ที่เห็นจริง, OS/version
- user สำหรับจัดการ (ไม่ใช่รหัสผ่าน), SSH เปิดหรือยัง, fingerprint ที่ตรวจจาก console
- backup target ที่สุขภาพดี และวัน/ผล restore ล่าสุด
- VM200 มี MT5/MetaEditor และบัญชี Demo หรือยัง; มี EA/โปรแกรมอื่นส่งคำสั่งบัญชีเดียวกันหรือไม่

## 9. หลักฐานอ้างอิงและสถานะ

| ข้อสรุป | หลักฐาน | สถานะ |
|---|---|---|
| บทบาท VM100/VM200/Proxmox | Blueprint docs/01, 02, 05, 09 และ hosts.example.yaml | เป้าหมาย ยังไม่ deployed/verified |
| API bridge และ token | `services/api_gateway/routes/bridge.py`, `services/bridge/relay.py` | ตรวจ source |
| EA inputs/order paths/duplicate arrays | `bridge/No7BridgeEA.mq5` | ตรวจ source; compile/runtime ยังไม่ทดสอบ |
| MT5 local diagnostic แยก runtime | `integrations/brokers/mt5_readonly.py`, `scripts/check-mt5-demo.ps1` | ตรวจ source; account/quote จริงยังไม่ยืนยัน |
| configuration paths | `packages/shared_schemas/settings.py` | ตรวจ source |
| broker adapter selection | `integrations/brokers/registry.py`, `config/brokers.yaml` | ตรวจ source |
| risk/auth/notification backlog | `services/api_gateway/state.py`, `services/api_gateway/routes/ws.py`, `services/notification/notifier.py` | source-review concern ไม่ใช่ regression result ใหม่ |
| rule proxy ใน backtest | `services/backtest_engine/backtester.py` | ตรวจ source |

ทบทวนเอกสารเมื่อเปลี่ยน endpoint, machine roles, paths, executor/state ownership หรือผ่าน gate ใหม่ เก็บสถานะจริงและข้อเสนอแยกกันเสมอ