"""Disposable local audit journal fixture; no workers or actual network reads."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("vlan_configuration_fixture.py")))

from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.identity.security import audit, hasher  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8242"
settings.cache_clear()
with session_factory()() as db:
    owner = db.scalar(select(m.User))
    owner.display_name = "Ayşe Yönetici"
    operator = m.User(
        email="mehmet@example.test",
        display_name="Mehmet Operatör",
        role="operator",
        password_hash=hasher.hash("browser-fixture-password"),
    )
    db.add(operator)
    db.commit()
    for index in range(27):
        db.info["audit_actor"] = owner if index % 2 == 0 else operator
        row = m.Institution(name=f"Kampüs {index}", code=f"AUD{index}")
        db.add(row)
        db.commit()
    db.info["audit_actor"] = operator
    row.name = "Yeni kampüs"
    db.commit()
    db.info.pop("audit_actor", None)
    db.add(
        m.Audit(
            actor_id=owner.id,
            action="update",
            entity_type="institutions",
            entity_id=row.id,
            summary="Geçmiş kayıt: kampüs bilgisi düzenlendi",
            details=None,
        )
    )
    audit(db, None, "enqueue", "jobs", None, "ipam_ping görevi kuyruğa alındı")
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8242, log_level="warning")
