"""Operator maintenance: clear saved broker links, retaining a protected backup."""
import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    path = Path(args.database).resolve(strict=True)
    connection = sqlite3.connect(f"file:{path}?mode=rw", uri=True)
    count = connection.execute("SELECT count(*) FROM broker_accounts").fetchone()[0]
    print(json.dumps({"managed_accounts": count, "database": str(path)}))
    if not args.clear:
        return
    backup_dir = Path.home() / ".local/share/no7/private-backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / ("before-broker-clear-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".sqlite3")
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(backup) as target:
        connection.backup(target)
    with connection:
        connection.execute("DELETE FROM broker_accounts")
    print(json.dumps({"remaining": connection.execute("SELECT count(*) FROM broker_accounts").fetchone()[0],
                      "backup": str(backup), "broker_accounts_closed": False}))
    connection.close()


if __name__ == "__main__":
    main()
