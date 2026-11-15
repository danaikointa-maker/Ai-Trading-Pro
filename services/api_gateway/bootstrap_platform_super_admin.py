"""Provision the first platform super-admin from a local terminal prompt."""
from __future__ import annotations

from getpass import getpass

from packages.persistence.db import Database
from packages.shared_schemas.settings import get_settings
from services.api_gateway.platform_admin import create_platform_super_admin


def main() -> int:
    email = input("Platform super-admin email: ").strip()
    password = getpass("Password (hidden): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 2

    settings = get_settings()
    db = Database(settings.database_path,
                  workspace_id=settings.security.get("workspace_id", "local"))
    try:
        admin = create_platform_super_admin(db, email, password)
    except ValueError as exc:
        print(f"Could not provision super-admin: {exc}")
        return 2
    finally:
        db.close()

    print(f"Platform super-admin created: {admin['email']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())