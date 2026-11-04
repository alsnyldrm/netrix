"""Address matrix fixture with a second, paginated VLAN and no protocol jobs."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("ipam_allocation_fixture.py")))
from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory  # noqa: E402
from sqlalchemy import select  # noqa: E402

with session_factory()() as db:
    source = db.scalar(select(m.VLAN))
    db.add(
        m.VLAN(
            name="BACKUP",
            vid=30,
            cidr="198.18.0.0/23",
            vrf_id=source.vrf_id,
            institution_id=source.institution_id,
            site_id=source.site_id,
        )
    )
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8247, log_level="warning")
