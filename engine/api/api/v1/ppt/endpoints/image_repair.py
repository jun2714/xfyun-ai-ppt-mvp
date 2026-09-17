import uuid
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from services.database import get_async_session
from services.image_repair_service import read_status, claim_repair, run_repair
from api.v1.auth.context import get_current_owner_id
from pydantic import BaseModel, Field


class ImageReplacementRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    expected_url: str = Field(min_length=1)

IMAGE_REPAIR_ROUTER = APIRouter(prefix='/presentation', tags=['Image repair'])


@IMAGE_REPAIR_ROUTER.get('/{id}/image-repair')
async def image_repair_status(id: uuid.UUID, session: AsyncSession = Depends(get_async_session)):
    return await read_status(session, id)


@IMAGE_REPAIR_ROUTER.post('/{id}/image-repair')
async def start_image_repair(id: uuid.UUID, background_tasks: BackgroundTasks,
                             replacement: ImageReplacementRequest | None = None,
                             session: AsyncSession = Depends(get_async_session)):
    state, run_id = await claim_repair(session, id, replacement.model_dump() if replacement else None)
    if run_id:
        background_tasks.add_task(run_repair, id, run_id, get_current_owner_id())
    return state
