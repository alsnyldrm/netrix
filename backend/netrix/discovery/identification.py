"""Extract inventory identity from device responses, never from selected adapters."""

import re

from .software_version import clean_version, software_version, unique_version

FIELDS = {"vendor": 80, "model": 100, "kind": 20, "software_version": 120}
KINDS = {"switch", "router", "firewall", "server"}
PLACEHOLDERS = {
    "unknown",
    "none",
    "null",
    "n/a",
    "na",
    "not specified",
    "not available",
    "default string",
    "to be filled by o.e.m.",
    "system manufacturer",
    "system product name",
    "other",
    "-",
}


def clean(value, limit):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if (
        not value
        or len(value) > limit
        or value.lower() in PLACEHOLDERS
        or any(ord(c) < 32 for c in value)
        or value.lower().startswith("no such")
    ):
        return ""
    return value


def normalize(fields):
    if not isinstance(fields, dict):
        return {}
    result = {key: clean(fields.get(key), limit) for key, limit in FIELDS.items() if key != "kind"}
    result["software_version"] = clean_version(result.get("software_version", ""))
    kind = fields.get("kind")
    if isinstance(kind, str) and kind.strip().lower() in KINDS:
        result["kind"] = kind.strip().lower()
    return {key: value for key, value in result.items() if value}


def infer_kind(model, description=""):
    model = model.lower()
    families = [
        (r"^(?:fortigate|fortiwifi|fg-|srx|vsrx|asa\d|fpr\d)", "firewall"),
        (r"^(?:ws-c|c[239]\d{3}|catalyst|n[235679]k-|n[39]\d{3}|ex\d|qfx|dcs-|crs\d|css\d)", "switch"),
        (r"^(?:isr|asr|c[18]\d{3}|csr\d|mx\d|acx\d|ptx\d|ccr\d)", "router"),
        (r"^(?:poweredge|proliant|thinksystem|primergy)", "server"),
    ]
    for pattern, kind in families:
        if re.search(pattern, model):
            return kind
    kinds = {
        kind
        for kind in ("switch", "router", "firewall", "server")
        if re.search(rf"\b{kind}\b", description, re.I)
    }
    return kinds.pop() if len(kinds) == 1 else ""


def snmp_identity(system, tables):
    # ENTITY-MIB chassis(3) identifies the device; modules/transceivers do not.
    chassis = [i for i, value in tables.get("entity_class", {}).items() if str(value) == "3"]
    fields = {}
    ambiguous = set()
    for key, table in (("vendor", "entity_vendor"), ("model", "entity_model")):
        values = {clean(str(tables.get(table, {}).get(i, "")), FIELDS[key]) for i in chassis}
        values.discard("")
        if len(values) == 1:
            fields[key] = values.pop()
        elif len(values) > 1:
            ambiguous.add(key)
    oid = system.get("sys_object_id", "").lstrip(".")
    enterprises = {
        "9": "Cisco",
        "2636": "Juniper",
        "12356": "Fortinet",
        "2011": "Huawei",
        "30065": "Arista",
        "14988": "MikroTik",
        "14823": "Aruba",
    }
    for enterprise, vendor in enterprises.items():
        if "vendor" not in ambiguous and oid.startswith(f"1.3.6.1.4.1.{enterprise}."):
            fields.setdefault("vendor", vendor)
    description = system.get("sys_description", "")
    versions = {clean_version(str(tables.get("entity_software", {}).get(i, ""))) for i in chassis}
    versions.discard("")
    if len(versions) == 1:
        fields["software_version"] = unique_version(versions)
    elif not versions:
        fields["software_version"] = software_version(description)
    # Recognize explicit model tokens, not software versions or the entire sysDescr.
    if "model" not in fields and "model" not in ambiguous:
        match = re.search(
            r"\b(FortiGate-[\w-]+|FortiWiFi-[\w-]+|WS-C[\w-]+|C9\d{3}[\w-]*|"
            r"ISR\d[\w-]*|ASR\d[\w-]*|(?:SRX|EX|QFX|MX|ACX|PTX)\d[\w-]*)\b",
            description,
            re.I,
        )
        if match:
            fields["model"] = match[1]
    kind = infer_kind(fields.get("model", ""), description)
    if kind:
        fields["kind"] = kind
    return normalize(fields)


