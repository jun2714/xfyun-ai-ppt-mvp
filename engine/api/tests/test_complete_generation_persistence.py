import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select

from api.v1.ppt.endpoints import kindergarten as endpoint
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.async_task import AsyncTaskModel
from enums.async_task_status import AsyncTaskStatus
from models.image_policy import ImagePolicy


async def seed(session, *, missing=False, disabled=False, blank=False):
    deck = PresentationModel(version=PresentationVersion.V2_STANDARD, content='观察记录', n_slides=3,
                             language='Chinese', image_policy=ImagePolicy.DISABLED if disabled else ImagePolicy.STANDARD)
    session.add(deck)
    await session.commit()
    for i in range(3):
        session.add(SlideModel(presentation=deck.id, layout_group='test', layout='test', index=i,
                              content={'picture': {'image_prompt': '观察记录场景',
                                  'image_url': '' if missing and i == 1 else 'https://example.com/ready.png'}},
                              ui={'type': 'text', 'runs': [{'text': 'title' if blank and i == 1 else '教师观察记录'}]}))
    await session.commit()
    return deck.id


@pytest.mark.parametrize('missing,disabled,blank', [(True, False, False), (False, False, True),
                                                  (False, False, False), (True, True, False)])
def test_completion_checks_real_saved_copy_and_images(missing, disabled, blank):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                deck_id = await seed(session, missing=missing, disabled=disabled, blank=blank)
                if blank:
                    with pytest.raises(HTTPException):
                        await endpoint._require_persisted_visible_slides(session, deck_id, 3)
                else:
                    report = await endpoint._require_persisted_visible_slides(session, deck_id, 3)
                    assert report['visible_count'] == 3
                    if missing and not disabled:
                        assert report['missing_image_pages'] == [2]
                        assert '第 2 页' in report['warnings'][0]
                    else:
                        assert report['missing_image_pages'] == []
                assert len(list(await session.scalars(select(SlideModel)))) == 3
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_background_provider_error_keeps_saved_pages_and_does_not_replay(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                deck_id = await seed(session)
                task = AsyncTaskModel(type=endpoint.ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE, status=AsyncTaskStatus.PENDING)
                session.add(task)
                await session.commit()
                task_id = task.id
            prepare = AsyncMock(return_value=SimpleNamespace(presentation_id=deck_id, outline=SimpleNamespace(slides=[{}, {}, {}])))
            consume = AsyncMock(side_effect=HTTPException(status_code=504, detail='图片服务响应超时'))
            monkeypatch.setattr(endpoint, 'async_session_maker', sessions)
            monkeypatch.setattr(endpoint, 'prepare_kindergarten_presentation', prepare)
            monkeypatch.setattr(endpoint, '_consume_presentation_stream', consume)
            await endpoint._run_kindergarten_complete_task(task_id, {'topic': '教师观察记录', 'n_slides': 3})
            assert consume.await_count == 1 and prepare.await_count == 1
            async with sessions() as session:
                saved = await session.get(AsyncTaskModel, task_id)
                deck = await session.get(PresentationModel, deck_id)
                assert deck.theme['kindergarten_generation']['research_task_id'] == str(task_id)
                assert saved.status == AsyncTaskStatus.COMPLETED
                assert saved.data['stage'] == 'completed_with_warnings'
                assert saved.data['has_warnings'] is True
                assert '图片服务响应超时' in saved.data['warnings'][0]
                assert str(saved.data['presentation_id']) == str(deck_id)
                assert len(list(await session.scalars(select(SlideModel)))) == 3
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_background_quality_failure_keeps_review_link_without_generating_images(monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                deck = PresentationModel(version=PresentationVersion.V2_STANDARD,
                    content='海洋动物', n_slides=3, language='Chinese',
                    outlines={'slides': [{'content': '保存题目'}, {'content': '保存答案'}, {'content': '保存回顾'}]})
                task = AsyncTaskModel(type=endpoint.ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE,
                    status=AsyncTaskStatus.PENDING)
                session.add(deck)
                session.add(task)
                await session.commit()
                deck_id, task_id = deck.id, task.id
            detail = dict(code='KINDERGARTEN_PLAN_REVIEW_REQUIRED', message='第 2 页答案不一致',
                          presentation_id=str(deck_id), outline_path=f'/presentations/{deck_id}/outline',
                          quality={'passed': False, 'errors': [{'code': 'reveal-contract-mismatch'}]})
            prepare = AsyncMock(side_effect=HTTPException(status_code=422, detail=detail))
            consume = AsyncMock()
            monkeypatch.setattr(endpoint, 'async_session_maker', sessions)
            monkeypatch.setattr(endpoint, 'prepare_kindergarten_presentation', prepare)
            monkeypatch.setattr(endpoint, '_consume_presentation_stream', consume)
            await endpoint._run_kindergarten_complete_task(task_id, {'topic': '海洋动物', 'n_slides': 3})
            consume.assert_not_awaited()
            assert prepare.await_count == 1
            async with sessions() as session:
                saved = await session.get(AsyncTaskModel, task_id)
                assert saved.status == AsyncTaskStatus.ERROR
                assert saved.data['stage'] == 'review_required'
                assert saved.data['outline_path'] == detail['outline_path']
                assert saved.data['presentation_id'] == str(deck_id)
                assert not saved.data['quality']['passed']
                assert len((await session.get(PresentationModel, deck_id)).outlines['slides']) == 3
                assert not list(await session.scalars(select(SlideModel)))
        finally:
            await engine.dispose()
    asyncio.run(run())
