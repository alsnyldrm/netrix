"""Only real ACL syslog messages from uniquely identified managed device addresses."""

import re
from datetime import datetime, timedelta
from ipaddress import ip_address

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select

from .. import models as m
from ..configuration.diff import SENSITIVE
from ..core import now, redis_client, session_factory, settings
from .service import eligible_inventory

ACL_EVENT = re.compile(r"(?i)\b(?:ACL(?:_LOG)?|IP[-_ ]?ACL|packet[- ]filter(?:ing)?|firewall)\b")
DENY = re.compile(r"(?i)\b(?:deny|denied|drop|dropped|discard|discarded)\b")
PERMIT = re.compile(r"(?i)\b(?:permit|permitted|allow|allowed)\b")
IP = r"(?:\d{1,3}\.){3}\d{1,3}"


def safe_message(value):
    # Device ACL records need no credential values. Redact from the first
    # sensitive field onward, including quoted and whitespace-delimited forms.
    sensitive = SENSITIVE.search(value)
    if sensitive:
        value = value[:sensitive.start()] + "[gizlendi]"
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", value)[:2000].strip()


def normalized_ip(value):
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def parse_message(raw):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    controller_match = bool(re.search(r"(?i)\bsrcip=" + IP, text) and re.search(r"(?i)\bdstip=" + IP, text)
                            and re.search(r"(?i)\baction=(?:deny|permit|allow)\b", text)
                            and re.search(r"(?i)\bpolicy=[A-Za-z0-9_.-]+", text))
    if not controller_match and not ACL_EVENT.search(text) and not re.search(
        r"(?i)\bList [A-Za-z0-9_.-]+,\s*seq#?\s*\d+\s+(?:denied|permitted)\b", text
    ):
        return None
    explicit_action = re.search(r"(?i)\baction\s*[=:]\s*(deny|denied|drop|dropped|discard|permit|permitted|allow|allowed)\b", text)
    action_text = explicit_action[1] if explicit_action else text
    action = "deny" if DENY.search(action_text) else "permit" if PERMIT.search(action_text) else "unknown"
    # Configuration/audit messages are never presented as packet matches.
    if action == "unknown" or re.search(r"(?i)\b(?:configure|configuration|command|created|deleted)\b", text):
        return None
    if not re.search(r"(?i)(?:ACL_LOG|packet[- ]filter|\b(?:src|srcip|source|from|denied|permitted|matched|match|drop|dropped|deny|permit)\b)", text):
        return None
    source = re.search(r"(?i)\b(?:src(?:[-_ ]?ip)?|source(?:[-_ ]?(?:ip|address))?|from)\s*[=:]?\s*(" + IP + ")", text)
    destination = re.search(r"(?i)\b(?:dst(?:[-_ ]?ip)?|dest(?:ination)?(?:[-_ ]?(?:ip|address))?|to)\s*[=:]?\s*(" + IP + ")", text)
    arrow = re.search("(" + IP + r")(?:[:/]\d+)?\s*->\s*(" + IP + ")", text)
    if arrow:
        source_address, destination_address = arrow.groups()
    else:
        source_address = source[1] if source else None
        destination_address = destination[1] if destination else None
    acl = re.search(r'(?i)\b(?:list|policy|acl(?:[-_ ]?(?:name|id|number))?)\s*[=:]?\s*["\']?([A-Za-z0-9_.-]{1,64})', text)
    acl_name = acl[1] if acl else None
    if acl_name and acl_name.casefold() in ("log", "logging", "denied", "deny", "packet", "event"):
        acl_name = None
    occurred_at = None
    timestamp = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", text)
    if timestamp:
        try:
            occurred_at = datetime.fromisoformat(timestamp[0].replace("Z", "+00:00"))
        except ValueError:
            pass
    return {
        "action": action, "acl": acl_name,
        "source_address": normalized_ip(source_address) if source_address else None,
        "destination_address": normalized_ip(destination_address) if destination_address else None,
        "occurred_at": occurred_at, "message": safe_message(text),
    }


