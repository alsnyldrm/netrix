"""IP location backfill/constraints, restricted to disposable MariaDB netrix_test."""

import subprocess

from netrix.core import engine
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
migrate("check")
migrate("downgrade", "20261031_16")
with engine().begin() as db:
    for sql in (
        "INSERT INTO institutions (id,name,code,lock_version,created_at,updated_at) VALUES ('i','Fixture','I',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO sites (id,name,code,institution_id,description,timezone,created_at,updated_at) VALUES ('s','Campus','S','i','','Europe/Istanbul',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)),('s2','Campus','S2','i','','Europe/Istanbul',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO sites (id,name,code,institution_id,parent_id,description,timezone,created_at,updated_at) VALUES ('room','Room','R','i','s','','Europe/Istanbul',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('v','Fixture','',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO prefixes (id,cidr,vrf_id,description,created_at,updated_at) VALUES ('p','192.0.2.0/24','v','',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
    ):
        db.execute(text(sql))
    for suffix, location in ((1, "Room"), (2, "Campus"), (3, "Legacy text")):
        db.execute(
            text(
                "INSERT INTO ip_addresses (id,address,vrf_id,prefix_id,hostname,status,location,created_at,updated_at) VALUES (:id,:address,'v','p','server','active',:location,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
            ),
            {"id": f"ip{suffix}", "address": f"192.0.2.{suffix}", "location": location},
        )
migrate("upgrade", "head")
migrate("check")
with engine().connect() as db:
    rows = db.execute(
        text("SELECT id,institution_id,site_id,sub_site_id,location FROM ip_addresses ORDER BY id")
    ).all()
    assert tuple(rows[0]) == ("ip1", "i", "s", "room", "Room"), rows
    assert tuple(rows[1]) == ("ip2", None, None, None, "Campus"), rows
    assert tuple(rows[2]) == ("ip3", None, None, None, "Legacy text"), rows
for column in ("institution_id", "site_id", "sub_site_id"):
    try:
        with engine().begin() as db:
            db.execute(text(f"UPDATE ip_addresses SET {column}='missing' WHERE id='ip1'"))
    except IntegrityError:
        pass
    else:
        raise AssertionError(f"Missing foreign key: {column}")
assert migrate("downgrade", "20261031_16", check=False).returncode != 0
with engine().begin() as db:
    db.execute(text("UPDATE ip_addresses SET institution_id=NULL,site_id=NULL,sub_site_id=NULL"))
migrate("downgrade", "20261031_16")
migrate("upgrade", "head")
migrate("check")
assert {"ix_ip_addresses_institution_id", "ix_ip_addresses_site_id", "ix_ip_addresses_sub_site_id"}.issubset(
    {i["name"] for i in inspect(engine()).get_indexes("ip_addresses")}
)
print(
    "MariaDB IP hierarchy PASS: exact unambiguous backfill, legacy text preservation, three indexed FKs, guarded downgrade and roundtrip"
)
