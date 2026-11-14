# P1.1 — ตรวจ cumulative changes และขอบเขต baseline

## ขอบเขตและผล

- Snapshot inventory: `2026-11-09T05:07:24Z` ตามเวลาเครื่อง; ไม่ใช้เป็นวันที่เสร็จของงานย้อนหลัง
- Branch: `integration/safety-main-2026-11-08`
- HEAD: `46438d71e16dfaa5dc58e88d997ca0ed43be2aff`; ไม่มี staged changes ณ inventory
- ตรวจ tracked changes 24 ไฟล์และ untracked 13 ไฟล์ ณ เริ่มตรวจ รวม generated receipts/HTML
- งานนี้เป็น inventory/source-diff review และ local regression ไม่ใช่ full security audit หรือ release sign-off
- ไม่แก้ production behavior, ไม่ reset/stash/delete งานเดิม, ไม่ commit/push/deploy หรือเปิด execution
- หลักฐาน snapshot/hash/diff รายไฟล์: `C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety\p11-inventory.json` และ `p11-review-00.txt` ถึง `p11-review-23.txt`
- Inventory ไม่รวม ignored runtime files, `.env`, dependencies หรือ raw account logs; ไม่ได้อ่าน secrets

## Coverage ของไฟล์ ณ snapshot

| กลุ่ม | ไฟล์ที่ตรวจ (relative จาก `C:\workspace\Ai-Trading-Pro`) | ผูกงาน |
| --- | --- | --- |
| Hygiene | `.gitignore` | ignore EA compiled binary; P1.4 |
| UI | `apps/web-dashboard/src/components/SignalCard.vue`, `apps/web-dashboard/src/lib/api.js`, `apps/web-dashboard/src/views/Brokers.vue` | structured errors/reconciliation warning/permissions/threshold; P6.3 |
| EA | `bridge/No7BridgeEA.mq5` | persistent claim/outcome journal, exclusive file, read/write guards, profit currency; P4.3 |
| Handoff | `docs/SAFETY-HANDOFF.th.md` | cumulative evidence และข้อจำกัด; P1.4/P8.3 |
| Adapters | `integrations/brokers/bridge.py`, `fx.py`, `mt5_live.py`, `paper.py` | spec completeness/currency/finite rates/history identity; P2.4/P3/P6 |
| Persistence/schemas | `packages/persistence/db.py`, `packages/shared_schemas/models.py`, `settings.py` | ledger/workspace/spec checks/namespaces; P2/P3 |
| API/runtime | `services/api_gateway/auth.py`, `state.py` | workspace token, signal broker check, unresolved block, fill verification response; P2/P4/P6 |
| Execution | `services/execution_gateway/gateway.py` | atomic admission, full-position fill checks, scoped snapshots, analytical history refresh; P3/P4 |
| Notifications | `services/notification/notifier.py` | pacing reservation fix; P6.4 |
| Risk/planner | `services/risk_engine/engine.py`, `planner.py` | account currency consistency และ early sizing refusal; P6 |
| Tracked tests | `tests/test_bridge.py`, `test_execution_recovery.py`, `test_exposure_failure.py`, `test_notify_outbox.py`, `test_signal_execution.py` | ตรวจ assertions/fixtures พร้อม changes ที่เกี่ยวข้อง |
| New application code | `services/execution_gateway/history.py` | immutable ingest, FIFO/reversal/costs, explicit no auto-resolution; P3 |
| New tests | `tests/test_atomic_execution_claim.py`, `test_deal_ledger.py`, `test_ea_durable_guard.py`, `test_mt5_history.py`, `test_spec_safety.py`, `test_workspace_isolation.py` | มี scope จำกัด: mocked brokers/source-contract ไม่แทน runtime จริง |
| Tracking (6 files) | `.clinerules/02-project-progress.md`; candidate, HTML, delivery/finalize/finalize-summary receipts ใน `.archify/explainer-project-progress-20261109-114911/` | P1.5; ตรวจ receipt อัตโนมัติ ไม่ได้ visual review |

## Findings ที่ต้องทำต่อ (ยังไม่แก้ใน P1.1)

### R01 — DB workspace rejection เกิดหลัง schema/PRAGMA operations

- หลักฐาน: `C:\workspace\Ai-Trading-Pro\packages\persistence\db.py:146–162`
- `executescript(SCHEMA)` และ WAL configuration เกิดก่อนตรวจ stored workspace จึงไม่ควรอ้างว่า wrong-workspace open ไม่มี side effects
- ยังไม่มี regression ยืนยัน DB bytes/schema ไม่เปลี่ยนเมื่อ identity mismatch; legacy DB ไม่มี identity ยังผูก workspace ของ opener แรก
- งานใหม่ **P2.5**: กำหนด legacy adoption policy และเพิ่ม regressions ก่อนแก้ลำดับ initialization

