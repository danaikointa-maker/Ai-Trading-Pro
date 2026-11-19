# One Instruction for VS Code / Cline / Codex — V4

Use ONLY this execution sequence for the Ai-Trading-Pro repository. Earlier Master prompts are historical input, not separate backlogs.

1. Check workspace path, Git branch, HEAD, uncommitted files, runtime environment. Never overwrite current work.
2. Read docs/blueprint-v3/AGENTS.md first, then docs/SAFETY-HANDOFF.th.md, docs/LIMITATIONS.md, docs/UNIFIED-MASTER-PLAN-V4.md, docs/UNIFIED-TASK-REGISTER-V4.md, docs/UNIFIED-CONFLICTS-V4.md, config/risk.yaml and relevant code/tests.
3. Create evidence-based existing/partial/missing/unverified matrix for each U-ID in the task register; distinguish source code existence from actual MT5 demonstration.
4. Resolve conflicts through the conflict register. Keep deployed configuration unchanged until separately reviewed and tested.
5. Select ONE U-ID at a time, verify it is not already done, and name one owner module. Reuse existing FastAPI/Vue/MQL5/SQLite, RiskEngine, PositionManager and ExecutionGateway. Never create duplicate backend, engine or database.
6. Work in a focused branch. Implement the smallest safe patch and deterministic tests, preserving API and broker protection.
7. Keep confirmation, entry planning, protected order execution and position modification separate. Only the authorized gateway may reach the broker. Calculator endpoints are read-only.
8. Tests required: point/tick specification, bid/ask BUY-SELL, original R, net costs, risk veto, 100-point signal expiry, no duplicate orders, one stop modification per position, nonworsening SL, restart reconciliation, and stable chart zoom.
9. Record exact test commands, outputs, PASS/FAIL/SKIP, broker evidence and not-tested gaps. Demo testing requires separate explicit operator permission; never enable LIVE by default.
10. Update task status and README/API/MATH/RUNBOOK/LIMITATIONS documents in the same PR as code changes. Include rollback, security impact, next task, and blockers.
11. Stop at a safety or authorization blocker rather than guessing. Do not enable trading, deploy, or merge without separate authorization.

Begin with U00 audit and a proposed implementation order. Do not execute any older prompt as an independent task.
