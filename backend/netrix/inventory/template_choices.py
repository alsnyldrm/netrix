"""Public, current workbook choices; never load credential payloads."""

from collections import Counter

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..schemas import DeviceInput
from .csv_transfer import ENUMS, FIELDS, REFERENCES, normalized

MAX_CHOICES = 32767


def bounded(db, statement):
    rows = db.execute(statement.limit(MAX_CHOICES + 1)).all()
    if len(rows) > MAX_CHOICES:
        raise HTTPException(
            422, "Excel seçim listesi çok büyük; bir alanda en fazla 32767 farklı seçenek desteklenir"
        )
    return rows


def reference_choices(rows):
    counts = Counter(normalized(name) for _, name in rows)
    # Names can collide (e.g. two sites). IDs remain valid import values.
    return [name if counts[normalized(name)] == 1 else id for id, name in rows]


def template_choices(db):
    choices = {}
    for key, model in REFERENCES.items():
        statement = select(model.code if model is m.DeviceType else model.id, model.name)
        if model is m.Credential:
            protocols = ("snmpv3", "snmpv2c") if key == "snmp_credential_id" else ("ssh", "rest")
            statement = statement.where(m.Credential.protocol.in_(protocols))
        choices[key] = reference_choices(bounded(db, statement.order_by(model.name, model.id)))
    for key in FIELDS:
        if key in choices:
            continue
        if key in ENUMS:
            choices[key] = list(ENUMS[key].values())
        elif key in ("ssh_trust_host_key", "monitoring_enabled"):
            choices[key] = ["Hayır", "Evet"]
        else:
            column = getattr(m.Device, key)
            rows = bounded(db, select(column).where(m.Device.archived.is_(False)).distinct().order_by(column))
            values = [str(value) for (value,) in rows if value is not None and str(value).strip()]
            field = DeviceInput.model_fields[key]
            if not field.is_required() and field.default is not None and str(field.default).strip():
                default = str(field.default)
                if default not in values:
                    values.insert(0, default)
            choices[key] = values
    # Keep the example's adapter compatible with its selected SSH/API profile.
    if choices["config_credential_id"]:
        first = choices["config_credential_id"][0]
        protocol = db.scalar(
            select(m.Credential.protocol)
            .where((m.Credential.name == first) | (m.Credential.id == first))
            .order_by(m.Credential.name, m.Credential.id)
            .limit(1)
        )
        choices["_example_adapter"] = "rest" if protocol == "rest" else "ios"
    return choices