def ingest_batch(messages):
    """Socket peer identity is authoritative. Claimed syslog hostnames are ignored."""
    peers = {peer for peer, _, _, _ in messages}
    with session_factory()() as db:
        candidates = list(db.scalars(
            eligible_inventory().where(
                m.Device.management_ip.in_(peers),
                m.Device.id.in_(select(m.ACLGroupDevice.device_id)),
            )
        ))
        by_address = {}
        for device in candidates:
            by_address.setdefault(device.management_ip, []).append(device.id)
        inserted = 0
        for peer, payload, transport, stamp in messages:
            ids = by_address.get(peer, [])
            if len(ids) != 1 or transport not in ("syslog_udp", "syslog_tcp"):
                continue
            event = parse_message(payload)
            if event is None:
                continue
            db.add(m.ACLLog(device_id=ids[0], peer_address=peer, transport=transport,
                            received_at=stamp, **event))
            inserted += 1
        db.commit()
    return inserted


def receiver_status(db):
    config = settings()
    host = config.acl_log_host or config.firmware_advertise_host
    ready, dropped = False, 0
    try:
        stamp = redis_client().get("netrix:acl_logs:heartbeat")
        ready = bool(stamp and (now() - datetime.fromisoformat(stamp)).total_seconds() < 30)
        dropped = int(redis_client().get("netrix:acl_logs:dropped") or 0)
    except Exception:
        pass
    return {
        "ready": ready, "host": host, "port": config.acl_log_port,
        "transport": "Syslog UDP/TCP", "dropped": dropped,
        "last_received_at": db.scalar(select(func.max(m.ACLLog.received_at))),
        "retention_days": 30,
    }


def list_logs(db, *, q="", device_id=None, hours=24, before=None, before_id=None, limit=50):
    conditions = []
    if hours:
        conditions.append(m.ACLLog.received_at >= now() - timedelta(hours=hours))
    if device_id:
        conditions.append(m.ACLLog.device_id == device_id)
    if q:
        conditions.append(or_(
            m.Device.name.contains(q), m.ACLLog.acl.contains(q),
            m.ACLLog.source_address.contains(q), m.ACLLog.destination_address.contains(q),
            m.ACLLog.message.contains(q),
        ))
    if bool(before) != bool(before_id):
        raise HTTPException(422, "Sayfalama konumu eksik.")
    if before:
        if before.tzinfo is None:
            raise HTTPException(422, "Sayfalama zamanı saat dilimi içermeli.")
        conditions.append(or_(
            m.ACLLog.received_at < before,
            and_(m.ACLLog.received_at == before, m.ACLLog.id < before_id),
        ))
    rows = db.execute(
        select(m.ACLLog, m.Device.name, m.Device.management_ip)
        .join(m.Device, m.Device.id == m.ACLLog.device_id)
        .where(*conditions)
        .order_by(m.ACLLog.received_at.desc(), m.ACLLog.id.desc()).limit(limit + 1)
    ).all()
    visible = rows[:limit]
    next_page = None
    if len(rows) > limit:
        next_page = {"before": visible[-1][0].received_at.isoformat(), "before_id": visible[-1][0].id}
    return {
        "items": [
            {"id": event.id, "device_id": event.device_id, "device_name": name,
             "management_ip": address, "received_at": event.received_at, "occurred_at": event.occurred_at,
             "peer_address": event.peer_address, "transport": event.transport, "acl": event.acl,
             "source_address": event.source_address, "destination_address": event.destination_address,
             "action": event.action, "message": event.message}
            for event, name, address in visible
        ],
        "next": next_page, "receiver": receiver_status(db),
    }


def prune():
    with session_factory()() as db:
        expired = select(m.ACLLog.id).where(m.ACLLog.received_at < now() - timedelta(days=30)).limit(10000)
        db.execute(delete(m.ACLLog).where(m.ACLLog.id.in_(expired)))
        db.commit()
