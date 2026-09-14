"""Exercise routing and preparation through real persisted template rows."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from api.v1.ppt.endpoints import kindergarten, presentation
from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.template_v2 import TemplateV2
from services.kindergarten_template_routing_service import resolve_kindergarten_template
from templates.education_variants import EDUCATION_VARIANTS, build_education_variant
from utils.llm_calls import generate_presentation_structure as structure_module
from utils.llm_calls import generate_slide_content as content_module


def lesson():
    slides = []
    for index in range(8):
        points = [f'发现{i}：观察叶子的变化。' for i in range(3)]
        assets = [dict(slot='scene', semantic_label='叶子观察', description='观察叶子的形状与颜色变化')]
        if index == 0:
            points = ['活动目标：观察变化并交流发现', '使用类型：课堂活动']
            assets = []
        elif index == 2:
            points = [f'证据{i}：' + '记录孩子原话和具体动作，再讨论支持策略。' * 2 + '保留原始证据。' for i in range(4)]
            assets = [dict(slot=str(i), semantic_label=f'观察证据{i}', description='保留本条记录对应的现场行为',
                           audience_text=point) for i, point in reversed(list(enumerate(points)))]
        slides.append(dict(slide_no=index + 1, slide_type='cover-scene' if index == 0 else 'image-observation',
                           teaching_goal='观察与交流', screen_content=dict(title=f'第{index + 1}页：观察变化', points=points),
                           teacher_note='结合图像引导观察，保留儿童原话。', assets=assets))
    return KindergartenLessonPlan.model_validate(dict(
        meta=dict(topic='植物观察案例', age_group='4-5岁', domain='science'),
        lesson_goals=['观察变化并交流发现'], lesson_arc=['观察', '交流', '回顾'], slides=slides,
    ))


@pytest.mark.parametrize('template_id', EDUCATION_VARIANTS)
def test_preparation_persists_eight_pages_and_roomier_bindings_without_another_llm(monkeypatch, template_id):
    monkeypatch.setattr(presentation.MEM0_PRESENTATION_MEMORY_SERVICE, 'store_generated_outlines', AsyncMock())
    def no_model(*args, **kwargs):
        raise AssertionError('Confirmed semantic pages must not make another paid text request')
    monkeypatch.setattr(structure_module, 'get_client', no_model)
    monkeypatch.setattr(content_module, 'get_client', no_model)

    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            plan = lesson()
            outline = plan.to_presentation_outline()
            before = outline.model_dump(mode='json')
            async with sessions() as session:
                session.add(build_education_variant(template_id))
                saved = PresentationModel(version=PresentationVersion.V2_STANDARD, content='植物观察案例',
                                          n_slides=8, language='Chinese', outlines=before)
                session.add(saved)
                await session.commit()
                saved_id = saved.id
                result = await presentation.prepare_presentation(saved_id, outline.slides, template_id,
                                                                  title='观察变化', sql_session=session)
                assert result.presentation_id == saved_id
            async with sessions() as session:
                saved = await session.get(PresentationModel, saved_id)
                assert saved.n_slides == 8
                assert saved.outlines == before
                assert len(saved.structure['slides']) == 8
                template = await session.get(TemplateV2, template_id)
                layout = presentation._build_template_structure_layout(template, saved.layout)
                selected_ids = []
                for index, selected in enumerate(saved.structure['slides']):
                    slide_layout = layout.slides[selected]
                    selected_ids.append(slide_layout.id)
                    content = await content_module.get_slide_content_from_type_and_outline(
                        slide_layout, outline.slides[index], 'Chinese')
                    ui = presentation._apply_template_content_to_ui(
                        copy.deepcopy(saved.layout['layouts'][selected]), content)
                    assert content['__content_contract__']['screen_points'] == outline.slides[index].content_contract.screen_points
                    assert content['__speaker_note__'] == outline.slides[index].content_contract.teacher_note
                    assert ui['id'] == slide_layout.id
                    if index == 2:
                        for i, point in enumerate(outline.slides[index].content_contract.screen_points):
                            assert content[f'card_{i}']['text'] == point
                            assert f'观察证据{i}' in content[f'card_{i}']['visual']['image_prompt']
                assert selected_ids[2].endswith('cards_roomy_4')
                # An overflowing edit is rejected before overwriting the saved deck.
                outline.slides[1].content = '标题\n' + '原文必须保留' * 100
                with pytest.raises(HTTPException) as error:
                    await presentation.prepare_presentation(saved_id, outline.slides, template_id, sql_session=session)
                assert error.value.status_code == 422
                await session.refresh(saved)
                assert saved.outlines == before
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_recommendation_uses_existing_default_rows_and_their_saved_geometry():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                nature = build_education_variant('classroom-nature')
                nature.assets['template_metadata']['auto_match'] = False
                story = build_education_variant('classroom-story')
                private = build_education_variant('training-case')
                private.is_default = False
                session.add_all([nature, story, private])
                await session.commit()
                payload = kindergarten.KindergartenPresentationCreateRequest(topic='植物观察案例', template='auto')
                pool = await kindergarten._available_auto_templates(payload, session)
                assert 'training-case' not in pool
                plan = lesson()
                result = SimpleNamespace(plan=plan)
                _, routing, _ = kindergarten._apply_visual_mode(payload, result, available_templates=pool)
                assert routing.template == 'classroom-story'
                # Removing the sole enabled row must not resurrect a code-built template.
                await session.delete(story)
                await session.commit()
                pool = await kindergarten._available_auto_templates(payload, session)
                _, routing, _ = kindergarten._apply_visual_mode(payload, result, available_templates=pool)
                assert routing.template == ''
                assert '手动选择' in routing.reason
                # Capacity checking must use the saved template, not its factory defaults.
                nature.assets = {**nature.assets, 'template_metadata': {'auto_match': True, 'audiences': ['child']}}
                updated_layouts = copy.deepcopy(nature.layouts)
                for layout in updated_layouts['layouts']:
                    for component in layout['components']:
                        for element in component['elements']:
                            if element['type'] == 'text' and not element.get('decorative'):
                                element['size']['height'] = 1
                nature.layouts = updated_layouts
                session.add(nature)
                await session.commit()
                session.expunge_all()
                pool = await kindergarten._available_auto_templates(payload, session)
                routing = resolve_kindergarten_template(plan, 'auto', available_templates=pool)
                assert '请先调整大纲' in routing.reason
        finally:
            await engine.dispose()
    asyncio.run(run())
