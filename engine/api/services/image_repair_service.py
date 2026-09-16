"""Explicit, durable missing-image repair. Never regenerate reviewed slide copy."""
import asyncio
import os
import logging
import uuid
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import String, cast, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from api.v1.auth.context import get_current_owner_id, set_current_owner_id, reset_current_owner_id
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.image_policy import ImagePolicy
from services.asset_planning_service import (
    REPAIR_FAILED_PROMPT_KEY,
    REPAIR_FAILED_REASON_KEY,
    build_asset_plan,
    extract_asset_slots,
)
from services.owner_scope import get_by_id_unscoped
from utils.datetime_utils import get_current_utc_datetime
from utils.dict_utils import get_dict_at_path
from utils.process_slides import IMAGE_PROMPT_KEYS, _asset_dicts_with_prompt

LOGGER = logging.getLogger(__name__)
TASK_TYPE = 'ppt-missing-images'
LEASE_SECONDS = 90


def task_id(presentation_id):
    return f'image-repair-{presentation_id}'


def resolved(url):
    return isinstance(url, str) and bool(url.strip()) and 'placeholder' not in url.lower()


def image_url(value):
    return value.get('image_url') or value.get('__image_url__') if isinstance(value, dict) else None


def sync_image_ui(slide, slot, url):
    """Update only matching image data; never reflow a teacher's edited text."""
    keys = [getattr(guide, 'key', None) for guide in slot.content_path.guides]
    component_id = keys[0] if keys else None
    def visit(value):
        if isinstance(value, dict):
            if value.get('type') == 'image' and value.get('name') == slot.slot_name:
                value['data'] = url
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    if isinstance(slide.ui, dict):
        for component in slide.ui.get('components', []):
            if component.get('id') == component_id:
                visit(component)


def preserve_completed_images(source, target):
    """Merge newly completed URLs into a missing-only snapshot, retaining all edits.

    Also used by autosave: stale placeholders cannot erase a successful repair.
    A changed prompt, removed field, or manually replaced image always wins.
    """
    from services.asset_execution_service import _assign_url
    changed = 0
    for slot in extract_asset_slots([target]):
        try:
            old = get_dict_at_path(source.content, slot.content_path)
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        if not isinstance(old, dict):
            continue
        prompt = old.get('image_prompt') or old.get('__image_prompt__')
        url = image_url(old)
        if prompt != slot.prompt or not resolved(url):
            continue
        # Direct canvas edits can replace the UI image without changing content.
        keys = [getattr(guide, 'key', None) for guide in slot.content_path.guides]
        images = []
        def find(value):
            if isinstance(value, dict):
                if value.get('type') == 'image' and value.get('name') == slot.slot_name:
                    images.append(value)
                for child in value.values():
                    find(child)
            elif isinstance(value, list):
                for child in value:
                    find(child)
        for component in (target.ui or {}).get('components', []):
            if keys and component.get('id') == keys[0]:
                find(component)
        replacement = next((image['data'] for image in images if resolved(image.get('data'))), None)
        empty = next((image for image in images if not resolved(image.get('data'))), None)
        chosen = replacement if replacement and empty is None else (url if resolved(url) else replacement)
        _assign_url(target, slot, chosen)
        if empty is not None:
            empty['data'] = chosen
        else:
            sync_image_ui(target, slot, chosen)
        changed += 1
    return changed


def copy_repair_failure_marks(source, target) -> int:
    changed = 0
    if not isinstance(getattr(source, 'content', None), dict) or not isinstance(getattr(target, 'content', None), dict):
        return 0
    for path, parent, prompt in _asset_dicts_with_prompt(source.content, IMAGE_PROMPT_KEYS):
        failed_prompt = parent.get(REPAIR_FAILED_PROMPT_KEY) if isinstance(parent, dict) else None
        if failed_prompt != prompt:
            continue
        try:
            dest = get_dict_at_path(target.content, path)
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
        if not isinstance(dest, dict):
            continue
        dest[REPAIR_FAILED_PROMPT_KEY] = failed_prompt
        dest[REPAIR_FAILED_REASON_KEY] = parent.get(REPAIR_FAILED_REASON_KEY)
        changed += 1
    return changed


async def owned_presentation(session, presentation_id):
    row = await get_by_id_unscoped(session, PresentationModel, presentation_id)
    owner = get_current_owner_id()
    if row is None or row.owner_id != owner or (owner is None and os.getenv('DISABLE_AUTH', '').lower() != 'true'):
        raise HTTPException(404, '课件不存在或无权访问')
    return row


async def load_slides(session, presentation_id):
    return list(await session.scalars(select(SlideModel).where(
        SlideModel.presentation == presentation_id).order_by(SlideModel.index).execution_options(skip_owner_scope=True)))


