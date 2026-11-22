# ruff: noqa: E402
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

folder = tempfile.mkdtemp(prefix="netrix-mfa-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + folder + "/test.db",
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="browser-only-setup-token-long",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8298",
    NETRIX_SECURE_COOKIES="false",
)
sys.path.insert(0, str(Path.cwd() / "tests"))
from conftest import MemoryRedis
from netrix import main, services
from netrix import models as m
from netrix.core import Base, engine, session_factory
from netrix.identity.security import hasher

Base.metadata.create_all(engine())
with session_factory()() as db:
    db.add(m.SystemState(key="setup", value="complete"))
    db.add(
        m.User(
            email="alisan.yildirim@fbu.edu.tr",
            display_name="Browser Owner",
            role="super_admin",
            password_hash=hasher.hash("browser-fixture-password"),
        )
    )
    db.commit()
redis = MemoryRedis()
main.redis_client = services.redis_client = lambda: redis
import uvicorn

uvicorn.run(main.app, host="127.0.0.1", port=8298, log_level="warning", access_log=False)
