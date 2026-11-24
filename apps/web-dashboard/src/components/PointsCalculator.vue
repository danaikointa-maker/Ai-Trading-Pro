<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Trading Calculators</div>
        <div class="panel-sub">{{ sourceLabel }} · {{ sourceContext }}</div>
      </div>
      <span class="chip" :class="spec?.source === 'broker' ? 'chip-up' : 'chip-gold'" :title="`Feed: ${provenance?.market_feed || '—'}`">
        {{ spec?.symbol || state.symbol }} · {{ spec?.source || '—' }}
      </span>
      <button type="button" class="btn py-1.5" :aria-expanded="learningVisible" @click="learningVisible = !learningVisible">{{ learningVisible ? 'ปิดบทเรียน' : 'เรียนรู้' }}</button>
    </div>
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-700 px-4 pt-3">
      <label class="flex min-w-0 items-center gap-2">
        <span class="label shrink-0">เครื่องมือคำนวณ</span>
        <select v-model="tool" class="input min-w-0 py-1.5" aria-label="Calculator tool">
          <option value="atr_volatility">ATR &amp; volatility</option>
          <option value="support_resistance">Support / resistance</option>
          <option value="points">Points → P&amp;L</option>
          <option value="size">Position size</option>
          <option value="risk_reward">Risk / Reward</option>
          <option value="break_even">Break-even win rate</option>
          <option value="trading_costs">Spread / commission / swap</option>
          <option value="drawdown">Drawdown recovery</option>
          <option value="point_tick">Points / Ticks</option>
          <option value="profit_loss">Profit &amp; Loss</option>
          <option value="auto_sl_tp">Auto SL/TP preview</option>
          <option value="margin">Margin / Leverage</option>
          <option value="confirmation_100pt">100-Point preview</option>
          <option value="scenario">Scenario simulator</option>
          <option value="capital_growth">Capital growth</option>
          <option value="currency_convert">Currency converter</option>
          <option value="trade_review_whatif">Trade review / what-if</option>
        </select>
      </label>
      <div class="flex items-center gap-1.5">
        <span class="chip" :class="isReadOnlyTool ? 'chip-up' : 'chip-gold'">{{ isPlanPreviewTool ? 'READ ONLY · PLAN PREVIEW' : isAnalysisTool ? 'READ ONLY · ANALYSIS' : isBrokerReadTool ? 'READ ONLY · BROKER PREVIEW' : 'MANUAL · SANDBOX' }}</span>
        <button type="button" class="btn py-1.5" @click="resetInputs">Reset</button>
        <button v-if="result && (tool !== 'size' || positionSize)" type="button" class="btn py-1.5" @click="copyResult">Copy result</button>
        <button v-if="result && (tool !== 'size' || positionSize)" type="button" class="btn py-1.5" @click="downloadResult('json')">JSON</button>
        <button v-if="result && (tool !== 'size' || positionSize)" type="button" class="btn py-1.5" @click="downloadResult('csv')">CSV</button>
        <button v-if="result && (tool !== 'size' || positionSize)" type="button" class="btn py-1.5" title="พิมพ์หรือบันทึกเป็น PDF จากหน้าต่างเบราว์เซอร์" @click="printResult">PDF</button>
      </div>
    </div>
    <section v-if="learningVisible" class="border-b border-ink-700 bg-ink-900/50 px-4 py-3" aria-label="Calculator learning center">
      <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(260px,0.8fr)]">
        <article class="rounded-lg border border-ink-700 p-3">
          <label class="label" for="calculator-lesson">บทเรียนพื้นฐาน</label>
          <select id="calculator-lesson" v-model="selectedLessonId" class="input mt-1 max-w-md">
            <option v-for="lesson in lessons" :key="lesson.id" :value="lesson.id">{{ lesson.title }}</option>
          </select>
          <p class="mt-2 text-xs leading-relaxed text-slate-300">{{ selectedLesson.body }}</p>
          <p class="mt-2 text-[10px] leading-relaxed text-muted">{{ selectedLesson.example }}</p>
        </article>
        <article class="rounded-lg border border-ink-700 p-3">
          <h3 class="text-xs font-semibold">ลองตอบ</h3>
          <p class="mt-1 text-xs text-slate-300">{{ selectedLesson.question }}</p>
          <div class="mt-2 space-y-1.5">
            <label v-for="(answer, index) in selectedLesson.answers" :key="answer" class="flex items-start gap-2 text-xs text-slate-300">
              <input v-model.number="quizChoice" type="radio" name="calculator-quiz" :value="index" class="mt-0.5 accent-gold-400" />{{ answer }}
            </label>
          </div>
          <button type="button" class="btn mt-2 py-1.5" @click="checkLessonAnswer">ตรวจคำตอบ</button>
          <p v-if="quizFeedback" class="mt-2 text-[10px] leading-relaxed" :class="quizCorrect ? 'text-up' : 'text-amber-300'">{{ quizFeedback }}</p>
        </article>
      </div>
    </section>
    <div v-if="tool === 'points'" class="grid gap-3 px-4 py-3 sm:grid-cols-2">
      <label class="block">
        <span class="label">Target per trade (points)</span>
        <div class="mt-1 flex items-center gap-2">
          <input v-model.number="points" type="range" min="500" max="1000" step="50" class="w-full accent-gold-400" />
          <span class="num w-14 text-right text-[12px] text-gold-400">{{ points }}</span>
        </div>
      </label>
      <label class="block">
        <span class="label">Trade lot</span>
        <input v-model.number="lot" type="number" min="0.01" step="0.01" class="input mt-1 num" />
      </label>
      <div class="kv"><dt>Point size</dt><dd>{{ spec?.point ?? '—' }}</dd></div>
      <div class="kv"><dt>Contract size</dt><dd>{{ fmt(spec?.contract_size, 0) }}</dd></div>
      <div class="kv"><dt>Price movement</dt><dd>{{ fmt(result?.price_move, spec?.digits ?? 2) }}</dd></div>
      <div class="kv"><dt>Gross profit</dt><dd class="text-up">{{ accountMoney(result?.gross_profit) }}</dd></div>
      <div class="kv"><dt>Commission</dt><dd class="text-down">{{ accountMoney(result?.commission) }}</dd></div>
      <div class="kv"><dt>Net after commission</dt><dd>{{ accountMoney(result?.net_profit) }}</dd></div>
      <div class="kv"><dt>Value / point / lot</dt><dd>{{ accountMoney(result?.value_per_point_per_lot) }}</dd></div>
      <div class="kv"><dt>Spread @ typical</dt><dd class="text-down">{{ accountMoney(result?.spread_cost) }}</dd></div>
      <div class="kv"><dt>Net after known costs</dt><dd class="text-gold-400">{{ accountMoney(result?.net_after_known_costs) }}</dd></div>
    </div>
    <div v-else-if="tool === 'size'" class="space-y-3 px-4 py-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="chip chip-gold">MANUAL · SANDBOX</span>
        <span class="text-[10px] text-muted">ไม่มีการอ่านหรือบันทึกยอดเงินในบัญชี</span>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block">
          <span class="label">ทุนจำลอง ({{ spec?.account_currency || 'สกุลบัญชี' }})</span>
          <input v-model.number="equity" type="number" min="0.01" step="100" class="input mt-1 num" placeholder="กรอกทุนจำลอง" />
        </label>
        <label class="block">
          <span class="label">เสี่ยงต่อไม้ (%)</span>
          <input v-model.number="riskPct" type="number" min="0.01" max="100" step="0.05" class="input mt-1 num" />
        </label>
        <label class="block">
          <span class="label">ระยะ Stop Loss (points)</span>
          <input v-model.number="slPoints" type="number" min="0.01" step="10" class="input mt-1 num" />
        </label>
        <div class="kv"><dt>สเปก / point size</dt><dd>{{ spec?.source || '—' }} · {{ spec?.point ?? '—' }}</dd></div>
      </div>
      <div v-if="positionSize?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-3">
        <div class="kv"><dt>งบเสี่ยง</dt><dd>{{ accountMoney(positionSize.risk_budget) }}</dd></div>
        <div class="kv"><dt>Lot ที่ไม่เกินงบ</dt><dd class="text-gold-300">{{ fmt(positionSize.lot, lotPrecision(positionSize.lot_step)) }}</dd></div>
        <div class="kv"><dt>ขาดทุนประเมินที่ SL*</dt><dd class="text-down">{{ accountMoney(positionSize.estimated_stop_cost) }}</dd></div>
      </div>
      <p v-else-if="positionSize" class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-[10.5px] leading-relaxed text-amber-200">
        {{ positionSize.status === 'no_legal_lot' ? 'ไม่มีขนาด Lot ขั้นต่ำที่อยู่ในงบเสี่ยงนี้' : positionSize.reason }}
        <span v-if="positionSize.estimated_stop_cost != null"> · ขั้นต่ำประเมิน {{ accountMoney(positionSize.estimated_stop_cost) }}</span>
      </p>
      <p class="text-[10px] leading-relaxed text-muted">
        *คำนวณจากสเปก {{ spec?.source || 'ที่ยังไม่ทราบ' }} พร้อม spread ทั่วไปและ commission; ไม่รวม slippage/swap และไม่ใช่คำสั่งซื้อขาย
      </p>
    </div>
    <div v-else-if="tool === 'risk_reward'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label class="block"><span class="label">Side</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">Entry</span><input v-model.number="entry" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Stop Loss</span><input v-model.number="stopLoss" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Take Profit</span><input v-model.number="takeProfit" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Lot</span><input v-model.number="lot" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>Gross R:R</dt><dd>{{ fmt(result.rr_gross, 2) }}R</dd></div>
        <div class="kv"><dt>Net estimate R:R</dt><dd class="text-gold-300">{{ fmt(result.rr_net, 2) }}R</dd></div>
        <div class="kv"><dt>Risk estimate</dt><dd class="text-down">{{ accountMoney(result.risk_amount_estimate) }}</dd></div>
        <div class="kv"><dt>Reward after known costs</dt><dd class="text-up">{{ accountMoney(result.reward_amount_net_estimate) }}</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">สูตร: ระยะ TP ÷ ระยะ SL; Net estimate รวม typical spread และ commission. เป็นค่าประเมิน ไม่ใช่สัญญาณเข้าเทรด</p>
    </div>
    <div v-else-if="tool === 'drawdown'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block"><span class="label">Equity ปัจจุบันแบบจำลอง ({{ spec?.account_currency || 'สกุลบัญชี' }})</span><input v-model.number="currentEquity" type="number" min="0.01" step="100" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Peak Equity แบบจำลอง ({{ spec?.account_currency || 'สกุลบัญชี' }})</span><input v-model.number="peakEquity" type="number" min="0.01" step="100" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>Drawdown</dt><dd class="text-down">{{ fmt(result.drawdown_pct, 2) }}%</dd></div>
        <div class="kv"><dt>Drawdown amount</dt><dd>{{ accountMoney(result.drawdown_amount) }}</dd></div>
        <div class="kv"><dt>ต้องเพิ่มจาก equity ปัจจุบัน</dt><dd>{{ fmt(result.recovery_pct, 2) }}%</dd></div>
        <div class="kv"><dt>จำนวนเงินเพื่อกลับ peak</dt><dd>{{ accountMoney(result.recovery_amount) }}</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">สูตร recovery = (Peak − Equity) ÷ Equity. กรอกค่าจำลองเอง ระบบไม่ดึงยอดจริงในบัญชี</p>
    </div>
    <div v-else-if="tool === 'break_even'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">กำไรต่อไม้ก่อนต้นทุน ({{ spec?.account_currency || 'สกุลเดียวกัน' }})</span><input v-model.number="grossReward" type="number" min="0.01" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">ขาดทุนต่อไม้ก่อนต้นทุน ({{ spec?.account_currency || 'สกุลเดียวกัน' }})</span><input v-model.number="grossLoss" type="number" min="0.01" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">ต้นทุนประมาณต่อไม้ ({{ spec?.account_currency || 'สกุลเดียวกัน' }})</span><input v-model.number="estimatedCost" type="number" min="0" step="0.1" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-3">
        <div class="kv"><dt>กำไรสุทธิสมมติ</dt><dd class="text-up">{{ accountMoney(result.net_reward) }}</dd></div>
        <div class="kv"><dt>ขาดทุนสุทธิสมมติ</dt><dd class="text-down">{{ accountMoney(result.net_loss) }}</dd></div>
        <div class="kv"><dt>Win rate เพื่อคุ้มทุน</dt><dd class="text-gold-300">{{ fmt(result.break_even_win_rate_pct, 2) }}%</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">สูตร = ขาดทุนสุทธิ ÷ (กำไรสุทธิ + ขาดทุนสุทธิ). ใช้สมมติฐานสกุลเดียวกัน; เป็นเส้นคุ้มทุนทางคณิตศาสตร์ ไม่ใช่ผลคาดการณ์</p>
    </div>
    <div v-else-if="tool === 'trading_costs'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label class="block"><span class="label">Side</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">ราคาอ้างอิง swap</span><input v-model.number="entry" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Lot</span><input v-model.number="lot" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">จำนวนคืนที่ถือ</span><input v-model.number="holdingNights" type="number" min="0" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">คืนคิด swap 3 เท่า</span><input v-model.number="tripleSwapNights" type="number" min="0" step="1" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-5">
        <div class="kv"><dt>Spread ทั่วไป</dt><dd>{{ accountMoney(result.spread_cost) }}</dd></div>
        <div class="kv"><dt>Commission ไป-กลับ</dt><dd>{{ accountMoney(result.commission_cost) }}</dd></div>
        <div class="kv"><dt>Swap {{ result.swap_mode }} (ลบ=เสีย)</dt><dd :class="result.swap_amount_signed <= 0 ? 'text-down' : 'text-up'">{{ accountMoney(result.swap_amount_signed) }}</dd></div>
        <div class="kv"><dt>คืนที่คิด swap</dt><dd>{{ result.swap_nights_applied }}</dd></div>
        <div class="kv"><dt>ต้นทุนสุทธิประมาณ</dt><dd class="text-gold-300">{{ accountMoney(result.total_cost_estimate) }}</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">ใช้ swap mode/rate จาก {{ result?.spec_source || spec?.source || 'สเปกสัญลักษณ์' }}; จำนวนคืน 3 เท่าต้องกรอกตามวัน rollover ของโบรกเกอร์เอง. ถ้าสเปกยังไม่ยืนยัน ให้ถือเป็นตัวอย่างเท่านั้น</p>
    </div>
    <div v-else-if="tool === 'atr_volatility'" class="space-y-3 px-4 py-3">
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>ATR 14 · {{ result.timeframe }}</dt><dd>{{ fmt(result.atr14, spec?.digits ?? 2) }} {{ spec?.profit_currency || '' }}</dd></div>
        <div class="kv"><dt>ATR points</dt><dd>{{ fmt(result.atr_points, 1) }}</dd></div>
        <div class="kv"><dt>ATR ต่อราคา</dt><dd>{{ fmt(result.atr_percent, 3) }}%</dd></div>
        <div class="kv"><dt>Regime · ADX</dt><dd>{{ result.regime?.regime || '—' }} · {{ fmt(result.regime?.adx, 1) }}</dd></div>
        <div class="kv"><dt>ATR percentile · M15</dt><dd>{{ fmt(Number(result.regime?.atr_percentile) * 100, 1) }}%</dd></div>
        <div class="kv"><dt>Feed · spec</dt><dd>{{ result.feed }} · {{ result.spec_source }}</dd></div>
        <div class="kv"><dt>อายุ quote</dt><dd>{{ result.quote_age_seconds ?? '—' }}s</dd></div>
        <div class="kv"><dt>แท่ง M5 ปิด UTC</dt><dd class="text-[10px]">{{ result.closed_bar_close_utc }}</dd></div>
      </div>
      <p v-else-if="result" class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">{{ result.reason }} · ไม่แสดงค่า ATR เมื่อข้อมูลตลาดไม่สดหรือแท่งปิดไม่ครบ</p>
      <p class="text-[10px] leading-relaxed text-muted">อ่านจาก Analysis Snapshot เดิม; ATR ใช้แท่ง M5 ที่ปิดแล้ว ส่วน regime/ADX เป็นข้อมูล M15. เป็นข้อมูลวิเคราะห์ ไม่ใช่แผนหรือคำสั่งซื้อขาย</p>
    </div>
    <div v-else-if="tool === 'support_resistance'" class="space-y-3 px-4 py-3">
      <div v-if="result?.status === 'ready'" class="grid gap-3 md:grid-cols-2">
        <div class="rounded-lg border border-up/25 bg-up/5 p-3">
          <h3 class="mb-2 text-xs font-semibold text-up">Support ใกล้ราคา · {{ fmt(result.price, spec?.digits ?? 2) }}</h3>
          <p v-if="!result.supports.length" class="text-xs text-muted">ไม่พบ zone สำหรับแสดง</p>
          <div v-for="zone in result.supports" :key="zone.id" class="mb-2 grid grid-cols-[1fr_auto] gap-2 border-b border-ink-700/70 pb-2 last:mb-0 last:border-0 last:pb-0">
            <span class="text-xs">{{ fmt(zone.low, spec?.digits ?? 2) }}–{{ fmt(zone.high, spec?.digits ?? 2) }} · {{ zone.status }}</span>
            <span class="text-right text-[10px] text-muted">{{ zone.quality }} · {{ fmt(zone.distance_atr, 2) }} ATR</span>
          </div>
        </div>
        <div class="rounded-lg border border-down/25 bg-down/5 p-3">
          <h3 class="mb-2 text-xs font-semibold text-down">Resistance</h3>
          <p v-if="!result.resistances.length" class="text-xs text-muted">ไม่พบ zone สำหรับแสดง</p>
          <div v-for="zone in result.resistances" :key="zone.id" class="mb-2 grid grid-cols-[1fr_auto] gap-2 border-b border-ink-700/70 pb-2 last:mb-0 last:border-0 last:pb-0">
            <span class="text-xs">{{ fmt(zone.low, spec?.digits ?? 2) }}–{{ fmt(zone.high, spec?.digits ?? 2) }} · {{ zone.status }}</span>
            <span class="text-right text-[10px] text-muted">{{ zone.quality }} · {{ fmt(zone.distance_atr, 2) }} ATR</span>
          </div>
        </div>
        <div class="kv"><dt>Feed · timeframe</dt><dd>{{ result.feed }} · {{ result.timeframe }}</dd></div>
        <div class="kv"><dt>แท่งปิด UTC</dt><dd class="text-[10px]">{{ result.closed_bar_close_utc }}</dd></div>
      </div>
      <p v-else-if="result" class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">{{ result.reason }} · ซ่อนโซนจนกว่าข้อมูลตลาดจะผ่าน freshness check</p>
      <p class="text-[10px] leading-relaxed text-muted">แสดง zones จาก Analysis Service เดิม เรียงตามระยะ ATR และคงสถานะ candidate/confirmed กับ quality ไว้ครบ. ไม่คำนวณโซนซ้ำและไม่ใช่คำสั่ง</p>
    </div>
    <div v-else-if="tool === 'point_tick'" class="space-y-3 px-4 py-3">
      <label class="block max-w-sm"><span class="label">ระยะราคา (price units)</span><input v-model.number="priceDelta" type="number" step="0.01" class="input mt-1 num" /></label>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-3">
        <div class="kv"><dt>Points</dt><dd>{{ fmt(result.points, 4) }}</dd></div>
        <div class="kv"><dt>จำนวน Tick แบบคำนวณ</dt><dd>{{ fmt(result.exact_ticks, 4) }}</dd></div>
        <div class="kv"><dt>จำนวน Tick ที่ถูกต้อง</dt><dd>{{ result.tick_aligned ? result.legal_tick_count : 'ไม่ตรง tick size' }}</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">Points = ระยะราคา ÷ Point; Ticks = ระยะราคา ÷ Tick Size. Point และ Tick อาจไม่เท่ากัน</p>
    </div>
    <div v-else-if="tool === 'profit_loss'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">Side</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">Entry</span><input v-model.number="entry" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Exit สมมติ</span><input v-model.number="exitPrice" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Lot</span><input v-model.number="lot" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>ผลต่าง</dt><dd>{{ fmt(result.points, 1) }} points</dd></div>
        <div class="kv"><dt>Gross P&amp;L</dt><dd :class="result.gross_profit >= 0 ? 'text-up' : 'text-down'">{{ accountMoney(result.gross_profit) }}</dd></div>
        <div class="kv"><dt>Known costs</dt><dd class="text-down">{{ accountMoney((result.commission || 0) + (result.spread_cost || 0)) }}</dd></div>
        <div class="kv"><dt>Net estimate</dt><dd :class="result.net_after_known_costs >= 0 ? 'text-up' : 'text-down'">{{ accountMoney(result.net_after_known_costs) }}</dd></div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">คำนวณแบบจำลองจากราคาที่กรอกและสเปกสัญลักษณ์ ไม่อ่าน position หรือยอดจริงจากบัญชี</p>
    </div>
    <div v-else-if="tool === 'auto_sl_tp'" class="space-y-3 px-4 py-3">
      <div class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-[10.5px] leading-relaxed text-amber-200">
        ตัวอย่างแผนแบบอ่านอย่างเดียว · ใช้ทุนจำลองที่กรอกเองและแท่ง M5 ที่ปิดแล้ว · ไม่อ่านยอดบัญชี ไม่บันทึกโปรไฟล์ และไม่ส่งคำสั่ง
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">ฝั่ง</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">ราคาเข้า (กรอกเอง)</span><input v-model.number="previewEntry" type="number" min="0.000001" step="0.01" class="input mt-1 num" placeholder="กรอกราคาเข้า" /></label>
        <label class="block"><span class="label">ทุนจำลอง ({{ spec?.account_currency || 'สกุลบัญชี' }})</span><input v-model.number="manualEquity" type="number" min="0.01" step="100" class="input mt-1 num" placeholder="กรอกทุนจำลอง" /></label>
        <label class="block"><span class="label">งบเสี่ยง (%)</span><input v-model.number="riskPct" type="number" min="0.01" max="100" step="0.05" class="input mt-1 num" /></label>
        <label class="block"><span class="label">วิธีวาง SL</span><select v-model="stopMode" class="input mt-1"><option value="atr_structure">ATR + Structure</option><option value="atr">ATR</option><option value="structure">Structure</option><option value="fixed">Fixed points</option></select></label>
        <label v-if="stopMode === 'fixed'" class="block"><span class="label">ระยะ SL (points)</span><input v-model.number="fixedSlPoints" type="number" min="0.01" step="10" class="input mt-1 num" /></label>
        <label v-if="stopMode === 'atr' || stopMode === 'atr_structure'" class="block"><span class="label">ATR multiplier</span><input v-model.number="atrMultiplier" type="number" min="0.01" step="0.1" class="input mt-1 num" /></label>
        <label v-if="stopMode === 'structure' || stopMode === 'atr_structure'" class="block"><span class="label">Structure buffer (ATR)</span><input v-model.number="structureBufferAtr" type="number" min="0" step="0.05" class="input mt-1 num" /></label>
        <label v-if="stopMode === 'structure' || stopMode === 'atr_structure'" class="block"><span class="label">Swing lookback (M5 bars)</span><input v-model.number="swingLookbackBars" type="number" min="1" max="100" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">วิธีตั้ง TP</span><select v-model="previewTargetMode" class="input mt-1"><option value="adaptive">Adaptive ตาม ATR/Zone</option><option value="fixed">Fixed ladder</option><option value="single_r">เป้าหมายเดียวตาม R</option></select></label>
        <label v-if="previewTargetMode === 'single_r'" class="block"><span class="label">เป้าหมาย (R)</span><input v-model.number="targetR" type="number" min="0.1" max="10" step="0.1" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready' && result.plan" class="space-y-2 rounded-lg border border-up/30 bg-up/5 p-3">
        <div class="flex flex-wrap items-center justify-between gap-2"><strong class="text-sm text-up">คำนวณแผนได้ · ยังไม่ใช่การอนุมัติเทรด</strong><span class="chip chip-gold">manual preview</span></div>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div class="kv"><dt>Entry · {{ side }}</dt><dd>{{ fmt(result.plan.entry, spec?.digits ?? 2) }}</dd></div>
          <div class="kv"><dt>Stop Loss</dt><dd class="text-down">{{ fmt(result.plan.sl, spec?.digits ?? 2) }} · {{ fmt(result.plan.sl_points, 1) }} pts</dd></div>
          <div class="kv"><dt>Take Profit 1</dt><dd class="text-up">{{ fmt(result.plan.tp1, spec?.digits ?? 2) }} · {{ fmt(result.plan.tp_points?.[0], 1) }} pts</dd></div>
          <div class="kv"><dt>TP2 · TP3</dt><dd>{{ fmt(result.plan.tp2, spec?.digits ?? 2) }} · {{ fmt(result.plan.tp3, spec?.digits ?? 2) }}</dd></div>
          <div class="kv"><dt>Lot ประเมิน</dt><dd>{{ fmt(result.plan.lot, lotPrecision(spec?.lot_step)) }}</dd></div>
          <div class="kv"><dt>Risk estimate</dt><dd class="text-down">{{ accountMoney(result.plan.risk_amount) }} · {{ fmt(result.plan.risk_pct, 2) }}%</dd></div>
          <div class="kv"><dt>Net Reward / Risk</dt><dd>{{ fmt(result.plan.reward_risk_net, 2) }}R</dd></div>
          <div class="kv"><dt>ATR(14) ปิด M5</dt><dd>{{ fmt(result.atr_points, 1) }} points</dd></div>
        </div>
        <ul v-if="result.notes?.length" class="space-y-1 text-[10px] leading-relaxed text-muted"><li v-for="note in result.notes" :key="note">{{ note }}</li></ul>
      </div>
      <div v-else-if="result" class="rounded-lg border border-amber-400/30 bg-amber-400/5 p-3 text-xs text-amber-200">
        <strong>{{ result.status === 'blocked' ? 'แผนถูกบล็อกโดยเงื่อนไข Risk/Planner' : result.status === 'invalid_input' ? 'ตรวจข้อมูลที่กรอก' : 'ยังคำนวณไม่ได้' }}</strong>
        <ul class="mt-1 space-y-1"><li v-for="(reason, index) in result.blockers || []" :key="index">{{ reason }}</li></ul>
      </div>
      <p class="text-[10px] leading-relaxed text-muted">ใช้ TradePlanner เดิม ตรวจ spread/spec, ATR และ swing ที่ยืนยันแล้ว; หากข้อมูลไม่สดหรือระยะ SL/TP ไม่ผ่านกฎ จะซ่อนแผนหรือแสดงเหตุผลบล็อก. ไม่มีการอ่าน equity จาก MT5 และไม่มีปุ่มส่งคำสั่งในเครื่องมือนี้</p>
    </div>
    <div v-else-if="tool === 'margin'" class="space-y-3 px-4 py-3">
      <div class="rounded-lg border border-ink-700 bg-ink-900/60 p-3 text-[10.5px] leading-relaxed text-muted">ใช้ MT5 order_calc_margin และ free margin ของบัญชีที่ยืนยัน ownership แล้วเท่านั้น หากไม่มี terminal/quote/spec สด จะแสดงว่าไม่พร้อมโดยไม่เดาค่า</div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">Side</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">Volume (lot)</span><input v-model.number="lot" type="number" min="0.001" step="0.01" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'sufficient' || result?.status === 'insufficient_margin'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>ผลตรวจ</dt><dd :class="result.status === 'sufficient' ? 'text-up' : 'text-down'">{{ result.status === 'sufficient' ? 'มาร์จินคงเหลือพอ' : 'มาร์จินไม่พอ' }}</dd></div>
        <div class="kv"><dt>ราคาที่ประเมิน</dt><dd>{{ fmt(result.price, spec?.digits ?? 2) }} · {{ result.side }}</dd></div>
        <div class="kv"><dt>Required margin</dt><dd>{{ fmt(result.required_margin, 2) }} {{ result.currency }}</dd></div>
        <div class="kv"><dt>Free after estimate</dt><dd>{{ fmt(result.projected_free_margin, 2) }} {{ result.currency }}</dd></div>
        <div class="kv"><dt>Leverage</dt><dd>1:{{ result.leverage }}</dd></div>
        <div class="kv"><dt>Quote age</dt><dd>{{ fmt(result.quote_age_seconds, 1) }}s</dd></div>
      </div>
      <p v-else-if="result" class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">{{ result.reason || 'ไม่มีผลคำนวณจาก MT5' }}</p>
      <p class="text-[10px] leading-relaxed text-muted">เป็นการอ่านค่าเท่านั้น; ไม่ได้เรียก order_check/order_send และไม่ใช่การรับประกันว่าโบรกเกอร์จะรับออเดอร์</p>
    </div>
    <div v-else-if="tool === 'confirmation_100pt'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-3">
        <label class="block"><span class="label">Side</span><select v-model="side" class="input mt-1"><option>BUY</option><option>SELL</option></select></label>
        <label class="block"><span class="label">ราคาอ้างอิง bid/ask</span><input v-model.number="confirmationReference" type="number" min="0.000001" step="0.01" class="input mt-1 num" placeholder="กรอกราคาอ้างอิง" /></label>
      </div>
      <div v-if="result?.status === 'preview_match' || result?.status === 'waiting'" class="space-y-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3">
        <div class="flex flex-wrap items-center justify-between gap-2"><strong :class="result.status === 'preview_match' ? 'text-up' : 'text-gold-300'">{{ result.status === 'preview_match' ? 'เข้าเงื่อนไข preview' : 'ยังรอยืนยัน' }}</strong><span class="chip chip-gold">ไม่ใช่ confirmation ที่บันทึกไว้</span></div>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div class="kv"><dt>ราคาเป้าหมาย</dt><dd>{{ fmt(result.target_price, spec?.digits ?? 2) }}</dd></div>
          <div class="kv"><dt>M1 close progress</dt><dd>{{ fmt(result.closed_m1_progress_points, 1) }} / {{ fmt(result.threshold_points, 0) }} pts</dd></div>
          <div class="kv"><dt>ระยะคงเหลือ</dt><dd>{{ fmt(result.remaining_points, 1) }} pts</dd></div>
          <div class="kv"><dt>M5 aligned · chase</dt><dd>{{ result.m5_aligned ? 'yes' : 'no' }} · {{ fmt(result.chase_points, 1) }} pts</dd></div>
        </div>
        <ul v-if="result.blockers?.length" class="text-[10px] text-amber-200"><li v-for="reason in result.blockers" :key="reason">{{ reason }}</li></ul>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.blockers?.join(' · ') || result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">ใช้ราคาตลาดและแท่งปิด M1/M5 ล่าสุดพร้อมสูตรเดียวกับ confirmation gate; ไม่อ่านหรือเปลี่ยน candidate ของบัญชี และ 100 points ไม่ได้อนุมัติคำสั่ง</p>
    </div>
    <div v-else-if="tool === 'scenario'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">ทุนจำลอง ({{ spec?.account_currency || 'สกุลที่สมมติ' }})</span><input v-model.number="manualEquity" type="number" min="0.01" step="100" class="input mt-1 num" placeholder="กรอกทุนเอง" /></label>
        <label class="block"><span class="label">Risk ต่อไม้ (%)</span><input v-model.number="riskPct" type="number" min="0.01" max="100" step="0.05" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Win rate สมมติ (%)</span><input v-model.number="scenarioWinRate" type="number" min="0" max="100" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Reward / Risk</span><input v-model.number="scenarioRewardRisk" type="number" min="0.01" step="0.1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">จำนวนไม้</span><input v-model.number="scenarioTrades" type="number" min="1" max="1000" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Cost ต่อไม้ (สกุลเดียวกัน)</span><input v-model.number="scenarioCost" type="number" min="0" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">จำนวน simulation</span><input v-model.number="scenarioRuns" type="number" min="50" max="1000" step="50" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Seed</span><input v-model.number="scenarioSeed" type="number" step="1" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>ผลปลายทาง P10</dt><dd>{{ fmt(result.ending_equity_p10, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>Median</dt><dd>{{ fmt(result.ending_equity_median, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>P90</dt><dd>{{ fmt(result.ending_equity_p90, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>Expectancy / ไม้*</dt><dd>{{ fmt(result.expectancy_per_trade_at_start, 2) }} หน่วยเงิน · {{ fmt(result.expectancy_pct_of_starting_equity, 3) }}%</dd></div><div class="kv"><dt>Max DD P90</dt><dd class="text-down">{{ fmt(result.max_drawdown_p90_pct, 2) }}%</dd></div><div class="kv"><dt>Longest losing streak</dt><dd>{{ result.longest_losing_streak_max }} ไม้</dd></div>
      </div><p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">สุ่มผลตาม assumption และ seed ที่กรอกเพื่อเรียนรู้ผลของ risk/cost; *expectancy เป็นค่าเฉลี่ยเชิงคณิตศาสตร์ต่อไม้เมื่อใช้ทุนเริ่มต้นเท่านั้น. ไม่ใช้ข้อมูลย้อนหลัง ไม่ใช่ backtest หรือการคาดการณ์</p>
    </div>
    <div v-else-if="tool === 'capital_growth'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block"><span class="label">ทุนเริ่มต้น</span><input v-model.number="manualEquity" type="number" min="0.01" step="100" class="input mt-1 num" placeholder="กรอกทุนเอง" /></label>
        <label class="block"><span class="label">Low return / period (%)</span><input v-model.number="growthLow" type="number" step="0.1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Base return / period (%)</span><input v-model.number="growthBase" type="number" step="0.1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">High return / period (%)</span><input v-model.number="growthHigh" type="number" step="0.1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">จำนวน period</span><input v-model.number="growthPeriods" type="number" min="1" max="1000" step="1" class="input mt-1 num" /></label>
        <label class="block"><span class="label">Risk ต่อไม้ (%)</span><input v-model.number="riskPct" type="number" min="0" max="100" step="0.05" class="input mt-1 num" /></label>
        <label class="block"><span class="label">แพ้ติดกัน (สมมติ)</span><input v-model.number="growthLossStreak" type="number" min="0" max="1000" step="1" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4">
        <div class="kv"><dt>Low case</dt><dd>{{ fmt(result.low_case, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>Base case</dt><dd>{{ fmt(result.base_case, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>High case</dt><dd>{{ fmt(result.high_case, 2) }} หน่วยเงิน</dd></div><div class="kv"><dt>หลังแพ้ติดกัน · DD</dt><dd class="text-down">{{ fmt(result.after_assumed_losing_streak, 2) }} หน่วยเงิน · {{ fmt(result.losing_streak_drawdown_pct, 2) }}%</dd></div>
      </div><p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">ทุกค่า return เป็นสมมติฐานที่กรอกเอง; ไม่มีการประเมินผลตอบแทนในอนาคต</p>
    </div>
    <div v-else-if="tool === 'currency_convert'" class="space-y-3 px-4 py-3">
      <div class="grid gap-3 sm:grid-cols-3">
        <label class="block"><span class="label">จำนวนเงิน</span><input v-model.number="fxAmount" type="number" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">จากสกุลเงิน</span><input v-model="fromCurrency" maxlength="3" class="input mt-1 uppercase" /></label>
        <label class="block"><span class="label">เป็นสกุลเงิน</span><input v-model="toCurrency" maxlength="3" class="input mt-1 uppercase" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-2 lg:grid-cols-4"><div class="kv"><dt>ผลแปลง</dt><dd>{{ fmt(result.converted_amount, 2) }} {{ result.to_currency }}</dd></div><div class="kv"><dt>FX rate</dt><dd>{{ fmt(result.rate, 6) }}</dd></div><div class="kv"><dt>Source pair</dt><dd>{{ result.rate_pair || 'identity' }}</dd></div><div class="kv"><dt>Captured UTC</dt><dd>{{ result.captured_at ? new Date(result.captured_at * 1000).toISOString() : '—' }}</dd></div></div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason }}</p>
      <p class="text-[10px] leading-relaxed text-muted">ใช้ FX ticker สดที่ feed นี้มีให้เท่านั้น; ไม่ใช้ USD/THB หรืออัตราคงที่แทนข้อมูลที่ขาด</p>
    </div>
    <div v-else-if="tool === 'trade_review_whatif'" class="space-y-3 px-4 py-3">
      <div class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-[10px] leading-relaxed text-amber-200">เลือกไม้ปิดแล้วจากบัญชีที่กำลังใช้งาน ข้อมูลจริงและสมมติฐาน What-if จะแสดงคนละส่วน และไม่แก้ประวัติ</div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <label class="block lg:col-span-2"><span class="label">ไม้ปิดแล้ว · บัญชีที่เลือก</span><select v-model="tradeTicket" class="input mt-1" aria-label="Closed trade for review"><option value="">เลือกไม้ที่ปิดแล้ว</option><option v-for="trade in availableTrades" :key="trade.ticket" :value="trade.ticket">{{ trade.symbol }} · {{ trade.direction === 'up' ? 'BUY' : 'SELL' }} · #{{ trade.ticket }} · {{ money(trade.pnl) }}</option></select></label>
        <button type="button" class="btn self-end py-1.5" :disabled="tradeListLoading" @click="refreshTradeList">{{ tradeListLoading ? 'กำลังโหลด…' : 'รีเฟรชประวัติ' }}</button>
        <label class="block"><span class="label">Entry สมมติ</span><input v-model.number="whatifEntry" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">SL สมมติ</span><input v-model.number="whatifStop" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
        <label class="block"><span class="label">TP สมมติ</span><input v-model.number="whatifTarget" type="number" min="0.000001" step="0.01" class="input mt-1 num" /></label>
      </div>
      <div v-if="result?.status === 'ready'" class="space-y-3">
        <div class="rounded-lg border border-ink-700 p-3">
          <div class="flex flex-wrap items-center justify-between gap-2"><strong class="text-xs">ผลจริงที่บันทึก · {{ result.actual.ticket }}</strong><span class="chip">{{ result.actual.currency }} · account scoped</span></div>
          <div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div class="kv"><dt>Entry → Exit</dt><dd>{{ fmt(result.actual.entry, spec?.digits ?? 2) }} → {{ fmt(result.actual.exit, spec?.digits ?? 2) }}</dd></div>
            <div class="kv"><dt>Net P&amp;L จริง</dt><dd :class="result.actual.net_pnl >= 0 ? 'text-up' : 'text-down'">{{ fmt(result.actual.net_pnl, 2) }} {{ result.actual.currency }}</dd></div>
            <div class="kv"><dt>ต้นทุน · Swap</dt><dd>{{ fmt(result.actual.costs, 2) }} · {{ fmt(result.actual.swap, 2) }} {{ result.actual.currency }}</dd></div>
            <div class="kv"><dt>R จริง</dt><dd>{{ fmt(result.actual.r_multiple, 2) }}R</dd></div>
          </div>
        </div>
        <div class="rounded-lg border border-gold-400/25 bg-gold-400/5 p-3">
          <strong class="text-xs text-gold-300">What-if จากสมมติฐานที่กรอก</strong>
          <div class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <div class="kv"><dt>Net R:R โดยประมาณ</dt><dd>{{ result.whatif.risk_reward.status === 'ready' ? `${fmt(result.whatif.risk_reward.rr_net, 2)}R` : result.whatif.risk_reward.reason }}</dd></div>
            <div class="kv"><dt>Net ถ้าปิดที่ SL*</dt><dd :class="(result.whatif.at_stop?.net_after_known_costs || 0) >= 0 ? 'text-up' : 'text-down'">{{ result.whatif.at_stop?.status === 'ready' ? `${fmt(result.whatif.at_stop.net_after_known_costs, 2)} ${result.actual.currency}` : 'ยังคำนวณไม่ได้' }}</dd></div>
            <div class="kv"><dt>Net ถ้าปิดที่ TP*</dt><dd :class="(result.whatif.at_target?.net_after_known_costs || 0) >= 0 ? 'text-up' : 'text-down'">{{ result.whatif.at_target?.status === 'ready' ? `${fmt(result.whatif.at_target.net_after_known_costs, 2)} ${result.actual.currency}` : 'ยังคำนวณไม่ได้' }}</dd></div>
            <div class="kv"><dt>Lot สมมติ</dt><dd>{{ fmt(result.whatif.volume, lotPrecision(spec?.lot_step)) }}</dd></div>
          </div>
          <p v-for="limitation in result.limitations" :key="limitation" class="mt-2 text-[10px] leading-relaxed text-muted">{{ limitation }}</p>
        </div>
      </div>
      <p v-else-if="result" class="text-xs text-amber-300">{{ result.reason || result.status }}</p>
      <p class="text-[10px] leading-relaxed text-muted">*What-if หัก typical spread/commission จากสเปกที่เลือก ไม่ใช้ต้นทุนจริงของไม้เดิม และไม่จำลองลำดับแท่งว่า SL หรือ TP จะถูกชนก่อน</p>
    </div>
    <div v-if="['scenario', 'capital_growth'].includes(tool)" class="border-t border-ink-700/60 px-4 py-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="block min-w-[180px] flex-1"><span class="label">ชื่อสมมติฐานที่บันทึก</span><input v-model="scenarioName" maxlength="64" class="input mt-1" placeholder="เช่น ทุน 10k · Risk 0.5%" /></label>
        <button type="button" class="btn btn-gold py-1.5" :disabled="scenarioSaving || !scenarioName.trim()" @click="saveScenario">{{ scenarioSaving ? 'กำลังบันทึก…' : 'บันทึกค่าที่กรอก' }}</button>
        <label v-if="savedScenarios.length" class="block min-w-[180px] flex-1"><span class="label">โหลดค่าที่บันทึกไว้</span><select v-model="selectedSavedId" class="input mt-1"><option value="">เลือกสมมติฐาน</option><option v-for="saved in savedScenarios" :key="saved.id" :value="saved.id">{{ saved.name }} · {{ saved.tool }}</option></select></label>
        <button v-if="selectedSavedId" type="button" class="btn py-1.5" @click="applySavedScenario">โหลด</button>
        <button v-if="selectedSavedId" type="button" class="btn btn-danger py-1.5" @click="deleteScenario">ลบ</button>
        <button type="button" class="btn py-1.5" @click="refreshSavedScenarios">รีเฟรช</button>
      </div>
      <p v-if="scenarioMessage" class="mt-2 text-[10px]" :class="scenarioError ? 'text-down' : 'text-up'">{{ scenarioMessage }}</p>
      <p class="mt-2 text-[10px] leading-relaxed text-muted">เก็บเฉพาะตัวเลขสมมติของผู้ใช้นี้ ไม่เก็บยอดบัญชี, positions หรือ broker credentials · สูงสุด 100 รายการต่อผู้ใช้</p>
    </div>
    <p v-if="result?.valuation_valid === false" class="border-t border-amber-400/30 px-4 py-2 text-[10px] leading-relaxed text-amber-300">
      สเปกหรืออัตราแปลงสกุลเงินยังไม่ครบ จึงไม่แสดงยอดกำไร/ขาดทุนเป็นตัวเลข
    </p>
    <p v-if="tool === 'points' || tool === 'size'" class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
      ตัวอย่าง: XAUUSD ที่ point = 0.01 → 500 points = $5.00, 750 = $7.50, 1,000 = $10.00 ต่อราคา
      แต่ถ้า point = 0.001 ระยะ 500 points จะเหลือเพียง $0.50 ของการเคลื่อนไหวราคา
      Net after known costs หัก typical spread และ commission แล้ว; ยังไม่รวม swap และ slippage
    </p>
    <p v-if="error" class="px-4 pb-3 text-[10.5px] text-down">{{ error }}</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../lib/api'
import { projectAtrVolatility, projectSupportResistance } from '../lib/calculatorAnalysis'
import { fmt, money } from '../lib/format'
import { calculatorCsv, calculatorJson, calculatorPrintDocument } from '../lib/calculatorExport'
import { lotPrecision } from '../lib/lotPrecision'
import { state } from '../lib/store'

const points = ref(750)
const lot = ref(0.01)
const tool = ref('points')
const equity = ref(null)
const riskPct = ref(0.5)
const manualEquity = ref(null)
const slPoints = ref(400)
const side = ref('BUY')
const confirmationReference = ref(null)
const entry = ref(2000)
const previewEntry = ref(null)
const stopLoss = ref(1990)
const takeProfit = ref(2020)
const exitPrice = ref(2010)
const grossReward = ref(100)
const grossLoss = ref(100)
const estimatedCost = ref(7)
const holdingNights = ref(3)
const tripleSwapNights = ref(1)
const currentEquity = ref(9000)
const peakEquity = ref(10000)
const priceDelta = ref(5)
const stopMode = ref('atr_structure')
const fixedSlPoints = ref(500)
const atrMultiplier = ref(1.5)
const structureBufferAtr = ref(0.2)
const swingLookbackBars = ref(10)
const previewTargetMode = ref('adaptive')
const targetR = ref(2)
const scenarioWinRate = ref(50)
const scenarioRewardRisk = ref(2)
const scenarioTrades = ref(50)
const scenarioCost = ref(0)
const scenarioRuns = ref(300)
const scenarioSeed = ref(7)
const growthLow = ref(-2)
const growthBase = ref(1)
const growthHigh = ref(4)
const growthPeriods = ref(12)
const growthLossStreak = ref(5)
const fxAmount = ref(1000)
const fromCurrency = ref('USD')
const toCurrency = ref('THB')
const learningVisible = ref(false)
const lessons = [
  { id: 'risk', title: '1 · Risk ต่อไม้', body: 'กำหนดเงินที่ยอมเสียได้ก่อนเปิดไม้ แล้วคำนวณขนาดสถานะจากระยะ Stop Loss อย่าขยับ SL ให้แคบลงเพียงเพื่อเพิ่ม lot', example: 'ตัวอย่าง: ทุนจำลอง 10,000 และ risk 0.5% หมายถึงงบขาดทุนตามแผน 50 หน่วยเงิน ก่อนต้นทุน/ความคลาดเคลื่อน', question: 'ถ้าต้องการลดความเสี่ยงเมื่อ SL กว้างขึ้น ควรทำอย่างไร?', answers: ['ลด lot ตามงบความเสี่ยง', 'ขยับ SL ให้แคบลงเสมอ'], correct: 0 },
  { id: 'rr', title: '2 · Risk / Reward', body: 'R:R เปรียบเทียบระยะเป้าหมายกับระยะ Stop Loss โดยค่า gross ไม่รวมต้นทุน ส่วนค่า net หักต้นทุนที่ทราบตามแบบจำลอง', example: 'ความเสี่ยง 10 จุดและเป้าหมาย 20 จุด มี gross R:R = 2:1 ก่อนต้นทุน', question: 'Gross R:R รวม spread และ commission แล้วหรือยัง?', answers: ['รวมแล้วทุกกรณี', 'ยัง ต้องดู net estimate แยก'], correct: 1 },
  { id: 'costs', title: '3 · ต้นทุน', body: 'Spread, commission, swap และ slippage ลดผลสุทธิได้ ตัวเลขประมาณการจะเชื่อถือได้เท่าข้อมูลที่ป้อนหรือสเปกที่มี', example: 'ต้นทุนจำลอง 7 หน่วยจากกำไรขั้นต้น 20 เหลือสุทธิประมาณ 13 หน่วย', question: 'ต้นทุนที่ไม่ได้บันทึกควรมองอย่างไร?', answers: ['ถือว่าเป็นศูนย์แน่นอน', 'เป็นความไม่แน่นอนที่อาจทำให้สุทธิต่างออกไป'], correct: 1 },
  { id: 'dd', title: '4 · Drawdown', body: 'Drawdown วัดการลดลงจากจุดทุนสูงสุด การกลับไปทุนเดิมต้องใช้เปอร์เซ็นต์กำไรมากกว่าเปอร์เซ็นต์ที่ขาดทุน', example: 'ลดจาก 100 เหลือ 90 คือ DD 10%; จาก 90 ต้องเพิ่ม 11.11% เพื่อกลับถึง 100', question: 'เสีย 10% จากจุดสูงสุด ต้องทำกำไรเท่าไรจากทุนที่เหลือเพื่อคืนทุน?', answers: ['10%', 'ประมาณ 11.11%'], correct: 1 },
  { id: 'simulation', title: '5 · Simulation ไม่ใช่ Backtest', body: 'Monte Carlo ใช้สมมติฐานที่ระบุเพื่อแสดงการกระจายผลที่เป็นไปได้ ไม่ได้พิสูจน์ว่ากลยุทธ์ทำกำไรได้จริง', example: 'เปลี่ยน win rate, R:R, cost หรือจำนวนไม้ จะเปลี่ยนผลจำลอง แม้ไม่มีข้อมูลแท่งราคา', question: 'ผล Monte Carlo ยืนยันผลจริงในอนาคตหรือไม่?', answers: ['ยืนยันได้', 'ไม่ได้ เป็นภาพจำลองตามสมมติฐาน'], correct: 1 },
]
const selectedLessonId = ref('risk')
const selectedLesson = computed(() => lessons.find((lesson) => lesson.id === selectedLessonId.value) || lessons[0])
const quizChoice = ref(null)
const quizFeedback = ref('')
const quizCorrect = ref(false)
const scenarioName = ref('')
const savedScenarios = ref([])
const savedScenariosLoaded = ref(false)
const selectedSavedId = ref('')
const scenarioSaving = ref(false)
const scenarioMessage = ref('')
const scenarioError = ref(false)
const availableTrades = ref([])
const tradeListLoaded = ref(false)
const tradeListLoading = ref(false)
const tradeTicket = ref('')
const whatifEntry = ref(null)
const whatifStop = ref(null)
const whatifTarget = ref(null)
const spec = ref(null)
const result = ref(null)
const positionSize = ref(null)
const provenance = ref(null)
const copyPayload = ref(null)
const error = ref('')
let requestId = 0
let loadTimer = null

const symbol = computed(() => state.symbol)
const isAnalysisTool = computed(() => ['atr_volatility', 'support_resistance'].includes(tool.value))
const isPlanPreviewTool = computed(() => tool.value === 'auto_sl_tp')
const isBrokerReadTool = computed(() => ['margin', 'confirmation_100pt'].includes(tool.value))
const isReadOnlyTool = computed(() => isAnalysisTool.value || isPlanPreviewTool.value || isBrokerReadTool.value)
const sourceLabel = computed(() => isAnalysisTool.value
  ? `Analysis snapshot · ${spec.value?.source || '—'}`
  : isPlanPreviewTool.value ? 'Manual SL/TP preview · read only'
  : isBrokerReadTool.value ? `${tool.value === 'margin' ? 'MT5 margin' : '100-point'} · read only`
  : spec.value?.source === 'broker' ? 'Broker symbol spec' : 'Declared symbol spec')
const sourceContext = computed(() => isAnalysisTool.value
  ? `feed ${provenance.value?.market_feed || '—'}`
  : isPlanPreviewTool.value ? `fresh ${provenance.value?.market_feed || 'market'} · manual equity`
  : isBrokerReadTool.value ? `${provenance.value?.adapter || provenance.value?.market_feed || 'fresh feed'} · read only`
  : `${spec.value?.account_currency || '—'} · FX ${spec.value?.rate_source || '—'}`)

function checkLessonAnswer() {
  if (quizChoice.value === null) {
    quizCorrect.value = false
    quizFeedback.value = 'เลือกคำตอบก่อนตรวจ'
    return
  }
  quizCorrect.value = quizChoice.value === selectedLesson.value.correct
  quizFeedback.value = quizCorrect.value ? 'ถูกต้อง' : 'ยังไม่ถูก ลองทบทวนคำอธิบายด้านซ้าย'
}

function manualScenarioInputs() {
  let inputs
  if (tool.value === 'scenario') inputs = {
    manual_equity: manualEquity.value, risk_pct: riskPct.value,
    win_rate_pct: scenarioWinRate.value, reward_risk: scenarioRewardRisk.value,
    trades: scenarioTrades.value, cost_per_trade: scenarioCost.value,
    runs: scenarioRuns.value, seed: scenarioSeed.value,
  }
  else if (tool.value === 'capital_growth') inputs = {
    manual_equity: manualEquity.value, low_return_pct: growthLow.value,
    base_return_pct: growthBase.value, high_return_pct: growthHigh.value,
    periods: growthPeriods.value, risk_pct: riskPct.value, loss_streak: growthLossStreak.value,
  }
  else return null
  return Object.fromEntries(Object.entries(inputs).filter(([, value]) =>
    value !== null && value !== '' && Number.isFinite(Number(value))))
}

async function refreshSavedScenarios() {
  try {
    const data = await api.get('/api/risk/calculator/scenarios')
    savedScenarios.value = data.scenarios || []
    savedScenariosLoaded.value = true
    if (!savedScenarios.value.some((item) => item.id === selectedSavedId.value)) selectedSavedId.value = ''
  } catch (err) {
    savedScenariosLoaded.value = false
    scenarioError.value = true
    scenarioMessage.value = err.message || 'โหลดสมมติฐานไม่ได้'
  }
}

async function saveScenario() {
  const inputs = manualScenarioInputs()
  if (!inputs || !scenarioName.value.trim()) return
  scenarioSaving.value = true
  scenarioMessage.value = ''
  scenarioError.value = false
  try {
    const data = await api.post('/api/risk/calculator/scenarios', {
      name: scenarioName.value.trim(), tool: tool.value, inputs,
    })
    await refreshSavedScenarios()
    selectedSavedId.value = data.scenario.id
    scenarioMessage.value = 'บันทึกสมมติฐานแล้ว'
  } catch (err) {
    scenarioError.value = true
    scenarioMessage.value = err.message || 'บันทึกไม่ได้'
  } finally {
    scenarioSaving.value = false
  }
}

function applySavedScenario() {
  const item = savedScenarios.value.find((saved) => saved.id === selectedSavedId.value)
  if (!item) return
  tool.value = item.tool
  Object.entries(item.inputs || {}).forEach(([key, value]) => {
    const targets = {
      manual_equity: manualEquity, risk_pct: riskPct, win_rate_pct: scenarioWinRate,
      reward_risk: scenarioRewardRisk, trades: scenarioTrades, cost_per_trade: scenarioCost,
      runs: scenarioRuns, seed: scenarioSeed, low_return_pct: growthLow,
      base_return_pct: growthBase, high_return_pct: growthHigh, periods: growthPeriods,
      loss_streak: growthLossStreak,
    }
    if (targets[key]) targets[key].value = value
  })
}

async function deleteScenario() {
  const item = savedScenarios.value.find((saved) => saved.id === selectedSavedId.value)
  if (!item) return
  try {
    await api.del(`/api/risk/calculator/scenarios/${encodeURIComponent(item.id)}`)
    selectedSavedId.value = ''
    scenarioMessage.value = 'ลบสมมติฐานแล้ว'
    scenarioError.value = false
    await refreshSavedScenarios()
  } catch (err) {
    scenarioError.value = true
    scenarioMessage.value = err.message || 'ลบไม่ได้'
  }
}

async function ensureTradeList() {
  if (tradeListLoaded.value) return
  tradeListLoading.value = true
  try {
    const response = await api.get('/api/trading/trades?limit=100')
    availableTrades.value = Array.isArray(response.trades) ? response.trades : []
    tradeListLoaded.value = true
  } finally {
    tradeListLoading.value = false
  }
}

async function refreshTradeList() {
  tradeListLoaded.value = false
  try {
    await ensureTradeList()
    if (tradeTicket.value && !availableTrades.value.some((item) => String(item.ticket) === String(tradeTicket.value))) {
      tradeTicket.value = ''
    }
  } catch (err) {
    error.value = err.message || 'โหลดประวัติไม่สำเร็จ'
  }
}

function downloadResult(format) {
  const payload = copyPayload.value
  if (!payload) return
  const body = format === 'csv' ? calculatorCsv(payload) : calculatorJson(payload)
  const type = format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8'
  const blob = new Blob([body], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `no7-calculator-${tool.value}-${new Date().toISOString().replaceAll(':', '-')}.${format}`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function printResult() {
  const payload = copyPayload.value
  if (!payload) return
  error.value = ''
  try {
    const printWindow = window.open('', '_blank', 'popup,width=900,height=700')
    if (!printWindow) {
      error.value = 'เบราว์เซอร์บล็อกหน้าต่างพิมพ์ กรุณาอนุญาต pop-up แล้วลองใหม่'
      return
    }
    printWindow.opener = null
    printWindow.document.open()
    printWindow.document.write(calculatorPrintDocument({
      ...payload,
      exported_at: new Date().toISOString(),
    }))
    printWindow.document.close()
    printWindow.focus()
    printWindow.print()
  } catch {
    error.value = 'เปิดหน้าต่างพิมพ์ไม่ได้ กรุณาลองอีกครั้งจาก browser'
  }
}

function accountMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const amount = Number(value)
  const currency = spec.value?.account_currency || 'USD'
  return `${amount < 0 ? '-' : ''}${fmt(Math.abs(amount), 2)} ${currency}`
}

async function load() {
  const activeRequest = ++requestId
  error.value = ''
  result.value = null
  copyPayload.value = null
  spec.value = null
  provenance.value = null
  positionSize.value = null
  try {
    if (tool.value === 'scenario' || tool.value === 'capital_growth') {
      if (!savedScenariosLoaded.value) await refreshSavedScenarios()
      if (activeRequest !== requestId) return
    }
    if (tool.value === 'trade_review_whatif') {
      await ensureTradeList()
      if (activeRequest !== requestId) return
      if (!tradeTicket.value) {
        result.value = null
        spec.value = null
        provenance.value = null
        error.value = ''
        return
      }
      const query = new URLSearchParams({ tool: 'trade_review_whatif', trade_ticket: tradeTicket.value })
      if (whatifEntry.value !== null && whatifEntry.value !== '') query.set('whatif_entry', String(whatifEntry.value))
      if (whatifStop.value !== null && whatifStop.value !== '') query.set('whatif_stop_loss', String(whatifStop.value))
      if (whatifTarget.value !== null && whatifTarget.value !== '') query.set('whatif_take_profit', String(whatifTarget.value))
      const data = await api.get(`/api/risk/calculator?${query.toString()}`)
      if (activeRequest !== requestId) return
      result.value = data.result || null
      spec.value = data.spec || null
      provenance.value = data.provenance || null
      copyPayload.value = { tool: tool.value, result: result.value, source: provenance.value, symbol: spec.value?.symbol }
      return
    }
    if (isAnalysisTool.value) {
      result.value = null
      spec.value = null
      provenance.value = null
      const data = await api.get(`/api/analysis/${encodeURIComponent(symbol.value)}?fresh=true`)
      if (activeRequest !== requestId) return
      spec.value = data.snapshot?.spec || null
      provenance.value = {
        market_feed: data.snapshot?.data_quality?.feed,
        spec_source: data.snapshot?.spec?.source,
        bar_open_utc: data.snapshot?.server_time,
      }
      result.value = tool.value === 'atr_volatility'
        ? projectAtrVolatility(data)
        : projectSupportResistance(data)
      copyPayload.value = { tool: tool.value, result: result.value,
        source: provenance.value, symbol: spec.value?.symbol }
      return
    }
    const query = new URLSearchParams({
      symbol: symbol.value,
      points: String(tool.value === 'size' ? slPoints.value : points.value),
      lot: String(lot.value),
    })
    let endpoint = '/api/market/calculator'
    if (tool.value === 'size') {
      endpoint = '/api/risk/calculator'
      if (equity.value !== null && equity.value !== '' && Number.isFinite(Number(equity.value))) {
        query.set('tool', 'size')
        query.set('balance', String(equity.value))
        query.set('risk_pct', String(riskPct.value))
        query.set('sl_points', String(slPoints.value))
      }
    } else if (tool.value === 'risk_reward') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'risk_reward')
      query.set('entry', String(entry.value))
      query.set('stop_loss', String(stopLoss.value))
      query.set('take_profit', String(takeProfit.value))
      query.set('side', side.value)
    } else if (tool.value === 'drawdown') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'drawdown')
      query.set('current_equity', String(currentEquity.value))
      query.set('peak_equity', String(peakEquity.value))
    } else if (tool.value === 'break_even') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'break_even')
      query.set('gross_reward', String(grossReward.value))
      query.set('gross_loss', String(grossLoss.value))
      query.set('estimated_cost', String(estimatedCost.value))
    } else if (tool.value === 'trading_costs') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'trading_costs')
      query.set('side', side.value)
      query.set('price', String(entry.value))
      query.set('holding_nights', String(holdingNights.value))
      query.set('triple_swap_nights', String(tripleSwapNights.value))
    } else if (tool.value === 'point_tick') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'point_tick')
      query.set('price_delta', String(priceDelta.value))
    } else if (tool.value === 'profit_loss') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'profit_loss')
      query.set('entry', String(entry.value))
      query.set('exit_price', String(exitPrice.value))
      query.set('side', side.value)
    } else if (tool.value === 'auto_sl_tp') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'auto_sl_tp')
      if (previewEntry.value !== null && previewEntry.value !== '') query.set('entry', String(previewEntry.value))
      query.set('side', side.value)
      if (manualEquity.value !== null && manualEquity.value !== '') query.set('manual_equity', String(manualEquity.value))
      query.set('risk_pct', String(riskPct.value))
      query.set('stop_mode', stopMode.value)
      query.set('fixed_sl_points', String(fixedSlPoints.value))
      query.set('atr_multiplier', String(atrMultiplier.value))
      query.set('structure_buffer_atr', String(structureBufferAtr.value))
      query.set('swing_lookback_bars', String(swingLookbackBars.value))
      query.set('target_mode', previewTargetMode.value)
      query.set('target_r', String(targetR.value))
    } else if (tool.value === 'margin') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'margin')
      query.set('side', side.value)
      query.set('lot', String(lot.value))
    } else if (tool.value === 'confirmation_100pt') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'confirmation_100pt')
      query.set('side', side.value)
      if (confirmationReference.value !== null && confirmationReference.value !== '') {
        query.set('reference_price', String(confirmationReference.value))
      }
    } else if (tool.value === 'scenario') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'scenario')
      if (manualEquity.value !== null && manualEquity.value !== '') query.set('manual_equity', String(manualEquity.value))
      query.set('risk_pct', String(riskPct.value))
      query.set('win_rate_pct', String(scenarioWinRate.value))
      query.set('reward_risk', String(scenarioRewardRisk.value))
      query.set('trades', String(scenarioTrades.value))
      query.set('cost_per_trade', String(scenarioCost.value))
      query.set('runs', String(scenarioRuns.value))
      query.set('seed', String(scenarioSeed.value))
    } else if (tool.value === 'capital_growth') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'capital_growth')
      if (manualEquity.value !== null && manualEquity.value !== '') query.set('manual_equity', String(manualEquity.value))
      query.set('low_return_pct', String(growthLow.value))
      query.set('base_return_pct', String(growthBase.value))
      query.set('high_return_pct', String(growthHigh.value))
      query.set('periods', String(growthPeriods.value))
      query.set('risk_pct', String(riskPct.value))
      query.set('loss_streak', String(growthLossStreak.value))
    } else if (tool.value === 'currency_convert') {
      endpoint = '/api/risk/calculator'
      query.set('tool', 'currency_convert')
      query.set('amount', String(fxAmount.value))
      query.set('from_currency', fromCurrency.value)
      query.set('to_currency', toCurrency.value)
    }
    const data = await api.get(`${endpoint}?${query.toString()}`)
    if (activeRequest !== requestId) return
    result.value = data.result || data.points
    spec.value = data.spec
    provenance.value = data.provenance || null
    positionSize.value = data.position_size || null
    copyPayload.value = { tool: tool.value, result: positionSize.value || result.value,
      source: provenance.value, symbol: spec.value?.symbol }
  } catch (err) {
    if (activeRequest !== requestId) return
    error.value = err.message
  }
}

