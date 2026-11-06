"""Preserve SNMP NUL padding as a visible escape in PostgreSQL text/JSONB."""

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


def postgres_value(value):
    if isinstance(value, str):
        return value.replace("\x00", "\\u0000")
    if isinstance(value, list):
        return [postgres_value(item) for item in value]
    if isinstance(value, dict):
        return {postgres_value(key): postgres_value(item) for key, item in value.items()}
    return value


class PostgreSQLValue(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, base_type):
        super().__init__()
        self.base_type = base_type
        self.impl = base_type

    def process_bind_param(self, value, dialect):
        return postgres_value(value) if dialect.name == "postgresql" else value

    def coerce_compared_value(self, op, value):
        return self.impl.coerce_compared_value(op, value)

    @property
    def python_type(self):
        return self.impl.python_type
