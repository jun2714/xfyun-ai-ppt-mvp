from dataclasses import dataclass
from typing import Literal
import uuid

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.users import UsernameUserDatabase, UserManager, get_jwt_strategy
from models.sql.access_token import AccessToken
from models.sql.user import User
from api.v1.auth.request_tokens import collect_request_session_tokens


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: uuid.UUID
    username: str
    is_admin: bool
    method: Literal["jwt", "api_key"]


async def _principal_from_token(
    session: AsyncSession,
    token: str,
    *,
    allow_api_key: bool,
) -> tuple[AuthPrincipal | None, User | None]:
    if allow_api_key and token.startswith("sk-presenton-"):
        access_token = await session.get(AccessToken, token)
        if access_token is None:
            return None, None
        user = await session.get(User, access_token.user_id)
        if user is None or not user.is_active or not user.is_superuser:
            return None, None
        return (
            AuthPrincipal(
                user_id=user.id,
                username=user.username,
                is_admin=True,
                method="api_key",
            ),
            user,
        )

    user_db = UsernameUserDatabase(session)
    user = await get_jwt_strategy().read_token(token, UserManager(user_db))
    if not user:
        return None, None
    return (
        AuthPrincipal(
            user_id=user.id,
            username=user.username,
            is_admin=user.is_superuser,
            method="jwt",
        ),
        user,
    )


async def resolve_request_principal(
    request: Request, session: AsyncSession
) -> tuple[AuthPrincipal | None, User | None]:
    for source, token in collect_request_session_tokens(request):
        principal, user = await _principal_from_token(
            session,
            token,
            allow_api_key=source == "bearer",
        )
        if principal is not None:
            return principal, user
    return None, None


def principal_from_request(request: Request) -> AuthPrincipal:
    principal = getattr(request.state, "auth_principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return principal


def require_browser_admin_principal(request: Request) -> AuthPrincipal:
    principal = principal_from_request(request)
    if principal.method != "jwt" or not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin browser session required")
    return principal
