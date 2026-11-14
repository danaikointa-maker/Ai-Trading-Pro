# 03 — Hybrid Self-Hosted AI, Learning and Losing-Trade Improvement

## Roles (all on VM100, separated and throttled)
1. Market Context: existing deterministic features, multi-timeframe trend/BOS/CHoCH/confirmed S/R; never use a single LLM image judgment as trading truth.
2. Forecast: existing LightGBM calibrated probabilities/quantile band; optional XGBoost comparator; no automatic deployment.
3. Strategy Research: test candidate rule changes offline against frozen dataset snapshots, net of fees/spread/slippage/swap.
4. Trade Review: post-close reason codes and adverse/favorable excursion: entry timing, SL placement, setup quality, slippage, spread, time-to-fill, news, market regime, model uncertainty and operational failure.
5. Trading Copilot (Ollama small Qwen3 1.7b then 4b if CPU headroom): Thai-language explanation, hypothesis generation, human-readable postmortem, notifications; strictly read-only tools/data.
6. Risk Supervisor: code/rule-driven safety, cannot be overridden by LLM and must not change limits automatically.
7. Ops Agent: metrics/anomaly summarization, incident drafts and recovery suggestions; manual approval for VM/Network/system changes.

## Training vs serving
- FAST PATH: MT5 -> verified tick -> features -> approved frozen model -> deterministic strategy/risk -> bridge, with bounded latency and only CPU-appropriate operations.
- SLOW PATH: closed trades -> replay bundle -> loss taxonomy -> hypothesis -> train candidate -> walk-forward/OOS and paper shadow -> model registry candidate -> manual review -> promotion -> monitored rollback.
- Model IDs are content hashes. Save dataset snapshot, train window, calibration window, timezone, fee assumptions, broker spec revision, git commit, pipeline version, metrics by regime, seed and full audit.
- Use n>=appropriate sample before inference; stratify by symbol/regime/session; multiple-comparison checks and untouched holdout, not 1–3 losing positions.
- Compare baseline and champion: expectancy, win rate AND payoff ratio, net profit factor, max drawdown, Brier, calibration, coverage, tail risk, trade frequency and confidence intervals; monitor drift.
- Generate proposals, never immediate live change. Promote only after walk-forward, OOS, forward DEMO and manual signoff. Roll back on drift or operational issues.
- No guarantee to win next trade. Correct output may be NO TRADE.

## Loss-review event sample (concept, add schema after code audit)
```json
{"event_type":"trade.closed.v1","event_id":"uuid","ts_utc":"...","account_mode":"demo","broker_id":"connext-demo","symbol":"XAUUSD","trade_ticket":"...","signal_id":"...","model_version":"...","setup":"breakout_retest","regime":"range","entry_price":0,"exit_price":0,"spread_points":0,"slippage_points":0,"net_r":-1,"mae_points":0,"mfe_points":0,"risk_checks":[],"data_source":"broker","quality":"verified"}
```
Loss label must not be simplistic. Distinguish `strategy_error`, `normal_statistical_loss`, `execution_cost`, `data_quality`, `operational_failure`, `manual_override`, and `unknown` based on evidence. Normal stopouts do not prove strategy failure.

## Host resource policy
- VM100 16GiB: OS/page cache 3–4GiB, core/API/ML inference 4–5GiB, DB/Redis optional 2–3GiB, research/LLM MAX ~3GiB (test actual model usage), reserve 2GiB. Do not run 4b model concurrently with heavy ML training.
- VM200 8GiB: prioritize MT5, bridge, antivirus, OS; no LLM/quant trainer.
- Machine CPU likely limited; pin worker counts (start 1 inference/1 training when idle), lower process priority, pause research on core latency, staleness or memory-pressure alarm.
- Choose existing Ollama integration; CPU-only qwen3:1.7b first. LLM remains disabled if agent response time/memory unacceptable. Avoid cloud dependency for safety path.
