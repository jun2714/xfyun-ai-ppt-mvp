"""Real ORM cache + separate HTTP requests; never use the application database."""
import asyncio
import uuid
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select

from api.v1.async_tasks.router import API_V1_ASYNC_TASKS_ROUTER
from api.v1.auth.context import set_current_owner_id, reset_current_owner_id
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from models.sql.template_v2 import TemplateV2
from services.database import get_async_session
from services.owner_scope import attach_owner_to_session


def test_task_status_and_list_follow_each_request_owner(tmp_path):
    async def run():
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "owners.db"}')
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        owners = [uuid.uuid4(), uuid.uuid4()]
        ids = ['task-first-teacher', 'task-second-teacher']
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            for owner, task_id in zip(owners, ids):
                async with sessions() as session:
                    attach_owner_to_session(session, SimpleNamespace(user_id=owner, is_admin=False))
                    session.add(AsyncTaskModel(id=task_id, type='kindergarten.generate_complete',
                                              status=AsyncTaskStatus.PENDING))
                    session.add(TemplateV2(id=task_id, name='Private template'))
                    if owner == owners[0]:
                        session.add(TemplateV2(id='official', name='Shared template', is_default=True))
                    await session.commit()
            app = FastAPI()
            async def session_dependency(request: Request):
                owner = uuid.UUID(request.headers['x-test-owner'])
                async with sessions() as session:
                    attach_owner_to_session(session, SimpleNamespace(user_id=owner, is_admin=False))
                    yield session
            app.dependency_overrides[get_async_session] = session_dependency
            app.include_router(API_V1_ASYNC_TASKS_ROUTER)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                for index in [0, 1, 0, 1]:
                    headers = {'x-test-owner': str(owners[index])}
                    own = await client.get(f'/api/v1/async-tasks/status/{ids[index]}', headers=headers)
                    assert own.status_code == 200, own.text
                    foreign = await client.get(f'/api/v1/async-tasks/status/{ids[1-index]}', headers=headers)
                    assert foreign.status_code == 404
                    listing = await client.get('/api/v1/async-tasks', headers=headers)
                    assert [row['id'] for row in listing.json()] == [ids[index]]
            # Background workers bind ContextVars instead of request session info.
            for index in [1, 0]:
                token = set_current_owner_id(owners[index])
                try:
                    async with sessions() as session:
                        assert await session.get(AsyncTaskModel, ids[index]) is not None
                        assert await session.get(AsyncTaskModel, ids[1-index]) is None
                        visible = (await session.execute(select(TemplateV2))).scalars().all()
                        assert {row.id for row in visible} == {ids[index], 'official'}
                finally:
                    reset_current_owner_id(token)
        finally:
            await engine.dispose()
    asyncio.run(run())
