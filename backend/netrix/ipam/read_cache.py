"""Authenticated IPAM responses are projections of SQL, never stored JSON copies."""

import json
import time

from fastapi.responses import Response


def json_response(parameters, load, *, force=False):
    started = time.perf_counter()
    body = json.dumps(load(), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return Response(
        body,
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Server-Timing": f'ipam;dur={(time.perf_counter() - started) * 1000:.2f};desc="sql"',
        },
    )
