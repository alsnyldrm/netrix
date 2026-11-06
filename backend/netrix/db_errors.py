"""Database-neutral classifications; never use driver text in API responses."""

CONFLICT_STATES = {"40001", "40P01", "55P03"}
TRANSIENT_STATES = {"57P01", "57P02", "57P03"}
MYSQL_CONFLICTS = (1020, 1205, 1213)
MYSQL_TRANSIENT = (2006, 2013)


def code(exc):
    original = getattr(exc, "orig", None)
    state = getattr(original, "sqlstate", None)
    if state:
        return state
    args = getattr(original, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def conflict(exc):
    value = code(exc)
    return value in CONFLICT_STATES or value in MYSQL_CONFLICTS


def retryable(exc):
    value = code(exc)
    return bool(
        conflict(exc)
        or value in TRANSIENT_STATES
        or value in MYSQL_TRANSIENT
        or (isinstance(value, str) and value.startswith("08"))
        or getattr(exc, "connection_invalidated", False)
    )
