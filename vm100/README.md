# VM100 Document Pack

เอกสารชุดนี้รวบรวมแนวทางเตรียม VM100 ให้ทำงานคู่กับเครื่อง Windows สำหรับ No7 AI Trading Pro โดยเน้น AI Development/QA/Creative Office และ API/control-plane ฝั่ง VM100; Trader และ MT5 อยู่ฝั่ง Windows

## อ่านตามลำดับ

1. [`AGENTS.md`](AGENTS.md) — ข้อกำหนดความปลอดภัยและบทบาทเครื่องที่มีผลเหนือแผนงาน
2. [`UNIFIED-MASTER-PLAN-V4.md`](UNIFIED-MASTER-PLAN-V4.md) — สถาปัตยกรรมและขอบเขตงานเป้าหมาย
3. [`UNIFIED-TASK-REGISTER-V4.md`](UNIFIED-TASK-REGISTER-V4.md) — คิวงานและหลักฐาน/สถานะล่าสุดที่บันทึกไว้
4. [`UNIFIED-CONFLICTS-V4.md`](UNIFIED-CONFLICTS-V4.md) — ข้อขัดแย้งและแนวทางป้องกันการทำงานซ้ำหรือทำให้ระบบถอยหลัง
5. [`VM100-PARALLEL-DEV-HANDOFF-V1.md`](VM100-PARALLEL-DEV-HANDOFF-V1.md) — แบ่งงาน Windows/VM100, วิธีเชื่อมต่อ, Cloudflare, readiness และ rollback
6. [`WINDOWS-VM100-WORK-ALLOCATION.md`](WINDOWS-VM100-WORK-ALLOCATION.md) — แยกงาน Windows/VM100 สำหรับ TradingView, AI Officer/QA และ Ai-Video-Editor
7. [`WINDOWS-TRADING-INTERFACE-CONTRACT.md`](WINDOWS-TRADING-INTERFACE-CONTRACT.md) — ขอบเขตเชื่อมต่อกับ Windows Trader และโหมด Manual/Semi-Auto/Auto; VM100 ไม่มีสิทธิ์ส่งคำสั่งโบรกเกอร์
8. [`references/README.md`](references/README.md) — แหล่งที่มาและสถานะ PR ของเอกสาร Officer/QA และ Video ที่นำเข้าจาก GitHub

## เอกสารต้นฉบับจาก GitHub

สำเนาเอกสาร Draft ที่นำเข้าเป็น reference อยู่ใน [`references/README.md`](references/README.md): แผน Officer/QA จาก PR #154 และแผน Ai-Video-Editor จาก PR #153 พร้อม source branch, commit และ hash ที่ใช้ตรึง snapshot ทั้งสอง PR ยังไม่ merge จึงยังเป็นข้อเสนอ ไม่ใช่พฤติกรรมที่ติดตั้งใน runtime

## วิธีใช้ชุดเอกสาร

- นี่คือ snapshot สำหรับ handoff จาก planning worktree `Ai-Trading-Pro-unified-v4-plan` ณ วันที่ 2026-11-22 ไม่ใช่ source code หรือคำสั่งติดตั้งที่ผ่านการรับรองบน VM100
- Source of truth สำหรับโค้ดและเอกสารปัจจุบันยังเป็น repository หลัก `danaikointa-maker/Ai-Trading-Pro`; ให้ตรวจ branch/commit ปัจจุบันและซิงก์เอกสารชุดนี้ผ่าน Git/PR ก่อนใช้เป็น runbook จริง
- `AGENTS.md` ในโฟลเดอร์นี้ระบุขอบเขต VM100 ปัจจุบัน ส่วนสำเนา blueprint เก่าที่มีบทบาท VM200 เก็บไว้ใน `references/legacy/` เพื่ออ้างอิงประวัติเท่านั้น; กฎความปลอดภัย root ของ repository ยังมีผลเหนือกว่า
- เมื่อตรวจ checkout เต็มแล้ว ให้อ่าน `README.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/RUNBOOK.md`, `docs/LIMITATIONS.md`, `config/` และ `docs/blueprint-v3/AGENTS.md` จาก root ของ repository ด้วย เอกสารเหล่านั้นอธิบายพฤติกรรมที่มีอยู่จริงและอาจไม่ตรงกับแผนเป้าหมาย
- สถานะ VM100, Cloudflare Tunnel, DNS `agent.youridea168.com`, Access policy, origin port และ feed ในเอกสารเป็นหลักฐาน/ความตั้งใจ ณ เวลาที่ระบุ ต้องตรวจใหม่ก่อนใช้งาน
- การวางเอกสารไว้ในโฟลเดอร์นี้ไม่ได้ติดตั้งหรือเปลี่ยน service, database, firewall, DNS, Cloudflare route หรือเปิดสิทธิ์เทรด
- เอกสาร `vm100/` รวมข้อกำหนด VM100 และ interface ที่จำเป็นต่อการทำงานกับ Windows แต่ไม่ใช่ source code/installer แบบ standalone; ให้ clone repository เต็มก่อนแก้หรือรันระบบ

เป้าหมาย Cloudflare คือ `https://agent.youridea168.com` → Cloudflare Tunnel → service staging ที่ bind เฉพาะ loopback หลังผ่าน readiness/security gates เท่านั้น ห้าม route ไปพอร์ต development/simulator `8000` หรือเปิด MT5 execution bridge สู่สาธารณะ
