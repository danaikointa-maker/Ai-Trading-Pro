"""Preview or stage a non-activating V1.1 profile migration manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.shared_schemas.settings import CONFIG_DIR
from services.risk_engine.protection_profile import load_v1_1_profile, migration_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", action="store_true",
                        help="write an audit manifest only; does not edit config/risk.yaml or activate V1.1")
    parser.add_argument("--output", default="storage/config-migrations/position-protection-v1.1.json")
    args = parser.parse_args()
    import yaml

    current = yaml.safe_load((CONFIG_DIR / "risk.yaml").read_text(encoding="utf-8")) or {}
    profile = load_v1_1_profile()
    manifest = migration_manifest(current, profile)
    rendered = json.dumps(manifest, indent=2, sort_keys=True)
    print(rendered)
    if args.stage:
        output = Path(args.output)
        if not output.is_absolute():
            output = CONFIG_DIR.parent / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Staged manifest: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
