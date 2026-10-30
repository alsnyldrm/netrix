"""Decode protocol identifiers without rendering binary octets as text."""


def neighbor_label(value):
    if value is None:
        return ""
    raw = value.asOctets() if hasattr(value, "asOctets") else value if isinstance(value, bytes) else None
    if raw is None:
        text = str(value)
        # Historical PySNMP str(OctetString) used a reversible Latin-1 mapping.
        if len(text) == 6 and any(not c.isprintable() for c in text):
            try:
                raw = text.encode("latin1")
            except UnicodeEncodeError:
                pass
        if raw is None:
            return " ".join("".join(c if c.isprintable() or c.isspace() else " " for c in text).split())
    try:
        text = raw.decode("utf-8")
        if all(c.isprintable() or c in "\r\n\t" for c in text) and not (
            len(raw) == 6 and any(not c.isprintable() for c in text)
        ):
            return " ".join(text.split())
    except UnicodeDecodeError:
        pass
    return ":".join(f"{b:02x}" for b in raw) if len(raw) == 6 else "0x" + raw.hex()