def _task_run_id(task) -> str | None:
    data = task.data if task and isinstance(task.data, dict) else {}
    value = data.get('run_id')
    return str(value) if value else None


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_stale_pending(task) -> bool:
    if task is None or task.status != AsyncTaskStatus.PENDING:
        return False
    updated = _as_utc(task.updated_at)
    if updated is None:
        return False
    cutoff = get_current_utc_datetime() - timedelta(seconds=LEASE_SECONDS)
    return updated < cutoff


async def expire_stale_repair_task(session, task):
    """Mark a crashed worker as error without blocking the status poller."""
    if not _is_stale_pending(task):
        return task
    try:
        result = await session.execute(update(AsyncTaskModel).where(
            AsyncTaskModel.id == task.id,
            AsyncTaskModel.status == AsyncTaskStatus.PENDING,
            AsyncTaskModel.updated_at < get_current_utc_datetime() - timedelta(seconds=LEASE_SECONDS),
        ).execution_options(synchronize_session=False).values(
            status=AsyncTaskStatus.ERROR,
            message='补图任务已中断；已完成图片保留，可手动继续补图。',
        ))
        if result.rowcount:
            await session.commit()
            await session.refresh(task)
    except OperationalError:
        await session.rollback()
        LOGGER.warning(
            "Skip stale image-repair expiry because the worker still holds the row"
        )
    return task


def _run_id_sql(run_id):
    text = cast(AsyncTaskModel.data, String)
    compact = f'"run_id":"{run_id}"'
    spaced = f'"run_id": "{run_id}"'
    return or_(text.contains(compact), text.contains(spaced))


async def update_active_run(session, presentation_id, run_id, **values):
    """Update only this repair run. Avoid MySQL JSON path comparators that miss rows."""
    task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
    if (
        task is None
        or task.status != AsyncTaskStatus.PENDING
        or _task_run_id(task) != str(run_id)
    ):
        return 0
    values.setdefault('updated_at', get_current_utc_datetime())
    result = await session.execute(update(AsyncTaskModel).where(
        AsyncTaskModel.id == task.id,
        AsyncTaskModel.status == AsyncTaskStatus.PENDING,
        _run_id_sql(run_id),
    ).execution_options(synchronize_session=False).values(**values))
    return int(result.rowcount or 0)


async def read_status(session, presentation_id):
    presentation = await owned_presentation(session, presentation_id)
    task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
    # Expired workers are never restarted automatically: DMX may still bill the
    # original request. An explicit user retry claims a fresh run identifier.
    task = await expire_stale_repair_task(session, task)
    slides = await load_slides(session, presentation_id)
    slots = (
        []
        if presentation.image_policy == ImagePolicy.DISABLED
        else extract_asset_slots(slides, include_blocked=True)
    )
    payable = (
        []
        if presentation.image_policy == ImagePolicy.DISABLED
        else extract_asset_slots(slides)
    )
    payable_keys = {(item.slide_index, item.slot_name, item.prompt) for item in payable}
    missing = [dict(page=s.slide_index + 1, slot=s.slot_name) for s in slots]
    blocked = [
        dict(page=s.slide_index + 1, slot=s.slot_name)
        for s in slots
        if (s.slide_index, s.slot_name, s.prompt) not in payable_keys
    ]
    data = (task.data or {}) if task else {}
    status = str(task.status.value if hasattr(task.status, 'value') else task.status) if task else 'idle'
    message = task.message if task else ''
    if task and status == 'pending' and _is_stale_pending(task):
        status = 'error'
        message = '补图任务已中断；已完成图片保留，可手动继续补图。'
    elif status != 'pending' and blocked and not payable:
        pages = '、'.join(str(page) for page in dict.fromkeys(item['page'] for item in blocked))
        message = f'第 {pages} 页有图片未通过审核或质检，已停止重复生图以免重复扣费。可改画面说明后再试。'
    return dict(status=status, message=message, missing=missing, missing_count=len(missing),
                payable_count=len(payable), blocked_count=len(blocked),
                processed=data.get('processed', 0), total=data.get('total', 0),
                run_id=data.get('run_id'), stage=data.get('stage', 'idle'))


async def claim_repair(session, presentation_id):
    task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
    await expire_stale_repair_task(session, task)
    state = await read_status(session, presentation_id)
    if state['status'] == 'pending' or not state.get('payable_count'):
        return state, None
    slides = await load_slides(session, presentation_id)
    total = len(build_asset_plan(slides))  # validate semantics before a paid call
    run_id = uuid.uuid4().hex
    values = dict(status=AsyncTaskStatus.PENDING, message='正在准备补齐缺图', error=None,
                  data=dict(run_id=run_id, total=total, processed=0, stage='queued'),
                  updated_at=get_current_utc_datetime())
    existing = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
    if existing:
        result = await session.execute(update(AsyncTaskModel).where(
            AsyncTaskModel.id == existing.id, AsyncTaskModel.status != AsyncTaskStatus.PENDING,
        ).execution_options(synchronize_session=False).values(**values))
        claimed = bool(result.rowcount)
    else:
        session.add(AsyncTaskModel(id=task_id(presentation_id), owner_id=get_current_owner_id(), type=TASK_TYPE, **values))
        claimed = True
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        claimed = False
    session.expire_all()
    return await read_status(session, presentation_id), run_id if claimed else None