function scheduleLoad() {
  if (loadTimer !== null) clearTimeout(loadTimer)
  if (isPlanPreviewTool.value) {
    requestId += 1
    result.value = null
    loadTimer = setTimeout(load, 350)
  } else {
    load()
  }
}

function resetInputs() {
  points.value = 750
  lot.value = 0.01
  equity.value = null
  manualEquity.value = null
  riskPct.value = 0.5
  slPoints.value = 400
  side.value = 'BUY'
  confirmationReference.value = null
  entry.value = 2000
  previewEntry.value = null
  stopLoss.value = 1990
  takeProfit.value = 2020
  exitPrice.value = 2010
  grossReward.value = 100
  grossLoss.value = 100
  estimatedCost.value = 7
  holdingNights.value = 3
  tripleSwapNights.value = 1
  currentEquity.value = 9000
  peakEquity.value = 10000
  priceDelta.value = 5
  stopMode.value = 'atr_structure'
  fixedSlPoints.value = 500
  atrMultiplier.value = 1.5
  structureBufferAtr.value = 0.2
  swingLookbackBars.value = 10
  previewTargetMode.value = 'adaptive'
  targetR.value = 2
  scenarioWinRate.value = 50
  scenarioRewardRisk.value = 2
  scenarioTrades.value = 50
  scenarioCost.value = 0
  scenarioRuns.value = 300
  scenarioSeed.value = 7
  growthLow.value = -2
  growthBase.value = 1
  growthHigh.value = 4
  growthPeriods.value = 12
  growthLossStreak.value = 5
  fxAmount.value = 1000
  fromCurrency.value = 'USD'
  toCurrency.value = 'THB'
  scenarioName.value = ''
  scenarioMessage.value = ''
  scenarioError.value = false
  tradeTicket.value = ''
  whatifEntry.value = null
  whatifStop.value = null
  whatifTarget.value = null
  quizChoice.value = null
  quizFeedback.value = ''
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(JSON.stringify(copyPayload.value, null, 2))
  } catch {
    error.value = 'คัดลอกไม่ได้ใน browser นี้'
  }
}

