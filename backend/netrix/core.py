from datetime import datetime, timezone
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


def now():
    return datetime.now(timezone.utc)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETRIX_", env_file=".env", extra="ignore")
    database_url: str = "sqlite+pysqlite:///.secrets/netrix.db"
    redis_url: str = "redis://localhost:6379/0"
    encryption_key: str = ""
    public_url: str = "https://netrix.fbu.edu.tr"
    secure_cookies: bool = True
    known_hosts: str = "/run/secrets/known_hosts"
    setup_token: str = ""
    firmware_directory: str = "/data/firmware"
    firmware_advertise_host: str = ""
    firmware_sftp_port: int = 2222
    firmware_tftp_port: int = 1069
    firmware_transfer_port_start: int = 20000
    firmware_max_bytes: int = 2 * 1024 * 1024 * 1024
    firmware_repository_bytes: int = 20 * 1024 * 1024 * 1024


@lru_cache
def settings():
    return Settings()


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name in ("mysql", "mariadb"):
            from sqlalchemy.dialects.mysql import DATETIME

            return dialect.type_descriptor(DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timezone required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value else None


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    url = settings().database_url
    obj = create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"check_same_thread": False}
        if url.startswith("sqlite")
        else {"connect_timeout": 5, "read_timeout": 15, "write_timeout": 15},
    )
    if not url.startswith("sqlite"):

        @event.listens_for(obj, "connect")
        def configure_mariadb(connection, _):
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION time_zone = '+00:00'")
                cursor.execute("SET SESSION wsrep_sync_wait = 1")

    if url.startswith("sqlite"):

        @event.listens_for(obj, "connect")
        def fk_on(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return obj


@event.listens_for(Session, "do_orm_execute")
def track_statement_writes(state):
    # Text statements count as writes: a false positive only disables a rewind.
    if not state.is_select:
        state.session.info["netrix_writes"] = True


@event.listens_for(Session, "after_flush")
def track_flush_writes(session, _):
    session.info["netrix_writes"] = True


@event.listens_for(Session, "after_transaction_end")
def reset_writes(session, transaction):
    if transaction.parent is None:
        session.info.pop("netrix_writes", None)


def read_only_transaction(db):
    """True when rolling back discards only reads, never caller work."""
    return not (
        db.info.get("netrix_writes") or db.new or db.dirty or db.deleted or db.in_nested_transaction()
    )


def session_factory():
    return sessionmaker(engine(), expire_on_commit=False)


def db_session():
    with session_factory()() as session:
        yield session


def redis_client():
    from redis import Redis

    return Redis.from_url(
        settings().redis_url, socket_connect_timeout=2, socket_timeout=3, decode_responses=True
    )
