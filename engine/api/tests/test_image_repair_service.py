import asyncio
import pytest
from datetime import timedelta

from PIL import Image
from unittest.mock import AsyncMock
from services import asset_execution_service
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from enums.async_task_status import AsyncTaskStatus
from models.image_policy import ImagePolicy
from models.sql.async_task import AsyncTaskModel
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.user import User  # noqa: F401 - register owner FK table
from services.image_repair_service import (
    claim_repair, load_slides, persist_repaired_slide, preserve_completed_images,
    read_status, run_repair, task_id, update_active_run,
)
from utils.datetime_utils import get_current_utc_datetime


class PassingQuality:
    async def validate(self, _image, _expectations):
        from services.asset_semantic_quality_service import AssetSemanticQualityResult
        return AssetSemanticQualityResult(passed=True)


@pytest.fixture(autouse=True)
def configured_test_quality(monkeypatch):
    monkeypatch.setenv('ASSET_SEMANTIC_QA_ENABLED', 'true')
    monkeypatch.setattr(asset_execution_service, 'build_default_asset_semantic_quality_service', PassingQuality)


def make_slide(deck_id, *, url=''):
    return SlideModel(
        presentation=deck_id, layout_group='classroom', layout='classroom_cover', index=0,
        content={
            'heading': {'title': '小种子的春天'},
            'scene': {'visual': {'image_prompt': '无字春天花园背景', 'image_url': url}},
            '__content_contract__': {'classroom_mapping_version': 1, 'classroom_role': 'cover-scene'},
        },
        ui={'components': [
            {'id': 'scene', 'elements': [{'type': 'image', 'name': 'visual', 'data': url,
                'decorative': False, 'asset_role': 'background', 'asset_mode': 'direct-background',
                'fit': 'cover', 'required': True, 'text_safe_area': 'right',
                'position': {'x': 0, 'y': 0}, 'size': {'width': 1280, 'height': 720}}]},
            {'id': 'heading', 'elements': [{'type': 'text', 'name': 'title',
                'runs': [{'text': '小种子的春天'}]}]},
        ]},
    )


async def database():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class FakeImageService:
    def __init__(self, output):
        self.output_directory = str(output.parent)
        self.output = output
        self.calls = 0
    async def generate_image(self, _prompt):
        self.calls += 1
        return ImageAsset(path=str(self.output), is_uploaded=False)
    def configured_model_name(self):
        return 'fake-dmx'


