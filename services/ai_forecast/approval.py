"""Version stamp for the model-approval rule.

Approval is a *policy*, and policies tighten. A model file records the version of
the rule it was judged under; when the rule changes, the old "approved" flag is no
longer evidence of anything — it was measured against a weaker gate. Bumping this
constant demotes every stored approval instead of quietly inheriting it.

1 — single out-of-sample split (retired)
2 — chronological folds, ≥75% must pass, median must clear the bar, and at least
    `min_validation_folds` folds must be scored at all (walk-forward refit when the
    history allows it)
"""
from __future__ import annotations

APPROVAL_RULE_VERSION = 2
