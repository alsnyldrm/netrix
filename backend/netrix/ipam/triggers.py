"""Trusted job provenance shared by the API queue and worker admission checks."""

# Operator-started group run: same device collection as the schedule, unlike "manual".
GROUP_MANUAL = "group_manual"
SCHEDULED_ORIGINS = {
    "ipam_ping": "ping_timer",
    "ipam_discover": "schedule",
    "integration": "scheduled_source",
    "ipam_address_scan": None,
}


def allowed_origin(kind, origin, requested_by=None):
    if requested_by and kind == "ipam_discover" and origin == GROUP_MANUAL:
        return True
    return bool(origin and origin == SCHEDULED_ORIGINS[kind]) or bool(
        requested_by and kind in ("ipam_ping", "ipam_discover", "ipam_address_scan") and origin == "manual"
    )
