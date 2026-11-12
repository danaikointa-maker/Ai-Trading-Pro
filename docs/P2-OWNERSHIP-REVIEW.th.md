# P2 — ownership และขอบเขตหลักฐาน local

## Continuation H082–H084 (8 พฤศจิกายน 2026)
- Final terminal H082–H084 full 1256 passed/39 skipped/1 warning; JUnit 1295 failures/errors 0 ทุก job exit 0
- H085 P2.4 decoded model schema/path array guards RED 12 failed; focused/full ใหม่รอยืนยัน
- H085 accepted focused 84 passed, Ruff F,E9/diff exit 0; fresh p24-model-shape-detached-full รอ terminal ไม่ยืม full H082
- H085 full terminal 1269 passed/39 skipped/1 warning; JUnit 1308 failures/errors 0 ทุก job exit 0
- H086 RED corrected 4 failed; shared cached_forecast สำหรับ API/live/watchdog/management หลัง H085 terminal; focused/full ใหม่รอยืนยัน
- H086 accepted focused 239 passed/1 existing warning exit 0; fresh p24-model-readers-detached-full รอ terminal
- H086 full terminal 1275 passed/39 skipped/1 warning; JUnit 1314 failures/errors 0 ทุก job exit 0
- H087 Vue/store merge guards และ H088 persisted authority revalidation เริ่มหลัง terminal; RED UI 4, authority 9, cache 3; final focused/full รอยืนยัน
- H087–H088 final focused 121 passed, Ruff F,E9/diff exit 0; fresh p24-model-authority-detached-full รอ terminal
- H087–H088 full terminal 1289 passed/39 skipped/1 warning; JUnit 1328 failures/errors 0 ทุก job exit 0
- H089 replica RED 2 และ H090 generation RED 1; implementation หลัง terminal ยังรอ focused/full ใหม่; ไม่มี broker fencing claim
- H089–H090 focused accepted 162 passed/1 warning; JUnit 162/0/0/0, Ruff/diff exit 0. Full p25 blocked ก่อน tests ที่ Vite build; ต้อง rerun build/full แยกเมื่อ environment พร้อม
- Full follow-up p25 ยังไม่รับรอง: build isolated ไม่มี terminal marker; Python full มี duplicate pytest parent/child sharing JUnit path และถูกยุติเป็น inconclusive. ต้องแก้ runner isolation ก่อนใช้ full evidence
- Revalidation hash ทุก consumer อาจมีต้นทุน I/O; ยังไม่แก้ DB+hash authority, signatures, joblib sandbox, model memory mutation, check/use races, replica model disclosure และ operator release
- H082 P2.4: ปิด revoked path-table และ stale table หลัง install arrays ว่าง
- H083 P2.3/P2.4: training ทั้ง predictor และ runtime worker ผ่าน registry reload แทน direct result installation
- H084 P2.4: approval boolean strict; cache clear ก่อน reload ใต้ runtime lock; forecast_for ตรวจ version/approval
- RED evidence h082-red (5 failed), red2 (8 failed), red3 (2 failed); focused/full ล่าสุดรอยืนยัน
- ขอบเขตยังไม่ครอบคลุม dictionary consumers/replica/UI stale merge, concurrent decision writes, loaded artifact revalidation และ direct install_payload API; ไม่ใช่ full security audit

## Resume summary — H076–H081

Final terminal addendum H081: full 1240 passed/39 skipped/1 warning; independent JUnit 1279
failures/errors 0 skipped 39 ทุก job exit 0; tests.err ว่าง; finished_at 2026-11-10T09:22:57Z
เสร็จ local H076–H081 เท่านั้น; snapshots รอ terminal ด้านล่างเป็น historical evidence ไม่ใช่ current status

H076 full 1223 passed/39 skipped; H077–H078 full 1234 passed/39 skipped;
H079 full 1236 passed/39 skipped; H080 full 1239 passed/39 skipped
ทุกชุดมี failures/errors 0 และ jobs exit 0; H081 focused 71 passed ยังรอ fresh full terminal
อ่าน addendum ใหม่แทน snapshot RUNNING/RED เก่า; ไม่ลบหลักฐานรอบก่อนและไม่ใช้ local tests ปิด P2
Misuse-resistance review จำกัด local source: latch ไม่ decode truthiness, ไม่ auto-release,
unknown version ไม่อ้าง success, malformed latch fail closed, ไม่เผย paths ใน generic quarantine reason
ยังเปิด bool coercion ใน approval payload, arbitrary registered joblib code, mutable DB/hash authority,
model metadata shape, cache/path-table/direct install/concurrent updates และ operator release workflow
รายการนี้เป็น source findings/limitations ไม่ใช่ full security audit หรือ real execution acceptance

## H081 — revoked horizon inference

RED 1 failed ยืนยัน predictor.approved=false ยังเรียก approved horizon และรายงาน lightgbm method
หลัง H080 full terminal 1239 passed/39 skipped/JUnit 1278 failures/errors 0 ทุก job exit 0
เพิ่ม self.approved guard ก่อน horizon inference; focused 71 passed, Ruff F,E9/diff exit 0
fresh p24-model-inference-detached-full เริ่มหลัง final source/tests ต้อง actual terminal/JUnit
ไม่ใช่ cache/path-table/concurrent update acceptance; P2 และ real-environment gates ยังเปิด

## H080 — persisted approval revocation

RED-v2 2 failed/1 passed ยืนยัน revoked DB ไม่ส่งผลต่อ reload และ route revoke ไม่ reload predictor
หลัง H079 full terminal 1236 passed/39 skipped/JUnit 1275 failures/errors 0 ทุก job exit 0
แก้ load approval เป็น payload AND DB และ route reload ทั้ง approve/revoke; artifact bytes ไม่แก้
focused 70 passed exit 0; Ruff F,E9 ผ่าน; fresh p24-model-revoke-detached-full เริ่มต้อง actual terminal
ยังไม่อ้าง per-horizon inference/cache invalidation/concurrent update fencing; P2 ยังไม่ปิด

## H076–H078 — model approval refusal และ durable quarantine

H079 addendum: decoder failure RED 2 failed → focused 67 passed, Ruff F,E9/diff exit 0
หลัง H078 full terminal 1234 passed/39 skipped (JUnit 1273 failures/errors 0) จึงแก้ joblib/NumPy
decode exception เป็น durable latch/generic refusal; ไม่รับรอง executable joblib sandbox
fresh p24-model-decode-detached-full เริ่มหลัง source ล่าสุด ต้องตรวจ terminal ไม่ยืม H078 full

วันอ้างอิง environment 8 พฤศจิกายน 2026; artifact clock 10 พฤศจิกายน แยกจากวันส่งมอบ
H075 full terminal 1219 passed/39 skipped; independent JUnit 1258 failures/errors 0 ทุก job exit 0
H076 registry list/approve ตรวจ registered bytes ไม่ deserialize; RED 3 failed → focused 54 passed
H076 fresh full 1223 passed/39 skipped/1 warning; independent JUnit 1262 failures/errors 0 ทุก job exit 0
finished_at 2026-11-10T08:47:42Z; ไม่ใช่รับรอง source H077–H078 ที่แก้ภายหลัง
H077 API refusal RED 2 failed/2 passed → คืน generic 409 และไม่โหลด predictor เมื่อ registry ปฏิเสธ
H078 durable latch RED 5 failed → focused ล่าสุด 65 passed รวม restart/restored bytes/malformed latch/revoke/DB failure
เก็บ generic record ใน workspace kv ด้วย INSERT OR IGNORE; ไม่ overwrite detection evidence/approval/provenance หรือย้ายไฟล์
list เปิดเผย artifact_status/reason โดยไม่ raw paths; persistence failure ไม่ deserialize และไม่อ้าง success
ยังไม่มี operator release API/CLI ที่รับรอง; retrain ด้วย version ใหม่ ไม่ลบ latch/แก้ hash เพื่อ bypass
ขอบเขตยังไม่ครอบคลุม signature, resource budgets, reparse/TOCTOU, concurrency/session fencing หรือ real acceptance
ถัดไป fresh full terminal → remaining P2; ไม่ปิดเฟส/ไม่เริ่ม P3 ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H075 — backtest tick refusal RED

Implementation addendum: RED-v3 2 failed (TickStoreError/OSError) → focused 180 passed/1 existing warning exit 0
หลัง H074 terminal worker ปฏิเสธ requested ticks ที่ load exception ด้วย generic error ไม่ run/persist report/raw path
fresh p23-tick-backtest-detached-full เริ่มแล้ว; missing ticks คืน None ยัง conservative contract เดิม ไม่รับรอง coverage ทุก window
H074 full 1217 passed/39 skipped/1 warning; JUnit 1256 cases failures/errors 0 skipped 39 ทุก job exit 0
finished_at 2026-11-10T05:01:15Z ตาม artifact clock ไม่รับรอง source H075 หลัง full

