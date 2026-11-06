from datetime import datetime, timedelta, timezone

from netrix import models as m
from netrix.core import UTCDateTime
from netrix.db_layout import SCHEMA_TABLES, TABLE_SCHEMAS
from netrix.db_types import postgres_value
from netrix.pg_transfer import canonical
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable


def test_postgresql_failure_codes_are_safe_and_retryable():
    from types import SimpleNamespace

    from netrix.db_errors import code, conflict, retryable
    from sqlalchemy.exc import OperationalError

    for state in ("40001", "40P01", "55P03", "08006", "57P01"):
        error = OperationalError(None, None, SimpleNamespace(sqlstate=state, args=("secret driver text",)))
        assert code(error) == state
        assert retryable(error)
    error = OperationalError(None, None, SimpleNamespace(sqlstate="40P01", args=()))
    assert conflict(error)
    error = OperationalError(None, None, SimpleNamespace(sqlstate="42P01", args=("secret driver text",)))
    assert not retryable(error)


def test_every_table_has_one_menu_schema_and_qualified_foreign_keys():
    assert len(SCHEMA_TABLES) == 8
    assert len(TABLE_SCHEMAS) == sum(map(len, SCHEMA_TABLES.values()))
    assert {t.name for t in m.Base.metadata.tables.values()} == set(TABLE_SCHEMAS)
    for table in m.Base.metadata.tables.values():
        assert table.schema == TABLE_SCHEMAS[table.name]
        assert table.schema not in ("public", "kaynaklar", "ortak")
        assert table.primary_key.columns
        for key in table.foreign_keys:
            assert key.column.table.schema == TABLE_SCHEMAS[key.column.table.name]


def test_postgresql_uses_native_timezone_jsonb_and_qualified_names():
    ddl = str(CreateTable(m.Job.__table__).compile(dialect=postgresql.dialect()))
    assert "operasyon.jobs" in ddl
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "JSONB" in ddl
    ddl = str(CreateTable(m.Observation.__table__).compile(dialect=postgresql.dialect()))
    assert "REFERENCES envanter.devices" in ddl
    assert "DEFERRABLE" in ddl


def test_timezone_conversion_preserves_instant():
    value = datetime(2026, 11, 6, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    column = UTCDateTime()
    assert column.process_bind_param(value, postgresql.dialect()).hour == 12
    assert column.process_bind_param(value, postgresql.dialect()).tzinfo is not None
    assert column.process_bind_param(value, sqlite.dialect()).tzinfo is None


def test_snmp_nul_is_escaped_without_dropping_source_characters():
    raw = {"description": "Port\x00\x00", "values": ["A\x00B"]}
    expected = {"description": "Port\\u0000\\u0000", "values": ["A\\u0000B"]}
    assert postgres_value(raw) == expected
    assert canonical(raw) == canonical(expected)
    assert raw["description"].endswith("\x00\x00")


def test_single_reference_check_compiles_without_boolean_arithmetic():
    ddl = str(CreateTable(m.ResolutionConnection.__table__).compile(dialect=postgresql.dialect()))
    assert "CASE WHEN" in ddl
    assert "(neighbor_id IS NOT NULL) +" not in ddl


def test_postgresql_backup_uses_private_pgpass_not_argv(monkeypatch):
    from pathlib import Path

    from netrix import backup

    monkeypatch.setenv(
        "NETRIX_DATABASE_URL", "postgresql+psycopg://netrix_app:private%3Asecret@10.2.0.31:5432/netrix"
    )
    paths = []

    def run(command, **kwargs):
        path = Path(kwargs["env"]["PGPASSFILE"])
        paths.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert "private\\:secret" in path.read_text()
        assert "private" not in " ".join(command)
        assert command[0] == "pg_dump"

    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.run()
    assert not paths[0].exists()


def test_postgresql_vrf_lock_uses_no_shared_state_table(admin_client, env):
    import pytest
    from netrix.db_errors import conflict
    from netrix.services import lock_vrf
    from sqlalchemy import select, text
    from sqlalchemy.exc import OperationalError

    with env() as first, env() as second:
        if first.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL transaction lock integration")
        vrf = first.scalar(select(m.VRF))
        lock_vrf(first, vrf.id)
        second.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError) as raised:
            lock_vrf(second, vrf.id)
        assert conflict(raised.value)
        second.rollback()
        first.commit()
        lock_vrf(second, vrf.id)
        assert second.get(m.SystemState, "vrf:" + vrf.id) is None


def test_imported_integer_ids_advance_postgresql_sequence(env, monkeypatch):
    import pytest
    from netrix import pg_transfer
    from sqlalchemy import Column, Integer, MetaData, Table, select, text

    with env() as db:
        if db.get_bind().dialect.name != "postgresql":
            pytest.skip("PostgreSQL sequence integration")
        metadata = MetaData()
        table = Table("sequence_probe", metadata, Column("id", Integer, primary_key=True), schema="envanter")
        monkeypatch.setattr(pg_transfer.Base, "metadata", metadata)
        with db.get_bind().begin() as c:
            table.create(c)
            c.execute(table.insert().values(id=900))
            pg_transfer.sync_sequences(c)
            value = c.scalar(table.insert().values().returning(table.c.id))
            assert value == 901
            assert c.scalar(select(table.c.id).order_by(table.c.id.desc()).limit(1)) == 901
            # Empty tables retain the first usable sequence value.
            c.execute(text("TRUNCATE envanter.sequence_probe RESTART IDENTITY"))
            pg_transfer.sync_sequences(c)
            assert c.scalar(table.insert().values().returning(table.c.id)) == 1
            table.drop(c)
