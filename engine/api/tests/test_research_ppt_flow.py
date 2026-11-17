"""Offline HTTP integration: real parent/child workers, SQLite, assets and repair.

Only the planning/model output and image provider are substitutes. Tests must
never contact a paid model or reuse the developer's application database.
"""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select

from api.v1.async_tasks.router import API_V1_ASYNC_TASKS_ROUTER
from api.v1.ppt.endpoints import kindergarten, presentation, image_repair
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.image_asset import ImageAsset
from models.sql.asset_generation_trace import AssetGenerationTrace
from services import database, prepared_deck_generation, image_generation_service


async def make_flow_app(monkeypatch, directory, *, fail_at=None, gated=False):
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('DISABLE_AUTH', 'true')  # This isolated test app only.
    monkeypatch.setenv('APP_DATA_DIRECTORY', str(directory))
    monkeypatch.setenv('ALIYUN_OSS_ENABLED', 'false')
    monkeypatch.setenv('ASSET_GENERATION_CONCURRENCY', '1')
    monkeypatch.delenv('ASSET_SEMANTIC_QA_ENABLED', raising=False)
    monkeypatch.setenv('ASSET_SEMANTIC_QA_PROVIDER', 'dmx')  # Legacy deployed setting.
    engine = create_async_engine(f'sqlite+aiosqlite:///{directory / "flow.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    for module in (database, kindergarten, prepared_deck_generation):
        monkeypatch.setattr(module, 'async_session_maker', sessions)
    state = dict(image_calls=0, planning_calls=0, failed=False, deck_ids=[], requests=[])
    gate = asyncio.Event()
    if not gated:
        gate.set()

    class Images:
        def __init__(self, *_):
            self.output_directory = str(directory)
            self.is_image_generation_disabled = False
        def configured_model_name(self):
            return 'local-test-image-provider'
        async def generate_image(self, prompt):
            await gate.wait()
            state['image_calls'] += 1
            if state['image_calls'] == fail_at and not state['failed']:
                state['failed'] = True
                raise TimeoutError('模拟图片服务超时')
            output = directory / f'image-{state["image_calls"]}.png'
            Image.new('RGB', (640, 360), '#b9e2d8').save(output)
            return ImageAsset(path=str(output), is_uploaded=False)

    monkeypatch.setattr(presentation, 'ImageGenerationService', Images)
    monkeypatch.setattr(image_generation_service, 'ImageGenerationService', Images)

    async def prepare(payload, _request, session):
        state['planning_calls'] += 1
        state['requests'].append(payload.model_dump(mode='json'))
        deck = PresentationModel(version=PresentationVersion.V2_STANDARD,
            title=payload.topic, content=payload.topic, n_slides=12, language='Chinese',
            image_policy=payload.image_policy, generation_mode='standard',
            theme={'kindergarten_generation': {'content_mode': 'training'}})
        session.add(deck)
        await session.commit()
        # Deterministic model output. All subsequent stream, image, checkpoint,
        # task, history and repair behavior is the production implementation.
        for index in range(12):
            session.add(SlideModel(presentation=deck.id, layout_group='qa', layout='scene', index=index,
                speaker_note=f'第 {index + 1} 页教师讲稿',
                content={'heading': {'title': f'观察与回应 · 第 {index + 1} 页'},
                         'scene': {'visual': {'image_prompt': f'教师沟通场景 {index + 1}'}},
                         '__content_contract__': {'classroom_mapping_version': 1, 'visual_audience': 'teacher'}},
                ui={'components': [
                    {'id': 'heading', 'elements': [{'type': 'text', 'name': 'title', 'runs': [{'text': f'观察与回应 · 第 {index + 1} 页'}]}]},
                    {'id': 'scene', 'elements': [{'type': 'image', 'name': 'visual', 'data': '',
                        'asset_role': 'framed-image', 'asset_mode': 'composite-image', 'fit': 'contain',
                        'position': {'x': 10, 'y': 80}, 'size': {'width': 640, 'height': 360}}]},
                ]}))
        await session.commit()
        state['deck_ids'].append(str(deck.id))
        return SimpleNamespace(presentation_id=deck.id, outline=SimpleNamespace(slides=[{}] * 12))

    monkeypatch.setattr(kindergarten, 'prepare_kindergarten_presentation', prepare)
    app = FastAPI()
    async def session_dependency():
        async with sessions() as session:
            yield session
    app.dependency_overrides[database.get_async_session] = session_dependency
    app.include_router(kindergarten.KINDERGARTEN_ROUTER, prefix='/api/v1/ppt')
    app.include_router(presentation.PRESENTATION_ROUTER, prefix='/api/v1/ppt')
    app.include_router(image_repair.IMAGE_REPAIR_ROUTER, prefix='/api/v1/ppt')
    app.include_router(API_V1_ASYNC_TASKS_ROUTER)
    return SimpleNamespace(app=app, state=state, gate=gate, sessions=sessions, engine=engine)


@pytest.mark.parametrize('fail_at', [None, 3])
def test_research_http_generation_reopen_and_repair(tmp_path, monkeypatch, fail_at):
    async def run():
        flow = await make_flow_app(monkeypatch, tmp_path, fail_at=fail_at)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=flow.app), base_url='http://test') as client:
                result = await asyncio.wait_for(client.post('/api/v1/ppt/kindergarten/presentation/generate-complete/async',
                    json={'topic': '家园共育有效沟通', 'age_group': '教师教研', 'content_mode': 'training', 'n_slides': 12}), 45)
                assert result.status_code == 200, result.text
                task_id = result.json()['id']
                status = (await client.get(f'/api/v1/async-tasks/status/{task_id}')).json()
                assert status['status'] == 'completed', status
                deck_id = status['data']['presentation_id']
                assert flow.state['image_calls'] == 12
                assert flow.state['planning_calls'] == 1
                deck = (await client.get(f'/api/v1/ppt/presentation/{deck_id}')).json()
                assert len(deck['slides']) == 12
                assert deck['generation_metadata']['research_task_id'] == task_id
                assert deck['generation_metadata']['deck_task_id'] != task_id
                texts = [slide['speaker_note'] for slide in deck['slides']]
                # Opening/reloading the editor is a replay, never a new image job.
                for _ in range(2):
                    replay = await client.get(f'/api/v1/ppt/presentation/stream/{deck_id}')
                    assert '"type": "complete"' in replay.text, replay.text
                assert flow.state['image_calls'] == 12
                repair_url = f'/api/v1/ppt/presentation/{deck_id}/image-repair'
                repair = (await client.get(repair_url)).json()
                assert repair['missing_count'] == (1 if fail_at else 0), repair
                if fail_at:
                    assert status['data']['stage'] == 'completed_with_warnings'
                    assert status['data']['missing_image_pages'] == [3]
                    response = await client.post(repair_url)
                    assert response.status_code == 200, response.text
                    repair = (await client.get(repair_url)).json()
                    assert repair['missing_count'] == 0 and repair['status'] == 'completed', repair
                    assert flow.state['image_calls'] == 13  # Only the failed image.
                deck_after = (await client.get(f'/api/v1/ppt/presentation/{deck_id}')).json()
                assert [slide['speaker_note'] for slide in deck_after['slides']] == texts
                assert all(slide['content']['scene']['visual'].get('image_url') for slide in deck_after['slides'])
                async with flow.sessions() as session:
                    traces = list(await session.scalars(select(AssetGenerationTrace)))
                    assert len(traces) == flow.state['image_calls']
                    assert all(trace.retry_of is None for trace in traces)
        finally:
            await flow.engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['planning', 'images'])