วันอ้างอิง 8 พฤศจิกายน 2026; test แรกผ่านผิดเหตุผลจาก mock snapshot ขาด as_dict
แก้ fixture แล้ว h075-red-v2.xml 1 failed/errors 0 ยืนยัน worker จบ done หลัง tick load refusal
production ยังไม่แก้ขณะ H074 full; ถัดไป H074 terminal → generic fail requested tick run → focused/fresh full
ไม่ใช้ผล test แรกอ้าง regression success; P2/real acceptance ยังไม่ปิด

## H074 — status refusal RED, implementation pending

Implementation addendum: หลัง H073 terminal แก้ per-symbol quarantine ไม่ raw error/path; valid symbols แยกจาก damaged
inventory รักษา underscores และ linked root guard ก่อน enumerate; focused 172 passed/1 existing warning exit 0
fresh p23-tick-status-detached-full เริ่มแล้ว; status ไม่ใช่ durable quarantine record/day content verification
H073 full 1213 passed/39 skipped/1 warning; JUnit 1252 cases failures/errors 0 skipped 39 ทุก job exit 0
artifact finished_at 2026-11-10T04:52:34Z ไม่รับรอง source H074 หลัง full

วันอ้างอิง 8 พฤศจิกายน 2026; standalone h074-red.xml 4 failed/errors 0/skips 0
status damaged manifest ล้มทั้ง request/valid symbols ถูกกลบ; underscore inventory ผิดและตาม linked tick root
ยังไม่แก้ source ขณะ H073 full ทำงาน; batch status-red RUNNING ไม่มี terminal ไม่ใช่ acceptance
ถัดไป H073 terminal → status quarantine/linked inventory patch → focused/fresh full → backtest disclosure
P2 ยังไม่ปิด ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H073 — prune preflight/index consistency

วันอ้างอิง 8 พฤศจิกายน 2026; H072 full log 1209 passed/39 skipped/1 warning tests exit 0 ยังต้อง independent JUnit/job check
H072 verification addendum: JUnit 1248 cases failures/errors 0 skipped 39 ทุก job exit 0; finished_at 2026-11-10T04:44:58Z ตาม artifact clock
H073 RED 4 failed/164 passed → focused 168 passed/1 existing warning exit 0
prune valid manifest ก่อน unlink/preflight selected paths ทั้งหมด; update remaining entries/totals หลังสำเร็จ
ไม่ repair/adopt damaged index; ไม่ใช่ multi-file crash-atomic/deletion rollback/full-data preflight/TOCTOU guarantee
fresh p23-tick-prune-detached-full เริ่มแล้วต้อง actual JUnit/log/exits
status/backtest disclosure/model approval/durable quarantine และ remaining P2 acceptance ยังเปิด
ไม่ปิด P2/ไม่เริ่ม P3 ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H072 — tick index aggregate/cache consistency

วันอ้างอิง 8 พฤศจิกายน 2026; H071 full actual log 1201 passed/39 skipped/1 warning tests/diff exit 0
H071 JUnit 1240 cases failures/errors 0 skipped 39 ทุก job exit 0; finished_at 2026-11-10T04:36:35Z ตาม artifact clock
H072 RED 8 failed/156 passed → focused 164 passed/1 existing warning exit 0, Ruff F,E9 ผ่าน
aggregate rows/day-count/bounds/type ต้องตรง entries; daily missing-index summary ปฏิเสธ
cache hit ตรวจ index เดิมก่อนใช้ ไม่ใช่ byte revalidation ทุก hit/inode/root pinning/TOCTOU guarantee
fresh p23-tick-index-detached-full เริ่มแล้ว ต้อง actual JUnit/log/exits ก่อนรับรอง
status/backtest refusal disclosure/model approval/durable quarantine และ real acceptance ยังเปิด
ไม่ปิด P2/ไม่เริ่ม P3 ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H071 — tick CLI workspace boundary

วันอ้างอิง 8 พฤศจิกายน 2026; H070 full 1197 passed/39 skipped/1 warning, JUnit 1236 cases failures/errors 0 ทุก job exit 0
artifact finished_at 2026-11-10T04:28:18Z ไม่รับรอง source H071 หลัง full
CLI RED 2 failed/154 passed → focused 156 passed/1 existing warning
ใช้ workspace_dataset_dir เดียวกับ candle CLI; foreign root ปฏิเสธก่อน import และ handle TickStoreError exit 1
configured default/owned child ยังใช้ได้; fresh p23-tick-cli-detached-full เริ่มแล้วต้องตรวจ terminal
ถัดไป cache/status aggregate/missing-index regressions → remaining P2; ไม่ปิด P2/เริ่ม P3
ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H070 — legacy tick registration

วันอ้างอิง 8 พฤศจิกายน 2026; H069 full terminal 1182 passed/39 skipped/1 warning, tests/diff exit 0
H070 RED 15 failed/137 passed → shared legacy verified reader สำหรับ load/summary/import
schema/root/symbol/path/stored bytes checks ก่อน parse; load ตรวจ canonical digest/rows/bounds
missing/foreign/corrupt ไม่ repair/adopt; sidecar ไม่ใช่ signature/DB-backed identity
focused แรก collection syntax error แก้แล้ว; v2 1 failed/151 passed จาก historical auto-adopt expectation
ปรับ test เป็น refusal/preserve bytes; v3 รอ terminal ต้อง fresh full หลัง source ล่าสุด
H070 terminal addendum: v3 152 passed/1 existing warning exit 0; Ruff F,E9 ผ่าน
fresh p23-tick-legacy-detached-full เริ่มหลัง source ล่าสุด ต้องตรวจ actual JUnit/log/exits
H069 final verification: JUnit 1221 cases failures/errors 0 skipped 39 ทุก job exit 0
finished_at 2026-11-10T04:17:18Z ตาม artifact clock แยกวันอ้างอิง; H070 full runner/pytest มีจริงยังรอ terminal
cache/missing-index summary/TOCTOU/budget/crash/concurrency/model disclosure/durable quarantine และ real acceptance ยังเปิด
ไม่ปิด P2/ไม่เริ่ม P3 ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H068–H069 — tick daily index identity และ verified-byte parsing

วันอ้างอิง 8 พฤศจิกายน 2026; H068 RED 26 failed → focused 132 passed/1 existing warning
read_manifest ตรวจ schema/root/symbol/layout/day-entry shape/duplicates; consumer/writer ใช้ร่วมกัน
malformed/copied manifest ถูกปฏิเสธ ไม่ silent fallback/repair; extras ห้ามเปลี่ยน identity
H069 content RED 4 failed/132 passed → 136 passed; stored-byte RED 1 failed/136 passed
→ accepted bytes-focused 137 passed/1 existing warning exit 0
read_day ต้องมี registration ตรวจ stored SHA-256/size ก่อน parse bytes เดียวกัน แล้ว canonical digest/rows/bounds
ไม่อ้าง signature/DB-backed ownership หรือ broker authenticity; ผู้แก้ data+index ยังปลอม local evidence ได้
H066 full ยังไม่มี terminal; fresh p23-tick-manifest-accepted-full เริ่มหลัง source ล่าสุด ต้องตรวจ actual JUnit/exits
H069 correction: process inspection พบสองรอบเก่าไม่มี runner/pytest แม้ marker RUNNING;
interrupted/unconfirmed ไม่ใช่ผ่านหรือยังรัน เปิด finite detached p23-tick-manifest-detached-full
ตรวจพบ runner/pytest จริงแล้ว ยังต้อง terminal/JUnit ไม่แก้ source ขณะ full
legacy trust/cache/missing-index summary, root reparse/TOCTOU, budget, overwrite/crash/concurrency,
model disclosure/durable operator quarantine และ real acceptance ยังเปิด
คำขอ loop หมายถึงเดิน local tasks ต่อในเซสชัน ไม่เปิด background watcher/execution หรือข้าม P2 gate
ถัดไป full terminal → legacy/content/cache/provenance regressions; ไม่ปิด P2/ไป P3
ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H067 — tick inventory calendar/path validation

