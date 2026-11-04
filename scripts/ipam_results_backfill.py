"""Explicit offline result projection; does not start scans or import inventory."""

import asyncio

from netrix.ipam.backfill import run

if __name__ == "__main__":
    print("Existing IP results materialized:", asyncio.run(run()))
