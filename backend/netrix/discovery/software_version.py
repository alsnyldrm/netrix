"""Extract only explicit running software revisions, never boot ROM or image candidates."""

import re

FORTIGATE_VERSION_OID = "1.3.6.1.4.1.12356.101.4.1.1.0"


def software_scalar(object_id):
    """Vendor version scalars supplement agents with a hostname-only sysDescr."""
    if str(object_id).lstrip(".").startswith("1.3.6.1.4.1.12356.101."):
        return FORTIGATE_VERSION_OID
    return None


def scalar_version(oid, value):
    if oid != FORTIGATE_VERSION_OID:
        return ""
    match = re.fullmatch(
        r"v?(\d+\.\d+\.\d+)(?:,build(\d+))?(?:,\d{6})?(?: \([A-Za-z0-9. -]+\))?",
        str(value).strip(),
        re.I,
    )
    return match[1] + (f" build{match[2]}" if match[2] else "") if match else ""


def clean_version(value):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value[:1].lower() == "v" and value[1:2].isdigit():
        value = value[1:]
    return (
        value
        if re.fullmatch(
            r"[A-Za-z]{0,5}\.?\d[A-Za-z0-9.()+_-]{0,90}(?: (?:Release|build)\s?[A-Za-z0-9.-]+)?", value
        )
        else ""
    )


def unique_version(values):
    found = {clean_version(v) for v in values}
    found.discard("")
    return found.pop() if len(found) == 1 else ""


def software_version(text, adapter=None):
    if not isinstance(text, str):
        return ""
    text = "\n".join(
        re.split(r",\s*(?:ROM|Boot ROM|BIOS)\b", line, flags=re.I)[0]
        for line in text.splitlines()
        if not re.match(r"^\s*(?:Boot(?:\s+ROM)?|ROM|BIOS|Service\s+OS)\b", line, re.I)
    )
    patterns = [
        r"(?:software\s+(?:revision|version)|\brevision)\s*[: ]\s*([A-Za-z]{0,5}\.?\d[\w.()+-]*)",
        r"(?:Cisco IOS[^\r\n]*?|NXOS:|system:)\s*[, ]\s*Version\s+([\w.()+-]+)",
        r"(?:Junos:|JUNOS Software Release)\s*\[?([\w.()+-]+)",
        r"(?:Forti(?:Gate|WiFi)-[\w-]+)\s+v(\d[\w.()-]*(?:,build\d+)?)",
        r"ArubaOS\s*\(MODEL:[^\r\n)]+\),?\s*Version\s+([\w.()-]+)",
        r"Comware[^\r\n]*?Version\s+(\d[\w.()-]*,\s*Release\s+[\w.-]+)",
    ]
    if adapter in ("aruba_5400", "aruba_2900"):
        patterns.append(r"^\s*([A-Z]{1,4}\.\d+\.\d+(?:\.\d+)+)\s*$")
    if adapter == "aruba_6100":
        patterns.append(r"^\s*Version\s*:\s*([\w.()-]+)\s*$")
    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.M | re.I):
            value = re.sub(r",\s*Release\s+", " Release ", match[1], flags=re.I)
            values.append(value.replace(",build", " build"))
    return unique_version(values)
