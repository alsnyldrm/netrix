"""Connection management belongs to inventory devices, not IPAM rack endpoints."""

from sqlalchemy import and_, or_, select

from .. import models as m


def inventory_links(*, include_archived=False):
    from .link_edits import peer_column

    devices = select(m.Device.id).where(m.Device.discovery_scope_id.is_not(None)).correlate(None)
    if not include_archived:
        devices = devices.where(m.Device.archived.is_(False))
    # Unresolved protocol evidence still belongs to its inventory source. A
    # resolved peer must also be inventory-owned, including manual overrides.
    peer = peer_column()
    return and_(m.Link.device_id.in_(devices), or_(peer.is_(None), peer.in_(devices)))
