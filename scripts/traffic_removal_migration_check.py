"""Exercise permanent cleanup on disposable MariaDB, including shared provenance."""

import subprocess

from netrix.core import engine
from sqlalchemy import inspect, text

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "20261031_19"], check=True)
with engine().begin() as db:
    db.execute(
        text(
            "INSERT INTO jobs (id,created_at,updated_at,kind,target_id,status,progress,total,attempts,error,result,cancel_requested,available_at) "
            "VALUES ('old-job',NOW(),NOW(),'monitor','fixture','succeeded',1,1,1,'','{}',0,NOW()), "
            "('old-live',NOW(),NOW(),'ipam_live','fixture','queued',0,1,0,'','{}',0,NOW())"
        )
    )
    db.execute(
        text(
            "INSERT INTO discovery_observations (id,created_at,updated_at,job_id,address,source,evidence,confidence) "
            "VALUES ('old-evidence',NOW(),NOW(),'old-job','192.0.2.1','snmpv3','{}',1)"
        )
    )
    db.execute(
        text(
            "INSERT INTO alert_rules (id,created_at,updated_at,name,metric,threshold,recovery_threshold,duration_seconds,severity,enabled) "
            "VALUES ('old-rule',NOW(),NOW(),'Traffic','utilization',80,70,0,'warning',1), "
            "('config-rule',NOW(),NOW(),'Config','config_change',80,70,0,'warning',1)"
        )
    )
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with engine().connect() as db:
    inspector = inspect(db)
    assert not {"ip_traffic", "interface_samples"} & set(inspector.get_table_names())
    for table in ("devices", "interfaces"):
        assert not {"monitoring_enabled", "monitor_interval", "last_monitor_at"} & {
            c["name"] for c in inspector.get_columns(table)
        }
    assert db.scalar(text("SELECT COUNT(*) FROM jobs WHERE kind IN ('monitor','ipam_live')")) == 0
    assert db.scalar(text("SELECT kind FROM jobs WHERE id='old-job'")) == "inventory_import"
    assert db.scalar(text("SELECT COUNT(*) FROM discovery_observations WHERE id='old-evidence'")) == 1
    assert db.scalar(text("SELECT COUNT(*) FROM alert_rules WHERE id='old-rule'")) == 0
    assert db.scalar(text("SELECT COUNT(*) FROM alert_rules WHERE id='config-rule'")) == 1
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print("PASS: removed tables/columns/jobs/rules; preserved shared inventory provenance and config rules")
