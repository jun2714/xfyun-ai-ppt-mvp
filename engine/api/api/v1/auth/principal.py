from dataclasses import dataclass
from typing import Literal
import uuid

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.users import UsernameUserDatabase, UserManager, get_jwt_strategy
from models.sql.access_token import AccessToken
from models.sql.user import User
from api.v1.auth.config import SESSION_COOKIE_NAME


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: uuid.UUID
    username: str
    is_admin: bool
    method: Literal["jwt", "api_key"]


async def resolve_request_principal(
    request: Request, session: AsyncSession
) -> tuple[AuthPrincipal | None, User | None]:
    """Authenticate the request.

    Priority (first match wins):
      1. Authorization: Bearer  — explicit header set by client code
      2. tn_session / session query parameter — URL token from TeachNova
      3. presenton_session cookie — implicit browser cookie

    The order matters: TeachNova iframe users carry a teacher-specific
    Bearer / tn_session token, but the browser may also hold an admin
    cookie from a previous editor login.  If the cookie were checked
    first the admin identity would shadow the actual teacher.
    """

    # --- 1. Authorization header (Bearer JWT or API-key) ---
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token.startswith("sk-presenton-"):
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
        if user:
            return (
                AuthPrincipal(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_superuser,
                    method="jwt",
                ),
                user,
            )

    # --- 2. tn_session / session query parameter ---
    query_token = (
        request.query_params.get("tn_session")
        or request.query_params.get("session")
        or ""
    ).strip()
    if query_token:
        user_db = UsernameUserDatabase(session)
        user = await get_jwt_strategy().read_token(query_token, UserManager(user_db))
        if user:
            return (
                AuthPrincipal(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_superuser,
                    method="jwt",
                ),
                user,
            )

    # --- 3. Session cookie (lowest priority) ---
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        user_db = UsernameUserDatabase(session)
        user = await get_jwt_strategy().read_token(cookie_token, UserManager(user_db))
        if user:
            return (
                AuthPrincipal(
                    user_id=user.id,
                    username=user.username,
                    is_admin=user.is_superuser,
                    method="jwt",
                ),
                user,
            )

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
