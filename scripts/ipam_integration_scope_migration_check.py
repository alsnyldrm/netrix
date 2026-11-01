"""Validate removal on disposable MariaDB; preserve inventory and supported secrets."""

import subprocess

from netrix.core import engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(action, revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", action, revision], check=True)


migrate("upgrade", "20261101_23")
with engine().begin() as db:
    for kind in ("vcenter", "windows_dhcp", "corner_switch", "backbone_switch", "firewall"):
        db.execute(
            text(
                "INSERT INTO integrations (id,name,kind,host,port,encrypted_secret,enabled,verify_tls,interval_seconds,created_at,updated_at) VALUES (:kind,:kind,:kind,'192.0.2.1',443,:secret,1,1,600,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
            ),
            {"kind": kind, "secret": "fixture-ciphertext-" + kind},
        )
        db.execute(
            text(
                "INSERT INTO jobs (id,kind,target_id,status,progress,total,error,cancel_requested,active_key,created_at,updated_at,attempts,result,available_at) VALUES (:kind,'integration',:kind,'queued',0,0,'',0,CONCAT('integration:',:kind),UTC_TIMESTAMP(),UTC_TIMESTAMP(),0,'{}',UTC_TIMESTAMP())"
            ),
            {"kind": kind},
        )
    db.execute(
        text(
            "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('vrf','Fixture','',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO vlans (id,name,domain,vid,vrf_id,cidr,scan_authorized,created_at,updated_at) VALUES ('vlan','Fixture','fixture',123,'vrf','192.0.2.0/24',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO ip_addresses (id,address,vrf_id,vlan_id,status,hostname,created_at,updated_at) VALUES ('ip','192.0.2.1','vrf','vlan','active','Retained',UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    for kind in ("windows_dhcp", "corner_switch", "backbone_switch", "firewall"):
        db.execute(
            text(
                "INSERT INTO ip_observations (id,address_id,source,source_key,data,observed_at,created_at,updated_at) VALUES (:kind,'ip',:kind,:kind,'{}',UTC_TIMESTAMP(),UTC_TIMESTAMP(),UTC_TIMESTAMP())"
            ),
            {"kind": kind},
        )
    before_devices = db.scalar(text("SELECT COUNT(*) FROM devices"))
    before_credentials = db.scalar(text("SELECT COUNT(*) FROM credentials"))
migrate("upgrade", "head")
with engine().connect() as db:
    assert dict(db.execute(text("SELECT kind,encrypted_secret FROM integrations")).all()) == {
        k: "fixture-ciphertext-" + k for k in ("vcenter", "windows_dhcp")
    }
    assert db.execute(text("SELECT source FROM ip_observations")).scalars().all() == ["windows_dhcp"]
    assert db.scalar(text("SELECT hostname FROM ip_addresses WHERE id='ip'")) == "Retained"
    assert db.scalar(text("SELECT COUNT(*) FROM devices")) == before_devices
    assert db.scalar(text("SELECT COUNT(*) FROM credentials")) == before_credentials
    assert (
        db.scalar(
            text(
                "SELECT COUNT(*) FROM jobs WHERE target_id IN ('corner_switch','backbone_switch','firewall') AND status='cancelled' AND active_key IS NULL AND cancel_requested=1"
            )
        )
        == 3
    )
    assert (
        db.scalar(
            text(
                "SELECT COUNT(*) FROM jobs WHERE target_id IN ('vcenter','windows_dhcp') AND status='queued'"
            )
        )
        == 2
    )
    for kind in ("corner_switch", "backbone_switch", "firewall"):
        try:
            db.execute(text("UPDATE integrations SET kind=:kind WHERE id='vcenter'"), {"kind": kind})
            raise AssertionError("Unsupported integration accepted")
        except (IntegrityError, OperationalError) as error:
            assert error.orig.args[0] == 4025
            db.rollback()
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
migrate("downgrade", "20261101_23")
migrate("upgrade", "head")
print(
    "PASS: removed network sources/jobs/evidence, preserved DHCP/VMware ciphertext, IPs and inventory; schema parity and round trip"
)
