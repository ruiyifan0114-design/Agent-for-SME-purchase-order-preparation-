from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
from hmac import compare_digest
from secrets import token_hex, token_urlsafe

from sqlalchemy import delete, select

from backend.models.entities import DemoAccount, DemoSession
from backend.tools.runtime import BusinessError

PBKDF2_ITERATIONS = 310_000
SESSION_LIFETIME = timedelta(days=7)


def password_hash(password: str) -> str:
    salt = token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return compare_digest(digest.hex(), expected)
    except (TypeError, ValueError):
        return False


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def issue_session(db, account: DemoAccount) -> dict:
    token = f"demo_{token_urlsafe(32)}"
    expires_at = datetime.now(timezone.utc) + SESSION_LIFETIME
    db.add(DemoSession(account_id=account.id, token_hash=token_digest(token), expires_at=expires_at))
    db.commit()
    return {
        "access_token": token,
        "expires_at": expires_at.isoformat(),
        "user": {
            "name": account.display_name,
            "email": "",
            "role": "Demo member",
            "initials": "".join(part[0].upper() for part in account.display_name.split()[:2]) or "DU",
        },
    }


def authenticate_demo_token(db, token: str) -> dict | None:
    if not token.startswith("demo_"):
        return None
    session = db.scalar(select(DemoSession).where(DemoSession.token_hash == token_digest(token)))
    if session is None:
        raise BusinessError("Your demo session is invalid or expired", "UNAUTHORIZED", 401)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise BusinessError("Your demo session is invalid or expired", "UNAUTHORIZED", 401)
    account = db.get(DemoAccount, session.account_id)
    if account is None:
        raise BusinessError("Your demo session is invalid or expired", "UNAUTHORIZED", 401)
    return {
        "actor": account.display_name,
        "email": f"demo-{account.id}@demo.supplydesk.local",
        "user_id": f"demo:{account.id}",
        "human": True,
        "auth_type": "demo",
    }


def remove_expired_sessions(db) -> None:
    db.execute(
        delete(DemoSession).where(DemoSession.expires_at <= datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False},
    )
