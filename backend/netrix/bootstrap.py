"""Seed an empty installation after migrations; preserve populated installations."""

from sqlalchemy import func, select

from . import models as m
from .core import session_factory
from .inventory.device_types import seed_defaults


def bootstrap():
    with session_factory()() as db:
        if db.scalar(select(func.count()).select_from(m.User)) == 0:
            seed_defaults(db)
            if not db.get(m.SystemState, "setup"):
                db.add(m.SystemState(key="setup", value="pending"))
            db.commit()


if __name__ == "__main__":
    bootstrap()
