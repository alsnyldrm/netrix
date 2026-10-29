"""Local browser fixture only. Never included in the production image."""

import os
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["NETRIX_DATABASE_URL"] = "sqlite+pysqlite:///.secrets/browser.db"
os.environ["NETRIX_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["NETRIX_SETUP_TOKEN"] = "browser-fixture-setup-token-only"
os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8201"
os.environ["NETRIX_SECURE_COOKIES"] = "false"
import time

from netrix import main, models, services
from netrix.core import Base, engine
from sqlalchemy.orm import Session


class PubSub:
    def subscribe(self, *args):
        pass

    def get_message(self, **kwargs):
        time.sleep(0.5)
        return None

    def close(self):
        pass


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, *args):
        pass

    def ping(self):
        return True

    def publish(self, *args):
        pass

    def get(self, *args):
        return None

    def pubsub(self):
        return PubSub()


r = MemoryRedis()
main.redis_client = lambda: r
services.redis_client = lambda: r
Path(".secrets").mkdir(mode=0o700, exist_ok=True)
Base.metadata.create_all(engine())
with Session(engine()) as db:
    if not db.get(models.SystemState, "setup"):
        db.add(models.SystemState(key="setup", value="pending"))
        db.commit()
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8201, log_level="warning")
