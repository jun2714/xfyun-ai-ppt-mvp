"""Explicit, durable missing-image repair. Never regenerate reviewed slide copy."""
import asyncio
import os
import logging
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import JSON, String, cast, literal, select, update
from sqlalchemy.exc import IntegrityError

from api.v1.auth.context import get_current_owner_id, set_current_owner_id, reset_current_owner_id
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.image_policy import ImagePolicy
from services.asset_planning_service import extract_asset_slots, build_asset_plan
from services.owner_scope import get_by_id_unscoped
from utils.datetime_utils import get_current_utc_datetime
from utils.dict_utils import get_dict_at_path

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
        _assign_url(target, slot, replacement or url)
        sync_image_ui(target, slot, replacement or url)
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


async def read_status(session, presentation_id):
    presentation = await owned_presentation(session, presentation_id)
    task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
    # Expired workers are never restarted automatically: DMX may still bill the
    # original request. An explicit user retry claims a fresh run identifier.
    if task and task.status == AsyncTaskStatus.PENDING:
        cutoff = get_current_utc_datetime() - timedelta(seconds=LEASE_SECONDS)
        result = await session.execute(update(AsyncTaskModel).where(
            AsyncTaskModel.id == task.id, AsyncTaskModel.status == AsyncTaskStatus.PENDING,
            AsyncTaskModel.updated_at < cutoff,
        ).execution_options(synchronize_session=False).values(status=AsyncTaskStatus.ERROR, message='补图任务已中断；已完成图片保留，可手动继续补图。'))
        if result.rowcount:
            await session.commit()
            await session.refresh(task)
    slides = await load_slides(session, presentation_id)
    slots = (
        []
        if presentation.image_policy == ImagePolicy.DISABLED
        else extract_asset_slots(slides)
    )
    missing = [dict(page=s.slide_index + 1, slot=s.slot_name) for s in slots]
    data = (task.data or {}) if task else {}
    return dict(status=str(task.status.value if hasattr(task.status, 'value') else task.status) if task else 'idle',
                message=task.message if task else '', missing=missing, missing_count=len(missing),
                processed=data.get('processed', 0), total=data.get('total', 0),
                run_id=data.get('run_id'), stage=data.get('stage', 'idle'))


async def claim_repair(session, presentation_id):
    state = await read_status(session, presentation_id)
    if state['status'] == 'pending' or not state['missing_count']:
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


def active_run(presentation_id, run_id):
    return (AsyncTaskModel.id == task_id(presentation_id),
            AsyncTaskModel.status == AsyncTaskStatus.PENDING,
            AsyncTaskModel.data['run_id'].as_string() == run_id)


async def persist_repaired_slide(session, generated):
    # Compare-and-swap both JSON columns. A teacher editing in another tab wins;
    # retry merges into their latest row rather than saving our old slide snapshot.
    for _ in range(4):
        session.expire_all()
        latest = await get_by_id_unscoped(session, SlideModel, generated.id)
        if latest is None or latest.presentation != generated.presentation:
            return
        merged = latest.model_copy(deep=True)
        if not preserve_completed_images(generated, merged):
            return
        result = await session.execute(update(SlideModel).where(
            SlideModel.id == latest.id,
            cast(SlideModel.content, String) == cast(literal(latest.content, type_=JSON), String),
            cast(SlideModel.ui, String) == cast(literal(latest.ui, type_=JSON), String),
        ).values(content=merged.content, ui=merged.ui).execution_options(synchronize_session=False))
        if result.rowcount:
            return
    raise RuntimeError('页面正在其他窗口编辑，已生成图片保存在素材中，请稍后检查缺图。')


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
                result = await session.execute(update(AsyncTaskModel).where(*active_run(presentation_id, run_id)).execution_options(synchronize_session=False).values(updated_at=get_current_utc_datetime()))
                await session.commit()
                if not result.rowcount:
                    raise RuntimeError('补图任务已被中断')
    try:
        async with session_factory() as session:
            await owned_presentation(session, presentation_id)
            slides = [s.model_copy(deep=True) for s in await load_slides(session, presentation_id)]
        heartbeat = asyncio.create_task(touch())
        async def checkpoint(assets):
            async with session_factory() as session:
                # Serialize checkpoint with expiry/claim changes before attaching.
                result = await session.execute(update(AsyncTaskModel).where(*active_run(presentation_id, run_id)).execution_options(synchronize_session=False).values(updated_at=get_current_utc_datetime()))
                if not result.rowcount:
                    raise RuntimeError('补图任务已中断，停止写入旧任务结果')
                session.add_all(assets)
                for slide in slides:
                    await persist_repaired_slide(session, slide)
                await session.commit()
        async def finished():
            nonlocal processed
            processed += 1
            async with session_factory() as session:
                task = await get_by_id_unscoped(session, AsyncTaskModel, task_id(presentation_id))
                data = {**(task.data or {}), 'processed': processed, 'stage': 'generating'}
                await session.execute(update(AsyncTaskModel).where(*active_run(presentation_id, run_id)).execution_options(synchronize_session=False).values(data=data, message=f'已处理 {processed}/{data["total"]} 个补图请求'))
                await session.commit()
        service = image_service or ImageGenerationService(get_images_directory())
        generation = asyncio.create_task(process_presentation_assets(service, slides, presentation_id=presentation_id,
                                         on_item_completed=checkpoint, on_item_finished=finished))
        done, _ = await asyncio.wait([generation, heartbeat], return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            generation.cancel()
            await asyncio.gather(generation, return_exceptions=True)
            await heartbeat
        await generation
        async with session_factory() as session:
            remaining = len(extract_asset_slots(await load_slides(session, presentation_id)))
            message = '缺图已补齐，可继续编辑。' if not remaining else f'仍有 {remaining} 处缺图，已有内容已保存，可稍后继续补图。'
            await session.execute(update(AsyncTaskModel).where(*active_run(presentation_id, run_id)).execution_options(synchronize_session=False).values(
                status=AsyncTaskStatus.COMPLETED if not remaining else AsyncTaskStatus.ERROR, message=message))
            await session.commit()
    except Exception:
        LOGGER.exception("Missing-image repair failed: presentation_id=%s", presentation_id)
        async with session_factory() as session:
            await session.execute(update(AsyncTaskModel).where(*active_run(presentation_id, run_id)).execution_options(synchronize_session=False).values(
                status=AsyncTaskStatus.ERROR, message='本次补图未完成，已完成图片保留，请查看缺图位置后继续。'))
            await session.commit()
    finally:
        if heartbeat:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        reset_current_owner_id(token)
