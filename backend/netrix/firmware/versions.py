"""Order supported firmware releases without comparing unrelated software branches."""

import re


def release(value):
    value = (value or "").strip().upper()
    match = re.fullmatch(r"(K|KB|WB|WC|PL)\.(\d+)\.(\d+)\.(\d+)", value)
    if match:
        return match[1], tuple(int(part) for part in match.groups()[1:])
    # Comware inventory observations may include the operating system version.
    match = re.fullmatch(r"(?:\d+(?:\.\d+)+,?\s*)?(?:R|RELEASE\s*)(\d{4})(?:P(\d+))?", value)
    if match and match[1][:2] in ("35", "51"):
        return "R" + match[1][:2], (int(match[1]), int(match[2] or 0))
    return None


def compare(current, target):
    """Return -1/0/1 for older/equal/newer, or None when not safely comparable."""
    a, b = release(current), release(target)
    if not a or not b or a[0] != b[0]:
        return None
    return (a[1] > b[1]) - (a[1] < b[1])
