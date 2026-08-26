from typing import TypeVar
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

T = TypeVar("T", bound=SQLModel)


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
