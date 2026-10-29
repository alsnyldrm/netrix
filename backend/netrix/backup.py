"""Run native MariaDB clients inside the application container, without argv secrets."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url


def run(restore=False, confirm_database=""):
    url = make_url(os.environ["NETRIX_DATABASE_URL"])
    database = url.database or ""
    if url.get_backend_name() != "mysql" or not database or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in database
    ):
        raise ValueError("A named MariaDB database is required")
    if restore and confirm_database != database:
        raise ValueError("Restore requires explicit confirmation of the database name")

    def quote(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'

    with tempfile.TemporaryDirectory(prefix="netrix-backup-") as directory:
        client = Path(directory) / "client.cnf"
        descriptor = os.open(client, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as target:
            target.write(
                "[client]\nhost=" + quote(url.host or "")
                + "\nport=" + str(url.port or 3306)
                + "\nuser=" + quote(url.username or "")
                + "\npassword=" + quote(url.password or "") + "\n"
            )
        command = ["mariadb" if restore else "mariadb-dump", f"--defaults-extra-file={client}"]
        if not restore:
            command += ["--single-transaction", "--skip-lock-tables", "--no-tablespaces"]
        subprocess.run(command + [database], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args()
    try:
        run(args.restore, args.confirm_database)
    except Exception as exc:
        raise SystemExit(f"NETRIX backup failed: {type(exc).__name__}") from None
