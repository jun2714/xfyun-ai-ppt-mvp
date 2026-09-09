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


def _owner_key(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("-", "").lower()


def is_row_owned_by(row: Any, owner_id: uuid.UUID | None) -> bool:
    """Compare ownership in Python to avoid MySQL CHAR(32) UUID predicates."""
    row_owner = _owner_key(getattr(row, "owner_id", None) if row is not None else None)
    current_owner = _owner_key(owner_id)
    if not row_owner or not current_owner:
        return False
    return row_owner == current_owner


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


async def get_owned_by_id(
    sql_session: AsyncSession,
    model: type[T],
    row_id: uuid.UUID,
) -> T | None:
    """Load a row the current user owns, without SQLAlchemy owner-scope filters.

    Dashboard list/get already skip ``with_loader_criteria`` because it can
    compile to an always-false comparison on MySQL CHAR(32) UUID columns.
    ``session.get()`` still applies that filter, so listed incomplete decks
    404 on DELETE even though ``GET /all`` returned them.
    """
    row = await get_by_id_unscoped(sql_session, model, row_id)
    if not is_row_owned_by(row, get_current_owner_id()):
        return None
    return row
