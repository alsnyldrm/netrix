"""Local TOTP enrollment and one-use challenges; no session before proof."""

import base64
import hashlib
import hmac
import io
import secrets
import struct
from datetime import timedelta
from urllib.parse import quote, urlencode

import qrcode
from fastapi import HTTPException
from sqlalchemy import delete, select

from .. import models as m
from ..core import now
from .permissions import is_super_admin
from .roles import locked_accounts
from .security import audit, decrypt, encrypt, token_hash


def totp(secret, step, digits=6):
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def clear_challenge(user):
    user.mfa_challenge_hash = user.mfa_expires_at = user.encrypted_mfa_pending = None
    user.mfa_attempts = 0


def begin(db, user):
    challenge = secrets.token_urlsafe(48)
    user.mfa_challenge_hash = token_hash(challenge)
    user.mfa_expires_at = now() + timedelta(minutes=5)
    user.mfa_attempts = 0
    result = {
        "mfa_required": True,
        "mfa_setup_required": not bool(user.encrypted_mfa_secret),
        "challenge": challenge,
    }
    if not user.encrypted_mfa_secret:
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        user.encrypted_mfa_pending = encrypt(secret)
        uri = (
            "otpauth://totp/"
            + quote("NETRIX:" + user.email, safe="")
            + "?"
            + urlencode(
                {"secret": secret, "issuer": "NETRIX", "algorithm": "SHA1", "digits": 6, "period": 30}
            )
        )
        image = qrcode.make(uri)
        output = io.BytesIO()
        image.save(output, format="PNG")
        result.update(
            secret=secret, qr_code="data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
        )
    db.commit()
    return result


def complete(db, challenge, code):
    user = db.scalar(
        select(m.User).where(m.User.mfa_challenge_hash == token_hash(challenge)).with_for_update()
    )
    if (
        not user
        or not user.is_active
        or user.deleted_at
        or user.auth_source != "local"
        or not user.mfa_expires_at
        or user.mfa_expires_at <= now()
        or user.mfa_attempts >= 5
    ):
        raise HTTPException(401, "Doğrulama isteği geçersiz veya süresi dolmuş. Yeniden giriş yapın.")
    secret = decrypt(user.encrypted_mfa_secret or user.encrypted_mfa_pending)
    current = int(now().timestamp()) // 30
    matched = next(
        (
            step
            for step in (current, current - 1, current + 1)
            if hmac.compare_digest(totp(secret, step), code)
        ),
        None,
    )
    if matched is None or (user.mfa_last_step is not None and matched <= user.mfa_last_step):
        user.mfa_attempts += 1
        if user.mfa_attempts >= 5:
            clear_challenge(user)
        db.commit()
        raise HTTPException(
            401, "Doğrulama kodu hatalı veya kullanılmış. Authenticator saatini kontrol edin."
        )
    if not user.encrypted_mfa_secret:
        user.encrypted_mfa_secret = user.encrypted_mfa_pending
        audit(db, user, "mfa_enrolled", "users", user.id, "Authenticator kurulumu tamamlandı")
    user.mfa_last_step = matched
    clear_challenge(user)
    return user


def reset(db, actor_id, target_id):
    accounts = locked_accounts(db, {actor_id, target_id})
    actor, target = accounts.get(actor_id), accounts.get(target_id)
    if not is_super_admin(actor) or not actor.is_active:
        raise HTTPException(403, "Süper yönetici yetkisi gerekiyor")
    if not target:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    if target.auth_source != "local":
        raise HTTPException(409, "Bu hesabın MFA ayarları Microsoft tarafından yönetilir")
    target.encrypted_mfa_secret = target.mfa_last_step = None
    clear_challenge(target)
    db.execute(delete(m.AuthSession).where(m.AuthSession.user_id == target_id))
    audit(db, actor, "mfa_reset", "users", target_id, "Authenticator sıfırlandı; yeniden kurulum zorunlu")
    db.commit()
