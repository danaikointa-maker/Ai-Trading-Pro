# ตรวจสอบ Cloudflare, VM100 และ Trading Pro — 2026-11-24

สถานะเอกสาร: **Read-only audit** บน planning baseline `7f4d574eaf1a308794ab4a89da436d7dd9e21853` เท่านั้น

## สรุป

`agent.youridea168.com` มี DNS ผ่าน Cloudflare และใบรับรอง HTTPS ใช้งานได้ แต่คำขอ HTTPS ได้ **502** เพราะ Cloudflare Tunnel ชี้ไป `https://localhost:8080` ขณะที่ VM100 ไม่มี service ฟัง port 8080. บน VM100 มี Trading Pro listeners ที่ `127.0.0.1:8000`, `127.0.0.1:18081` และ isolated V4 staging `127.0.0.1:18082`; ทั้งหมดไม่ใช่ Office API ที่ตรวจรับแล้ว และห้ามนำไปแทน origin เดิมโดยอัตโนมัติ.

เครื่อง VM100 มี IP ภายใน `192.168.1.10` แต่แอปที่ตรวจพบ bind เฉพาะ loopback. จาก PC เข้าถึง SSH `192.168.1.10:22` ได้ แต่ TCP ไปยัง application ports ที่ตรวจไม่สำเร็จ. ดังนั้น **ยังไม่มีการเชื่อมต่อ VM100 ↔ Windows Trading Pro ที่ยืนยันว่าพร้อมใช้งาน**.

ไม่แก้ DNS, Cloudflare route, Access policy, firewall, service, database หรือ broker state. ไม่อ่าน `.env`, token, private key หรือ broker credential. ไม่มีคำสั่งซื้อขาย.

## ผลตรวจ 5 ประเด็น

| # | ประเด็น | ผล | หลักฐานและข้อจำกัด |
|---|---|---|---|
| 1 | Public DNS และ HTTPS | **PASS บางส่วน** | DNS ตอบ Cloudflare edge addresses; TLS certificate validation สำเร็จ. GET `/` และ `/api/system/health` ผ่าน hostname ได้ HTTP 502 จึงยืนยันได้เพียง DNS/TLS และการไปถึง Tunnel edge ไม่ใช่ความพร้อมของแอป |
| 2 | Cloudflare Tunnel และ origin | **FAIL — origin unreachable** | `cloudflared.service` active/enabled, version `2026.11.1`; ใช้ remote-managed `--token-file` โดยไม่ได้อ่านค่า token. Sanitized logs แสดง origin `https://localhost:8080` และ `connect: connection refused`. Local metrics readiness ตอบสนอง แต่ไม่มี listener port 8080 |
| 3 | การเข้าจาก LAN | **FAIL — ยังไม่มี app listener บน private interface** | VM100 `ai-server`, `ens18`, `192.168.1.10/24`. Listener 8000/18081/18082 bind `127.0.0.1`. จาก Windows TCP port 22 สำเร็จ; ports 8080/18081/18082 ไม่สำเร็จ. ไม่ตรวจ/แก้ UFW เพราะต้องใช้สิทธิ์ root และไม่เปลี่ยน firewall |
| 4 | บทบาทของ API ที่มีอยู่ | **BLOCKED — ไม่มี origin ที่ตรงบทบาท** | 8000 เป็น development/simulated runtime; 18081 เป็น runtime เก่าที่แยกไว้; 18082 เป็น V4 Trading Pro API ใน simulation mode โดย publisher credentials ไม่ได้ตั้งค่า. ไม่มี Office API ที่ตรวจสอบแล้ว. ห้าม route hostname สาธารณะไปยัง API เหล่านี้ |
| 5 | Windows Trading Pro ↔ VM100 identity/API | **NOT TESTED / NOT READY** | Source V4 มี `/api/explain` แบบ local/read-only แต่ไม่พบ service client ที่เชื่อมต่อ Office API. Keycloak + Vault PKI เป็นแนวทางที่เลือกไว้ แต่ยังไม่ provision; issuer/realm/client identity และ tenant/project/trading workspace mapping ยังไม่ครบ. Draft PR #34 มีเอกสาร identity boundary แต่ target เป็น `integration/unified-tradeai` และไม่ใช่ live connector |

## สถานะ Cloudflare Access