watch([symbol, tool], scheduleLoad, { immediate: true })
watch(selectedLessonId, () => { quizChoice.value = null; quizFeedback.value = '' })
watch(tradeTicket, (ticket) => {
  const trade = availableTrades.value.find((item) => String(item.ticket) === String(ticket))
  whatifEntry.value = trade?.entry || null
  whatifStop.value = trade?.sl > 0 ? trade.sl : null
  whatifTarget.value = trade?.tp > 0 ? trade.tp : null
  if (tool.value === 'trade_review_whatif') scheduleLoad()
})
watch([points, lot, equity, manualEquity, riskPct, slPoints, side, confirmationReference, entry, stopLoss, takeProfit, exitPrice,
  grossReward, grossLoss, estimatedCost, holdingNights, tripleSwapNights, currentEquity,
  peakEquity, priceDelta, previewEntry, stopMode, fixedSlPoints, atrMultiplier, structureBufferAtr,
  swingLookbackBars, previewTargetMode, targetR, scenarioWinRate, scenarioRewardRisk,
  scenarioTrades, scenarioCost, scenarioRuns, scenarioSeed, growthLow, growthBase,
  growthHigh, growthPeriods, growthLossStreak, fxAmount, fromCurrency, toCurrency,
  whatifEntry, whatifStop, whatifTarget],
  () => { if (!isAnalysisTool.value) scheduleLoad() })

onBeforeUnmount(() => {
  if (loadTimer !== null) clearTimeout(loadTimer)
})
</script>
