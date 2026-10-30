"""Bounded, atomic device CSV transfer. Credential payloads are never read."""

import csv
import io
import unicodedata

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..identity.security import audit

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
REQUIRED = {"name", "management_ip", "vrf_id"}
FIELDS = {
    "name": "Cihaz adı",
    "management_ip": "Yönetim IP adresi",
    "vrf_id": "VRF",
    "site_id": "Lokasyon",
    "vendor": "Üretici",
    "kind": "Cihaz türü",
    "model": "Model",
    "lifecycle_status": "Yaşam döngüsü",
    "adapter": "Adaptör",
    "snmp_credential_id": "SNMP profili",
    "config_credential_id": "SSH / API profili",
    "snmp_port": "SNMP portu",
    "config_port": "SSH / HTTPS portu",
    "ssh_trust_host_key": "Anahtara güven",
    "config_path": "Konfigürasyon yolu",
    "identity_path": "Cihaz bilgisi yolu",
    "monitoring_enabled": "Zamanlanmış izleme",
    "monitor_interval": "İzleme aralığı",
    "backup_interval": "Yedekleme aralığı",
    "backup_group_id": "Yedek grubu",
    "backup_retention": "En fazla yedek sayısı",
}
SECRETS = {
    "ssh_password": "SSH parolası",
    "api_token": "API token",
    "snmp_auth_key": "SNMP kimlik doğrulama anahtarı",
    "snmp_priv_key": "SNMP gizlilik anahtarı",
    "snmp_community": "SNMP community",
}
REFERENCES = {
    "vrf_id": m.VRF,
    "site_id": m.Site,
    "snmp_credential_id": m.Credential,
    "config_credential_id": m.Credential,
    "backup_group_id": m.BackupGroup,
}
ENUMS = {
    "kind": {
        "switch": "Switch",
        "router": "Router",
        "firewall": "Firewall",
        "server": "Sunucu",
        "other": "Diğer",
    },
    "lifecycle_status": {
        "active": "Aktif",
        "planned": "Planlandı",
        "maintenance": "Bakımda",
        "retired": "Arşiv",
    },
}


def normalized(value):
    return unicodedata.normalize("NFKC", value).strip().casefold().replace("\u0307", "")


def safe_cell(value):
    """Prevent spreadsheet formulas, including formulas after leading whitespace."""
    if value is None:
        return ""
    text = str(value)
    if (
        text.startswith("'")
        or text.lstrip().startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
    ):
        return "'" + text
    return text


def unescape_cell(value):
    if value.startswith("'") and safe_cell(value[1:]) == value:
        return value[1:]
    return value


def render(rows, *, is_template=False):
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(
        [
            label + (" *" if is_template and key in REQUIRED else "")
            for key, label in {**FIELDS, **SECRETS}.items()
        ]
    )
    for row in rows:
        writer.writerow([safe_cell(row.get(key)) for key in (*FIELDS, *SECRETS)])
    return "\ufeff" + output.getvalue()


def template():
    return render(
        [
            {
                "name": "Cihaz-01",
                "management_ip": "192.0.2.10",
                "vrf_id": "Global",
            }
        ],
        is_template=True,
    )


def reference_rows(db):
    # Select only public columns: even an encrypted secret must not enter an export.
    return {model: db.execute(select(model.id, model.name)).all() for model in set(REFERENCES.values())}