วันอ้างอิง 8 พฤศจิกายน 2026; RED 9 failed ก่อนแก้ suffix .csv.gz ให้เป็น calendar day
inventory deduplicate formats และใช้ day_path validation ปฏิเสธ malformed names/link/dangling/directory
ไม่อ่าน content ไม่อ้าง digest verification/manifest trust/root binding/signature
H066 full ยัง RUNNING ไม่มี terminal evidence; source เปลี่ยน H067 แล้วห้ามใช้รอบเก่ารับรอง source ใหม่
focused H067 รอ terminal; ถัดไป full/process reconciliation → manifest/root-binding regressions
H067 terminal addendum: focused 106 passed/1 existing Starlette warning exit 0;
Ruff F,E9/diff exit 0; fresh full H067 ยังไม่รัน H066 terminal ยังไม่ยืนยัน
reparse/TOCTOU, crash/concurrency, trusted provenance/durable quarantine/real acceptance ยังเปิด
ไม่มี activation/connect/adopt/deploy/restart/commit/push; ไม่ปิด P2/ไป P3

## H066 — tick staging และ legacy path safety

วันอ้างอิง 8 พฤศจิกายน 2026; P2.3/P2.4 RED 12 failed ก่อน source patch
staging เปิด xb ปฏิเสธ existing/link/dangling; legacy data/metadata ใช้ path guards ร่วมกัน
import preflight ทั้งสอง destination ก่อนอ่าน export/write data; ไม่มี automatic staging adoption/cleanup
ยัง replace daily data ได้ตาม re-import contract เดิม ไม่ใช่ full provenance หรือ crash/concurrency acceptance
focused/full ต้องตรวจ terminal ใหม่; ถัดไป inventory/manifest trust/root binding regressions
H066 focused terminal 122 passed/1 existing Starlette warning exit 0; Ruff F,E9/diff exit 0
fresh p23-tick-writer-accepted-full launched หลัง source patch; terminal ยังไม่ยืนยัน
reparse/TOCTOU, durable quarantine, trusted identity และ real acceptance ยังเปิด ไม่ปิด P2/ไป P3
ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H065 — bounded daily tick path guards

วันอ้างอิง 8 พฤศจิกายน 2026; P2.3/P2.4 regression RED 44 failed/1 passed ก่อนแก้
tick_store.py เพิ่ม symbol/calendar day/format validation และ symlink path guard
ครอบคลุม daily helpers/manifest selection เท่านั้น ไม่อ้างครบ tick pipeline หรือ trusted provenance
legacy paths, temp writer, inventory/manifest integrity, foreign-root binding และ reparse/TOCTOU ยังเปิด
focused ครั้งแรก exit 4 (ชื่อ test_ticks.py ไม่มี); helper แก้เป็น test_tick_data.py
accepted-focused-v2 เริ่มรอ terminal; ต้อง fresh full หลัง source เปลี่ยน ไม่ใช้ H064 แทน
H065 terminal addendum: accepted-focused-v2 110 passed/1 existing Starlette warning exit 0;
Ruff F,E9/diff exit 0; H065 fresh full ยังไม่รัน
ถัดไป focused terminal → writer/temp/legacy/provenance regressions → full; ไม่ปิด P2/ไป P3
ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H064 — snapshot artifact full terminal ยืนยัน H063 local slice

วันอ้างอิง 8 พฤศจิกายน 2026; artifact finished 2026-11-09T17:33:47Z ตาม artifact clock
p23-snapshot-artifact-accepted-full: 1085 passed/39 skipped/1 existing warning;
actual JUnit 1124 cases failures/errors 0 skipped 39 ทุก job exit 0 tests.err ว่าง
ตรวจ summary/log/JUnit/exits ใหม่ด้วย check_p23_snapshot_artifact.py; RUNNING ใน H063 เป็น historical snapshot
ไม่มี source change เพิ่ม รักษางาน uncommitted; ไม่ใช้ผลนี้อ้าง tick guards หรือ real environment acceptance
ถัดไป tick path/provenance regressions → P2.4 ส่วนที่เหลือ; TOCTOU/reparse, trusted provenance,
decompression budget, crash/concurrency/durable quarantine ยังเปิด ไม่ปิด P2/ไป P3
ไม่มี activation/connect/adopt/deploy/restart/commit/push

## H062–H063 — snapshot artifacts ไม่เชื่อ manifest-selected path

วันอ้างอิง 8 พฤศจิกายน 2026; artifact clock 9 พฤศจิกายน เก็บ historical timestamps ตามหลักฐาน
H062 dataset full terminal 1057 passed/39 skipped/1 warning; JUnit 1096 cases failures/errors 0 ทุก job exit 0;
finished 2026-11-09T17:18:13Z, tests.err ว่าง ตรวจ JUnit/log/exits ตรงกัน
H063 P2.3/P2.4 derive snapshot path จาก root+ID ตรวจ manifest schema/root/path/id/full hash;
ปฏิเสธ symlink root/manifest/data ก่อน IO, hash decompressed bytes แล้ว parse bytes เดียวกันและตรวจ metadata
Save verify existing data ก่อน reuse; instrument/timeframe/source conflict หรือ legacy/incomplete/corrupted ปฏิเสธ
ไม่ overwrite/repair/adopt/ย้าย/ลบ evidence; listing ข้าม invalid manifests ไม่อ้าง full content verified
RED 24 failed/109 passed → 133 passed; decoder RED 1 failed/134 passed → accepted-focused 135 passed/1 existing warning
Ruff F,E9/diff exit 0; fresh p23-snapshot-artifact-accepted-full เริ่มแล้วต้องตรวจ terminal
p23-snapshot-accepted-full เป็นคนละงานเก่า (position snapshot) ห้ามใช้แทน
Remaining: ticks, root reparse/TOCTOU, DB-backed provenance/signature, decompression budget,
crash/concurrency/durable quarantine workflow และ model list/approve disclosure; real acceptance ยังเปิด
ถัดไป fresh full terminal → tick loaders/writers tests → P2.4 ที่เหลือ ไม่ปิด P2/ไป P3 ไม่มี activation/connect/adopt/deploy/restart/commit/push
H063 verification addendum: fresh full dependencies/lint/build ผ่าน tests ยัง RUNNING;
HTML validate/deliver/check ผ่าน hashes ตรง มี H063; 7 writing warnings, browser/visual ไม่รัน

## H059–H061 — candle dataset integrity และ workspace CLI

วันอ้างอิง 8 พฤศจิกายน 2026; artifact clock 9 พฤศจิกายน แยกจากวันส่งมอบ
H059 provenance full terminal 1032 passed/39 skipped/1 warning; JUnit 1071 cases failures/errors 0 ทุก job exit 0
H060 เพิ่ม schema/root/symbol/timeframe/full source+CSV SHA-256 ใน sidecar;
loader hash และ parse bytes เดียวกัน, malformed/missing/legacy/damaged sidecar ไม่ parse CSV;
identifier/path guards ก่อน IO, exclusive writes ไม่ overwrite/adopt หรือย้าย/ลบหลักฐานเดิม
H061 CLI import/evaluate default configured workspace datasets และห้าม foreign root;
re-import source ที่ตรวจแล้วไปโฟลเดอร์ว่างใน workspace ดู DATA.md ไม่ลบ evidence เพื่อข้าม guard
RED 21 failed/69 passed → 90 passed; CLI RED 4 failed/90 passed → accepted-focused 94 passed;
Ruff F,E9/diff exit 0; fresh p23-dataset-accepted-full เริ่มแล้วต้องตรวจ terminal ไม่ใช้ H059 รับรอง final source
ข้อจำกัด: sidecar ไม่ใช่ trusted DB identity/signature; ผู้แก้ CSV+sidecar ยังปลอม integrity evidence ได้
snapshot manifest path ยังเป็น trusted path input, snapshot/tick consumers และ save/root TOCTOU/reparse ยังต้องแก้;
model list/approve disclosure และ durable operator quarantine ยังเปิด ไม่ปิด P2/ไม่เริ่ม P3
ถัดไป full terminal → snapshot/tick path/provenance tests → P2.4 ที่เหลือ; ไม่มี activation/connect/adopt/deploy/restart/commit/push
Verification addendum: dataset full dependencies/lint/build ผ่าน tests ยัง RUNNING ณ ตรวจล่าสุด;
progress render gates/hashes ผ่าน 7 writing warnings, browser/visual ไม่รัน ไม่ใช่ external acceptance

## H056–H058 — model provenance และ quarantine local

