import difflib
import json
import re
import xml.etree.ElementTree as ET

SENSITIVE = re.compile(
    r"(?i)(password|passwd|passphrase|secret|community|private[-_ ]?key|token|authorization|"
    r"pre-shared|psk|snmp-server user|encrypted-password|key-string|"
    r"(?:api|auth|priv(?:acy)?)[-_ ]?(?:key|password))"
)
MASK = "[REDACTED SECRET]"


def redact_json(value):
    if isinstance(value, dict):
        return {key: MASK if SENSITIVE.search(key) else redact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    return value


def redact_config(content):
    stripped = content.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return json.dumps(redact_json(json.loads(content)), indent=2, ensure_ascii=False)
        except (ValueError, RecursionError):
            return "[REDACTED: invalid structured configuration]"
    if stripped.startswith("<"):
        if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
            return "[REDACTED: unsupported XML declarations]"
        try:
            root = ET.fromstring(content)
            for element in root.iter():
                sensitive = SENSITIVE.search(element.tag) or any(
                    key.lower() in ("name", "key") and SENSITIVE.search(value)
                    for key, value in element.attrib.items()
                )
                if sensitive:
                    element.clear()
                    element.text = MASK
                else:
                    for key in element.attrib:
                        if SENSITIVE.search(key):
                            element.attrib[key] = MASK
            return ET.tostring(root, encoding="unicode")
        except (ET.ParseError, RecursionError):
            return "[REDACTED: invalid structured configuration]"
    lines, private, redact_next = [], False, False
    for line in content.splitlines():
        if "-----BEGIN" in line and "PRIVATE KEY" in line:
            private = True
        if private:
            lines.append("[REDACTED KEY]")
            if "-----END" in line:
                private = False
        elif redact_next and line.strip():
            lines.append(MASK)
            redact_next = False
        elif SENSITIVE.search(line):
            lines.append("[REDACTED SECRET LINE]")
            redact_next = bool(re.search(r"[:=]\s*$", line) or SENSITIVE.fullmatch(line.strip()))
        else:
            lines.append(line)
    return "\n".join(lines)


def config_diff(previous, current):
    return "\n".join(
        difflib.unified_diff(
            redact_config(previous).splitlines(),
            redact_config(current).splitlines(),
            fromfile="önceki",
            tofile="güncel",
            lineterm="",
        )
    )