@pytest.mark.parametrize('outcome', ['success', 'qa_disabled', 'quality_failed', 'manual_image', 'changed_prompt', 'unconfigured'])
def test_single_replacement_keeps_original_until_validated_and_preserves_edits(tmp_path, monkeypatch, outcome):
    from services.asset_semantic_quality_service import AssetSemanticQualityResult
    monkeypatch.setenv('DISABLE_AUTH', 'true')
    monkeypatch.setenv('APP_DATA_DIRECTORY', str(tmp_path))
    monkeypatch.setenv('ALIYUN_OSS_ENABLED', 'false')
    monkeypatch.setattr(asset_execution_service, 'record_asset_generation_trace', AsyncMock())
    if outcome == 'qa_disabled':
        monkeypatch.delenv('ASSET_SEMANTIC_QA_ENABLED')
    if outcome == 'unconfigured':
        monkeypatch.setattr(asset_execution_service, 'build_default_asset_semantic_quality_service', lambda: None)
    output = tmp_path / 'new-image.png'
    Image.new('RGB', (1280, 720), 'green').save(output)
    class FailedQuality:
        async def validate(self, _image, _expectations):
            return AssetSemanticQualityResult(passed=False, subject_cropped=True, overall_reason='主体被截断')
    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='教研', n_slides=2,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck); await session.commit()
                original = make_slide(deck.id, url='/app_data/images/original.png')
                original.speaker_note = '老师完整讲稿'
                original.ui['components'][0]['elements'][0].update(asset_role='framed-image', asset_mode='composite-image')
                original.ui['components'][0]['elements'][0]['size'] = {'width': 1184, 'height': 216}
                missing = make_slide(deck.id); missing.index = 1
                session.add_all([original, missing]); await session.commit()
                deck_id, slide_id = deck.id, original.id
                before = original.model_copy(deep=True)
                state = await read_status(session, deck_id)
                target = state['replaceable'][0]
                request = dict(key=target['key'], expected_url=target['url'])
                _, run_id = await claim_repair(session, deck_id, request)
                _, duplicate = await claim_repair(session, deck_id, request)
                assert run_id and duplicate is None
                saved = await session.get(SlideModel, slide_id)
                assert saved.content['scene']['visual']['image_url'] == target['url']

            class ConcurrentEditsService(FakeImageService):
                async def generate_image(self, prompt):
                    async with sessions() as session:
                        saved = await session.get(SlideModel, slide_id)
                        edited = saved.model_copy(deep=True)
                        edited.content['heading']['title'] = '老师等待期间修改的标题'
                        if outcome == 'manual_image':
                            edited.ui['components'][0]['elements'][0]['data'] = '/app_data/images/manual.png'
                        if outcome == 'changed_prompt':
                            edited.content['scene']['visual']['image_prompt'] = '老师新指定的主题'
                        saved.content, saved.ui = edited.content, edited.ui
                        session.add(saved); await session.commit()
                    return await super().generate_image(prompt)
            provider = ConcurrentEditsService(output)
            await run_repair(deck_id, run_id, None, session_factory=sessions, image_service=provider,
                quality_service=FailedQuality() if outcome in ('quality_failed', 'qa_disabled') else None)
            async with sessions() as session:
                saved = await session.get(SlideModel, slide_id)
                state = await read_status(session, deck_id)
                assert provider.calls == (0 if outcome == 'unconfigured' else 1)
                assert state['missing_count'] == 1  # Other page was never generated.
                assert saved.speaker_note == before.speaker_note
                image = saved.ui['components'][0]['elements'][0]
                assert image['position'] == before.ui['components'][0]['elements'][0]['position']
                assert image['size'] == before.ui['components'][0]['elements'][0]['size']
                if outcome != 'unconfigured':
                    assert saved.content['heading']['title'] == '老师等待期间修改的标题'
                if outcome in ('success', 'qa_disabled'):
                    assert state['status'] == 'completed'
                    assert len(state['replacements']) == 1
                    assert image['fit'] == 'contain' and image['crop_scale'] == 1
                    assert saved.content['scene']['visual']['image_url'] != target['url']
                    # A late autosave retains the replacement, but keeps current copy/geometry.
                    stale = before.model_copy(deep=True)
                    stale.content['heading']['title'] = '新标题'
                    stale.ui['components'][0]['elements'][0]['position']['x'] = 99
                    preserve_completed_images(saved, stale)
                    assert stale.content['scene']['visual']['image_url'] == image['data']
                    assert stale.content['heading']['title'] == '新标题'
                    assert stale.ui['components'][0]['elements'][0]['position']['x'] == 99
                    # A client which has received the result is free to undo it.
                    acknowledged = saved.model_copy(deep=True)
                    acknowledged.content['scene']['visual']['image_url'] = target['url']
                    acknowledged.ui['components'][0]['elements'][0]['data'] = target['url']
                    preserve_completed_images(saved, acknowledged)
                    assert acknowledged.content['scene']['visual']['image_url'] == target['url']
                else:
                    assert state['status'] == 'error'
                    assert state['replacements'] == []
                    assert saved.content['scene']['visual']['image_url'] == target['url']
                    assert image['data'] == ('/app_data/images/manual.png' if outcome == 'manual_image' else target['url'])
                    if outcome == 'quality_failed':
                        assert '主体被截断' in state['message']
                    if outcome == 'unconfigured':
                        assert '未配置' in state['message']
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_claim_is_idempotent_and_expired_task_requires_explicit_retry(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', 'true')
    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='种子', n_slides=1,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck); await session.commit()
                session.add(make_slide(deck.id)); await session.commit()
                first, run_id = await claim_repair(session, deck.id)
                second, duplicate = await claim_repair(session, deck.id)
                assert run_id and duplicate is None
                assert first['status'] == second['status'] == 'pending'
                task = await session.get(AsyncTaskModel, task_id(deck.id))
                task.updated_at = get_current_utc_datetime() - timedelta(seconds=100)
                await session.commit()
                expired = await read_status(session, deck.id)
                assert expired['status'] == 'error'
                assert expired['missing_count'] == 1
                retried, retry_id = await claim_repair(session, deck.id)
                assert retry_id and retry_id != run_id and retried['status'] == 'pending'
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_old_repair_run_cannot_overwrite_a_newer_claim(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', 'true')

    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='种子', n_slides=1,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck); await session.commit()
                session.add(make_slide(deck.id)); await session.commit()
                _, old_run = await claim_repair(session, deck.id)
                task = await session.get(AsyncTaskModel, task_id(deck.id))
                task.updated_at = get_current_utc_datetime() - timedelta(seconds=100)
                await session.commit()
                _, new_run = await claim_repair(session, deck.id)
                changed = await update_active_run(session, deck.id, old_run, message='旧任务不应写入')
                await session.commit()
                current = await session.get(AsyncTaskModel, task_id(deck.id))
                assert new_run and old_run != new_run
                assert changed == 0
                assert current.message != '旧任务不应写入'
                assert (current.data or {}).get('run_id') == new_run
        finally:
            await engine.dispose()
    asyncio.run(run())
    monkeypatch.setenv('DISABLE_AUTH', 'true')

    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(
                    version=PresentationVersion.V2_STANDARD,
                    content='种子',
                    n_slides=1,
                    language='Chinese',
                    image_policy=ImagePolicy.DISABLED,
                )
                session.add(deck)
                await session.commit()
                session.add(make_slide(deck.id))
                await session.commit()

                state, run_id = await claim_repair(session, deck.id)

                assert state['missing_count'] == 0
                assert run_id is None
                assert await session.get(AsyncTaskModel, task_id(deck.id)) is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_completed_image_merge_preserves_teacher_copy_and_manual_replacement():
    import uuid
    deck_id = uuid.uuid4()
    generated = make_slide(deck_id, url='/app_data/images/generated.png')
    edited = make_slide(deck_id)
    edited.content['heading']['title'] = '老师修改后的完整标题'
    edited.ui['components'][1]['elements'][0]['runs'][0]['text'] = '老师修改后的完整标题'
    assert preserve_completed_images(generated, edited) == 1
    assert edited.content['heading']['title'] == '老师修改后的完整标题'
    assert edited.content['scene']['visual']['image_url'] == '/app_data/images/generated.png'
    assert edited.ui['components'][0]['elements'][0]['data'] == '/app_data/images/generated.png'

    manual = make_slide(deck_id)
    manual.ui['components'][0]['elements'][0]['data'] = '/app_data/images/teacher-choice.png'
    preserve_completed_images(generated, manual)
    assert manual.content['scene']['visual']['image_url'] == '/app_data/images/teacher-choice.png'


