# Personal Trade Journal, Screenshot and Share Studio

## Capture per closed trade
- Identity scope: tenant + user + account + portfolio, broker account alias; do not leak true account/ticket in shares.
- IDs: internal trade id, broker order/deal tickets encrypted or protected, open/close timestamps (UTC + user-local display), symbol and deal side.
- Exact price/lot, broker digits/point/tick size, gross P/L, commissions, swap, realized net in account currency, points, R-multiple, MAE/MFE, drawdown, SL/TP, exit reason, strategy/model/risk version and market regime.
- Partial fills/partial closes: aggregate by canonical position lifecycle, avoid counting one position as many wins in daily metrics without explicit method.
- Evidence: before-entry snapshot, at-entry, exit and optional manually uploaded screenshot; source/image checksum, metadata, retention and privacy controls; no assumption broker provides chart images automatically.
- Journal: manual notes, AI hypothesis, test result and whether lesson was validated; mark guesses as such.

## Daily / monthly report
- Per-user calendar + selected portfolio/account strategy, timezone `Asia/Bangkok` default; grouping by **close date**; show trade count, wins, losses, breakeven, net points per symbol, money P/L after cost, win rate, profit factor (handle divide-by-zero), expectancy, avg R, max drawdown and data coverage.
- Import the user-supplied 'Lady Gold October 2026' as **example only**, not verified broker deals. Ensure `cut -100` is parsed as a realized outcome and point/monetary units annotated.
- Each day shows entry rows `SELL +2000 pt`/`BUY -1000 pt`, source broker, local time, screenshot links. Aggregates must reconcile with broker Deals.

## Sharing
- Preview -> redact -> explicit user confirmation -> text/PNG/PDF -> optional Telegram/LINE/Discord webhook/message. Never auto-publish other users' stats, P/L, account identity, private notes or screenshots.
- Report watermark: `DEMO`, `PAPER`, or `LIVE`; date and period, timezone, unit (points vs currency), portfolio alias, metrics definitions and whether verified against broker.
- Provide copy-to-clipboard message and downloadable image/PDF. Record share history and revocation where supported; platform copies may not be retractable.
- Accessibility: mobile legibility, readable Thai/EN, distinct symbols besides red/green, selectable dark/light themes.

## Suggested report text
📍 สรุปสถิติ Lady Gold — ตุลาคม 2026 (ตัวอย่าง ไม่ใช่บัญชีจริง)
📍 05/10/2026: ✅ SELL +2,000 จุด | ⭕ SELL −1,000 จุด | ⭕ BUY −1,000 จุด | ✅ SELL +2,000 จุด
📍 22/10/2026: ✅ SELL +2,000 จุด × 3
หมายเหตุ: เป็น "จุด" (points), ไม่ใช่กำไรเงิน; ต้นทุนและข้อมูลบัญชีจริงต้องตรวจจาก MT5 ก่อนสรุปยอด
