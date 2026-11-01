"""Short-lived, revision-invalidated IPAM JSON responses after authentication."""

import hashlib
import json
import time
from functools import lru_cache

from fastapi.responses import Response
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from ..core import settings

REVISION_KEY = "netrix:ipam:revision"
_retry_after = 0.0


@lru_cache(maxsize=2)
def client(url):
    return Redis.from_url(
        url,
        socket_connect_timeout=0.05,
        socket_timeout=0.05,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0),
    )


def json_response(parameters, load, *, force=False):
    global _retry_after
    started = time.perf_counter()
    cache, key = None, None
    if time.monotonic() >= _retry_after:
        try:
            cache = client(settings().redis_url)
            revision = cache.get(REVISION_KEY) or "0"
            digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
            key = f"netrix:ipam:read:v1:{revision}:{digest}"
            saved = cache.get(key)
            if saved and not force:
                saved = json.loads(saved)
                if saved["until"] > time.time():
                    return response(saved["body"], started, "hit")
        except Exception:
            # Redis is optional for these reads. Never turn a cache outage into a slow page.
            _retry_after = time.monotonic() + 5
            cache = None
    body = json.dumps(load(), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if cache is not None and key:
        try:
            cache.set(key, json.dumps({"until": time.time() + 5, "body": body}), ex=5)
        except Exception:
            _retry_after = time.monotonic() + 5
    return response(body, started, "miss")


def response(body, started, state):
    return Response(
        body,
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Server-Timing": f'ipam;dur={(time.perf_counter() - started) * 1000:.2f};desc="{state}"',
        },
    )
