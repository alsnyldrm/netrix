"""Bounded SNMP bulk reads with explicit, non-secret per-table outcomes."""

import asyncio

from pysnmp.error import PySnmpError
from pysnmp.hlapi.v3arch.asyncio import bulk_cmd

from . import protocols as p


async def walk_table(
    snmp, auth, target, context, nonrepeat, repeats, varbind, *, root_oid, maxCalls, **options
):
    """Keep exception varbinds that pysnmp.bulk_walk_cmd silently treats as EOF."""
    cursor = varbind
    previous = tuple(map(int, root_oid.split(".")))
    root = root_oid + "."
    for _ in range(maxCalls):
        error, status, index, bindings = await bulk_cmd(
            snmp, auth, target, context, nonrepeat, repeats, cursor, lookupMib=False
        )
        if error or status:
            yield error, status, index, bindings
            return
        if not bindings:
            raise p.NetworkError("Empty SNMP response without end-of-table proof")
        ending = False
        for key, value in bindings:
            if isinstance(value, (p.EndOfMibView, p.NoSuchObject, p.NoSuchInstance)) or not str(
                key
            ).startswith(root):
                ending = True
                break
            current = tuple(map(int, str(key).split(".")))
            if current <= previous:
                raise p.NetworkError("Non-increasing SNMP table OID")
            previous = current
        yield error, status, index, bindings
        if ending:
            return
        cursor = p.ObjectType(p.ObjectIdentity(str(bindings[-1][0])))
    raise p.NetworkError("SNMP table request limit")


async def read_table(snmp, auth, target, context, oid, *, limit=65536, timeout=15, deadline=None):
    """`timeout` bounds silence between responses; `deadline` bounds the whole table."""
    rows = {}
    status, code = "complete", ""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 160 if deadline is None else deadline
    try:
        async with asyncio.timeout_at(min(loop.time() + timeout, deadline)) as budget:
            async for error, error_status, _, bindings in walk_table(
                snmp,
                auth,
                target,
                context,
                0,
                25,
                p.ObjectType(p.ObjectIdentity(oid)),
                lexicographicMode=False,
                lookupMib=False,
                root_oid=oid,
                maxRows=limit + 1,
                maxCalls=limit + 1,
            ):
                # A slow table that keeps answering is not a stalled table.
                budget.reschedule(min(loop.time() + timeout, deadline))
                if error or error_status:
                    status = "error"
                    code = "pdu_" + str(int(error_status)) if error_status else type(error).__name__[:60]
                    break
                for key, value in bindings:
                    if isinstance(value, (p.NoSuchObject, p.NoSuchInstance)):
                        status, code = "unsupported", type(value).__name__
                        continue
                    if isinstance(value, p.EndOfMibView) or not str(key).startswith(oid + "."):
                        continue
                    rows[str(key)[len(oid) + 1 :]] = value
                    if len(rows) > limit:
                        rows.pop(str(key)[len(oid) + 1 :])
                        return rows, dict(status="truncated", row_count=len(rows), error_code="row_limit")
    except TimeoutError:
        status, code = "timeout", "table_timeout"
    except (OSError, p.NetworkError, PySnmpError) as exc:
        status, code = "error", type(exc).__name__
    return rows, dict(status=status, row_count=len(rows), error_code=code)
