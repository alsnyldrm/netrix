"""Transaction-local audit capture for authenticated application writes.

Explicit domain audit messages and ORM field changes share one journal entry.
Workers have no request actor and therefore cannot impersonate a user's edit.
Only allowlisted public scalar fields are copied; secret values never enter JSON.
"""

from datetime import datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .. import models as m

RESOURCES = {
    m.User: "users",
    m.Institution: "institutions",
    m.Site: "sites",
    m.Cabinet: "cabinets",
    m.VRF: "vrfs",
    m.VLAN: "vlans",
    m.IPAMScanGroup: "ipam_scan_groups",
    m.Credential: "credentials",
    m.BackupGroup: "backup-groups",
    m.DeviceType: "device-types",
    m.Device: "devices",
    m.Interface: "interfaces",
    m.DNSServer: "dns-servers",
    m.Integration: "integrations",
    m.IPAddress: "addresses",
    m.Scope: "scopes",
    m.FirmwareImage: "firmware_images",
    m.FirmwareGroup: "firmware_groups",
    m.FirmwarePlan: "firmware_plans",
    m.Link: "links",
    m.Snapshot: "snapshots",
    m.AlertRule: "rules",
    m.Alert: "alerts",
    m.RackPlacement: "rack_placements",
    m.RackAccessory: "rack_accessories",
    m.PatchPanel: "patch_panels",
    m.PatchPort: "patch_ports",
    m.OperatingSystem: "operating-systems",
    m.UserWorkspace: "user_workspaces",
    m.UserSSHProfile: "user_ssh_profile",
    m.AccessGroup: "access_group",
}
# Deliberately do not serialize arbitrary JSON, protocol evidence, commands or content.
PUBLIC_FIELDS = set(
    """
name code description email display_name role ssh_access is_active institution_id site_id sub_site_id
parent_id timezone floor_number department_name units cabinet_id device_id start_unit kind vrf_id vid
domain cidr enabled ping_enabled ping_interval scan_group_id interval_seconds schedule_enabled
protocol vendor model management_ip hostname mac_address status interface_id address location
operating_system_id operating_system cabinet lifecycle_status archived backup_interval backup_group_id adapter snmp_port config_port
snmp_credential_id config_credential_id ssh_trust_host_key identity_path is_gateway credential_id
is_managed is_deleted admin_status oper_status dns_server_id port host username url verify_tls
manual_remote_name manual_remote_port remote_device_id auto_add_excluded is_current base_snapshot_id
acknowledged_at acknowledged_by owner_id ssh_profile_id target_version strategy concurrency
timeout_seconds retry_limit scan_enabled scan_interval warning_threshold scan_authorized dns_enabled
dns_timeout dns_concurrency dns_server dns_port dns_transport zone scope_id vlan_id vlan_vid
frequency repeat_every start_at run_limit mode available_at cancel_requested severity event_kind
family version original_name size_bytes notes floor_number department_name force_stop_requested deleted_at
""".split()
)
ALIASES = {"device": "devices", "user": "users"}


def actor_snapshot(user):
    return {"name": user.display_name, "email": user.email} if user else {}


def record(db, user, action, entity_type, entity_id, summary, *, automatic=False):
    resource = ALIASES.get(entity_type, entity_type)
    entries = db.info.setdefault("audit_entries", {})
    key = (user.id if user else None, resource, entity_id)
    entry = entries.get(key)
    # Separate explicit actions remain separate; a field capture can be enriched
    # by the domain action even when an autoflush already inserted its audit row.
    if entry is None or (not automatic and not getattr(entry, "_automatic", False)):
        entry = m.Audit(
            actor_id=user.id if user else None,
            action=action,
            entity_type=resource,
            entity_id=entity_id,
            summary=summary[:400],
            details={"actor": actor_snapshot(user)},
        )
        entry._automatic = automatic
        entries[key] = entry
        db.add(entry)
    elif not automatic:
        entry.action, entry.summary, entry._automatic = action, summary[:400], False
    return entry


def scalar(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:400]


def preference_changes(previous, current):
    """Validate the public settings shape before copying any JSON values."""
    from ..access.schemas import Preferences

    def public(data):
        if data is None:
            return {}
        try:
            parsed = Preferences.model_validate(data).model_dump()
        except ValueError:
            return {}
        terminal = parsed.pop("terminal")
        return {**parsed, **{"terminal." + key: val for key, val in terminal.items()}}

    old, new = public(previous), public(current)
    return {
        "preferences." + key: {"previous": scalar(old.get(key)), "current": scalar(new.get(key))}
        for key in old.keys() | new.keys()
        if old.get(key) != new.get(key)
    }


@event.listens_for(Session, "before_flush")
def capture_changes(db, *_):
    actor = db.info.get("audit_actor")
    if actor is None:
        return
    for row in list(db.new) + list(db.dirty) + list(db.deleted):
        resource = RESOURCES.get(type(row))
        if not resource:
            continue
        state = inspect(row)
        deleted, created = row in db.deleted, row in db.new
        changes = {}
        for col in state.mapper.column_attrs:
            key = col.key
            history = state.attrs[key].history
            if not deleted and not history.has_changes():
                continue
            if isinstance(row, m.UserWorkspace) and key == "preferences":
                previous = history.deleted[0] if history.deleted else None
                changes.update(preference_changes(previous, None if deleted else row.preferences))
            elif key.startswith("encrypted_") or key == "password_hash":
                changes["protected_values"] = {"previous": "Gizli", "current": "Güncellendi"}
            elif key in PUBLIC_FIELDS:
                previous = history.deleted[0] if history.deleted else (getattr(row, key) if deleted else None)
                current = None if deleted else getattr(row, key)
                if previous != current:
                    changes[key] = {"previous": scalar(previous), "current": scalar(current)}
        if not changes and not (created or deleted or db.is_modified(row, include_collections=False)):
            continue
        if hasattr(row, "id") and not row.id:
            row.id = m.uid()
        entity_id = getattr(row, "id", None) or getattr(row, "user_id", None)
        action = "delete" if deleted else "create" if created else "update"
        entry = record(
            db,
            actor,
            action,
            resource,
            entity_id,
            "Kayıt "
            + {
                "delete": "silindi",
                "create": "oluşturuldu",
                "update": "güncellendi",
            }[action],
            automatic=True,
        )
        details = dict(entry.details or {})
        combined = dict(details.get("changes", {}))
        for key, change in changes.items():
            combined[key] = {"previous": combined.get(key, change)["previous"], "current": change["current"]}
        details["changes"] = combined
        details["target"] = next(
            (
                str(getattr(row, key))
                for key in ("name", "address", "display_name", "hostname")
                if getattr(row, key, None)
            ),
            entity_id,
        )
        if isinstance(row, m.UserWorkspace):
            details["target"] = actor.display_name
        if getattr(entry, "_automatic", False):
            from .audit_read import RESOURCE_LABELS

            entry.summary = (
                f"{RESOURCE_LABELS.get(resource, 'Kayıt')} “{details['target']}” "
                + {"create": "oluşturuldu", "update": "güncellendi", "delete": "silindi"}[action]
            )[:400]
        entry.details = details


@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def clear_entries(db):
    db.info.pop("audit_entries", None)
