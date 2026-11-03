"""Encrypted, bounded Redis state; interactive output never enters MariaDB."""

import json
import time
from uuid import uuid4

from fastapi import HTTPException
from redis.exceptions import RedisError

from ..core import redis_client
from ..identity.security import decrypt, encrypt

PREFIX = "netrix:ssh:"
TTL = 14400
RESULT_TTL = 600


def pack(value):
    return encrypt(json.dumps(value))


def unpack(value):
    return json.loads(decrypt(value)) if value else None


def key(kind, id):
    return f"{PREFIX}{kind}:{id}"


def read(client, kind, id, user=None):
    value = unpack(client.get(key(kind, id)))
    if not value or (user and value["user_id"] != user.id):
        raise HTTPException(404, "Oturum veya sonuç bulunamadı; süresi dolmuş olabilir")
    return value


def admit(kind, value):
    client = redis_client()
    try:
        heartbeat = client.get(PREFIX + "heartbeat")
        if not heartbeat or time.time() - float(heartbeat) > 15:
            raise HTTPException(503, "SSH hizmeti hazır değil. Yeniden deneyin.")
        with client.lock(PREFIX + "admission", timeout=5, blocking_timeout=1):
            active = PREFIX + kind + ":active"
            client.zremrangebyscore(active, "-inf", time.time())
            ids = client.zrange(active, 0, -1)
            own = sum(
                1
                for id in ids
                if (entry := unpack(client.get(key(kind, id)))) and entry["user_id"] == value["user_id"]
            )
            if len(ids) >= (32 if kind == "session" else 4) or own >= (16 if kind == "session" else 1):
                raise HTTPException(429, "SSH kapasitesi dolu. Açık oturumu veya toplu işlemi kapatın.")
            id = str(uuid4())
            value.update(id=id, status="queued", created=time.time())
            with client.pipeline(transaction=True) as transaction:
                transaction.set(key(kind, id), pack(value), ex=TTL)
                transaction.zadd(active, {id: time.time() + TTL})
                transaction.rpush(PREFIX + "queue", json.dumps({"kind": kind, "id": id}))
                transaction.execute()
            return {"id": id, "status": "queued"}
    except RedisError:
        raise HTTPException(503, "SSH hizmetine ulaşılamadı") from None


def draft(value):
    """A tab handoff stores encrypted input for ten minutes, without queuing SSH."""
    client = redis_client()
    index = key("drafts", value["user_id"])
    try:
        with client.lock(index + ":lock", timeout=5, blocking_timeout=1):
            client.zremrangebyscore(index, "-inf", time.time())
            if len(client.zrange(index, 0, -1)) >= 16:
                raise HTTPException(
                    429, "En fazla 16 toplu komut taslağı açılabilir. Eski taslakları kapatın."
                )
            id = str(uuid4())
            value = {**value, "id": id, "status": "draft"}
            with client.pipeline(transaction=True) as transaction:
                transaction.set(key("draft", id), pack(value), ex=RESULT_TTL)
                transaction.zadd(index, {id: time.time() + RESULT_TTL})
                transaction.execute()
            client.expire(index, RESULT_TTL)
            return {"id": id}
    except RedisError:
        raise HTTPException(503, "SSH hizmetine ulaşılamadı") from None