def export_devices(db, ids, user, *, file_format="csv"):
    ids = list(dict.fromkeys(ids))
    devices = db.scalars(
        select(m.Device)
        .where(m.Device.id.in_(ids), m.Device.archived.is_(False))
        .order_by(m.Device.name, m.Device.id)
    ).all()
    if len(devices) != len(ids):
        raise HTTPException(404, "Seçilen cihazlardan biri bulunamadı")
    refs = {model: dict(rows) for model, rows in reference_rows(db).items()}
    snmp_versions = dict(db.execute(select(m.Credential.id, m.Credential.protocol)).all())
    rows = []
    for device in devices:
        row = {key: getattr(device, key) for key in FIELDS}
        for key, model in REFERENCES.items():
            row[key] = refs[model].get(row[key], "")
        for key in ("ssh_trust_host_key", "monitoring_enabled"):
            row[key] = "true" if row[key] else "false"
        if device.snmp_credential_id:
            if snmp_versions.get(device.snmp_credential_id) == "snmpv2c":
                row["snmp_community"] = "********"
            else:
                row.update(snmp_auth_key="********", snmp_priv_key="********")
        if device.config_credential_id:
            row["api_token" if device.adapter == "rest" else "ssh_password"] = "********"
        rows.append(row)
    audit(
        db,
        user,
        f"{file_format}_export",
        "devices",
        None,
        f"{len(rows)} cihaz {file_format.upper()} olarak dışa aktarıldı",
    )
    db.commit()
    return render(rows)


def parse(content):
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "CSV dosyası en fazla 1 MiB olabilir")
    if "\x00" in content:
        raise HTTPException(422, "CSV dosyasında geçersiz karakter var")
    content = content.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content, newline=""), dialect=dialect, strict=True)
    aliases = {normalized(label): key for key, label in {**FIELDS, **SECRETS}.items()}
    aliases.update({normalized(key): key for key in (*FIELDS, *SECRETS)})
    aliases.update({normalized(FIELDS[key] + " *"): key for key in REQUIRED})
    aliases[normalized("SNMPv3 profili")] = "snmp_credential_id"
    try:
        header = next(reader)
        keys = [aliases.get(normalized(cell)) for cell in header]
        if not keys or None in keys or len(set(keys)) != len(keys):
            raise HTTPException(422, "Bilinmeyen veya yinelenen sütun başlığı var; CSV şablonunu kullanın")
        if not {"name", "management_ip", "vrf_id"}.issubset(keys):
            raise HTTPException(422, "Cihaz adı, Yönetim IP adresi ve VRF sütunları gerekli")
        rows = []
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise HTTPException(422, "Tek dosyada en fazla 500 cihaz içe aktarılabilir")
            if len(cells) != len(keys):
                raise HTTPException(422, f"CSV satır {reader.line_num}: sütun sayısı başlıkla eşleşmiyor")
            rows.append((reader.line_num, {key: unescape_cell(value) for key, value in zip(keys, cells)}))
        if not rows:
            raise HTTPException(422, "CSV dosyasında cihaz satırı bulunamadı")
        return rows
    except (csv.Error, StopIteration):
        raise HTTPException(422, "CSV okunamadı; UTF-8 CSV şablonunu kullanın") from None


def validate(db, raw):
    refs = reference_rows(db)
    errors, valid, seen = [], [], set()
    for line, cells in raw:
        try:
            for key in SECRETS:
                value = cells.get(key, "").strip()
                if value and set(value) != {"*"}:
                    raise HTTPException(
                        422,
                        "Parola ve anahtar sütunları boş veya yıldızlı olmalı; kayıtlı erişim profili kullanın",
                    )
            data = {key: value.strip() for key, value in cells.items() if key in FIELDS and value.strip()}
            for key, model in REFERENCES.items():
                if key not in data:
                    continue
                matches = [
                    id
                    for id, name in refs[model]
                    if id == data[key] or normalized(name) == normalized(data[key])
                ]
                if len(matches) != 1:
                    raise HTTPException(
                        422,
                        FIELDS[key] + ": eşleşen tek bir kayıt bulunamadı; adı veya kayıt kimliğini kullanın",
                    )
                data[key] = matches[0]
            for key, choices in ENUMS.items():
                if key in data:
                    data[key] = next(
                        (
                            k
                            for k, label in choices.items()
                            if normalized(data[key]) in (normalized(k), normalized(label))
                        ),
                        data[key],
                    )
            for key in ("ssh_trust_host_key", "monitoring_enabled"):
                if key in data:
                    data[key] = {"evet": True, "etkin": True, "hayır": False, "kapalı": False}.get(
                        normalized(data[key]), data[key]
                    )
            data = s.DeviceInput.model_validate(data).model_dump()
            svc.validate_relations(db, "devices", data, lock=False)
            identity = (data["vrf_id"], data["management_ip"])
            if identity in seen:
                raise HTTPException(422, "Dosyada aynı VRF ve IP adresi birden fazla kez var")
            seen.add(identity)
            if db.scalar(
                select(m.Device.id)
                .where(m.Device.vrf_id == identity[0], m.Device.management_ip == identity[1])
                .limit(1)
            ):
                raise HTTPException(
                    422, "Bu VRF ve IP adresinde zaten cihaz var; mevcut kayıtlar değiştirilmez"
                )
            valid.append((line, data))
        except ValidationError as exc:
            for error in exc.errors(include_input=False, include_url=False):
                key = str(error["loc"][0]) if error["loc"] else ""
                errors.append(
                    {
                        "row": line,
                        "field": FIELDS.get(key, "Cihaz"),
                        "message": "Değer eksik veya geçersiz; şablondaki alan biçimini ve sınırlarını kontrol edin",
                    }
                )
        except HTTPException as exc:
            errors.append({"row": line, "field": "Cihaz", "message": str(exc.detail)})
    return valid, errors


