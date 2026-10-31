"""Remove AOS-S terminal spacing without changing configuration commands/values."""

import re

AOSS_HEADER = re.compile(r"^;[^\n]*Configuration Editor;[^\n]*Created on release", re.I)


def config_text(content):
    if not AOSS_HEADER.match(content.lstrip()):
        return content
    # Unknown banner delimiters are opaque data, not formatting. Leave them alone.
    if re.search(r'(?m)^\s*banner\s+\S+\s+[^"\s]', content):
        return content
    result, quoted, pem = [], False, False
    for line in content.splitlines(keepends=True):
        if "-----BEGIN " in line:
            pem = True
        if line.strip() or quoted or pem:
            result.append(line)
        if "-----END " in line:
            pem = False
        # Preserve whitespace inside multiline quoted values, including banners.
        # Escaped quotes and comment text do not open/close a value.
        if not quoted and line.lstrip().startswith(";"):
            continue
        escaped = False
        for char in line:
            if char == '"' and not escaped:
                quoted = not quoted
            escaped = char == "\\" and not escaped
    return "".join(result)
