"""Complete local login in authorization tests, using only isolated fixture SQL."""

from datetime import timedelta
from unittest.mock import patch

from netrix import models as m
from netrix.core import now, session_factory
from netrix.identity.mfa import totp
from netrix.identity.security import decrypt
from sqlalchemy import select


def local_login(client, **kwargs):
    response = client.post("/api/v1/auth/login", **kwargs)
    data = response.json()
    if response.status_code != 200 or not data.get("mfa_required"):
        return response
    with session_factory()() as db:
        from netrix.identity.security import token_hash

        user = db.scalar(select(m.User).where(m.User.mfa_challenge_hash == token_hash(data["challenge"])))
        secret = data.get("secret") or decrypt(user.encrypted_mfa_secret)
        # Advance only the verification clock when testing multiple logins in one
        # real 30-second window. Production replay protection remains exercised.
        instant = now()
        if user.mfa_last_step is not None and user.mfa_last_step >= int(instant.timestamp()) // 30:
            instant += timedelta(seconds=(user.mfa_last_step + 1) * 30 - int(instant.timestamp()))
    with patch("netrix.identity.mfa.now", return_value=instant):
        return client.post(
            "/api/v1/auth/mfa/verify",
            json={"challenge": data["challenge"], "code": totp(secret, int(instant.timestamp()) // 30)},
        )
