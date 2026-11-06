"""Verified, transactional MariaDB → PostgreSQL transfer for a stopped NETRIX.

Source is read-only; secrets and encrypted blobs are never printed. The caller
must quiesce all writers for the final cutover (a live snapshot is a rehearsal).
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import MetaData, create_engine, func, inspect, select, text

from . import models  # noqa: F401
from .core import Base, engine
from .db_types import postgres_value


def canonical(row):
    def scalar(value):
        if isinstance(value, datetime):
            at = (
                value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
            )
            return at.isoformat(timespec="microseconds")
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            return {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
        return value

    return json.dumps(
        postgres_value(dict(row)), default=scalar, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()


def signature(connection, table):
    digests = []
    query = select(table).order_by(*table.primary_key.columns)
    for row in connection.execute(query).mappings():
        digests.append(hashlib.sha256(canonical(row)).digest())
    return fingerprint(digests)


def fingerprint(digests):
    # MariaDB and PostgreSQL collations order composite text keys differently.
    # Hash the full multiset of rows, retaining duplicate multiplicity.
    return {"rows": len(digests), "sha256": hashlib.sha256(b"".join(sorted(digests))).hexdigest()}


def transfer(confirm, report):
    target = engine()
    if target.dialect.name != "postgresql" or target.url.database != confirm:
        raise ValueError("The explicitly confirmed PostgreSQL target is required")
    source = create_engine(os.environ["NETRIX_SOURCE_DATABASE_URL"], hide_parameters=True, pool_pre_ping=True)
    if source.dialect.name not in ("mysql", "mariadb"):
        raise ValueError("Source must be MariaDB")
    # Reflect only known current columns, with model types handling JSON/binary/UTC.
    source_meta = MetaData()
    from sqlalchemy import Column, Table

    for table in Base.metadata.tables.values():
        Table(
            table.name,
            source_meta,
            *[Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in table.columns],
        )
    inventory = inspect(source)
    expected_names = {table.name for table in Base.metadata.tables.values()}
    actual_names = set(inventory.get_table_names()) - {"alembic_version"}
    if expected_names != actual_names:
        raise RuntimeError("Source table inventory differs from the mapped schema")
    manifests = {}
    with source.connect().execution_options(isolation_level="REPEATABLE READ") as src:
        src.execute(text("SET TRANSACTION READ ONLY"))
        with target.begin() as dst:
            dst.execute(text("SET LOCAL statement_timeout = 0"))
            dst.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            for table in Base.metadata.tables.values():
                if dst.scalar(select(func.count()).select_from(table)):
                    raise RuntimeError("Target is not empty; no existing rows were changed")
            for table in Base.metadata.tables.values():
                original = source_meta.tables[table.name]
                columns = {c["name"] for c in inventory.get_columns(table.name)}
                if columns != set(original.c.keys()):
                    raise RuntimeError("Source column inventory differs: " + table.name)
                query = select(original).order_by(*original.primary_key.columns)
                result = src.execution_options(stream_results=True).execute(query).mappings()
                count, digests = 0, []
                while batch := result.fetchmany(500):
                    rows = [dict(row) for row in batch]
                    try:
                        dst.execute(table.insert(), rows)
                    except Exception as exc:
                        print(
                            json.dumps(
                                {
                                    "table": table.fullname,
                                    "sqlstate": getattr(getattr(exc, "orig", None), "sqlstate", None),
                                    "driver_error": type(getattr(exc, "orig", None)).__name__,
                                    "nul_columns": sorted(
                                        {
                                            k
                                            for r in rows
                                            for k, v in r.items()
                                            if isinstance(v, str) and "\x00" in v
                                        }
                                    ),
                                }
                            ),
                            flush=True,
                        )
                        raise
                    for row in rows:
                        digests.append(hashlib.sha256(canonical(row)).digest())
                    count += len(rows)
                manifests[table.fullname] = fingerprint(digests)
                print(json.dumps({"table": table.fullname, "copied": count}), flush=True)
            dst.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            # Full-column content comparison, including encrypted credentials/configs.
            for table in Base.metadata.tables.values():
                actual = signature(dst, table)
                if actual != manifests[table.fullname]:
                    print(
                        json.dumps(
                            {"table": table.fullname, "expected": manifests[table.fullname], "actual": actual}
                        ),
                        flush=True,
                    )
                    raise RuntimeError("Content mismatch: " + table.fullname)
            dst.execute(text("ANALYZE"))
    if report:
        with open(report, "w") as out:
            json.dump({"database": confirm, "tables": manifests, "verified": True}, out, indent=2)
    print(
        json.dumps(
            {"verified": True, "tables": len(manifests), "rows": sum(v["rows"] for v in manifests.values())}
        )
    )
    source.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-target", required=True)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        transfer(args.confirm_target, args.report)
    except Exception as exc:
        # SQLAlchemy exception text can contain source values; keep logs secret-free.
        print("NETRIX transfer failed: " + type(exc).__name__, flush=True)
        raise SystemExit(1) from None
