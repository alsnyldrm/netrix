"""Legacy AOS-S terminal spacing fixture; no device connections or persistent data."""

import hashlib

from netrix.identity.security import decrypt, encrypt
from sqlalchemy import select

from scripts import inventory_fixture as fixture

app = fixture.app
with fixture.session_factory()() as db:
    for snapshot in db.scalars(select(fixture.m.Snapshot)):
        original = decrypt(snapshot.encrypted_content)
        content = "; J9851A Configuration Editor; Created on release #KB.16.11\n" + original + "\n"
        for index in range(1, 31):
            content += f"qos udp-port ipv4 range {50000 + index * 2} {50001 + index * 2} dscp ef\n"
            if index % 5 == 0:
                content += "\n\n\n"
        snapshot.encrypted_content = encrypt(content)
        snapshot.size_bytes = len(content.encode())
        snapshot.fingerprint = hashlib.sha256(content.encode()).hexdigest()
    db.commit()
