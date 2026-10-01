from functools import lru_cache
from secrets import compare_digest

import jwt
from fastapi import Depends, Header
from jwt import PyJWKClient
from sqlalchemy import func, or_, select

from backend.config import settings
from backend.db.session import get_session
from backend.auth.demo import authenticate_demo_token
from backend.models.entities import LEGACY_WORKSPACE_ID, WorkspaceMembership
from backend.tools.procurement import ProcurementTools
from backend.tools.runtime import BusinessError


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True)


def authenticated_user(
    db=Depends(get_session),
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
):
    cfg = settings()
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        demo_identity = authenticate_demo_token(db, token)
        if demo_identity:
            return demo_identity
        if not cfg.supabase_url:
            raise BusinessError("Supabase authentication is not configured", "CONFIGURATION_ERROR", 503)
        try:
            signing_key = _jwks_client(cfg.supabase_url).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=cfg.supabase_audience,
                issuer=f"{cfg.supabase_url.rstrip('/')}/auth/v1",
                options={"require": ["exp", "sub", "aud"]},
            )
        except Exception as exc:
            raise BusinessError("Your session is invalid or expired", "UNAUTHORIZED", 401) from exc
        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise BusinessError("Authenticated account has no email", "UNAUTHORIZED", 401)
        metadata = claims.get("user_metadata") or {}
        name = str(metadata.get("full_name") or metadata.get("name") or email.split("@")[0]).strip()
        return {
            "actor": name,
            "email": email,
            "user_id": str(claims["sub"]),
            "human": True,
            "auth_type": "jwt",
        }

    if not cfg.allow_api_keys:
        raise BusinessError("Sign in with your Supabase account", "UNAUTHORIZED", 401)
    if len({cfg.api_key, cfg.reviewer_api_key, cfg.finance_api_key}) != 3:
        raise BusinessError("Service, purchasing and finance credentials must differ", "CONFIGURATION_ERROR", 503)
    candidates = (
        (cfg.finance_api_key, cfg.finance_reviewer_name, True, "finance"),
        (cfg.reviewer_api_key, cfg.reviewer_name, True, "purchasing"),
        (cfg.api_key, "procurement-service", False, "service"),
    )
    for expected, actor, human, role in candidates:
        if x_api_key and compare_digest(x_api_key, expected):
            return {
                "actor": actor,
                "email": "",
                "user_id": "",
                "human": human,
                "role": role,
                "workspace_id": LEGACY_WORKSPACE_ID,
                "auth_type": "api_key",
            }
    raise BusinessError("Valid authentication required", "UNAUTHORIZED", 401)


def workspace_identity(
    db=Depends(get_session),
    user=Depends(authenticated_user),
    x_workspace_id: str = Header(default=""),
):
    if user["auth_type"] == "api_key":
        return user
    query = select(WorkspaceMembership).where(or_(
        WorkspaceMembership.user_id == user["user_id"],
        func.lower(WorkspaceMembership.email) == user["email"],
    ))
    if x_workspace_id:
        query = query.where(WorkspaceMembership.workspace_id == x_workspace_id)
    membership = db.scalar(query.order_by(WorkspaceMembership.created_at, WorkspaceMembership.id).limit(1))
    if membership is None:
        raise BusinessError("Create or request access to a workspace", "WORKSPACE_REQUIRED", 403)
    if membership.user_id is None:
        membership.user_id = user["user_id"]
        db.commit()
    return {
        **user,
        "actor": membership.display_name or user["actor"],
        "role": membership.role,
        "workspace_id": membership.workspace_id,
    }


def tools(db=Depends(get_session), identity=Depends(workspace_identity)):
    return ProcurementTools(
        db,
        actor=identity["actor"],
        human=identity["human"],
        role=identity["role"],
        workspace_id=identity["workspace_id"],
    )


def _allow(t: ProcurementTools, roles: set[str]):
    if t.role not in roles:
        raise BusinessError("Your workspace role cannot perform this action", "FORBIDDEN", 403)
    return t


def write_tools(t=Depends(tools)):
    return _allow(t, {"service", "owner", "procurement", "purchasing"})


def purchasing_tools(t=Depends(tools)):
    return _allow(t, {"owner", "purchasing"})


def finance_tools(t=Depends(tools)):
    return _allow(t, {"owner", "finance"})


def reviewer_tools(t=Depends(tools)):
    return _allow(t, {"owner", "purchasing", "finance"})