วันอ้างอิง 8 พฤศจิกายน 2026; artifacts ใช้ clock 9 พฤศจิกายน ไม่แก้ historical entries ย้อนหลัง
H056 ยืนยัน H055 full terminal: 1014 passed/39 skipped/1 warning; JUnit 1053 cases failures/errors 0 ทุก job exit 0
EA source hash ตรง QA compiled copy, compile 0 errors/0 warnings; continuation-check เดิมเป็น snapshot ก่อน terminal
H057 เพิ่ม provenance ใน workspace DB ผูก version/root/path และ SHA-256 ของ joblib/NPZ/metadata;
model row+provenance register transaction เดียว; hash และ deserialize in-memory bytes ชุดเดียว, NPZ allow_pickle=false
H058 model quarantine ไม่โหลด legacy/foreign/tampered/missing/unregistered ไม่ adopt/ย้าย/ลบหรือแก้ evidence เดิม;
immutable versions ไม่เขียนทับ; predictor ล้าง prior approval/models ก่อน revalidation และกลับ baseline เมื่อโหลดไม่ได้
RED 9 failed/85 passed → 94 passed; edge RED 6 failed/95 passed → accepted-focused 101 passed/1 existing warning
Ruff F,E9/diff exit 0; fresh p23-provenance-accepted-full dependencies/lint/build ผ่าน tests รอ terminal
ยังเปิด dataset provenance/digests, remaining consumers/writers, root inode/reparse/save TOCTOU,
model list/approve disclosure และ durable quarantine/operator workflow; digest ไม่ใช่ signature ไม่กันผู้แก้ทั้ง DB+files
services/ai_forecast/predict.py และ services/forecasting/predictor.py ไม่มีจริง; dataset.load_dataset ยังไม่ตรวจ sidecar/digest
ถัดไป full terminal → dataset tests/provenance → P2.4 ส่วนที่เหลือ; ไม่ปิด P2/ไป P3
ไม่มี trading/connect/adopt/deploy/restart/commit/push; real Redis/MT5/VM/browser/crash acceptance ยังเปิด

## H050–H053 — ผลต่อเนื่องและขอบเขตที่ยังไม่ปิด

H055: Bridge close transport/EA error คืน generic unknown ไม่เผย raw receipt/exception ไม่ retry;
RED 1 failed/33 passed → accepted-focused 352 passed/1 existing warning; Ruff F,E9/diff exit 0
fresh p23-transport-accepted-full เริ่มหลัง final patch ยังต้องตรวจ terminal ไม่ใช้ p23-contract/hardening full แทน
งานถัดไป transport full terminal → provenance/digest/remaining file consumers → P2.4 quarantine;
P2 ยังไม่ครบ ไม่เริ่ม P3 ไม่มี activation/adoption/deploy/restart/commit/push

H054 addendum: Bridge malformed/status/price/retcode conflict → generic unknown;
MT5 normalized volume finite/positive/ไม่เกิน requested ก่อนส่ง; RED 12 failed/66 passed → focused 351 passed/1 warning
Ruff F,E9/diff exit 0; fresh p23-contract-accepted-full dependency/lint/build ผ่าน tests ยังรอ terminal
p23-paths full terminal JUnit 1027 cases failures/errors 0 skipped 39 ทุก job exit 0;
artifact finished 2026-11-09T16:24:36Z เริ่มก่อน final volume guards ไม่รับรอง final source
Remaining เพิ่ม Bridge transport raw-error sanitization; provenance/quarantine/remaining consumers/real acceptance ยังเปิด

- วันอ้างอิง 8 พ.ย. 2026: mapping full terminal 944 passed/39 skipped/1 warning;
  JUnit 983 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T15:37:21Z ตาม artifact clock
- MT5 close mapping ใช้ reported receipt ไม่ใช่ requested fill; None/unknown/nonterminal เป็น unknown,
  DONE_PARTIAL แยก partial; verified=false, post-send identity guard, reject/cancel ต้อง volume=0
- EA close ใช้ result.volume/result.price และ partial acknowledgement; compile QA copy ได้ 0 errors/0 warnings
  ไม่ติดตั้งหรือ activate EA ไม่เชื่อม terminal/broker; source-contract checks ไม่แทน runtime acceptance
- record_trade atomic transaction และ collision/evidence checks; failure rollback insert/delete พร้อมกัน;
  identical replay idempotent ไม่ลบ newer snapshot; transaction ไม่ใช่ account-side fencing หรือ power-loss proof
- Model version allowlist/containment/symlink guards ตรวจ joblib/npz/metadata ก่อนอ่านหรือเขียน;
  replay custom dataset root/file ต้องอยู่ใต้ settings.paths datasets ของ workspace ไม่ fallback legacy
- TDD evidence: MT5/EA RED 21 failed/244 passed → green 265; atomic RED 6 failed/273 passed → 279;
  reused-ticket RED 1 failed/7 passed → accepted 280; paths RED 14 failed/311 passed → fixture correction → 325;
  metadata valid RED 1 failed/14 passed → 326; volume RED 13 failed/53 passed
- latest accepted-focused 339 passed/1 existing warning; Ruff F,E9/diff exit 0;
  fresh p23-hardening-accepted-full รอ terminal ไม่ใช้ pre-final p23-paths full รับรอง final volume guards
- ยังเปิด Bridge malformed/contradictory receipts, normalized-volume validation, model provenance/digest/legacy
  quarantine, root mutability/TOCTOU/remaining file consumers และ real Redis/MT5/VM/browser/crash acceptance
- ถัดไป final full terminal → remaining close/path contracts → P2.4; ไม่ปิด P2/ไป P3 ไม่มี activation/adoption/deploy/commit/push

เริ่มตรวจรอบนี้วันที่ 8 พฤศจิกายน 2026 ตาม environment ที่ให้มา;
artifact clock รายงาน 9 พฤศจิกายน 2026 จึงเก็บ timestamp ตาม artifacts แยกจากวันอ้างอิง
ไม่เปิด trading, login terminal, deploy, restart, commit หรือ push

## Ownership ที่มีจริง ไม่ใช่สิ่งที่คาดหวัง

| Resource | Authority ปัจจุบัน | ผลตรวจและช่องว่าง |
| --- | --- | --- |
| DB/users/REST | workspace singleton + JWT workspace + current DB user/role | เพิ่ม runtime DB/settings equality guard ก่อน user lookup และ runtime dependency; ไม่ใช่ per-user account grants |
| WS live | JWT + DB active/role ตรวจซ้ำก่อน frame | เพิ่ม DB/settings equality guard; tests เดิมต้องระบุ workspace ของ fake DB ให้ชัด |
| Orders | workspace DB + persisted account-owner ต่อ broker alias + account_identity ใน claim | ตรวจ workspace/broker/login/server/currency; result update เก็บ metadata; replay ต้องตรง account; actor ไม่ใช่ owner; legacy claims ไม่ถูก adopt |
| Deals/history | workspace DB + persisted alias owner + explicit batch account evidence + broker_id/account_key/deal_id | ตรวจ owner ก่อน/หลังอ่าน; ตรวจ identity/key/currency แม้ batch ว่าง; ไม่เปลี่ยน claims และไม่ resend |
| Reports | workspace DB | สมาชิกที่มีสิทธิ์อ่าน workspace เห็น reports ร่วมกัน; ไม่รับรอง per-user isolation |
| Background jobs | process-global JOBS | เพิ่ม workspace_id ทุก running/done/error record; foreign/unknown workspace ตอบ 404 |
| Broker sessions | Bridge account token/session + expected Demo identity; direct MT5 configured login/server | direct MT5 เพิ่ม identity check ก่อน initialize, ก่อน account/positions/trade I/O และก่อนส่ง; ไม่ใช่ atomic broker-side fencing |
| Redis snapshots | workspace key prefix | ยังไม่ทดสอบ real Redis; ไม่เท่ากับ multi-host fencing |
| Runtime positions | pinned adapter + persisted account owner รอบ positions/spec reads | snapshot row validation ต้องผ่านก่อนแทน cache; ตรวจ owner/active adapter ก่อนแต่ละ action; cache ที่คงไว้เมื่อ failure เป็นหลักฐานเก่า ไม่ใช่ live account view |
| Files/models/datasets | Settings.paths ต่อท้าย workspaces/<workspace_id> | datasets/models/backtests/logs รวม local ถูก namespace; legacy files ไม่ย้าย/ไม่ fallback; replay/custom paths และ DB model references ยังต้องตรวจครบ จึง P2.3 ยังไม่เสร็จ |

## P2.5 — DB preflight และ legacy adoption

- DB ใหม่/ว่าง: สร้าง schema และ workspace identity ใน transaction เดียว
- DB มี identity: ต้องมี row singleton=1 เพียงหนึ่ง row, format ถูกต้อง และตรง workspace
  adoption flag ไม่สามารถข้าม identity ที่ผิดหรือ malformed ได้
