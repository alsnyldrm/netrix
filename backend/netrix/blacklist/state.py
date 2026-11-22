"""Desired blacklist content per device, compared with the last verified device state.

Desired state comes only from SQL: active groups, their member devices and
active IPv4 entries. A device sync job makes the NETRIX ACL equal to it; an
an active group keeps its ACL even without IP entries.
"""

from dataclasses import dataclass, field
from ipaddress import ip_address

from sqlalchemy import delete, select, update

from .. import models as m
from .service import device_family, eligible_inventory


@dataclass
class Desired:
    device_id: str
    family: str | None = None
    profile: dict | None = None
    addresses: set = field(default_factory=set)
    group_ids: set = field(default_factory=set)
    issue: str = ""

    def key(self):
        return (self.profile, sorted(self.addresses))


def profile_key(profile):
    return (profile["type"], profile.get("name"), profile.get("number")) if profile else None


def desired_state(db, device_ids=None):
    """Return {device_id: Desired} for devices in active groups or with a recorded state."""
    member_rows = select(m.ACLGroupDevice.group_id, m.ACLGroupDevice.device_id).join(
        m.ACLGroup, m.ACLGroup.id == m.ACLGroupDevice.group_id
    ).where(m.ACLGroup.status == "active")
    state_ids = select(m.DeviceACLState.device_id)
    if device_ids is not None:
        member_rows = member_rows.where(m.ACLGroupDevice.device_id.in_(device_ids))
        state_ids = state_ids.where(m.DeviceACLState.device_id.in_(device_ids))
    members = {}
    for group_id, device_id in db.execute(member_rows):
        members.setdefault(device_id, set()).add(group_id)
    all_ids = set(members) | set(db.scalars(state_ids))
    groups = {group.id: group for group in db.scalars(select(m.ACLGroup).where(m.ACLGroup.status == "active"))}
    addresses = {}
    for group_id, address in db.execute(
        select(m.BlacklistEntryGroup.group_id, m.BlacklistEntry.address)
        .join(m.BlacklistEntry, m.BlacklistEntry.id == m.BlacklistEntryGroup.entry_id)
        .where(m.BlacklistEntry.status == "active")
    ):
        if ip_address(address).version == 4:
            addresses.setdefault(group_id, set()).add(address)
    eligible = {
        device.id: device_family(device)
        for device in db.scalars(eligible_inventory().where(m.Device.id.in_(all_ids)))
    }
    result = {}
    for device_id in all_ids:
        item = Desired(device_id, eligible.get(device_id))
        group_ids = members.get(device_id, set())
        if not item.family:
            item.issue = "Cihaz artık aktif ve uygun bir Kara Liste hedefi değil."
            result[device_id] = item
            continue
        profiles = {}
        for group_id in group_ids:
            profile = groups[group_id].profiles.get(item.family)
            if not profile:
                item.issue = "Cihaz ailesinin ACL bilgisi eksik."
                continue
            profiles.setdefault(profile_key(profile), profile)
            item.group_ids.add(group_id)
            item.addresses |= addresses.get(group_id, set())
        if len(profiles) > 1:
            item.issue = "Aynı cihazın tüm portları için tek ACL seçin. Gruplardaki ACL kimlikleri çakışıyor."
        elif profiles:
            item.profile = next(iter(profiles.values()))
        result[device_id] = item
    return result


def states(db, device_ids=None):
    query = select(m.DeviceACLState)
    if device_ids is not None:
        query = query.where(m.DeviceACLState.device_id.in_(device_ids))
    return {row.device_id: row for row in db.scalars(query)}


def in_sync(desired, state):
    """True when the verified device content equals the desired content."""
    if state is None:
        return desired.profile is None
    if state.status != "synced":
        return False
    if desired.profile is None:
        return False  # No group wants this ACL anymore.
    return profile_key(state.profile) == profile_key(desired.profile) and set(state.addresses) == set(
        desired.addresses
    )


def held(state):
    """Addresses and groups that may still be present on the device."""
    addresses, group_ids = set(state.addresses or []), set(state.group_ids or [])
    if state.status == "dirty" and state.attempted:
        addresses |= set(state.attempted.get("addresses", []))
        group_ids |= set(state.attempted.get("group_ids", []))
    return addresses, group_ids


def devices_holding(db, *, address=None, group_id=None):
    result = set()
    for row in db.scalars(select(m.DeviceACLState)):
        addresses, group_ids = held(row)
        if (address and address in addresses) or (group_id and group_id in group_ids):
            result.add(row.device_id)
    return result


def finalize_deletions(db):
    """Delete entries and groups whose removal is verified on every device."""
    held_addresses, held_groups = set(), set()
    for row in db.scalars(select(m.DeviceACLState)):
        addresses, group_ids = held(row)
        held_addresses |= addresses
        held_groups |= group_ids
    removed = 0
    for entry in db.scalars(select(m.BlacklistEntry).where(m.BlacklistEntry.status == "deleting")):
        if entry.address in held_addresses:
            continue
        db.execute(
            update(m.BlacklistDelivery).where(m.BlacklistDelivery.entry_id == entry.id).values(entry_id=None)
        )
        db.execute(delete(m.BlacklistEntryGroup).where(m.BlacklistEntryGroup.entry_id == entry.id))
        db.delete(entry)
        removed += 1
    for group in db.scalars(select(m.ACLGroup).where(m.ACLGroup.status == "deleting")):
        if group.id in held_groups:
            continue
        db.execute(delete(m.BlacklistEntryGroup).where(m.BlacklistEntryGroup.group_id == group.id))
        db.execute(delete(m.ACLGroupDevice).where(m.ACLGroupDevice.group_id == group.id))
        db.delete(group)
        removed += 1
    db.flush()
    return removed
