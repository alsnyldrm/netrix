from sqlalchemy import select

from ..core import now
from ..models import Alert, AlertRule, Event


def evaluate(db, device, metric, value):
    rules = db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True), AlertRule.metric == metric)).all()
    for rule in rules:
        key = f"{rule.id}:{device.id}"
        existing = db.scalar(select(Alert).where(Alert.active_key == key))
        triggered = (
            (value == 0)
            if metric == "availability"
            else value >= rule.threshold
            if metric in ("utilization", "no_data")
            else bool(value)
        )
        recovered = (
            (value == 1)
            if metric == "availability"
            else value <= rule.recovery_threshold
            if metric == "utilization"
            else not triggered
        )
        if triggered:
            if not existing:
                existing = Alert(
                    rule_id=rule.id,
                    device_id=device.id,
                    active_key=key,
                    severity=rule.severity,
                    state="pending",
                    message=f"{device.name}: {rule.name}",
                    observed_value=value,
                )
                db.add(existing)
                db.flush()
            existing.observed_value = value
            if (
                existing.state == "pending"
                and (now() - existing.created_at).total_seconds() >= rule.duration_seconds
            ):
                existing.state = "firing"
                db.add(
                    Event(
                        device_id=device.id,
                        kind="alert_firing",
                        message=existing.message,
                        details={"alert_id": existing.id, "severity": rule.severity},
                    )
                )
        elif existing and recovered:
            existing.state, existing.active_key, existing.resolved_at = "resolved", None, now()
            db.add(
                Event(
                    device_id=device.id,
                    kind="alert_resolved",
                    message=existing.message,
                    details={"alert_id": existing.id},
                )
            )
