"""Physical device location derived from its shared cabinet placement."""

from sqlalchemy import select
from sqlalchemy.orm import aliased

from .. import models as m


def device_location(db, device_id):
    location, room = aliased(m.Site), aliased(m.Site)
    row = (
        db.execute(
            select(
                location.name.label("site_name"),
                room.floor_number,
                room.department_name,
                room.name.label("room_name"),
                m.Cabinet.name.label("cabinet_number"),
                m.RackPlacement.start_unit,
            )
            .select_from(m.RackPlacement)
            .join(m.Cabinet, m.Cabinet.id == m.RackPlacement.cabinet_id)
            .outerjoin(location, location.id == m.Cabinet.site_id)
            .outerjoin(room, room.id == m.Cabinet.sub_site_id)
            .where(m.RackPlacement.device_id == device_id)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None
