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
        </select>
      </label>
      <div class="flex items-center gap-1.5">
        <span class="chip" :class="isReadOnlyTool ? 'chip-up' : 'chip-gold'">{{ isPlanPreviewTool ? 'READ ONLY · PLAN PREVIEW' : isAnalysisTool ? 'READ ONLY · ANALYSIS' : 'MANUAL · SANDBOX' }}</span>
        <button type="button" class="btn py-1.5" @click="resetInputs">Reset</button>
        <button v-if="result && (tool !== 'size' || positionSize)" type="button" class="btn py-1.5" @click="copyResult">Copy result</button>
      </div>
    </div>
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
import { fmt } from '../lib/format'
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
const isReadOnlyTool = computed(() => isAnalysisTool.value || isPlanPreviewTool.value)
const sourceLabel = computed(() => isAnalysisTool.value
  ? `Analysis snapshot · ${spec.value?.source || '—'}`
  : isPlanPreviewTool.value ? 'Manual SL/TP preview · read only'
  : spec.value?.source === 'broker' ? 'Broker symbol spec' : 'Declared symbol spec')
const sourceContext = computed(() => isAnalysisTool.value
  ? `feed ${provenance.value?.market_feed || '—'}`
  : isPlanPreviewTool.value ? `fresh ${provenance.value?.market_feed || 'market'} · manual equity`
  : `${spec.value?.account_currency || '—'} · FX ${spec.value?.rate_source || '—'}`)

function accountMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const amount = Number(value)
  const currency = spec.value?.account_currency || 'USD'
  return `${amount < 0 ? '-' : ''}${fmt(Math.abs(amount), 2)} ${currency}`
}

async function load() {
  const activeRequest = ++requestId
  error.value = ''
  positionSize.value = null
  try {
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
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(JSON.stringify(copyPayload.value, null, 2))
  } catch {
    error.value = 'คัดลอกไม่ได้ใน browser นี้'
  }
}

watch([symbol, tool], scheduleLoad, { immediate: true })
watch([points, lot, equity, manualEquity, riskPct, slPoints, side, entry, stopLoss, takeProfit, exitPrice,
  grossReward, grossLoss, estimatedCost, holdingNights, tripleSwapNights, currentEquity,
  peakEquity, priceDelta, previewEntry, stopMode, fixedSlPoints, atrMultiplier, structureBufferAtr,
  swingLookbackBars, previewTargetMode, targetR], () => { if (!isAnalysisTool.value) scheduleLoad() })

onBeforeUnmount(() => {
  if (loadTimer !== null) clearTimeout(loadTimer)
})
</script>