def test_cancelling_research_also_stops_its_image_worker(tmp_path, monkeypatch, phase):
    async def run():
        flow = await make_flow_app(monkeypatch, tmp_path, gated=True)
        if phase == 'planning':
            prepare = kindergarten.prepare_kindergarten_presentation
            async def slow_prepare(*args):
                result = await prepare(*args)
                await flow.gate.wait()
                return result
            monkeypatch.setattr(kindergarten, 'prepare_kindergarten_presentation', slow_prepare)
        request = None
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=flow.app), base_url='http://test') as client:
                request = asyncio.create_task(client.post('/api/v1/ppt/kindergarten/presentation/generate-complete/async',
                    json={'topic': '取消流程验证', 'age_group': '教师教研', 'content_mode': 'training', 'n_slides': 12}))
                async def wait_for_child():
                    while True:
                        rows = (await client.get('/api/v1/async-tasks')).json()
                        parent = next((row for row in rows if row['type'] == 'kindergarten.generate_complete'), None)
                        child = next((row for row in rows if row['type'] == 'ppt.generate_slides'), None)
                        if parent and (child or (phase == 'planning' and flow.state['deck_ids'])):
                            return parent, child
                        await asyncio.sleep(0.02)
                parent, child = await asyncio.wait_for(wait_for_child(), 10)
                response = await client.post(f'/api/v1/ppt/kindergarten/presentation/generate-complete/{parent["id"]}/cancel')
                assert response.status_code == 200
                flow.gate.set()
                await asyncio.wait_for(request, 15)
                if child:
                    for _ in range(50):
                        if not prepared_deck_generation.deck_job_running(child['data']['presentation_id']):
                            break
                        await asyncio.sleep(0.02)
                parent_after = (await client.get(f'/api/v1/async-tasks/status/{parent["id"]}')).json()
                assert parent_after['data']['stage'] == 'cancelled'
                if child:
                    child_after = (await client.get(f'/api/v1/async-tasks/status/{child["id"]}')).json()
                    assert child_after['data']['stage'] == 'cancelled', child_after
                assert flow.state['image_calls'] == 0
        finally:
            if request and not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
            await flow.engine.dispose()
    asyncio.run(run())
