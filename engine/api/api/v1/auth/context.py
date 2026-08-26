from contextvars import ContextVar, Token
from typing import Any
import uuid


_CURRENT_OWNER_ID: ContextVar[uuid.UUID | None] = ContextVar(
    "presenton_current_owner_id", default=None
)
_CURRENT_OWNER_IS_ADMIN: ContextVar[bool] = ContextVar(
    "presenton_current_owner_is_admin", default=False
)


def get_current_owner_id() -> uuid.UUID | None:
    return _CURRENT_OWNER_ID.get()


def get_current_owner_is_admin() -> bool:
    return _CURRENT_OWNER_IS_ADMIN.get()


def set_current_owner_id(owner_id: uuid.UUID | None) -> Token:
    return _CURRENT_OWNER_ID.set(owner_id)


def set_current_owner_is_admin(is_admin: bool) -> Token:
    return _CURRENT_OWNER_IS_ADMIN.set(is_admin)


def reset_current_owner_id(token: Token) -> None:
    _CURRENT_OWNER_ID.reset(token)


def reset_current_owner_is_admin(token: Token) -> None:
    _CURRENT_OWNER_IS_ADMIN.reset(token)


def bind_owner_from_principal(principal: Any) -> tuple[Token | None, Token | None]:
    """Bind owner ContextVars from request.state.auth_principal.

    Must run in the same task as the endpoint (e.g. a FastAPI dependency).
    Starlette BaseHTTPMiddleware may set the same vars in a parent task, which
    the ORM listener would not see.
    """
    if principal is None:
        return None, None
    user_id = getattr(principal, "user_id", None)
    if user_id is None:
        return None, None
    owner_token = set_current_owner_id(user_id)
    admin_token = set_current_owner_is_admin(bool(getattr(principal, "is_admin", False)))
    return owner_token, admin_token


def unbind_owner(owner_token: Token | None, admin_token: Token | None) -> None:
    if admin_token is not None:
        reset_current_owner_is_admin(admin_token)
    if owner_token is not None:
        reset_current_owner_id(owner_token)
