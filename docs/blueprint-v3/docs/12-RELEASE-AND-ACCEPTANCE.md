# Release acceptance record / sign-off template

## Change request
- Date / engineer / approved reviewer:
- Git commit / feature branch / release tag:
- Scope and impacted VM(s):
- Backup ID / last successful restore test:
- Before-state observations and baseline test results:
- Security and risk review:

## Quality gate evidence
| Gate | Status (PASS/FAIL/BLOCKED) | Evidence path | Approver |
|---|---|---|---|
| Python unit/contract suite | | | |
| Vue build + accessibility smoke | | | |
| Ubuntu authenticated health / mTLS | | | |
| Windows MT5 Demo symbol/account check | | | |
| Bridge disconnect/reconnect | | | |
| Duplicate order / unknown reconciliation | | | |
| Risk veto / kill switch | | | |
| User isolation + signed image URLs | | | |
| Journal totals to broker deal parity | | | |
| Backup and sample restore | | | |
| Rollback dry-run | | | |

## Rollout / rollback
- Rollout: build immutable artifact, stage, test, operator approval, deploy, smoke, observe. No changes to production VM storage without separate approval.
- Rollback: stop/new-order block, revert release symlink/artifact and schema via tested backup/reverse migration, reconcile MT5, restore validated DB if needed, post-incident audit.
- Release statuses: DEVELOPMENT -> STAGING -> DEMO_ACCEPTED -> LIVE_REVIEW_REQUIRED. **No automatic promotion to live.**
