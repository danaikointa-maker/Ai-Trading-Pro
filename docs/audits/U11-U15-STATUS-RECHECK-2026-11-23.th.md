# U11–U15 Regression and Acceptance Recheck

วันที่: 2026-11-23
ฐาน: `plan/unified-development-v4` ที่ `2b06e027fbaac7b34dd6fa15e820ffbe726a22c4`
ขอบเขต: ทดสอบ source/local fixtures และตรวจสถานะเอกสาร V4 โดยไม่เชื่อมบัญชีหรือส่งคำสั่ง

## ผลตรวจ

| งาน | ผล local | สถานะ acceptance |
|---|---|---|
| U11 Demo acceptance | PASS เฉพาะ read-only/failure-safety fixtures | **BLOCKED** — ไม่มี MT5 Demo order, partial fill, restart/power-loss หรือ broker receipt; ไม่มีคำสั่งถูกส่ง |
| U12 AI Trader Team | PASS เฉพาะ read-only `/api/explain` tests | **PARTIAL** — officer orchestration ยังไม่ implement และ independent security review ยังไม่ทำ |
| U13 Documentation sync | ตรวจชุด README/API/ARCHITECTURE/MATH/RUNBOOK/LIMITATIONS เดิม | **DONE** — ไม่มี documentation/runtime config เปลี่ยนใน recheck นี้ |
| U14 TradingView contract | Contract, normalizer, persistence tests ผ่าน | **DONE เฉพาะ contract** — upstream corpus, Pine compile, Bar Replay และ release certification ยัง NOT TESTED |
| U15 Secure adapter | Auth, allowlist, payload limits, redaction, dedupe และ rate-limit tests ผ่าน | **PARTIAL** — TLS/proxy, secret manager, multi-worker limiter และ public threat model ยัง NOT TESTED |

## หลักฐานทดสอบ

คำสั่งทดสอบชุดเดียว:

```text
pytest -q tests/test_tradingview_contract.py tests/test_tradingview_ingest.py tests/test_tradingview_persistence.py tests/test_ai_trader_readonly.py tests/test_security.py tests/test_mt5_readonly.py tests/test_mt5_windows_pc_readonly.py tests/test_ratelimit.py tests/test_ratelimit_shared.py
```

ผล: **115 passed**, warning เดิม 1 รายการจาก Starlette/httpx (`TestClient` แนะนำ `httpx2`). ชุด MT5 ใช้ fixture/fake เท่านั้น ไม่ได้เปิดหรือสลับ terminal จริง

## ขอบเขตที่คงไว้

- ไม่สร้าง order API, execution tool, signal engine, risk engine, agent runtime หรือ database ใหม่
- ไม่ enable TradingView ingress ใน runtime และไม่เปลี่ยนค่า Cloudflare/DNS
- ไม่อ่านหรือเปลี่ยน secret, account, VM service, broker state, Auto หรือ Live setting
- U12 ไม่เริ่มสร้าง officers จนกว่าเงื่อนไข independent review และขอบเขต account/data ตาม V4 จะผ่าน
- U11 ต้องรอ fresh quote ที่ยืนยัน Demo identity และการอนุมัติทดสอบ Demo แยกต่างหาก
- U15 ยังต้องพิสูจน์ public perimeter/proxy/secret rotation/multi-worker ก่อนเปิดใช้จริง
