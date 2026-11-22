"""Bounded Syslog UDP/TCP receiver in the existing NETRIX container."""

import asyncio
import logging
import signal

from ..core import now, redis_client, settings
from ..services import publish
from .logs import ingest_batch, prune

MAX_MESSAGE = 8192
QUEUE_SIZE = 4096
CONNECTIONS = 32
log = logging.getLogger("netrix.acl_logs")


async def read_frame(reader):
    first = await reader.read(1)
    if not first:
        return None
    if first.isdigit():
        digits = bytearray(first)
        while True:
            char = await reader.readexactly(1)
            if char == b" ":
                break
            if not char.isdigit() or len(digits) >= 5:
                raise ValueError("Invalid frame length")
            digits.extend(char)
        size = int(digits)
        if not 0 < size <= MAX_MESSAGE:
            raise ValueError("Frame too large")
        return await reader.readexactly(size)
    rest = await reader.readuntil(b"\n")
    if len(first) + len(rest) > MAX_MESSAGE:
        raise ValueError("Frame too large")
    return (first + rest).rstrip(b"\r\n")


class Receiver:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.connections = 0
        self.dropped = 0
        self.changed = False

    def enqueue(self, peer, payload, transport):
        if not payload or len(payload) > MAX_MESSAGE:
            self.dropped += 1
            return
        try:
            self.queue.put_nowait((peer, payload, transport, now()))
        except asyncio.QueueFull:
            self.dropped += 1

    async def tcp(self, reader, writer):
        if self.connections >= CONNECTIONS:
            self.dropped += 1
            writer.close()
            await writer.wait_closed()
            return
        self.connections += 1
        peer = writer.get_extra_info("peername")[0]
        try:
            while True:
                async with asyncio.timeout(30):
                    payload = await read_frame(reader)
                if payload is None:
                    break
                self.enqueue(peer, payload, "syslog_tcp")
        except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError):
            self.dropped += 1
        finally:
            self.connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def consume(self, stopping):
        while not stopping.is_set() or not self.queue.empty():
            try:
                first = await asyncio.wait_for(self.queue.get(), timeout=1)
            except TimeoutError:
                continue
            batch = [first]
            for _ in range(99):
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for attempt in range(3):
                try:
                    inserted = await asyncio.to_thread(ingest_batch, batch)
                    self.changed = self.changed or inserted > 0
                    break
                except Exception as exc:
                    log.warning("acl_log_store_failed error_class=%s", type(exc).__name__)
                    if attempt == 2:
                        self.dropped += len(batch)
                    else:
                        await asyncio.sleep(0.5 * 2**attempt)

    async def heartbeat(self, stopping):
        last_prune = 0.0
        while not stopping.is_set():
            dropped, self.dropped = self.dropped, 0
            def update():
                redis = redis_client()
                redis.set("netrix:acl_logs:heartbeat", now().isoformat(), ex=30)
                if dropped:
                    redis.incrby("netrix:acl_logs:dropped", dropped)
            try:
                await asyncio.to_thread(update)
                dropped = 0
                if self.changed:
                    await asyncio.to_thread(publish)
                    self.changed = False
                if asyncio.get_running_loop().time() - last_prune > 60:
                    await asyncio.to_thread(prune)
                    last_prune = asyncio.get_running_loop().time()
            except Exception as exc:
                self.dropped += dropped
                log.warning("acl_log_maintenance_failed error_class=%s", type(exc).__name__)
            try:
                await asyncio.wait_for(stopping.wait(), timeout=5)
            except TimeoutError:
                pass


class DatagramReceiver(asyncio.DatagramProtocol):
    def __init__(self, receiver):
        self.receiver = receiver

    def datagram_received(self, data, addr):
        self.receiver.enqueue(addr[0], data, "syslog_udp")

    def error_received(self, exc):
        self.receiver.dropped += 1


async def main():
    receiver, stopping = Receiver(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    port = settings().acl_log_port
    udp, _ = await loop.create_datagram_endpoint(
        lambda: DatagramReceiver(receiver), local_addr=("0.0.0.0", port),
    )
    server = await asyncio.start_server(receiver.tcp, "0.0.0.0", port, limit=MAX_MESSAGE + 1)
    consumer = asyncio.create_task(receiver.consume(stopping))
    heart = asyncio.create_task(receiver.heartbeat(stopping))
    try:
        await stopping.wait()
    finally:
        udp.close()
        server.close()
        await server.wait_closed()
        await asyncio.gather(consumer, heart)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
