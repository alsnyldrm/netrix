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
    return "\n".join(cli_lines(content))


def fortios_text(content):
    return content.lstrip().startswith("#config-version=")


def quote_state(line, quoted):
    escaped = False
    for char in line:
        if char == '"' and not escaped:
            quoted = not quoted
        escaped = char == "\\" and not escaped
    return quoted


def cli_lines(content):
    """One safe display line per source line, keeping multiline secret state."""
    fortios = fortios_text(content)
    lines, private, redact_next, quoted, secret_quoted = [], False, False, False, False
    for line in content.splitlines():
        sensitive = bool(SENSITIVE.search(line))
        command = re.match(r"^(\s*(?:set|unset) [a-z][a-z0-9-]*)(?:\s|$)", line) if fortios else None
        masked = command[1] + " " + MASK if command else "[REDACTED SECRET LINE]"
        if "-----BEGIN" in line and "PRIVATE KEY" in line:
            private = True
        if private:
            lines.append(masked if command else "[REDACTED KEY]")
            if "-----END" in line:
                private = False
        elif secret_quoted:
            lines.append(MASK)
        elif redact_next and line.strip():
            lines.append(MASK)
            redact_next = False
        elif sensitive:
            lines.append(masked)
            redact_next = bool(re.search(r"[:=]\s*$", line) or SENSITIVE.fullmatch(line.strip()))
        else:
            lines.append(line)
        if fortios and (quoted or not line.lstrip().startswith("#")):
            quoted = quote_state(line, quoted)
            secret_quoted = quoted and (secret_quoted or sensitive)
    return lines


def section_paths(source, display):
    """FortiOS config/edit nesting; quoted multiline values are opaque data."""
    stack, paths, quoted = [], [], False
    for line, safe in zip(source, display, strict=True):
        command = line.strip()
        opening = not quoted and command.startswith(("config ", "edit "))
        if opening:
            stack.append((command.split()[0], safe.strip()))
        paths.append(tuple(label for _, label in stack))
        if not quoted and command in ("end", "next"):
            kind = "config" if command == "end" else "edit"
            while stack:
                if stack.pop()[0] == kind:
                    break
        if quoted or not command.startswith("#"):
            quoted = quote_state(line, quoted)
    return paths


def line_range(start, end):
    length = end - start
    return str(start + 1) if length == 1 else f"{start + (length > 0)},{length}"


def config_diff(previous, current):
    if previous == current:
        return ""
    # Structured formats need their existing whole-document redaction. A hidden
    # value change must still be reported even if the masked documents are equal.
    if any(text.lstrip().startswith(("{", "[", "<")) for text in (previous, current)):
        result = "\n".join(
            difflib.unified_diff(
                redact_config(previous).splitlines(),
                redact_config(current).splitlines(),
                fromfile="önceki",
                tofile="güncel",
                lineterm="",
            )
        )
        return result or "Görünür alanlarda fark yok; maskelenmiş değer veya dosya biçimi değişmiş."
    old, new = previous.splitlines(), current.splitlines()
    safe_old, safe_new = cli_lines(previous), cli_lines(current)
    fortios = fortios_text(previous) and fortios_text(current)
    old_paths = section_paths(old, safe_old) if fortios else [()] * len(old)
    new_paths = section_paths(new, safe_new) if fortios else [()] * len(new)
    # Match the original lines, then render masked values. Matching after
    # redaction silently loses password/key changes because both sides are equal.
    groups = list(difflib.SequenceMatcher(None, old, new).get_grouped_opcodes(0 if fortios else 3))
    if not groups:
        return ""
    header_only = fortios and all(
        not paths[index] and (not lines[index].strip() or lines[index].lstrip().startswith("#"))
        for group in groups
        for tag, i, j, k, l in group
        if tag != "equal"
        for lines, paths, start, end in ((old, old_paths, i, j), (new, new_paths, k, l))
        for index in range(start, end)
    )
    result = (
        ["Yalnızca dosya üstbilgisi değişmiş; kayıtlı konfigürasyon ayarlarında fark yok."]
        if header_only
        else []
    )
    result.extend(["--- önceki", "+++ güncel"])
    for group in groups:
        first, last = group[0], group[-1]
        result.append(f"@@ -{line_range(first[1], last[2])} +{line_range(first[3], last[4])} @@")
        last_path = None

        def emit(sign, lines, paths, start, end):
            nonlocal last_path
            for index in range(start, end):
                path = paths[index]
                if fortios and path != last_path:
                    result.append("Bölüm: " + (" > ".join(path) if path else "Dosya üstbilgisi"))
                    last_path = path
                result.append(sign + lines[index])

        for tag, i, j, k, l in group:
            if tag == "equal":
                emit(" ", safe_old, old_paths, i, j)
            if tag in ("delete", "replace"):
                emit("-", safe_old, old_paths, i, j)
            if tag in ("insert", "replace"):
                emit("+", safe_new, new_paths, k, l)
    return "\n".join(result)
