"""TeachNova → Presenton session bridge."""

from __future__ import annotations

import secrets
from typing import Any

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from api.v1.auth.config import SESSION_COOKIE_NAME, SESSION_TTL_SECONDS
from api.v1.auth.users import PASSWORD_HELPER, get_jwt_strategy, serialize_user
from models.sql.user import User
from services.database import get_async_session
from utils.get_env import (
    get_teachnova_auth_introspect_url,
    get_teachnova_tenant_id,
)


TEACHNOVA_BRIDGE_ROUTER = APIRouter(tags=["Auth"])


class TeachnovaBridgeRequest(BaseModel):
    access_token: str = Field(min_length=8, max_length=512)
    tenant_id: str | None = Field(default=None, max_length=64)


def teachnova_username(user_id: str | int) -> str:
    return f"tn_{user_id}"


def _secure_request(request: Request) -> bool:
    return (
        request.headers.get("x-forwarded-proto", "").lower() == "https"
        or request.url.scheme == "https"
    )


def _set_login_cookie(response: JSONResponse, token: str, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_request(request),
        samesite="lax",
        path="/",
    )


async def introspect_teachnova_user(
    access_token: str, tenant_id: str
) -> dict[str, Any]:
    url = get_teachnova_auth_introspect_url()
    if not url:
        raise HTTPException(
            status_code=503,
            detail="TEACHNOVA_AUTH_INTROSPECT_URL is not configured",
        )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "tenant-id": tenant_id,
        "Accept": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(url, headers=headers) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    raise HTTPException(
                        status_code=401,
                        detail="TeachNova token rejected",
                    )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"TeachNova introspect failed: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid TeachNova response")

    code = payload.get("code")
    if code is not None and int(code) != 0:
        raise HTTPException(
            status_code=401,
            detail=str(payload.get("msg") or "TeachNova unauthorized"),
        )

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="TeachNova user missing")

    raw_id = user.get("id")
    if raw_id is None:
        raise HTTPException(status_code=401, detail="TeachNova user id missing")

    return {
        "user_id": str(raw_id),
        "username": str(user.get("username") or user.get("nickname") or raw_id),
        "nickname": str(user.get("nickname") or user.get("username") or ""),
        "is_admin": _teachnova_user_is_admin(user, data),
    }


def _teachnova_user_is_admin(user: dict[str, Any], data: dict[str, Any]) -> bool:
    """Match official-site admin: nickname/username admin, or role super_admin."""
    for key in ("nickname", "username"):
        value = str(user.get(key) or "").strip().lower()
        if value == "admin":
            return True
    roles = data.get("roles") or []
    role_codes: set[str] = set()
    if isinstance(roles, (list, set, tuple)):
        for item in roles:
            if isinstance(item, str):
                role_codes.add(item.strip())
            elif isinstance(item, dict):
                code = item.get("code") or item.get("name") or item.get("roleKey") or ""
                if code:
                    role_codes.add(str(code).strip())
    if "super_admin" in role_codes:
        return True
    permissions = data.get("permissions") or []
    if isinstance(permissions, (list, set, tuple)) and "*:*:*" in permissions:
        return True
    return False


async def ensure_teachnova_user(
    session: AsyncSession, teachnova_user_id: str, *, is_admin: bool = False
) -> User:
    username = teachnova_username(teachnova_user_id)
    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        if not existing.is_active:
            raise HTTPException(status_code=403, detail="Mapped user is disabled")
        if existing.is_superuser != is_admin:
            existing.is_superuser = is_admin
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
        return existing

    user = User(
        username=username,
        hashed_password=PASSWORD_HELPER.hash(secrets.token_urlsafe(32)),
        is_active=True,
        is_verified=True,
        is_superuser=is_admin,
        admin_slot=None,
        auth_version=1,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@TEACHNOVA_BRIDGE_ROUTER.post("/bridge/teachnova")
async def bridge_teachnova_session(
    body: TeachnovaBridgeRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Exchange a TeachNova access token for a Presenton browser session."""
    tenant_id = (body.tenant_id or get_teachnova_tenant_id() or "1").strip() or "1"
    identity = await introspect_teachnova_user(body.access_token.strip(), tenant_id)
    user = await ensure_teachnova_user(
        session, identity["user_id"], is_admin=bool(identity.get("is_admin"))
    )
    token = await get_jwt_strategy().write_token(user)
    response = JSONResponse(
        {
            "configured": True,
            "authenticated": True,
            "session_token": token,
            "expires_in": SESSION_TTL_SECONDS,
            "teachnova_user_id": identity["user_id"],
            **serialize_user(user),
        }
    )
    _set_login_cookie(response, token, request)
    return response