def import_devices(db, content, apply, user, *, test_after=False, file_format="csv"):
    raw = parse(content)
    valid, errors = validate(db, raw)
    if errors:
        return {"total": len(raw), "valid": len(valid), "imported": 0, "errors": errors, "preview": []}
    if not apply:
        return {
            "total": len(raw),
            "valid": len(valid),
            "imported": 0,
            "errors": [],
            "preview": [
                {
                    "row": line,
                    "name": data["name"],
                    "management_ip": data["management_ip"],
                    "kind": data["kind"],
                }
                for line, data in valid
            ],
        }
    # Stable ordering and the existing VRF write barrier protect duplicate checks on Galera.
    for vrf in sorted({data["vrf_id"] for _, data in valid}):
        svc.lock_vrf(db, vrf)
    valid, errors = validate(db, raw)
    if errors:
        db.rollback()
        return {"total": len(raw), "valid": len(valid), "imported": 0, "errors": errors, "preview": []}
    tests = []
    for _, data in valid:
        device = svc.save_resource(db, "devices", data, user, commit=False)
        if test_after:
            tests.extend(queue_import_tests(db, device, user))
    audit(
        db,
        user,
        f"{file_format}_import",
        "devices",
        None,
        f"{len(valid)} cihaz {file_format.upper()} olarak içe aktarıldı",
    )
    db.commit()
    svc.publish()
    return {
        "total": len(raw),
        "valid": len(valid),
        "imported": len(valid),
        "errors": [],
        "preview": [],
        "tests": tests,
    }


def queue_import_tests(db, device, user):
    """Use the ordinary authorized worker queue inside the import transaction."""
    target = svc.get(db, m.Device, device["id"])
    options = svc.connection_test_options(db, target)
    base = {"device_id": target.id, "name": target.name, "management_ip": target.management_ip}
    if not options["can_test"]:
        return [{**base, "protocol": "—", "status": "skipped", "message": options["reason"], "job_id": None}]
    rows = []
    for option in options["protocols"]:
        if not option["enabled"]:
            continue
        kind = next(k for k, p in svc.CONNECTION_TESTS.items() if p == option["protocol"])
        job = svc.enqueue(db, kind, target.id, user, commit=False)
        rows.append(
            {
                **base,
                "protocol": option["label"],
                "job_id": job.id,
                "status": job.status,
                "message": "Test sırada.",
            }
        )
    return rows


def import_test_status(db, ids):
    jobs = db.scalars(select(m.Job).where(m.Job.id.in_(set(ids)), m.Job.kind.in_(svc.CONNECTION_TESTS))).all()
    if len(jobs) != len(set(ids)):
        raise HTTPException(404, "Bağlantı testi bulunamadı")
    return [
        {
            "job_id": job.id,
            "status": job.status,
            "message": (job.result or {}).get("message")
            or job.error
            or ("Test çalışıyor…" if job.status == "running" else "Test sırada."),
        }
        for job in jobs
    ]
