"""Explicit, owner-scoped content review from the saved outline editor."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.kindergarten_presentation_review import (
    ApplyPresentationReviewRequest,
    ApplyPresentationReviewResponse,
    PresentationReviewRequest,
    PresentationReviewResponse,
    PresentationReviewSourceResponse,
)
from services.database import get_async_session
from services.kindergarten_content_review_provider import OpenAICompatibleReviewCaller
from services.kindergarten_presentation_review_service import (
    apply_review,
    read_review_source,
    review_presentation,
)


KINDERGARTEN_REVIEW_ROUTER = APIRouter(
    prefix="/kindergarten/presentation", tags=["Kindergarten review"],
)


@KINDERGARTEN_REVIEW_ROUTER.get(
    "/{presentation_id}/review-source", response_model=PresentationReviewSourceResponse,
)
async def get_saved_review_source(
    presentation_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
):
    return await read_review_source(session, presentation_id)


@KINDERGARTEN_REVIEW_ROUTER.post(
    "/{presentation_id}/review", response_model=PresentationReviewResponse,
)
async def review_saved_presentation(
    presentation_id: uuid.UUID,
    payload: PresentationReviewRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    return await review_presentation(
        session, presentation_id, payload,
        caller=OpenAICompatibleReviewCaller(),
        disconnect_checker=request.is_disconnected,
    )


@KINDERGARTEN_REVIEW_ROUTER.post(
    "/{presentation_id}/review/apply", response_model=ApplyPresentationReviewResponse,
)
async def apply_saved_presentation_review(
    presentation_id: uuid.UUID,
    payload: ApplyPresentationReviewRequest,
    session: AsyncSession = Depends(get_async_session),
):
    return await apply_review(session, presentation_id, payload)
