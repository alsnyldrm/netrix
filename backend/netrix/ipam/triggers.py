"""Trusted job provenance shared by the API queue and worker admission checks."""

SCHEDULED_ORIGINS = {
    "ipam_ping": "ping_timer",
    "ipam_discover": "schedule",
    "integration": "scheduled_source",
}


def allowed_origin(kind, origin, requested_by=None):
    return origin == SCHEDULED_ORIGINS[kind] or (
        kind in ("ipam_ping", "ipam_discover") and origin == "manual" and bool(requested_by)
    )
