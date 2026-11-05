"""Worker-wide bounds: device reads share one limit, heavy SQL leaves the event loop."""

import asyncio
import contextvars
import functools
import weakref
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.exc import OperationalError

# One switch counts once, whether its read uses SNMP alone or SNMP followed by SSH.
DEVICE_READ_CONCURRENCY = 10
# Snapshot conflict, lock wait timeout and deadlock: another transaction won the row.
RETRIED_DB_ERRORS = (1020, 1205, 1213)
SQL_RETRIES = 6

_slots = weakref.WeakKeyDictionary()
# Source writes stay serialized as they were on the event loop: no new deadlock
# or Galera certification conflicts between jobs of this process.
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="netrix-sql-writer")


def device_slot():
    loop = asyncio.get_running_loop()
    slot = _slots.get(loop)
    if slot is None:
        slot = _slots[loop] = asyncio.Semaphore(DEVICE_READ_CONCURRENCY)
    return slot


def _conflict(exc):
    args = getattr(getattr(exc, "orig", None), "args", ())
    return bool(args) and args[0] in RETRIED_DB_ERRORS


async def _with_retry(submit):
    # Each attempt opens a fresh session, so a rolled-back attempt leaves nothing behind.
    for attempt in range(SQL_RETRIES):
        try:
            return await submit()
        except OperationalError as exc:
            if attempt == SQL_RETRIES - 1 or not _conflict(exc):
                raise
            await asyncio.sleep(0.05 * 2**attempt)


async def sql_write(fn, /, *args, **kwargs):
    """Run a self-contained session function on the single writer thread.

    `fn` may run again after a snapshot conflict: publish state only after commit.
    """
    loop = asyncio.get_running_loop()

    def submit():
        call = functools.partial(contextvars.copy_context().run, fn, *args, **kwargs)
        return loop.run_in_executor(_writer, call)

    return await _with_retry(submit)


async def sql_read(fn, /, *args, **kwargs):
    """Run a slow, self-contained step so SNMP/ICMP timers keep firing."""
    return await _with_retry(lambda: asyncio.to_thread(fn, *args, **kwargs))
