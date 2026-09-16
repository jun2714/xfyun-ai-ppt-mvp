import asyncio
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
    claim_repair, load_slides, preserve_completed_images,
    read_status, run_repair, task_id,
)
from utils.datetime_utils import get_current_utc_datetime


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


def test_disabled_image_policy_never_offers_or_starts_repair(monkeypatch):
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
