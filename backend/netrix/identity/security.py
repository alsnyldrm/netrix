import hashlib
import json
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request

from ..core import db_session, now, settings
from ..models import Audit, AuthSession, User

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))


def encrypt(value):
    return Fernet(settings().encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt(value):
    return Fernet(settings().encryption_key.encode()).decrypt(value.encode()).decode()


def secret_data(credential):
    return json.loads(decrypt(credential.encrypted_secret))


def verify(password, digest):
    try:
        return hasher.verify(digest, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(db, token):
    auth = db.get(AuthSession, token_hash(token or ""))
    if not auth or auth.expires_at <= now():
        return None
    user = db.get(User, auth.user_id)
    return user if user and user.is_active else None


def current_user(request: Request, db=Depends(db_session)):
    user = session_user(db, request.cookies.get("netrix_session"))
    if not user:
        raise HTTPException(401, "Oturum açmanız gerekiyor")
    return user


def operator(user=Depends(current_user)):
    if user.role not in ("admin", "operator"):
        raise HTTPException(403, "Bu işlem için operatör yetkisi gerekiyor")
    return user


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Bu işlem için yönetici yetkisi gerekiyor")
    return user


def audit(db, user, action, entity_type, entity_id, summary):
    db.add(
        Audit(
            actor_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:400],
        )
    )


def issue_session(db, user):
    token = secrets.token_urlsafe(48)
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(hours=12)))
    return token
