"""Host-side backup/restore using the existing NETRIX container's native client."""

import argparse
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", required=True)
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--confirm-database", default="")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    command = [
        "docker", "compose", "--project-directory", str(root),
        "--env-file", str(Path(args.env_file).resolve()), "-f", str(root / "compose.yaml"),
        "exec", "-T", "netrix-app", "python", "-m", "netrix.backup",
    ]
    output = Path(args.output)
    if args.restore:
        if not args.confirm_database:
            raise SystemExit("Restore requires --confirm-database")
        with output.open("rb") as source:
            subprocess.run(
                command + ["--restore", "--confirm-database", args.confirm_database],
                stdin=source, check=True,
            )
    else:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as target:
                subprocess.run(command, stdout=target, stdin=subprocess.DEVNULL, check=True)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    print("Restore complete" if args.restore else "Backup complete")


if __name__ == "__main__":
    main()