### R02 — snapshot แบบไม่ส่ง broker scope และ positions ว่าง

- หลักฐาน: `C:\workspace\Ai-Trading-Pro\services\execution_gateway\gateway.py`, `open_position_snapshot()`
- `scope` ว่างทำให้เงื่อนไข `not scope` เลือกทุก stored position; runtime caller ปัจจุบันส่ง broker_id แล้ว แต่ public method default ยังเปิดช่อง misuse
- งานใหม่ **P4.7**: regression สำหรับ empty/unscoped snapshots และ atomic snapshot updates; ไม่ใช้จุดนี้ล้าง claims

### R03 — UI threshold และ reconciliation message ไม่ตรงทุกสถานการณ์

- หลักฐาน: `C:\workspace\Ai-Trading-Pro\apps\web-dashboard\src\components\SignalCard.vue`
- `canApprove` hardcode 70 ขณะที่ server ใช้ configured threshold; warning `reconciliation_required` ทุกชนิดกล่าวว่า broker รายงาน fill แม้เป็น unresolved precheck ที่ยังไม่ส่งคำสั่งใหม่
- งานใหม่ **P6.6**: tests และ shared threshold/error-state contract; backend ยังเป็น authority ไม่ลด guard เพื่อให้ UI กดได้

### R04 — ข้อความเอกสารเก่าและ scope ของ tests

- ส่วนเก่าของ handoff ยังกล่าวว่าไม่มี deal ledger; README บางส่วนยังกล่าวว่า EA ไม่เคย compile; อยู่ใน **P1.4** ต้องแยก historical/current ไม่ลบประวัติ
- `test_immutable_scoped_deals_survive_restart` ใช้ Database object เดิม ไม่ได้ close/reopen จริง; **P3.6** เพิ่ม reopen และ concurrent-ingest regressions ก่อนขยายคำรับรอง
- `DealLedger.ingest()` ใช้ transaction ของ connection แต่ไม่มี explicit writer lock ก่อน read-existing; concurrent conflict case ต้องทดสอบ ไม่อ้างว่า broken หรือผ่านจาก source review เพียงอย่างเดียว
- EA source-contract tests ตรวจข้อความและลำดับ source ไม่ได้ execute MQL; ยังอยู่ **P4.3** runtime acceptance

### R05 — Baseline verification environment

- shell integration มี PSReadLine error และรายงาน completion ไม่ได้ จึงใช้ subprocess artifacts/explicit exit ไม่ใช้ tool wrapper success เป็นเกณฑ์
- Node PATH ทำให้ atomic full รอบก่อนเพิ่ม skip 1 case; **P1.3** ต้องทำ verification runner ให้สม่ำเสมอ
- local artifacts อยู่ใน ignored storage; **P1.4** ต้องกำหนดหลักฐานที่จะรักษาใน release ไม่ถือว่าอยู่ใน Git แล้ว

## Verification รอบ P1.1

- runner: `C:\workspace\Ai-Trading-Pro\storage\local-dev\qa\safety\inspect_p11.py` (local helper, ไม่ใช่ application feature)
- pytest ที่เกี่ยวข้อง 11 test files: **216 passed / 1 warning**, exit 0; JUnit `p11-tests.xml`
- Ruff `--select F,E9 services tests integrations packages`: exit 0
- `git diff --check`: exit 0
- warning เดิม: Starlette/httpx TestClient deprecation; ไม่มีการ upgrade dependency
- ไม่รัน full suite/build/compiler/browser ใหม่ในงานนี้; full 704 passed/40 skipped เป็น historical atomic evidence เท่านั้น
- ไม่ได้ทดสอบ Redis/VM/MT5/crash/power loss หรือกำไรจากกลยุทธ์

## การปิดงานและลำดับต่อ

P1.1 เสร็จเฉพาะ inventory/source-diff review ของ snapshot ข้างต้น โดย findings ยังคงเปิด งานเปลี่ยนหลัง snapshot ต้องตรวจใหม่ก่อน release

ถัดไป: **P1.3** runner/tool paths → **P1.4** docs/baseline → **P2.2/P2.5** ownership/DB initialization → **P3.3/P3.6** authoritative evidence/tests ส่วน P4.7/P6.6 เตรียม regressions ได้โดยไม่เปิด execution