- DB มี tables แต่ไม่มี identity: default ปฏิเสธก่อน schema หรือ journal-mode mutation
- `Database(path, workspace_id=..., adopt_legacy=True)` เป็น API สำหรับ operator/tooling ที่ได้รับอนุมัติแยก
  ต้องเป็น boolean จริง; string `"false"` ไม่ถูกตีความเป็นอนุมัติ
  runtime ไม่ส่ง flag นี้และไม่มี environment switch เปิดให้ยึดข้อมูลเก่าโดยปริยาย
- ตรวจ identity ทั้งก่อนและหลัง `BEGIN IMMEDIATE`; สร้าง schema โดยไม่ใช้
  `executescript()` ซึ่งจะ implicit commit; schema/migration failure rollback ownership
- tests ใช้ temporary DB เท่านั้น รวม byte snapshots ของ DB/sidecars, schema/journal mode,
  reopen, malformed identity, rollback และ competing initializers/adopters
- การ adopt workspace ไม่ได้พิสูจน์ ownership ของ orders/deals/reports เก่า ต้อง backup,
  ตรวจ provenance/เจ้าของ และ reconcile ข้อมูลเก่าก่อนใช้จริง; งานรอบนี้ไม่ได้ adopt DB ผู้ใช้
- ไม่รับรอง file mtime, OS metadata, active WAL recovery, network filesystem หรือหลาย host

## Direct MT5 continuity ที่ยังต้องแยกจาก acceptance

ทดสอบ fake terminal เท่านั้น: missing identity ต้องไม่ initialize; wrong account ต้องไม่อ่าน positions,
quote หรือส่งคำสั่ง; empty positions หลัง account switch ต้องไม่ถูกใช้เป็น authoritative empty
และ health ห้ามแสดง foreign account ว่า connected/degraded

การตรวจทันก่อน `order_send` ไม่สามารถปิด race กับการสลับบัญชีจากภายนอก terminal ได้
ไม่ใช้ผล tests นี้เป็น authorization เปิด execution; ต้องกำหนด session ownership/fencing
ก่อนปิด P2.2/P2.4 แม้มี persisted account binding สำหรับ claims ใหม่แล้ว

## รอบต่อเนื่อง — account claims และ reconciliation

- `_assert_account()` อ่าน identity ก่อน `BEGIN IMMEDIATE` แล้วเทียบ/สร้าง KV owner ภายใต้ write lock;
  `Database.cursor()` commit เมื่อสำเร็จและ rollback เมื่อ exception ไม่เปลี่ยน owner อัตโนมัติ
- First binding ปฏิเสธ orders/trades ของ alias เดิม หรือ open_positions ใด ๆ ใน DB;
  เป็น conservative global rejection ไม่ใช่เครื่องมือ migration/quarantine
- Claim เก็บ account_identity และ `_persist_result()` รักษา metadata; corrupt owner ถูกแปลงเป็น
  BrokerError โดยไม่ repair; replay ของ claim ที่ไม่มี/ไม่ตรง account ถูกปฏิเสธ
- `unresolved_orders()` เปรียบเทียบ claim กับ persisted workspace/account owner ก่อนรับ verified result;
  `reconcile()` ตรวจ account ซ้ำหลัง positions ก่อนยอมรับหรือเขียน snapshot
- RED `p22-tamper-red.log`: 2 failed/10 passed (corrupt owner และ tampered replay);
  RED `p22-reconcile-red.log`: 2 failed/12 passed (account switch และ tampered verified claim)
- Historical focused `p2-account-focused.log`: 77 passed ก่อน tests ล่าสุด;
  รอบ resume focused แรก 1 failed/79 passed เพราะ fixture Position ขาด sl/tp/current_price;
  แก้ fixture ให้ครบแล้ว ไม่ลด production guard
- Full `p2-account-full/summary.json`: ทุก job exit 0, JUnit 803 cases/39 skipped/0 failures/errors;
  เริ่มก่อนการแก้ล่าสุด จึงไม่ใช้แทน fresh verification รอบ resume
- Fresh verification ของ source ล่าสุด: `storage/local-dev/qa/safety/p2-resume-full/summary.json`;
  ต้องตรวจสถานะ terminal/JUnit ก่อนอ้างผล ไม่ยึด shell completion ที่จับไม่ได้
- Focused green ล่าสุด `p2-resume-focused-green.log` และ XML: 80 passed, failures/errors/skips 0;
  ครอบคลุม snapshot preservation และ competing first binding; full runner ยังรอ terminal ณ จุดบันทึกนี้

### ผล terminal หลังบันทึกข้างต้น

- `p2-resume-full` เสร็จตาม artifact clock 2026-11-09T08:26:20Z:
  769 passed / 39 skipped / 1 existing Starlette deprecation warning
- JUnit 808 cases, failures/errors 0; node/git/dependencies/Ruff/build/tests/diff ทุก job exit 0
- Skips: Redis dependency 20, Bash dependency 13, policy 6; ไม่มี unclassified skips
- อ่าน historical logs จริงแล้ว: `p22-regression.log` คือ 10 failed/58 passed;
  `p22-ownership-green.log` แม้ชื่อ green แต่มี failures จำนวนมาก ไม่ใช่หลักฐานผ่าน;
  `p23-storage-green.log` คือ 13 passed; ทั้งหมดไม่ใช้แทน fresh run
- ผล local ผ่านไม่เปลี่ยนสถานะ acceptance ที่ยังเปิดด้านล่าง และไม่อนุญาตเปิด execution

### Acceptance ที่ยังเปิด (ไม่อนุมานจาก tests ผ่าน)

รอบ P2.2 ต่อจาก H018: `p22-io-red.log` 5 failed/15 passed ยืนยัน account-switch
ระหว่าง modify, close, send acknowledgement, fill positions และ recovery positions
เพิ่ม `_assert_account()` หลัง I/O ก่อนยอมรับผลหรือเขียน trade; fill ตรวจซ้ำก่อน persist
แม้ปิด verify_after_send ก็ตรวจ account หลัง send; ไม่รับ filled/rejected acknowledgement จาก account ที่เปลี่ยน
กรณี send outcome ไม่แน่นอนคง pending/ไม่ resend; recovery ที่อ่าน account ผิดไม่เขียนทับ claim เดิม
เพิ่ม close TradeRecord regression ที่สลับ account ตอนอ่าน positions: ไม่เขียน trades/ไม่ลบ snapshot
`p22-io-green.log` และ XML ยืนยัน focused 79 passed, failures/errors/skips 0
Full ล่าสุดใช้ `storage/local-dev/qa/safety/p22-io-full/summary.json` ซึ่งยังรอ terminal ณ จุดบันทึกนี้
ผล terminal ที่มาภายหลัง: เสร็จ 2026-11-09T09:18:14Z ตาม artifact clock,
JUnit 814 cases/39 skipped/failures errors 0; ทุก job รวม lint/build/tests/diff exit 0
Post-I/O rejection ไม่ย้อนคืน broker action ที่เกิดไปแล้ว และไม่ใช่ broker-side atomic fencing

ตรวจ source เพิ่มเพื่อกำหนดงานถัดไป (ยังไม่แก้ในรอบนี้):
- `services/market_data/replay.py:268` ให้ config replay.dataset_dir มาก่อน Settings.paths;
  config default ยังเป็น storage/datasets จึงมีเส้นทางอ่าน legacy root ข้าม namespace
- `services/ai_forecast/registry.py:58` derive path จาก model_dir/version ไม่ได้โหลด DB path โดยตรง;
  ยังต้องตรวจ version traversal/symlink/provenance ก่อนถือว่าขอบเขตไฟล์ครบ
- finding เดิม `services/api_gateway/state.py:649` ไม่มี owner checks รอบอ่าน แก้ใน P2.3 runtime slice
  ด้านล่าง; ไม่ได้หมายความว่า account/cache/background consumers ทุกเส้นทางได้รับการตรวจแล้ว

- P2.2: management/send/fill/recovery post-I/O guards ผ่าน focused local แล้ว;
  history ingestion มี owner/evidence guards รอบนี้; resource provenance และ real account/session acceptance ยังเปิด
- P2.3: runtime `_manage_cycle()` cache/snapshot เป็นคนละเส้นทางจาก reconcile; custom replay root,
  model paths ใน DB, background/cache/file consumers และ real Redis ยังต้อง negative acceptance
