"""Compatibility entry point for the current workspace regression check."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("user_ssh_profiles_mariadb_check.py")), run_name="__main__")