def test_persist_repaired_slide_writes_url_without_matching_json_bytes(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', 'true')

    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='种子', n_slides=1,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck)
                await session.commit()
                stored = make_slide(deck.id)
                session.add(stored)
                await session.commit()
                slide_id = stored.id
                presentation_id = stored.presentation
                generated = make_slide(deck.id, url='/app_data/images/generated.png')
                generated.id = slide_id
                generated.presentation = presentation_id
                await persist_repaired_slide(session, generated)
                await session.commit()
                session.expire_all()
                latest = await session.get(SlideModel, slide_id)
                assert latest.content['scene']['visual']['image_url'] == '/app_data/images/generated.png'
                assert latest.ui['components'][0]['elements'][0]['data'] == '/app_data/images/generated.png'
                assert latest.content['heading']['title'] == '小种子的春天'
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_explicit_retry_claims_previously_failed_slot(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', 'true')

    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='种子', n_slides=1,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck)
                await session.commit()
                stored = make_slide(deck.id)
                stored.content['scene']['visual']['__repair_failed_prompt__'] = '无字春天花园背景'
                stored.content['scene']['visual']['__repair_failed_reason__'] = '审核未通过'
                session.add(stored)
                await session.commit()
                slide_id = stored.id
                preview = await read_status(session, deck.id)
                assert preview['missing_count'] == 1
                assert '补齐缺图' in (preview['message'] or '')
                assert '审核' not in (preview['message'] or '')
                state, run_id = await claim_repair(session, deck.id)
                assert run_id
                assert state['status'] == 'pending'
                session.expire_all()
                latest = await session.get(SlideModel, slide_id)
                assert '__repair_failed_prompt__' not in (latest.content['scene']['visual'] or {})
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_repair_generates_only_missing_asset_and_persists_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', 'true')
    monkeypatch.setenv('APP_DATA_DIRECTORY', str(tmp_path / 'app-data'))
    monkeypatch.setattr(asset_execution_service, 'record_asset_generation_trace', AsyncMock())
    output = tmp_path / 'generated.png'
    Image.new('RGB', (1280, 720), '#dcefe5').save(output)
    async def run():
        engine, sessions = await database()
        try:
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='种子', n_slides=1,
                    language='Chinese', image_policy=ImagePolicy.STANDARD)
                session.add(deck); await session.commit(); deck_id = deck.id
                session.add(make_slide(deck_id)); await session.commit()
                _, run_id = await claim_repair(session, deck_id)
            service = FakeImageService(output)
            await run_repair(deck_id, run_id, None, session_factory=sessions, image_service=service)
            async with sessions() as session:
                state = await read_status(session, deck_id)
                slide = (await load_slides(session, deck_id))[0]
                assert state['status'] == 'completed'
                assert state['missing_count'] == 0
                assert service.calls == 1
                assert slide.content['heading']['title'] == '小种子的春天'
                assert slide.content['scene']['visual']['image_url']
                assert slide.ui['components'][0]['elements'][0]['data'] == slide.content['scene']['visual']['image_url']
        finally:
            await engine.dispose()
    asyncio.run(run())