- H143 เพิ่ม local guard ที่ `ModelRegistry` constructor: ตรวจ `model_dir` และ ancestors ก่อน `mkdir`, ปิด parent-symlink redirect ที่ยังไม่ครอบคลุมใน provenance tests; consumer/cache audit และ real Redis ยังเปิด
- H144 source audit: snapshot save/load/list ตรวจ root+ancestor symlinks, manifest/path identity และ content digest; tick read/inventory ตรวจ path links, manifest owner/root และ byte/content digests. ไม่พบช่องว่างที่ยืนยันได้ในสอง flow นี้; เป็น audit เฉพาะ flow ไม่ใช่การปิด consumer/cache audit ทั้งหมด
- H145 trace training worker → `ForecastPredictor.install()` → registry save/registration → verified reload: immutable version + persisted provenance/hash; existing regression corrupts bytes after registration and checks fail-closed install/cache invalidation. ไม่พบ bypass ที่ยืนยันได้ใน flow นี้; worker lifecycle/concurrent-start coverage ยังแยกเปิด
- H146 trace tick import CLI → importer → daily/legacy writers: output root ถูก constrain; `--csv` เป็นผู้ใช้เลือก source ไม่ใช่พื้นที่จัดเก็บที่ต้องผูกกับ workspace. CLI workspace tests 4 passed และ legacy provenance tests 15 passed ตาม runner artifacts. ไม่พบ bypass ใน flow นี้; source mutation ระหว่าง chunking และ concurrent imports ยังไม่ได้รับการยืนยัน
- P2.4: quarantine/migration workflow, external account-switch race และ broker-side fencing ยังไม่ปิด
- Settings.security ยังอ่าน environment ขณะเรียก property; การเปลี่ยน workspace ระหว่าง runtime
  ต้องทบทวนแยกจากการ derive paths ตอน initialization; namespace ไม่ใช่ OS access-control boundary

## หลักฐานและเกณฑ์ถัดไป

### P2.3 replica account/freshness ต่อจาก H032

- Terminal `p23-action-accepted-full`: 843 passed/39 skipped/1 warning;
  JUnit 882 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T11:01:46Z
- Publisher ส่ง account_identity envelope หลังตรวจ live identity/adapter และ persisted owner
  รอบสร้าง payload; ไม่ bind/adopt owner ผ่าน publication/read
- Replica ตรวจ workspace/broker/login/server/currency กับ local identity และ persisted owner,
  payload.account และ broker ของทุก position; ตรวจ identity/selection ซ้ำก่อนส่ง
- ปฏิเสธ timestamp ผิดรูปแบบ/NaN/infinity/future/age >10s แม้ backend TTL ยาวกว่า;
  อายุ positions รวม frame age ต้อง ≤10s และต้องมี available=true รวม empty positions
- Frame หาย/invalid/owner unavailable คืน minimal unavailable payload, account=null,
  risk fail-closed; ไม่ fallback local payload หรือใช้ _replica_frame เก่ารับรอง role
- RED 18 failed/1 passed (รวม expired-frame local fallback AttributeError);
  green แรก 1 failed/101 passed จาก publication fixture ยังไม่สร้าง persisted owner;
  แก้ test ให้ successful management read ก่อน publish โดยไม่ลด ownership checks
- `p23-replica-accepted-focused`: 122 passed/1 existing deprecation warning;
  canonical Ruff F,E9/diff exit 0; `p23-replica-accepted-full` ยังรอ terminal
- เป็น local/fake shared-store regression เท่านั้น ไม่มี real Redis/MT5 acceptance;
  envelope ไม่ใช่ cryptographic authentication หรือ broker-side fencing;
  UI unavailable wording/clock-skew availability, snapshot transactionality, close_all selection/
  notifications, custom paths และ provenance ยังเปิด ไม่ปิด P2/ไป P3

### P2.3 action disclosure invalidation ต่อจาก H030

- Terminal `p23-view-accepted-full`: 828 passed/39 skipped/1 warning; JUnit 867 cases,
  failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T10:48:39Z
- `_position_mutation()` ทำ unavailable ก่อนและหลัง submit/close_ticket/close_all/
  management modify/partial_close/close รวม exception; เก็บ cache/snapshot evidence เดิม
- นับ overlapping mutations และ epoch: management read ระหว่าง action หรือคาบเกี่ยว action
  ที่จบแล้วไม่ทำให้ presentation available; ต้องมี successful read ใหม่หลัง action ทั้งหมดจบ
- RED action 12 failed และ refresh-during-close 1 failed; green แรก 1 failed/133 passed
  จาก fixture OrderResult ขาด idempotency_key แก้ fixture โดยไม่ลด production guards
- Focused `p23-action-accepted-focused`: 136 passed/1 existing deprecation warning;
  canonical Ruff F,E9/diff exit 0; fresh full `p23-action-accepted-full` ยังรอ terminal
  ไม่ใช้ `p23-action-full` ซึ่งเริ่มก่อน fixture correction รับรอง source/tests สุดท้าย
- เป็น local disclosure guard ไม่ใช่ execution serialization หรือ snapshot transactionality:
  management read ที่ overlap ยังอาจเขียน snapshot; ต้องตรวจ write-side แยก
- replica ownership/freshness, UI unavailable wording, close_all adapter selection/notification
  semantics, custom paths, provenance และ real environment acceptance ยังเปิด ไม่ปิด P2/ไป P3

### P2.3 local position disclosure ต่อจาก H027

- ผล terminal `p23-runtime-accepted-full`: 809 passed/39 skipped/1 warning;
  JUnit 848 cases failures/errors 0 ทุก job exit 0 (artifact finished 2026-11-09T10:35:37Z)
- `position_view()` เป็น read-only guard ที่ REST state และ leader live payload (REST/WS) ใช้ร่วมกัน:
  ต้องมี successful owned management read อายุไม่เกิน 10 วินาทีจาก monotonic clock,
  ตรวจ live identity และ persisted owner ก่อน/หลัง serialize และตรวจ adapter selection
- เมื่อ owner หาย/เสียหาย/account เปลี่ยน/read ล้มเหลว/cache เก่า หรือเริ่ม management action:
  คืน positions ว่างพร้อม positions_status.available=false โดยไม่ลบ cache/snapshot เดิม
  และไม่สร้าง account-owner ผ่าน GET; unavailable หมายถึงไม่ทราบ exposure ไม่ใช่ไม่มี positions
- RED แรก 11 missing-method failures และ 2 fixture enum failures; แก้ enum แล้ว surface RED
  2 assertion failures ยืนยัน REST/live เปิดเผย foreign-account cache จริงก่อน patch
- Focused ล่าสุด `p23-view-final-focused.log`: 66 passed/1 existing deprecation warning;
  canonical Ruff F,E9 และ diff check exit 0; full ใหม่ `p23-view-full/summary.json` ยังรอ terminal
- ยังไม่ครอบคลุม replica frame account/freshness contract, UI unavailable wording, manual-action cache
  invalidation, switch-away/back หรือ atomic broker fencing; snapshot transactionality/custom paths/
  provenance/real Redis/MT5 acceptance ยังเปิด ไม่ปิด P2 หรือไป P3
- Correction ต่อเนื่อง: same-identity replacement adapter RED 1 failed; ผูก adapter object
  ที่ successful read กับ cache เพิ่มแล้ว `p23-view-accepted-focused` 67 passed/1 warning;
  Ruff F,E9/diff exit 0; full canonical ใหม่ `p23-view-accepted-full` ยังรอ terminal
  `p23-view-full` เริ่มก่อน adapter correction จึงไม่รับรอง source สุดท้าย

### P2.3 runtime cache/snapshot ต่อจาก H023

- `_manage_cycle()` pin adapter แล้วตรวจ persisted owner ก่อน/หลัง positions และหลัง symbol specs;
  ปฏิเสธ registry selection ที่เปลี่ยน ก่อนรับ snapshot/cache และก่อนแต่ละ management action
- Snapshot validation รวม foreign broker rows, duplicate tickets และ cross-account collisions
  ต้องผ่านก่อนแทน cache; failure เก็บ cache/snapshot เดิมและไม่ประเมิน actions
- Sync snapshot ก่อน actions และไม่เขียน pre-action list ซ้ำท้ายรอบ จึงไม่ resurrect row ที่ close ลบแล้ว;
  `_apply_action()` รับ pinned adapter ไม่อ่าน registry ซ้ำขณะส่งต่อ gateway
- RED `p23-runtime-red.log`: 9 failed/2 passed; action-switch RED 2 failed;
  pinned-adapter RED 1 failed จาก signature ที่ยังไม่รองรับ
- Focused ระหว่างทาง 85 → 87 passed; pinned-green รอบแรก 1 failed/87 passed จาก mock
  ไม่รับ keyword `adapter=`; แก้ fixture แล้ว `p23-runtime-accepted-focused` 88 passed