**NOT TESTED.** การเรียก `/cdn-cgi/access/get-identity` ได้ 404 ซึ่งไม่ใช่หลักฐานพอจะสรุปว่า Access policy เปิดหรือปิด. ยังไม่ได้ตรวจ Access application, hostname policy, identity provider, unauthenticated denial หรือ authenticated allow flow ในบัญชี Cloudflare. ห้ามถือว่า 502 เป็น Access protection.

## ช่องว่างและแนวทางเชื่อมต่อที่ต้องทำต่อ

1. กำหนด/ติดตั้ง **VM100 Office API แยกบทบาท** ก่อน โดยใช้ source checkout/branch ที่ผ่าน V4 review และไม่เปลี่ยน runtime 8000 หรือ 18081. API นี้ควรให้บริการ office/dev/QA/video/task metadata และ advisory ที่ตกลงไว้; ห้ามมี broker credentials, order endpoint, MT5 command bridge หรือสิทธิ์สั่ง execution.
2. เลือก application port และ health/readiness contract หลังตรวจ service จริง. ให้ process bind loopback สำหรับ Tunnel; ถ้าต้องให้ PC ภายในเรียก `192.168.1.10` โดยตรง ให้เพิ่ม private ingress/reverse proxy แยกที่ listen บน private interface พร้อม firewall จำกัดเฉพาะ PC/VPN และ authentication. อย่าเปิด `0.0.0.0` หรือ port สู่ LAN แบบไม่จำกัด.
3. Export/backup Tunnel route configuration ก่อนแก้; ตั้ง origin ให้ตรง scheme/port ของ Office API หลังตรวจ health บน VM100 แล้วเท่านั้น. Cloudflare Access ต้องปฏิเสธ unauthenticated requests; application auth/service identity ต้องตรวจ token audience, issuer, expiry, scope และ client identity ซ้ำ.
4. Provision Keycloak + Vault PKI ตามการเลือกเดิม แล้วออก scoped service identity ให้ Windows Trading Pro. อนุญาตเฉพาะ API methods/resources ที่ผ่าน schema review; ใช้ tenant/project/workspace mapping ที่ยืนยันแล้วทุก request. ห้ามแชร์ account state ข้าม broker/trading account.
5. พัฒนา Windows client ผ่าน REST/HTTPS (และ WSS หากจำเป็น) แบบ outbound. Client ต้อง fail closed เมื่อ auth, hostname, TLS, freshness หรือ ownership ตรวจไม่ผ่าน. VM100/LLM/webhook ส่งคำแนะนำได้ แต่ห้ามส่งคำสั่งเข้า MT5 หรือข้าม Windows Risk Engine/ExecutionGateway.
6. สำหรับ direct-LAN และ external DNS ให้ทดสอบแยกกัน: (ก) allowed PC ไป `192.168.1.10` ได้เฉพาะ API ที่กำหนด, (ข) host อื่นถูก firewall ปฏิเสธ, (ค) public DNS/TLS ผ่าน Cloudflare, (ง) unauthenticated ถูกปฏิเสธโดย Access, (จ) authenticated identity ได้เฉพาะ scopes ที่อนุญาต, (ฉ) `/api/health` ผ่านแต่ order/broker/bridge endpoints ไม่มีใน origin, (ช) log ไม่มี token/body secrets, (ซ) WSS/fallback และ rollback ผ่าน.

หากผู้ใช้ต้องการใช้ hostname เดียวกันจาก LAN และ WAN ต้องกำหนด split-DNS หรือใช้ Cloudflare hostname จากทั้งสองเครือข่าย; การเรียก private IP โดยตรงต้องใช้ internal TLS/auth policy แยกและไม่ใช่การยืนยัน Cloudflare Access.

## Acceptance / Rollback Gate

- **PASS ที่มี:** DNS ไป Cloudflare edge; TLS validation; tunnel connector active; ยืนยันเหตุ 502 ว่า origin ปฏิเสธ connection.
- **BLOCKED:** Dedicated Office API/origin, internal app ingress, Access policy, Keycloak/Vault identity, workspace binding, Windows client, full end-to-end tests.
- **NOT TESTED:** Access allow/deny, firewall restrictions, API route/scope allowlist, authenticated Windows request, WebSocket, proxy body-log redaction, secret rotation, backup/restore และ rollback drill.
- ก่อนแก้ route: บันทึก/export current remote-managed route metadata และเวลาตรวจ, เตรียมย้อน route เดิม, ตรวจ local health, ทำ negative auth/security tests แล้วค่อยเปลี่ยน route. หาก health หรือ Access check ไม่ผ่าน ให้ restore route เดิมและหยุด.
- ห้ามเปิด trading API, Live/Auto, broker account, order route หรือ command bridge ผ่าน DNS นี้.

