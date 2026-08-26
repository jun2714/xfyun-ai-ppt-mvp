from typing import Any, TypeVar
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from api.v1.auth.context import get_current_owner_id

T = TypeVar("T", bound=SQLModel)

OWNER_SESSION_INFO_KEY = "presenton_owner_id"
ADMIN_SESSION_INFO_KEY = "presenton_owner_is_admin"


def attach_owner_to_session(session: Any, principal: Any) -> None:
    """Store owner identity on the Session so greenlet listeners can read it."""
    if principal is None:
        return
    user_id = getattr(principal, "user_id", None)
    if user_id is None:
        return
    session.info[OWNER_SESSION_INFO_KEY] = user_id
    session.info[ADMIN_SESSION_INFO_KEY] = bool(getattr(principal, "is_admin", False))


def owner_id_from_session(session: Any) -> uuid.UUID | None:
    stored = session.info.get(OWNER_SESSION_INFO_KEY) if session is not None else None
    return stored if stored is not None else get_current_owner_id()


async def get_by_id_unscoped(
    sql_session: AsyncSession,
    model: type[T],
    row_id: uuid.UUID,
) -> T | None:
    """Load a row by primary key, ignoring the current user's owner filter.

    Theme generation jumps from the editor to ppt-web. That second origin may
    briefly miss the TeachNova session, so GET-by-id must still find the deck
    that create just wrote. List endpoints stay owner-scoped.
    """
    result = await sql_session.execute(
        select(model).where(model.id == row_id).execution_options(skip_owner_scope=True)
    )
    return result.scalar_one_or_none()