- Full สุดท้ายให้ยึด `p23-runtime-final-full/summary.json`; เริ่มหลัง production patch สุดท้าย
  ก่อน fixture keyword correction; ตรวจ JUnit จริงก่อนอ้าง acceptance ไม่ใช้ full รอบแรกแทน
- Correction หลัง terminal: `p23-runtime-final-full` จบ 1 failed/808 passed/39 skipped/1 warning;
  failure เป็น pre-correction keyword mock ข้างต้น; canonical fresh final เปลี่ยนเป็น
  `p23-runtime-accepted-full/summary.json` ที่เริ่มหลังหยุดแก้ source/tests แล้ว ยังรอ terminal
- Full รอบแรก `p23-runtime-full` จบ failed: JUnit 847 cases/2 failures/0 errors/39 skipped;
  failures คือ account/adapter switch ระหว่าง evaluate เพราะ process โหลด source ก่อน action guard
  เก็บเป็น intermediate evidence ไม่ใช้ชื่อ directory หรือ focused green กลบ failed full
- Ruff แบบ expanded พบ 3 findings เดิมนอก scope (import order และ shutdown except/pass);
  ไม่ rewrite งานเดิมเพื่อแก้ style; canonical gate ของ repository คือ `--select F,E9`
- ขอบเขตยังเปิด: cache presentation freshness/account binding ใน REST/WS, concurrent registry/session
  changes ระหว่าง checks, snapshot writer transactionality และ P4.7 unscoped empty writes;
  เก็บ cache เดิมไม่เท่ากับรับรองว่าเป็นสถานะปัจจุบัน ไม่ใช่ atomic broker-side fencing
- งานถัดไป custom replay root/model paths แล้ว P2.4 legacy provenance/quarantine;
  ไม่มี trading activation, broker connection, DB adoption, deploy/restart, commit หรือ push

### P2.2 history slice ต่อจาก H020

- `refresh_history()` ตรวจ persisted owner ก่อนและหลังอ่าน; batch ต้องมี explicit
  `account_identity` ตรง broker/login/server/currency และ account_key แม้ไม่มี deals
- ตรวจ currency ทั้ง batch ก่อน ledger validation/persistence; row broker/account guards เดิมยังคงอยู่
- MT5 คืน batch evidence จาก identity ที่ตรวจรอบ history read; ไม่ใช้ inferred comment ownership
- RED `p22-history-red.log`: 13 failed; focused ล่าสุด `p22-history-final-focused.log`:
  59 passed รวม empty MT5 evidence และ existing pending claim preservation
- Ruff ตรวจไฟล์ที่แก้ครั้งแรกพบ style violations 7 จุด; แก้แล้วตรวจซ้ำผ่าน exit 0
- Full `p22-history-full/summary.json` ยังรอ terminal; ไม่ยืมผล p22-io-full อ้าง source ล่าสุด
- ผล terminal ภายหลัง: 790 passed/39 skipped/1 warning; JUnit 829 cases failures/errors 0;
  ทุก job exit 0 เสร็จ 2026-11-09T10:00:24Z ตาม artifact clock; ไม่มี real Redis/MT5 acceptance
- Legacy broker_deals provenance, currency changes ในประวัติ, incomplete history และ external
  switch-away/back ระหว่าง checks ไม่ได้รับการรับรอง; ไม่ใช่ broker-side fencing หรือ claim resolution

- `storage/local-dev/qa/safety/p2-p1-evidence-check.json`: ตรวจ P1 manifest binding,
  54 artifact hashes/byte lengths, terminal exit artifacts และ JUnit counts โดยไม่ recapture baseline
- RED: `p2-preflight-red.log` (8 failed/1 passed), `p2-surfaces-red.log` (4 failed/1 passed),
  `p2-adoption-flag-red.log` (1 failed/11 passed), `p2-runtime-red.log` (1 failed/5 passed),
  `p2-continuity-red.log` (11 failed/1 passed); failures รวม missing guard และ API ที่ยังไม่มี
- Focused หลังแก้: `p2-focused-final.log` — 82 passed / 1 existing deprecation warning
- Full รอบแรก `p2-verification`: 7 failed / 724 passed / 39 skipped; WS fake DB ไม่มี workspace;
  แก้ fixtures ให้สะท้อน identity contract ไม่ลด production guard
- Full หลังแก้ให้ยึด `p2-final-verification/summary.json`, terminal exits และ JUnit จริง
  ห้ามอนุมานจากสถานะ process หรือ shell integration ที่จับ output ไม่ได้

### H035–H036: replica terminal และ UI disclosure

- Replica accepted-full: 868 passed/39 skipped/1 warning; JUnit 907 cases failures/errors 0;
  summary ทุก job exit 0; finished 2026-11-09T11:07:20Z ตาม artifact clock (วันอ้างอิง 8 พ.ย. 2026)
- Store ตรวจ positions_status คู่กับ rows ทุก frame ไม่ inherit availability จาก light/error frame;
  available ต้อง boolean true, age numeric finite/nonnegative และรวมเวลาฝั่ง client ไม่เกิน 10s
- ตารางแยก unknown exposure จาก owned empty และปิด buttons ตาม availability/role;
  กราฟอ่าน gated positions พร้อม watch เพื่อถอน stale overlays โดยไม่ลบ prior payload evidence
- RED UI 1 failed missing availability; focused แรก 94 passed รวม Vue SSR/store จริง;
  Ruff F,E9/diff exit 0; เพิ่ม role/button assertions และ fresh p23-ui-accepted-full ยังรอ terminal
- ไม่ใช่ browser/visual review, broker-side fencing หรือ execution lock; snapshot transactionality,
  close_all adapter/notification/ack semantics, custom paths และ legacy quarantine ยังเปิด

### H037–H038: UI terminal และ snapshot transactionality

- UI accepted-full terminal 869 passed/39 skipped/1 warning; JUnit 908 cases failures/errors 0;
  ทุก job exit 0; artifact finished 2026-11-09T11:26:23Z (วันอ้างอิง 8 พ.ย. 2026)
- P2.3/P4.7 snapshot collision checks และ replacement อยู่ใน BEGIN IMMEDIATE เดียว;
  failure rollback ทั้งชุด; empty snapshot ต้อง explicit nonblank broker scope
- Runtime ข้าม read ระหว่าง active mutation; discard read ที่ epoch เปลี่ยนก่อนเขียน;
  runtime lock ครอบ epoch check/snapshot/cache acceptance; ไม่ evaluate stale-read actions
- RED 8 failed/138 passed; green 146; accepted-focused 148 passed รวม rollback insert/delete,
  observer connection, writer-lock collision recheck และ concurrent read หลัง mutation ลบ snapshot
- Ruff F,E9/diff exit 0; fresh p23-snapshot-accepted-full ยังรอ terminal
- ไม่ใช่ cross-process ordering, broker execution lock/fencing หรือ crash/power-loss acceptance;
  record_trade ยัง trade insert/delete แยก transaction; close_all semantics/custom paths/P2.4 ยังเปิด

### H039–H040: snapshot terminal และ close_all results

- Snapshot accepted-full 879 passed/39 skipped/1 warning; JUnit 918 cases failures/errors 0;
  ทุก job exit 0; artifact finished 2026-11-09T12:06:43Z (วันอ้างอิง 8 พ.ย. 2026)
- close_all ใช้ pinned adapter และ owner checks รอบ read/action; ตรวจ foreign/duplicate rows
  ก่อนส่ง; selection/account เปลี่ยนหยุด batch ไม่ retry
- attempted/accepted/rejected เป็น acknowledgement; exposure_verified=false ไม่รับรอง flat account;
  notification/UI ไม่แสดงจำนวน attempts เป็นจำนวนปิดสำเร็จ
- RED 11 failed/130 passed/1 warning → green 141; UI RED missing feedback module;
  accepted-focused 142 passed/1 existing warning; Ruff F,E9/diff exit 0
- Fresh p23-closeall-accepted-full ยังรอ terminal; exception partial-result reporting,
  single-close/management notifications, record_trade atomicity และ custom paths ยังเปิด
- ไม่มี broker fencing/real acceptance; exception หลังส่งบางรายการต้อง reconcile ไม่ resend

### H041–H042: close_all terminal และ exception results

- วันอ้างอิง 8 พ.ย. 2026: closeall accepted-full 890 passed/39 skipped/1 warning;
  JUnit 929 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T13:34:57Z ตาม artifact clock
