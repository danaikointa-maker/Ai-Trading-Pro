// Acknowledgements are not an authoritative post-close position read.
export function closeFeedback(result) {
  const unknown = result?.outcome === 'unknown' || result?.unknown > 0
  const outcome = unknown ? 'ไม่ทราบผลคำขอปิด' : result?.ok === true ? 'ตอบรับคำขอปิด' : result?.ok === false ? 'ปฏิเสธคำขอปิด' : 'ไม่ทราบผลคำขอปิด'
  return {
    type: !unknown && result?.ok === true ? 'info' : 'error',
    message: `${outcome} — ยังไม่ยืนยัน exposure คงเหลือ ต้องตรวจสอบสถานะก่อนส่งซ้ำ`,
  }
}

export function closeAllFeedback(result) {
  const unknown = result?.unknown ?? 0
  const notAttempted = result?.not_attempted ?? 0
  const valid = [result?.attempted, result?.accepted, result?.rejected, unknown, notAttempted]
    .every((n) => Number.isSafeInteger(n) && n >= 0)
    && result.accepted + result.rejected + unknown === result.attempted
  return {
    type: !valid || result.ok !== true || result.rejected > 0 || unknown > 0 || notAttempted > 0 ? 'error' : 'info',
    message: valid
      ? `คำขอปิด: ตอบรับ ${result.accepted} / ปฏิเสธ ${result.rejected} / ไม่ทราบผล ${unknown} จาก ${result.attempted} รายการ / ยังไม่ส่ง ${notAttempted} — ยังไม่ยืนยัน exposure คงเหลือ ต้องตรวจสอบสถานะก่อนส่งซ้ำ`
      : 'ผลคำขอปิดไม่ครบถ้วน — ยังไม่ยืนยัน exposure คงเหลือ ต้องตรวจสอบสถานะก่อนส่งซ้ำ',
  }
}