อ้างอิง Cloudflare: [Tunnel troubleshooting — 502 / origin unreachable](https://developers.cloudflare.com/cloudflare-one/troubleshooting/tunnel/), [Access application types — self-hosted applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/choose-application-type/).

## Recheck from Windows PC — 2026-11-24

- SSH ไป `danai@192.168.1.10:22` สำเร็จ; `cloudflared.service` ยัง active/running.
- DNS ยังชี้ไป Cloudflare edge และ HTTPS ที่ `https://agent.youridea168.com/` ยังตอบ **502**.
- Listener ที่ตรวจพบยัง bind เฉพาะ `127.0.0.1`: ports 8000, 18081 และ 18082; ไม่มี listener ที่ port 8080 ซึ่งเป็น Tunnel origin ปัจจุบัน.
- GET health บน loopback ของ 18081/18082 ตอบสำเร็จ แต่ health response ของ Trading Pro มี operational metadata มากกว่าคำตอบ liveness ขั้นต่ำ รวมถึง broker/account identifier และรายละเอียดบริการ จึง **ห้ามเผย health route นี้ผ่าน public hostname**; Office API ควรมี minimal health endpoint แยกที่ไม่แสดง runtime/account details.
- การตรวจนี้เป็น read-only; ไม่อ่าน secret/config token, ไม่แก้ Tunnel, firewall, service หรือ broker state. ไม่ทดสอบ Access allow/deny หรือ authenticated Windows application flow.

### Repeat verification — 2026-11-24 17:38 ICT

- Windows PC ยัง SSH ถึง `192.168.1.10:22` ได้; บน VM100 `cloudflared.service` เป็น `active`.
- HTTPS `HEAD /` ที่ `agent.youridea168.com` ยังคงตอบ `502 Bad Gateway` จาก Cloudflare.
- `ss -ltn` แสดง app listeners `127.0.0.1:8000`, `127.0.0.1:18081`, `127.0.0.1:18082`; ไม่มี listener `:8080` ตาม origin ที่บันทึกไว้. SSH reachable จึงไม่เท่ากับ app/API reachable จาก LAN.
- ยังคงไม่เปลี่ยน origin, DNS, Access, firewall หรือบริการ; ไม่อ่าน token/config secret และไม่เรียก API ที่มี account metadata.

### Repeat verification — 2026-11-24 21:46 ICT

- From the Windows PC, `HEAD https://agent.youridea168.com/` returned **502 Bad Gateway** from Cloudflare; TLS certificate verification succeeded (`ssl_verify_result=0`).
- `cloudflared.service` reports `active`. VM100 still has no listener on origin port 8080; `ss -ltn` shows the Trading Pro services on loopback only, including V4 staging `127.0.0.1:18082`.
- The staging API is reachable from the PC only through the temporary loopback SSH forward `127.0.0.1:18182 -> VM100 127.0.0.1:18082`, and reports simulation mode. It is not a reviewed Office API and must not be made the public origin.
- No public route, tunnel origin, Access policy, firewall, service, secret or broker state was changed. Do not repoint the hostname until a dedicated authenticated Office API origin and its security/rollback checks are ready.

### Read-only recheck — 2026-11-25

- SSH to `danai@192.168.1.10` succeeded; `cloudflared.service` is active. VM100 still listens on `127.0.0.1:8000`, `127.0.0.1:18081` and `127.0.0.1:18082`; there is no listener on `:8080`.
- Status-only GET probes to `/api/system/health` returned HTTP 200 on 8000, 18081 and 18082; the response bodies were discarded. Port 8080 returned connection refused. These are Trading Pro endpoints, not a dedicated Office API.
- `https://agent.youridea168.com/` returned HTTP 502 from Cloudflare with TLS verification successful (`ssl_verify_result=0`).
- The isolated V4 staging health response on loopback `18082`, filtered to its rate-limit section, reports `requested=memory`, `shared=false` and warns that the request budget multiplies across workers. The active worker count was not checked; multi-worker rate-limit acceptance remains NOT TESTED.
- No `.env`, token or credential was read or printed. No DNS, route, tunnel, Access policy, firewall, service, broker/account state or trading command was changed. Access allow/deny, Office API authentication and LAN application reachability remain NOT TESTED.