- P2.3 เก็บ prior acknowledgements หลัง exception; send/malformed acknowledgement/post-owner failure
  เป็น unknown (ok=null); ที่ยังไม่เรียก gateway เป็น not_attempted; หยุดทันที ไม่มี retry
- attempted นับ gateway invocation ไม่ใช่หลักฐาน broker send; exposure_verified=false และ
  reconciliation_required=true; notification failure ไม่ทำ response หายและคืน notification_failed
- Pre-batch owner/read/scope failures ยัง raise; ไม่เผย raw exceptions; ไม่ใช่ broker fencing/execution lock
- RED 5 failed/139 passed → green 144; UI RED unknown count; edge RED 5 failed/146 passed;
  accepted-focused 151 passed/1 existing warning รวม route contract/Vue SSR; Ruff F,E9/diff exit 0
- Fresh p23-partial-accepted-full dependency/lint/build ผ่าน; tests ยังรอ terminal;
  single-close UI/management acknowledgement wording, record_trade atomicity, custom paths และ P2.4 ยังเปิด
- ถัดไป full terminal → remaining acknowledgement consumers → custom paths → P2.4 quarantine;
  real Redis/MT5/browser/crash acceptance ยังไม่ทำ ไม่มี activate/connect/adopt/deploy/restart/commit/push

### H043–H044: partial terminal และ single-close/management feedback

- วันอ้างอิง 8 พ.ย. 2026: partial accepted-full 899 passed/39 skipped/1 warning;
  JUnit 938 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T13:44:09Z ตาม artifact clock
- P2.3 single-close UI ไม่อ้างปิดแล้ว; feedback แยก gateway acknowledgement จาก exposure;
  HTTP/transport errors และ close_all fallback ย้ำผลไม่แน่นอน ต้องตรวจสถานะก่อนส่งซ้ำ
- Management modify/partial_close/close เลิก Stop moved/Position closed/success;
  accepted/rejected/unknown เป็น gateway reply เท่านั้น execution/exposure ยังไม่ verified;
  modify False รวม BrokerError จึงแสดง unknown / not accepted; exceptions แจ้ง unknown แล้ว propagate ไม่ retry
- RED 13 failed/150 passed → focused green 163 passed/1 existing warning รวม management 12 cases,
  Vue SSR/store, feedback helper และ source wiring; Ruff F,E9/diff exit 0
- Fresh p23-ack-accepted-full เริ่มแล้ว ยังรอ terminal; ไม่ใช่ browser/real Redis/MT5 acceptance
- ยังเปิด single-close structured exception payload, management notifier failure masking original exception,
  adapter status mapping, record_trade atomicity, custom paths/P2.4; ไม่เปลี่ยน gateway execution contract
- ถัดไป full terminal → remaining close outcome/notification edge cases → custom paths → legacy quarantine;
  ไม่ปิด P2/ไป P3 ไม่มี activate/connect/adopt/deploy/restart/commit/push

### H045: management notification failure ไม่กลบ action outcome

- วันอ้างอิง 8 พ.ย. 2026: RED 2 failed/163 passed → accepted-focused 165 passed/1 existing warning;
  Ruff F,E9/diff exit 0; notification errors ใช้ generic log ไม่เผย private detail ไม่ retry
- Accepted action ไม่กลายเป็น exception จาก notifier; original action RuntimeError ยังคง propagate
- p23-ack-accepted-full เริ่มก่อน patch นี้ ไม่ใช่ final evidence; fresh p23-ack-final-full
  dependency/lint/build ผ่าน แต่ tests ยังรอ terminal; P2 ยังเปิด ไม่ไป P3
- ถัดไป final-full terminal → remaining close outcome contracts → custom paths → legacy quarantine;
  single-close structured exceptions, adapter mapping/record_trade atomicity และ real/browser acceptance ยังเปิด

### H046–H047: ack terminal และ single-close unknown contract

- วันอ้างอิง 8 พ.ย. 2026: p23-ack-final-full 913 passed/39 skipped/1 warning;
  JUnit 952 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T14:26:54Z ตาม artifact clock
- P2.3 single-close pin adapter/owner checks ก่อนและหลัง gateway; exception/malformed reply/selection change
  คืน structured unknown ไม่เผย raw exception ไม่ retry; attempted นับ gateway invocation ไม่ยืนยัน broker send
- accepted/rejected เป็น gateway acknowledgement เท่านั้น; exposure_verified=false/reconciliation_required=true;
  HTTP 400 detail คง unknown contract ผ่าน actual TestClient; UI ใช้ err.detail ไม่ตีความ unknown ว่าปฏิเสธ
- RED 10 failed/163 passed → accepted-focused 173 passed/1 existing warning; Ruff F,E9/diff exit 0
- fresh p23-single-accepted-full dependencies/lint/build ผ่าน แต่ tests ยังรอ terminal
- พบ debt ยังไม่แก้: Bridge default missing/unknown status เป็น closed, verified จาก ok;
  MT5 non-DONE/None เป็น rejected และ requested volume ไม่ใช่ actual fill; ไม่ใช้ runtime guards รับรอง adapter mapping
- ถัดไป single full terminal → adapter close acknowledgement mapping → custom paths → P2.4;
  record_trade atomicity, real Redis/MT5/browser/crash acceptance ยังเปิด ไม่มี activate/connect/adopt/deploy/restart/commit/push

**ยังไม่ปิดเฟส 2:** ต้องตรวจ account-bound order/session ownership ให้ครบทุกเส้นทาง (P2.2), files/cache/background
negative acceptance ให้ครบ (P2.3), quarantine/migration provenance ของข้อมูลเก่าและ continuity
ที่ไม่พึ่งการเดาจาก broker alias (P2.4) ก่อนเดิน P3.3/P3.6

### H048–H049: single terminal และ Bridge close receipts

- วันอ้างอิง 8 พ.ย. 2026: p23-single-accepted-full terminal 921 passed/39 skipped/1 warning;
  JUnit 960 cases failures/errors 0 ทุก job exit 0; artifact finished 2026-11-09T14:50:46Z ตาม artifact clock
- P2.3 Bridge close ต้อง explicit ok=true และ closed/filled, ticket ตรง, reported volume finite/positive
  ไม่เกิน requested; missing/unknown/partial/pending คืน BrokerError เพื่อ runtime unknown; verified=false
- ไม่ default closed หรือใช้ requested volume แทน reported receipt; receipt ไม่พิสูจน์ actual broker fill/exposure
- Gateway pending/submitted/partially_filled เป็น unknown ไม่ใช่ rejected; real-gateway runtime tests
  ตรวจ single/close-all หยุดโดยไม่ retry ไม่เขียน trades และเก็บ ticket ถัดไปเป็น not_attempted
- RED 17 failed/209 passed → initial green 226 passed/1 warning; expanded focused 1 failed/227 passed
  (SPA 404 ระหว่าง full dashboard build พร้อมกัน); เก็บ failed evidence และรอ accepted-recheck
- Ruff F,E9/diff exit 0; p23-mapping-accepted-full dependency/lint/build ผ่าน tests ยังรอ terminal
- ยังเปิด MT5 None/non-DONE/partial/actual volume, EA requested-volume reporting, Bridge error review,
  record_trade atomicity, custom paths/provenance/P2.4 และ real Redis/MT5/browser/crash acceptance
- ไม่ปิด P2/ไป P3 ไม่มี activate/connect/adopt/deploy/restart/commit/push
- H049 verification addendum: accepted-recheck หลัง build จบ 228 passed/1 existing warning exit 0;
  Ruff F,E9/diff exit 0; เก็บ expanded focused failure เดิมไว้; full tests ยัง RUNNING

### H147 — Trade review account scope (local, pending verification)

- Regression RED showed `/api/trading/trades` previously returned rows for another `broker_id`; list now filters to the active adapter, and detail endpoint rejects other-account tickets as not found.
- Detail uses the stored trade plus exact `signal_id`, and accepts a snapshot only when its broker ID and symbol match. Missing linkage is explicit; retrospective derives only from persisted realized P&L/points/R and does not run a new prediction.
- API outage test covers market feed outage only; process/database offline and browser-side retained history are not implemented/accepted. Broker history completeness and deal-to-trade ownership remain separate P3 work.
- Expanded pre-correction feature run had 4 pass/2 fail; scope assertion was too strict about same-account row count, and ticker assignment referenced `quote` before definition. Both corrected. Fresh isolated API regression: 6 passed with exit 0, JUnit clean, stderr empty. Full API module still terminates with Windows `3221225786` and no log; not counted as module pass. Vite build log says built in 15.63s and includes Trades chunk, but wrapper exit marker absent; SFC transform verifies compiled selection handlers, no browser interaction test run.