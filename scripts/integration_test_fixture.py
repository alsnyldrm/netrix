"""Local fixture with real API/interactive dispatch and fake protocol responses."""

import asyncio
import os
import runpy
import time
from contextlib import asynccontextmanager, suppress

fixture = runpy.run_path("scripts/vlan_configuration_fixture.py", run_name="fixture")
app = fixture["main"].app
from netrix import worker  # noqa: E402
from netrix.core import settings  # noqa: E402
from netrix.ipam import connection_tests  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8267"
settings.cache_clear()


def fake_probe(config, secret):
    time.sleep(0.5)
    if config.host == "failed.example.test":
        raise TimeoutError("Private fixture protocol error")
    if config.host == "slow.example.test":
        time.sleep(2)
    assert secret["username"] and secret["password"]
    return "Fixture: bağlantı, kullanıcı doğrulaması ve okuma erişimi başarılı."


connection_tests.probe = fake_probe
original = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async def run():
        while True:
            id = worker.claim(interactive=True, include_kinds=(connection_tests.KIND,))
            if id:
                await worker.execute(id, heartbeat_role="tests")
            await asyncio.sleep(0.05)

    async with original(application):
        task = asyncio.create_task(run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app.router.lifespan_context = lifespan
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8267, log_level="warning")
