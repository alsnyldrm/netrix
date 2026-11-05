"""Worker-wide bounds: device reads share one limit, heavy SQL leaves the event loop."""

import asyncio
import contextvars
import functools
import weakref
from concurrent.futures import ThreadPoolExecutor

# One switch counts once, whether its read uses SNMP alone or SNMP followed by SSH.
DEVICE_READ_CONCURRENCY = 10

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


async def sql_write(fn, /, *args, **kwargs):
    """Run a self-contained session function on the single writer thread."""
    call = functools.partial(contextvars.copy_context().run, fn, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(_writer, call)


async def sql_read(fn, /, *args, **kwargs):
    """Run a slow, self-contained read so SNMP/ICMP timers keep firing."""
    return await asyncio.to_thread(fn, *args, **kwargs)
