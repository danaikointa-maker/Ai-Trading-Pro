<template>
  <div class="space-y-4">
    <header class="rounded-xl border border-sky-500/30 bg-sky-500/10 p-4 sm:p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h1 class="text-xl font-semibold text-slate-100">AI Development Team</h1>
        <span class="chip border-sky-500/30 text-sky-200">OFFLINE · READ-ONLY</span>
      </div>
      <p class="mt-3 text-sm leading-relaxed text-slate-300">
        พื้นที่ทีมพัฒนาแยกจาก AI Trading Floor ขณะนี้ยังไม่มีการเชื่อมต่อ service ของ No7 AI Dev Team
        จึงไม่แสดง project, agent หรือ task ว่าเป็นข้อมูลจริง
      </p>
    </header>

    <section class="grid gap-3 md:grid-cols-2" aria-label="สถานะการเชื่อมต่อ">
      <article v-for="item in checkpoints" :key="item.title" class="panel p-4">
        <p class="label">{{ item.title }}</p>
        <p class="mt-2 text-sm font-semibold text-slate-100">{{ item.status }}</p>
        <p class="mt-1 break-words text-xs leading-relaxed text-muted">{{ item.detail }}</p>
      </article>
    </section>

    <section class="panel p-4" aria-labelledby="contract-heading">
      <h2 id="contract-heading" class="panel-title">สัญญาข้อมูลที่เตรียมไว้</h2>
      <dl class="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <dt class="label">Read endpoint</dt>
          <dd class="num mt-1 text-sm text-slate-100">GET /api/v1/projects</dd>
        </div>
        <div>
          <dt class="label">Contract version</dt>
          <dd class="num mt-1 break-all text-sm text-slate-100">no7-ai-dev-team.project-snapshot.v1</dd>
        </div>
      </dl>
      <p class="mt-3 text-xs leading-relaxed text-muted">
        มี fixture สำหรับตรวจ schema แบบออฟไลน์เท่านั้น; ไม่เรียก API ภายนอก ไม่อ่าน credential
        และปิดความสามารถสั่งงานไว้เสมอ
      </p>
      <a
        class="mt-3 inline-block text-xs text-sky-200 underline"
        href="https://github.com/danaikointa-maker/no7_ai_dev_team_plan"
        target="_blank"
        rel="noopener noreferrer"
      >เปิดแผน No7 AI Dev Team ↗</a>
    </section>

    <section class="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4" aria-label="ขั้นตอนที่ยังรอ">
      <h2 class="text-sm font-semibold text-amber-200">รอข้อมูลก่อนเปิด live read</h2>
      <p class="mt-2 text-xs leading-relaxed text-slate-300">
        ต้อง provision Keycloak และ Vault PKI พร้อมกำหนด tenant/project ID ของ default workspace ก่อน
        จากนั้นจึงต่อเฉพาะ project registry แบบอ่านอย่างเดียว; route งาน worker/task ยังไม่มีใน upstream
      </p>
    </section>
  </div>
</template>

<script setup>
const checkpoints = [
  {
    title: 'Identity',
    status: 'Keycloak + Vault PKI · ยังไม่ provision',
    detail: 'เลือกแนวทางแล้ว แต่ยังไม่มี issuer, service identity หรือ certificate role ที่ใช้งานได้',
  },
  {
    title: 'Workspace scope',
    status: 'default workspace · รอ tenant/project ID',
    detail: 'ยังไม่มี scope ID สำหรับจำกัดคำขอให้อยู่ใน project ที่อนุญาต',
  },
  {
    title: 'Upstream capability',
    status: 'Project registry only',
    detail: 'API ปัจจุบันยังไม่เปิดข้อมูล agent, worker, task หรือ execution state',
  },
  {
    title: 'Execution',
    status: 'Disabled',
    detail: 'หน้านี้ไม่มีคำสั่ง shell, repository write, approval หรือ deployment action',
  },
]
</script>