async def persist_repaired_slide(session, generated):
    """Merge completed image URLs into the latest slide without JSON compare-and-swap."""
    latest = await get_by_id_unscoped(session, SlideModel, generated.id)
    if latest is None or latest.presentation != generated.presentation:
        return
    merged = latest.model_copy(deep=True)
    changed = preserve_completed_images(generated, merged)
    marked = copy_repair_failure_marks(generated, merged)
    if not changed and not marked:
        return
    await session.execute(update(SlideModel).where(
        SlideModel.id == latest.id,
    ).values(content=merged.content, ui=merged.ui).execution_options(synchronize_session=False))


async def run_repair(presentation_id, run_id, owner_id, session_factory=None, image_service=None):
    from services.database import async_session_maker
    from services.image_generation_service import ImageGenerationService
    from services.asset_execution_service import process_presentation_assets
    from utils.asset_directory_utils import get_images_directory
    session_factory = session_factory or async_session_maker
    token = set_current_owner_id(owner_id)
    heartbeat = None
    processed = 0
    async def touch():
        while True:
            await asyncio.sleep(15)
            async with session_factory() as session:
                rowcount = await update_active_run(session, presentation_id, run_id)
                await session.commit()
                if not rowcount:
                    raise RuntimeError('补图任务已被中断')
    try:
        async with session_factory() as session:
            await owned_presentation(session, presentation_id)
            slides = [s.model_copy(deep=True) for s in await load_slides(session, presentation_id)]
        heartbeat = asyncio.create_task(touch())
        async def checkpoint(assets):
            async with session_factory() as session:
                # Serialize checkpoint with expiry/claim changes before attaching.
                rowcount = await update_active_run(session, presentation_id, run_id)
                if not rowcount:
                    raise RuntimeError('补图任务已中断，停止写入旧任务结果')
                session.add_all(assets)
                for slide in slides:
                    try:
                        await persist_repaired_slide(session, slide)
                    except Exception:
                        LOGGER.exception(
                            "Failed to persist repaired slide %s for presentation %s",
                            getattr(slide, 'id', None),
                            presentation_id,
                        )
                await session.commit()
        async def finished():
            nonlocal processed
            processed += 1
            async with session_factory() as session:
                task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
                data = {**(task.data or {}), 'processed': processed, 'stage': 'generating'}
                if not await update_active_run(
                    session,
                    presentation_id,
                    run_id,
                    data=data,
                    message=f'已处理 {processed}/{data["total"]} 个补图请求',
                ):
                    raise RuntimeError('补图任务已中断，停止写入旧任务进度')
                await session.commit()
        service = image_service or ImageGenerationService(get_images_directory())
        generation = asyncio.create_task(process_presentation_assets(
            service, slides, presentation_id=presentation_id,
            on_item_completed=checkpoint, on_item_finished=finished,
            quality_retries=0,
            skip_semantic_quality=True,
        ))
        done, _ = await asyncio.wait([generation, heartbeat], return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            generation.cancel()
            await asyncio.gather(generation, return_exceptions=True)
            await heartbeat
        await generation
        async with session_factory() as session:
            latest_slides = await load_slides(session, presentation_id)
            remaining = extract_asset_slots(latest_slides, include_blocked=True)
            payable = extract_asset_slots(latest_slides)
            if not remaining:
                message = '缺图已补齐，可继续编辑。'
            elif not payable:
                pages = '、'.join(str(index + 1) for index in dict.fromkeys(slot.slide_index for slot in remaining))
                message = f'第 {pages} 页有图片未通过审核或质检，已停止重复生图以免重复扣费。可改画面说明后再试。'
            else:
                message = f'仍有 {len(remaining)} 处缺图，已有内容已保存，可稍后继续补图。'
            await update_active_run(
                session,
                presentation_id,
                run_id,
                status=AsyncTaskStatus.COMPLETED if not remaining else AsyncTaskStatus.ERROR,
                message=message,
            )
            await session.commit()
    except Exception:
        LOGGER.exception("Missing-image repair failed: presentation_id=%s", presentation_id)
        async with session_factory() as session:
            await update_active_run(
                session,
                presentation_id,
                run_id,
                status=AsyncTaskStatus.ERROR,
                message='本次补图未完成，已完成图片保留，请查看缺图位置后继续。',
            )
            await session.commit()
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        reset_current_owner_id(token)