def ssh_identity(adapter, text):
    fields = {"software_version": software_version(text, adapter)}
    if adapter == "ios":
        if re.search(r"\bCisco\b", text, re.I):
            fields["vendor"] = "Cisco"
        matches = re.findall(r"^\s*Model\s+Number\s*:\s*(\S+)", text, re.M | re.I)
        if not matches:
            matches = re.findall(r"\bcisco\s+([\w/-]+)\s+\([^\r\n]*\)\s+processor", text, re.I)
        models = {value.casefold(): value for value in matches}
        if len(models) == 1:
            fields["model"] = next(iter(models.values()))
    elif adapter == "junos":
        if re.search(r"\b(?:Junos|Juniper)\b", text, re.I):
            fields["vendor"] = "Juniper"
        models = {value.casefold(): value for value in re.findall(r"^\s*Model:\s*(\S+)", text, re.M | re.I)}
        if len(models) == 1:
            fields["model"] = next(iter(models.values()))
    elif adapter == "fortios":
        match = re.search(r"^\s*Version:\s*(Forti(?:Gate|WiFi)-[\w-]+)\s+v", text, re.M | re.I)
        if match:
            fields.update(vendor="Fortinet", model=match[1])
    elif adapter in ("aruba_5400", "aruba_2900"):
        # Chassis lines identify the switch; module descriptions and hostnames do not.
        models = set(re.findall(r"^\s*Chassis\s*:\s*([^\r\n]+)", text, re.M | re.I))
        models = {re.split(r"\s+Serial Number\s*:", model, flags=re.I)[0].strip() for model in models}
        if len(models) == 1:
            model = models.pop()
            fields["model"] = model
            if re.search(r"\b(?:54\d\d|29\d\d)[\w-]*\b", model):
                fields["kind"] = "switch"
        if re.search(r"\bAruba\b", text):
            fields["vendor"] = "Aruba"
        elif re.search(r"\b(?:HP|HPE|Hewlett[ -]Packard)\b", text):
            fields["vendor"] = "HPE"
    elif adapter == "aruba_6100":
        for field, label in (("vendor", "Vendor"), ("model", "Product Name")):
            match = re.search(rf"^\s*{label}\s*:\s*([^\r\n]+)", text, re.M | re.I)
            if match:
                fields[field] = match[1].strip()
        if re.search(r"\b61\d\d[\w-]*\b", fields.get("model", "")):
            fields["kind"] = "switch"
    elif adapter == "aruba_7200":
        match = re.search(r"ArubaOS\s*\(MODEL:\s*([^\r\n)]+)\)", text, re.I)
        if match:
            fields["model"] = match[1].strip()
            if re.search(r"\bAruba\s*72\d\d\b", match[1], re.I):
                fields["vendor"] = "Aruba"
    elif adapter == "hp_1950":
        # Read product descriptions, never infer a model from the selected adapter or sysname.
        models = set(
            re.findall(
                r"^\s*((?:HP|HPE)\s+(?:OfficeConnect\s+)?(?:V?19\d\d)[^\r\n]*?)\s+uptime is\b",
                text,
                re.M | re.I,
            )
        )
        models.update(
            re.findall(
                r"^\s*Device description\s*:\s*((?:HP|HPE)\s+(?:OfficeConnect\s+)?V?19\d\d[^\r\n]*)",
                text,
                re.M | re.I,
            )
        )
        models = {value.strip() for value in models}
        if len(models) == 1:
            fields.update(model=models.pop(), kind="switch", vendor="HPE")
        elif re.search(r"\b(?:HP|HPE|Hewlett[ -]Packard)\b", text):
            fields["vendor"] = "HPE"
    elif adapter == "linux":
        for field in ("vendor", "model"):
            match = re.search(rf"^NETRIX_{field.upper()}=([^\r\n]*)", text, re.M)
            if match:
                fields[field] = match[1]
        match = re.search(r"^NETRIX_CHASSIS=(\d+)\s*$", text, re.M)
        if match and match[1] in {"17", "23", "28"}:
            fields["kind"] = "server"
    fields = normalize(fields)
    kind = infer_kind(fields.get("model", ""))
    if kind:
        fields.setdefault("kind", kind)
    return fields


def rest_identity(payload):
    if not isinstance(payload, dict):
        return {}
    for key in ("results", "data", "system"):
        if isinstance(payload.get(key), dict):
            payload = payload[key]
    fields = normalize(
        {
            "vendor": payload.get("vendor") or payload.get("manufacturer"),
            "model": payload.get("model") or payload.get("model_name"),
            "kind": payload.get("kind") or payload.get("device_type") or payload.get("type"),
            "software_version": payload.get("software_version")
            or payload.get("firmware_version")
            or payload.get("version"),
        }
    )
    kind = infer_kind(fields.get("model", ""))
    if kind:
        fields.setdefault("kind", kind)
    return fields
