"""Disposable browser fixture; no worker, scheduler, or network device access."""

import json

from inventory_fixture import app  # noqa: F401 (shared disposable app and DB)
from netrix import models as m
from netrix.core import session_factory
from netrix.identity.security import encrypt
from sqlalchemy import select

with session_factory()() as db:
    institutions = [
        m.Institution(name="Kuzey Üniversitesi", code="KU"),
        m.Institution(name="Güney Üniversitesi", code="GU"),
    ]
    db.add_all(institutions)
    db.flush()
    north = db.scalar(select(m.Site))
    north.institution_id = institutions[0].id
    db.add(m.Site(name="Güney Kampüs", code="G", institution_id=institutions[1].id))
    for name, protocol, secret in (
        (
            "Merkez SNMP",
            "snmpv3",
            {"username": "fixture", "auth_key": "fixture-auth", "priv_key": "fixture-priv"},
        ),
        ("Şube SNMP", "snmpv2c", {"community": "fixture-community"}),
    ):
        db.add(m.Credential(name=name, protocol=protocol, encrypted_secret=encrypt(json.dumps(secret))))
    db.commit()
